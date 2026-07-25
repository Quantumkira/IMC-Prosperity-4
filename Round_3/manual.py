import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# ==========================================
# 1. CORE GAME THEORY AND PNL LOGIC
# ==========================================


def calculate_pnl(b1, b2, b2_avg):
    """Calculates the expected PnL based on the game's strict rules."""
    # Counterparties from 670 to 920 in steps of 5
    reserves = np.arange(670, 925, 5)

    # Count how many counterparties fall into each bucket
    trades_b1 = np.sum(reserves <= b1)
    trades_b2 = np.sum((reserves > b1) & (reserves <= b2))

    # Calculate base profit margin per tier
    profit_b1 = trades_b1 * (920 - b1)
    base_profit_b2 = trades_b2 * (920 - b2)

    # Apply the game theory cubic penalty
    if b2 < b2_avg:
        penalty = ((920 - b2_avg) / (920 - b2)) ** 3
    else:
        penalty = 1.0

    profit_b2 = base_profit_b2 * penalty

    return profit_b1 + profit_b2


def get_optimal_bids(b2_avg):
    """Calculates the mathematically optimal bids given the market average."""
    # To avoid the penalty but maximize margin, b2 must equal the market average
    opt_b2 = b2_avg

    # Apply the exact mathematical derivation: b1 = (b2 + 665) / 2
    raw_b1 = (opt_b2 + 665) / 2

    # Round to the nearest valid increment of 5
    opt_b1 = round(raw_b1 / 5) * 5

    return opt_b1, opt_b2


# ==========================================
# 2. PARAMETERS & INITIALIZATION
# ==========================================

# Set your expected market average here
MARKET_AVG_B2 = 850

opt_b1, opt_b2 = get_optimal_bids(MARKET_AVG_B2)
max_pnl = calculate_pnl(opt_b1, opt_b2, MARKET_AVG_B2)

print(f"--- OPTIMAL STRATEGY ---")
print(f"Market Average b2: {MARKET_AVG_B2}")
print(f"Optimal First Bid (b1): {opt_b1}")
print(f"Optimal Second Bid (b2): {opt_b2}")
print(f"Maximum Expected PnL: {max_pnl:,.2f}\n")

# ==========================================
# 3. VISUALIZATIONS
# ==========================================

# Define the valid bidding range
bid_range = np.arange(670, 925, 5)

fig, axes = plt.subplots(1, 3, figsize=(18, 5))
sns.set_theme(style="darkgrid")

# --- Plot 1: Isolating b1 (Holding b2 at Optimal) ---
pnl_b1_varies = [calculate_pnl(b, opt_b2, MARKET_AVG_B2) for b in bid_range]

axes[0].plot(bid_range, pnl_b1_varies, color="blue", lw=2)
axes[0].axvline(opt_b1, color="red", linestyle="--", label=f"Optimal b1: {opt_b1}")
axes[0].set_title(f"Sensitivity of b1\n(Holding b2 fixed at {opt_b2})")
axes[0].set_xlabel("First Bid (b1)")
axes[0].set_ylabel("Total Expected PnL")
axes[0].legend()

# --- Plot 2: Isolating b2 (Holding b1 at Optimal) ---
pnl_b2_varies = [calculate_pnl(opt_b1, b, MARKET_AVG_B2) for b in bid_range]

axes[1].plot(bid_range, pnl_b2_varies, color="green", lw=2)
axes[1].axvline(
    opt_b2, color="red", linestyle="--", label=f"Optimal b2 (Avoids Penalty): {opt_b2}"
)
axes[1].set_title(f"Sensitivity of b2\n(Holding b1 fixed at {opt_b1})")
axes[1].set_xlabel("Second Bid (b2)")
axes[1].legend()

# Highlight the penalty zone
axes[1].axvspan(
    670, MARKET_AVG_B2 - 1, color="red", alpha=0.1, label="Cubic Penalty Zone"
)

# --- Plot 3: 2D Heatmap of the Combined Effect ---
# Create a grid for the heatmap
pnl_matrix = np.zeros((len(bid_range), len(bid_range)))

for i, b1 in enumerate(bid_range):
    for j, b2 in enumerate(bid_range):
        # Logically, b1 should not be greater than b2.
        if b1 <= b2:
            pnl_matrix[i, j] = calculate_pnl(b1, b2, MARKET_AVG_B2)
        else:
            pnl_matrix[i, j] = np.nan  # Mask invalid bid structures

# Plot heatmap
im = axes[2].imshow(
    pnl_matrix,
    origin="lower",
    extent=[670, 920, 670, 920],
    cmap="viridis",
    aspect="auto",
)
axes[2].set_title("Combined Effect: PnL Heatmap")
axes[2].set_xlabel("Second Bid (b2)")
axes[2].set_ylabel("First Bid (b1)")
fig.colorbar(im, ax=axes[2], label="Total PnL")

# Mark the absolute peak on the heatmap
axes[2].plot(
    opt_b2, opt_b1, marker="*", color="red", markersize=15, label="Absolute Max"
)
axes[2].legend()

plt.tight_layout()
plt.show()
