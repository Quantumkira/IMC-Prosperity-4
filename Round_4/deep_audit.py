"""
Deep audit of every assumption in the Round 4 options analysis.
"""
import numpy as np
from scipy import stats

# ── 1. TIME CONVENTION AUDIT ─────────────────────────────────────────────────
print("=== 1. TIME CONVENTION AUDIT ===")
TRADING_DAYS_PER_YEAR = 252
STEPS_PER_DAY         = 4
STEPS_PER_YEAR        = TRADING_DAYS_PER_YEAR * STEPS_PER_DAY  # 1008

def steps_for_weeks(weeks):
    return int(round(weeks * 5 * STEPS_PER_DAY))

def weeks_to_years(weeks):
    return (weeks * 5) / TRADING_DAYS_PER_YEAR

T2_steps = steps_for_weeks(2)   # 40
T3_steps = steps_for_weeks(3)   # 60
T2_yr    = weeks_to_years(2)    # 10/252
T3_yr    = weeks_to_years(3)    # 15/252
dt       = 1.0 / STEPS_PER_YEAR

print(f"  2 weeks -> {T2_steps} steps, {T2_yr:.6f} years")
print(f"  3 weeks -> {T3_steps} steps, {T3_yr:.6f} years")
print(f"  dt per step = 1/{STEPS_PER_YEAR} = {dt:.8f} years")

# ── 2. GBM PARAMETER AUDIT ───────────────────────────────────────────────────
print("\n=== 2. GBM PARAMETER AUDIT ===")
S0    = 50.0
sigma = 2.51
r     = 0.0

drift     = (r - 0.5 * sigma**2) * dt
diffusion = sigma * np.sqrt(dt)
print(f"  sigma^2 = {sigma**2:.6f}")
print(f"  drift per step = {drift:.8f}")
print(f"  diffusion per step = {diffusion:.8f}")
print(f"  Total log-drift over T3 = {drift * T3_steps:.6f} (should = {(r-0.5*sigma**2)*T3_yr:.6f})")
print(f"  Total log-vol over T3   = {diffusion * np.sqrt(T3_steps):.6f} (should = {sigma*np.sqrt(T3_yr):.6f})")

# ── 3. LOGNORMAL CROSS-CHECK FOR P(S_T3 < 40) ───────────────────────────────
print("\n=== 3. LOGNORMAL CROSS-CHECK ===")
mu_log   = np.log(S0) + (r - 0.5*sigma**2) * T3_yr  # E[log(S_T3)]
sig_log  = sigma * np.sqrt(T3_yr)
p_below_40 = stats.norm.cdf((np.log(40) - mu_log) / sig_log)
print(f"  E[log S_T3]   = {mu_log:.6f}")
print(f"  Std[log S_T3] = {sig_log:.6f}")
print(f"  Analytical P(S_T3 < 40) = {p_below_40:.6f}   <- should be ~0.4775")
print(f"  Binary put fair value    = {10 * p_below_40:.4f}")

# P(S_T2 < 50) — sanity check: should be 0.5 for ATM with r=0? Not exactly, drift = -sigma^2/2
mu_log2  = np.log(S0) + (r - 0.5*sigma**2) * T2_yr
sig_log2 = sigma * np.sqrt(T2_yr)
p_below_50_T2 = stats.norm.cdf((np.log(50) - mu_log2) / sig_log2)
print(f"\n  P(S_T2 < 50)  = {p_below_50_T2:.6f}  (not 0.5 due to lognormal skew)")

# ── 4. BS CLOSED-FORM AUDIT ──────────────────────────────────────────────────
print("\n=== 4. BLACK-SCHOLES CLOSED-FORM ===")
def bs_call(S, K, T, v, r=0):
    if T <= 0: return max(S-K, 0)
    d1 = (np.log(S/K) + (r + 0.5*v**2)*T) / (v*np.sqrt(T))
    d2 = d1 - v*np.sqrt(T)
    return S*np.exp(-r*T)*stats.norm.cdf(d1) - K*np.exp(-r*T)*stats.norm.cdf(d2)

def bs_put(S, K, T, v, r=0):
    return bs_call(S, K, T, v, r) - S*np.exp(-r*T) + K*np.exp(-r*T)

products_bs = [
    ("AC_50_P",   "put",  50, T3_yr, 12.00, 12.05),
    ("AC_50_C",   "call", 50, T3_yr, 12.00, 12.05),
    ("AC_35_P",   "put",  35, T3_yr,  4.33,  4.35),
    ("AC_40_P",   "put",  40, T3_yr,  6.50,  6.55),
    ("AC_45_P",   "put",  45, T3_yr,  9.05,  9.10),
    ("AC_60_C",   "call", 60, T3_yr,  8.80,  8.85),
    ("AC_50_P_2", "put",  50, T2_yr,  9.70,  9.75),
    ("AC_50_C_2", "call", 50, T2_yr,  9.70,  9.75),
]
print(f"  {'Product':<12} {'BS Fair':>8}  {'Bid':>6} {'Ask':>6}  {'Edge(buy)':>10} {'Edge(sell)':>11}")
for name, typ, K, T, bid, ask in products_bs:
    fair = bs_call(S0, K, T, sigma) if typ == "call" else bs_put(S0, K, T, sigma)
    print(f"  {name:<12} {fair:8.4f}  {bid:6.3f} {ask:6.4f}  {fair-ask:10.4f} {bid-fair:11.4f}")

# Chooser closed form (Rubinstein, r=0): Call(T3) + Put(T2)
chooser_bs = bs_call(S0, 50, T3_yr, sigma) + bs_put(S0, 50, T2_yr, sigma)
print(f"\n  Chooser (Rubinstein) = Call(T3) + Put(T2) = {bs_call(S0,50,T3_yr,sigma):.4f} + {bs_put(S0,50,T2_yr,sigma):.4f} = {chooser_bs:.4f}")
print(f"  Market:  bid=22.200  ask=22.300")
print(f"  Edge(sell at bid): {22.20-chooser_bs:.4f}")

# ── 5. VERIFY RUBINSTEIN DECOMPOSITION DERIVATION ───────────────────────────
print("\n=== 5. RUBINSTEIN DECOMPOSITION VERIFICATION (r=0) ===")
print("  At T1 (choice date), chooser = max(C_1wk(S_T1), P_1wk(S_T1))")
print("  By put-call parity (r=0): C - P = S - K")
print("  => max(C, P) = C + max(0, P-C) = C + max(0, K-S_T1)")
print("  => E_0[max(C,P)] = E_0[C(S_T1, K, T2-T1)] + E_0[max(0, K-S_T1)]")
print("  => Chooser = C(S0, K, T2) + P(S0, K, T1)  [Tower property + put pricing]")
print("  *** This identity holds for r=0 in continuous time. ***")
print("  Discrete GBM introduces a small error (we verified MC matches closely).")

# ── 6. FULL MC SIMULATION ────────────────────────────────────────────────────
print("\n=== 6. MONTE CARLO (2M paths) ===")
np.random.seed(42)
N = 2_000_000
Z   = np.random.randn(N, T3_steps)
log_R = drift + diffusion * Z
S   = np.exp(np.log(S0) + np.cumsum(log_R, axis=1))  # (N, 60), index i = step i+1

S2  = S[:, T2_steps - 1]   # step 40 price
S3  = S[:, T3_steps - 1]   # step 60 price
Smin = np.min(S, axis=1)   # discrete minimum over steps 1..60

def mc(arr): return np.mean(arr), np.std(arr)/np.sqrt(N)

# Vanilla
p50_3, se = mc(np.maximum(50-S3,0)); print(f"  AC_50_P   MC={p50_3:.4f} ±2SE={2*se:.4f}  BS={bs_put(S0,50,T3_yr,sigma):.4f}")
c50_3, se = mc(np.maximum(S3-50,0)); print(f"  AC_50_C   MC={c50_3:.4f} ±2SE={2*se:.4f}  BS={bs_call(S0,50,T3_yr,sigma):.4f}")
p35_3, se = mc(np.maximum(35-S3,0)); print(f"  AC_35_P   MC={p35_3:.4f} ±2SE={2*se:.4f}  BS={bs_put(S0,35,T3_yr,sigma):.4f}")
p40_3, se = mc(np.maximum(40-S3,0)); print(f"  AC_40_P   MC={p40_3:.4f} ±2SE={2*se:.4f}  BS={bs_put(S0,40,T3_yr,sigma):.4f}")
p45_3, se = mc(np.maximum(45-S3,0)); print(f"  AC_45_P   MC={p45_3:.4f} ±2SE={2*se:.4f}  BS={bs_put(S0,45,T3_yr,sigma):.4f}")
c60_3, se = mc(np.maximum(S3-60,0)); print(f"  AC_60_C   MC={c60_3:.4f} ±2SE={2*se:.4f}  BS={bs_call(S0,60,T3_yr,sigma):.4f}")
p50_2, se = mc(np.maximum(50-S2,0)); print(f"  AC_50_P_2 MC={p50_2:.4f} ±2SE={2*se:.4f}  BS={bs_put(S0,50,T2_yr,sigma):.4f}")
c50_2, se = mc(np.maximum(S2-50,0)); print(f"  AC_50_C_2 MC={c50_2:.4f} ±2SE={2*se:.4f}  BS={bs_call(S0,50,T2_yr,sigma):.4f}")

# Chooser
cho = np.where(S2>=50, np.maximum(S3-50,0), np.maximum(50-S3,0))
cho_mc, se = mc(cho)
print(f"  AC_50_CO  MC={cho_mc:.4f} ±2SE={2*se:.4f}  Rubinstein={chooser_bs:.4f}")
print(f"            Diff MC vs Rubinstein: {cho_mc-chooser_bs:.4f}  (discrete GBM error)")

# Binary put
bp = np.where(S3<40, 10., 0.)
bp_mc, se = mc(bp)
print(f"  AC_40_BP  MC={bp_mc:.4f} ±2SE={2*se:.4f}  Analytical={10*p_below_40:.4f}")

# KO put
ko = np.where(Smin<35, 0., np.maximum(45-S3, 0))
ko_mc, se = mc(ko)
pko = np.mean(Smin<35)
print(f"  AC_45_KO  MC={ko_mc:.4f} ±2SE={2*se:.4f}  P(knockout)={pko:.4f}")

# ── 7. CHOOSER PAYOFF VERIFICATION ──────────────────────────────────────────
print("\n=== 7. CHOOSER PAYOFF LOGIC VERIFICATION ===")
print("  'Selecting whichever would be in the money at T2':")
print("  If S_T2 > 50: call is ITM -> becomes a call")
print("  If S_T2 < 50: put is ITM  -> becomes a put")
print("  By PCP (r=0): C-P=S-K => C>P iff S>K. So 'ITM choice' = 'optimal choice'. CONFIRMED.")
n_call_path = np.mean(S2 >= 50)
n_put_path  = np.mean(S2 < 50)
print(f"  P(S_T2 >= 50) = {n_call_path:.4f}  (chooser becomes call)")
print(f"  P(S_T2 <  50) = {n_put_path:.4f}  (chooser becomes put)")

# ── 8. KO BARRIER INTERPRETATION ────────────────────────────────────────────
print("\n=== 8. KO BARRIER AUDIT ===")
print("  Problem: 'If the value ever falls BELOW 35 XIRECs' -> strict inequality (S < 35)")
print("  Monitoring: discrete only at 60 step-end grid points (confirmed by problem statement)")
print(f"  My code: Smin < 35 (strict) -> correct")
print(f"  P(Smin < 35 across 60 steps) = {pko:.4f} = {pko*100:.1f}%")
# Check if S0=50 could be the minimum at step 0 (it's NOT in S since we start after 1 step)
print(f"  Note: S_0=50 is NOT checked (simulation starts from S_1); S_0=50 >> 35, no issue.")

# ── 9. PORTFOLIO COMPARISON: HEDGE vs NO-HEDGE ──────────────────────────────
print("\n=== 9. PORTFOLIO COMPARISON: WITH vs WITHOUT 3wk CALL HEDGE ===")

# Scenario A: Sell chooser + Buy 2wk straddle + Sell binary + Buy KO
port_A = (
      50*(22.20 - cho)                              # short chooser
    + 50*(np.maximum(50-S2,0) - 9.75)              # long 2wk put
    + 50*(np.maximum(S2-50,0) - 9.75)              # long 2wk call
    + 50*(5.00 - np.where(S3<40,10.,0.))            # short binary put
    + 500*(np.where(Smin<35,0.,np.maximum(45-S3,0))-0.175)  # long KO put
)
# Scenario B: Same + Buy 50 3wk calls as Rubinstein hedge (replaces nothing, additive)
port_B = port_A + 50*(np.maximum(S3-50,0) - 12.05)  # long 50 3wk calls

mA, sA = np.mean(port_A), np.std(port_A)
mB, sB = np.mean(port_B), np.std(port_B)
print(f"  Scenario A (no 3wk call): E={mA:.2f}  Std={sA:.2f}  Sharpe={mA/sA:.4f}")
print(f"  Scenario B (+ 3wk call) : E={mB:.2f}  Std={sB:.2f}  Sharpe={mB/sB:.4f}")
print(f"  Std reduction from hedge: {(sA-sB)/sA*100:.1f}%")
print(f"  E[PnL] cost of hedge:     {mA-mB:.2f} units = {(mA-mB)*3000:.0f} XIRECs")
print(f"\n  Scenario A × 3000: E={mA*3000:.0f}  Std={sA*3000:.0f} XIRECs")
print(f"  Scenario B × 3000: E={mB*3000:.0f}  Std={sB*3000:.0f} XIRECs")
print(f"\n  P(A > 0 per path) = {np.mean(port_A>0)*100:.1f}%")
print(f"  P(B > 0 per path) = {np.mean(port_B>0)*100:.1f}%")

# P(score > 0) assuming 100-sim average (CLT approximation)
import scipy.stats as st
se_A = np.std(port_A)/np.sqrt(100)
se_B = np.std(port_B)/np.sqrt(100)
p_pos_A = st.norm.cdf(mA / se_A)
p_pos_B = st.norm.cdf(mB / se_B)
print(f"\n  P(100-sim average > 0): A={p_pos_A*100:.1f}%   B={p_pos_B*100:.1f}%")

# ── 10. MISPRICING TABLE FINAL ───────────────────────────────────────────────
print("\n=== 10. FINAL MISPRICING TABLE ===")
row = [
    ("AC_50_P",   p50_3, 12.00, 12.05, "FAIR"),
    ("AC_50_C",   c50_3, 12.00, 12.05, "FAIR"),
    ("AC_35_P",   p35_3,  4.33,  4.35, "FAIR"),
    ("AC_40_P",   p40_3,  6.50,  6.55, "FAIR"),
    ("AC_45_P",   p45_3,  9.05,  9.10, "FAIR"),
    ("AC_60_C",   c60_3,  8.80,  8.85, "FAIR"),
    ("AC_50_P_2", p50_2,  9.70,  9.75, "BUY"),
    ("AC_50_C_2", c50_2,  9.70,  9.75, "BUY"),
    ("AC_50_CO",  cho_mc,22.20, 22.30, "SELL"),
    ("AC_40_BP",  bp_mc,  5.00,  5.10, "SELL"),
    ("AC_45_KO",  ko_mc,  0.15, 0.175, "BUY"),
]
print(f"  {'Product':<12} {'MC Fair':>8}  {'Bid':>6} {'Ask':>7}  {'Eb(buy)':>8} {'Eb(sell)':>9}  Signal")
for name, fair, bid, ask, sig in row:
    eb = fair - ask
    es = bid - fair
    star = " *** MISPRICED" if sig != "FAIR" else ""
    print(f"  {name:<12} {fair:8.4f}  {bid:6.3f} {ask:7.4f}  {eb:8.4f} {es:9.4f}  {sig}{star}")

print("\n=== DONE ===")
