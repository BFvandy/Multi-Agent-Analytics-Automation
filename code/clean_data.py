"""
Data cleaning script:
- Remaps years: 2013 → 2023, 2014 → 2024, 2015 → 2025
- Reformats dates to DD/MM/YYYY (e.g. 01/09/2025)
- Saves cleaned file as India_cc_transactions_cleaned.csv
"""

import pandas as pd
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent.parent
INPUT_CSV  = BASE_DIR / "data" / "India_cc_transactions.csv"
OUTPUT_CSV = BASE_DIR / "data" / "India_cc_transactions_cleaned.csv"

YEAR_MAP = {2013: 2023, 2014: 2024, 2015: 2025}

# ── Load ──────────────────────────────────────────────────────────────────────
print(f"Loading: {INPUT_CSV}")
df = pd.read_csv(INPUT_CSV)
df.columns = [c.strip() for c in df.columns]

print(f"Rows loaded: {len(df):,}")
print(f"Raw date sample: {df['Date'].head(3).tolist()}")

# ── Parse dates ───────────────────────────────────────────────────────────────
df["Date"] = pd.to_datetime(df["Date"], format="%d-%b-%y")

print(f"\nYear distribution BEFORE remap:")
print(df["Date"].dt.year.value_counts().sort_index().to_string())

# ── Remap years ───────────────────────────────────────────────────────────────
def remap_year(date):
    new_year = YEAR_MAP.get(date.year, date.year)
    return date.replace(year=new_year)

df["Date"] = df["Date"].apply(remap_year)

print(f"\nYear distribution AFTER remap:")
print(df["Date"].dt.year.value_counts().sort_index().to_string())

# ── Reformat to DD/MM/YYYY ────────────────────────────────────────────────────
df["Date"] = df["Date"].dt.strftime("%m/%d/%Y")

print(f"\nFormatted date sample: {df['Date'].head(3).tolist()}")

# ── Save ──────────────────────────────────────────────────────────────────────
df.to_csv(OUTPUT_CSV, index=False)
print(f"\nSaved cleaned file to: {OUTPUT_CSV}")
print("Done!")
