# IMC Prosperity 4 — Team Report

A five-round journey through market-making, trend following, options pricing
and counterparty exploitation. This report walks through what we built each
round, what worked, what didn't, and how our rank moved from the middle of
the pack to a strong finish.

## Journey at a glance

| Round | Products introduced | Strategy family | Result |
|------:|--------------------|-----------------|--------|
| 0 (Tutorial) | EMERALDS, TOMATOES | Grid-fit meta strategy (MR / momentum) | Framework validated on historical days |
| 1 | ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT | Fixed-FV MM + OLS drift trend | ~1800 rank — average, but pipeline solid |
| 2 | (same two products) | Hand-tuned spike-capture MM + refined drift | ~1000 rank — big jump |
| 3 | HYDROGEL_PACK, VELVETFRUIT_EXTRACT, VEV_* (10 option strikes) | Four-strategy options stack (surface MM, IV scalping, gamma, cross-strike) | Poor — no profit, over-engineered |
| 4 | (same three products) | "Penny the MM" + counterparty lean + aggressive VEV taker | Improvement — recovered ground |
| 5 | PEBBLES_XS..XL, 45 poly-unit assets, SNACKPACK_* | Joint basket quoting + wide market-making + pair-trade & MR overlays | Best round — strong finish |

The arc is the story of the report: build a general framework early, over-fit
in the middle, then throw the framework away for R4/R5 and let the data drive
the strategy.

---

## Round 0 — Tutorial (EMERALDS, TOMATOES)

The tutorial was our chance to build tooling, not to score. We built a
`QuantitativeTrading_CLI` assembler that emits a single `trader.py` from a
declarative config:

- `round_config.json` — per-product position limits, strategy family, and
  parameter grid bounds.
- `3_universe_definitions/universes.json` — products, hedge weights, exogenous
  observation keys.
- `4_parameter_fitting/meta_params.json` — the winning grid point per scope
  (lookback, entry/exit thresholds, inventory skew, momentum sign).
- `5_backtesting/results.json` — Sharpe, drawdown, fill rate per scope.

The core is `MetaStrategy` — a single class that can be configured as mean
reversion (`signal_m=+1`) or momentum (`signal_m=-1`), on single products or
multi-leg baskets with OLS hedge ratios. Fitted params:

- EMERALDS: MR, N=10, z_buy=7.87, inv_skew=4.72 → 570k proxy PnL
- TOMATOES: MR, N=5, z_buy=6.53, inv_skew=3.92 → 400k proxy PnL

Portfolio proxy Sharpe ~255 on backtest days. Framework validated; time to
face real competition.

## Round 1 — Onboarding (rank ~1800)

New products: **ASH_COATED_OSMIUM** (mean anchored at 10 000) and
**INTARIAN_PEPPER_ROOT** (IPR).

**OSMIUM** — treated as a fixed-fair-value MM (like Rainforest Resin in prior
Prosperity editions). Grid-fit found `fair_value=10000, take_edge=1,
skew_threshold=0.75`. Straightforward.

**IPR** — this is where we spent the analysis budget. Empirically IPR is not
a random walk; it's a deterministic linear drift (~+0.1 tick per step, i.e.
~+1000 per day) plus a tight, mean-reverting bid-ask bounce
(σ ≈ 1.9, AC₁ ≈ −0.46). See `Round_1/doc/IPR.md` for the full derivation.

Our v1 EMA strategy was subtly broken: for a constantly drifting asset an EMA
just trails price by a mathematically fixed lag of `μ/α`. The optimizer
happily set a huge `z_entry` so the "momentum" signal was permanently
triggered — the algorithm was effectively buy-and-hold with no exit
mechanism. Robust in-sample, brittle out-of-sample.

We replaced it with a **rolling OLS drift strategy**: compute the actual
regression slope β over N=50 ticks, convert to a t-statistic, size the
position proportionally to confidence, and cut on a σ-scaled stop.

**Manual round** was a first-price sealed-bid auction of Intarian goods.
See `Round_1/manual/manual_round_explainer.md` — the analysis and profit
curves are worth keeping.

**Result:** middle of the pack (~1800). Pipeline was working, but the
one-size-fits-all `MetaStrategy` was not squeezing all the edge available.

## Round 2 — Rank up (~1000)

Round 2 kept the same two products but let us iterate. We abandoned the
generated `trader.py` and wrote `shankar_trader.py` — a single hand-tuned
`Trader` class where we could bake in microstructure observations.

Key insight for OSMIUM: **the bid-ask spread is always exactly 16 ticks in
normal conditions**. Any spread below 16 is an inward spike — a taker
crossing on one side. Behaviour:

- Spread == 16 → normal MM at `best_bid+1 / best_ask-1`, refresh
  `stable_mid` and last-clean L1.
- Spread < 16 → **do not** update references. Identify the spiking side by
  comparing L1 to `stable_mid` and cross it (taker) for guaranteed edge.
  Maker quotes fall back to the last clean L1 ± 1.

For IPR we kept the OLS-drift framework from R1 with an explicit exit
threshold (`t_exit = t_entry/2`), tighter stops, and precomputed regression
constants.

We iterated many variants in `Round_2/{351984,352298,354918,358233,358537,
359438,359622,361727}/` — the last submitted was `361727/361727.py`. The
`old_algo/`, `just_MM/`, and `new_shankar/` folders capture dead-ends worth
keeping for the write-up (each shows one thing we tried and rejected).

**Result:** rank jumped to ~1000. Beating the generic MM by paying attention
to a single microstructure artefact was the takeaway of the round.

## Round 3 — Options round, harsh lesson (no profit)

New products: **HYDROGEL_PACK**, **VELVETFRUIT_EXTRACT** (VFE, delta-1
underlying), and **VEV_4000..VEV_6500** — 10 European call vouchers on VFE,
7-day TTE at start, one-day decrement per round.

We went **too big**. The final submission
(`Round_3/R3_claude/round3_submission_v7_mm.py`) stacks four strategies at
once:

1. **Vol Surface MM** — quote a rolling smile on ITM/ATM strikes {5100, 5200}
   with aggressive inventory skew.
2. **IV Scalping** — per-strike IV EMA + deviation trigger, mean-revert
   perceived IV to the smile.
3. **Gamma Scalping** — buy long-vol when IV << realized vol, monetise via
   delta hedging on VFE.
4. **Cross-Strike Vol Arb** — trade the IV spread between strikes when it
   diverges from the smile.

The infrastructure was real: `BlackScholes` class with call price, delta,
gamma, vega, and a Newton implied-vol solver. Rolling smile fit with two
learning rates (`α_c=0.20` for the ATM level, `α_ab=0.05` for curvature and
skew). Delta hedging against VFE with a tolerance band.

Where it went wrong:

- Four overlapping strategies fought each other for the same inventory.
- Passive quoting under-performed because market-makers had time-priority
  at the same price.
- Vol assumptions drifted from the true market IV (~0.22-0.23 vs our 0.20),
  so "cheap vol" trades were structurally short EV.
- Delta-hedge cadence and spread cost were badly tuned — we bled the edge
  into the hedge.

Considerable analysis was captured in the notebooks
(`round3_options_analysis.ipynb`, `round3_opt_upd.ipynb`) and the intermediate
CSVs (`voucher_df_with_implied_vol*.csv`, ~50 MB total). Useful for the
report; not needed in the repo.

**Result:** no meaningful profit. The lesson bought Round 4.

## Round 4 — Rebuild from data (improvement)

Same three products, zero code carried over from R3. `Round_4/PLAN.md` is
the living plan for this round — it's the structured version of "what
actually is in this data?". Key findings that shaped the trader:

- **HYDROGEL_PACK**: mean ~9994, spread is a constant 16, AC₁ ≈ −0.12. "Mark
  14" always posts MM at mid±8; "Mark 38" always crosses at mid±8. Classic
  MM opportunity: penny Mark 14 at mid±7 so Mark 38 fills us first — earn
  ~7 ticks per fill on both sides.
- **VELVETFRUIT_EXTRACT**: Mark 01/22 are MMs, Mark 55 is the noise crosser,
  and **Mark 67 only ever buys VFE** — with an 83% hit-rate for ~+2 ticks in
  the next 500 timestamps. When Mark 67 is active we pause our ask (lean
  long) so we don't sell them cheap paper.
- **VEV options**: passive quoting fails (MM has price-time priority).
  Market prices vouchers at IV ≈ 0.22-0.23 while our σ=0.20 → the market
  bid consistently exceeds Black-Scholes fair. Cross the bid as a taker
  whenever `best_bid − fair ≥ 1.5`, only on strikes with |δ| < 0.50 (so
  hedges are manageable), skip when TTE ≤ 2 days.

Support files: `hedge_analysis.py`, `manual_pricing.py` (Monte-Carlo pricing
of a manual-round chooser / knock-out / binary put with 2M simulated paths
cross-checked against Black-Scholes), `manual_simulation.ipynb`, and the
verification scripts `deep_audit.py`, `recheck.py`, `final_verify.py`.

**Result:** improvement — recovered rank ground lost in R3. The write-up
point: R4 outperformed R3's four-strategy stack with three tightly
data-driven rules.

## Round 5 — All-in (best round)

Round 5 was the biggest surface area — 55 products across three cohorts:

- **PEBBLES_XS..XL** — five correlated tiers of the same underlying idea.
- 45 **"poly-unit" assets** — Galaxy Sounds, Sleep Pods, Microchips, Robots,
  UV Visors, Translators, Panels, Oxygen Shakes (5 variants each).
- **SNACKPACK_*** — Chocolate, Vanilla, Pistachio, Strawberry, Raspberry.

We ran three sub-strategies inside a single `Trader.run()`:

1. **PEBBLES basket** — joint take + independent quoting. If every one of
   the five tiers shows a favourable crossable inner (top ask below fair
   for a buy, top bid above fair for a sell) in the same direction, we
   take simultaneously and solve a small optimisation to keep the tier
   inventories aligned around a common target (minimise the sum of squared
   tier-vs-XL spreads plus a mild inventory penalty). Then quote every leg
   one tick inside the top of its own book.

2. **45 poly-unit independents** — a simple, robust loop per product:
   take at fair when it shrinks inventory, then quote one tick inside.
   Small edge per name, but 45 of them add up.

3. **SNACKPACK book** — three overlays on the same set:
   - **Choco/Vanilla joint take**: pair-trade so the two positions stay
     close in size while penalising absolute inventory.
   - **Raspberry mean reversion**: slow EMA (span 4000, band 140) around
     ~10 000; take against extreme fair prints.
   - **Strawberry / Pistachio mean reversion**: fast EMA (span 800, band
     16) around ~10 300 / ~9 650 respectively.
   - Passive quotes on all five, using the same one-tick-inside rule.

Common to all three cohorts: the **"wall-mid"** fair price — take the
midpoint of the thickest bid level and thickest ask level (the "wall"),
prefer any isolated tick within 1 of it, else use `wall_mid − 0.5`. That
one rule handled almost every product in the round.

The final trader is `round_5.py`.

**Result:** best round of the competition. The mix of a joint quote for
correlated products, uniform market making on a wide universe of small
edges, and light MR overlays on the snack book paid off cleanly.

---

## What we learned

1. **A general framework is scaffolding, not a strategy.** The Round 0
   `MetaStrategy` was great to build against but got us to ~1800. The rank
   jump came in R2 when we started hand-writing product-specific rules
   informed by microstructure.
2. **Look at the spread distribution before writing code.** OSMIUM's
   constant-16 spread and Hydrogel's constant-16 spread both handed us
   a clean rule. R3's biggest mistake was assuming the vol we fit was the
   vol the market was quoting.
3. **Fewer strategies, more edge per strategy.** R3 had four options
   sub-strategies fighting each other. R4 had three tight data-driven
   rules and did better.
4. **Name your counterparties.** Once the trade tape carried buyer/seller
   fields, one line of analysis ("Mark 67 only buys VFE") unlocked a
   directional lean that neither an MM nor an MR framework would find.
5. **Correlated products want joint decisions.** The PEBBLES joint-take
   in R5 works because inventory drift across the five tiers is more
   expensive than any single-leg edge; the small optimisation buys back
   most of that cost.

---

## Recommended GitHub repo structure

The `prosperity-4/` tree today mixes final submissions, dead-end variants,
raw CSVs, and virtualenvs. For a public repo we suggest:

**Keep (per round):**

- `Round_0/`
  - `trader.py` (assembled), `benchmark_trader.py`
  - `round_config.json`, `3_universe_definitions/universes.json`,
    `4_parameter_fitting/meta_params.json`,
    `5_backtesting/{config,results}.json`
  - `datamodel.py`
- `Round_1/`
  - `trader.py`, `benchmark_trader.py`, `datamodel.py`
  - `round_config.json`, `3_universe_definitions/`, `4_parameter_fitting/meta_params.json`
  - `doc/IPR.md`
  - `manual/manual_round_explainer.md` (+ the 4 PNGs)
- `Round_2/`
  - Final submission `361727/361727.py` (rename to `trader.py` for clarity)
  - `shankar_trader.py` (working hand-tuned version, for the write-up)
  - Optional: keep `old_algo/321577.py`, `just_MM/324298.py` as "what we
    tried" appendix
- `Round_3/`
  - `R3_claude/round3_submission_v7_mm.py` (final submission)
  - `R3_claude/'Round 3 - "Gloves Off"...md'` (round briefing)
  - **Drop** the 50 MB of `voucher_df_*.csv` and the `.venv/` — regenerate
    from `generate_all_days_data.py` if needed
- `Round_4/`
  - `trader.py`, `datamodel.py`, `PLAN.md`
  - `manual_pricing.py`, `manual_simulation.ipynb`
  - Keep `hedge_analysis.py`; the `deep_audit.py`, `recheck.py`,
    `final_verify.py` can stay if you want to show the review process
- `Round_5/`
  - `round_5.py` (final submission)

**Drop from the repo entirely:**

- Every `.venv/` and `__pycache__/` folder
- Every `local_backtests/` timestamped run directory (regenerate on demand)
- Large logs / JSON dumps inside `Round_*/<submission_id>/<submission_id>.json`
  and `benchmark_results/*.json` — keep one representative sample per round
  if you want, delete the rest
- Round 3 CSVs (`all_days_data.csv`, `voucher_df_*.csv`) — total ~65 MB
- Duplicate copies of `datamodel.py` — consolidate into one at the top level
- `.DS_Store` files

**Add at the top level:**

- `README.md` — one-paragraph summary + link to this report
- `REPORT.md` — this document
- `.gitignore` — `.venv/`, `__pycache__/`, `*.pyc`, `.DS_Store`,
  `local_backtests/`, `*.csv` in `Round_3/`

After the cleanup the repo should be well under 5 MB and read as a
narrative rather than a workspace snapshot.
