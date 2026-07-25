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

OSMIUM_FAIR_VALUE = 10_006  # Fixed true price fallback
OSMIUM_ROLLING_WINDOW = 20  # Number of ticks for rolling mid average


# ─────────────────────────────────────────────────────────────────────────────
# Trader
# ─────────────────────────────────────────────────────────────────────────────


class Trader:
    def __init__(self):
        pass

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

        # Wall = furthest price level (deepest liquidity)
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

    def compute_osmium_fair_value(self, order_depth: OrderDepth, mid_history: List[float]) -> float:
        best_bid, best_ask = self.get_best_bid_ask(order_depth)
        if best_bid is not None and best_ask is not None:
            current_mid = (best_bid + best_ask) / 2
            mid_history.append(current_mid)
        # Trim to window size
        while len(mid_history) > OSMIUM_ROLLING_WINDOW:
            mid_history.pop(0)

        if mid_history:
            return sum(mid_history) / len(mid_history)
        return OSMIUM_FAIR_VALUE  # fallback

    def osmium_orders(self, order_depth: OrderDepth, position: int, mid_history: List[float]) -> List[Order]:
        orders: List[Order] = []
        fair_value = self.compute_osmium_fair_value(order_depth, mid_history)
        pos_limit = POSITION_LIMITS[OSMIUM]

        buy_volume = 0
        sell_volume = 0

        # Sorted order book
        sorted_asks = sorted(order_depth.sell_orders.items())  # ascending price
        sorted_bids = sorted(
            order_depth.buy_orders.items(), reverse=True
        )  # descending price

        # ── 1. TAKING: sweep ALL levels below/above fair value ───────────
        # Buy everything offered below fair value (all levels, not just best)
        for ask_price, ask_vol in sorted_asks:
            ask_vol = abs(ask_vol)
            if ask_price < fair_value:
                qty = min(ask_vol, pos_limit - position - buy_volume)
                if qty > 0:
                    orders.append(Order(OSMIUM, ask_price, qty))
                    buy_volume += qty
            elif ask_price == fair_value and position < 0:
                # Flatten negative inventory at fair value
                qty = min(ask_vol, abs(position + buy_volume))
                if qty > 0:
                    orders.append(Order(OSMIUM, ask_price, qty))
                    buy_volume += qty

        # Sell everything bid above fair value (all levels)
        for bid_price, bid_vol in sorted_bids:
            if bid_price > fair_value:
                qty = min(bid_vol, pos_limit + position - sell_volume)
                if qty > 0:
                    orders.append(Order(OSMIUM, bid_price, -qty))
                    sell_volume += qty
            elif bid_price == fair_value and position > 0:
                # Flatten positive inventory at fair value
                qty = min(bid_vol, position - sell_volume)
                if qty > 0:
                    orders.append(Order(OSMIUM, bid_price, -qty))
                    sell_volume += qty

        # ── 2. MAKING: passive quotes with inventory skew ────────────────
        position_after_take = position + buy_volume - sell_volume

        best_bid, best_ask = self.get_best_bid_ask(order_depth)

        # Overbid: place bid just above the best existing bid below fair value
        bid_price = fair_value - 2  # default
        if best_bid is not None:
            for bp, bv in sorted_bids:
                if bp < fair_value - 1:
                    bid_price = bp + 1 if bv > 1 else bp
                    break
                elif bp < fair_value:
                    bid_price = bp
                    break

        # Undercut: place ask just below the best existing ask above fair value
        ask_price = fair_value + 2  # default
        if best_ask is not None:
            for ap, av in sorted_asks:
                av = abs(av)
                if ap > fair_value + 1:
                    ask_price = ap - 1 if av > 1 else ap
                    break
                elif ap > fair_value:
                    ask_price = ap
                    break

        # Continuous linear inventory skew.
        # position_ratio: -1.0 (max short) to +1.0 (max long)
        # skew shifts BOTH quotes down when long, up when short,
        # so the unwinding side gets more attractive continuously.
        position_ratio = position_after_take / pos_limit
        max_skew = 4  # max ticks of skew at full inventory
        skew = round(position_ratio * max_skew)

        bid_price = bid_price - skew
        ask_price = ask_price - skew

        # Safety: never let bid cross above fair or ask cross below fair
        bid_price = min(bid_price, fair_value - 1)
        ask_price = max(ask_price, fair_value + 1)

        # Post remaining volume as passive quotes
        remaining_buy = pos_limit - position - buy_volume
        if remaining_buy > 0:
            orders.append(Order(OSMIUM, int(bid_price), remaining_buy))

        remaining_sell = pos_limit + position - sell_volume
        if remaining_sell > 0:
            orders.append(Order(OSMIUM, int(ask_price), -remaining_sell))

        return orders

    # ── Strategy 2: INTARIAN_PEPPER_ROOT — Dynamic Market Making ─────────

    def pepper_orders(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        pos_limit = POSITION_LIMITS[PEPPER]

        buy_volume = 0
        sell_volume = 0

        # Compute fair value using filtered mid (large quote filtering)
        fair_value = self.get_filtered_mid(order_depth, min_bid_vol=15, min_ask_vol=15)
        if fair_value is None:
            fair_value = self.get_wall_mid(order_depth)
        if fair_value is None:
            return orders  # no book, skip

        sorted_asks = sorted(order_depth.sell_orders.items())
        sorted_bids = sorted(order_depth.buy_orders.items(), reverse=True)

        best_bid, best_ask = self.get_best_bid_ask(order_depth)
        fair_value = best_ask + best_bid / 2
        if fair_value is None:
            fair_value = self.get_wall_mid(order_depth)
        if fair_value is None:
            return orders  # no book, skip
        # Compute current spread to detect adverse selection risk
        spread = (
            (best_ask - best_bid)
            if (best_bid is not None and best_ask is not None)
            else 999
        )

        # ── 1. TAKING: spread-aware, volume-filtered ─────────────────────

        # Dynamic take width: require more edge when spread is tight
        if spread <= 6:
            take_width = (
                2  # tight spread → higher edge required, avoid adverse selection
            )
        else:
            take_width = 1  # normal spread → standard edge

        for ask_price, ask_vol in sorted_asks:
            ask_vol = abs(ask_vol)
            if ask_price <= fair_value - take_width:
                # Only take small orders (<=15), large ones are market makers
                if ask_vol <= 15:
                    qty = min(ask_vol, pos_limit - position - buy_volume)
                    if qty > 0:
                        orders.append(Order(PEPPER, ask_price, qty))
                        buy_volume += qty

        for bid_price, bid_vol in sorted_bids:
            if bid_price >= fair_value + take_width:
                if bid_vol <= 15:
                    qty = min(bid_vol, pos_limit + position - sell_volume)
                    if qty > 0:
                        orders.append(Order(PEPPER, bid_price, -qty))
                        sell_volume += qty

        # ── 2. INVENTORY CLEARING ────────────────────────────────────────
        position_after_take = position + buy_volume - sell_volume
        fair_for_bid = math.floor(fair_value)
        fair_for_ask = math.ceil(fair_value)

        if position_after_take > 0:
            # Sell inventory: try at ceil(fair) first, then floor(fair)
            for clear_price in [fair_for_ask, fair_for_bid]:
                if clear_price in order_depth.buy_orders:
                    clear_qty = min(
                        order_depth.buy_orders[clear_price], position_after_take
                    )
                    sell_cap = pos_limit + position - sell_volume
                    qty = min(clear_qty, sell_cap)
                    if qty > 0:
                        orders.append(Order(PEPPER, clear_price, -qty))
                        sell_volume += qty
                        position_after_take -= qty

        elif position_after_take < 0:
            # Buy to flatten: try at floor(fair) first, then ceil(fair)
            for clear_price in [fair_for_bid, fair_for_ask]:
                if clear_price in order_depth.sell_orders:
                    clear_qty = min(
                        abs(order_depth.sell_orders[clear_price]),
                        abs(position_after_take),
                    )
                    buy_cap = pos_limit - position - buy_volume
                    qty = min(clear_qty, buy_cap)
                    if qty > 0:
                        orders.append(Order(PEPPER, clear_price, qty))
                        buy_volume += qty
                        position_after_take += qty

        # ── 3. MAKING: inventory-skewed passive quotes ───────────────────
        position_after_take = position + buy_volume - sell_volume

        asks_above = [p for p in order_depth.sell_orders if p > fair_value + 1]
        bids_below = [p for p in order_depth.buy_orders if p < fair_value - 1]

        bid_price = max(bids_below) + 1 if bids_below else math.floor(fair_value) - 1
        ask_price = min(asks_above) - 1 if asks_above else math.ceil(fair_value) + 1

        # Inventory skew: when holding large position, lean quotes to reduce it
        if position_after_take > pos_limit * 0.5:
            # Heavy long → more aggressive sell, less aggressive buy
            ask_price = max(math.ceil(fair_value), ask_price - 1)
            bid_price = min(bid_price, math.floor(fair_value) - 2)
        elif position_after_take < -pos_limit * 0.5:
            # Heavy short → more aggressive buy, less aggressive sell
            bid_price = min(math.floor(fair_value), bid_price + 1)
            ask_price = max(ask_price, math.ceil(fair_value) + 2)

        remaining_buy = pos_limit - (position + buy_volume)
        if remaining_buy > 0:
            orders.append(Order(PEPPER, int(bid_price), remaining_buy))

        remaining_sell = pos_limit + (position - sell_volume)
        if remaining_sell > 0:
            orders.append(Order(PEPPER, int(ask_price), -remaining_sell))

        return orders

    # ── Main entry point ─────────────────────────────────────────────────────

    def run(self, state: TradingState):
        result = {}

        # Restore persisted state
        stored = {}
        if state.traderData and state.traderData != "":
            try:
                stored = json.loads(state.traderData)
            except json.JSONDecodeError:
                stored = {}

        osmium_mid_history: List[float] = stored.get("osmium_mids", [])

        if OSMIUM in state.order_depths:
            osmium_position = state.position.get(OSMIUM, 0)
            result[OSMIUM] = self.osmium_orders(
                state.order_depths[OSMIUM], osmium_position, osmium_mid_history
            )
            # Log the bids and asks we are quoting
            for order in result[OSMIUM]:
                side = "BID" if order.quantity > 0 else "ASK"
                logger.print(f"ASH {side} {order.price} x {abs(order.quantity)}")

        if PEPPER in state.order_depths:
            pepper_position = state.position.get(PEPPER, 0)
            result[PEPPER] = self.pepper_orders(
                state.order_depths[PEPPER], pepper_position
            )

        # Persist state for next tick
        trader_data = json.dumps({"osmium_mids": osmium_mid_history})
        conversions = 0
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data