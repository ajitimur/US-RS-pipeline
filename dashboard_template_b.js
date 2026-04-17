
const state = { data: EMBEDDED, activeTab: 'RS Leaders', sorts:{}, filters:{} };
const TAB_LIST = ['RS Leaders','1M Leaders','3M Leaders','6M Leaders','12M Leaders','Cross-TF','Momentum','Sectors'];
const LEADER_COLS = ['rank','ticker','sector','exchange','rs_delta','rs_delta_momentum','pct_from_52w_high','price_vs_sma10','price_vs_sma20','price_vs_sma50','price_vs_sma200','percentile','pct_1m','pct_3m','pct_6m','pct_12m','rs_score','market_cap','avg_vol_30d','elite_count'];
const CROSS_COLS = ['rank','ticker','sector','exchange','tf_count_10','avg_pct','shape_score','rs_delta','rs_delta_momentum','pct_from_52w_high','price_vs_sma50','price_vs_sma200','pct_1m','pct_3m','pct_6m','pct_12m','rs_score','elite_count'];
const MOM_COLS = ['rank','ticker','sector','exchange','accel','rs_delta','rs_delta_momentum','pct_from_52w_high','price_vs_sma50','price_vs_sma200','pct_1m','pct_3m','pct_6m','pct_12m','rs_score','avg_vol_30d'];
const PCT_COLS = new Set(['percentile','pct_1m','pct_3m','pct_6m','pct_12m']);
const SMA_COLS = new Set(['price_vs_sma10','price_vs_sma20','price_vs_sma50','price_vs_sma200']);
const ROWS_TOP = 30;

const fmt = (v,d=1)=> (v===null||v===undefined||Number.isNaN(v))?'':Number(v).toFixed(d);
const clsPct = v => v>=80?'g':(v<50?'r':'');
const clsRsd = v => v>5?'g':(v<-5?'r':'');
const cls52 = v => v>=-10?'g':(v<-25?'r':'a');
const clsSma = v => v>0?'g':'r';

function badge(text,cls){ return `<span class="badge ${cls} mono">${text??''}</span>`; }
function metaLine(){ const m=state.data.meta||{}; document.getElementById('meta').textContent=`Date ${m.date||'-'} | Liquid ${m.liquid_count||0} | Universe ${m.total_count||0}`; }
function tabButtons(){ document.getElementById('tabs').innerHTML = TAB_LIST.map(t=>`<button class="tab ${state.activeTab===t?'active':''}" data-tab="${t}">${t}</button>`).join(''); }
function panels(){ document.getElementById('panels').innerHTML = TAB_LIST.map(t=>`<div class="panel ${state.activeTab===t?'active':''}" data-panel="${t}"></div>`).join(''); }

function applyCommonFilters(rows,f){
  return rows.filter(r=>{
    if(f.rsDeltaRising && !(Number(r.rs_delta)>0)) return false;
    if(f.near52 && !(Number(r.pct_from_52w_high)>=-15)) return false;
    if(f.sma50 && !(Number(r.price_vs_sma50)>0)) return false;
    if(f.sma200 && !(Number(r.price_vs_sma200)>0)) return false;
    if(f.topPct){
      const p = Number(r.percentile||0);
      const min = 100 - f.topPct;
      if(!(p>=min)) return false;
    }
    return true;
  });
}

function sortRows(rows,tab){
  const sorters = state.sorts[tab] || [{key: tab==='Momentum'?'accel':'rs_score', dir:'desc'}];
  return [...rows].sort((a,b)=>{
    for(const s of sorters){
      const av = a[s.key], bv = b[s.key];
      if(av===bv) continue;
      const na = Number(av), nb = Number(bv);
      const bothNum = !Number.isNaN(na) && !Number.isNaN(nb);
      const cmp = bothNum ? (na-nb) : String(av??'').localeCompare(String(bv??''));
      if(cmp!==0) return s.dir==='asc'?cmp:-cmp;
    }
    return 0;
  });
}

function headerCell(tab,col,label){
  return `<th data-sort-tab="${tab}" data-sort-col="${col}">${label||col}</th>`;
}
function td(col,v){
  if(col==='ticker') return `<td class="mono" style="text-align:left">${v||''}</td>`;
  if(col==='sector') return `<td style="text-align:left">${badge(v,'sector')}</td>`;
  if(col==='exchange') return `<td>${badge(v,'exch')}</td>`;
  let cls = '';
  if(PCT_COLS.has(col)) cls = clsPct(Number(v));
  if(col==='rs_delta') cls = clsRsd(Number(v));
  if(col==='pct_from_52w_high') cls = cls52(Number(v));
  if(SMA_COLS.has(col)) cls = clsSma(Number(v));
  const d = ['rank','tf_count_10','elite_count'].includes(col)?0:1;
  return `<td class="mono ${cls}">${typeof v==='number'?fmt(v,d):(v??'')}</td>`;
}

function tableHtml(tab,rows,cols){
  const shown = cols.filter(c=>rows.some(r=>r[c]!==null && r[c]!==undefined && r[c]!=='' ));
  const hdr = shown.map(c=>headerCell(tab,c,c)).join('');
  const body = rows.map(r=>`<tr>${shown.map(c=>td(c,r[c])).join('')}</tr>`).join('');
  return `<div style="overflow:auto"><table><thead><tr>${hdr}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function controlsLeader(tab){
  const f = state.filters[tab]||{};
  return `<div class="controls">
    <label><input type="checkbox" data-f="${tab}" data-k="rsDeltaRising" ${f.rsDeltaRising?'checked':''}/> RS Δ Rising</label>
    <label><input type="checkbox" data-f="${tab}" data-k="near52" ${f.near52?'checked':''}/> Near 52W Hi</label>
    <button class="btn" data-toggle="${tab}" data-k="sma50">SMA50 ↑ ${f.sma50?'ON':'OFF'}</button>
    <button class="btn" data-toggle="${tab}" data-k="sma200">SMA200 ↑ ${f.sma200?'ON':'OFF'}</button>
    <div class="chips">${[1,2,5,10,20].map(p=>`<span class="pill ${f.topPct===p?'active':''}" data-top="${tab}" data-v="${p}">TOP ${p}%</span>`).join('')}</div>
  </div>`;
}

function renderLeaders(tab,key){
  const p = document.querySelector(`[data-panel="${tab}"]`);
  const f = state.filters[tab]||{};
  let rows = sortRows(applyCommonFilters(state.data.stocks,f),tab).slice(0,ROWS_TOP);
  rows = sortRows(rows,tab==='RS Leaders'?tab:key);
  p.innerHTML = controlsLeader(tab) + tableHtml(tab, rows.sort((a,b)=>Number(b[key])-Number(a[key])), LEADER_COLS);
}

function renderCross(){
  const tab = 'Cross-TF';
  const p = document.querySelector('[data-panel="Cross-TF"]');
  const f = state.filters[tab]||{};
  let rows = [...state.data.cross];
  rows = rows.filter(r=>Number(r.tf_count_10)>=Number(f.minTf||2));
  if(f.accelOnly) rows = rows.filter(r=>Number(r.shape_score)>0);
  rows = applyCommonFilters(rows,f);
  rows = sortRows(rows,tab);
  p.innerHTML = `<div class="controls">
    <div class="chips">${[2,3,4].map(v=>`<span class="pill ${Number(f.minTf||2)===v?'active':''}" data-min-tf="${v}">${v}</span>`).join('')}</div>
    <label><input type="checkbox" data-f="${tab}" data-k="accelOnly" ${f.accelOnly?'checked':''}/> Accelerating Only</label>
    <label><input type="checkbox" data-f="${tab}" data-k="rsDeltaRising" ${f.rsDeltaRising?'checked':''}/> RS Δ Rising</label>
    <button class="btn" data-toggle="${tab}" data-k="sma50">SMA50 ↑ ${f.sma50?'ON':'OFF'}</button>
    <button class="btn" data-toggle="${tab}" data-k="sma200">SMA200 ↑ ${f.sma200?'ON':'OFF'}</button>
  </div>` + tableHtml(tab, rows, CROSS_COLS);
}

function renderMomentum(){
  const tab = 'Momentum';
  const p = document.querySelector('[data-panel="Momentum"]');
  const f = state.filters[tab]||{};
  let rows = [...state.data.momentum];
  if(f.near52) rows = rows.filter(r=>Number(r.pct_from_52w_high)>=-15);
  if(f.rsDeltaRising) rows = rows.filter(r=>Number(r.rs_delta)>0);
  if(f.sma200) rows = rows.filter(r=>Number(r.price_vs_sma200)>0);
  rows = sortRows(rows,tab);
  p.innerHTML = `<div class="controls">
    <label><input type="checkbox" data-f="${tab}" data-k="near52" ${f.near52?'checked':''}/> Near 52W Hi</label>
    <label><input type="checkbox" data-f="${tab}" data-k="rsDeltaRising" ${f.rsDeltaRising?'checked':''}/> RS Δ Rising</label>
    <button class="btn" data-toggle="${tab}" data-k="sma200">SMA200 ↑ ${f.sma200?'ON':'OFF'}</button>
  </div>` + tableHtml(tab, rows, MOM_COLS);
}

function renderSectors(){
  const p = document.querySelector('[data-panel="Sectors"]');
  const cards = (state.data.sectors||[]).map(s=>`
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center"><h4 style="margin:0">${s.sector}</h4><span class="mono">${s.count} stocks</span></div>
      <div class="mono" style="font-size:30px;font-weight:700;margin:8px 0">${fmt(s.composite,1)}</div>
      ${[['breadth_1m',s.breadth_1m],['breadth_3m',s.breadth_3m],['breadth_6m',s.breadth_6m],['ceiling',s.ceiling],['avg',s.avg]].map(([k,v])=>`<div style="margin:6px 0"><div style="display:flex;justify-content:space-between"><span>${k}</span><span class="mono">${fmt(v,1)}</span></div><div class="bar"><span style="width:${Math.max(0,Math.min(100,Number(v)||0))}%"></span></div></div>`).join('')}
      <div style="margin-top:8px" class="chips">${(s.top5||[]).map(t=>`<span class="pill">${t}</span>`).join('')}</div>
      <div style="margin-top:8px;color:#9ca8ba">Top industries: ${(s.top_industries||[]).join(', ') || '-'}</div>
    </div>`).join('');
  p.innerHTML = `<div class="meta" style="margin-bottom:8px">composite=(multi_breadth*0.4)+(ceiling*0.4)+(avg*0.2), multi_breadth=(breadth_1m*0.5)+(breadth_3m*0.3)+(breadth_6m*0.2)</div><div class="cards">${cards}</div>`;
}

function renderActive(){
  metaLine(); tabButtons(); panels();
  renderLeaders('RS Leaders','rs_score');
  renderLeaders('1M Leaders','pct_1m');
  renderLeaders('3M Leaders','pct_3m');
  renderLeaders('6M Leaders','pct_6m');
  renderLeaders('12M Leaders','pct_12m');
  renderCross(); renderMomentum(); renderSectors();
}

function updateSort(tab,col,shift){
  const arr = state.sorts[tab] || [];
  const i = arr.findIndex(s=>s.key===col);
  if(i>=0){ arr[i].dir = arr[i].dir==='asc'?'desc':'asc'; }
  else { arr.push({key:col,dir:'desc'}); }
  state.sorts[tab] = shift ? arr : [arr[arr.length-1]];
}

function bind(){
  document.addEventListener('click',ev=>{
    const t = ev.target;
    if(t.matches('[data-tab]')){ state.activeTab=t.dataset.tab; renderActive(); bind(); return; }
    if(t.matches('[data-sort-col]')){ updateSort(t.dataset.sortTab,t.dataset.sortCol,ev.shiftKey); renderActive(); bind(); return; }
    if(t.matches('[data-toggle]')){ const tab=t.dataset.toggle; const k=t.dataset.k; state.filters[tab]=state.filters[tab]||{}; state.filters[tab][k]=!state.filters[tab][k]; renderActive(); bind(); return; }
    if(t.matches('[data-top]')){ const tab=t.dataset.top; state.filters[tab]=state.filters[tab]||{}; const v=Number(t.dataset.v); state.filters[tab].topPct=(state.filters[tab].topPct===v?null:v); renderActive(); bind(); return; }
    if(t.matches('[data-min-tf]')){ state.filters['Cross-TF']=state.filters['Cross-TF']||{}; state.filters['Cross-TF'].minTf=Number(t.dataset.minTf); renderActive(); bind(); return; }
  });
  document.addEventListener('change',ev=>{
    const t = ev.target;
    if(t.matches('input[data-f]')){ const tab=t.dataset.f; const k=t.dataset.k; state.filters[tab]=state.filters[tab]||{}; state.filters[tab][k]=t.checked; renderActive(); bind(); }
  });
  document.getElementById('helpBtn').onclick=()=>{ document.getElementById('helpModal').classList.add('open'); };
  document.getElementById('closeHelp').onclick=()=>{ document.getElementById('helpModal').classList.remove('open'); };
  document.getElementById('loadCsvBtn').onclick=()=>document.getElementById('csvInput').click();
  document.getElementById('csvInput').onchange=async ev=>{
    const file = ev.target.files[0]; if(!file) return;
    const txt = await file.text();
    const [h,...rows] = txt.trim().split(/\r?\n/);
    const cols = h.split(',');
    state.data.stocks = rows.map(line=>{ const vals=line.split(','); const o={}; cols.forEach((c,i)=>{ const raw=vals[i]; const n=Number(raw); o[c]=Number.isNaN(n)?raw:n; }); return o; });
    state.data.cross = state.data.stocks.filter(r=>Number(r.tf_count_10)>=2);
    state.data.momentum = state.data.stocks.filter(r=>Number(r.pct_1m)>Number(r.pct_3m) && Number(r.pct_3m)>Number(r.pct_12m) && Number(r.pct_1m)>=60 && (Number(r.pct_1m)-Number(r.pct_3m))>=10).map(r=>({...r,accel:Number(r.pct_1m)-Number(r.pct_3m)}));
    state.data.meta = { ...(state.data.meta||{}), liquid_count: state.data.stocks.length, total_count: state.data.stocks.length };
    renderActive(); bind();
  };
  renderHelp();
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
  document.querySelectorAll('[data-ht]').forEach(btn=>btn.onclick=()=>{
    document.querySelectorAll('[data-ht]').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('[data-hp]').forEach(x=>x.classList.remove('active'));
    btn.classList.add('active');
    document.querySelector(`[data-hp="${btn.dataset.ht}"]`).classList.add('active');
  });
  document.addEventListener('click',ev=>{
    const p = ev.target.dataset.preset; if(!p) return;
    if(p==='HIGH CONVICTION'){ state.activeTab='RS Leaders'; state.filters['RS Leaders']={near52:true,sma50:true,sma200:true}; state.sorts['RS Leaders']=[{key:'rs_score',dir:'desc'}]; }
    if(p==='CATCHING BREATH'){ state.activeTab='RS Leaders'; state.filters['RS Leaders']={sma50:true,sma200:true}; state.sorts['RS Leaders']=[{key:'pct_from_52w_high',dir:'desc'}]; }
    if(p==='STALLING LEADER'){ state.activeTab='RS Leaders'; state.filters['RS Leaders']={}; state.sorts['RS Leaders']=[{key:'rs_delta',dir:'asc'}]; }
    if(p==='EMERGING LEADER'){ state.activeTab='Cross-TF'; state.filters['Cross-TF']={accelOnly:true,minTf:2}; state.sorts['Cross-TF']=[{key:'tf_count_10',dir:'desc'},{key:'avg_pct',dir:'desc'}]; }
    document.getElementById('helpModal').classList.remove('open'); renderActive(); bind();
  });
}

renderActive(); bind();

