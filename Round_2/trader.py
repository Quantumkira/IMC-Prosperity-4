import json
import math
from datamodel import (
    OrderDepth,
    TradingState,
    Order,
    Symbol,
    Listing,
    Trade,
    Observation,
    ProsperityEncoder,
)
from typing import List, Dict, Any


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: dict[Symbol, list[Order]],
        conversions: int,
        trader_data: str,
    ) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(
                        state, self.truncate(state.traderData, max_item_length)
                    ),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(
        self, order_depths: dict[Symbol, OrderDepth]
    ) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            encoded_candidate = json.dumps(candidate)
            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"

POSITION_LIMITS = {
    OSMIUM: 80,
    PEPPER: 80,
}

# ── Osmium spread geometry ─────────────────────────────────────────────────
# The normal bid-ask spread for OSMIUM is always 16 pts.
# Any spread below this signals an inward spike on one side.
OSMIUM_NORMAL_SPREAD = 16

# ── Drift (OLS trend-following) parameters for IPR ────────────────────────
PEPPER_WINDOW_N = 50
PEPPER_T_ENTRY = 1.0
PEPPER_T_FULL = 2.0
PEPPER_T_EXIT = PEPPER_T_ENTRY / 2.0
PEPPER_STOP_MULT = 10.0
PEPPER_SIGNAL_M = 1

# OLS constants (precomputed for window_n)
_N = PEPPER_WINDOW_N
_SUM_T = _N * (_N - 1) / 2.0
_D = _N * _N * (_N * _N - 1) / 12.0
_SE_DEN = (_D / _N) ** 0.5
_T_FULL_SAFE = max(float(PEPPER_T_FULL), 1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Trader
# ─────────────────────────────────────────────────────────────────────────────


class Trader:
    def __init__(self):
        pass

    def bid(self):
        return 5000

    # ── Helpers ──────────────────────────────────────────────────────────────

    def get_best_bid_ask(self, order_depth: OrderDepth):
        best_bid = (
            max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
        )
        best_ask = (
            min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
        )
        return best_bid, best_ask

    def get_wall_mid(self, order_depth: OrderDepth):
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None
        bid_wall = min(order_depth.buy_orders.keys())
        ask_wall = max(order_depth.sell_orders.keys())
        return (bid_wall + ask_wall) / 2

    def get_filtered_mid(
        self, order_depth: OrderDepth, min_bid_vol: int = 15, min_ask_vol: int = 15
    ):
        best_bid, best_ask = self.get_best_bid_ask(order_depth)

        filtered_bids = [
            p for p, v in order_depth.buy_orders.items() if v >= min_bid_vol
        ]
        filtered_asks = [
            p for p, v in order_depth.sell_orders.items() if abs(v) >= min_ask_vol
        ]

        mm_bid = max(filtered_bids) if filtered_bids else best_bid
        mm_ask = min(filtered_asks) if filtered_asks else best_ask

        if mm_bid is not None and mm_ask is not None:
            return (mm_bid + mm_ask) / 2
        return None

    def osmium_orders(
        self, order_depth: OrderDepth, position: int, ctx: dict
    ) -> List[Order]:
        orders: List[Order] = []
        pos_limit = POSITION_LIMITS[OSMIUM]

        buy_volume = 0
        sell_volume = 0

        sorted_asks = sorted(order_depth.sell_orders.items())
        sorted_bids = sorted(order_depth.buy_orders.items(), reverse=True)

        # ── Stable mid (dynamic fair value) ──────────────────────────────
        # Retrieve the last clean OB references from ctx.
        prev_best_bid = ctx.get("osm_prev_bid", 10_000)
        prev_best_ask = ctx.get("osm_prev_ask", 10_000)

        # Fall back to stored values if one side is missing.
        best_bid = sorted_bids[0][0] if sorted_bids else prev_best_bid
        best_ask = sorted_asks[0][0] if sorted_asks else prev_best_ask
        spread   = best_ask - best_bid

        # stable_mid is only updated on clean ticks (spread == normal).
        # During a spike tick it stays frozen at the last clean value.
        stable_mid = ctx.get("osm_stable_mid", (prev_best_bid + prev_best_ask) / 2.0)
        if spread >= OSMIUM_NORMAL_SPREAD:
            stable_mid = (best_bid + best_ask) / 2.0
            ctx["osm_stable_mid"]  = stable_mid
            ctx["osm_prev_bid"]    = best_bid
            ctx["osm_prev_ask"]    = best_ask

        # Use stable_mid as fair value throughout this method.
        fair_value = stable_mid

        # ── 1. TAKING: sweep ALL levels below/above fair value ───────────
        for ask_price, ask_vol in sorted_asks:
            ask_vol = abs(ask_vol)
            if ask_price < fair_value:
                qty = min(ask_vol, pos_limit - position - buy_volume)
                if qty > 0:
                    orders.append(Order(OSMIUM, ask_price, qty))
                    buy_volume += qty
            elif ask_price == fair_value and position < 0:
                qty = min(ask_vol, abs(position + buy_volume))
                if qty > 0:
                    orders.append(Order(OSMIUM, ask_price, qty))
                    buy_volume += qty

        for bid_price, bid_vol in sorted_bids:
            if bid_price > fair_value:
                qty = min(bid_vol, pos_limit + position - sell_volume)
                if qty > 0:
                    orders.append(Order(OSMIUM, bid_price, -qty))
                    sell_volume += qty
            elif bid_price == fair_value and position > 0:
                qty = min(bid_vol, position - sell_volume)
                if qty > 0:
                    orders.append(Order(OSMIUM, bid_price, -qty))
                    sell_volume += qty

        # ── 2. MAKING: passive quotes with inventory skew ────────────────
        position_after_take = position + buy_volume - sell_volume

        best_bid, best_ask = self.get_best_bid_ask(order_depth)

        bid_price = fair_value - 2
        if best_bid is not None:
            for bp, bv in sorted_bids:
                if bp < fair_value - 1:
                    bid_price = bp + 1 if bv > 1 else bp
                    break
                elif bp < fair_value:
                    bid_price = bp
                    break

        ask_price = fair_value + 2
        if best_ask is not None:
            for ap, av in sorted_asks:
                av = abs(av)
                if ap > fair_value + 1:
                    ask_price = ap - 1 if av > 1 else ap
                    break
                elif ap > fair_value:
                    ask_price = ap
                    break

        if position_after_take > pos_limit * 0.5:
            ask_price = max(fair_value + 1, ask_price - 1)
            bid_price = min(bid_price, fair_value - 3)
        elif position_after_take < -pos_limit * 0.5:
            bid_price = min(fair_value - 1, bid_price + 1)
            ask_price = max(ask_price, fair_value + 3)

        remaining_buy = pos_limit - position - buy_volume
        if remaining_buy > 0:
            orders.append(Order(OSMIUM, int(bid_price), remaining_buy))

        remaining_sell = pos_limit + position - sell_volume
        if remaining_sell > 0:
            orders.append(Order(OSMIUM, int(ask_price), -remaining_sell))

        return orders

    # ── Strategy 2: INTARIAN_PEPPER_ROOT — OLS Drift / Trend-Following ──

    def pepper_orders(
        self, order_depth: OrderDepth, position: int, drift_state: dict
    ) -> List[Order]:
        orders: List[Order] = []
        lim = POSITION_LIMITS[PEPPER]

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        buf = drift_state.get("buf", [])
        hd = drift_state.get("hd", 0)
        cnt = drift_state.get("cnt", 0)
        sp = drift_state.get("sp", 0.0)
        stp = drift_state.get("stp", 0.0)
        epx = drift_state.get("epx", None)
        pts = drift_state.get("pts", -1)

        bb = max(order_depth.buy_orders)
        ba = min(order_depth.sell_orders)
        bv = float(order_depth.buy_orders[bb])
        av = abs(float(order_depth.sell_orders[ba]))
        tv = bv + av
        mid = (bb + ba) / 2.0
        micro = (ba * bv + bb * av) / tv if tv > 0 else mid

        ts = drift_state.get("ts", 0)
        if ts < pts - 1000:
            buf, hd, cnt, sp, stp, epx = [], 0, 0, 0.0, 0.0, None
        pts = ts

        N = PEPPER_WINDOW_N
        p = micro
        if cnt < N:
            buf = buf + [p]
            stp += cnt * p
            sp += p
            cnt += 1
        else:
            p_old = buf[hd]
            stp = stp - sp + p_old + (N - 1) * p
            sp = sp - p_old + p
            buf = list(buf)
            buf[hd] = p
            hd = (hd + 1) % N

        drift_state.update(
            buf=buf, hd=hd, cnt=cnt, sp=sp, stp=stp, epx=epx, pts=pts
        )

        if cnt < N:
            return orders

        beta = (N * stp - _SUM_T * sp) / _D
        icpt = (sp - beta * _SUM_T) / N

        ss = 0.0
        for j in range(N):
            r = buf[(hd + j) % N] - (beta * j + icpt)
            ss += r * r
        sig = (ss / N) ** 0.5

        t_stat = (beta / (sig / _SE_DEN)) if sig > 1e-9 else 0.0

        direction = (1 if beta > 0 else -1) * PEPPER_SIGNAL_M
        thresh = PEPPER_T_EXIT if position != 0 else PEPPER_T_ENTRY

        if abs(t_stat) < thresh:
            tgt = 0
        else:
            scl = min(abs(t_stat) / _T_FULL_SAFE, 1.0)
            tgt = int(direction * scl * lim)

        tgt = max(-lim, min(lim, tgt))

        if PEPPER_STOP_MULT > 0.0 and position != 0 and epx is not None and sig > 0:
            unreal = position * (mid - epx)
            if unreal < -PEPPER_STOP_MULT * sig * abs(position):
                tgt = 0

        delta = tgt - position
        if delta > 0:
            orders.append(Order(PEPPER, ba, delta))
            if position == 0:
                epx = float(ba)
        elif delta < 0:
            orders.append(Order(PEPPER, bb, delta))
            if tgt == 0:
                epx = None

        drift_state["epx"] = epx
        return orders

    # ── Main entry point ─────────────────────────────────────────────────────

    def run(self, state: TradingState):
        result = {}

        try:
            ctx = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            ctx = {}

        drift_state = ctx.setdefault("drift", {})

        if OSMIUM in state.order_depths:
            osmium_position = state.position.get(OSMIUM, 0)
            result[OSMIUM] = self.osmium_orders(
                state.order_depths[OSMIUM], osmium_position, ctx
            )

        if PEPPER in state.order_depths:
            pepper_position = state.position.get(PEPPER, 0)
            drift_state["ts"] = state.timestamp
            result[PEPPER] = self.pepper_orders(
                state.order_depths[PEPPER], pepper_position, drift_state
            )

        trader_data = json.dumps(ctx)
        conversions = 0
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data