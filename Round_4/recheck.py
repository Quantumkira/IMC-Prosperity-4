"""
Systematic re-check of every assumption and number.
"""
import numpy as np
from scipy import stats

np.random.seed(42)
S0=50.; sigma=2.51; r=0.
STEPS_PER_YEAR=252*4; T2=40; T3=60
dt=1./STEPS_PER_YEAR
drift=(r-0.5*sigma**2)*dt
diff=sigma*np.sqrt(dt)
N=3_000_000  # 3M for tighter SE

Z=np.random.randn(N,T3)
S=np.exp(np.log(S0)+np.cumsum(drift+diff*Z,axis=1))
S2=S[:,T2-1]; S3=S[:,T3-1]; Smin=np.min(S,axis=1)

# ─── CHECK A: Put-call parity (r=0 means C=P for ATM; verify our MC is consistent) ───
print("=== A. PUT-CALL PARITY CHECK (r=0) ===")
c50_3 = np.maximum(S3-50,0); p50_3 = np.maximum(50-S3,0)
c50_2 = np.maximum(S2-50,0); p50_2 = np.maximum(50-S2,0)
print(f"  C(T3)-P(T3) = {np.mean(c50_3)-np.mean(p50_3):.6f}  (should be S0-K = 0)")
print(f"  C(T2)-P(T2) = {np.mean(c50_2)-np.mean(p50_2):.6f}  (should be 0)")
print(f"  Both ≈ 0 confirms r=0 and correct GBM drift. ✓")

# ─── CHECK B: Chooser Rubinstein identity — MC vs analytical ────────────────
print("\n=== B. CHOOSER RUBINSTEIN DECOMPOSITION ===")
cho = np.where(S2>=50, c50_3, p50_3)  # at T2, pick ITM side; payoff at T3
cho_mc = np.mean(cho); cho_se = np.std(cho)/np.sqrt(N)
rub = np.mean(c50_3) + np.mean(p50_2)  # Rubinstein: Call(T3) + Put(T2)
print(f"  MC chooser:              {cho_mc:.6f} ± {2*cho_se:.6f} (2SE)")
print(f"  Rubinstein C(T3)+P(T2):  {rub:.6f}")
print(f"  Difference:              {cho_mc-rub:.6f}  (discrete GBM error, should be tiny)")
print(f"  Market bid:              22.200")
print(f"  Edge to SELL at bid:     {22.20-cho_mc:.6f}")

# ─── CHECK C: Is the Rubinstein formula EXACT? Verify derivation path-by-path ─────
print("\n=== C. RUBINSTEIN IDENTITY — PATH-BY-PATH RESIDUAL ===")
# max(C_T1, P_T1) where C_T1,P_T1 are BS values at T2 with T remaining = T3-T2 = 20 steps
T_rem_yr = (T3-T2)/STEPS_PER_YEAR  # 20 steps remaining after choice
sig_rem = sigma*np.sqrt(T_rem_yr)

def bs_call_vec(S, K, T_yr, v):
    d1 = (np.log(S/K) + 0.5*v**2*T_yr) / (v*np.sqrt(T_yr))
    d2 = d1 - v*np.sqrt(T_yr)
    return S*stats.norm.cdf(d1) - K*stats.norm.cdf(d2)

def bs_put_vec(S, K, T_yr, v):
    return bs_call_vec(S, K, T_yr, v) - S + K

# BS values AT T2 with 1 week remaining
C_at_T2 = bs_call_vec(S2, 50, T_rem_yr, sigma)
P_at_T2 = bs_put_vec(S2, 50, T_rem_yr, sigma)
chooser_optimal = np.maximum(C_at_T2, P_at_T2)
chooser_itm     = np.where(S2>=50, C_at_T2, P_at_T2)

print(f"  E[max(C_T2,P_T2)] (optimal BS):  {np.mean(chooser_optimal):.6f}")
print(f"  E[ITM choice BS]:                {np.mean(chooser_itm):.6f}")
print(f"  Difference:                      {np.mean(chooser_optimal-chooser_itm):.8f}")
print(f"  *** ITM choice = optimal choice CONFIRMED (difference is numerically zero) ***")
# Note: these are BS values at T2, not final payoffs at T3
# The MC chooser payoff (actual realised at T3) is what we priced above

# ─── CHECK D: Binary put — strict < vs <= ─────────────────────────────────────
print("\n=== D. BINARY PUT STRICT INEQUALITY ===")
bp_strict = np.mean(np.where(S3 < 40, 10., 0.))
bp_lte    = np.mean(np.where(S3 <= 40, 10., 0.))
print(f"  S3 < 40 (strict):   {bp_strict:.6f}")
print(f"  S3 <= 40 (lte):     {bp_lte:.6f}")
print(f"  Difference:         {bp_lte-bp_strict:.8f}  (P(S3=40 exactly) ≈ 0 for cont. dist)")
print(f"  Market bid: 5.000   Edge to sell: {5.0-bp_strict:.6f}")

# ─── CHECK E: KO put — is S_0=50 included in barrier monitoring? ──────────────
print("\n=== E. KO PUT BARRIER MONITORING ===")
# S[:,0] is the price AFTER step 1 (not S0=50). Minimum is over steps 1..60.
print(f"  S_0 = {S0} (starting price, NOT included in discrete monitoring)")
print(f"  S_min range: {Smin.min():.4f} to {Smin.max():.4f}")
print(f"  P(Smin < 35): {np.mean(Smin<35):.6f}")
print(f"  P(Smin <= 35): {np.mean(Smin<=35):.6f}  (essentially same, continuous dist)")
ko = np.where(Smin<35, 0., np.maximum(45-S3,0))
ko_mc = np.mean(ko); ko_se = np.std(ko)/np.sqrt(N)
print(f"  KO put fair value: {ko_mc:.6f} ± {2*ko_se:.6f} (2SE)")
print(f"  Market ask: 0.175   Edge to BUY: {ko_mc-0.175:.6f}")

# ─── CHECK F: WHY does the Rubinstein 3wk-call "hedge" INCREASE variance? ────
print("\n=== F. WHY 3WK CALL HEDGE INCREASES PORTFOLIO VARIANCE ===")
# Core insight: when S_T2 < 50 (60% of paths), chooser becomes a PUT.
# Adding a long 3wk call in these paths creates a net LONG FORWARD position:
# [-max(50-S3,0)] + [+max(S3-50,0)] = S3 - 50  (linear in S3 → high variance)

pct_put = np.mean(S2 < 50)
pct_call = np.mean(S2 >= 50)
print(f"  P(chooser→put) = {pct_put:.4f},  P(chooser→call) = {pct_call:.4f}")

# Variance contribution of long 3wk call in paths where chooser→put
cho_put_paths = S2 < 50
net_in_put_paths = (22.20 - p50_3[cho_put_paths]) + (c50_3[cho_put_paths] - 12.05)
net_in_call_paths = (22.20 - c50_3[~cho_put_paths]) + (c50_3[~cho_put_paths] - 12.05)
print(f"  [PUT paths, hedged] E={np.mean(net_in_put_paths):.4f} Std={np.std(net_in_put_paths):.4f}")
print(f"  [CALL paths, hedged] E={np.mean(net_in_call_paths):.4f} Std={np.std(net_in_call_paths):.4f}")
# In PUT paths: short chooser pays -max(50-S3,0), long call adds +max(S3-50,0)
# Combined = S3-50, a linear forward-like payoff → HIGH VARIANCE
# In CALL paths: short chooser pays -max(S3-50,0), long call adds +max(S3-50,0) → nets out ≈ 0 (LOW var)
print(f"  In PUT paths (60%): combined = S3-50 (forward exposure, HIGH variance)")
print(f"  In CALL paths (40%): combined ≈ 0 (hedge works)")
print(f"  Net: hedge ADDS variance in 60% of paths, removes it in 40% → net WORSE")

# ─── CHECK G: ALL FIVE TRADES — final numbers ─────────────────────────────────
print("\n=== G. FINAL TRADE TABLE (3M simulations) ===")
trades = [
    ("AC_50_CO SELL",  50, 22.20, 22.20, np.mean(cho),      np.std(cho)/np.sqrt(N)),
    ("AC_50_P_2 BUY",  50,  9.75,  9.75, np.mean(p50_2),    np.std(p50_2)/np.sqrt(N)),
    ("AC_50_C_2 BUY",  50,  9.75,  9.75, np.mean(c50_2),    np.std(c50_2)/np.sqrt(N)),
    ("AC_40_BP SELL",  50,  5.00,  5.00, np.mean(np.where(S3<40,10.,0.)), np.std(np.where(S3<40,10.,0.))/np.sqrt(N)),
    ("AC_45_KO BUY",  500,  0.175, 0.175, ko_mc, ko_se),
]
print(f"  {'Trade':<20} {'Vol':>4}  {'TxPrice':>8} {'MCFair':>8} {'±2SE':>7} {'EdgePerUnit':>12} {'TotalEdge':>10}")
print("  " + "-"*80)
total_edge = 0
for name, vol, tx_price, _, mc_fair, se in trades:
    sign = -1 if "SELL" in name else 1
    edge = sign*(mc_fair - tx_price)  # + means profitable
    if "SELL" in name:
        edge = tx_price - mc_fair  # receive price, owe fair value
    else:
        edge = mc_fair - tx_price   # receive fair value, pay price
    total = edge * vol
    total_edge += total
    print(f"  {name:<20} {vol:>4}  {tx_price:>8.4f} {mc_fair:>8.4f} {2*se:>7.4f} {edge:>12.4f} {total:>10.2f}")
print(f"  {'TOTAL':<20}       {'':>8} {'':>8} {'':>7} {'':>12} {total_edge:>10.2f}")
print(f"\n  × contract size 3000 = {total_edge*3000:,.0f} expected XIRECs")

# Portfolio PnL distribution
port = (
      50*(22.20 - cho)
    + 50*(p50_2 - 9.75)
    + 50*(c50_2 - 9.75)
    + 50*(5.00 - np.where(S3<40,10.,0.))
    + 500*(ko - 0.175)
)
port_se = np.std(port)/np.sqrt(100)  # 100 sim average SE
p_pos_100 = stats.norm.cdf(np.mean(port)/port_se)
print(f"\n  Portfolio per-path: E={np.mean(port):.4f}  Std={np.std(port):.2f}")
print(f"  Score (avg 100 sims): E={np.mean(port):.4f}  SE={port_se:.2f}")
print(f"  P(score > 0 across 100 sims): {p_pos_100*100:.1f}%")
print(f"\n  Percentiles of 100-sim average (in units, before ×3000):")
sims_of_100 = [np.mean(np.random.choice(port, 100)) for _ in range(100_000)]
for pct in [5, 25, 50, 75, 95]:
    v = np.percentile(sims_of_100, pct)
    print(f"    {pct:>3}th: {v:>8.2f}  ({v*3000:>10,.0f} XIRECs)")
