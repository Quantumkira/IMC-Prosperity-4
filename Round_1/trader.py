"""
ASH_COATED_OSMIUM : failsafe cap + slow EMA drift guard (submission 193427)
INTARIAN_PEPPER_ROOT : OLS-drift trend-following with explicit Plateau Control
"""
from __future__ import annotations
from typing import TYPE_CHECKING, List
if TYPE_CHECKING:
    from datamodel import TradingState
from datamodel import Order
import json as _json

# ── ASH constants ─────────────────────────────────────────────────────────────
_OSMIUM          = 'ASH_COATED_OSMIUM'
_OSMIUM_ANCHOR   = 10_000
_OSMIUM_LIMIT    = 80

_ALPHA_SLOW      = 0.002   # ~1000-tick lookback
_DRIFT_THRESHOLD = 5       # only trust drift if EMA moves >5 pts from anchor
_DRIFT_FOLLOW    = 0.8     # incorporate 80% of confirmed drift into fv


# ── DriftStrategy (IPR) ───────────────────────────────────────────────────────
class DriftStrategy:
    def __init__(self, scope_name, product, window_n, t_entry, t_full, t_exit,
                 stop_mult, signal_m, limits):
        self.scope_name = scope_name
        self.product    = product
        self.window_n   = window_n
        self.t_entry    = t_entry
        self.t_full     = t_full
        self.t_exit     = t_exit      # EXPLICIT EXIT PARAMETER
        self.stop_mult  = stop_mult
        self.signal_m   = signal_m
        self.limits     = limits

        _N = window_n
        self._N           = _N
        self._sum_t       = _N * (_N - 1) / 2.0
        self._D           = _N * _N * (_N * _N - 1) / 12.0
        self._se_den      = (self._D / _N) ** 0.5
        self._t_full_safe = max(float(t_full), 1e-9)

    def run(self, state: "TradingState", ctx: dict, positions=None) -> list:
        _k = "_DF_" + self.scope_name
        _s = ctx.setdefault(_k, {})
        _N = self._N

        _buf  = _s.get("buf",  [])
        _hd   = _s.get("hd",   0)
        _cnt  = _s.get("cnt",  0)
        _sp   = _s.get("sp",   0.0)
        _stp  = _s.get("stp",  0.0)
        _epx  = _s.get("epx",  None)
        _pts  = _s.get("pts",  -1)

        _ts = state.timestamp
        if _ts < _pts - 1000:
            _buf = []; _hd = 0; _cnt = 0; _sp = 0.0; _stp = 0.0; _epx = None
        _pts = _ts

        _od = state.order_depths.get(self.product)
        if not _od or not _od.buy_orders or not _od.sell_orders:
            _s.update(buf=_buf, hd=_hd, cnt=_cnt, sp=_sp, stp=_stp, epx=_epx, pts=_pts)
            return []

        _bb = max(_od.buy_orders)
        _ba = min(_od.sell_orders)
        _bv = float(_od.buy_orders[_bb])
        _av = abs(float(_od.sell_orders[_ba]))
        _tv = _bv + _av
        _mid   = (_bb + _ba) / 2.0
        _micro = (_ba * _bv + _bb * _av) / _tv if _tv > 0 else _mid

        _p = _micro
        if _cnt < _N:
            _buf  = _buf + [_p]
            _stp += _cnt * _p
            _sp  += _p
            _cnt += 1
        else:
            _p_old = _buf[_hd]
            _stp   = _stp - _sp + _p_old + (_N - 1) * _p
            _sp    = _sp - _p_old + _p
            _buf   = list(_buf)
            _buf[_hd] = _p
            _hd    = (_hd + 1) % _N

        if _cnt < _N:
            _s.update(buf=_buf, hd=_hd, cnt=_cnt, sp=_sp, stp=_stp, epx=_epx, pts=_pts)
            return []

        _beta = (_N * _stp - self._sum_t * _sp) / self._D
        _icpt = (_sp - _beta * self._sum_t) / _N

        _ss = 0.0
        for _j in range(_N):
            _r   = _buf[(_hd + _j) % _N] - (_beta * _j + _icpt)
            _ss += _r * _r
        _sig = (_ss / _N) ** 0.5

        _t_stat = (_beta / (_sig / self._se_den)) if _sig > 1e-9 else 0.0

        _pos_map = positions if positions is not None else state.position
        _pos     = _pos_map.get(self.product, 0)
        _lim     = self.limits.get(self.product, 0)
        _dir     = (1 if _beta > 0 else -1) * self.signal_m

        # ── 3-STATE PLATEAU & EXIT LOGIC ──────────────────────────────────────
        
        if abs(_t_stat) >= self.t_entry:
            # STATE 1: Trend is Confirmed. Scale aggressively into the trend.
            _scl = min(abs(_t_stat) / self._t_full_safe, 1.0)
            _tgt = int(_dir * _scl * _lim)
            
        elif abs(_t_stat) <= self.t_exit:
            # STATE 2: Trend is Dead. (Only triggers if you set t_exit >= 0)
            _tgt = 0
            
        else:
            # STATE 3: The Plateau. (t-stat is between t_exit and t_entry)
            # We hold whatever our current position is until trend resumes or reverses.
            _tgt = _pos

        # ──────────────────────────────────────────────────────────────────────

        if   _tgt >  _lim: _tgt =  _lim
        elif _tgt < -_lim: _tgt = -_lim

        # Dynamic Stop Loss
        if self.stop_mult > 0.0 and _pos != 0 and _epx is not None and _sig > 0:
            _unreal = _pos * (_mid - _epx)
            if _unreal < -self.stop_mult * _sig * abs(_pos):
                _tgt = 0

        _orders = []
        _delta  = _tgt - _pos
        
        # Order Generation & Smart Reversal Entry-Price Tracking
        if _delta > 0:
            _orders.append(Order(self.product, _ba, _delta))
            if _pos <= 0 and _tgt > 0:      # Crossed 0 from Short to Long
                _epx = float(_ba)
            elif _tgt == 0:
                _epx = None
                
        elif _delta < 0:
            _orders.append(Order(self.product, _bb, _delta))
            if _pos >= 0 and _tgt < 0:      # Crossed 0 from Long to Short
                _epx = float(_bb)
            elif _tgt == 0:
                _epx = None

        _s.update(buf=_buf, hd=_hd, cnt=_cnt, sp=_sp, stp=_stp, epx=_epx, pts=_pts)
        return _orders


# ── Trader ────────────────────────────────────────────────────────────────────
class Trader:
    def __init__(self):
        self._ipr = DriftStrategy(
            scope_name='INTARIAN_PEPPER_ROOT',
            product='INTARIAN_PEPPER_ROOT',
            window_n=40,
            t_entry=2.0,
            t_full=3.0,
            t_exit=-1.0,        # <--- SET TO -1.0 TO NEVER EXIT ON PLATEAU!
            stop_mult=15.0,
            signal_m=1,
            limits={'INTARIAN_PEPPER_ROOT': 80},
        )

    def run(self, state: "TradingState") -> tuple:
        try:
            ctx: dict = _json.loads(state.traderData) if state.traderData else {}
        except Exception:
            ctx = {}

        orders: dict = {}
        positions: dict = dict(state.position)

        # ── ASH: failsafe cap + drift guard ──────────────────────────────────
        ema_slow = ctx.get("ema_slow", float(_OSMIUM_ANCHOR))
        if _OSMIUM in state.order_depths:
            od  = state.order_depths[_OSMIUM]
            pos = positions.get(_OSMIUM, 0)

            best_bid = max(od.buy_orders.keys())  if od.buy_orders  else None
            best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
            if best_bid is not None and best_ask is not None:
                mid      = (best_bid + best_ask) / 2.0
                ema_slow = (1.0 - _ALPHA_SLOW) * ema_slow + _ALPHA_SLOW * mid

            drift = ema_slow - _OSMIUM_ANCHOR
            if abs(drift) > _DRIFT_THRESHOLD:
                fv = int(round(_OSMIUM_ANCHOR + drift * _DRIFT_FOLLOW))
            else:
                fv = _OSMIUM_ANCHOR

            ash_orders = self._osmium_orders(od, pos, fv)
            if ash_orders:
                orders[_OSMIUM] = ash_orders
        ctx["ema_slow"] = ema_slow

        # ── IPR: drift ────────────────────────────────────────────────────────
        for o in self._ipr.run(state, ctx, positions):
            orders.setdefault(o.symbol, []).append(o)
            positions[o.symbol] = positions.get(o.symbol, 0) + o.quantity

        return orders, 0, _json.dumps(ctx)

    def _osmium_orders(self, order_depth, position: int, fv: int) -> List[Order]:
        orders: List[Order] = []
        pos_limit  = _OSMIUM_LIMIT
        buy_volume = sell_volume = 0

        sorted_asks = sorted(order_depth.sell_orders.items())
        sorted_bids = sorted(order_depth.buy_orders.items(), reverse=True)

        # TAKER: sweep all levels with edge vs fv
        for ask_price, ask_vol in sorted_asks:
            ask_vol = abs(ask_vol)
            if ask_price < fv:
                qty = min(ask_vol, pos_limit - position - buy_volume)
                if qty > 0:
                    orders.append(Order(_OSMIUM, ask_price, qty))
                    buy_volume += qty

        for bid_price, bid_vol in sorted_bids:
            if bid_price > fv:
                qty = min(bid_vol, pos_limit + position - sell_volume)
                if qty > 0:
                    orders.append(Order(_OSMIUM, bid_price, -qty))
                    sell_volume += qty

        # MAKER: penny-bait, default = fv
        position_after_take = position + buy_volume - sell_volume
        best_bid = max(order_depth.buy_orders.keys())  if order_depth.buy_orders  else None
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

        bid_price = fv
        if best_bid is not None:
            for bp, bv in sorted_bids:
                if bp < fv - 1:
                    bid_price = bp + 1 if bv > 1 else bp
                    break
                elif bp < fv:
                    bid_price = bp
                    break

        ask_price = fv
        if best_ask is not None:
            for ap, av in sorted_asks:
                av = abs(av)
                if ap > fv + 1:
                    ask_price = ap - 1 if av > 1 else ap
                    break
                elif ap > fv:
                    ask_price = ap
                    break

        # Inventory skew at 75%
        if position_after_take > pos_limit * 0.75:
            ask_price = max(fv + 1, ask_price - 1)
            bid_price = min(bid_price, fv - 3)
        elif position_after_take < -pos_limit * 0.75:
            bid_price = min(fv - 1, bid_price + 1)
            ask_price = max(ask_price, fv + 3)

        # Failsafe: guarantee 1-tick edge on every fill
        bid_price = min(bid_price, fv - 1)
        ask_price = max(ask_price, fv + 1)

        remaining_buy  = pos_limit - position - buy_volume
        remaining_sell = pos_limit + position - sell_volume

        if remaining_buy  > 0:
            orders.append(Order(_OSMIUM, int(bid_price),  remaining_buy))
        if remaining_sell > 0:
            orders.append(Order(_OSMIUM, int(ask_price), -remaining_sell))

        return orders