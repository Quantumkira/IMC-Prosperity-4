"""
Round 3 Options Submission v5 — Prosperity 4 (Solvenar)
========================================================
Updated: Gamma Scalping Fixed (Passive Hedging + Spread Minimization)

Strategies:
1. Vol Surface MM — earn bid-ask spread, stay flat
2. IV Scalping — mean-revert per-strike IV deviations
3. Gamma Scalping — buy cheap options (IV << realized vol), profit from delta hedging
4. Cross-Strike Vol Arb — trade when IV spread between strikes diverges from smile
"""

import json
import math
import numpy as np
from math import log, sqrt, exp, pi
from statistics import NormalDist
from typing import Any
from datamodel import (
    Listing,
    Observation,
    Order,
    OrderDepth,
    ProsperityEncoder,
    Symbol,
    Trade,
    TradingState,
)


# ─────────────────────────── Logger ───────────────────────────
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


# ─────────────────────── Black-Scholes ────────────────────────
class BlackScholes:
    _norm = NormalDist()

    @staticmethod
    def call_price(S, K, T, sigma):
        if T <= 0 or sigma <= 0:
            return max(S - K, 0.0)
        d1 = (log(S / K) + 0.5 * sigma**2 * T) / (sigma * sqrt(T))
        d2 = d1 - sigma * sqrt(T)
        return S * BlackScholes._norm.cdf(d1) - K * BlackScholes._norm.cdf(d2)

    @staticmethod
    def delta(S, K, T, sigma):
        if T <= 0 or sigma <= 0:
            return 1.0 if S > K else 0.0
        d1 = (log(S / K) + 0.5 * sigma**2 * T) / (sigma * sqrt(T))
        return BlackScholes._norm.cdf(d1)

    @staticmethod
    def gamma(S, K, T, sigma):
        if T <= 0 or sigma <= 0:
            return 0.0
        d1 = (log(S / K) + 0.5 * sigma**2 * T) / (sigma * sqrt(T))
        return BlackScholes._norm.pdf(d1) / (S * sigma * sqrt(T))

    @staticmethod
    def vega(S, K, T, sigma):
        if T <= 0 or sigma <= 0:
            return 0.0
        d1 = (log(S / K) + 0.5 * sigma**2 * T) / (sigma * sqrt(T))
        return S * sqrt(T) * BlackScholes._norm.pdf(d1)

    @staticmethod
    def implied_vol(price, S, K, T, max_iter=50):
        intrinsic = max(S - K, 0.0)
        if price <= intrinsic + 0.01 or T <= 0 or S <= 0:
            return None
        sigma = sqrt(2 * pi / T) * price / S
        sigma = max(0.01, min(sigma, 2.0))
        for _ in range(max_iter):
            v = BlackScholes.vega(S, K, T, sigma)
            if v < 1e-12:
                break
            diff = BlackScholes.call_price(S, K, T, sigma) - price
            sigma -= diff / v
            sigma = max(0.01, min(sigma, 2.0))
        return sigma


# ─────────────────────────── Trader ───────────────────────────
class Trader:
    def __init__(self):
        self.voucher_strikes = [
            4000,
            4500,
            5000,
            5100,
            5200,
            5300,
            5400,
            5500,
            6000,
            6500,
        ]
        self.vouchers = [f"VEV_{k}" for k in self.voucher_strikes]
        self.underlying = "VELVETFRUIT_EXTRACT"

        self.underlying_limit = 200
        self.voucher_limit = 300

        self.days_left = 5

        # ── Rolling IV Smile ──
        self.max_moneyness = 0.8
        self.smile_alpha_c = 0.20  # fast tracking for ATM level (c drifts ~2% intraday)
        self.smile_alpha_ab = 0.05  # slow tracking for noisy curvature/skew
        self.smile_params = None
        self.smile_spread = {}  # per-strike IV spread tracking
        self.smile_ready = False

        # ── Strategy 1: Vol Surface MM ──
        self.mm_strikes = {5100, 5200}  # ITM/ATM strikes (OTM bleeds from vol drift)
        self.mm_quote_size = 3
        self.mm_max_inv = 15
        self.inv_skew_vol = 0.025  # lean very hard against inventory
        self.edge_required = 2

        # ── Strategy 2: IV Scalping ──
        self.iv_ema_alpha = 0.02
        self.iv_edge = 0.008
        self.regime_thr = 0.001
        self.scalp_size = 3
        self.scalp_max_inv = 40

        # ── Strategy 3: Gamma Scalping (LONG VOL) ──
        # Buy cheap options, hold them, profit from delta hedging.
        # NO profit-taking sells — all profit comes from the hedge.
        self.gamma_scalp_strikes = [5000, 5100, 5200, 5300, 5400, 5500]
        self.gamma_scalp_size = 2  # buy slowly: 2 per tick
        self.gamma_scalp_max_pos = 10  # position cap per strike
        self.gamma_iv_discount = 0.06  # RV - IV threshold (selective entry)
        self.gamma_buy_cooldown = 10  # only buy every N ticks
        self.gamma_last_buy_tick = {}  # per-strike cooldown tracker

        # ── Strategy 4: Cross-Strike Vol Arb ──
        self.arb_threshold = 0.005
        self.arb_size = 3
        self.arb_max_pos = 25

        # ── Delta hedging ──
        # Balance: hedge often enough to capture gamma, but not so often
        # that spread costs overwhelm the profit. VE spread ≈ 5 ticks.
        self.delta_tolerance = 20
        self.delta_hedge_target = 0

        # ── State ──
        self.underlying_prices = []
        self.prev_underlying = None
        self.realized_var = 0.0

        self.iv_ema = {v: None for v in self.vouchers}
        self.dev_ema = {v: 0.0 for v in self.vouchers}

        self.orders = {}
        self.ul_buy_orders = 0
        self.ul_sell_orders = 0
        self.prev_timestamp = None
        self.day_offset = 0

        self.voucher_buys_this_tick = {}
        self.voucher_sells_this_tick = {}

    def save_state(self):
        return json.dumps(
            {
                "up": self.underlying_prices[-200:],
                "pu": self.prev_underlying,
                "rv": self.realized_var,
                "ie": {k: v for k, v in self.iv_ema.items() if v is not None},
                "de": self.dev_ema,
                "pt": self.prev_timestamp,
                "do": self.day_offset,
                "sp": self.smile_params,
                "ss": self.smile_spread,
                "gb": self.gamma_last_buy_tick,
            }
        )

    def load_state(self, data_str):
        if not data_str or data_str == "SAMPLE" or data_str == "":
            return
        try:
            d = json.loads(data_str)
            self.underlying_prices = d.get("up", [])
            self.prev_underlying = d.get("pu", None)
            self.realized_var = d.get("rv", 0.0)
            ie = d.get("ie", {})
            for k, v in ie.items():
                if k in self.iv_ema:
                    self.iv_ema[k] = v
            de = d.get("de", {})
            for k, v in de.items():
                if k in self.dev_ema:
                    self.dev_ema[k] = v
            self.prev_timestamp = d.get("pt", None)
            self.day_offset = d.get("do", 0)
            sp = d.get("sp", None)
            if sp is not None:
                self.smile_params = sp
                self.smile_ready = True
            ss = d.get("ss", {})
            if ss:
                self.smile_spread = {int(k): v for k, v in ss.items()}
            gb = d.get("gb", {})
            if gb:
                self.gamma_last_buy_tick = gb
        except Exception:
            pass

    def get_pos(self, state, product):
        return state.position.get(product, 0)

    def get_mid(self, state, product):
        od = state.order_depths.get(product)
        if od is None:
            return None
        bids = od.buy_orders
        asks = od.sell_orders
        if bids and asks:
            return (max(bids.keys()) + min(asks.keys())) / 2.0
        return None

    def get_best_bid_ask(self, state, product):
        od = state.order_depths.get(product)
        if od is None:
            return None, None, None, None
        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
        bid_vol = od.buy_orders.get(best_bid, 0) if best_bid is not None else 0
        ask_vol = od.sell_orders.get(best_ask, 0) if best_ask is not None else 0
        return best_bid, bid_vol, best_ask, ask_vol

    def predict_iv(self, m, bid=False, strike=None):
        if self.smile_params is None:
            return 0.20
        p = self.smile_params
        mid_iv = p["a"] * m**2 + p["b"] * m + p["c"]
        if strike is not None and strike in self.smile_spread:
            half_spread = self.smile_spread[strike] / 2
        else:
            half_spread = 0.005  # default
        if bid:
            return mid_iv - half_spread
        else:
            return mid_iv + half_spread

    def is_tradeable(self, S, strike, T):
        if T <= 0 or S <= 0 or strike <= 0:
            return False
        m = log(S / strike) / sqrt(T)
        return abs(m) <= self.max_moneyness

    def fit_smile(self, state):
        S = self.spot
        if S is None:
            return

        T = self.get_tte(state.timestamp)
        if T < 0.5 / 365:
            return

        m_vals = []
        iv_vals = []
        for voucher in self.vouchers:
            strike = int(voucher.split("_")[-1])
            if not self.is_tradeable(S, strike, T):
                continue
            mid = self.get_mid(state, voucher)
            if mid is None:
                continue
            iv = BlackScholes.implied_vol(mid, S, strike, T)
            if iv is None or iv < 0.01 or iv > 1.5:
                continue
            m = log(S / strike) / sqrt(T)
            m_vals.append(m)
            iv_vals.append(iv)

        if len(m_vals) < 3:
            return

        m_arr = np.array(m_vals)
        iv_arr = np.array(iv_vals)
        V = np.column_stack([m_arr**2, m_arr, np.ones_like(m_arr)])
        try:
            coeffs, _, _, _ = np.linalg.lstsq(V, iv_arr, rcond=None)
        except Exception:
            return

        new_a, new_b, new_c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])

        if self.smile_params is None:
            self.smile_params = {"a": new_a, "b": new_b, "c": new_c}
        else:
            ac = self.smile_alpha_c
            aab = self.smile_alpha_ab
            self.smile_params["a"] = (1 - aab) * self.smile_params["a"] + aab * new_a
            self.smile_params["b"] = (1 - aab) * self.smile_params["b"] + aab * new_b
            self.smile_params["c"] = (1 - ac) * self.smile_params["c"] + ac * new_c

        self.smile_ready = True

        # Per-strike IV spread tracking
        for voucher in self.vouchers:
            strike = int(voucher.split("_")[-1])
            if not self.is_tradeable(S, strike, T):
                continue
            bb, _, ba, _ = self.get_best_bid_ask(state, voucher)
            if bb is not None and ba is not None and ba > bb:
                bid_iv = BlackScholes.implied_vol(bb, S, strike, T)
                ask_iv = BlackScholes.implied_vol(ba, S, strike, T)
                if bid_iv is not None and ask_iv is not None and ask_iv > bid_iv:
                    spread = ask_iv - bid_iv
                    alpha = self.smile_alpha_c
                    if strike in self.smile_spread:
                        self.smile_spread[strike] = (1 - alpha) * self.smile_spread[
                            strike
                        ] + alpha * spread
                    else:
                        self.smile_spread[strike] = spread

    def get_tte(self, timestamp):
        T = (self.days_left - self.day_offset - timestamp / 1_000_000) / 365.0
        return max(T, 0.0001)

    def send_order(self, product, price, qty):
        if qty == 0:
            return
        self.orders[product].append(Order(product, int(price), int(qty)))

    def voucher_buy_room(self, state, voucher, max_inv=None):
        if max_inv is None:
            max_inv = self.mm_max_inv
        pos = self.get_pos(state, voucher)
        sent = self.voucher_buys_this_tick.get(
            voucher, 0
        ) - self.voucher_sells_this_tick.get(voucher, 0)
        max_from_inv = max_inv - pos - sent
        max_from_limit = self.voucher_limit - pos - sent
        return max(0, min(max_from_inv, max_from_limit))

    def voucher_sell_room(self, state, voucher, max_inv=None):
        if max_inv is None:
            max_inv = self.mm_max_inv
        pos = self.get_pos(state, voucher)
        sent = self.voucher_buys_this_tick.get(
            voucher, 0
        ) - self.voucher_sells_this_tick.get(voucher, 0)
        max_from_inv = pos + sent + max_inv
        max_from_limit = pos + sent + self.voucher_limit
        return max(0, min(max_from_inv, max_from_limit))

    def record_voucher_order(self, voucher, qty):
        if qty > 0:
            self.voucher_buys_this_tick[voucher] = (
                self.voucher_buys_this_tick.get(voucher, 0) + qty
            )
        elif qty < 0:
            self.voucher_sells_this_tick[voucher] = self.voucher_sells_this_tick.get(
                voucher, 0
            ) + abs(qty)

    # ─────────────────── Underlying tracking ──────────────────
    def update_underlying(self, state):
        mid = self.get_mid(state, self.underlying)
        if mid is None:
            return

        if self.prev_timestamp is not None and state.timestamp < self.prev_timestamp:
            self.day_offset += 1

        self.prev_timestamp = state.timestamp
        self.underlying_prices.append(mid)
        self.underlying_prices = self.underlying_prices[-200:]
        self.prev_underlying = mid

    @property
    def spot(self):
        return self.underlying_prices[-1] if self.underlying_prices else None

    @property
    def realized_vol(self):
        """Smoothed windowed realized vol — uses last 200 prices for stability."""
        prices = self.underlying_prices
        if len(prices) < 50:
            return 0.0
        window = prices[-200:]
        log_rets = []
        for i in range(1, len(window)):
            if window[i - 1] > 0:
                log_rets.append(log(window[i] / window[i - 1]))
        if len(log_rets) < 30:
            return 0.0
        mean_r = sum(log_rets) / len(log_rets)
        var_r = sum((r - mean_r) ** 2 for r in log_rets) / (len(log_rets) - 1)
        annual_var = var_r * 10000 * 365
        return sqrt(max(annual_var, 0.0))

    # ─────────────────── STRATEGY 1: Vol Surface MM ───────────
    def strategy_vol_surface_mm(self, state):
        S = self.spot
        if S is None or not self.smile_ready:
            return

        # Warmup: need 200+ prices for smile to stabilize
        if len(self.underlying_prices) < 200:
            return

        T = self.get_tte(state.timestamp)
        if T < 0.5 / 365:
            return

        for voucher in self.vouchers:
            strike = int(voucher.split("_")[-1])
            if strike not in self.mm_strikes:
                continue
            if not self.is_tradeable(S, strike, T):
                continue
            m = log(S / strike) / sqrt(T)

            bid_iv = self.predict_iv(m, bid=True, strike=strike)
            ask_iv = self.predict_iv(m, bid=False, strike=strike)

            pos = self.get_pos(state, voucher)
            inv_norm = (
                max(-1.0, min(1.0, pos / self.mm_max_inv)) if self.mm_max_inv > 0 else 0
            )

            adj_bid_iv = bid_iv - self.inv_skew_vol * inv_norm
            adj_ask_iv = ask_iv + self.inv_skew_vol * inv_norm

            model_bid = BlackScholes.call_price(S, strike, T, adj_bid_iv)
            model_ask = BlackScholes.call_price(S, strike, T, adj_ask_iv)

            intrinsic = max(S - strike, 0.0)
            model_ask = max(model_ask, intrinsic + 0.5)

            bid_price = int(math.floor(model_bid))
            ask_price = int(math.ceil(model_ask))

            if bid_price >= ask_price:
                mid_p = (model_bid + model_ask) / 2
                bid_price = int(math.floor(mid_p)) - 1
                ask_price = int(math.ceil(mid_p)) + 1

            best_bid, best_bid_vol, best_ask, best_ask_vol = self.get_best_bid_ask(
                state, voucher
            )

            buy_room = self.voucher_buy_room(state, voucher)
            sell_room = self.voucher_sell_room(state, voucher)

            took_buy = False
            took_sell = False

            if (
                best_ask is not None
                and best_ask <= bid_price - self.edge_required
                and buy_room > 0
            ):
                take_qty = min(self.mm_quote_size, buy_room, abs(best_ask_vol))
                if take_qty > 0:
                    self.send_order(voucher, best_ask, take_qty)
                    self.record_voucher_order(voucher, take_qty)
                    took_buy = True

            if (
                best_bid is not None
                and best_bid >= ask_price + self.edge_required
                and sell_room > 0
            ):
                take_qty = min(self.mm_quote_size, sell_room, abs(best_bid_vol))
                if take_qty > 0:
                    self.send_order(voucher, best_bid, -take_qty)
                    self.record_voucher_order(voucher, -take_qty)
                    took_sell = True

            buy_room = self.voucher_buy_room(state, voucher)
            sell_room = self.voucher_sell_room(state, voucher)

            if not took_buy and buy_room > 0:
                q = min(self.mm_quote_size, buy_room)
                if q > 0:
                    self.send_order(voucher, bid_price, q)
                    self.record_voucher_order(voucher, q)

            if not took_sell and sell_room > 0:
                q = min(self.mm_quote_size, sell_room)
                if q > 0:
                    self.send_order(voucher, ask_price, -q)
                    self.record_voucher_order(voucher, -q)

    # ─────────────────── STRATEGY 2: IV Scalping ──────────────
    def strategy_iv_scalping(self, state):
        S = self.spot
        if S is None:
            return

        T = self.get_tte(state.timestamp)
        if T < 1.0 / 365:
            return

        scalp_strikes = {5100, 5200, 5300, 5400, 5500, 6000, 6500}

        for voucher in self.vouchers:
            strike = int(voucher.split("_")[-1])
            if strike not in scalp_strikes:
                continue
            if not self.is_tradeable(S, strike, T):
                continue

            mid = self.get_mid(state, voucher)
            if mid is None:
                continue

            market_iv = BlackScholes.implied_vol(mid, S, strike, T)
            if market_iv is None:
                continue

            alpha = self.iv_ema_alpha
            if self.iv_ema[voucher] is None:
                self.iv_ema[voucher] = market_iv
                self.dev_ema[voucher] = 0.0
                continue

            self.iv_ema[voucher] = (1 - alpha) * self.iv_ema[
                voucher
            ] + alpha * market_iv
            self.dev_ema[voucher] = (1 - alpha) * self.dev_ema[voucher] + alpha * abs(
                market_iv - self.iv_ema[voucher]
            )

            if self.dev_ema[voucher] < self.regime_thr:
                continue

            iv_diff = market_iv - self.iv_ema[voucher]
            best_bid, best_bid_vol, best_ask, best_ask_vol = self.get_best_bid_ask(
                state, voucher
            )

            if iv_diff > self.iv_edge:
                sell_room = self.voucher_sell_room(state, voucher, self.scalp_max_inv)
                sell_qty = min(self.scalp_size, sell_room)
                if sell_qty > 0 and best_bid is not None:
                    self.send_order(voucher, best_bid, -sell_qty)
                    self.record_voucher_order(voucher, -sell_qty)

            elif iv_diff < -self.iv_edge:
                buy_room = self.voucher_buy_room(state, voucher, self.scalp_max_inv)
                buy_qty = min(self.scalp_size, buy_room)
                if buy_qty > 0 and best_ask is not None:
                    self.send_order(voucher, best_ask, buy_qty)
                    self.record_voucher_order(voucher, buy_qty)

    # ─────────────────── STRATEGY 3: Gamma Scalping ───────────
    def strategy_gamma_scalping(self, state):
        """Buy cheap options and hold. Profit comes from delta hedging,
        NOT from selling options. No profit-taking — pure gamma capture."""
        S = self.spot
        if S is None or len(self.underlying_prices) < 100:
            return

        T = self.get_tte(state.timestamp)
        if T < 1.5 / 365:
            return

        rv = self.realized_vol
        if rv <= 0.10:
            return

        tick = state.timestamp

        for voucher in self.vouchers:
            strike = int(voucher.split("_")[-1])

            if strike not in self.gamma_scalp_strikes:
                continue

            pos = self.get_pos(state, voucher)
            if pos >= self.gamma_scalp_max_pos:
                continue

            # Cooldown: don't buy every tick
            last_buy = self.gamma_last_buy_tick.get(voucher, -999999)
            if tick - last_buy < self.gamma_buy_cooldown * 100:
                continue

            mid = self.get_mid(state, voucher)
            if mid is None:
                continue

            market_iv = BlackScholes.implied_vol(mid, S, strike, T)
            if market_iv is None:
                continue

            iv_discount = rv - market_iv

            # Only buy when RV significantly exceeds IV
            if iv_discount > self.gamma_iv_discount:
                buy_room = self.voucher_buy_room(
                    state, voucher, self.gamma_scalp_max_pos
                )
                buy_qty = min(self.gamma_scalp_size, buy_room)
                if buy_qty > 0:
                    best_ask = (
                        min(state.order_depths[voucher].sell_orders.keys())
                        if state.order_depths.get(voucher)
                        and state.order_depths[voucher].sell_orders
                        else None
                    )
                    if best_ask is not None:
                        self.send_order(voucher, best_ask, buy_qty)
                        self.record_voucher_order(voucher, buy_qty)
                        self.gamma_last_buy_tick[voucher] = tick

    # ─────────────────── STRATEGY 4: Cross-Strike Vol Arb ─────
    def strategy_cross_strike_arb(self, state):
        S = self.spot
        if S is None or not self.smile_ready:
            return

        T = self.get_tte(state.timestamp)
        if T < 1.0 / 365:
            return

        strike_ivs = {}
        strike_mids = {}
        for voucher in self.vouchers:
            strike = int(voucher.split("_")[-1])
            if not self.is_tradeable(S, strike, T):
                continue
            mid = self.get_mid(state, voucher)
            if mid is None:
                continue
            iv = BlackScholes.implied_vol(mid, S, strike, T)
            if iv is not None:
                strike_ivs[strike] = iv
                strike_mids[strike] = mid

        if len(strike_ivs) < 2:
            return

        sorted_strikes = sorted(strike_ivs.keys())
        for i in range(len(sorted_strikes)):
            for j in range(i + 1, len(sorted_strikes)):
                K1 = sorted_strikes[i]
                K2 = sorted_strikes[j]

                m1 = log(S / K1) / sqrt(T)
                m2 = log(S / K2) / sqrt(T)

                expected_iv1 = (
                    self.predict_iv(m1, bid=True) + self.predict_iv(m1, bid=False)
                ) / 2
                expected_iv2 = (
                    self.predict_iv(m2, bid=True) + self.predict_iv(m2, bid=False)
                ) / 2
                expected_spread = expected_iv1 - expected_iv2

                actual_spread = strike_ivs[K1] - strike_ivs[K2]
                mispricing = actual_spread - expected_spread

                v1 = f"VEV_{K1}"
                v2 = f"VEV_{K2}"

                if mispricing > self.arb_threshold:
                    sell_room = self.voucher_sell_room(state, v1, self.arb_max_pos)
                    buy_room = self.voucher_buy_room(state, v2, self.arb_max_pos)
                    qty = min(self.arb_size, sell_room, buy_room)
                    if qty > 0:
                        bb1, _, _, _ = self.get_best_bid_ask(state, v1)
                        _, _, ba2, _ = self.get_best_bid_ask(state, v2)
                        if bb1 is not None and ba2 is not None and bb1 > ba2:
                            self.send_order(v1, bb1, -qty)
                            self.record_voucher_order(v1, -qty)
                            self.send_order(v2, ba2, qty)
                            self.record_voucher_order(v2, qty)

                elif mispricing < -self.arb_threshold:
                    buy_room = self.voucher_buy_room(state, v1, self.arb_max_pos)
                    sell_room = self.voucher_sell_room(state, v2, self.arb_max_pos)
                    qty = min(self.arb_size, buy_room, sell_room)
                    if qty > 0:
                        _, _, ba1, _ = self.get_best_bid_ask(state, v1)
                        bb2, _, _, _ = self.get_best_bid_ask(state, v2)
                        if ba1 is not None and bb2 is not None:
                            self.send_order(v1, ba1, qty)
                            self.record_voucher_order(v1, qty)
                            self.send_order(v2, bb2, -qty)
                            self.record_voucher_order(v2, -qty)

    # ─────────────────── Delta Hedge (Aggressive for Gamma Scalping) ──────
    def delta_hedge_portfolio(self, state):
        """Hedge delta every tick by crossing the spread.
        This is where gamma scalping profit is captured:
        buy underlying when it drops, sell when it rises."""
        S = self.spot
        if S is None:
            return

        T = self.get_tte(state.timestamp)
        total_delta = 0.0

        for voucher in self.vouchers:
            strike = int(voucher.split("_")[-1])
            pos = self.get_pos(state, voucher)
            if pos == 0:
                continue

            # Use market IV for delta calculation (most accurate)
            mid = self.get_mid(state, voucher)
            if mid is not None:
                avg_iv = BlackScholes.implied_vol(mid, S, strike, T)
                if avg_iv is None:
                    avg_iv = 0.20
            else:
                m = log(S / strike) / sqrt(T) if T > 0 else 0
                if self.smile_ready:
                    avg_iv = (
                        self.predict_iv(m, bid=True) + self.predict_iv(m, bid=False)
                    ) / 2
                else:
                    avg_iv = 0.20
            d = BlackScholes.delta(S, strike, T, avg_iv)
            total_delta += d * pos

        ul_pos = self.get_pos(state, self.underlying)
        net_delta = total_delta + ul_pos

        if abs(net_delta) <= self.delta_tolerance:
            return

        hedge_qty = -round(net_delta - self.delta_hedge_target)
        if hedge_qty == 0:
            return

        best_bid, _, best_ask, _ = self.get_best_bid_ask(state, self.underlying)

        if hedge_qty > 0:
            if best_ask is None:
                return
            max_buy = self.underlying_limit - ul_pos - self.ul_buy_orders
            actual = min(hedge_qty, max_buy)
            if actual > 0:
                self.send_order(self.underlying, best_ask, actual)
                self.ul_buy_orders += actual
        else:
            if best_bid is None:
                return
            max_sell = ul_pos + self.underlying_limit - self.ul_sell_orders
            actual = min(abs(hedge_qty), max_sell)
            if actual > 0:
                self.send_order(self.underlying, best_bid, -actual)
                self.ul_sell_orders += actual

    # ─────────────────── Main entry point ─────────────────────
    def run(self, state: TradingState):
        self.load_state(state.traderData)

        self.orders = {p: [] for p in list(state.order_depths.keys())}
        self.ul_buy_orders = 0
        self.ul_sell_orders = 0
        self.voucher_buys_this_tick = {}
        self.voucher_sells_this_tick = {}

        if self.underlying not in state.order_depths:
            trader_data = self.save_state()
            logger.flush(state, self.orders, 0, trader_data)
            return self.orders, 0, trader_data

        self.update_underlying(state)

        if self.spot is not None:
            T = self.get_tte(state.timestamp)

            self.fit_smile(state)

            sp = self.smile_params
            sp_str = (
                f"a={sp['a']:.4f} b={sp['b']:.4f} c={sp['c']:.4f}" if sp else "none"
            )
            logger.print(
                f"t={state.timestamp} S={self.spot:.1f} T={T * 365:.2f}d RV={self.realized_vol:.4f} smile=[{sp_str}]"
            )

            self.strategy_vol_surface_mm(state)
            # self.strategy_gamma_scalping(state)

            self.delta_hedge_portfolio(state)

        trader_data = self.save_state()
        logger.flush(state, self.orders, 0, trader_data)
        return self.orders, 0, trader_data
