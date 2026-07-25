from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
INPUT_FILE = BASE / "voucher_df_with_implied_vol_bid_ask.csv"
OUTPUT_FILE = BASE / "all_days_data.csv"

if not INPUT_FILE.exists():
    raise FileNotFoundError(
        f"Input file not found: {INPUT_FILE}\n"
        "Make sure voucher_df_with_implied_vol_bid_ask.csv exists in the same folder."
    )

print(f"Loading input from {INPUT_FILE}")
raw = pd.read_csv(INPUT_FILE)

# Rename columns to expected names
column_mapping = {
    "T": "time_to_expiry",
    "strike": "strike_price",
    "mid_price_underlying": "underlying_price",
    "implied_vol_bid": "bid_implied_vol",
    "implied_vol_ask": "ask_implied_vol",
}
raw = raw.rename(columns=column_mapping)

# Only keep the first two trading days (day 0 and day 1)
# Timestamp is encoded in microseconds-like units with a day boundary at 1,000,000.
raw = raw[raw["timestamp"] < 2_000_000].copy()

# Add the day label if missing.
if "day" not in raw.columns:
    raw["day"] = (raw["timestamp"] // 1_000_000).astype(int)

# Filter invalid rows: time_to_expiry must be positive, prices must be positive
raw = raw[
    (raw["time_to_expiry"] > 0)
    & (raw["underlying_price"] > 0)
    & (raw["strike_price"] > 0)
].copy()

# Compute moneyness if missing.
if "moneyness" not in raw.columns:
    with np.errstate(divide="ignore", invalid="ignore"):
        raw["moneyness"] = np.log(
            raw["underlying_price"] / raw["strike_price"]
        ) / np.sqrt(raw["time_to_expiry"])

# Keep the expected column order.
columns = [
    "timestamp",
    "product",
    "ask_price_1",
    "strike_price",
    "time_to_expiry",
    "underlying_price",
    "bid_price_1",
    "ask_implied_vol",
    "bid_implied_vol",
    "moneyness",
    "day",
]

missing_cols = [c for c in columns if c not in raw.columns]
if missing_cols:
    raise ValueError(f"Missing required columns in input data: {missing_cols}")

output = raw[columns].copy()
output.to_csv(OUTPUT_FILE, index=False)
print(f"Saved {len(output)} rows to {OUTPUT_FILE}")
