"""
fetch_and_enrich.py
===================
Fetch Fred6725 RS CSVs, enrich liquid stocks with yfinance history, and
write enriched rankings plus diagnostics.
"""

from __future__ import annotations

import io
import os
import time
import glob
import math
import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import numpy as np
import pandas as pd
import yfinance as yf


MAX_WORKERS = int(os.environ.get("US_MAX_WORKERS", 10))
REQUEST_DELAY = float(os.environ.get("US_REQUEST_DELAY", 0.3))
PRICE_MIN = 5.0
VOL_MIN = 500_000
HISTORY_PERIOD = "18mo"
FILE_RETENTION_KEEP = 30
FRED_STOCKS_URL = "https://raw.githubusercontent.com/Fred6725/rs-log/main/output/rs_stocks.csv"
FRED_INDUSTRIES_URL = "https://raw.githubusercontent.com/Fred6725/rs-log/main/output/rs_industries.csv"

OUTPUT_ROOT = "outputs"
RANKINGS_DIR = os.path.join(OUTPUT_ROOT, "rankings")
INDUSTRIES_DIR = os.path.join(OUTPUT_ROOT, "industries")
DIAGNOSTICS_DIR = os.path.join(OUTPUT_ROOT, "diagnostics")

SPY = "SPY"


@dataclass
class EnrichmentResult:
    ticker: str
    pct_12m: Optional[float]
    rs_delta: Optional[float]
    rs_delta_momentum: Optional[float]
    price_vs_sma10: Optional[float]
    price_vs_sma20: Optional[float]
    price_vs_sma50: Optional[float]
    price_vs_sma200: Optional[float]
    pct_from_52w_low: Optional[float]
    range_position: Optional[float]
    failed: bool = False


def ensure_dirs() -> None:
    for path in (RANKINGS_DIR, INDUSTRIES_DIR, DIAGNOSTICS_DIR):
        os.makedirs(path, exist_ok=True)


def now_slug() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def date_slug() -> str:
    return dt.datetime.now().strftime("%Y%m%d")


def _fetch_csv_with_retry(url: str, retries: int = 3, backoff_s: int = 5) -> pd.DataFrame:
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return pd.read_csv(io.StringIO(resp.text))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                print(f"   Fetch retry {attempt}/{retries} failed for {url}: {exc}")
                time.sleep(backoff_s)
    raise RuntimeError(f"Failed to fetch CSV after {retries} attempts: {url}; last error: {last_err}")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {
        "Relative Strength": "rs_score",
        "Percentile": "percentile",
        "1M_RS_Percentile": "pct_1m",
        "3M_RS_Percentile": "pct_3m",
        "6M_RS_Percentile": "pct_6m",
        "PctFrom52WkHigh": "pct_from_52w_high",
        "AvgVol30": "avg_vol_30d",
        "AvgVol10": "avg_vol_10d",
        "AvgVol50": "avg_vol_50d",
        "MarketCap": "market_cap",
        "Float": "float_shares",
        "ShortFloatPct": "short_float_pct",
        "RevenueGrowth": "revenue_growth",
    }
    out = df.rename(columns={c: mapping.get(c, c) for c in df.columns}).copy()
    out.columns = [c.strip().lower().replace(" ", "_") for c in out.columns]
    return out


def _coerce_numeric(df: pd.DataFrame, cols: List[str]) -> None:
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")


def liquidity_filter(df: pd.DataFrame) -> pd.DataFrame:
    _coerce_numeric(df, ["avg_vol_30d", "price"])
    liq = df[(df["avg_vol_30d"] >= VOL_MIN) & (df["price"] >= PRICE_MIN)].copy()
    print(f"   Liquidity gate: {len(liq):,}/{len(df):,} pass (avg_vol_30d >= {VOL_MIN:,}, price >= {PRICE_MIN})")
    return liq


def _history_with_retry(ticker: str, retries: int = 3, backoff_s: int = 2) -> Optional[pd.DataFrame]:
    for attempt in range(1, retries + 1):
        try:
            time.sleep(REQUEST_DELAY)
            hist = yf.Ticker(ticker).history(period=HISTORY_PERIOD, auto_adjust=False)
            if hist is not None and not hist.empty and "Close" in hist.columns:
                return hist
        except Exception:  # noqa: BLE001
            pass
        if attempt < retries:
            time.sleep(backoff_s)
    return None


def _return_pct(series: pd.Series, bars: int) -> Optional[float]:
    if len(series) <= bars:
        return None
    curr = float(series.iloc[-1])
    prev = float(series.iloc[-(bars + 1)])
    if prev == 0:
        return None
    return ((curr / prev) - 1.0) * 100.0


def _compute_single_enrichment(
    ticker: str,
    stock_hist: pd.DataFrame,
    spy_hist: pd.DataFrame,
) -> EnrichmentResult:
    close = stock_hist["Close"].dropna()
    spy_close = spy_hist["Close"].dropna()
    if close.empty or spy_close.empty:
        return EnrichmentResult(ticker=ticker, pct_12m=None, rs_delta=None, rs_delta_momentum=None,
                                price_vs_sma10=None, price_vs_sma20=None, price_vs_sma50=None,
                                price_vs_sma200=None, pct_from_52w_low=None, range_position=None, failed=True)

    bars_12m = 252
    stock_12m = _return_pct(close, bars_12m)
    spy_12m = _return_pct(spy_close, bars_12m)
    rel_12m = None if stock_12m is None or spy_12m is None else (stock_12m - spy_12m)

    last = float(close.iloc[-1])
    sma10 = close.rolling(10).mean().iloc[-1] if len(close) >= 10 else np.nan
    sma20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else np.nan
    sma50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else np.nan
    sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else np.nan

    lookback = close.tail(252) if len(close) >= 252 else close
    low_52 = float(lookback.min()) if not lookback.empty else math.nan
    high_52 = float(lookback.max()) if not lookback.empty else math.nan

    def pct_vs(sma: float) -> Optional[float]:
        if np.isnan(sma) or sma == 0:
            return None
        return ((last / sma) - 1.0) * 100.0

    pct_from_52w_low = None
    if not np.isnan(low_52) and low_52 > 0:
        pct_from_52w_low = ((last - low_52) / low_52) * 100.0

    range_position = None
    if not np.isnan(low_52) and not np.isnan(high_52) and high_52 > low_52:
        range_position = ((last - low_52) / (high_52 - low_52)) * 100.0

    return EnrichmentResult(
        ticker=ticker,
        pct_12m=rel_12m,
        rs_delta=None,
        rs_delta_momentum=None,
        price_vs_sma10=pct_vs(float(sma10)),
        price_vs_sma20=pct_vs(float(sma20)),
        price_vs_sma50=pct_vs(float(sma50)),
        price_vs_sma200=pct_vs(float(sma200)),
        pct_from_52w_low=pct_from_52w_low,
        range_position=range_position,
        failed=False,
    )


def enrich_liquid(liq: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    spy_hist = _history_with_retry(SPY)
    if spy_hist is None:
        raise RuntimeError("Unable to fetch SPY history. Aborting enrichment.")

    results: List[EnrichmentResult] = []
    failed: List[str] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for ticker in liq["ticker"].astype(str).tolist():
            futures[pool.submit(_history_with_retry, ticker)] = ticker

        stock_histories: Dict[str, pd.DataFrame] = {}
        for fut in as_completed(futures):
            ticker = futures[fut]
            hist = fut.result()
            if hist is None:
                failed.append(ticker)
            else:
                stock_histories[ticker] = hist

    for ticker in liq["ticker"].astype(str).tolist():
        hist = stock_histories.get(ticker)
        if hist is None:
            results.append(
                EnrichmentResult(
                    ticker=ticker,
                    pct_12m=None,
                    rs_delta=None,
                    rs_delta_momentum=None,
                    price_vs_sma10=None,
                    price_vs_sma20=None,
                    price_vs_sma50=None,
                    price_vs_sma200=None,
                    pct_from_52w_low=None,
                    range_position=None,
                    failed=True,
                )
            )
        else:
            results.append(_compute_single_enrichment(ticker, hist, spy_hist))

    enrich_df = pd.DataFrame([r.__dict__ for r in results])
    liq2 = liq.merge(enrich_df.drop(columns=["failed"]), on="ticker", how="left")

    # Percentile from 12M relative return, inside liquid universe only.
    liq2["pct_12m"] = liq2["pct_12m"].rank(pct=True, method="average") * 100.0

    # RS delta based on Fred's percentile snapshots.
    liq2["rs_delta"] = liq2["percentile"] - liq2["pct_1m"]
    liq2["rs_delta_momentum"] = (liq2["percentile"] - liq2["pct_1m"]) - (liq2["pct_1m"] - liq2["pct_3m"])

    print(f"   Enrichment done: {len(liq2) - len(failed):,} success, {len(failed):,} failed")
    return liq2, failed


def assign_elite_flags(df: pd.DataFrame) -> None:
    fields = [("elite_rs", "percentile"), ("elite_1m", "pct_1m"), ("elite_3m", "pct_3m"),
              ("elite_6m", "pct_6m"), ("elite_12m", "pct_12m")]
    for elite_col, source in fields:
        thr = df[source].quantile(0.98)
        df[elite_col] = (df[source] >= thr).astype(int)
    df["elite_count"] = df[["elite_rs", "elite_1m", "elite_3m", "elite_6m", "elite_12m"]].sum(axis=1)


def add_cross_tf(df: pd.DataFrame) -> None:
    tf_cols = ["pct_1m", "pct_3m", "pct_6m", "pct_12m"]
    df["tf_count_10"] = df[tf_cols].apply(lambda r: int(sum(pd.notna(r[c]) and r[c] >= 90 for c in tf_cols)), axis=1)
    df["avg_pct"] = df[tf_cols].mean(axis=1)
    df["shape_score"] = (
        (df["pct_1m"] - df["pct_12m"]) * 0.5
        + (df["pct_1m"] - df["pct_3m"]) * 0.3
        + (df["pct_3m"] - df["pct_6m"]) * 0.2
    )


def reorder_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "rank", "ticker", "sector", "industry", "exchange", "avg_vol_30d", "price",
        "rs_score", "rs_delta", "rs_delta_momentum", "pct_from_52w_high", "pct_from_52w_low",
        "range_position", "price_vs_sma10", "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
        "percentile", "pct_1m", "pct_3m", "pct_6m", "pct_12m",
        "elite_rs", "elite_1m", "elite_3m", "elite_6m", "elite_12m", "elite_count",
        "market_cap", "float_shares", "short_float_pct", "revenue_growth",
        "avg_vol_10d", "avg_vol_50d",
        "tf_count_10", "avg_pct", "shape_score",
        "date",
    ]
    existing = [c for c in cols if c in df.columns]
    return df[existing].copy()


def retain_latest(path_pattern: str, keep: int) -> None:
    files = sorted(glob.glob(path_pattern))
    if len(files) <= keep:
        return
    for old in files[:-keep]:
        try:
            os.remove(old)
        except OSError:
            pass


def save_industries_snapshot(industries: pd.DataFrame) -> str:
    out = os.path.join(INDUSTRIES_DIR, f"us_rs_industries_{now_slug()}.csv")
    industries.to_csv(out, index=False)
    return out


def main() -> None:
    started = time.time()
    ensure_dirs()

    print("\nUS RS Pipeline — fetch and enrich")

    fetch_started = time.time()
    stocks_raw = _fetch_csv_with_retry(FRED_STOCKS_URL, retries=3, backoff_s=5)
    industries_raw = _fetch_csv_with_retry(FRED_INDUSTRIES_URL, retries=3, backoff_s=5)
    fetch_duration = time.time() - fetch_started
    print(f"   Fred CSV fetch complete in {fetch_duration:.1f}s")

    stocks = normalize_columns(stocks_raw)
    industries = normalize_columns(industries_raw)
    save_industries_snapshot(industries)

    liq = liquidity_filter(stocks)
    enriched, failed = enrich_liquid(liq)

    assign_elite_flags(enriched)
    add_cross_tf(enriched)

    enriched = enriched.sort_values("rs_score", ascending=False).reset_index(drop=True)
    enriched["rank"] = np.arange(1, len(enriched) + 1)
    enriched["date"] = dt.date.today().isoformat()

    rounded_cols = [
        "rs_delta", "rs_delta_momentum", "pct_from_52w_low", "range_position",
        "price_vs_sma10", "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
        "percentile", "pct_1m", "pct_3m", "pct_6m", "pct_12m", "avg_pct", "shape_score",
    ]
    for c in rounded_cols:
        if c in enriched.columns:
            enriched[c] = pd.to_numeric(enriched[c], errors="coerce").round(1)

    final_df = reorder_columns(enriched)
    rankings_path = os.path.join(RANKINGS_DIR, f"us_rs_rankings_{now_slug()}.csv")
    final_df.to_csv(rankings_path, index=False)

    total_duration = time.time() - started
    diagnostics = pd.DataFrame([
        {
            "date": dt.date.today().isoformat(),
            "universe_total": int(len(stocks)),
            "liquid_count": int(len(liq)),
            "enriched_count": int(len(final_df) - len(failed)),
            "failed_count": int(len(failed)),
            "fetch_duration_s": round(fetch_duration, 2),
            "total_duration_s": round(total_duration, 2),
        }
    ])
    diag_path = os.path.join(DIAGNOSTICS_DIR, f"us_rs_diagnostics_{now_slug()}.csv")
    diagnostics.to_csv(diag_path, index=False)

    retain_latest(os.path.join(RANKINGS_DIR, "us_rs_rankings_*.csv"), FILE_RETENTION_KEEP)
    retain_latest(os.path.join(DIAGNOSTICS_DIR, "us_rs_diagnostics_*.csv"), FILE_RETENTION_KEEP)
    retain_latest(os.path.join(INDUSTRIES_DIR, "us_rs_industries_*.csv"), FILE_RETENTION_KEEP)

    if failed:
        print(f"   Failed tickers sample ({min(15, len(failed))}/{len(failed)}): {', '.join(failed[:15])}")

    print(f"   Saved rankings   : {rankings_path}")
    print(f"   Saved diagnostics: {diag_path}")
    print(f"✅ Done in {total_duration:.1f}s\n")


if __name__ == "__main__":
    main()
