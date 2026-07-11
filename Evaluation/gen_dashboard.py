"""
Generates Evaluation/indicator_dashboard.html — a self-contained interactive chart
of all indicator CSVs found in Evaluation/Indicators/.

Run standalone:  python Evaluation/gen_dashboard.py
Called from main loop via generate_dashboard(base_dir).
"""
import sys
import json
import os
import math
import logging
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

# Rows of 1d history to include in the dashboard (≈10 years)
CHART_ROWS = 2520

# ── HTML template ─────────────────────────────────────────────────────────────
# Plain string (not f-string) so JavaScript {} are kept as literals.
# @@DATA@@ and @@TICKERS@@ are substituted at generation time.
TMPL = """<title>Stock Indicator Dashboard</title>
<style>
:root {
  --bg:  #eef2f7; --sf:  #ffffff; --sf2: #e4ecf5;
  --ink: #0d1624; --ink2:#3a5068; --mu:  #7590a8;
  --gr:  #cdd8e6; --bd:  rgba(20,60,100,.12);
  --acc: #1a56db;
  --c1:  #1a56db; --c2:  #0d9488; --c3:  #c97b06;
  --zg:  rgba(5,150,105,.09); --zb:  rgba(220,38,38,.08);
  --rg:  #059669; --rb:  #dc2626; --tbg: #e9eff7;
}
@media (prefers-color-scheme:dark){:root{
  --bg:  #070b12; --sf:  #0e1520; --sf2: #162030;
  --ink: #d4e4f4; --ink2:#7a98b8; --mu:  #4a6278;
  --gr:  #1a2840; --bd:  rgba(100,180,255,.08);
  --acc: #4d8ef0;
  --c1:  #4d8ef0; --c2:  #14b8a6; --c3:  #f59e0b;
  --zg:  rgba(20,184,166,.08); --zb:  rgba(248,113,113,.08);
  --rg:  #10b981; --rb:  #f87171; --tbg: #111c2c;
}}
:root[data-theme=dark]{
  --bg:#070b12;--sf:#0e1520;--sf2:#162030;
  --ink:#d4e4f4;--ink2:#7a98b8;--mu:#4a6278;
  --gr:#1a2840;--bd:rgba(100,180,255,.08);--acc:#4d8ef0;
  --c1:#4d8ef0;--c2:#14b8a6;--c3:#f59e0b;
  --zg:rgba(20,184,166,.08);--zb:rgba(248,113,113,.08);
  --rg:#10b981;--rb:#f87171;--tbg:#111c2c;
}
:root[data-theme=light]{
  --bg:#eef2f7;--sf:#ffffff;--sf2:#e4ecf5;
  --ink:#0d1624;--ink2:#3a5068;--mu:#7590a8;
  --gr:#cdd8e6;--bd:rgba(20,60,100,.12);--acc:#1a56db;
  --c1:#1a56db;--c2:#0d9488;--c3:#c97b06;
  --zg:rgba(5,150,105,.09);--zb:rgba(220,38,38,.08);
  --rg:#059669;--rb:#dc2626;--tbg:#e9eff7;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:13px;min-height:100vh}
.app{display:flex;flex-direction:column;max-width:1160px;margin:0 auto;padding:0 16px 32px}
.bar{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:10px 0;border-bottom:1px solid var(--bd);margin-bottom:12px}
.appname{font-family:'SF Mono','Fira Code','Cascadia Code','Consolas',monospace;font-size:11px;font-weight:600;letter-spacing:.08em;color:var(--acc);text-transform:uppercase;padding:3px 8px;background:var(--sf2);border-radius:3px;border:1px solid var(--bd);white-space:nowrap}
.sep{color:var(--gr);user-select:none;font-size:16px;line-height:1}
.tabs{display:flex;flex-wrap:wrap;gap:3px}
.tab{font-family:'SF Mono','Fira Code','Cascadia Code','Consolas',monospace;font-size:11px;font-weight:600;letter-spacing:.03em;padding:3px 9px;border-radius:3px;border:1px solid transparent;background:transparent;color:var(--mu);cursor:pointer;transition:color .12s,background .12s}
.tab:hover{color:var(--ink2);background:var(--sf2)}
.tab.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.spacer{flex:1}
.rbts{display:flex;gap:2px}
.rbt{font-size:11px;font-weight:500;padding:3px 9px;border-radius:3px;border:1px solid var(--bd);background:transparent;color:var(--mu);cursor:pointer;transition:color .12s,background .12s}
.rbt:hover{color:var(--ink2);background:var(--sf2)}
.rbt.on{background:var(--sf2);color:var(--ink);border-color:var(--gr)}
.slab{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:14px 0 5px}
.stitle{font-size:10px;font-weight:700;letter-spacing:.10em;text-transform:uppercase;color:var(--mu)}
.sdesc{font-size:11px;color:var(--mu)}
.leg{display:flex;gap:14px;margin-left:4px}
.li{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--ink2)}
.ls{width:16px;height:2px;border-radius:1px;flex-shrink:0}
.cw{position:relative;border:1px solid var(--bd);border-radius:4px;overflow:hidden;background:var(--sf)}
.cw-lg{height:230px}
.cw-sm{height:180px}
canvas{display:block;width:100%;height:100%;cursor:crosshair}
.tkbadge{position:absolute;top:7px;left:62px;font-family:'SF Mono','Fira Code','Cascadia Code','Consolas',monospace;font-size:11px;font-weight:700;letter-spacing:.04em;color:var(--mu);pointer-events:none;user-select:none}
#tt{position:fixed;pointer-events:none;z-index:99;display:none;background:var(--sf);border:1px solid var(--bd);border-radius:5px;padding:9px 12px;box-shadow:0 4px 16px rgba(0,0,0,.18);min-width:174px}
.ttdate{font-family:'SF Mono','Fira Code','Cascadia Code','Consolas',monospace;font-size:11px;font-weight:600;color:var(--ink);margin-bottom:6px;letter-spacing:.02em}
.ttr{display:flex;justify-content:space-between;gap:16px;line-height:1.8}
.ttl{font-size:11px;color:var(--mu)}
.ttv{font-family:'SF Mono','Fira Code','Cascadia Code','Consolas',monospace;font-size:11px;font-weight:500;color:var(--ink);font-variant-numeric:tabular-nums}
.bge{font-family:'SF Mono','Fira Code','Cascadia Code','Consolas',monospace;font-size:9px;font-weight:700;letter-spacing:.05em;padding:1px 5px;border-radius:2px;margin-left:4px;vertical-align:middle}
.bge.buy{background:var(--zg);color:var(--rg)}
.bge.sell{background:var(--zb);color:var(--rb)}
.ttdiv{border:none;border-top:1px solid var(--bd);margin:5px 0 4px}
.tbtrig{margin:16px 0 6px;display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;width:fit-content}
.tbtrig-arrow{font-size:10px;color:var(--mu);transition:transform .15s}
.tbtrig-arrow.open{transform:rotate(90deg)}
.tbtrig-lbl{font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--mu)}
.tbtrig:hover .tbtrig-lbl,.tbtrig:hover .tbtrig-arrow{color:var(--ink2)}
.tbw{overflow:auto;border:1px solid var(--bd);border-radius:4px;max-height:320px}
.tbw[hidden]{display:none}
table{width:100%;border-collapse:collapse;font-size:11px;font-variant-numeric:tabular-nums;font-family:'SF Mono','Fira Code','Cascadia Code','Consolas',monospace}
thead th{position:sticky;top:0;background:var(--sf2);border-bottom:1px solid var(--bd);padding:5px 10px;text-align:right;font-weight:600;letter-spacing:.04em;color:var(--mu);white-space:nowrap;font-size:10px}
thead th:first-child{text-align:left}
tbody td{padding:3px 10px;text-align:right;color:var(--ink2);border-bottom:1px solid var(--gr)}
tbody td:first-child{text-align:left;color:var(--mu)}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:var(--tbg)}
.foot{margin-top:20px;padding-top:12px;border-top:1px solid var(--bd);font-family:'SF Mono','Fira Code','Cascadia Code','Consolas',monospace;font-size:10px;color:var(--mu);letter-spacing:.02em}
</style>

<div class="app">
  <div class="bar">
    <span class="appname">PSU · Indicators</span>
    <span class="sep">|</span>
    <div class="tabs" id="tabs"></div>
    <div class="spacer"></div>
    <div class="rbts">
      <button class="rbt" data-r="3m">3M</button>
      <button class="rbt" data-r="1y">1Y</button>
      <button class="rbt on" data-r="3y">3Y</button>
      <button class="rbt" data-r="max">MAX</button>
    </div>
  </div>

  <div class="slab">
    <span class="stitle">Price &amp; Moving Averages</span>
    <div class="leg">
      <span class="li"><span class="ls" style="background:var(--c1)"></span>Close</span>
      <span class="li"><span class="ls" style="background:var(--c2)"></span>SMA 20</span>
      <span class="li"><span class="ls" style="background:var(--c3)"></span>SMA 50</span>
    </div>
    <span class="sdesc">SMA 20/50 crossover signals trend change</span>
  </div>
  <div class="cw cw-lg"><canvas id="c-sma"></canvas><span class="tkbadge" id="tkb"></span></div>

  <div class="slab">
    <span class="stitle">RSI · 14</span>
    <span class="sdesc">Zone &lt;30 oversold · Zone &gt;70 overbought</span>
  </div>
  <div class="cw cw-sm"><canvas id="c-rsi"></canvas></div>

  <div class="slab">
    <span class="stitle">Bollinger Bands · SMA 20 ± 2σ</span>
    <span class="sdesc">Shaded band = ±2 std dev · Price outside band signals over/undervalued</span>
  </div>
  <div class="cw cw-sm"><canvas id="c-bb"></canvas></div>

  <div class="slab">
    <span class="stitle">ADX · 14</span>
    <span class="sdesc">Below 20 = no directional trend · 25+ = developing · 40+ = strong</span>
  </div>
  <div class="cw cw-sm"><canvas id="c-adx"></canvas></div>

  <div class="tbtrig" id="tbtrig" role="button" tabindex="0" aria-expanded="false">
    <span class="tbtrig-arrow" id="tbarr">&#9658;</span>
    <span class="tbtrig-lbl">Data Table</span>
  </div>
  <div class="tbw" id="tbw" hidden>
    <table>
      <thead><tr>
        <th>Date</th><th>Close</th><th>SMA 20</th><th>SMA 50</th>
        <th>RSI</th><th>BB Low</th><th>BB High</th><th>ADX</th>
      </tr></thead>
      <tbody id="tbd"></tbody>
    </table>
  </div>

  <p class="foot" id="foot"></p>
</div>

<div id="tt"></div>

<script>
const DATA    = @@DATA@@;
const TICKERS = @@TICKERS@@;
const GENERATED = "@@GENERATED@@";

document.getElementById('foot').textContent =
  'Source: yfinance · Evaluation/Indicators/{ticker}_indicators.csv · Generated ' + GENERATED;

let ticker = TICKERS[0], range = '3y', hov = -1;

// ── Ticker tabs ─────────────────────────────────────────────────────────────
const tabsEl = document.getElementById('tabs');
TICKERS.forEach(t => {
  const b = document.createElement('button');
  b.className = 'tab' + (t === ticker ? ' on' : '');
  b.dataset.t = t; b.textContent = t;
  b.onclick = () => {
    ticker = t; hov = -1;
    document.querySelectorAll('.tab').forEach(x => x.classList.toggle('on', x.dataset.t === t));
    document.getElementById('tkb').textContent = t;
    renderAll(); renderTable();
  };
  tabsEl.appendChild(b);
});
document.getElementById('tkb').textContent = ticker;

document.querySelectorAll('.rbt').forEach(b => b.onclick = () => {
  range = b.dataset.r; hov = -1;
  document.querySelectorAll('.rbt').forEach(x => x.classList.toggle('on', x.dataset.r === range));
  renderAll(); renderTable();
});

// ── Slice helper ────────────────────────────────────────────────────────────
function slc() {
  const n = DATA[ticker].d.length;
  const w = {'3m':63,'1y':252,'3y':756,'max':n}[range] ?? n;
  const s = Math.max(0, n - w);
  return {s, e:n, n:n-s};
}

// ── Color tokens ────────────────────────────────────────────────────────────
function tok(name){ return getComputedStyle(document.documentElement).getPropertyValue(name).trim() }
function isDark(){
  const t = document.documentElement.dataset.theme;
  return t === 'dark' || (t !== 'light' && window.matchMedia('(prefers-color-scheme:dark)').matches);
}
function clr(){
  return {
    sf:tok('--sf'), gr:tok('--gr'), mu:tok('--mu'),
    c1:tok('--c1'), c2:tok('--c2'), c3:tok('--c3'),
    zg:tok('--zg'), zb:tok('--zb'), rg:tok('--rg'), rb:tok('--rb'),
    cr: isDark() ? 'rgba(180,215,255,.30)' : 'rgba(20,60,120,.22)',
  };
}

// ── Canvas geometry ─────────────────────────────────────────────────────────
const ML=58, MT=6, MR=16, MB=26;
const MONO = "'SF Mono','Fira Code','Cascadia Code','Consolas',monospace";

function prep(id){
  const c = document.getElementById(id), dpr = window.devicePixelRatio||1;
  const W = c.offsetWidth, H = c.offsetHeight;
  c.width = W*dpr; c.height = H*dpr;
  const ctx = c.getContext('2d'); ctx.scale(dpr,dpr);
  return {ctx, W, H, p:{x:ML, y:MT, w:W-ML-MR, h:H-MT-MB}};
}
function plotOf(id){
  const c = document.getElementById(id);
  return {x:ML, y:MT, w:c.offsetWidth-ML-MR, h:c.offsetHeight-MT-MB};
}

// ── Math ────────────────────────────────────────────────────────────────────
function px(i,n,x0,w){ return x0 + i/Math.max(n-1,1)*w }
function py(v,lo,hi,y0,h){ return y0 + h - (v-lo)/(hi-lo)*h }
function niceR(vals, pad=.06){
  const vs = vals.filter(v=>v!=null&&isFinite(v));
  if(!vs.length) return {lo:0,hi:1};
  let lo=Math.min(...vs), hi=Math.max(...vs);
  const r=(hi-lo)*pad||1;
  return {lo:lo-r, hi:hi+r};
}
function tks(lo,hi,n=5){
  const r=hi-lo, raw=r/n, mag=Math.pow(10,Math.floor(Math.log10(raw||1)));
  const nm=raw/mag, s=nm<1.5?1:nm<3?2:nm<7?5:10, step=s*mag;
  const t=[];
  for(let v=Math.ceil(lo/step)*step; v<=hi+step*.01; v=+(v+step).toFixed(12)) t.push(+v.toFixed(10));
  return t;
}
function hexA(hex,a){
  const h=hex.replace('#','');
  const [r,g,b]=[0,2,4].map(i=>parseInt(h.slice(i,i+2),16));
  return `rgba(${r},${g},${b},${a})`;
}

// ── Draw primitives ─────────────────────────────────────────────────────────
function drawGridPrice(ctx,ts,lo,hi,p,c){
  ctx.save(); ctx.strokeStyle=c.gr; ctx.lineWidth=1;
  ctx.font=`10px ${MONO}`; ctx.textAlign='right'; ctx.fillStyle=c.mu;
  for(const t of ts){
    const y=py(t,lo,hi,p.y,p.h);
    ctx.beginPath(); ctx.moveTo(p.x,y); ctx.lineTo(p.x+p.w,y); ctx.stroke();
    const lbl = t>=1000?'$'+(t/1000).toFixed(1)+'k':'$'+t.toFixed(t<10?2:0);
    ctx.fillText(lbl, p.x-5, y+3.5);
  }
  ctx.restore();
}
function drawGridNum(ctx,ts,lo,hi,p,c){
  ctx.save(); ctx.strokeStyle=c.gr; ctx.lineWidth=1;
  ctx.font=`10px ${MONO}`; ctx.textAlign='right'; ctx.fillStyle=c.mu;
  for(const t of ts){
    const y=py(t,lo,hi,p.y,p.h);
    ctx.beginPath(); ctx.moveTo(p.x,y); ctx.lineTo(p.x+p.w,y); ctx.stroke();
    ctx.fillText(t.toFixed(0), p.x-5, y+3.5);
  }
  ctx.restore();
}
function drawXAx(ctx,dates,s,e,p,c){
  const n=e-s;
  ctx.save(); ctx.strokeStyle=c.mu; ctx.lineWidth=1;
  ctx.font=`10px ${MONO}`; ctx.textAlign='center'; ctx.fillStyle=c.mu;
  const ay=p.y+p.h;
  ctx.beginPath(); ctx.moveTo(p.x,ay); ctx.lineTo(p.x+p.w,ay); ctx.stroke();
  const seen=new Set();
  for(let i=0;i<n;i++){
    const dt=dates[s+i], yr=dt.slice(0,4), mm=dt.slice(5,7), dd=+dt.slice(8);
    if(mm==='01'&&dd<=7&&!seen.has(yr)){
      seen.add(yr);
      const x=px(i,n,p.x,p.w);
      ctx.fillText(yr, x, ay+16);
      ctx.beginPath(); ctx.moveTo(x,ay); ctx.lineTo(x,ay+3); ctx.stroke();
    }
  }
  ctx.restore();
}
function drawZone(ctx,lo2,hi2,lo,hi,p,col){
  const y1=py(Math.min(hi2,hi),lo,hi,p.y,p.h), y2=py(Math.max(lo2,lo),lo,hi,p.y,p.h);
  ctx.save(); ctx.fillStyle=col; ctx.fillRect(p.x,y1,p.w,y2-y1); ctx.restore();
}
function drawRef(ctx,v,lo,hi,p,col,lbl){
  const y=py(v,lo,hi,p.y,p.h);
  ctx.save(); ctx.strokeStyle=col; ctx.lineWidth=1; ctx.globalAlpha=.45;
  ctx.setLineDash([3,3]);
  ctx.beginPath(); ctx.moveTo(p.x,y); ctx.lineTo(p.x+p.w,y); ctx.stroke();
  if(lbl){ ctx.globalAlpha=.70; ctx.setLineDash([]); ctx.font=`9px ${MONO}`; ctx.textAlign='right'; ctx.fillStyle=col; ctx.fillText(lbl,p.x+p.w-3,y-3); }
  ctx.restore();
}
function drawLine(ctx,vals,s,e,lo,hi,p,col,w=2){
  const n=e-s;
  ctx.save(); ctx.strokeStyle=col; ctx.lineWidth=w; ctx.lineJoin='round'; ctx.lineCap='round';
  ctx.beginPath(); let on=false;
  for(let i=0;i<n;i++){
    const v=vals[s+i]; if(v==null||!isFinite(v)){on=false;continue;}
    const x=px(i,n,p.x,p.w), y=py(v,lo,hi,p.y,p.h);
    if(!on){ctx.moveTo(x,y);on=true;}else ctx.lineTo(x,y);
  }
  ctx.stroke(); ctx.restore();
}
function drawBand(ctx,blo,bhi,s,e,lo,hi,p,col){
  const n=e-s;
  ctx.save(); ctx.fillStyle=col; ctx.beginPath(); let on=false;
  for(let i=0;i<n;i++){
    const v=bhi[s+i]; if(v==null){on=false;continue;}
    const x=px(i,n,p.x,p.w), y=py(v,lo,hi,p.y,p.h);
    if(!on){ctx.moveTo(x,y);on=true;}else ctx.lineTo(x,y);
  }
  for(let i=n-1;i>=0;i--){
    const v=blo[s+i]; if(v==null)continue;
    ctx.lineTo(px(i,n,p.x,p.w),py(v,lo,hi,p.y,p.h));
  }
  ctx.closePath(); ctx.fill(); ctx.restore();
}
function drawCross(ctx,idx,n,p,col){
  if(idx<0)return;
  const x=px(idx,n,p.x,p.w);
  ctx.save(); ctx.strokeStyle=col; ctx.lineWidth=1; ctx.globalAlpha=.55;
  ctx.setLineDash([4,3]);
  ctx.beginPath(); ctx.moveTo(x,p.y); ctx.lineTo(x,p.y+p.h); ctx.stroke();
  ctx.restore();
}

// ── Chart renderers ─────────────────────────────────────────────────────────
function drawSMA(){
  const {ctx,p}=prep('c-sma'); const d=DATA[ticker]; const {s,e,n}=slc(); const c=clr();
  const av=[...d.c.slice(s,e),...d.s20.slice(s,e),...d.s50.slice(s,e)].filter(v=>v!=null);
  const {lo,hi}=niceR(av);
  drawGridPrice(ctx,tks(lo,hi,5),lo,hi,p,c);
  drawXAx(ctx,d.d,s,e,p,c);
  drawLine(ctx,d.s50,s,e,lo,hi,p,c.c3,1.5);
  drawLine(ctx,d.s20,s,e,lo,hi,p,c.c2,1.5);
  drawLine(ctx,d.c,  s,e,lo,hi,p,c.c1,2);
  drawCross(ctx,hov,n,p,c.cr);
}
function drawRSI(){
  const {ctx,p}=prep('c-rsi'); const d=DATA[ticker]; const {s,e,n}=slc(); const c=clr();
  const lo=0,hi=100;
  drawZone(ctx,0,30,lo,hi,p,c.zg);
  drawZone(ctx,70,100,lo,hi,p,c.zb);
  drawGridNum(ctx,[20,50,80],lo,hi,p,c);
  drawRef(ctx,30,lo,hi,p,c.rg,'30');
  drawRef(ctx,70,lo,hi,p,c.rb,'70');
  drawXAx(ctx,d.d,s,e,p,c);
  drawLine(ctx,d.rsi,s,e,lo,hi,p,c.c1,2);
  drawCross(ctx,hov,n,p,c.cr);
}
function drawBB(){
  const {ctx,p}=prep('c-bb'); const d=DATA[ticker]; const {s,e,n}=slc(); const c=clr();
  const av=[...d.c.slice(s,e),...d.bbl.slice(s,e),...d.bbu.slice(s,e)].filter(v=>v!=null);
  const {lo,hi}=niceR(av);
  drawGridPrice(ctx,tks(lo,hi,5),lo,hi,p,c);
  drawXAx(ctx,d.d,s,e,p,c);
  drawBand(ctx,d.bbl,d.bbu,s,e,lo,hi,p,hexA(c.c1,.10));
  drawLine(ctx,d.bbu,s,e,lo,hi,p,hexA(c.c1,.45),1);
  drawLine(ctx,d.bbl,s,e,lo,hi,p,hexA(c.c1,.45),1);
  drawLine(ctx,d.c,  s,e,lo,hi,p,c.c1,2);
  drawCross(ctx,hov,n,p,c.cr);
}
function drawADX(){
  const {ctx,p}=prep('c-adx'); const d=DATA[ticker]; const {s,e,n}=slc(); const c=clr();
  const vals=d.adx.slice(s,e).filter(v=>v!=null);
  const hi=Math.max(60,vals.length?Math.max(...vals)*1.08:60), lo=0;
  drawZone(ctx,0,20,lo,hi,p,c.zg);
  drawGridNum(ctx,tks(lo,hi,5),lo,hi,p,c);
  drawRef(ctx,20,lo,hi,p,c.mu,'no trend');
  drawRef(ctx,25,lo,hi,p,c.rg,'trending');
  drawXAx(ctx,d.d,s,e,p,c);
  drawLine(ctx,d.adx,s,e,lo,hi,p,c.c1,2);
  drawCross(ctx,hov,n,p,c.cr);
}
function renderAll(){ drawSMA(); drawRSI(); drawBB(); drawADX(); }

// ── Tooltip ─────────────────────────────────────────────────────────────────
function fmtDate(s){ return new Date(s+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}) }
function f$(v){ return v!=null?'$'+v.toFixed(2):'--' }
function f1(v){ return v!=null?v.toFixed(1):'--' }

function showTT(clientX,clientY){
  const tt=document.getElementById('tt');
  if(hov<0){tt.style.display='none';return;}
  const d=DATA[ticker]; const {s}=slc(); const i=s+hov;
  const rsi=d.rsi[i], adx=d.adx[i];
  const rb=rsi!=null?(rsi<30?'<span class="bge buy">OVERSOLD</span>':rsi>70?'<span class="bge sell">OVERBOUGHT</span>':''):'';
  const al=adx!=null?(adx<20?' <span style="color:var(--mu)">no trend</span>':adx>=25?' <span style="color:var(--rg)">trending</span>'
    :' <span style="color:var(--mu)">developing</span>'):'';
  tt.innerHTML=`
    <div class="ttdate">${fmtDate(d.d[i])}</div><hr class="ttdiv">
    <div class="ttr"><span class="ttl">Close</span> <span class="ttv">${f$(d.c[i])}</span></div>
    <div class="ttr"><span class="ttl">SMA 20</span><span class="ttv">${f$(d.s20[i])}</span></div>
    <div class="ttr"><span class="ttl">SMA 50</span><span class="ttv">${f$(d.s50[i])}</span></div>
    <hr class="ttdiv">
    <div class="ttr"><span class="ttl">RSI</span>   <span class="ttv">${f1(rsi)}${rb}</span></div>
    <div class="ttr"><span class="ttl">BB low</span> <span class="ttv">${f$(d.bbl[i])}</span></div>
    <div class="ttr"><span class="ttl">BB high</span><span class="ttv">${f$(d.bbu[i])}</span></div>
    <hr class="ttdiv">
    <div class="ttr"><span class="ttl">ADX</span>   <span class="ttv">${f1(adx)}${al}</span></div>`;
  tt.style.display='block';
  const tw=tt.offsetWidth, th=tt.offsetHeight;
  let tx=clientX+14, ty=clientY-th/2;
  if(tx+tw>window.innerWidth-8) tx=clientX-tw-14;
  if(ty<8) ty=8;
  if(ty+th>window.innerHeight-8) ty=window.innerHeight-th-8;
  tt.style.left=tx+'px'; tt.style.top=ty+'px';
}

['c-sma','c-rsi','c-bb','c-adx'].forEach(id=>{
  const c=document.getElementById(id);
  c.addEventListener('mousemove',e=>{
    const {n}=slc(); const r=c.getBoundingClientRect(); const pl=plotOf(id);
    const mx=e.clientX-r.left;
    if(mx<pl.x||mx>pl.x+pl.w){if(hov!==-1){hov=-1;renderAll();showTT();}return;}
    const ni=Math.round((mx-pl.x)/pl.w*(n-1));
    if(ni!==hov){hov=ni;renderAll();}
    showTT(e.clientX,e.clientY);
  });
  c.addEventListener('mouseleave',()=>{hov=-1;renderAll();showTT();});
});

// ── Data table ───────────────────────────────────────────────────────────────
function renderTable(){
  const d=DATA[ticker]; const {s,e}=slc(); const rows=[];
  for(let i=e-1;i>=s;i--){
    rows.push(`<tr>
      <td>${d.d[i]}</td>
      <td>${f$(d.c[i])}</td><td>${f$(d.s20[i])}</td><td>${f$(d.s50[i])}</td>
      <td>${f1(d.rsi[i])}</td><td>${f$(d.bbl[i])}</td><td>${f$(d.bbu[i])}</td><td>${f1(d.adx[i])}</td>
    </tr>`);
  }
  document.getElementById('tbd').innerHTML=rows.join('');
}

const tbtrig=document.getElementById('tbtrig');
tbtrig.addEventListener('click',function(){
  const tbw=document.getElementById('tbw'), arr=document.getElementById('tbarr');
  const open=!tbw.hidden;
  tbw.hidden=open;
  this.setAttribute('aria-expanded',String(!open));
  arr.classList.toggle('open',!open);
  if(!open) renderTable();
});
tbtrig.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();tbtrig.click();}});

// ── Theme + resize ───────────────────────────────────────────────────────────
window.matchMedia('(prefers-color-scheme:dark)').addEventListener('change',renderAll);
new MutationObserver(renderAll).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
let rt; window.addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(renderAll,80);});

renderAll();
</script>
"""


# ── Data extraction ────────────────────────────────────────────────────────
def _nan_to_none(v):
    if v is None:
        return None
    try:
        if math.isnan(float(v)):
            return None
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _load_ticker(csv_path):
    df = pd.read_csv(str(csv_path))
    df = df.tail(CHART_ROWS).reset_index(drop=True)
    return dict(
        d=[str(x)[:10] for x in df["Datetime"]],
        c=[_nan_to_none(v) for v in df["Close"]],
        s20=[_nan_to_none(v) for v in df["SMA20"]],
        s50=[_nan_to_none(v) for v in df["SMA50"]],
        rsi=[_nan_to_none(v) for v in df["RSI14"]],
        bbl=[_nan_to_none(v) for v in df["BB_Lower"]],
        bbu=[_nan_to_none(v) for v in df["BB_Upper"]],
        adx=[_nan_to_none(v) for v in df["ADX14"]],
    )


# ── Public entry point ─────────────────────────────────────────────────────
def generate_dashboard(base_dir):
    """
    Read all Evaluation/Indicators/*.csv files and write a self-contained
    HTML dashboard to Evaluation/indicator_dashboard.html.
    """
    base_dir   = Path(base_dir)
    ind_dir    = base_dir / "Evaluation" / "Indicators"
    out_path   = base_dir / "Evaluation" / "indicator_dashboard.html"

    csv_files = sorted(ind_dir.glob("*_indicators.csv"))
    if not csv_files:
        logger.warning("No indicator CSVs found; skipping dashboard generation")
        return

    tickers = [f.name.replace("_indicators.csv", "") for f in csv_files]
    data    = {}
    for t, f in zip(tickers, csv_files):
        try:
            data[t] = _load_ticker(f)
        except Exception:
            logger.exception(f"Failed to load {f.name} for dashboard")

    if not data:
        return

    from datetime import datetime
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = (
        TMPL
        .replace("@@DATA@@",      json.dumps(data, separators=(",", ":")))
        .replace("@@TICKERS@@",   json.dumps(tickers))
        .replace("@@GENERATED@@", generated)
    )

    out_path.write_text(html, encoding="utf-8")
    logger.info(f"Dashboard written to {out_path} ({len(html)//1024} KB, {len(tickers)} tickers)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    base = Path(__file__).parent.parent
    generate_dashboard(base)
    print(f"Done. Open: {base / 'Evaluation' / 'indicator_dashboard.html'}")
