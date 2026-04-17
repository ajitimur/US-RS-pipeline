# US Relative Strength Pipeline

Daily US market Relative Strength (RS) pipeline that:

1. Pulls precomputed RS data from [Fred6725](https://github.com/Fred6725/relative-strength)
2. Enriches liquid stocks with yfinance-derived technical metrics
3. Builds a self-contained HTML dashboard
4. Publishes `docs/index.html` for GitHub Pages

**Live dashboard:** https://ajitimur.github.io/us-relative-strength/

This project mirrors the [IDX RS workflow](https://github.com/ajitimur/IHSG-relative-strength-percentile) style, but skips local RS recomputation and consumes Fred's daily CSV as the primary data source.

---

## Credits

RS scoring and daily data pipeline by [Fred6725](https://github.com/Fred6725/relative-strength), forked from [maximbelyayev](https://github.com/maximbelyayev/relative-strength) and originally by [skyte](https://github.com/skyte/relative-strength). This repo consumes Fred's published output and adds enrichment, additional signals, and a Minervini/Qullamaggie-oriented dashboard on top.

---

## Project Structure

```
US-RS-pipeline/
├── fetch_and_enrich.py
├── build_dashboard.py
├── extract_template.py
├── dashboard_template_a.html
├── dashboard_template_b.js
├── dashboard_template_c.html
├── requirements.txt
├── docs/
│   └── index.html
├── outputs/
│   ├── rankings/
│   ├── industries/
│   └── diagnostics/
└── .github/workflows/daily_rs.yml
```

---

## Data Sources

- Stocks CSV: <https://raw.githubusercontent.com/Fred6725/rs-log/main/output/rs_stocks.csv>
- Industries CSV: <https://raw.githubusercontent.com/Fred6725/rs-log/main/output/rs_industries.csv>
- Enrichment data: `yfinance` (`yf.Ticker(ticker).history(...)`)

---

## Requirements

- Python 3.11+ recommended
- Network access to GitHub raw and Yahoo Finance

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Run Locally

From the `US-RS-pipeline` directory:

```bash
python fetch_and_enrich.py
python build_dashboard.py
python extract_template.py docs/index.html
```

Outputs:

- Rankings CSV: `outputs/rankings/us_rs_rankings_YYYYMMDD_HHMMSS.csv`
- Diagnostics CSV: `outputs/diagnostics/us_rs_diagnostics_YYYYMMDD_HHMMSS.csv`
- Dashboard HTML:
  - `docs/index.html`
  - `outputs/us_rs_dashboard_YYYYMMDD.html`
- Industries snapshot: `outputs/industries/us_rs_industries_YYYYMMDD_HHMMSS.csv`

---

## Configuration

Environment variables supported by `fetch_and_enrich.py`:

| Variable | Default | Description |
|---|---|---|
| `US_MAX_WORKERS` | `10` | Parallel yfinance fetch workers |
| `US_REQUEST_DELAY` | `0.3` | Per-worker delay between requests (seconds) |

Example:

```bash
US_MAX_WORKERS=12 US_REQUEST_DELAY=0.25 python fetch_and_enrich.py
```

---

## GitHub Actions

Workflow file: `.github/workflows/daily_rs.yml`

- Scheduled weekdays at `21:30 UTC` (04:30 WIB) — after US market close
- Supports manual trigger (`workflow_dispatch`)
- Set repo variables `US_MAX_WORKERS` and `US_REQUEST_DELAY` to override defaults without editing code

Runs in order:
1. `python fetch_and_enrich.py`
2. `python build_dashboard.py`
3. Commits and pushes changes in `docs/` and `outputs/`

**GitHub Pages setup:** Enable Pages in repo Settings → Pages → Source: `Deploy from branch` → Branch: `main` → Folder: `/docs`.

---

## Important Implementation Notes

**Never use `yf.download()` in threaded mode.**
This project intentionally uses `yf.Ticker(...).history()` per ticker inside
`ThreadPoolExecutor` to avoid price series contamination between symbols —
a known issue with `yf.download()` under concurrent access.

**Liquidity filter is applied before enrichment:**
- `avg_vol_30d >= 500,000`
- `price >= 5.0`

**Fred's percentile fields are treated as source-of-truth and are not recomputed:**
- `percentile` — current RS percentile, ranked across all ~6,100 stocks
- `pct_1m` — RS percentile as of 1 month ago (not a 1-month return percentile)
- `pct_3m` — RS percentile as of 3 months ago
- `pct_6m` — RS percentile as of 6 months ago

**`pct_12m` is computed locally and is not directly comparable to the above.**
Fred does not publish a 12-month RS percentile. This pipeline computes it by
ranking 12-month returns within the liquid subset only (~1,500–2,000 stocks),
whereas Fred's other percentiles are ranked across the full ~6,100-stock universe.
Avoid treating `pct_12m` and `pct_1m/3M/6M` as equivalent scales in cross-TF
comparisons — use `pct_12m` as a directional signal, not an absolute rank.

**`extract_template.py` — when to run it:**
Run after the dashboard HTML is rebuilt (either locally or by Claude) to keep
`dashboard_template_a/b/c` in sync with `docs/index.html`. These template files
exist for version control readability — the dashboard itself is fully self-contained.