"""
Analytics tools for the Analyst Agent.
Reference date is driven by REFERENCE_DATE — change one line (or .env) to shift the entire analysis window.
Data file is driven by DATA_FILE — change one line (or .env) to switch datasets.
Default: October 1, 2015 (analyzing September 2015)
"""

import pandas as pd
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _json_default(o):
    """Convert numpy scalar types that the standard json encoder can't handle."""
    if hasattr(o, "item"):   # numpy int64, float64, bool_, etc.
        return o.item()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


# ── Data Source ───────────────────────────────────────────────────────────────
# To switch datasets, change DATA_FILE here OR set DATA_FILE in your .env
# Example: DATA_FILE=US_cc_transactions.csv

DATA_FILE = os.environ.get("DATA_FILE", "India_cc_transactions.csv")

# Path resolved automatically relative to this file — works from any directory
BASE_DIR    = Path(__file__).resolve().parent.parent
DEFAULT_CSV = str(BASE_DIR / "data" / DATA_FILE)

# ── Analysis Configuration ────────────────────────────────────────────────────
# To change the analysis window, change REFERENCE_DATE here OR set it in your .env
# Example: REFERENCE_DATE=2015-11-01 → analyzes October 2015

REFERENCE_DATE = pd.Timestamp(os.environ.get("REFERENCE_DATE", "2025-03-01"))

# All periods derived automatically from REFERENCE_DATE
_current    = REFERENCE_DATE - pd.DateOffset(months=1)
_prior      = REFERENCE_DATE - pd.DateOffset(months=2)
_prior_year = _current - pd.DateOffset(years=1)

CURRENT_MONTH    = (_current.year, _current.month)
PRIOR_MONTH      = (_prior.year, _prior.month)
PRIOR_YEAR_MONTH = (_prior_year.year, _prior_year.month)

ROLLING_END      = REFERENCE_DATE - pd.Timedelta(days=1)
ROLLING_START    = ROLLING_END - pd.Timedelta(days=6)
ROLLING_END_PY   = ROLLING_END - pd.DateOffset(years=1)
ROLLING_START_PY = ROLLING_START - pd.DateOffset(years=1)


def _period_label(year: int, month: int) -> str:
    return pd.Timestamp(year=year, month=month, day=1).strftime("%b %Y")


# ── Data loading ──────────────────────────────────────────────────────────────

_df: pd.DataFrame | None = None

def load_data(csv_path: str = DEFAULT_CSV) -> pd.DataFrame:
    global _df
    if _df is None:
        print(f"Loading data from: {csv_path}")
        _df = pd.read_csv(csv_path)
        _df["Date"] = pd.to_datetime(_df["Date"], format="mixed")
        _df.columns = [c.strip() for c in _df.columns]
        _df["Amount"] = pd.to_numeric(_df["Amount"], errors="coerce")
        _df = _df.dropna(subset=["Amount", "Date"])
        print(f"Loaded {len(_df):,} rows successfully.")
    return _df


def _month_filter(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    return df[(df["Date"].dt.year == year) & (df["Date"].dt.month == month)]


# ── Tool 1: Overall monthly summary ──────────────────────────────────────────

def get_overall_monthly_summary(csv_path: str = DEFAULT_CSV) -> str:
    """
    Returns overall spend and transaction volume for:
    - Current month vs prior month (MoM)
    - Current month vs prior year same month (YoY)
    All periods derived from REFERENCE_DATE.
    """
    df = load_data(csv_path)

    cur  = _month_filter(df, *CURRENT_MONTH)
    prev = _month_filter(df, *PRIOR_MONTH)
    py   = _month_filter(df, *PRIOR_YEAR_MONTH)

    cur_spend  = cur["Amount"].sum()
    prev_spend = prev["Amount"].sum()
    py_spend   = py["Amount"].sum()

    result = {
        "reference_date":   REFERENCE_DATE.strftime("%Y-%m-%d"),
        "current_month":    _period_label(*CURRENT_MONTH),
        "prior_month":      _period_label(*PRIOR_MONTH),
        "prior_year_month": _period_label(*PRIOR_YEAR_MONTH),
        "spend": {
            "current":     round(cur_spend, 2),
            "prior_month": round(prev_spend, 2),
            "prior_year":  round(py_spend, 2),
        },
        "transaction_volume": {
            "current":     int(len(cur)),
            "prior_month": int(len(prev)),
            "prior_year":  int(len(py)),
        },
        "mom_delta_spend":       round(cur_spend - prev_spend, 2),
        "mom_pct_change":        round((cur_spend / prev_spend - 1) * 100, 2) if prev_spend != 0 else None,
        "yoy_pct":               round((cur_spend / py_spend - 1) * 100, 2) if py_spend != 0 else None,
        "mom_volume_delta":      int(len(cur) - len(prev)),
        "mom_volume_pct_change": round((len(cur) / len(prev) - 1) * 100, 2) if len(prev) != 0 else None,
    }
    return json.dumps(result, indent=2, default=_json_default)


# ── Tool 2: YoY + CTG decomposition by dimension ─────────────────────────────

def get_dimension_decomposition(
    dimension: str,
    csv_path: str = DEFAULT_CSV
) -> str:
    """
    For a given dimension (Exp Type | City | Card Type), returns per-segment:
    - Spend for current month and prior year same month
    - YoY %: (segment_current / segment_prior_year) - 1
    - CTG %: (segment_current - segment_prior_year) / total_prior_year_spend
    - Verification: sum of all CTGs == total portfolio YoY

    dimension must be one of: 'Exp Type', 'City', 'Card Type'
    """
    # valid_dims = ["Exp Type", "City", "Card Type"]
    valid_dims = ["Exp Type", "Card Type"]
    if dimension not in valid_dims:
        return json.dumps({"error": f"dimension must be one of {valid_dims}"}, default=_json_default)

    df = load_data(csv_path)

    cur = _month_filter(df, *CURRENT_MONTH)
    py  = _month_filter(df, *PRIOR_YEAR_MONTH)

    total_py  = py["Amount"].sum()
    total_cur = cur["Amount"].sum()
    total_yoy = round((total_cur / total_py - 1) * 100, 4) if total_py != 0 else None

    cur_grp = cur.groupby(dimension)["Amount"].sum().rename("cur")
    py_grp  = py.groupby(dimension)["Amount"].sum().rename("py")

    combined = pd.concat([cur_grp, py_grp], axis=1).fillna(0)
    combined["yoy_pct"] = (
        ((combined["cur"] / combined["py"] - 1) * 100)
        .where(combined["py"] != 0)
        .round(2)
    )
    combined["ctg_pct"] = ((combined["cur"] - combined["py"]) / total_py * 100).round(4)

    ctg_sum = round(combined["ctg_pct"].sum(), 4)

    result = {
        "reference_date":          REFERENCE_DATE.strftime("%Y-%m-%d"),
        "dimension":               dimension,
        "period":                  f"{_period_label(*CURRENT_MONTH)} vs {_period_label(*PRIOR_YEAR_MONTH)}",
        "total_portfolio_yoy_pct": total_yoy,
        "total_prior_year_spend":  round(total_py, 2),
        "segments": [
            {
                dimension:          row[dimension],
                "spend_current":    round(row["cur"], 2),
                "spend_prior_year": round(row["py"], 2),
                "yoy_pct":          row["yoy_pct"],
                "ctg_pct":          row["ctg_pct"],
            }
            for row in combined.reset_index().to_dict(orient="records")
        ],
        "ctg_sum_check":        ctg_sum,
        "ctg_equals_total_yoy": abs(ctg_sum - total_yoy) < 0.05 if total_yoy else None,
    }
    return json.dumps(result, indent=2, default=_json_default)


# ── Tool 3: 7-day rolling average ────────────────────────────────────────────

def get_rolling_average(csv_path: str = DEFAULT_CSV) -> str:
    """
    Computes 7-day rolling average spend and its YoY.
    Window = last 7 days of current month, derived from REFERENCE_DATE.
    Rolling Avg     = SUM(daily spend in window) / 7
    Rolling Avg YoY = (rolling_avg_current / rolling_avg_prior_year) - 1
    """
    df = load_data(csv_path)

    cur_window = df[(df["Date"] >= ROLLING_START) & (df["Date"] <= ROLLING_END)]
    py_window  = df[(df["Date"] >= ROLLING_START_PY) & (df["Date"] <= ROLLING_END_PY)]

    cur_rolling_avg = round(cur_window["Amount"].sum() / 7, 2)
    py_rolling_avg  = round(py_window["Amount"].sum() / 7, 2)
    rolling_yoy     = round((cur_rolling_avg / py_rolling_avg - 1) * 100, 2) if py_rolling_avg != 0 else None

    cur_daily = cur_window.groupby("Date")["Amount"].sum().reset_index()
    cur_daily["Date"] = cur_daily["Date"].dt.strftime("%Y-%m-%d")

    result = {
        "reference_date":               REFERENCE_DATE.strftime("%Y-%m-%d"),
        "window_current":               f"{ROLLING_START.strftime('%b %d')}–{ROLLING_END.strftime('%b %d, %Y')}",
        "window_prior_year":            f"{ROLLING_START_PY.strftime('%b %d')}–{ROLLING_END_PY.strftime('%b %d, %Y')}",
        "rolling_avg_current":          cur_rolling_avg,
        "rolling_avg_prior_year":       py_rolling_avg,
        "rolling_avg_yoy_pct":          rolling_yoy,
        "daily_spend_current_window":   cur_daily.to_dict(orient="records"),
        "total_transactions_in_window": int(len(cur_window)),
    }
    return json.dumps(result, indent=2, default=_json_default)


# ── Tool 4: Drill-down into a specific segment ───────────────────────────────

def drill_down_segment(
    dimension: str,
    segment_value: str,
    csv_path: str = DEFAULT_CSV
) -> str:
    """
    Deep dives into a specific segment (e.g. dimension='Exp Type', segment_value='Food').
    Returns MoM, YoY, CTG for this segment plus cross-dimension breakdown.
    """
    df = load_data(csv_path)

    seg_df = df[df[dimension] == segment_value]
    cur  = _month_filter(seg_df, *CURRENT_MONTH)
    prev = _month_filter(seg_df, *PRIOR_MONTH)
    py   = _month_filter(seg_df, *PRIOR_YEAR_MONTH)

    total_py_all = _month_filter(df, *PRIOR_YEAR_MONTH)["Amount"].sum()

    seg_yoy = round((cur["Amount"].sum() / py["Amount"].sum() - 1) * 100, 2) if py["Amount"].sum() != 0 else None
    seg_ctg = round(((cur["Amount"].sum() - py["Amount"].sum()) / total_py_all) * 100, 4) if total_py_all != 0 else None

    # other_dims = [d for d in ["Exp Type", "City", "Card Type"] if d != dimension]
    other_dims = [d for d in ["Exp Type", "Card Type"] if d != dimension]
    cross_tabs = {}
    for other in other_dims:
        cur_grp = cur.groupby(other)["Amount"].sum().rename("cur")
        py_grp  = _month_filter(seg_df, *PRIOR_YEAR_MONTH).groupby(other)["Amount"].sum().rename("py")
        ct = pd.concat([cur_grp, py_grp], axis=1).fillna(0)
        ct["yoy_pct"] = round((ct["cur"] / ct["py"] - 1) * 100, 2).where(ct["py"] != 0)
        ct["ctg_within_segment"] = (
            round(((ct["cur"] - ct["py"]) / py["Amount"].sum()) * 100, 4)
            if py["Amount"].sum() != 0 else None
        )
        cross_tabs[other] = ct.reset_index().to_dict(orient="records")

    result = {
        "reference_date":             REFERENCE_DATE.strftime("%Y-%m-%d"),
        "segment":                    f"{dimension} = {segment_value}",
        "period_current":             _period_label(*CURRENT_MONTH),
        "period_prior_month":         _period_label(*PRIOR_MONTH),
        "period_prior_year":          _period_label(*PRIOR_YEAR_MONTH),
        "spend_current":              round(cur["Amount"].sum(), 2),
        "spend_prior_month":          round(prev["Amount"].sum(), 2),
        "spend_prior_year":           round(py["Amount"].sum(), 2),
        "mom_delta":                  round(cur["Amount"].sum() - prev["Amount"].sum(), 2),
        "yoy_pct":                    seg_yoy,
        "ctg_pct_of_total_portfolio": seg_ctg,
        "cross_dimension_breakdown":  cross_tabs,
    }
    return json.dumps(result, indent=2, default=_json_default)


# ── Tool 5: Schema info ───────────────────────────────────────────────────────

def get_schema_info(csv_path: str = DEFAULT_CSV) -> str:
    """Returns schema, date range, sample stats, and current analysis periods."""
    df = load_data(csv_path)
    result = {
        "data_file":  DATA_FILE,
        "csv_path":   csv_path,
        "columns":    list(df.columns),
        "row_count":  len(df),
        "date_range": {
            "min": df["Date"].min().strftime("%Y-%m-%d"),
            "max": df["Date"].max().strftime("%Y-%m-%d"),
        },
        "unique_values": {
            col: sorted(df[col].dropna().unique().tolist())
            # for col in ["City", "Card Type", "Exp Type", "Gender"]
            for col in ["Card Type", "Exp Type", "Gender"]
            if col in df.columns
        },
        "amount_stats": {
            "min":        round(df["Amount"].min(), 2),
            "max":        round(df["Amount"].max(), 2),
            "mean":       round(df["Amount"].mean(), 2),
            "null_count": int(df["Amount"].isna().sum()),
        },
        "analysis_periods": {
            "reference_date":   REFERENCE_DATE.strftime("%Y-%m-%d"),
            "current_month":    _period_label(*CURRENT_MONTH),
            "prior_month":      _period_label(*PRIOR_MONTH),
            "prior_year_month": _period_label(*PRIOR_YEAR_MONTH),
            "rolling_window":   f"{ROLLING_START.strftime('%Y-%m-%d')} to {ROLLING_END.strftime('%Y-%m-%d')}",
        },
    }
    return json.dumps(result, indent=2, default=_json_default)
