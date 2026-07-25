"""Round 5 combined trader.

Three sub-strategies run inside a single Trader.run() call:
  * PEBBLES basket (XS..XL) is quoted and taken jointly, since the five
    tiers move together and we prefer to keep their inventories aligned.
  * The 45 "poly-unit" assets each get an independent quote-and-fade loop.
  * The five SNACKPACK products are traded as a small mixed book: a
    chocolate/vanilla joint take, plus mean-reversion overlays on
    raspberry, strawberry and pistachio.
"""

import json
from typing import Dict, List, Optional, Tuple

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:  # backtester path
    from prosperity4bt.datamodel import Order, OrderDepth, TradingState


# ---------------------------------------------------------------------------
# Product universes
# ---------------------------------------------------------------------------

PEBBLE_TIERS = ("PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL")

_GALAXY = (
    "GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
    "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
    "GALAXY_SOUNDS_SOLAR_FLAMES",
)
_SLEEP = (
    "SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
    "SLEEP_POD_NYLON", "SLEEP_POD_COTTON",
)
_CHIPS = (
    "MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
    "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE",
)
_ROBOTS = (
    "ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
    "ROBOT_LAUNDRY", "ROBOT_IRONING",
)
_VISORS = (
    "UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
    "UV_VISOR_RED", "UV_VISOR_MAGENTA",
)
_TRANSLATORS = (
    "TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
    "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
    "TRANSLATOR_VOID_BLUE",
)
_PANELS = ("PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4")
_OXYGEN = (
    "OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
    "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC",
)

INDEPENDENT_ASSETS = (
    _GALAXY + _SLEEP + _CHIPS + _ROBOTS + _VISORS + _TRANSLATORS + _PANELS + _OXYGEN
)

# Snack pack symbols
SNK_CHOC = "SNACKPACK_CHOCOLATE"
SNK_VANI = "SNACKPACK_VANILLA"
SNK_PIST = "SNACKPACK_PISTACHIO"
SNK_STRW = "SNACKPACK_STRAWBERRY"
SNK_RASP = "SNACKPACK_RASPBERRY"
SNACK_UNIVERSE = (SNK_CHOC, SNK_VANI, SNK_PIST, SNK_STRW, SNK_RASP)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

MAX_POS = 10
INV_PENALTY = 0.1

# raspberry: slow EMA + wide threshold
LONG_EMA_SPAN = 4000
LONG_EMA_A = 2.0 / (LONG_EMA_SPAN + 1)
LONG_BAND = 140
RASP_MU0 = 10000.0

# strawberry/pistachio: fast EMA + tight threshold
SHORT_EMA_SPAN = 800
SHORT_EMA_A = 2.0 / (SHORT_EMA_SPAN + 1)
SHORT_BAND = 16
STRW_MU0 = 10300.0
PIST_MU0 = 9650.0


# ---------------------------------------------------------------------------
# Book helpers
# ---------------------------------------------------------------------------

def _thickest_level(levels: Dict[int, int]) -> Optional[int]:
    """Price of the level with the largest absolute volume ("wall")."""
    top_px, top_vol = None, -1
    for px, vol in levels.items():
        av = abs(vol)
        if av > top_vol:
            top_vol, top_px = av, px
    return top_px


def _wall_midpoint(od: OrderDepth, fallback: Optional[float]) -> Optional[float]:
    bid_wall = _thickest_level(od.buy_orders) if od.buy_orders else None
    ask_wall = _thickest_level(od.sell_orders) if od.sell_orders else None
    if bid_wall is not None and ask_wall is not None:
        return (bid_wall + ask_wall) / 2.0
    return fallback


def _round5_fair(od: OrderDepth, wall_mid: float) -> float:
    """Fair used everywhere: prefer an isolated price within 1 tick of the
    wall midpoint, else fall back to (wall_mid - 0.5)."""
    all_px = list(od.buy_orders.keys()) + list(od.sell_orders.keys())
    close = [p for p in all_px if abs(p - wall_mid) < 1]
    if len(close) == 1:
        return float(close[0])
    return wall_mid - 0.5


def _top_of_book(od: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
    top_bid = max(od.buy_orders) if od.buy_orders else None
    top_ask = min(od.sell_orders) if od.sell_orders else None
    return top_bid, top_ask


def _passive_quote(pos: int, top_bid: int, top_ask: int, fair: float
                   ) -> Tuple[int, int, int, int]:
    """One-tick-inside quote sizes, subject to fair-price sanity and pos limit."""
    bid_px = top_bid + 1
    bid_sz = MAX_POS - pos
    if bid_px >= fair or bid_sz <= 0:
        bid_sz = 0

    ask_px = top_ask - 1
    ask_sz = MAX_POS + pos
    if ask_px <= fair or ask_sz <= 0:
        ask_sz = 0
    return bid_px, bid_sz, ask_px, ask_sz


# ---------------------------------------------------------------------------
# PEBBLES: joint take + independent quotes
# ---------------------------------------------------------------------------

def _crossable_side(od: OrderDepth, fair: float
                    ) -> Tuple[int, int, Optional[int], Optional[int]]:
    """Returns (direction, size_available, top_bid, top_ask).

    direction = +1 if the top ask is below fair (we'd buy),
                -1 if the top bid is above fair (we'd sell),
                 0 otherwise.
    """
    tb, ta = _top_of_book(od)
    if tb is None or ta is None:
        return 0, 0, tb, ta
    if ta < fair:
        return +1, abs(od.sell_orders[ta]), tb, ta
    if tb > fair:
        return -1, abs(od.buy_orders[tb]), tb, ta
    return 0, 0, tb, ta


def _clamp(x: int, lo: int, hi: int) -> int:
    return lo if x < lo else hi if x > hi else x


def _joint_pebble_take(positions: Tuple[int, int, int, int, int],
                       size: int, direction: int) -> Tuple[int, int, int, int, int]:
    """Pick post-trade positions (a,b,c,d,e) that minimise
       sum_{i<5} (p_i - p_XL)^2 + INV_PENALTY * |p_XL|
    subject to each tier moving at most `size` in `direction`.

    We drive the XL leg first, then align the four smaller tiers to it as
    tightly as their per-tier limits allow. Returns per-tier deltas.
    """
    a0, b0, c0, d0, e0 = positions
    if direction == +1:
        bounds = [(p, min(p + size, MAX_POS)) for p in positions]
    elif direction == -1:
        bounds = [(max(p - size, -MAX_POS), p) for p in positions]
    else:
        return (0, 0, 0, 0, 0)

    (a_lo, a_hi), (b_lo, b_hi), (c_lo, c_hi), (d_lo, d_hi), (e_lo, e_hi) = bounds

    best_cost = None
    best_state = positions
    for e_new in range(e_lo, e_hi + 1):
        a_new = _clamp(e_new, a_lo, a_hi)
        b_new = _clamp(e_new, b_lo, b_hi)
        c_new = _clamp(e_new, c_lo, c_hi)
        d_new = _clamp(e_new, d_lo, d_hi)
        spread_sq = (
            (a_new - e_new) ** 2 + (b_new - e_new) ** 2
            + (c_new - e_new) ** 2 + (d_new - e_new) ** 2
        )
        cost = spread_sq + INV_PENALTY * abs(e_new)
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_state = (a_new, b_new, c_new, d_new, e_new)

    return tuple(new - old for new, old in zip(best_state, positions))


def _trade_pebbles(state: TradingState,
                   wall_cache: Dict[str, float]) -> Dict[str, List[Order]]:
    tiers_ctx = []  # list of dicts or None per tier
    for prod in PEBBLE_TIERS:
        od = state.order_depths.get(prod)
        pos = state.position.get(prod, 0)
        if od is None:
            tiers_ctx.append({"od": None, "pos": pos})
            continue
        wm = _wall_midpoint(od, wall_cache.get(prod))
        if wm is None:
            tiers_ctx.append({"od": od, "pos": pos})
            continue
        wall_cache[prod] = wm
        fair = _round5_fair(od, wm)
        direction, avail, tb, ta = _crossable_side(od, fair)
        tiers_ctx.append({
            "od": od, "pos": pos, "fair": fair,
            "dir": direction, "avail": avail,
            "tb": tb, "ta": ta,
        })

    orders: Dict[str, List[Order]] = {p: [] for p in PEBBLE_TIERS}

    fully_quoted = all(c.get("fair") is not None for c in tiers_ctx)

    # -- joint take: only if every tier's inner-cross agrees on a direction --
    if fully_quoted:
        d0 = tiers_ctx[0]["dir"]
        if d0 != 0 and all(c["dir"] == d0 for c in tiers_ctx):
            size = min(c["avail"] for c in tiers_ctx)
            positions = tuple(c["pos"] for c in tiers_ctx)
            if d0 == +1:
                size = min(size, *(MAX_POS - p for p in positions))
            else:
                size = min(size, *(MAX_POS + p for p in positions))
            if size > 0:
                deltas = _joint_pebble_take(positions, size, d0)
                for prod, ctx, delta in zip(PEBBLE_TIERS, tiers_ctx, deltas):
                    if delta > 0:
                        orders[prod].append(Order(prod, ctx["ta"], delta))
                    elif delta < 0:
                        orders[prod].append(Order(prod, ctx["tb"], delta))
                    ctx["pos"] += delta

    # -- passive quote each leg with post-take inventory --
    if fully_quoted:
        for prod, ctx in zip(PEBBLE_TIERS, tiers_ctx):
            bpx, bsz, apx, asz = _passive_quote(
                ctx["pos"], ctx["tb"], ctx["ta"], ctx["fair"])
            if bsz > 0:
                orders[prod].append(Order(prod, bpx, bsz))
            if asz > 0:
                orders[prod].append(Order(prod, apx, -asz))

    return {p: os for p, os in orders.items() if os}


# ---------------------------------------------------------------------------
# Independent single-asset market making (45 poly-unit products)
# ---------------------------------------------------------------------------

def _trade_independents(state: TradingState,
                        wall_cache: Dict[str, float]) -> Dict[str, List[Order]]:
    out: Dict[str, List[Order]] = {}

    for prod in INDEPENDENT_ASSETS:
        od = state.order_depths.get(prod)
        if od is None:
            continue
        wm = _wall_midpoint(od, wall_cache.get(prod))
        if wm is None:
            continue
        wall_cache[prod] = wm
        fair = _round5_fair(od, wm)

        pos = state.position.get(prod, 0)
        tb, ta = _top_of_book(od)
        legs: List[Order] = []

        # Take at fair to shed inventory toward zero.
        if pos > 0 and tb is not None and tb == fair:
            qty = min(pos, abs(od.buy_orders[tb]))
            if qty > 0:
                legs.append(Order(prod, tb, -qty))
                pos -= qty
        elif pos < 0 and ta is not None and ta == fair:
            qty = min(-pos, abs(od.sell_orders[ta]))
            if qty > 0:
                legs.append(Order(prod, ta, qty))
                pos += qty

        # Passive quoting.
        if tb is not None and ta is not None:
            bpx, bsz, apx, asz = _passive_quote(pos, tb, ta, fair)
            if bsz > 0:
                legs.append(Order(prod, bpx, bsz))
            if asz > 0:
                legs.append(Order(prod, apx, -asz))

        if legs:
            out[prod] = legs

    return out


# ---------------------------------------------------------------------------
# SNACKPACK book
# ---------------------------------------------------------------------------

def _inner_at_fair(od: OrderDepth, fair: float) -> Tuple[int, int]:
    """+1 if top ask == fair (buy), -1 if top bid == fair (sell), else 0."""
    if od.sell_orders:
        ta = min(od.sell_orders)
        if ta == fair:
            return +1, abs(od.sell_orders[ta])
    if od.buy_orders:
        tb = max(od.buy_orders)
        if tb == fair:
            return -1, abs(od.buy_orders[tb])
    return 0, 0


def _feasible_range(pos: int, size: int, direction: int):
    if direction == +1:
        return range(pos, min(pos + size, MAX_POS) + 1)
    if direction == -1:
        return range(max(pos - size, -MAX_POS), pos + 1)
    return (pos,)


def _joint_choco_vanilla(qC, qV, vC, vV, dC, dV):
    """Pair-trade choco/vanilla by minimising (nC - nV)^2 + penalty*(nC^2+nV^2)."""
    grid_c = list(_feasible_range(qC, vC, dC))
    grid_v = list(_feasible_range(qV, vV, dV))
    best_cost, best = None, (qC, qV)
    for nC in grid_c:
        for nV in grid_v:
            cost = (nC - nV) ** 2 + INV_PENALTY * (nC * nC + nV * nV)
            if best_cost is None or cost < best_cost:
                best_cost, best = cost, (nC, nV)
    return best[0] - qC, best[1] - qV


def _mr_strawberry(pos, size, direction, fair, mu):
    if fair > mu + SHORT_BAND and direction == -1:
        return -min(size, MAX_POS + pos)
    if direction == +1:
        return min(size, MAX_POS - pos)
    return 0


def _mr_pistachio(pos, size, direction, fair, mu):
    if fair < mu - SHORT_BAND and direction == +1:
        return min(size, MAX_POS - pos)
    if direction == -1:
        return -min(size, MAX_POS + pos)
    return 0


def _mr_raspberry(pos, size, direction, fair, mu):
    if fair > mu + LONG_BAND and direction == -1:
        return -min(size, MAX_POS + pos)
    if fair < mu - LONG_BAND and direction == +1:
        return min(size, MAX_POS - pos)
    return 0


def _trade_snacks(state: TradingState, wall_cache: Dict[str, float],
                  persistent: dict) -> Tuple[Dict[str, List[Order]], float, float, float]:
    mu_R = persistent.get("mu", RASP_MU0)
    mu_S = persistent.get("mu_S", STRW_MU0)
    mu_P = persistent.get("mu_P", PIST_MU0)

    frame: Dict[str, dict] = {}
    for prod in SNACK_UNIVERSE:
        od = state.order_depths.get(prod)
        if od is None:
            continue
        wm = _wall_midpoint(od, wall_cache.get(prod))
        if wm is None:
            continue
        wall_cache[prod] = wm
        fair = _round5_fair(od, wm)
        direction, size = _inner_at_fair(od, fair)
        tb, ta = _top_of_book(od)
        frame[prod] = {
            "od": od, "fair": fair, "dir": direction, "size": size,
            "tb": tb, "ta": ta, "pos": state.position.get(prod, 0),
        }

    # EMA updates
    if SNK_RASP in frame:
        mu_R = mu_R * (1 - LONG_EMA_A) + frame[SNK_RASP]["fair"] * LONG_EMA_A
    if SNK_STRW in frame:
        mu_S = mu_S * (1 - SHORT_EMA_A) + frame[SNK_STRW]["fair"] * SHORT_EMA_A
    if SNK_PIST in frame:
        mu_P = mu_P * (1 - SHORT_EMA_A) + frame[SNK_PIST]["fair"] * SHORT_EMA_A

    out: Dict[str, List[Order]] = {p: [] for p in SNACK_UNIVERSE}

    # Choco/Vanilla joint take
    if SNK_CHOC in frame and SNK_VANI in frame:
        fC, fV = frame[SNK_CHOC], frame[SNK_VANI]
        dC, dV = _joint_choco_vanilla(
            fC["pos"], fV["pos"], fC["size"], fV["size"], fC["dir"], fV["dir"],
        )
        if dC > 0:
            out[SNK_CHOC].append(Order(SNK_CHOC, fC["ta"], dC))
        elif dC < 0:
            out[SNK_CHOC].append(Order(SNK_CHOC, fC["tb"], dC))
        if dV > 0:
            out[SNK_VANI].append(Order(SNK_VANI, fV["ta"], dV))
        elif dV < 0:
            out[SNK_VANI].append(Order(SNK_VANI, fV["tb"], dV))
        fC["pos"] += dC
        fV["pos"] += dV

    # Mean-reversion overlays
    for prod, mu_val, fn in (
        (SNK_STRW, mu_S, _mr_strawberry),
        (SNK_PIST, mu_P, _mr_pistachio),
        (SNK_RASP, mu_R, _mr_raspberry),
    ):
        if prod not in frame:
            continue
        f = frame[prod]
        d = fn(f["pos"], f["size"], f["dir"], f["fair"], mu_val)
        if d > 0:
            out[prod].append(Order(prod, f["ta"], d))
            f["pos"] += d
        elif d < 0:
            out[prod].append(Order(prod, f["tb"], d))
            f["pos"] += d

    # Passive quotes for every snack we saw
    for prod, f in frame.items():
        if f["tb"] is None or f["ta"] is None:
            continue
        bpx, bsz, apx, asz = _passive_quote(f["pos"], f["tb"], f["ta"], f["fair"])
        if bsz > 0:
            out[prod].append(Order(prod, bpx, bsz))
        if asz > 0:
            out[prod].append(Order(prod, apx, -asz))

    return {p: o for p, o in out.items() if o}, mu_R, mu_S, mu_P


# ---------------------------------------------------------------------------
# Trader entry point
# ---------------------------------------------------------------------------

class Trader:
    def run(self, state: TradingState):
        try:
            persistent = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            persistent = {}
        wall_cache: Dict[str, float] = persistent.get("walls", {})

        result: Dict[str, List[Order]] = {}
        result.update(_trade_pebbles(state, wall_cache))
        result.update(_trade_independents(state, wall_cache))
        snacks, mu_R, mu_S, mu_P = _trade_snacks(state, wall_cache, persistent)
        result.update(snacks)

        next_state = json.dumps({
            "walls": wall_cache,
            "mu": mu_R, "mu_S": mu_S, "mu_P": mu_P,
        })
        return result, 0, next_state
