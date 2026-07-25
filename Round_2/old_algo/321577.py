"""
ASH_COATED_OSMIUM : failsafe cap + slow EMA drift guard 
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

# ── Trader ────────────────────────────────────────────────────────────────────
class Trader:
    def __init__(self):
        pass 

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
            osmium_order_depths  = state.order_depths[_OSMIUM]
            positions = positions.get(_OSMIUM, 0)

            best_bid = max(osmium_order_depths.buy_orders.keys())  if osmium_order_depths.buy_orders  else None
            best_ask = min(osmium_order_depths.sell_orders.keys()) if osmium_order_depths.sell_orders else None
            if best_bid is not None and best_ask is not None:
                mid      = (best_bid + best_ask) / 2.0
                ema_slow = (1.0 - _ALPHA_SLOW) * ema_slow + _ALPHA_SLOW * mid

            drift = ema_slow - _OSMIUM_ANCHOR
            if abs(drift) > _DRIFT_THRESHOLD:
                fv = int(round(_OSMIUM_ANCHOR + drift * _DRIFT_FOLLOW))
            else:
                fv = _OSMIUM_ANCHOR

            ash_orders = self._osmium_orders(osmium_order_depths, positions, fv)
            if ash_orders:
                orders[_OSMIUM] = ash_orders

            ## add information to the logger
            ## orders summited, market_trades, fv, best_bid and best_ask
            market_trades_this_tick = state.market_trades.get(_OSMIUM, [])                                                                                                                                                  
            print(f"[OSM] ts={state.timestamp} fv={fv} bid={best_bid} ask={best_ask}")                                                                                                                                      
            print(f"[OSM] drift={drift:.4f} ema_slow={ema_slow:.4f}")                                                                                                                                                       
            print(f"[OSM] orders_submitted={[(o.price, o.quantity) for o in ash_orders]}")                                                                                                                                  
            print(f"[OSM] market_trades={[(t.price, t.quantity, t.buyer, t.seller) for t in market_trades_this_tick]}")   


        ctx["ema_slow"] = ema_slow

        return orders, 0, _json.dumps(ctx)

    def _osmium_orders(self, osmium_order_depths, positions: int, fv: int) -> List[Order]:
        orders: List[Order] = []
        pos_limit  = _OSMIUM_LIMIT
        buy_volume = sell_volume = 0

        sorted_asks = sorted(osmium_order_depths.sell_orders.items())
        sorted_bids = sorted(osmium_order_depths.buy_orders.items(), reverse=True)

        # TAKER: sweep all levels with edge vs fv
        for ask_price, ask_vol in sorted_asks:
            ask_vol = abs(ask_vol)
            if ask_price < fv:
                qty = min(ask_vol, pos_limit - positions - buy_volume)
                if qty > 0:
                    orders.append(Order(_OSMIUM, ask_price, qty))
                    buy_volume += qty

        for bid_price, bid_vol in sorted_bids:
            if bid_price > fv:
                qty = min(bid_vol, pos_limit + positions - sell_volume)
                if qty > 0:
                    orders.append(Order(_OSMIUM, bid_price, -qty))
                    sell_volume += qty

        # MAKER: penny-bait, default = fv
        position_after_take = positions + buy_volume - sell_volume
        best_bid = max(osmium_order_depths.buy_orders.keys())  if osmium_order_depths.buy_orders  else None
        best_ask = min(osmium_order_depths.sell_orders.keys()) if osmium_order_depths.sell_orders else None

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

        remaining_buy  = pos_limit - positions - buy_volume
        remaining_sell = pos_limit + positions - sell_volume

        if remaining_buy  > 0:
            orders.append(Order(_OSMIUM, int(bid_price),  remaining_buy))
        if remaining_sell > 0:
            orders.append(Order(_OSMIUM, int(ask_price), -remaining_sell))

        return orders