"""
build_dashboard.py
==================
Build a self-contained US RS dashboard from latest enriched rankings CSV.
"""

from __future__ import annotations

import os
import io
import glob
import json
import argparse
import datetime as dt

import numpy as np
import pandas as pd
import requests


OUTPUT_ROOT = "outputs"
RANKINGS_DIR = os.path.join(OUTPUT_ROOT, "rankings")
INDUSTRIES_DIR = os.path.join(OUTPUT_ROOT, "industries")
DOCS_DIR = "docs"
FRED_INDUSTRIES_URL = "https://raw.githubusercontent.com/Fred6725/rs-log/main/output/rs_industries.csv"


def find_latest_csv() -> str:
    files = sorted(glob.glob(os.path.join(RANKINGS_DIR, "us_rs_rankings_*.csv")))
    if not files:
        raise FileNotFoundError(f"No US rankings CSV found in `{RANKINGS_DIR}`. Run fetch_and_enrich.py first.")
    return files[-1]


def find_latest_industries() -> str | None:
    files = sorted(glob.glob(os.path.join(INDUSTRIES_DIR, "us_rs_industries_*.csv")))
    return files[-1] if files else None


def fetch_industries_snapshot() -> str:
    os.makedirs(INDUSTRIES_DIR, exist_ok=True)
    r = requests.get(FRED_INDUSTRIES_URL, timeout=60)
    r.raise_for_status()
    out = os.path.join(INDUSTRIES_DIR, f"us_rs_industries_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.text)
    return out


def clean_value(v):
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, list):
        return [clean_value(x) for x in v]
    return v


def load_payload(rankings_csv: str, industries_csv: str) -> dict:
    stocks = pd.read_csv(rankings_csv)
    industries = pd.read_csv(industries_csv)
    industries.columns = [c.strip().lower().replace(" ", "_") for c in industries.columns]

    momentum = stocks[
        (stocks["pct_1m"] > stocks["pct_3m"])
        & (stocks["pct_3m"] > stocks["pct_12m"])
        & (stocks["pct_1m"] >= 60)
        & ((stocks["pct_1m"] - stocks["pct_3m"]) >= 10)
    ].copy()
    momentum["accel"] = momentum["pct_1m"] - momentum["pct_3m"]
    momentum = momentum.sort_values("accel", ascending=False)

    cross = stocks[stocks["tf_count_10"] >= 2].sort_values(["tf_count_10", "avg_pct"], ascending=[False, False])

    # Sector cards from enriched stocks + Fred industries.
    sector_rows = []
    for sector, grp in stocks.groupby("sector"):
        b1 = round(float((grp["pct_1m"] >= 70).mean() * 100), 1)
        b3 = round(float((grp["pct_3m"] >= 70).mean() * 100), 1)
        b6 = round(float((grp["pct_6m"] >= 70).mean() * 100), 1)
        multi = round(b1 * 0.5 + b3 * 0.3 + b6 * 0.2, 1)
        top5 = grp.nlargest(5, "pct_1m")
        ceiling = round(float(top5["pct_1m"].median()), 1) if not top5.empty else 0.0
        avg = round(float(grp["pct_1m"].mean()), 1)
        comp = round((multi * 0.4) + (ceiling * 0.4) + (avg * 0.2), 1)

        inds = industries[industries["sector"] == sector].sort_values("percentile", ascending=False).head(3)
        top_inds = inds["industry"].tolist() if not inds.empty else []
        sector_rows.append(
            {
                "sector": sector,
                "count": int(len(grp)),
                "composite": comp,
                "multi_breadth": multi,
                "breadth_1m": b1,
                "breadth_3m": b3,
                "breadth_6m": b6,
                "ceiling": ceiling,
                "avg": avg,
                "top5": top5["ticker"].astype(str).tolist(),
                "top_industries": top_inds,
            }
        )
    sector_rows = sorted(sector_rows, key=lambda x: x["composite"], reverse=True)

    date_value = str(stocks["date"].iloc[0]) if "date" in stocks.columns and len(stocks) else dt.date.today().isoformat()
    return {
        "stocks": [{k: clean_value(v) for k, v in row.items()} for row in stocks.to_dict("records")],
        "momentum": [{k: clean_value(v) for k, v in row.items()} for row in momentum.to_dict("records")],
        "cross": [{k: clean_value(v) for k, v in row.items()} for row in cross.to_dict("records")],
        "sectors": sector_rows,
        "meta": {
            "date": date_value,
            "liquid_count": int(len(stocks)),
            "total_count": int(len(stocks)),
        },
    }


def get_template() -> tuple[str, str, str]:
    here = os.path.dirname(os.path.abspath(__file__))
    a_path = os.path.join(here, "dashboard_template_a.html")
    b_path = os.path.join(here, "dashboard_template_b.js")
    c_path = os.path.join(here, "dashboard_template_c.html")
    if os.path.exists(a_path) and os.path.exists(b_path) and os.path.exists(c_path):
        with open(a_path, encoding="utf-8") as f:
            a = f.read()
        with open(b_path, encoding="utf-8") as f:
            b = f.read()
        with open(c_path, encoding="utf-8") as f:
            c = f.read()
        return a, b, c
    return default_template()


def default_template() -> tuple[str, str, str]:
    a = """<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>US RS Dashboard</title>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    :root{
      --bg:#0d0f14;--bg2:#131620;--bg3:#1a1e2e;--bg4:#1f2436;
      --border:#2a2f45;--border2:#343b56;
      --text:#e2e8f8;--text2:#8892b0;--text3:#4a5578;
      --green:#22d3a0;--amber:#f5a623;--red:#f06060;--blue:#4f8ef7;--purple:#a78bfa;
    }
    *{box-sizing:border-box;margin:0;padding:0}
    body{background:var(--bg);color:var(--text);font-family:'IBM Plex Sans',sans-serif;font-size:13px;min-height:100vh}
    .mono{font-family:'IBM Plex Mono',monospace}
    .wrap{width:100%}
    .head{background:var(--bg2);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
    .head h2{font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:600;letter-spacing:.05em}
    .meta{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--text3)}
    .btn{font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;padding:5px 12px;border-radius:4px;border:1px solid var(--border2);background:var(--bg3);color:var(--text2);cursor:pointer;transition:all .15s;white-space:nowrap}
    .btn:hover{border-color:var(--blue);color:var(--blue)}
    .tabs{display:flex;gap:2px;padding:0 24px;background:var(--bg2);border-bottom:1px solid var(--border);overflow-x:auto}
    .tab{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:500;padding:10px 16px;cursor:pointer;border-bottom:2px solid transparent;color:var(--text3);letter-spacing:.04em;transition:all .15s;white-space:nowrap;background:transparent;border-top:none;border-left:none;border-right:none}
    .tab:hover{color:var(--text2)}
    .tab.active{color:var(--blue);border-bottom-color:var(--blue)}
    #panels{padding:20px 24px}
    .panel{display:none}
    .panel.active{display:block}
    .controls{display:flex;align-items:center;gap:7px;margin-bottom:14px;flex-wrap:wrap}
    label{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--text3);letter-spacing:.04em}
    input[type="checkbox"]{margin-right:5px}
    .chips{display:flex;gap:4px;align-items:center}
    .pill{font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;padding:3px 9px;border-radius:12px;border:1px solid var(--border2);background:transparent;color:var(--text3);cursor:pointer;transition:all .15s;white-space:nowrap}
    .pill:hover{border-color:var(--text2);color:var(--text2)}
    .pill.active{background:rgba(79,142,247,.15);border-color:var(--blue);color:var(--blue)}
    .table-wrap, table{width:100%}
    .table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:6px}
    table{border-collapse:collapse;font-family:'IBM Plex Mono',monospace;font-size:11.5px}
    thead{background:var(--bg3);position:sticky;top:0;z-index:10}
    thead tr{border-bottom:1px solid var(--border2)}
    th{padding:8px 10px;text-align:right;color:var(--text3);font-weight:500;font-size:10px;letter-spacing:.06em;white-space:nowrap;cursor:pointer;user-select:none;transition:color .15s}
    th:first-child,td:first-child{text-align:left}
    th:hover{color:var(--text2)}
    td{padding:7px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid rgba(42,47,69,.5)}
    tbody tr:hover{background:rgba(255,255,255,.025)}
    .badge{display:inline-block;font-size:9px;padding:2px 6px;border-radius:3px;font-family:'IBM Plex Mono',monospace;font-weight:500;white-space:nowrap}
    .sector{background:rgba(79,142,247,.1);color:var(--blue);border:1px solid rgba(79,142,247,.3)}
    .exch{background:rgba(167,139,250,.1);color:var(--purple);border:1px solid rgba(167,139,250,.3)}
    .g{color:var(--green)} .r{color:var(--red)} .a{color:var(--amber)}
    .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
    .card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:16px}
    .card:hover{border-color:var(--border2)}
    .bar{height:5px;background:var(--bg4);border-radius:3px;overflow:hidden}
    .bar>span{display:block;height:100%;background:linear-gradient(90deg,#4f8ef7,#22d3a0)}
    .modal{position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:1000;display:none;align-items:center;justify-content:center;padding:20px}
    .modal.open{display:flex}
    .modal-box{background:var(--bg2);border:1px solid var(--border2);border-radius:10px;width:100%;max-width:980px;max-height:90vh;overflow:auto;padding:16px}
    .modal-box h3{font-family:'IBM Plex Mono',monospace;font-size:13px}
  </style>
</head>
<body><div class="wrap">
  <div class="head">
    <div>
      <h2 style="margin:0">US Relative Strength Dashboard</h2>
      <div class="meta mono" id="meta"></div>
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <button class="btn" id="loadCsvBtn">↑ LOAD CSV</button>
      <input id="csvInput" type="file" accept=".csv,text/csv" style="display:none"/>
      <button class="btn" id="helpBtn">? HOW TO USE</button>
    </div>
  </div>
  <div class="tabs" id="tabs"></div>
  <div id="panels"></div>
</div>
<div class="modal" id="helpModal"><div class="modal-box">
  <div style="display:flex;justify-content:space-between;align-items:center"><h3 style="margin:0">How To Use</h3><button class="btn" id="closeHelp">Close</button></div>
  <div class="tabs" id="helpTabs"></div><div id="helpPanels"></div>
</div></div>
<script>
"""
    b = """
const TAB_LIST = ['RS Leaders','1M Leaders','3M Leaders','6M Leaders','12M Leaders','Cross-TF','Momentum','Sectors'];
const PAGE_SIZE = 50;
const CACHE = { stocks:[], by_rs:[], by_1m:[], by_3m:[], by_6m:[], by_12m:[], momentum:[], cross:[], sectors:[], meta:{} };
const state = { activeTab:'RS Leaders', filters:{}, sorts:{}, page:{} };
const PCT_COLS = new Set(['percentile','pct_1m','pct_3m','pct_6m','pct_12m']);
const SMA_COLS = new Set(['price_vs_sma10','price_vs_sma20','price_vs_sma50','price_vs_sma200']);

const fmt = (v,d=1)=> (v===null||v===undefined||Number.isNaN(v))?'':Number(v).toFixed(d);
const clsPct = v => v>=80?'g':(v<50?'r':'');
const clsRsd = v => v>5?'g':(v<-5?'r':'');
const cls52 = v => v>=-10?'g':(v<-25?'r':'a');
const clsSma = v => v>0?'g':'r';

function toNumber(v){ const n=Number(v); return Number.isNaN(n) ? null : n; }
function parseCsv(text){
  const [h,...rows] = text.trim().split(/\\r?\\n/);
  const cols = h.split(',');
  return rows.map(line=>{
    const vals = line.split(',');
    const o = {};
    cols.forEach((c,i)=>{ const raw=(vals[i]??'').trim(); const n=toNumber(raw); o[c]= n===null ? raw : n; });
    return o;
  });
}
function computeRowDerived(r){
  const tfCols = ['pct_1m','pct_3m','pct_6m','pct_12m'];
  r.tf_count_10 = tfCols.filter(c=>r[c]!=null && Number(r[c])>=90).length;
  const vals = tfCols.map(c=>toNumber(r[c])).filter(v=>v!=null);
  r.avg_pct = vals.length ? +(vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(1) : null;
  const p1=toNumber(r.pct_1m), p3=toNumber(r.pct_3m), p6=toNumber(r.pct_6m), p12=toNumber(r.pct_12m);
  if([p1,p3,p6,p12].every(v=>v!=null)){
    r.shape_score = +(((p1-p12)*0.5)+((p1-p3)*0.3)+((p3-p6)*0.2)).toFixed(1);
  } else {
    r.shape_score = null;
  }
  r.accel = (p1!=null && p3!=null) ? +(p1-p3).toFixed(1) : null;
}
function buildSectors(stocks){
  const sMap = {};
  stocks.forEach(r=>{ const s=r.sector||'Unknown'; (sMap[s]=sMap[s]||[]).push(r); });
  return Object.entries(sMap)
    .filter(([,g])=>g.length>=3)
    .map(([sector, grp])=>{
      const brd = col => (grp.filter(r=>toNumber(r[col])!=null && Number(r[col])>=70).length / grp.length) * 100;
      const b1=brd('pct_1m'), b3=brd('pct_3m'), b6=brd('pct_6m');
      const mb = b1*0.5 + b3*0.3 + b6*0.2;
      const t5 = [...grp].sort((a,b)=>(Number(b.pct_1m)||-Infinity)-(Number(a.pct_1m)||-Infinity)).slice(0,5);
      const meds = t5.map(r=>Number(r.pct_1m)||0).sort((a,b)=>a-b);
      const ceiling = meds[Math.floor(meds.length/2)] ?? 0;
      const avg = grp.reduce((s,r)=>s+(Number(r.pct_1m)||0),0)/grp.length;
      const iMap = {};
      grp.forEach(r=>{ const ind=r.industry||'Unknown'; (iMap[ind]=iMap[ind]||[]).push(Number(r.percentile)||0); });
      const top_industries = Object.entries(iMap)
        .map(([ind,ps])=>({ind,avg:ps.reduce((a,b)=>a+b,0)/ps.length}))
        .sort((a,b)=>b.avg-a.avg).slice(0,3).map(x=>x.ind);
      return {
        sector, count:grp.length,
        composite:+(mb*0.4 + ceiling*0.4 + avg*0.2).toFixed(1),
        multi_breadth:+mb.toFixed(1),
        breadth_1m:+b1.toFixed(1), breadth_3m:+b3.toFixed(1), breadth_6m:+b6.toFixed(1),
        ceiling:+ceiling.toFixed(1), avg:+avg.toFixed(1),
        top5:t5.map(r=>r.ticker), top_industries
      };
    })
    .sort((a,b)=>b.composite-a.composite);
}
function buildCacheFromRows(rows){
  const stocks = rows.map(r=>({...r}));
  stocks.forEach(computeRowDerived);
  CACHE.stocks = stocks;
  CACHE.by_rs = [...stocks].sort((a,b)=>(Number(b.rs_score)||-Infinity)-(Number(a.rs_score)||-Infinity));
  CACHE.by_1m = [...stocks].sort((a,b)=>(Number(b.pct_1m)||-Infinity)-(Number(a.pct_1m)||-Infinity));
  CACHE.by_3m = [...stocks].sort((a,b)=>(Number(b.pct_3m)||-Infinity)-(Number(a.pct_3m)||-Infinity));
  CACHE.by_6m = [...stocks].sort((a,b)=>(Number(b.pct_6m)||-Infinity)-(Number(a.pct_6m)||-Infinity));
  CACHE.by_12m = [...stocks].sort((a,b)=>(Number(b.pct_12m)||-Infinity)-(Number(a.pct_12m)||-Infinity));
  CACHE.momentum = stocks
    .filter(r=>Number(r.pct_1m)>Number(r.pct_3m) && Number(r.pct_3m)>Number(r.pct_12m) && Number(r.pct_1m)>=60 && (Number(r.pct_1m)-Number(r.pct_3m))>=10)
    .sort((a,b)=>(Number(b.accel)||-Infinity)-(Number(a.accel)||-Infinity));
  CACHE.cross = stocks
    .filter(r=>Number(r.tf_count_10)>=2)
    .sort((a,b)=>(Number(b.tf_count_10)||-Infinity)-(Number(a.tf_count_10)||-Infinity) || (Number(b.avg_pct)||-Infinity)-(Number(a.avg_pct)||-Infinity));
  CACHE.sectors = buildSectors(stocks);
  const hasCol = c => stocks.length>0 && stocks.some(r=>r[c]!==undefined && r[c]!==null && r[c]!=='' );
  CACHE.meta = {
    date: stocks[0]?.date || (EMBEDDED.meta?.date || '-'),
    liquid_count: stocks.length,
    total_count: stocks.length,
    has_sma10: hasCol('price_vs_sma10'),
    has_sma20: hasCol('price_vs_sma20'),
    has_rs_delta: hasCol('rs_delta'),
    has_rs_delta_momentum: hasCol('rs_delta_momentum'),
    has_pct_52w: hasCol('pct_from_52w_high')
  };
}
function loadEmbedded(){
  buildCacheFromRows(EMBEDDED.stocks || []);
  if((EMBEDDED.meta||{}).total_count) CACHE.meta.total_count = EMBEDDED.meta.total_count;
}

function resetUiState(){
  TAB_LIST.forEach(tab=>{ state.filters[tab]={}; state.sorts[tab]=[]; state.page[tab]=PAGE_SIZE; });
}
function defaultSortForTab(tab){
  const m = { 'RS Leaders':'rs_score','1M Leaders':'pct_1m','3M Leaders':'pct_3m','6M Leaders':'pct_6m','12M Leaders':'pct_12m','Cross-TF':'tf_count_10','Momentum':'accel' };
  return m[tab];
}
function baseForTab(tab){
  if(tab==='RS Leaders') return CACHE.by_rs;
  if(tab==='1M Leaders') return CACHE.by_1m;
  if(tab==='3M Leaders') return CACHE.by_3m;
  if(tab==='6M Leaders') return CACHE.by_6m;
  if(tab==='12M Leaders') return CACHE.by_12m;
  if(tab==='Cross-TF') return CACHE.cross;
  if(tab==='Momentum') return CACHE.momentum;
  return CACHE.stocks;
}
function getFilteredRows(tab){
  const base = baseForTab(tab);
  const f = state.filters[tab] || {};
  return base.filter(r=>{
    if(f.rising && !(r.rs_delta!=null && Number(r.rs_delta)>0)) return false;
    if(f.near52 && !(r.pct_from_52w_high!=null && Number(r.pct_from_52w_high)>=-15)) return false;
    if(f.sma10 && !(r.price_vs_sma10!=null && Number(r.price_vs_sma10)>0)) return false;
    if(f.sma20 && !(r.price_vs_sma20!=null && Number(r.price_vs_sma20)>0)) return false;
    if(f.sma50 && !(r.price_vs_sma50!=null && Number(r.price_vs_sma50)>0)) return false;
    if(f.sma200 && !(r.price_vs_sma200!=null && Number(r.price_vs_sma200)>0)) return false;
    if(f.accel && !(r.shape_score!=null && Number(r.shape_score)>0)) return false;
    if(f.minTf && !(Number(r.tf_count_10)>=Number(f.minTf))) return false;
    if(f.topPct){ const min=100-f.topPct; if(!(Number(r.percentile)>=min)) return false; }
    return true;
  });
}
function getSortedFilteredRows(tab){
  const filtered = getFilteredRows(tab);
  const sorts = state.sorts[tab] || [];
  if(!sorts.length) return filtered;
  return [...filtered].sort((a,b)=>{
    for(const {col,dir} of sorts){
      const va = a[col] ?? -Infinity, vb = b[col] ?? -Infinity;
      const na = Number(va), nb = Number(vb);
      const bothNum = !Number.isNaN(na) && !Number.isNaN(nb);
      const cmp = bothNum ? (na-nb) : String(va).localeCompare(String(vb));
      if(cmp!==0) return dir==='asc' ? cmp : -cmp;
    }
    return 0;
  });
}
function updateSort(tab,col,shift){
  const arr = state.sorts[tab] || [];
  const i = arr.findIndex(s=>s.col===col);
  if(i>=0){ arr[i].dir = arr[i].dir==='asc' ? 'desc' : 'asc'; }
  else { arr.push({col,dir:'desc'}); }
  state.sorts[tab] = shift ? arr : [arr[arr.length-1]];
}

function badge(text,cls){ return `<span class="badge ${cls} mono">${text??''}</span>`; }
function valueCell(col,v){
  if(col==='ticker') return `<td class="mono" style="text-align:left">${v||''}</td>`;
  if(col==='sector') return `<td style="text-align:left">${badge(v,'sector')}</td>`;
  if(col==='exchange') return `<td>${badge(v,'exch')}</td>`;
  let cls='';
  if(PCT_COLS.has(col)) cls=clsPct(Number(v));
  if(col==='rs_delta') cls=clsRsd(Number(v));
  if(col==='pct_from_52w_high') cls=cls52(Number(v));
  if(SMA_COLS.has(col)) cls=clsSma(Number(v));
  const d = ['rank','tf_count_10','elite_count'].includes(col)?0:1;
  return `<td class="mono ${cls}">${typeof v==='number'?fmt(v,d):(v??'')}</td>`;
}
function tableHtml(tab,rows,cols,total){
  const shown = cols.filter(c=>rows.some(r=>r[c]!==null && r[c]!==undefined && r[c]!=='' ));
  const sort0 = (state.sorts[tab]||[])[0];
  const hdr = shown.map(c=>{
    const marker = sort0 && sort0.col===c ? (sort0.dir==='asc'?' ▲':' ▼') : '';
    return `<th data-sort-tab="${tab}" data-sort-col="${c}">${c}${marker}</th>`;
  }).join('');
  const body = rows.map(r=>`<tr>${shown.map(c=>valueCell(c,r[c])).join('')}</tr>`).join('');
  const shownCount = rows.length;
  const loadMore = total>shownCount
    ? `<div class="meta" style="padding:8px 4px">Showing ${shownCount} of ${total} <button class="btn" data-loadmore="${tab}">Load ${PAGE_SIZE} more</button></div>`
    : `<div class="meta" style="padding:8px 4px">Showing all ${total} results</div>`;
  return `<div class="table-wrap"><table><thead><tr>${hdr}</tr></thead><tbody>${body}</tbody></table>${loadMore}</div>`;
}

function topPills(tab){
  const f = state.filters[tab] || {};
  return [1,2,5,10,20].map(p=>`<span class="pill ${f.topPct===p?'active':''}" data-top="${tab}" data-v="${p}">TOP ${p}%</span>`).join('');
}
function commonControls(tab, opts={}){
  const f = state.filters[tab] || {};
  const has10 = CACHE.meta.has_sma10, has20 = CACHE.meta.has_sma20;
  return `<div class="controls">
    ${opts.top ? `<div class="chips">${topPills(tab)}</div>` : ''}
    ${opts.minTf ? `<div class="chips">${[2,3,4].map(v=>`<span class="pill ${(f.minTf||2)===v?'active':''}" data-min-tf="${v}">${v}</span>`).join('')}</div>` : ''}
    ${opts.accel ? `<label><input type="checkbox" data-f="${tab}" data-k="accel" ${f.accel?'checked':''}/> Accelerating Only</label>` : ''}
    ${opts.rising !== false ? `<label><input type="checkbox" data-f="${tab}" data-k="rising" ${f.rising?'checked':''}/> RS Δ Rising</label>` : ''}
    <label><input type="checkbox" data-f="${tab}" data-k="near52" ${f.near52?'checked':''}/> Near 52W Hi</label>
    ${has10 ? `<button class="btn" data-toggle="${tab}" data-k="sma10">SMA10 ↑ ${f.sma10?'ON':'OFF'}</button>` : ''}
    ${has20 ? `<button class="btn" data-toggle="${tab}" data-k="sma20">SMA20 ↑ ${f.sma20?'ON':'OFF'}</button>` : ''}
    <button class="btn" data-toggle="${tab}" data-k="sma50">SMA50 ↑ ${f.sma50?'ON':'OFF'}</button>
    <button class="btn" data-toggle="${tab}" data-k="sma200">SMA200 ↑ ${f.sma200?'ON':'OFF'}</button>
  </div>`;
}
function renderTableTab(tab, cols, controlsHtml){
  const panel = document.querySelector(`[data-panel="${tab}"]`);
  const all = getSortedFilteredRows(tab);
  const pageSize = state.page[tab] || PAGE_SIZE;
  const visible = all.slice(0, pageSize);
  panel.innerHTML = controlsHtml + tableHtml(tab, visible, cols, all.length);
}
function renderLeaders(tab){
  const cols = ['rank','ticker','sector','exchange','rs_delta','rs_delta_momentum','pct_from_52w_high','price_vs_sma10','price_vs_sma20','price_vs_sma50','price_vs_sma200','percentile','pct_1m','pct_3m','pct_6m','pct_12m','rs_score','market_cap','avg_vol_30d','elite_count'];
  renderTableTab(tab, cols, commonControls(tab,{top:true}));
}
function renderCross(){
  const cols = ['rank','ticker','sector','exchange','tf_count_10','avg_pct','shape_score','rs_delta','rs_delta_momentum','pct_from_52w_high','price_vs_sma10','price_vs_sma20','price_vs_sma50','price_vs_sma200','pct_1m','pct_3m','pct_6m','pct_12m','rs_score','elite_count'];
  renderTableTab('Cross-TF', cols, commonControls('Cross-TF',{minTf:true,accel:true}));
}
function renderMomentum(){
  const cols = ['rank','ticker','sector','exchange','accel','rs_delta','rs_delta_momentum','pct_from_52w_high','price_vs_sma10','price_vs_sma20','price_vs_sma50','price_vs_sma200','pct_1m','pct_3m','pct_6m','pct_12m','rs_score','avg_vol_30d'];
  renderTableTab('Momentum', cols, commonControls('Momentum',{top:false}));
}
function renderSectors(){
  const p = document.querySelector('[data-panel="Sectors"]');
  const cards = (CACHE.sectors||[]).map(s=>`
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center"><h4 style="margin:0">${s.sector}</h4><span class="mono">${s.count} stocks</span></div>
      <div class="mono" style="font-size:30px;font-weight:700;margin:8px 0">${fmt(s.composite,1)}</div>
      ${[['breadth_1m',s.breadth_1m],['breadth_3m',s.breadth_3m],['breadth_6m',s.breadth_6m],['ceiling',s.ceiling],['avg',s.avg]].map(([k,v])=>`<div style="margin:6px 0"><div style="display:flex;justify-content:space-between"><span>${k}</span><span class="mono">${fmt(v,1)}</span></div><div class="bar"><span style="width:${Math.max(0,Math.min(100,Number(v)||0))}%"></span></div></div>`).join('')}
      <div style="margin-top:8px" class="chips">${(s.top5||[]).map(t=>`<span class="pill">${t}</span>`).join('')}</div>
      <div style="margin-top:8px;color:#9ca8ba">Top industries: ${(s.top_industries||[]).join(', ') || '-'}</div>
    </div>`).join('');
  p.innerHTML = `<div class="meta" style="margin-bottom:8px">composite=(multi_breadth*0.4)+(ceiling*0.4)+(avg*0.2), multi_breadth=(breadth_1m*0.5)+(breadth_3m*0.3)+(breadth_6m*0.2)</div><div class="cards">${cards}</div>`;
}

function renderMeta(){ const m=CACHE.meta||{}; document.getElementById('meta').textContent=`Date ${m.date||'-'} | Liquid ${m.liquid_count||0} | Universe ${m.total_count||0}`; }
function renderShell(){
  document.getElementById('tabs').innerHTML = TAB_LIST.map(t=>`<button class="tab ${state.activeTab===t?'active':''}" data-tab="${t}">${t}</button>`).join('');
  document.getElementById('panels').innerHTML = TAB_LIST.map(t=>`<div class="panel ${state.activeTab===t?'active':''}" data-panel="${t}"></div>`).join('');
}
function renderTab(tab){
  state.activeTab = tab;
  renderShell();
  if(tab==='RS Leaders') return renderLeaders('RS Leaders');
  if(tab==='1M Leaders') return renderLeaders('1M Leaders');
  if(tab==='3M Leaders') return renderLeaders('3M Leaders');
  if(tab==='6M Leaders') return renderLeaders('6M Leaders');
  if(tab==='12M Leaders') return renderLeaders('12M Leaders');
  if(tab==='Cross-TF') return renderCross();
  if(tab==='Momentum') return renderMomentum();
  return renderSectors();
}

function onFilterChange(tab){ state.page[tab]=PAGE_SIZE; renderTab(tab); }
function switchTab(tab){
  state.sorts[tab] = [];
  state.page[tab] = PAGE_SIZE;
  renderTab(tab);
}

function renderHelp(){
  const tabs=['Overview','Columns','Tabs & Filters','Setups','Workflow'];
  document.getElementById('helpTabs').innerHTML=tabs.map((t,i)=>`<button class="tab ${i===0?'active':''}" data-ht="${t}">${t}</button>`).join('');
  const content = {
    'Overview':'RS is a screening tool, not a trigger. Always confirm Stage 2 structure, VCP behavior, and volume contraction on chart before entry.',
    'Columns':'Percentiles are rank scores (0-100). RS Δ is 4-week change proxy. SMA values are percent distance from moving averages.',
    'Tabs & Filters':'Use leader tabs for strongest names, Cross-TF for persistence, Momentum for acceleration, Sectors for rotation context.',
    'Setups':'<div class="chips"><button class="btn" data-preset="HIGH CONVICTION">HIGH CONVICTION</button><button class="btn" data-preset="CATCHING BREATH">CATCHING BREATH</button><button class="btn" data-preset="STALLING LEADER">STALLING LEADER</button><button class="btn" data-preset="EMERGING LEADER">EMERGING LEADER</button></div>',
    'Workflow':'1) Check SPY vs key MAs. 2) Focus top 2-3 sectors. 3) Cross-TF MIN=3 accelerating. 4) Momentum tab with RS Δ rising + near highs. 5) Cross-reference names across tabs. 6) Run chart review before entry.'
  };
  document.getElementById('helpPanels').innerHTML=tabs.map((t,i)=>`<div class="panel ${i===0?'active':''}" data-hp="${t}"><p>${content[t]}</p></div>`).join('');
}

function bindEvents(){
  document.addEventListener('click',ev=>{
    const t=ev.target;
    if(t.matches('[data-tab]')) return switchTab(t.dataset.tab);
    if(t.matches('[data-sort-col]')){ updateSort(t.dataset.sortTab,t.dataset.sortCol,ev.shiftKey); return renderTab(t.dataset.sortTab); }
    if(t.matches('[data-toggle]')){ const tab=t.dataset.toggle; const k=t.dataset.k; state.filters[tab][k]=!state.filters[tab][k]; return onFilterChange(tab); }
    if(t.matches('[data-top]')){ const tab=t.dataset.top; const v=Number(t.dataset.v); state.filters[tab].topPct = state.filters[tab].topPct===v ? null : v; return onFilterChange(tab); }
    if(t.matches('[data-min-tf]')){ state.filters['Cross-TF'].minTf = Number(t.dataset.minTf); return onFilterChange('Cross-TF'); }
    if(t.matches('[data-loadmore]')){ const tab=t.dataset.loadmore; state.page[tab]=(state.page[tab]||PAGE_SIZE)+PAGE_SIZE; return renderTab(tab); }
    if(t.matches('[data-ht]')){
      document.querySelectorAll('[data-ht]').forEach(x=>x.classList.remove('active'));
      document.querySelectorAll('[data-hp]').forEach(x=>x.classList.remove('active'));
      t.classList.add('active');
      const panel=document.querySelector(`[data-hp="${t.dataset.ht}"]`); if(panel) panel.classList.add('active');
      return;
    }
    if(t.matches('[data-preset]')){
      const p=t.dataset.preset;
      if(p==='HIGH CONVICTION'){ state.filters['RS Leaders']={near52:true,sma50:true,sma200:true}; state.sorts['RS Leaders']=[{col:'rs_score',dir:'desc'}]; state.page['RS Leaders']=PAGE_SIZE; renderTab('RS Leaders'); }
      if(p==='CATCHING BREATH'){ state.filters['RS Leaders']={sma50:true,sma200:true}; state.sorts['RS Leaders']=[{col:'pct_from_52w_high',dir:'desc'}]; state.page['RS Leaders']=PAGE_SIZE; renderTab('RS Leaders'); }
      if(p==='STALLING LEADER'){ state.filters['RS Leaders']={}; state.sorts['RS Leaders']=[{col:'rs_delta',dir:'asc'}]; state.page['RS Leaders']=PAGE_SIZE; renderTab('RS Leaders'); }
      if(p==='EMERGING LEADER'){ state.filters['Cross-TF']={accel:true,minTf:2}; state.sorts['Cross-TF']=[{col:'tf_count_10',dir:'desc'},{col:'avg_pct',dir:'desc'}]; state.page['Cross-TF']=PAGE_SIZE; renderTab('Cross-TF'); }
      document.getElementById('helpModal').classList.remove('open');
      return;
    }
  });
  document.addEventListener('change',ev=>{
    const t=ev.target;
    if(t.matches('input[data-f]')){ const tab=t.dataset.f; const k=t.dataset.k; state.filters[tab][k]=t.checked; onFilterChange(tab); }
  });
  document.getElementById('helpBtn').onclick=()=>document.getElementById('helpModal').classList.add('open');
  document.getElementById('closeHelp').onclick=()=>document.getElementById('helpModal').classList.remove('open');
  document.getElementById('loadCsvBtn').onclick=()=>document.getElementById('csvInput').click();
  document.getElementById('csvInput').onchange=async ev=>{
    const file = ev.target.files[0]; if(!file) return;
    const rows = parseCsv(await file.text());
    buildCacheFromRows(rows);
    resetUiState();
    renderMeta();
    renderTab(state.activeTab);
  };
}

loadEmbedded();
resetUiState();
renderMeta();
renderHelp();
bindEvents();
renderTab(state.activeTab);
"""
    c = """
</script>
</body>
</html>
"""
    return a, b, c


def build_html(payload: dict, output_path: str) -> None:
    a, b, c = get_template()
    data_json = json.dumps(payload, separators=(",", ":"))
    html = a + "const EMBEDDED =" + data_json + ";\n" + b + c
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US RS dashboard")
    parser.add_argument("csv", nargs="?", default=None, help="Path to us_rs_rankings_*.csv")
    parser.add_argument("--output", "-o", default=None, help="Optional single output HTML path")
    args = parser.parse_args()

    rankings = args.csv or find_latest_csv()
    industries = find_latest_industries() or fetch_industries_snapshot()
    payload = load_payload(rankings, industries)

    date_slug = str(payload["meta"]["date"]).replace("-", "")
    dated_output = os.path.join(OUTPUT_ROOT, f"us_rs_dashboard_{date_slug}.html")
    docs_output = os.path.join(DOCS_DIR, "index.html")

    targets = [args.output] if args.output else [dated_output, docs_output]
    for path in targets:
        build_html(payload, path)
        print(f"   Wrote {path}")
    print("✅ Dashboard build complete")


if __name__ == "__main__":
    main()
