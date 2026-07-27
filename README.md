# IMC Prosperity 4 — Algorithmic Trading Competition

**Final overall rank: 915 (top ~5%) · Round 5 algorithmic rank: 157 (top ~1%)** — out of ~18,000 registered teams globally

A five-round quant trading competition run by IMC Trading. Each round
introduces new products with distinct microstructure, and teams submit a
single `Trader.run()` Python entry point that is scored against a
simulated exchange. This repository contains our final submissions and
the analysis behind each round's strategy.

Full write-up: **[REPORT.md](./REPORT.md)**

## Results

| Round | Products | Strategy family |
|------:|----------|-----------------|
| 0 (tutorial) | EMERALDS, TOMATOES | Grid-fit meta-strategy (MR / momentum) |
| 1 | ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT | Fixed-FV MM + OLS drift trend |
| 2 | (same as R1) | Spike-capture MM + refined drift |
| 3 | HYDROGEL_PACK, VELVETFRUIT_EXTRACT, VEV_* (10 options) | Vol-surface MM + IV / gamma scalping + cross-strike arb |
| 4 | (same as R3) | "Penny the MM" + counterparty lean + aggressive VEV taker |
| 5 | PEBBLES_XS..XL, 45 poly-unit assets, SNACKPACK_* | Joint basket MM + wide market-making + pair-trade & MR overlays |
| — | — | — |

**915 / ~18,000 teams (top ~5%); Round 5 algorithmic rank 157 (top ~1%)**

## Strategies shipped

- **Market making** — one-tick-inside passive quoting with inventory skew, "wall-mid" fair-price derived from thickest-book levels, spike detection via constant-spread invariants.
- **Trend following** — rolling OLS regression with proportional t-stat sizing and σ-scaled stops; replaces a naïve EMA approach whose lag was mathematically constant under linear drift.
- **Options pricing** — Black-Scholes call price / delta / gamma / vega implementation, Newton implied-vol solver, rolling vol-smile fit with dual learning rates (fast ATM level, slow curvature/skew), delta hedging against the underlying.
- **Monte-Carlo pricing** — 2M-path simulator for chooser / knock-out / binary payoffs used in the R4 manual round, cross-checked against Black-Scholes closed form.
- **Pair trading & mean reversion** — Choco/Vanilla joint-take optimizer minimising `(qC − qV)² + λ·(qC² + qV²)`; EMA-based mean reversion on three snack products with per-product bandwidth.
- **Basket / correlated-asset trading** — joint take across five PEBBLES tiers that solves a small optimisation to keep tier inventories aligned while penalising absolute inventory.
- **Counterparty exploitation** — after Prosperity exposed buyer/seller identities in R4, analysis of per-"Mark" fill patterns produced the "Mark 67 lean" (an 83% hit-rate directional signal), plus classification of MMs vs. noise traders vs. informed flow.

## Repository layout

```
prosperity-4/
├── REPORT.md               narrative + lessons per round
├── round_5.py              final Round 5 submission (best round)
├── Round_0/                tutorial: MetaStrategy framework + configs
├── Round_1/                fixed-FV MM + OLS drift; IPR analysis doc
├── Round_2/                spike-capture MM (final: trader.py, iteration history retained)
├── Round_3/                options round — 4-strategy stack + round briefing
├── Round_4/                data-driven rebuild — PLAN + trader + MC pricing scripts
└── README.md / .gitignore
```

Each round directory contains only the final submission and the
analysis/config files that back the story in `REPORT.md`. Intermediate
backtests, virtualenvs, and raw CSVs were removed during cleanup.

## Tech stack

Python 3 · NumPy · SciPy · `statistics.NormalDist` for options pricing ·
Jupyter for exploratory analysis · IMC's `prosperity3bt` for local
backtesting.

## Key engineering notes

- **`round_5.py`** is the largest and highest-scoring artifact. Three
  sub-strategies co-exist in one `Trader.run()`: a PEBBLES basket joint
  quoter, an independent MM loop over 45 assets, and a five-product
  SNACKPACK book combining pair trading with EMA mean reversion.
- **`Round_2/trader.py`** demonstrates the microstructure insight that
  moved us from ~1800 → ~1000: OSMIUM's spread is always exactly 16
  ticks in normal conditions, so any spread < 16 is a taker crossing —
  detect the direction, take the crossing side, and quote from the last
  clean L1.
- **`Round_3/trader.py`** and **`Round_4/trader.py`** are worth reading
  side-by-side. R3 stacks four options strategies fighting for the same
  inventory (~1600 lines) and fails to profit. R4 replaces it with three
  tight data-driven rules and recovers rank. The lesson is the report's
  main takeaway.

See [REPORT.md](./REPORT.md) for the full narrative, per-round strategy
derivations, and lessons learned.
