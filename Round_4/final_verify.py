"""
Clean-room re-verification. Different seed, completely independent.
Checks every assumption and each product from scratch.
"""
import numpy as np
from scipy import stats

# ─── PARAMETERS (from problem statement) ────────────────────────────────────
S0    = 50.0
sigma = 2.51          # 251% annualized
r     = 0.0           # zero risk-neutral drift

TRADING_DAYS_PER_YEAR = 252
STEPS_PER_DAY         = 4
STEPS_PER_YEAR        = 252 * 4   # = 1008

# Problem's own code:
def steps_for_weeks(w): return int(round(w * 5 * STEPS_PER_DAY))
def weeks_to_years(w):  return (w * 5) / TRADING_DAYS_PER_YEAR

T2 = steps_for_weeks(2)    # 40 steps  — choice date for chooser, expiry for 2wk options
T3 = steps_for_weeks(3)    # 60 steps  — expiry for 3wk options & chooser
dt = 1.0 / STEPS_PER_YEAR  # time per step

# GBM step: log(S_{t+1}/S_t) ~ N(drift, diff^2)
drift = (r - 0.5 * sigma**2) * dt
diff  = sigma * np.sqrt(dt)

print(f"T2={T2} steps  T3={T3} steps  dt={dt:.8f}")
print(f"drift/step={drift:.8f}   diff/step={diff:.8f}")
print(f"E[log(S_T3/S0)] = {drift*T3:.6f}   Std[log(S_T3/S0)] = {diff*np.sqrt(T3):.6f}")

# ─── SIMULATE (fresh seed) ──────────────────────────────────────────────────
np.random.seed(99)   # deliberately different from earlier runs
N = 4_000_000

Z = np.random.randn(N, T3)
# Construct full price path: shape (N, T3), column i = price after step i+1
S    = np.exp(np.log(S0) + np.cumsum(drift + diff * Z, axis=1))
S2   = S[:, T2 - 1]           # price at end of step 40
S3   = S[:, T3 - 1]           # price at end of step 60
Smin = np.min(S, axis=1)      # minimum price over ALL 60 discrete steps

def mc(x): return np.mean(x), 2*np.std(x)/np.sqrt(N)

# ─── PRICE EACH PRODUCT ────────────────────────────────────────────────────

# Vanilla 3wk
p50_3v = np.maximum(50-S3,0);  P50_3,  e = mc(p50_3v); print(f"\nAC_50_P   (3wk put  K=50) = {P50_3:.5f} ±{e:.5f}")
c50_3v = np.maximum(S3-50,0);  C50_3,  e = mc(c50_3v); print(f"AC_50_C   (3wk call K=50) = {C50_3:.5f} ±{e:.5f}")
p35_3v = np.maximum(35-S3,0);  P35_3,  e = mc(p35_3v); print(f"AC_35_P   (3wk put  K=35) = {P35_3:.5f} ±{e:.5f}")
p40_3v = np.maximum(40-S3,0);  P40_3,  e = mc(p40_3v); print(f"AC_40_P   (3wk put  K=40) = {P40_3:.5f} ±{e:.5f}")
p45_3v = np.maximum(45-S3,0);  P45_3,  e = mc(p45_3v); print(f"AC_45_P   (3wk put  K=45) = {P45_3:.5f} ±{e:.5f}")
c60_3v = np.maximum(S3-60,0);  C60_3,  e = mc(c60_3v); print(f"AC_60_C   (3wk call K=60) = {C60_3:.5f} ±{e:.5f}")

# Vanilla 2wk
p50_2v = np.maximum(50-S2,0);  P50_2,  e = mc(p50_2v); print(f"AC_50_P_2 (2wk put  K=50) = {P50_2:.5f} ±{e:.5f}")
c50_2v = np.maximum(S2-50,0);  C50_2,  e = mc(c50_2v); print(f"AC_50_C_2 (2wk call K=50) = {C50_2:.5f} ±{e:.5f}")

# Chooser: at step 40, convert to ITM option; payoff at step 60
cho_v = np.where(S2 >= 50, np.maximum(S3-50,0), np.maximum(50-S3,0))
CHO, e = mc(cho_v); print(f"AC_50_CO  (chooser  K=50) = {CHO:.5f} ±{e:.5f}")

# Binary put: pays 10 if S_T3 < 40
bp_v = np.where(S3 < 40, 10.0, 0.0)
BP, e = mc(bp_v); print(f"AC_40_BP  (bin put  K=40) = {BP:.5f} ±{e:.5f}")

# KO put: K=45, barrier=35, discrete monitoring all 60 steps
ko_v = np.where(Smin < 35, 0.0, np.maximum(45-S3, 0.0))
KO, e = mc(ko_v); print(f"AC_45_KO  (KO put   K=45 B=35) = {KO:.5f} ±{e:.5f}")

# Knockout probability
p_ko = np.mean(Smin < 35)
print(f"\nP(knockout) = {p_ko:.5f}  ({p_ko*100:.2f}%)")

# ─── BS CROSS-CHECK ────────────────────────────────────────────────────────
print("\n─── Black-Scholes cross-check ───")
def bsc(S,K,T,v,r=0):
    d1=(np.log(S/K)+(r+.5*v**2)*T)/(v*T**.5); d2=d1-v*T**.5
    return S*stats.norm.cdf(d1)-K*np.exp(-r*T)*stats.norm.cdf(d2)
def bsp(S,K,T,v,r=0): return bsc(S,K,T,v,r)-S+K*np.exp(-r*T)

T2y = weeks_to_years(2); T3y = weeks_to_years(3)
print(f"  BS C(T3,K=50) = {bsc(S0,50,T3y,sigma):.5f}  BS P(T3,K=50) = {bsp(S0,50,T3y,sigma):.5f}")
print(f"  BS P(T2,K=50) = {bsp(S0,50,T2y,sigma):.5f}  BS C(T2,K=50) = {bsc(S0,50,T2y,sigma):.5f}")
chooser_rub = bsc(S0,50,T3y,sigma) + bsp(S0,50,T2y,sigma)
print(f"  Rubinstein chooser = {chooser_rub:.5f}  MC = {CHO:.5f}")
print(f"  PCP check (r=0): C(T3)-P(T3)={C50_3-P50_3:.6f}  (should ≈ 0)")

# ─── EDGE TABLE ────────────────────────────────────────────────────────────
print("\n─── EDGE TABLE (fresh seed=99, 4M paths) ───")
print(f"{'Product':<14} {'Fair':>8} {'Bid':>7} {'Ask':>7} {'Eb(buy)':>9} {'Es(sell)':>9}  Signal")
print("─"*70)
rows = [
    ("AC_50_P",   P50_3, 12.00, 12.05),
    ("AC_50_C",   C50_3, 12.00, 12.05),
    ("AC_35_P",   P35_3,  4.33,  4.35),
    ("AC_40_P",   P40_3,  6.50,  6.55),
    ("AC_45_P",   P45_3,  9.05,  9.10),
    ("AC_60_C",   C60_3,  8.80,  8.85),
    ("AC_50_P_2", P50_2,  9.70,  9.75),
    ("AC_50_C_2", C50_2,  9.70,  9.75),
    ("AC_50_CO",  CHO,   22.20, 22.30),
    ("AC_40_BP",  BP,     5.00,  5.10),
    ("AC_45_KO",  KO,     0.15,  0.175),
]
for name, fair, bid, ask in rows:
    eb = fair - ask; es = bid - fair
    if eb > 0.05:   sig = "<<< BUY"
    elif es > 0.05: sig = ">>> SELL"
    else:           sig = "fair"
    print(f"{name:<14} {fair:8.4f} {bid:7.3f} {ask:7.4f} {eb:9.4f} {es:9.4f}  {sig}")

# ─── PORTFOLIO PnL ─────────────────────────────────────────────────────────
print("\n─── PORTFOLIO (Scenario A — no 3wk call hedge) ───")
port = (
      50 * (22.20 - cho_v)                     # SELL 50 choosers at bid
    + 50 * (p50_2v - 9.75)                     # BUY  50 2wk puts at ask
    + 50 * (c50_2v - 9.75)                     # BUY  50 2wk calls at ask
    + 50 * (5.00 - bp_v)                       # SELL 50 binary puts at bid
    + 500* (ko_v - 0.175)                      # BUY 500 KO puts at ask
)
E_port = np.mean(port)
SD_port = np.std(port)
SE_100 = SD_port / np.sqrt(100)
p_pos = stats.norm.cdf(E_port / SE_100)

print(f"  E[portfolio PnL per path]: {E_port:.4f}")
print(f"  Std per path:              {SD_port:.2f}")
print(f"  SE of 100-sim average:     {SE_100:.2f}")
print(f"  P(100-sim avg > 0):        {p_pos*100:.1f}%")
print(f"  × contract 3000:           {E_port*3000:,.0f} expected XIRECs")

# Percentiles of 100-sim score distribution
np.random.seed(777)
sample_scores = [np.mean(np.random.choice(port, 100, replace=False)) for _ in range(200_000)]
pcts = [5, 10, 25, 50, 75, 90, 95]
print(f"\n  Distribution of 100-sim scores (200k trials):")
for p in pcts:
    v = np.percentile(sample_scores, p)
    print(f"    {p:>3}th pct:  {v:>8.2f}  ({v*3000:>12,.0f} XIRECs)")

# ─── INDIVIDUAL TRADE CONTRIBUTIONS ─────────────────────────────────────────
print("\n─── INDIVIDUAL CONTRIBUTIONS ───")
trades = [
    ("SELL 50 AC_50_CO", 50, 22.20, CHO,  "sell"),
    ("BUY  50 AC_50_P_2",50,  9.75, P50_2,"buy"),
    ("BUY  50 AC_50_C_2",50,  9.75, C50_2,"buy"),
    ("SELL 50 AC_40_BP", 50,  5.00, BP,   "sell"),
    ("BUY 500 AC_45_KO",500,  0.175, KO,  "buy"),
]
total = 0
for name,vol,price,fair,side in trades:
    e = (price-fair) if side=="sell" else (fair-price)
    contrib = e*vol
    total += contrib
    print(f"  {name:<22}  fair={fair:.4f}  edge={e:+.4f}/unit  total={contrib:+.2f}")
print(f"  {'TOTAL':<22}  {'':>10}  {'':>12}  total={total:+.2f}  ({total*3000:+,.0f} XIRECs)")
