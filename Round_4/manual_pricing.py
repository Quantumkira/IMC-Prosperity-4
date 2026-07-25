import numpy as np
from scipy import stats

np.random.seed(42)

# ── Parameters ──────────────────────────────────────────────────────────────
S0    = 50.0
sigma = 2.51        # 251% annualized vol
r     = 0.0

TRADING_DAYS_PER_YEAR = 252
STEPS_PER_DAY         = 4
STEPS_PER_YEAR        = TRADING_DAYS_PER_YEAR * STEPS_PER_DAY  # 1008

T2_steps = 2 * 5 * STEPS_PER_DAY   # 40  (2 weeks)
T3_steps = 3 * 5 * STEPS_PER_DAY   # 60  (3 weeks)

dt        = 1.0 / STEPS_PER_YEAR
drift     = (r - 0.5 * sigma**2) * dt
diffusion = sigma * np.sqrt(dt)

N_SIM = 2_000_000   # 2M paths — accurate enough to resolve small mispricings

print(f"dt = {dt:.6f}  |  drift/step = {drift:.6f}  |  diffusion/step = {diffusion:.6f}")
print(f"T2 = {T2_steps} steps  |  T3 = {T3_steps} steps")
print(f"Simulating {N_SIM:,} paths...\n")

# ── Simulate full 60-step paths ──────────────────────────────────────────────
Z          = np.random.randn(N_SIM, T3_steps)
log_returns = drift + diffusion * Z
log_S       = np.log(S0) + np.cumsum(log_returns, axis=1)
S           = np.exp(log_S)          # shape (N_SIM, T3_steps)

S_T2 = S[:, T2_steps - 1]           # price at step 40  (index 39)
S_T3 = S[:, T3_steps - 1]           # price at step 60  (index 59)
S_min = np.min(S, axis=1)           # path minimum across all 60 discrete steps

# ── Payoff functions ─────────────────────────────────────────────────────────

# Vanilla
def call(S_exp, K): return np.mean(np.maximum(S_exp - K, 0))
def put(S_exp, K):  return np.mean(np.maximum(K - S_exp, 0))

ac_50_p   = put(S_T3, 50)
ac_50_c   = call(S_T3, 50)
ac_35_p   = put(S_T3, 35)
ac_40_p   = put(S_T3, 40)
ac_45_p   = put(S_T3, 45)
ac_60_c   = call(S_T3, 60)
ac_50_p_2 = put(S_T2, 50)
ac_50_c_2 = call(S_T2, 50)

# Chooser: at T2 pick whichever is ITM → call if S_T2 >= 50 else put; payoff at T3
chooser_payoff = np.where(
    S_T2 >= 50,
    np.maximum(S_T3 - 50, 0),
    np.maximum(50 - S_T3, 0),
)
ac_50_co = np.mean(chooser_payoff)

# Binary put: pays 10 if S_T3 < 40
ac_40_bp = np.mean(np.where(S_T3 < 40, 10.0, 0.0))

# Knock-out put: K=45, barrier=35, discrete monitoring, T=60 steps
knocked_out = S_min < 35
ac_45_ko = np.mean(np.where(knocked_out, 0.0, np.maximum(45 - S_T3, 0)))

# ── Black-Scholes analytical cross-check ────────────────────────────────────
def bs_call(S, K, T_years, v):
    if T_years <= 0: return max(S - K, 0)
    d1 = (np.log(S/K) + 0.5*v**2*T_years) / (v*np.sqrt(T_years))
    d2 = d1 - v*np.sqrt(T_years)
    return S*stats.norm.cdf(d1) - K*stats.norm.cdf(d2)

def bs_put(S, K, T_years, v):
    return bs_call(S, K, T_years, v) - S + K   # put-call parity (r=0)

T2_yr = T2_steps / STEPS_PER_YEAR
T3_yr = T3_steps / STEPS_PER_YEAR

bs = {
    "AC_50_P":   bs_put(S0, 50, T3_yr, sigma),
    "AC_50_C":   bs_call(S0, 50, T3_yr, sigma),
    "AC_35_P":   bs_put(S0, 35, T3_yr, sigma),
    "AC_40_P":   bs_put(S0, 40, T3_yr, sigma),
    "AC_45_P":   bs_put(S0, 45, T3_yr, sigma),
    "AC_60_C":   bs_call(S0, 60, T3_yr, sigma),
    "AC_50_P_2": bs_put(S0, 50, T2_yr, sigma),
    "AC_50_C_2": bs_call(S0, 50, T2_yr, sigma),
    # Chooser closed form: C(T3) + P(T2)   [standard Rubinstein, r=0]
    "AC_50_CO":  bs_call(S0, 50, T3_yr, sigma) + bs_put(S0, 50, T2_yr, sigma),
}

# ── Results table ────────────────────────────────────────────────────────────
results = [
    ("AC_50_P",   ac_50_p,   bs.get("AC_50_P"),   12.00, 12.05),
    ("AC_50_C",   ac_50_c,   bs.get("AC_50_C"),   12.00, 12.05),
    ("AC_35_P",   ac_35_p,   bs.get("AC_35_P"),    4.33,  4.35),
    ("AC_40_P",   ac_40_p,   bs.get("AC_40_P"),    6.50,  6.55),
    ("AC_45_P",   ac_45_p,   bs.get("AC_45_P"),    9.05,  9.10),
    ("AC_60_C",   ac_60_c,   bs.get("AC_60_C"),    8.80,  8.85),
    ("AC_50_P_2", ac_50_p_2, bs.get("AC_50_P_2"),  9.70,  9.75),
    ("AC_50_C_2", ac_50_c_2, bs.get("AC_50_C_2"),  9.70,  9.75),
    ("AC_50_CO",  ac_50_co,  bs.get("AC_50_CO"),  22.20, 22.30),
    ("AC_40_BP",  ac_40_bp,  None,                  5.00,  5.10),
    ("AC_45_KO",  ac_45_ko,  None,                  0.15,  0.175),
]

print(f"{'Product':<12} {'MC Fair':>8} {'BS Fair':>8} {'Bid':>7} {'Ask':>7} {'Edge(buy)':>10} {'Edge(sell)':>11} {'Signal'}")
print("─" * 90)
for name, mc, bsv, bid, ask in results:
    bs_str = f"{bsv:8.4f}" if bsv is not None else "      --"
    edge_buy  = mc - ask          # positive → buying is +EV
    edge_sell = bid - mc          # positive → selling is +EV
    if   edge_buy  > 0.05: sig = ">>> BUY"
    elif edge_sell > 0.05: sig = "<<< SELL"
    else:                  sig = "  fair"
    print(f"{name:<12} {mc:8.4f} {bs_str} {bid:7.3f} {ask:7.4f} {edge_buy:10.4f} {edge_sell:11.4f}   {sig}")

print()
print("── Knock-out details ─────────────────────────────────────────────────────")
ko_prob = np.mean(knocked_out)
print(f"  P(barrier hit, discrete 60-step): {ko_prob:.4f}  ({ko_prob*100:.1f}%)")
print(f"  Standard AC_45_P fair value:      {ac_45_p:.4f}")
print(f"  AC_45_KO fair value:              {ac_45_ko:.4f}")
print(f"  KO discount vs vanilla:           {ac_45_p - ac_45_ko:.4f}")

print()
print("── Chooser decomposition ─────────────────────────────────────────────────")
print(f"  AC_50_C (3wk call):   {ac_50_c:.4f}")
print(f"  AC_50_P_2 (2wk put):  {ac_50_p_2:.4f}")
print(f"  Sum (Rubinstein):     {ac_50_c + ac_50_p_2:.4f}")
print(f"  MC chooser:           {ac_50_co:.4f}")
print(f"  Market bid/ask:       22.200 / 22.300")

print()
print("── Binary put details ────────────────────────────────────────────────────")
p_below_40 = np.mean(S_T3 < 40)
print(f"  P(S_T3 < 40):         {p_below_40:.4f}  ({p_below_40*100:.1f}%)")
print(f"  Fair value (×10):     {ac_40_bp:.4f}")
print(f"  Market bid/ask:        5.000 /  5.100")
print(f"  Edge if buy at 5.1:   {ac_40_bp - 5.1:.4f}")
print(f"  Edge if sell at 5.0:  {5.0 - ac_40_bp:.4f}")
