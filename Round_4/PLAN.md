# Round 4 Algo Strategy — Living Plan

**Last updated:** Session 1
**Status:** Awaiting data capsule

---

## Products

| Product | Limit | Notes |
|---------|-------|-------|
| HYDROGEL_PACK | 200 | Same as R3; microstructure TBD |
| VELVETFRUIT_EXTRACT | 200 | Underlying for VEVs; microstructure TBD |
| VEV_4000..VEV_6500 | 300 each | 10 call options, TTE=7 days from day 1, need BS pricing |

**New in R4:** `buyer`/`seller` fields now populated in trade history. Counterparties are named "Mark N".

---

## Analysis Checklist

### Phase 1 — Structural Analysis (per product)
- [ ] Plot price series across all days
- [ ] Compute autocorrelation of mid-price returns (AC1 near -0.5 = mean-revert, near +0.5 = trend)
- [ ] Spread distribution (mean, p50, p95)
- [ ] Order book imbalance (OBI) signal
- [ ] Classify each product: mean-reverting / trending / other

### Phase 2 — VEV Options Analysis
- [ ] Fit implied volatility per strike per day
- [ ] Build vol smile / surface
- [ ] Compare IV to realized vol of VELVETFRUIT_EXTRACT
- [ ] Identify mispriced strikes (IV << or >> realized vol)

### Phase 3 — Counterparty Analysis
- [ ] Enumerate unique counterparties ("Marks")
- [ ] Per Mark: buy/sell ratio, average trade size, trade timing, price quality
- [ ] Identify: informed Marks (directional, trade before moves), noise Marks (random), MM Marks (both sides)
- [ ] Signal: does trading after a specific Mark predict price direction?
- [ ] Strategy: if a Mark consistently crosses the spread at bad prices, be their counterparty

### Phase 4 — Cross-Product Relationships
- [ ] Does HYDROGEL_PACK correlate with VELVETFRUIT_EXTRACT?
- [ ] Is there a spread/ratio trade between them?
- [ ] Do VEV prices lead or lag the underlying?

### Phase 5 — Parameter Optimization
- [ ] For MM products: sweep (take_edge, skew_threshold, skew_ticks)
- [ ] For trend products: sweep (window_n, t_entry, t_full, t_exit)
- [ ] For VEVs: sweep (iv_edge, mm_quote_size, delta_tolerance)
- [ ] Validate out-of-sample (fit on day -2/-1, test on day 0+)

---

## Strategy Hypotheses (to confirm with data)

### HYDROGEL_PACK
- **Hypothesis A:** Mean-reverting → fixed_fv market making (like EMERALDS/OSMIUM)
- **Hypothesis B:** Trending → OLS drift following (like PEPPER_ROOT)
- Decision: check AC1 of returns

### VELVETFRUIT_EXTRACT
- Same two hypotheses as above
- Additionally: track realized vol → feeds into VEV pricing

### VEVs
- Base strategy: Black-Scholes MM with inventory skew (carry over Round 3 options framework)
- Key unknowns: what vol surface looks like, which strikes are most liquid
- Delta hedge with VELVETFRUIT_EXTRACT spot

### Counterparty Exploitation
- If a Mark is a consistent price-taker at bad levels → post liquidity they take
- If a Mark has directional alpha → trade in same direction when they trade

---

## Findings Log

### Products
- **HYDROGEL_PACK**: Mean ~9994, spread=16 (constant), AC1=-0.12. Mark 14 always MMs at mid±8. Mark 38 always crosses at mid±8. Classic MM opportunity.
- **VELVETFRUIT_EXTRACT**: Mean ~5247, spread=5 (mostly), AC1=-0.16. Half-integer mids (consecutive integer bid/ask). Mark 67 is a one-sided buyer with 83% hit rate (+1.945 price move in 500ts).
- **VEVs**: IV is constant at σ=0.20 ± 0.003 across all near-ATM strikes. TTE = 4 days remaining at Round 4 start (7-day TTE, 3 days elapsed in Round 3).

### Counterparties
| Mark | Role | Products | Key Behavior |
|------|------|----------|-------------|
| 01 | MM + net VEV buyer | VFE, VEV 5200-6500 | Buys at mid-2.60, sells at mid+2.69 on VFE. Net long VEV calls. |
| 14 | MM | HP, VFE, VEVs | ALWAYS at exactly mid±8 on HP. Reliable reference. |
| 22 | Heavy net seller | All VEV strikes | Sells 1542 vs buys 42. Dominant ask-side on VEVs. |
| 38 | Noise trader | HP, VEVs | ALWAYS crosses at mid±8 on HP. Our primary counterparty. |
| 49 | Low-activity MM | VFE | Rare, ignore. |
| 55 | Noise trader | VFE | Balanced (600/600), crosses spread. VFE counterparty. |
| 67 | **Informed one-sided buyer** | VFE only | NEVER sells. 83% hit rate +1.945 tick move in 500ts. KEY SIGNAL. |

### Key Parameters
- HP penny offset: 1 tick (earn 7/side vs Mark 14's 8)
- VFE: match market bid/ask; pause asks when Mark 67 active (m67_score ≥ 0.40)
- VEV: sigma=0.20, only trade K ≥ 5300 (delta ≤ 0.31 → hedge cost manageable)
- VEV_6000, 6500: sell-only when bid > BS fair + 0.30

---

## Backtest Results (3-day run, prosperity3bt)

| Day | HP | VFE | VEVs | Total |
|-----|-----|-----|------|-------|
| 1 | +13,272 | +487 | +1,738 | **+15,497** |
| 2 | −116 | −538 | +4,979 | **+4,326** |
| 3 | +7,140 | −89 | −1,530 | **+5,521** |
| **Total** | **+20,296** | **−140** | **+5,187** | **+25,344** |

Note: backtester runs each day fresh (day_off=0), so Day 3 VEV losses are a test artifact. In competition, day_off=2 on Day 3 → T_vev = 2/252 → guard blocks VEV quoting → +1,530 saved. Expected competition PnL ≈ +26,900.

Key stats: HP avg edge 6.88 ticks, 1022 fills. VFE −140 = delta hedge cost (not a bug). HP max drawdown 11,643 on Day 2 (trending day) — fully recovered.

---

## Current Best Strategy

### algo/trader_r4.py (v2 — READY TO SUBMIT)
- HYDROGEL_PACK: penny_mm at mid±7, inventory skew at 75%
- VELVETFRUIT_EXTRACT: match MM + Mark 67 lean (pause asks when signal active)
- VEV_5300/5400/5500: BS MM at σ=0.20, delta < 0.50, quote size 15
- VEV_6000/6500: sell-only (near-zero BS fair, market asks at 1)
- VEV_5000/5100/5200, VEV_4000/4500: SKIP (too much delta hedge cost)
- TTE: 4 - day_offset - ts/1e6 days, then divide by 252
- Guard: stop VEV quoting when TTE ≤ 2 trading days (gamma risk too high near expiry)

---

## Files
- `algo/trader_r4.py` — final submittable algo
- `notebooks/analysis.ipynb` — data exploration
- `PLAN.md` — this file
