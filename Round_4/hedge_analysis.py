import numpy as np

np.random.seed(42)

S0=50.; sigma=2.51; r=0.
STEPS_PER_YEAR=252*4
T2=40; T3=60
dt=1./STEPS_PER_YEAR
drift=(r-0.5*sigma**2)*dt
diff=sigma*np.sqrt(dt)
N=2_000_000

Z=np.random.randn(N,T3)
S=np.exp(np.log(S0)+np.cumsum(drift+diff*Z,axis=1))
S2=S[:,T2-1]; S3=S[:,T3-1]; Smin=np.min(S,axis=1)

print("=== Standard errors (2M sims) ===")
products = {
    'AC_50_P_2':  np.maximum(50-S2,0),
    'AC_50_C_2':  np.maximum(S2-50,0),
    'chooser':    np.where(S2>=50, np.maximum(S3-50,0), np.maximum(50-S3,0)),
    'binary_put': np.where(S3<40,10.,0.),
    'KO_put':     np.where(Smin<35, 0., np.maximum(45-S3,0)),
}
prices = {'AC_50_P_2':9.75, 'AC_50_C_2':9.75, 'chooser':22.20,
          'binary_put':5.00, 'KO_put':0.175}
sides  = {'AC_50_P_2':'BUY', 'AC_50_C_2':'BUY', 'chooser':'SELL',
          'binary_put':'SELL', 'KO_put':'BUY'}
vols   = {'AC_50_P_2':50, 'AC_50_C_2':50, 'chooser':50,
          'binary_put':50, 'KO_put':500}

print(f"{'Product':<15} {'MC Fair':>8} {'±2SE':>8} {'Edge':>8} {'Vol':>5} {'PnL':>8}")
print("-"*60)
for k,pnl in products.items():
    m=np.mean(pnl); se=np.std(pnl)/np.sqrt(N)
    price=prices[k]; side=sides[k]; v=vols[k]
    edge = (m-price) if side=='BUY' else (price-m)
    total=edge*v
    print(f"{k:<15} {m:8.4f} {2*se:8.4f} {edge:+8.4f} {v:5d} {total:+8.2f}")

print()
print("=== Hedge: Sell 50 chooser + Buy 50 AC_50_C (3wk) + Buy 50 AC_50_P_2 (2wk) ===")
call3  = np.maximum(S3-50,0)
put2   = np.maximum(50-S2,0)
choser = np.where(S2>=50, np.maximum(S3-50,0), np.maximum(50-S3,0))

hedge_pnl = (22.20-choser) + (call3-12.05) + (put2-9.75)
naked_pnl = 22.20-choser

print(f"  Hedged  — E[PnL]: {np.mean(hedge_pnl):+.4f}  Std/path: {np.std(hedge_pnl):.4f}")
print(f"  Naked   — E[PnL]: {np.mean(naked_pnl):+.4f}  Std/path: {np.std(naked_pnl):.4f}")
print(f"  Hedge reduces path-std by: {(1-np.std(hedge_pnl)/np.std(naked_pnl))*100:.1f}%")

print()
print("=== Full portfolio expected PnL (pre contract-size-3000 multiplier) ===")
# Sell 50 chooser + Buy 50 3wk call (hedge) + Buy 50 2wk put (hedge+edge)
# + Buy 50 2wk call + Sell 50 binary put + Buy 500 KO put
port = (
      50*(22.20-choser)       # short chooser
    + 50*(call3-12.05)        # long 3wk call (hedge)
    + 50*(put2-9.75)          # long 2wk put (hedge+edge)
    + 50*(np.maximum(S2-50,0)-9.75)    # long 2wk call
    + 50*(5.00-np.where(S3<40,10.,0.)) # short binary put
    + 500*(np.where(Smin<35,0.,np.maximum(45-S3,0))-0.175)  # long KO put
)

print(f"  Portfolio E[PnL]:  {np.mean(port):+.2f}")
print(f"  Portfolio Std:     {np.std(port):.2f}")
print(f"  Sharpe (E/Std):    {np.mean(port)/np.std(port):.4f}")
print(f"  P(PnL>0):          {np.mean(port>0)*100:.1f}%")
print(f"  P(PnL< -100):      {np.mean(port<-100)*100:.1f}%")
print()
print(f"  × contract size 3000 = {np.mean(port)*3000:+.0f} expected XIRECs")
print(f"  5th percentile:   {np.percentile(port,5):.2f} × 3000 = {np.percentile(port,5)*3000:.0f} XIRECs")
print(f"  95th percentile:  {np.percentile(port,95):.2f} × 3000 = {np.percentile(port,95)*3000:.0f} XIRECs")
