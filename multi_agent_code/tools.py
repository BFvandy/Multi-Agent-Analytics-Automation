"""
tools.py — Consolidated tool definitions for the multi-agent analytics system.

Sections:
  1. Analytics Tools  (get_schema_info, get_overall_monthly_summary,
                       get_dimension_decomposition, get_rolling_average,
                       drill_down_segment)
  2. Web Search Tool  (web_search)
  3. Visualization Tool (generate_slide)

Usage:
  Call tools.init("2025-03-01") once at startup before running any analytics tools.
  This sets the reference date and derives all analysis periods from it.
"""

import os
import json
import http.client
import subprocess
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


# ═══════════════════════════════════════════════════════════════════════════════
# § 1  ANALYTICS TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

def _json_default(o):
    """Convert numpy scalar types that the standard json encoder can't handle."""
    if hasattr(o, "item"):   # numpy int64, float64, bool_, etc.
        return o.item()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


# ── Data source ───────────────────────────────────────────────────────────────

BQ_PROJECT  = os.environ.get("BQ_PROJECT", "fb2635-test-flask")
BQ_TABLE    = os.environ.get("BQ_TABLE", "fb2635-test-flask.fb2635.India_cc_transactions")
DATA_FILE   = os.environ.get("DATA_FILE", "India_cc_transactions.csv")
BASE_DIR    = Path(__file__).resolve().parent.parent
DEFAULT_CSV = str(BASE_DIR / "data" / DATA_FILE)
USE_CSV     = os.environ.get("USE_CSV", "false").lower() == "true"

# ── Dataset configuration ─────────────────────────────────────────────────────

from dataclasses import dataclass, field

@dataclass
class DatasetConfig:
    """
    Describes the schema of one dataset so all tools work generically.

    date_col      : name of the date/month column
    value_col     : name of the numeric metric column (spend, revenue, etc.)
    dimensions    : all categorical columns available for decomposition
    primary_dim   : first dimension to decompose in Step 3 (e.g. "Card Type")
    secondary_dim : dimension drilled into in Step 4 within the primary segment
    value_label   : human-readable label for the value column (for display)
    """
    date_col:      str
    value_col:     str
    dimensions:    list[str]
    primary_dim:   str
    secondary_dim: str
    value_label:   str = "Spend"


# ── Built-in presets — select via DATASET_PRESET in .env ─────────────────────

DATASET_PRESETS: dict[str, DatasetConfig] = {
    "credit_card": DatasetConfig(
        date_col      = "Date",
        value_col     = "Amount",
        dimensions    = ["Card Type", "Exp Type"],
        primary_dim   = "Card Type",
        secondary_dim = "Exp Type",
        value_label   = "Spend",
    ),
    "global_ads": DatasetConfig(
        date_col      = "month",
        value_col     = "total_revenue",
        dimensions    = ["platform", "campaign_type", "industry", "country"],
        primary_dim   = "platform",
        secondary_dim = "campaign_type",
        value_label   = "Revenue",
    ),
}

# Active config — populated by init()
DATASET_CONFIG: DatasetConfig | None = None

# ── Analysis periods (populated by init()) ────────────────────────────────────

REFERENCE_DATE:   pd.Timestamp | None = None
CURRENT_MONTH:    tuple | None = None
PRIOR_MONTH:      tuple | None = None
PRIOR_YEAR_MONTH: tuple | None = None
ROLLING_END:      pd.Timestamp | None = None
ROLLING_START:    pd.Timestamp | None = None
ROLLING_END_PY:   pd.Timestamp | None = None
ROLLING_START_PY: pd.Timestamp | None = None


def init(reference_date: str, dataset_preset: str | None = None) -> None:
    """
    Set the reference date, derive all analysis periods, and load dataset config.

    Args:
        reference_date:  YYYY-MM-DD string, e.g. "2025-03-01".
                         Analyzes the month immediately before this date.
        dataset_preset:  Optional preset name from DATASET_PRESETS.
                         If None, reads DATASET_PRESET from .env (default: "credit_card").
                         Can also be a custom DatasetConfig passed directly.
    """
    global REFERENCE_DATE, CURRENT_MONTH, PRIOR_MONTH, PRIOR_YEAR_MONTH
    global ROLLING_END, ROLLING_START, ROLLING_END_PY, ROLLING_START_PY
    global DATASET_CONFIG

    # ── Periods ───────────────────────────────────────────────
    REFERENCE_DATE = pd.Timestamp(reference_date)

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

    # ── Dataset config ────────────────────────────────────────
    if isinstance(dataset_preset, DatasetConfig):
        DATASET_CONFIG = dataset_preset
    else:
        preset_name = dataset_preset or os.environ.get("DATASET_PRESET", "credit_card")
        if preset_name not in DATASET_PRESETS:
            raise ValueError(
                f"Unknown dataset preset '{preset_name}'. "
                f"Available: {list(DATASET_PRESETS.keys())}"
            )
        DATASET_CONFIG = DATASET_PRESETS[preset_name]

    print(f"[tools] Reference date  : {REFERENCE_DATE.strftime('%Y-%m-%d')}")
    print(f"[tools] Analyzing       : {_period_label(*CURRENT_MONTH)} "
          f"(vs {_period_label(*PRIOR_MONTH)} MoM, vs {_period_label(*PRIOR_YEAR_MONTH)} YoY)")
    print(f"[tools] Dataset config  : {DATASET_CONFIG}")


def _check_init():
    if REFERENCE_DATE is None or DATASET_CONFIG is None:
        raise RuntimeError(
            "tools.init() has not been called. "
            "Call tools.init('YYYY-MM-DD') before using any analytics tools."
        )


def _cfg() -> DatasetConfig:
    """Shorthand — returns active DatasetConfig."""
    return DATASET_CONFIG


def _period_label(year: int, month: int) -> str:
    return pd.Timestamp(year=year, month=month, day=1).strftime("%b %Y")


# ── Data loading ──────────────────────────────────────────────────────────────

import threading as _threading
_df: pd.DataFrame | None = None
_df_lock = _threading.Lock()


def load_data(csv_path: str = DEFAULT_CSV) -> pd.DataFrame:
    """
    Load transaction data from BigQuery (default) or local CSV (fallback).
    Thread-safe — only queries once regardless of concurrent callers.
    """
    global _df
    if _df is not None:
        return _df

    with _df_lock:
        if _df is not None:   # another thread may have loaded while we waited
            return _df

        if USE_CSV:
            print(f"[tools] Loading from CSV: {csv_path}")
            _df = pd.read_csv(csv_path)
        else:
            try:
                from google.cloud import bigquery
            except ImportError:
                raise ImportError(
                    "google-cloud-bigquery is not installed. "
                    "Run: pip install google-cloud-bigquery db-dtypes pyarrow"
                )
            print(f"[tools] Loading from BigQuery: {BQ_TABLE}")
            client = bigquery.Client(project=BQ_PROJECT)
            query  = f"SELECT * FROM `{BQ_TABLE}`"
            _df    = client.query(query).to_dataframe()
            print(f"[tools] Query complete.")

        _df.columns = [c.strip() for c in _df.columns]
        date_col    = _cfg().date_col  if DATASET_CONFIG else "Date"
        value_col   = _cfg().value_col if DATASET_CONFIG else "Amount"
        _df[date_col]  = pd.to_datetime(_df[date_col], format="mixed")
        _df[value_col] = pd.to_numeric(_df[value_col], errors="coerce")
        _df            = _df.dropna(subset=[value_col, date_col])
        print(f"[tools] Loaded {len(_df):,} rows successfully.")
        return _df


def _month_filter(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    dc = _cfg().date_col
    return df[(df[dc].dt.year == year) & (df[dc].dt.month == month)]


# ── Tool 1: Schema info ───────────────────────────────────────────────────────

def get_schema_info(csv_path: str = DEFAULT_CSV) -> str:
    """Returns schema, date range, sample stats, current analysis periods, and dataset config."""
    _check_init()
    df  = load_data(csv_path)
    cfg = _cfg()
    result = {
        "data_source":  BQ_TABLE if not USE_CSV else DATA_FILE,
        "columns":      list(df.columns),
        "row_count":    len(df),
        "date_range": {
            "min": df[cfg.date_col].min().strftime("%Y-%m-%d"),
            "max": df[cfg.date_col].max().strftime("%Y-%m-%d"),
        },
        "dataset_config": {
            "date_col":      cfg.date_col,
            "value_col":     cfg.value_col,
            "value_label":   cfg.value_label,
            "dimensions":    cfg.dimensions,
            "primary_dim":   cfg.primary_dim,
            "secondary_dim": cfg.secondary_dim,
        },
        "unique_values": {
            col: sorted(df[col].dropna().unique().tolist())
            for col in cfg.dimensions
            if col in df.columns
        },
        "value_stats": {
            "min":        round(df[cfg.value_col].min(), 2),
            "max":        round(df[cfg.value_col].max(), 2),
            "mean":       round(df[cfg.value_col].mean(), 2),
            "null_count": int(df[cfg.value_col].isna().sum()),
        },
        "analysis_periods": {
            "reference_date":   REFERENCE_DATE.strftime("%Y-%m-%d"),
            "current_month":    _period_label(*CURRENT_MONTH),
            "prior_month":      _period_label(*PRIOR_MONTH),
            "prior_year_month": _period_label(*PRIOR_YEAR_MONTH),
        },
    }
    return json.dumps(result, indent=2, default=_json_default)


# ── Tool 2: Overall monthly summary ──────────────────────────────────────────

def get_overall_monthly_summary(csv_path: str = DEFAULT_CSV) -> str:
    """
    Returns overall spend and transaction volume for:
    - Current month vs prior month (MoM)
    - Current month vs prior year same month (YoY)
    All periods derived from REFERENCE_DATE.
    """
    _check_init()
    df = load_data(csv_path)

    vc   = _cfg().value_col
    cur  = _month_filter(df, *CURRENT_MONTH)
    prev = _month_filter(df, *PRIOR_MONTH)
    py   = _month_filter(df, *PRIOR_YEAR_MONTH)

    cur_spend  = cur[vc].sum()
    prev_spend = prev[vc].sum()
    py_spend   = py[vc].sum()

    result = {
        "reference_date":   REFERENCE_DATE.strftime("%Y-%m-%d"),
        "current_month":    _period_label(*CURRENT_MONTH),
        "prior_month":      _period_label(*PRIOR_MONTH),
        "prior_year_month": _period_label(*PRIOR_YEAR_MONTH),
        "value_label":      _cfg().value_label,
        f"{_cfg().value_label.lower()}": {
            "current":     round(cur_spend, 2),
            "prior_month": round(prev_spend, 2),
            "prior_year":  round(py_spend, 2),
        },
        "transaction_volume": {
            "current":     int(len(cur)),
            "prior_month": int(len(prev)),
            "prior_year":  int(len(py)),
        },
        "mom_delta":             round(cur_spend - prev_spend, 2),
        "mom_pct_change":        round((cur_spend / prev_spend - 1) * 100, 2) if prev_spend != 0 else None,
        "yoy_pct":               round((cur_spend / py_spend - 1) * 100, 2) if py_spend != 0 else None,
        "mom_volume_delta":      int(len(cur) - len(prev)),
        "mom_volume_pct_change": round((len(cur) / len(prev) - 1) * 100, 2) if len(prev) != 0 else None,
    }
    return json.dumps(result, indent=2, default=_json_default)


# ── Tool 3: YoY + CTG decomposition by dimension ─────────────────────────────

def get_dimension_decomposition(
    dimension: str,
    csv_path: str = DEFAULT_CSV,
) -> str:
    """
    For a given dimension column, returns per-segment:
    - Value for current month and prior year same month
    - YoY %: (segment_current / segment_prior_year) - 1
    - CTG %: (segment_current - segment_prior_year) / total_prior_year_value
    - Verification: sum of all CTGs == total portfolio YoY

    dimension must be one of the configured dimensions for this dataset.
    """
    _check_init()
    cfg        = _cfg()
    valid_dims = cfg.dimensions
    if dimension not in valid_dims:
        return json.dumps({"error": f"dimension must be one of {valid_dims}"}, default=_json_default)

    df = load_data(csv_path)
    vc = cfg.value_col

    cur = _month_filter(df, *CURRENT_MONTH)
    py  = _month_filter(df, *PRIOR_YEAR_MONTH)

    total_py  = py[vc].sum()
    total_cur = cur[vc].sum()
    total_yoy = round((total_cur / total_py - 1) * 100, 4) if total_py != 0 else None

    cur_grp = cur.groupby(dimension)[vc].sum().rename("cur")
    py_grp  = py.groupby(dimension)[vc].sum().rename("py")

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
        "total_prior_year_value":  round(total_py, 2),
        "segments": [
            {
                dimension:           row[dimension],
                "value_current":     round(row["cur"], 2),
                "value_prior_year":  round(row["py"], 2),
                "yoy_pct":           row["yoy_pct"],
                "ctg_pct":           row["ctg_pct"],
            }
            for row in combined.reset_index().to_dict(orient="records")
        ],
        "ctg_sum_check":        ctg_sum,
        "ctg_equals_total_yoy": abs(ctg_sum - total_yoy) < 0.05 if total_yoy else None,
    }
    return json.dumps(result, indent=2, default=_json_default)


# ── Tool 3b: 12-month YoY trend + CTG chart data ─────────────────────────────

def get_trend_charts(
    dimension: str,
    csv_path: str = DEFAULT_CSV,
) -> str:
    """
    Computes month-by-month YoY % and CTG % for each segment over the last 12
    completed months before the reference date.

    dimension must be one of the configured dimensions for this dataset.
    """
    _check_init()
    cfg        = _cfg()
    valid_dims = cfg.dimensions
    if dimension not in valid_dims:
        return json.dumps({"error": f"dimension must be one of {valid_dims}"}, default=_json_default)

    df = load_data(csv_path)
    vc = cfg.value_col

    months = []
    for i in range(11, -1, -1):
        ts = REFERENCE_DATE - pd.DateOffset(months=i + 1)
        months.append((ts.year, ts.month))

    segments = sorted(df[dimension].dropna().unique().tolist())

    yoy_series: dict[str, list] = {s: [] for s in segments}
    ctg_series: dict[str, list] = {s: [] for s in segments}
    month_labels: list[str] = []

    for (yr, mo) in months:
        month_labels.append(_period_label(yr, mo))
        month_df     = _month_filter(df, yr, mo)
        py_df        = _month_filter(df, yr - 1, mo)

        total_py = py_df[vc].sum()

        cur_grp = month_df.groupby(dimension)[vc].sum()
        py_grp  = py_df.groupby(dimension)[vc].sum()

        for seg in segments:
            cur_val = cur_grp.get(seg, 0.0)
            py_val  = py_grp.get(seg, 0.0)

            yoy = round((cur_val / py_val - 1) * 100, 2) if py_val != 0 else None
            ctg = round((cur_val - py_val) / total_py * 100, 4) if total_py != 0 else None

            yoy_series[seg].append(yoy)
            ctg_series[seg].append(ctg)
            py_val  = py_grp.get(seg, 0.0)

            yoy = round((cur_val / py_val - 1) * 100, 2) if py_val != 0 else None
            ctg = round((cur_val - py_val) / total_py * 100, 4) if total_py != 0 else None

            yoy_series[seg].append(yoy)
            ctg_series[seg].append(ctg)

    result = {
        "reference_date": REFERENCE_DATE.strftime("%Y-%m-%d"),
        "dimension":      dimension,
        "window":         f"{month_labels[0]} – {month_labels[-1]} (12 months)",
        "months":         month_labels,
        "segments":       segments,
        "yoy_series":     yoy_series,
        "ctg_series":     ctg_series,
    }
    return json.dumps(result, indent=2, default=_json_default)


# ── Tool 4: Segment-filtered Exp Type decomposition ──────────────────────────

def get_segment_decomposition(
    primary_segment_value: str,
    csv_path: str = DEFAULT_CSV,
) -> str:
    """
    Filters the dataset to a specific primary dimension value, then runs a full
    secondary dimension decomposition within that segment.

    For example with credit_card preset:
      primary_segment_value='Signature' → filters to Signature card,
      then decomposes by Exp Type within it.

    For global_ads preset:
      primary_segment_value='Google' → filters to Google platform,
      then decomposes by campaign_type within it.

    Args:
        primary_segment_value: Exact value from the primary_dim column
    """
    _check_init()
    cfg  = _cfg()
    df   = load_data(csv_path)
    vc   = cfg.value_col
    pd1  = cfg.primary_dim
    sd   = cfg.secondary_dim

    seg_df   = df[df[pd1] == primary_segment_value]
    cur_seg  = _month_filter(seg_df, *CURRENT_MONTH)
    py_seg   = _month_filter(seg_df, *PRIOR_YEAR_MONTH)
    prev_seg = _month_filter(seg_df, *PRIOR_MONTH)

    total_py_all   = _month_filter(df, *PRIOR_YEAR_MONTH)[vc].sum()
    seg_py_spend   = py_seg[vc].sum()
    seg_cur_spend  = cur_seg[vc].sum()
    seg_yoy        = round((seg_cur_spend / seg_py_spend - 1) * 100, 2) if seg_py_spend != 0 else None

    cur_grp = cur_seg.groupby(sd)[vc].sum().rename("cur")
    py_grp  = py_seg.groupby(sd)[vc].sum().rename("py")

    combined = pd.concat([cur_grp, py_grp], axis=1).fillna(0)
    combined["yoy_pct"] = (
        ((combined["cur"] / combined["py"] - 1) * 100)
        .where(combined["py"] != 0)
        .round(2)
    )
    combined["ctg_within_segment"] = (
        ((combined["cur"] - combined["py"]) / seg_py_spend * 100).round(4)
        if seg_py_spend != 0 else None
    )
    combined["ctg_total_portfolio"] = (
        ((combined["cur"] - combined["py"]) / total_py_all * 100).round(4)
        if total_py_all != 0 else None
    )

    segments = [
        {
            sd:                      row[sd],
            "value_current":         round(row["cur"], 2),
            "value_prior_year":      round(row["py"], 2),
            "yoy_pct":               row["yoy_pct"],
            "ctg_within_segment":    row["ctg_within_segment"],
            "ctg_total_portfolio":   row["ctg_total_portfolio"],
        }
        for row in combined.reset_index().to_dict(orient="records")
    ]
    segments.sort(key=lambda x: abs(x["ctg_within_segment"] or 0), reverse=True)

    result = {
        "reference_date":        REFERENCE_DATE.strftime("%Y-%m-%d"),
        "primary_dim":           pd1,
        "primary_segment":       primary_segment_value,
        "secondary_dim":         sd,
        "period":                f"{_period_label(*CURRENT_MONTH)} vs {_period_label(*PRIOR_YEAR_MONTH)}",
        "segment_summary": {
            "value_current":         round(seg_cur_spend, 2),
            "value_prior_month":     round(prev_seg[vc].sum(), 2),
            "value_prior_year":      round(seg_py_spend, 2),
            "yoy_pct":               seg_yoy,
            "share_of_portfolio_py": round(seg_py_spend / total_py_all * 100, 2) if total_py_all != 0 else None,
        },
        "secondary_breakdown":       segments,
        "ctg_within_segment_sum":    round(combined["ctg_within_segment"].sum(), 4) if seg_py_spend != 0 else None,
        "ctg_total_portfolio_sum":   round(combined["ctg_total_portfolio"].sum(), 4) if total_py_all != 0 else None,
    }
    return json.dumps(result, indent=2, default=_json_default)


# ── Tool 4b: 7-day rolling average (kept for optional use) ───────────────────

def get_rolling_average(csv_path: str = DEFAULT_CSV) -> str:
    """
    Computes 7-day rolling average value and its YoY.
    Not registered in the analyst agent by default — call explicitly if needed.
    """
    _check_init()
    cfg = _cfg()
    df  = load_data(csv_path)
    vc  = cfg.value_col
    dc  = cfg.date_col

    cur_window = df[(df[dc] >= ROLLING_START) & (df[dc] <= ROLLING_END)]
    py_window  = df[(df[dc] >= ROLLING_START_PY) & (df[dc] <= ROLLING_END_PY)]

    cur_rolling_avg = round(cur_window[vc].sum() / 7, 2)
    py_rolling_avg  = round(py_window[vc].sum() / 7, 2)
    rolling_yoy     = round((cur_rolling_avg / py_rolling_avg - 1) * 100, 2) if py_rolling_avg != 0 else None

    cur_daily = cur_window.groupby(dc)[vc].sum().reset_index()
    cur_daily[dc] = cur_daily[dc].dt.strftime("%Y-%m-%d")

    result = {
        "reference_date":             REFERENCE_DATE.strftime("%Y-%m-%d"),
        "window_current":             f"{ROLLING_START.strftime('%b %d')}–{ROLLING_END.strftime('%b %d, %Y')}",
        "window_prior_year":          f"{ROLLING_START_PY.strftime('%b %d')}–{ROLLING_END_PY.strftime('%b %d, %Y')}",
        "rolling_avg_current":        cur_rolling_avg,
        "rolling_avg_prior_year":     py_rolling_avg,
        "rolling_avg_yoy_pct":        rolling_yoy,
        "daily_values_current_window": cur_daily.to_dict(orient="records"),
        "total_records_in_window":    int(len(cur_window)),
    }
    return json.dumps(result, indent=2, default=_json_default)


# ── Tool 5: Drill-down into a specific segment ───────────────────────────────

def drill_down_segment(
    dimension: str,
    segment_value: str,
    csv_path: str = DEFAULT_CSV,
) -> str:
    """
    Deep dives into a specific segment value within any dimension.
    Returns MoM, YoY, CTG for this segment plus cross-dimension breakdown.
    dimension must be one of the configured dimensions for this dataset.
    """
    _check_init()
    _check_init()
    cfg = _cfg()
    df  = load_data(csv_path)
    vc  = cfg.value_col

    if dimension not in cfg.dimensions:
        return json.dumps({"error": f"dimension must be one of {cfg.dimensions}"}, default=_json_default)

    seg_df = df[df[dimension] == segment_value]
    cur    = _month_filter(seg_df, *CURRENT_MONTH)
    prev   = _month_filter(seg_df, *PRIOR_MONTH)
    py     = _month_filter(seg_df, *PRIOR_YEAR_MONTH)

    total_py_all = _month_filter(df, *PRIOR_YEAR_MONTH)[vc].sum()
    cur_val  = cur[vc].sum()
    prev_val = prev[vc].sum()
    py_val   = py[vc].sum()

    seg_yoy = round((cur_val / py_val - 1) * 100, 2) if py_val != 0 else None
    seg_ctg = round(((cur_val - py_val) / total_py_all) * 100, 4) if total_py_all != 0 else None

    other_dims = [d for d in cfg.dimensions if d != dimension]
    cross_tabs = {}
    for other in other_dims:
        cur_grp = cur.groupby(other)[vc].sum().rename("cur")
        py_grp  = _month_filter(seg_df, *PRIOR_YEAR_MONTH).groupby(other)[vc].sum().rename("py")
        ct = pd.concat([cur_grp, py_grp], axis=1).fillna(0)
        ct["yoy_pct"] = round((ct["cur"] / ct["py"] - 1) * 100, 2).where(ct["py"] != 0)
        ct["ctg_within_segment"] = (
            round(((ct["cur"] - ct["py"]) / py_val) * 100, 4)
            if py_val != 0 else None
        )
        cross_tabs[other] = ct.reset_index().to_dict(orient="records")

    result = {
        "reference_date":             REFERENCE_DATE.strftime("%Y-%m-%d"),
        "segment":                    f"{dimension} = {segment_value}",
        "period_current":             _period_label(*CURRENT_MONTH),
        "period_prior_month":         _period_label(*PRIOR_MONTH),
        "period_prior_year":          _period_label(*PRIOR_YEAR_MONTH),
        "value_current":              round(cur_val, 2),
        "value_prior_month":          round(prev_val, 2),
        "value_prior_year":           round(py_val, 2),
        "mom_delta":                  round(cur_val - prev_val, 2),
        "yoy_pct":                    seg_yoy,
        "ctg_pct_of_total_portfolio": seg_ctg,
        "cross_dimension_breakdown":  cross_tabs,
    }
    return json.dumps(result, indent=2, default=_json_default)


# ═══════════════════════════════════════════════════════════════════════════════
# § 2  WEB SEARCH TOOL
# ═══════════════════════════════════════════════════════════════════════════════

SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")


def web_search(query: str, num_results: int = 5) -> str:
    """
    Search the web using Serper.dev and return top results.
    Use this to find external factors, news, and context explaining spend trends.

    Args:
        query:       Search query string
        num_results: Number of results to return (default 5)

    Returns:
        JSON string with search results including title, snippet, and link
    """
    if not SERPER_API_KEY:
        return json.dumps({"error": "SERPER_API_KEY not set in .env"})

    try:
        conn = http.client.HTTPSConnection("google.serper.dev")
        payload = json.dumps({"q": query, "num": num_results})
        headers = {
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json",
        }
        conn.request("POST", "/search", payload, headers)
        res = conn.getresponse()
        data = json.loads(res.read().decode("utf-8"))

        results = []
        for item in data.get("organic", [])[:num_results]:
            results.append({
                "title":   item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link":    item.get("link", ""),
                "date":    item.get("date", ""),
            })

        return json.dumps({
            "query":        query,
            "result_count": len(results),
            "results":      results,
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e), "query": query})


# ═══════════════════════════════════════════════════════════════════════════════
# § 3  VISUALIZATION TOOL
# ═══════════════════════════════════════════════════════════════════════════════

_TOOLS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR  = _TOOLS_DIR.parent / "output"
JS_SCRIPT   = _TOOLS_DIR / "generate_slide.js"


def generate_slide(
    title: str,
    subtitle: str,
    bullets: list,
    chart_title: str,
    chart_data: list,
    table_title: str,
    table_data: list,
    footnote: str,
    output_filename: str = "analytics_output.pptx",
) -> str:
    """
    Generate a professional PowerPoint slide with chart and data table.

    Args:
        title:           Headline sentence summarizing the key finding
        subtitle:        Month and reference date context line
        bullets:         List of 3-5 key insight strings
        chart_title:     Title for the bar chart
        chart_data:      List of dicts: [{"label": "Signature", "value": 15.1, "ctg": 3.51}, ...]
        table_title:     Title for the data table
        table_data:      2D list — first row is headers, rest are data rows
        footnote:        Small explanatory text below the table
        output_filename: Name of the output .pptx file

    Returns:
        JSON string with status and output file path
    """
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(OUTPUT_DIR / output_filename)

        slide_data = {
            "title":      title,
            "subtitle":   subtitle,
            "bullets":    bullets,
            "chartTitle": chart_title,
            "chartData":  chart_data,
            "tableTitle": table_title,
            "tableData":  table_data,
            "footnote":   footnote,
            "outputPath": output_path,
        }

        payload_path = _TOOLS_DIR / "_slide_payload.json"
        with open(payload_path, "w") as f:
            json.dump(slide_data, f, indent=2)

        # Resolve node binary — subprocess may not inherit shell PATH
        import shutil
        node_bin = shutil.which("node") or "node"

        result = subprocess.run(
            [node_bin, str(JS_SCRIPT), str(payload_path)],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PATH": os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin"},
        )

        payload_path.unlink(missing_ok=True)

        if result.returncode != 0:
            return json.dumps({
                "status": "error",
                "error":  result.stderr or result.stdout,
            })

        return json.dumps({
            "status":      "success",
            "output_path": output_path,
            "message":     f"Slide saved to {output_path}",
        })

    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})