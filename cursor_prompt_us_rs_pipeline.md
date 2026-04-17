# Cursor Prompt — US RS Pipeline (us_rs_pipeline)

## Context

I already run an IDX (Indonesian Stock Exchange) RS analysis pipeline at
`github.com/ajitimur/IHSG-relative-strength-percentile` or `./../RS-threshold` from local machine. This new repo is a parallel US market pipeline. Build it from scratch — do not copy the IDX
repo verbatim, but mirror its architecture and conventions where they apply.

The IDX repo has three scripts:
- `main.py` — fetches price data, computes RS scores, writes ranked CSV
- `build_dashboard.py` — reads latest CSV, builds HTML dashboard
- `extract_template.py` — splits dashboard HTML into 3 template files for
  version control

**For the US pipeline we skip `main.py` entirely.** Instead we consume a
pre-built public CSV from Fred6725's repo, enrich it, and build the
dashboard. This keeps our runtime under 20 minutes and avoids re-doing RS
computation that Fred already runs daily.

---

## Data Sources

### Primary — Fred6725 (fetched fresh each run)

```
Full stock universe:
https://raw.githubusercontent.com/Fred6725/rs-log/main/output/rs_stocks.csv

Industry rankings:
https://raw.githubusercontent.com/Fred6725/rs-log/main/output/rs_industries.csv
```

**Fred's stock CSV schema (19 columns):**
```
Rank, Ticker, Sector, Industry, Exchange, Relative Strength, Percentile,
1M_RS_Percentile, 3M_RS_Percentile, 6M_RS_Percentile,
Price, MarketCap, Float, ShortFloatPct, PctFrom52WkHigh,
AvgVol10, AvgVol30, AvgVol50, RevenueGrowth
```

**Important — column semantics:**
- `Relative Strength` = Fred's RS score (weighted 3/6/9/12M vs SPY)
- `Percentile` = current RS percentile (0–99), computed across all ~6100 stocks
- `1M_RS_Percentile` = RS percentile AS OF 1 month ago (NOT a 1-month return percentile)
- `3M_RS_Percentile` = RS percentile as of 3 months ago
- `6M_RS_Percentile` = RS percentile as of 6 months ago
- `PctFrom52WkHigh` = (price − 52w high) / 52w high × 100, always ≤ 0

**Fred's industry CSV schema:**
```
Rank, Industry, Sector, Relative Strength, Percentile,
1M_RS_Percentile, 3M_RS_Percentile, 6M_RS_Percentile, Tickers
```

### Enrichment — yfinance (fetched for liquid subset only)

After applying the liquidity filter, fetch the following via
`yf.Ticker(ticker).history()` inside `ThreadPoolExecutor` for each
liquid stock. **Never use `yf.download()` — it causes price series bleed
between tickers when run with threads (up to 60% contamination observed).**

Columns to compute from price history:
- `pct_12m` — 12-month RS percentile (rank within liquid universe by
  12-month return vs SPY, same Minervini weighting as IDX pipeline)
- `rs_delta` — change in RS percentile over 21 trading bars (4 weeks):
  `rs_delta = percentile[t] − percentile[t−21]`
- `rs_delta_momentum` — acceleration of rs_delta:
  `rs_delta_momentum = (percentile[t] − percentile[t−21]) − (percentile[t−21] − percentile[t−42])`
  Requires ≥ 42 bars of percentile history; null if insufficient.
- `price_vs_sma10` — `(price / SMA10 − 1) × 100`
- `price_vs_sma20` — `(price / SMA20 − 1) × 100`
- `price_vs_sma50` — `(price / SMA50 − 1) × 100`
- `price_vs_sma200` — `(price / SMA200 − 1) × 100`
- `pct_from_52w_low` — `(price − 52w low) / 52w low × 100`
- `range_position` — `(price − 52w low) / (52w high − 52w low) × 100`

**Note:** Fred already provides `PctFrom52WkHigh`. Do not re-fetch it —
rename it to `pct_from_52w_high` (snake_case) on ingest.

---

## Script: `fetch_and_enrich.py`

This is the main (and only) pipeline script. It replaces both `main.py`
and the data-fetch portion of `build_dashboard.py`.

### Steps

1. **Fetch Fred's CSVs** via `requests.get()` with a 60s timeout and
   retry (3 attempts, 5s backoff). If fetch fails after retries, abort
   with a clear error message — do not proceed with stale cached data.

2. **Normalize column names** to snake_case:
   - `Relative Strength` → `rs_score`
   - `Percentile` → `percentile`
   - `1M_RS_Percentile` → `pct_1m`
   - `3M_RS_Percentile` → `pct_3m`
   - `6M_RS_Percentile` → `pct_6m`
   - `PctFrom52WkHigh` → `pct_from_52w_high`
   - `AvgVol30` → `avg_vol_30d`
   - All others: lowercase + underscores

3. **Liquidity filter:**
   ```
   avg_vol_30d >= 500_000
   price >= 5.0
   ```
   Log how many stocks pass. This is the enrichment universe.

4. **Enrich liquid stocks** — fetch price history via yfinance:
   - Use `ThreadPoolExecutor(max_workers=MAX_WORKERS)`
   - Per-worker `time.sleep(REQUEST_DELAY)` — no global RateLimiter
   - Fetch 18 months of daily OHLCV via `yf.Ticker(t).history(period='18mo')`
   - Compute all enrichment columns listed above
   - Retry failed fetches up to 3 times with 2s backoff before marking null
   - Log count of successful enrichments, failed tickers

5. **Assign elite flags** (same logic as IDX pipeline):
   - `elite_rs` — top 2% by `percentile` within liquid universe
   - `elite_1m` — top 2% by `pct_1m`
   - `elite_3m` — top 2% by `pct_3m`
   - `elite_6m` — top 2% by `pct_6m`
   - `elite_12m` — top 2% by `pct_12m`
   - `elite_count` — sum of elite flags (0–5)

6. **Compute Cross-TF metrics** (computed here, not in dashboard JS):
   - `tf_count_10` — count of `{pct_1m, pct_3m, pct_6m, pct_12m}` ≥ 90
   - `avg_pct` — mean of `{pct_1m, pct_3m, pct_6m, pct_12m}`
   - `shape_score` — momentum shape:
     `(pct_1m − pct_12m) × 0.5 + (pct_1m − pct_3m) × 0.3 + (pct_3m − pct_6m) × 0.2`

7. **Save enriched CSV:**
   ```
   outputs/rankings/us_rs_rankings_YYYYMMDD_HHMMSS.csv
   ```
   Retain last 30 files (prune older ones).

8. **Save diagnostics CSV:**
   ```
   outputs/diagnostics/us_rs_diagnostics_YYYYMMDD_HHMMSS.csv
   ```
   Columns: `date, universe_total, liquid_count, enriched_count, failed_count,
   fetch_duration_s, total_duration_s`

### Config (top of file, env var overridable)

```python
MAX_WORKERS    = int(os.environ.get("US_MAX_WORKERS",    10))
REQUEST_DELAY  = float(os.environ.get("US_REQUEST_DELAY", 0.3))
PRICE_MIN      = 5.0
VOL_MIN        = 500_000
HISTORY_PERIOD = "18mo"
FILE_RETENTION_KEEP = 30
FRED_STOCKS_URL = "https://raw.githubusercontent.com/Fred6725/rs-log/main/output/rs_stocks.csv"
FRED_INDUSTRIES_URL = "https://raw.githubusercontent.com/Fred6725/rs-log/main/output/rs_industries.csv"
```

---

## Output CSV Schema (27 columns)

```
rank, ticker, sector, industry, exchange, avg_vol_30d, price,
rs_score, rs_delta, rs_delta_momentum, pct_from_52w_high, pct_from_52w_low,
range_position, price_vs_sma10, price_vs_sma20, price_vs_sma50, price_vs_sma200,
percentile, pct_1m, pct_3m, pct_6m, pct_12m,
elite_rs, elite_1m, elite_3m, elite_6m, elite_12m, elite_count,
market_cap, float_shares, short_float_pct, revenue_growth,
avg_vol_10d, avg_vol_50d,
tf_count_10, avg_pct, shape_score,
date
```

`rank` = rank by `rs_score` descending within liquid universe (re-ranked,
not Fred's rank which is across all 6100).

---

## Script: `build_dashboard.py`

Reads the latest enriched CSV from `outputs/rankings/` and the latest
Fred industries CSV (save a copy to `outputs/industries/` each run).
Builds a self-contained HTML dashboard written to:
```
docs/index.html
outputs/us_rs_dashboard_YYYYMMDD.html
```

### Dashboard — 8 tabs (mirror IDX dashboard structure)

All tabs share these conventions:
- Dark theme (`#0d0f14` base)
- IBM Plex Mono for data/numbers, IBM Plex Sans for labels
- All tables fully sortable, multi-column sort supported
- Percentile color: green ≥ 80, neutral 50–79, red < 50
- RS Δ color: green > +5, red < −5, neutral otherwise
- 52W Hi% color: green ≥ −10%, amber −10% to −25%, red < −25%
- SMA% color: green > 0 (price above), red ≤ 0 (price below)
- Columns auto-hidden when data absent (no empty cells, no errors)

**Header:** Show data date, liquid stock count, total universe count,
and a `↑ LOAD CSV` button for in-browser CSV reload.

**Tab accent colors:** Blue for leader tabs, green for momentum/cross-TF,
amber for sectors.

---

### Tab 1 — RS Leaders

Top 30 by `rs_score` descending.

**Filters:**
- `RS Δ Rising` checkbox — show only `rs_delta > 0`
- `Near 52W Hi` checkbox — show only `pct_from_52w_high ≥ −15`
- `SMA50 ↑` button — `price_vs_sma50 > 0`
- `SMA200 ↑` button — `price_vs_sma200 > 0`
- TOP% pills: 1% / 2% / 5% / 10% / 20% — filter by elite/percentile tier

**Columns:**
`rank, ticker, sector badge, exchange badge, RS Δ 4W, Δ MOM,
52W Hi%, SMA10%, SMA20%, SMA50%, SMA200%,
pct (RS %ile), 1M %ile, 3M %ile, 6M %ile, 12M %ile,
RS score, MarketCap, AvgVol30, elite_count`

---

### Tab 2 — 1M Leaders

Top 30 by `pct_1m` descending.
Same filters as RS Leaders minus `RS Δ Rising`.
Columns same as RS Leaders.

---

### Tab 3 — 3M Leaders

Top 30 by `pct_3m` descending. Same structure.

---

### Tab 4 — 6M Leaders

Top 30 by `pct_6m` descending. Same structure.

---

### Tab 5 — 12M Leaders

Top 30 by `pct_12m` descending. Same structure.

---

### Tab 6 — Cross-TF

All stocks with `tf_count_10 ≥ 2`, sorted by `tf_count_10` desc,
then `avg_pct` desc.

**Filters:**
- `MIN TF COUNT` pills: 2 / 3 / 4
- `Accelerating Only` checkbox — `shape_score > 0`
- `SMA50 ↑` / `SMA200 ↑` buttons
- `RS Δ Rising` checkbox

**Columns:**
`rank, ticker, sector badge, exchange badge, tf_count (badge: 2/3/4 colored),
avg_pct, shape_score, RS Δ 4W, Δ MOM,
52W Hi%, SMA50%, SMA200%,
1M %ile, 3M %ile, 6M %ile, 12M %ile, RS score, elite_count`

---

### Tab 7 — Momentum

All stocks passing momentum gainer filter — **all 4 conditions required:**
```
pct_1m > pct_3m
pct_3m > pct_12m
pct_1m >= 60
pct_1m - pct_3m >= 10   (accel)
```
Sort by `accel` descending. Darker green badge for `accel ≥ 25`.

**Filters:**
- `Near 52W Hi (> −15%)` checkbox
- `RS Δ Rising` checkbox
- `SMA200 ↑` button

**Columns:**
`rank, ticker, sector badge, exchange badge, accel (+),
RS Δ 4W, Δ MOM, 52W Hi%, SMA50%, SMA200%,
1M %ile, 3M %ile, 6M %ile, 12M %ile, RS score, AvgVol30`

---

### Tab 8 — Sectors

Use Fred's `rs_industries.csv` aggregated to sector level, cross-referenced
with the enriched stock CSV for SMA data.

**Sector composite formula:**
```
composite     = (multi_breadth × 0.4) + (ceiling × 0.4) + (avg × 0.2)
multi_breadth = (breadth_1m × 0.5) + (breadth_3m × 0.3) + (breadth_6m × 0.2)
breadth_Xm    = % of liquid sector stocks with pct_Xm ≥ 70
ceiling       = median of top-5 stocks by pct_1m
avg           = mean pct_1m across all liquid sector stocks
```

Display formula inline at top of tab.

**Sector cards** (sorted by `composite` descending), each card shows:
- Sector name + stock count
- Composite score (large)
- Metric boxes: breadth_1m / breadth_3m / breadth_6m / ceiling / avg
- Horizontal bar charts for all 5 metrics
- Top-5 ticker chips (by pct_1m), sector leader highlighted
- Top-3 industries within sector by RS percentile

---

### HOW TO USE modal (5 tabs)

Include a `? HOW TO USE` button in the header that opens a modal with
5 tabs: Overview, Columns, Tabs & Filters, Setups, Workflow.

**Setups tab — 4 interactive presets**, each with an "Apply Filter" button
that closes the modal, switches to the correct tab, and applies filters:

| Preset | Tab | Filters | Sort |
|--------|-----|---------|------|
| HIGH CONVICTION | RS Leaders | near52 + sma50 + sma200 | rs_score desc |
| CATCHING BREATH | RS Leaders | sma50 + sma200 | pct_from_52w_high desc |
| STALLING LEADER | RS Leaders | none | rs_delta asc |
| EMERGING LEADER | Cross-TF | accel only | tf_count_10 desc, avg_pct desc |

**Workflow tab** — document Minervini/Qullamaggie daily workflow adapted
for US market:
1. Check SPY vs key MAs before aggressive positioning
2. Sector rotation — top 2–3 sectors by composite
3. Persistent leaders — Cross-TF tab, MIN TF=3, Accelerating Only, SMA50+200
4. Fresh momentum — Momentum tab, RS Δ Rising + Near 52W Hi + SMA200
5. Cross-reference stocks appearing on multiple tabs simultaneously
6. Chart review required before entry (VCP base, volume contraction, SMA obedience)

---

## Script: `extract_template.py`

Same as IDX repo — splits `docs/index.html` into:
```
dashboard_template_a.html   ← everything before the embedded JSON data
dashboard_template_b.js     ← the JS/logic block
dashboard_template_c.html   ← closing tags
```
Run after Claude rebuilds the dashboard to keep templates in sync.

---

## GitHub Actions: `.github/workflows/daily_rs.yml`

```yaml
name: Daily US RS

on:
  schedule:
    - cron: '30 21 * * 1-5'   # 04:30 WIB (UTC+7) = 21:30 UTC, after US market close
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python fetch_and_enrich.py
        env:
          US_MAX_WORKERS: ${{ vars.US_MAX_WORKERS || '10' }}
          US_REQUEST_DELAY: ${{ vars.US_REQUEST_DELAY || '0.3' }}
      - run: python build_dashboard.py
      - name: Commit and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/ outputs/
          git diff --cached --quiet || git commit -m "Daily US RS update $(date +'%Y-%m-%d')"
          git push
```

---

## Repo structure

```
us-relative-strength/
├── fetch_and_enrich.py          ← main pipeline script
├── build_dashboard.py           ← dashboard builder
├── extract_template.py          ← template extractor
├── requirements.txt
├── dashboard_template_a.html
├── dashboard_template_b.js
├── dashboard_template_c.html
├── docs/
│   └── index.html               ← GitHub Pages output
└── outputs/
    ├── rankings/                ← enriched CSVs (30-file retention)
    ├── industries/              ← Fred's industry CSVs (saved each run)
    └── diagnostics/
```

---

## Key principles — do not deviate

- **Never use `yf.download()`** — causes price series bleed between tickers.
  Always `yf.Ticker(t).history()` inside `ThreadPoolExecutor`.
- **No global RateLimiter across workers** — use per-worker `time.sleep(REQUEST_DELAY)`.
- **Retry failed fetches** — 3 attempts, 2s backoff, log failures.
- **Fred's percentiles are pre-computed** — do not re-rank `pct_1m/3M/6M` or
  `percentile`. Only compute `pct_12m` yourself (not in Fred's data).
- **Liquidity filter is a hard gate** — apply before any enrichment or display.
- **RS is a screening tool, not a trigger** — note this in the HOW TO USE modal.
  Chart-level validation (Stage 2, VCP base, volume contraction) is always required.
