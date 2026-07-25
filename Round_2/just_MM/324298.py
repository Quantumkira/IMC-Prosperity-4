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

        # ──----------------------- ASH──────────────────────────────────
        if _OSMIUM in state.order_depths:
            osmium_order_depths  = state.order_depths[_OSMIUM]
            positions = positions.get(_OSMIUM, 0)


            ash_orders = self._osmium_orders(osmium_order_depths, positions, ctx, state)
            if ash_orders:
                orders[_OSMIUM] = ash_orders


        return orders, 0, _json.dumps(ctx)

    def _osmium_orders(self, osmium_order_depths, positions: int, ctx: dict, state: "TradingState") -> List[Order]:
        orders: List[Order] = []

        sorted_asks = sorted(osmium_order_depths.sell_orders.items())
        sorted_bids = sorted(osmium_order_depths.buy_orders.items(), reverse=True)

        best_bid = max(osmium_order_depths.buy_orders.keys())  if osmium_order_depths.buy_orders  else ctx["previous_best_bid"]
        best_ask = min(osmium_order_depths.sell_orders.keys()) if osmium_order_depths.sell_orders else ctx["previous_best_ask"]

        # Compute mid value
        if (best_ask - best_bid) >= 16: # so the spread is normal 
            mid = (best_bid + best_ask) / 2.0
        else:
            mid = ctx["previous_mid"]


        # ask and bid prices
        ask_price = best_ask - 1
        bid_price = best_bid + 1

        # ask and bid volumes
        ask_vol = sorted_asks[0][1] if sorted_asks else 0
        bid_vol = sorted_bids[0][1] if sorted_bids else 0                                                                                                                                                               


        orders.append(Order(_OSMIUM, int(ask_price), ask_vol))
        orders.append(Order(_OSMIUM, int(bid_price),  bid_vol))

        ## add information to the logger
        ## orders summited, market_trades, mid, best_bid and best_ask
        market_trades_this_tick = state.market_trades.get(_OSMIUM, [])                                                                                                                                                  
        print(f"[OSM] ts={state.timestamp} mid={mid} bid={best_bid} ask={best_ask}")                                                                                                                                                                                                                                                                                        
        print(f"[OSM] orders_submitted={[(o.price, o.quantity) for o in orders]}")                                                                                                                                  
        print(f"[OSM] market_trades={[(t.price, t.quantity, t.buyer, t.seller) for t in market_trades_this_tick]}")   

        # update data 
        ctx["previous_best_bid"] = best_bid
        ctx["previous_best_ask"] = best_ask
        ctx["previous_mid"] = mid

        return orders