"""
Round 4 Trader — Prosperity 4
================================
Products: HYDROGEL_PACK, VELVETFRUIT_EXTRACT, VEV_* (10 option strikes)

Strategies (all derived from data analysis, zero carry-over from R3):

1. HYDROGEL_PACK  — "penny the MM"
   Mark 14 is a pure market maker posting at exactly mid±8.
   Mark 38 is a noise trader crossing at exactly mid±8.
   We penny Mark 14 at mid±7 so Mark 38 fills us first.
   Earn ~7 ticks per fill on both sides.

2. VELVETFRUIT_EXTRACT — "penny the MM + Mark 67 lean"
   Mark 01/22 are market makers. Mark 55 is the noise trader crossing.
   Mark 67 ONLY buys VFE (never sells) — 83% hit-rate for +~2 tick
   price move in next 500 timestamps. When Mark 67 is active, we pause
   our ask (lean long) so we don't give away cheap sells.

3. VEV options — aggressive sell when market bid > BS fair + 1.5
   Market prices options at IV≈0.22-0.23 vs our sigma=0.20, so market
   bid consistently exceeds our fair value. Passive quoting fails (MM has
   time-priority at same price). Instead we cross the bid as a taker
   whenever sell_edge = best_bid - fair ≥ 1.5. Guaranteed fills, positive
   expected value. Only strikes where BS delta < 0.50 (manageable hedge).
   Delta hedge via VFE position (VFE MM naturally provides hedge fills).
   TTE = (4 - day_offset - ts/1e6) / 252.  Guard: skip when TTE ≤ 2 days.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, List, Dict
if TYPE_CHECKING:
    from datamodel import TradingState
from datamodel import Order
import json as _json
from math import log, sqrt
from statistics import NormalDist

# ── Position limits ────────────────────────────────────────────────────────────
_HP_LIM  = 200
_VFE_LIM = 200
_VEV_LIM = 300

# ── HYDROGEL_PACK constants ───────────────────────────────────────────────────
_HP  = 'HYDROGEL_PACK'
_HP_PENNY     = 1     # penny the existing MM by this many ticks
_HP_SKEW_THR  = 0.55  # start reducing size at this fraction of limit (110/200)
_HP_STOP_THR  = 0.75  # hard reduce to 5-unit quotes at this fraction (150/200)

# ── VELVETFRUIT_EXTRACT constants ─────────────────────────────────────────────
_VFE = 'VELVETFRUIT_EXTRACT'
_M67 = 'Mark 67'
_M67_DECAY = 0.80      # EMA decay for Mark 67 activity score
_M67_THRESHOLD = 0.40  # score above which we pause asks

# ── VEV option constants ──────────────────────────────────────────────────────
_VEV_SIGMA     = 0.20           # constant IV (confirmed stable, std < 0.003)
_VEV_DAYS_INIT = 4              # days remaining at Round 4 start (TTE = 4)
_TDPY          = 252            # trading days per year
_VEV_DELTA_CAP = 0.45           # skip strikes where delta > this (tighter: excludes near-ATM)
_VEV_DEEP_OTM_K = 5800         # K >= this → sell-only (deep OTM, BS ≈ 0)
_VEV_QUOTE_SIZE = 15           # max contracts per VEV quote
_VEV_SKEW_THR  = 0.60          # start skewing VEV at this fraction of limit
_VEV_MIN_TTE   = 2.0 / 252     # stop quoting VEVs when < 2 trading days remain (gamma too high)

_ALL_VEV_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
_norm = NormalDist()


# ── BS helpers ────────────────────────────────────────────────────────────────
def _bs_call(S: float, K: int, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (log(S / K) + 0.5 * sigma**2 * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    return S * _norm.cdf(d1) - K * _norm.cdf(d2)


def _bs_delta(S: float, K: int, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0
    d1 = (log(S / K) + 0.5 * sigma**2 * T) / (sigma * sqrt(T))
    return _norm.cdf(d1)


def _get_mid(od) -> float | None:
    if od and od.buy_orders and od.sell_orders:
        return (max(od.buy_orders) + min(od.sell_orders)) / 2.0
    return None


# ── Trader ────────────────────────────────────────────────────────────────────
class Trader:

    def run(self, state: "TradingState") -> tuple:
        # ── Load state ────────────────────────────────────────────────────────
        try:
            ctx: dict = _json.loads(state.traderData) if state.traderData else {}
        except Exception:
            ctx = {}

        # ── Day-offset tracking (timestamp resets to 0 each new day) ─────────
        prev_ts  = ctx.get('pt', None)
        day_off  = ctx.get('do', 0)
        ts       = state.timestamp
        if prev_ts is not None and ts < prev_ts - 200:
            day_off += 1
        ctx['pt'] = ts
        ctx['do'] = day_off

        # ── Mark 67 activity score ─────────────────────────────────────────────
        m67_fired = any(
            t.buyer == _M67
            for t in state.market_trades.get(_VFE, [])
        )
        m67_score = ctx.get('m67', 0.0) * _M67_DECAY + (1.0 if m67_fired else 0.0)
        ctx['m67'] = m67_score
        m67_bullish = m67_score >= _M67_THRESHOLD

        # ── Current VFE spot (used for all BS pricing) ────────────────────────
        vfe_od  = state.order_depths.get(_VFE)
        vfe_mid = _get_mid(vfe_od)

        # ── Current TTE for VEV options ───────────────────────────────────────
        T_vev = max((_VEV_DAYS_INIT - day_off - ts / 1_000_000) / _TDPY, 1e-9)

        # ── Compute net VEV delta so VFE MM can serve as natural hedge ────────
        vev_net_delta = 0.0
        if vfe_mid:
            for K in _ALL_VEV_STRIKES:
                vev_pos = state.position.get(f'VEV_{K}', 0)
                if vev_pos:
                    vev_net_delta += vev_pos * _bs_delta(vfe_mid, K, T_vev, _VEV_SIGMA)
        hedge_target = int(-round(vev_net_delta))
        # Clamp: VFE limit governs the hedge
        hedge_target = max(-_VFE_LIM, min(_VFE_LIM, hedge_target))

        # ── Build orders ──────────────────────────────────────────────────────
        orders: Dict[str, List[Order]] = {}

        # 1. HYDROGEL_PACK
        hp_od  = state.order_depths.get(_HP)
        hp_pos = state.position.get(_HP, 0)
        if hp_od:
            hp_orders = self._hydrogel(hp_od, hp_pos)
            if hp_orders:
                orders[_HP] = hp_orders

        # 2. VELVETFRUIT_EXTRACT
        vfe_pos = state.position.get(_VFE, 0)
        if vfe_od:
            vfe_orders = self._velvetfruit(vfe_od, vfe_pos, m67_bullish, hedge_target)
            if vfe_orders:
                orders[_VFE] = vfe_orders

        # 3. VEV options
        if vfe_mid and T_vev > _VEV_MIN_TTE:
            for K in _ALL_VEV_STRIKES:
                sym    = f'VEV_{K}'
                vev_od = state.order_depths.get(sym)
                if not vev_od:
                    continue
                vev_pos = state.position.get(sym, 0)
                delta   = _bs_delta(vfe_mid, K, T_vev, _VEV_SIGMA)
                vev_ords = self._vev(vev_od, vev_pos, vfe_mid, K, T_vev, delta)
                if vev_ords:
                    orders[sym] = vev_ords

        return orders, 0, _json.dumps(ctx)

    # ── HYDROGEL_PACK strategy ─────────────────────────────────────────────────
    def _hydrogel(self, od, pos: int) -> List[Order]:
        if not od.buy_orders or not od.sell_orders:
            return []

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)

        # Penny the existing MM by 1 tick each side
        my_bid = best_bid + _HP_PENNY
        my_ask = best_ask - _HP_PENNY

        if my_bid >= my_ask:   # spread too thin to penny safely
            return []

        orders: List[Order] = []
        buy_room  = _HP_LIM - pos
        sell_room = _HP_LIM + pos

        # Aggressive take: sweep any ask/bid that crossed fair value (rare edge case)
        fv = (best_bid + best_ask) // 2
        sorted_asks = sorted(od.sell_orders.items())
        sorted_bids = sorted(od.buy_orders.items(), reverse=True)

        bought = sold = 0
        for apx, avol in sorted_asks:
            if apx < fv and buy_room - bought > 0:
                qty = min(abs(avol), buy_room - bought)
                orders.append(Order(_HP, apx, qty))
                bought += qty

        for bpx, bvol in sorted_bids:
            if bpx > fv and sell_room - sold > 0:
                qty = min(bvol, sell_room - sold)
                orders.append(Order(_HP, bpx, -qty))
                sold += qty

        # Inventory skew: two-tier reduction to limit directional exposure
        soft_thr = int(_HP_LIM * _HP_SKEW_THR)   # 110: reduce to 20
        hard_thr = int(_HP_LIM * _HP_STOP_THR)   # 150: reduce to 5
        buy_qty  = buy_room  - bought
        sell_qty = sell_room - sold

        if pos >  hard_thr:
            buy_qty  = min(buy_qty,  5)
        elif pos >  soft_thr:
            buy_qty  = min(buy_qty,  20)
        if pos < -hard_thr:
            sell_qty = min(sell_qty, 5)
        elif pos < -soft_thr:
            sell_qty = min(sell_qty, 20)

        if buy_qty > 0:
            orders.append(Order(_HP, my_bid, buy_qty))
        if sell_qty > 0:
            orders.append(Order(_HP, my_ask, -sell_qty))

        return orders

    # ── VELVETFRUIT_EXTRACT strategy ──────────────────────────────────────────
    def _velvetfruit(self, od, pos: int, m67_bullish: bool, hedge_target: int) -> List[Order]:
        if not od.buy_orders or not od.sell_orders:
            return []

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)

        orders: List[Order] = []
        buy_room  = _VFE_LIM - pos
        sell_room = _VFE_LIM + pos

        # Hard taker: only fire when significantly off hedge target (threshold=20)
        # This prevents constant micro-trading that eats into spread profits
        gap = hedge_target - pos
        _HARD_TAKE_THR = 20
        if gap > _HARD_TAKE_THR and buy_room > 0:
            qty = min(gap - _HARD_TAKE_THR, buy_room, abs(od.sell_orders.get(best_ask, 0)))
            if qty > 0:
                orders.append(Order(_VFE, best_ask, qty))
                buy_room  -= qty
                sell_room += qty
        elif gap < -_HARD_TAKE_THR and sell_room > 0:
            qty = min(-gap - _HARD_TAKE_THR, sell_room, od.buy_orders.get(best_bid, 0))
            if qty > 0:
                orders.append(Order(_VFE, best_bid, -qty))
                buy_room  += qty
                sell_room -= qty

        # Inventory skew
        skew_thr  = int(_VFE_LIM * 0.75)
        buy_size  = buy_room
        sell_size = sell_room

        if pos >  skew_thr:
            buy_size  = min(buy_size,  10)
        if pos < -skew_thr:
            sell_size = min(sell_size, 10)

        # Market make at current best bid/ask
        # Mark 67 active → pause asks (lean long; don't sell cheaply into expected upmove)
        if buy_size > 0:
            orders.append(Order(_VFE, best_bid, buy_size))

        if sell_size > 0 and not m67_bullish:
            orders.append(Order(_VFE, best_ask, -sell_size))

        return orders

    # ── VEV options strategy ──────────────────────────────────────────────────
    def _vev(self, od, pos: int, S: float, K: int, T: float, delta: float) -> List[Order]:
        # Skip high-delta strikes (hedge cost outweighs premium)
        if delta > _VEV_DELTA_CAP:
            return []

        if not od.buy_orders:
            return []

        best_bid = max(od.buy_orders)
        fair     = _bs_call(S, K, T, _VEV_SIGMA)

        # Aggressive sell: market is pricing options above our BS fair.
        # Rather than posting passively (tied with MM, no priority), we cross
        # the bid as a taker whenever there is meaningful positive edge.
        # This gives guaranteed fills vs zero fills with passive quoting.
        _VEV_MIN_SELL_EDGE = 1.5
        sell_edge = best_bid - fair

        if sell_edge < _VEV_MIN_SELL_EDGE or pos <= -_VEV_LIM:
            return []

        # Scale size with edge: larger edge → larger sell; cap at quote size
        sell_room = _VEV_LIM + pos
        skew_thr  = int(_VEV_LIM * _VEV_SKEW_THR)
        sell_qty  = min(_VEV_QUOTE_SIZE, sell_room)
        if pos < -skew_thr:
            sell_qty = min(sell_qty, 5)

        if sell_qty <= 0:
            return []

        return [Order(f'VEV_{K}', best_bid, -sell_qty)]
