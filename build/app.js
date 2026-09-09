"use strict";
const DATA = JSON.parse(document.getElementById('payload').textContent);
const META = DATA.meta, SALES = DATA.sales, B = DATA.build;
const TAX = B.tax_factor || 1;
const MAIN_PRODUCT = B.main_product || 'Produto principal';
const MAIN_PREFIX = B.main_product_prefix || '';
/* status ATIVO/PAUSADO (mais recente) por campanha/conjunto/anúncio — só p/ o
   indicativo visual nas tabelas de otimização (Meta Ads), não afeta cálculos. */
const CAMP_ACTIVE = DATA.camp_active || {};
const ADSET_ACTIVE = DATA.adset_active || {};
const AD_ACTIVE = DATA.ad_active || {};

/* ---------------- format ---------------- */
const nf0=new Intl.NumberFormat('pt-BR',{maximumFractionDigits:0});
const nf1=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:1,maximumFractionDigits:1});
const nf2=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
const nf4=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:4});
/* Gasto (Meta Ads) e Faturamento deste funil vêm em USD na planilha. O toggle de
   moeda só troca a EXIBIÇÃO (símbolo + conversão pela cotação do dia); os valores
   crus usados nos cálculos (CAC, ROAS etc.) continuam em USD sempre. */
const brl=v=>{ if(v==null||!isFinite(v)) return '-';
  if(STATE.currency==='usd') return 'US$ '+nf2.format(v);
  return 'R$ '+nf2.format(v*(FX_RATE||FX_FALLBACK)); };
const pct=v=>(v==null||!isFinite(v))?'-':nf2.format(v*100)+'%';
const intf=v=>(v==null||!isFinite(v))?'-':nf0.format(v);
const numf=v=>(v==null||!isFinite(v))?'-':nf1.format(v);
const roasf=v=>(v==null||!isFinite(v))?'-':nf1.format(v)+'x';
const dimf=v=>v==null?'-':String(v);
/* remove acentos p/ casar com o norm() do build.py (unicodedata NFKD) */
const norm=s=>(s==null?'':String(s)).normalize('NFKD').replace(/[\u0300-\u036f]/g,'').trim().toLowerCase();
const isMainProd=p=>norm(p).startsWith(MAIN_PREFIX);
const brdate=d=>{ if(!d) return '-'; const p=d.split('-'); return p[2]+'/'+p[1]+'/'+p[0]; };
const WD=['Dom','Seg','Ter','Qua','Qui','Sex','Sáb'];
const weekday=d=>{ const dt=new Date(d+'T00:00:00'); return isNaN(dt)?'':WD[dt.getDay()]; };

/* ---------------- date helpers ---------------- */
function pad(n){return String(n).padStart(2,'0');}
function dstr(dt){return dt.getFullYear()+'-'+pad(dt.getMonth()+1)+'-'+pad(dt.getDate());}
function addDays(s,n){const dt=new Date(s+'T00:00:00');dt.setDate(dt.getDate()+n);return dstr(dt);}
const TODAY = B.today || B.date_max;

/* ---------------- STATE ---------------- */
const STATE = {
  page:'geral', from:B.date_min, to:B.date_max, preset:'todo', tax:true,
  currency: localStorage.getItem('dm_currency') || 'brl',
  selDays:new Set(),
  mSelC:new Set(), mSelA:new Set(), mSelAd:new Set(),
  sort:{}, colw: JSON.parse(localStorage.getItem('dm_colw')||'{}'),
};
const taxf = ()=> STATE.tax ? TAX : 1;

/* ---------------- cotação USD -> BRL (automática) ---------------- */
const FX_CACHE_KEY='dm_fx_usd_brl', FX_CACHE_MS=6*60*60*1000; /* 6h */
const FX_FALLBACK=5.30; /* só usado antes da 1ª cotação carregar (nunca visitou / sem cache / API fora do ar) */
let FX_RATE=null, FX_STALE=true;
(function loadFxCache(){
  try{ const c=JSON.parse(localStorage.getItem(FX_CACHE_KEY)||'null');
    if(c&&c.rate&&isFinite(c.rate)){ FX_RATE=c.rate; FX_STALE=(Date.now()-(c.ts||0))>FX_CACHE_MS; }
  }catch(e){}
})();
function curRateLabel(){
  const el=document.getElementById('curRate'); if(!el) return;
  el.textContent = FX_RATE ? ('1 USD = '+nf4.format(FX_RATE)+' BRL') : 'cotação indisponível';
}
function setFxRate(rate){ if(!rate||!isFinite(rate)) return;
  FX_RATE=rate; FX_STALE=false;
  try{ localStorage.setItem(FX_CACHE_KEY, JSON.stringify({rate,ts:Date.now()})); }catch(e){}
  curRateLabel();
  if(STATE.currency==='brl') renderAll();
}
async function fetchFxRate(){
  try{
    const r=await fetch('https://api.frankfurter.app/latest?from=USD&to=BRL');
    if(!r.ok) throw new Error('frankfurter '+r.status);
    const j=await r.json(); const v=j&&j.rates&&j.rates.BRL;
    if(!v) throw new Error('sem taxa (frankfurter)');
    setFxRate(v); return;
  }catch(e){ /* segue pro fallback */ }
  try{
    const r=await fetch('https://open.er-api.com/v6/latest/USD');
    if(!r.ok) throw new Error('er-api '+r.status);
    const j=await r.json(); const v=j&&j.rates&&j.rates.BRL;
    if(v) setFxRate(v);
  }catch(e){ /* mantém cache (se houver) ou o fallback fixo */ }
}
fetchFxRate();

/* active date test: selDays override the De/Até range */
function dateActive(d){
  if(!d) return false;
  if(STATE.selDays.size) return STATE.selDays.has(d);
  return (!STATE.from || d>=STATE.from) && (!STATE.to || d<=STATE.to);
}
const metaActive  = ()=> META.filter(m=>dateActive(m.d));
const salesActive = ()=> SALES.filter(s=>dateActive(s.d));

/* ---------------- aggregation ----------------
   bucket = {sp,im,cl,pv,ck, vendas, vendasM, fat}
   vendas  = compras do produto principal (base de exibição da página)
   vendasM = compras do produto principal atribuídas ao Meta Ads (base das conversões)
   fat     = faturamento (todos os produtos do escopo)
   Obs.: na aba Meta o conjunto de vendas já é filtrado a meta==1, então vendas==vendasM. */
function newBucket(){return {sp:0,im:0,cl:0,pv:0,ck:0,vendas:0,vendasM:0,fat:0};}
function addSales(a,r){ a.vendas+=r.main; a.vendasM+=(r.main&&r.meta)?1:0; a.fat+=r.val; }
function derive(a){
  const g=a.sp*taxf();
  return {gasto:g, impr:a.im, cliques:a.cl, pv:a.pv, ck:a.ck, vendas:a.vendas, fat:a.fat,
    cpm:a.im?g/a.im*1000:null, ctr:a.im?a.cl/a.im:null, cpc:a.cl?g/a.cl:null,
    cpv:a.pv?g/a.pv:null, cr:a.cl?a.pv/a.cl:null,               /* CR = Page Views / Cliques */
    cpic:a.ck?g/a.ck:null, vischk:a.pv?a.ck/a.pv:null,
    convlp:a.pv?a.vendasM/a.pv:null,                            /* Vendas(Meta) / Page Views */
    convchk:a.ck?a.vendasM/a.ck:null,                           /* Vendas(Meta) / Checkouts */
    cac:a.vendas?g/a.vendas:null, roas:g?a.fat/g:null, ticket:a.vendas?a.fat/a.vendas:null};
}
function buildAgg(fS,fM,dim){
  const m={}; const get=k=>m[k]||(m[k]=newBucket());
  fM.forEach(r=>{const a=get(r[dim]); a.sp+=r.sp; a.im+=r.im; a.cl+=r.cl; a.pv+=r.pv; a.ck+=r.ck;});
  fS.forEach(r=>{const a=get(r[dim]); addSales(a,r);});
  return m;
}
function totals(fS,fM){
  const a=newBucket();
  fM.forEach(r=>{a.sp+=r.sp;a.im+=r.im;a.cl+=r.cl;a.pv+=r.pv;a.ck+=r.ck;});
  fS.forEach(r=>addSales(a,r));
  return a;
}
function daily(fS,fM){
  const days={}; const g=d=>days[d]||(days[d]=Object.assign({d},newBucket()));
  fM.forEach(r=>{if(!r.d)return; const a=g(r.d); a.sp+=r.sp; a.im+=r.im; a.cl+=r.cl; a.pv+=r.pv; a.ck+=r.ck;});
  fS.forEach(r=>{if(!r.d)return; addSales(g(r.d),r);});
  return Object.values(days).sort((a,b)=>a.d<b.d?-1:1);
}

/* ---------------- generic interactive table ---------------- */
function colWidth(cfg,c){ const saved=(STATE.colw[cfg.id]||{})[c.key];
  if(saved) return saved;
  if(c.w) return c.w;
  if(c.type==='date') return 96;
  if(c.type==='dim') return c.big?300:150;
  return 88; }
function renderTable(cfg){
  const table=document.getElementById(cfg.id); if(!table) return;
  const sortState=STATE.sort[cfg.id];
  let rows=cfg.rows.slice();
  if(sortState){ const {key,dir}=sortState; const c=cfg.cols.find(x=>x.key===key);
    rows.sort((a,b)=>{ let va=a.cells[key], vb=b.cells[key];
      if(c && c.type==='dim'){ va=norm(va); vb=norm(vb); return dir==='asc'?(va<vb?-1:va>vb?1:0):(va>vb?-1:va<vb?1:0); }
      va=(va==null||!isFinite(va))?-Infinity:va; vb=(vb==null||!isFinite(vb))?-Infinity:vb;
      return dir==='asc'?va-vb:vb-va; }); }
  const ext={};
  cfg.cols.forEach(c=>{ if(c.heat){ const vs=rows.map(r=>r.cells[c.key]).filter(v=>v!=null&&isFinite(v)); ext[c.key]=[Math.min(...vs),Math.max(...vs)]; }});
  const fmt=(t,v)=> t==='brl'?brl(v):t==='pct'?pct(v):t==='int'?intf(v):t==='num'?numf(v):t==='roas'?roasf(v):t==='date'?brdate(v):dimf(v);
  const widths=cfg.cols.map(c=>colWidth(cfg,c)); const totalW=widths.reduce((a,b)=>a+b,0);
  const colgroup='<colgroup>'+cfg.cols.map((c,i)=>`<col style="width:${widths[i]}px">`).join('')+'</colgroup>';
  let thead='<thead><tr>'+cfg.cols.map((c,i)=>{
    const sc = sortState&&sortState.key===c.key ? (sortState.dir==='asc'?'sorted-asc':'sorted-desc') : '';
    return `<th class="${c.type==='dim'?'dim ':''}${sc}" data-k="${c.key}" data-ci="${i}">${c.label}<span class="rsz"></span></th>`;
  }).join('')+'</tr></thead>';
  let tbody='<tbody>'+rows.map(r=>{
    const sel = cfg.selectable && cfg.selSet && cfg.selSet.has(r.k);
    const tds=cfg.cols.map((c,ci)=>{
      const v=r.cells[c.key]; let bg='';
      if(c.heat && ext[c.key]) bg=`background:${heat(v,ext[c.key][0],ext[c.key][1],c.heat)}`;
      const cls=(c.type==='dim'?'dim':'');
      const dot = (ci===0 && cfg.statusMap) ? statusDot(cfg.statusMap[r.k]) : '';
      return `<td class="${cls}" style="${bg}">${dot}${fmt(c.type,v)}</td>`;
    }).join('');
    return `<tr class="${sel?'sel':''}" data-k="${encodeURIComponent(r.k)}">${tds}</tr>`;
  }).join('')+'</tbody>';
  let tfoot='';
  if(cfg.total){ tfoot='<tfoot><tr>'+cfg.cols.map((c,i)=>{
    const v=cfg.total[c.key]; return `<td class="${c.type==='dim'?'dim':''}">${i===0?(v==null?'Total Geral':fmt(c.type,v)):fmt(c.type,v)}</td>`;
  }).join('')+'</tr></tfoot>'; }
  table.style.width=totalW+'px';
  table.innerHTML=colgroup+thead+tbody+tfoot;
  const cols=table.querySelector('colgroup').children;
  table.querySelectorAll('thead th').forEach(th=>{
    th.addEventListener('click',e=>{ if(e.target.classList.contains('rsz'))return;
      const k=th.dataset.k, cur=STATE.sort[cfg.id];
      if(!cur||cur.key!==k) STATE.sort[cfg.id]={key:k,dir:'asc'};
      else if(cur.dir==='asc') STATE.sort[cfg.id]={key:k,dir:'desc'};
      else delete STATE.sort[cfg.id];
      renderTable(cfg);
    });
  });
  table.querySelectorAll('thead th .rsz').forEach(g=>{
    g.addEventListener('mousedown',e=>{ e.preventDefault(); e.stopPropagation();
      const th=g.parentElement, k=th.dataset.k, ci=+th.dataset.ci, x0=e.clientX;
      const w0=cols[ci].offsetWidth, tw0=table.offsetWidth;
      document.body.style.userSelect='none';
      const mv=ev=>{ const nw=Math.max(60,w0+(ev.clientX-x0)); cols[ci].style.width=nw+'px'; table.style.width=(tw0-w0+nw)+'px';
        STATE.colw[cfg.id]=STATE.colw[cfg.id]||{}; STATE.colw[cfg.id][k]=nw; };
      const up=()=>{ document.removeEventListener('mousemove',mv); document.removeEventListener('mouseup',up); document.body.style.userSelect=''; localStorage.setItem('dm_colw',JSON.stringify(STATE.colw)); };
      document.addEventListener('mousemove',mv); document.addEventListener('mouseup',up);
    });
  });
  if(cfg.selectable && cfg.onSelect){
    table.querySelectorAll('tbody tr').forEach(tr=>{
      tr.addEventListener('click',e=>{ cfg.onSelect(decodeURIComponent(tr.dataset.k), e); });
    });
  }
}
/* status ATIVO/PAUSADO ao lado do nome (campanha/conjunto/anúncio) — só o
   indicativo visual; não altera dado, ordenação ou filtro nenhum. */
function statusDot(active){
  if(active==null) return '';
  return active ? '<span class="status-dot on" title="Ativo"></span>' : '<span class="status-dot off" title="Pausado"></span>';
}
/* Heatmap por coluna: cor FIXA por métrica (definida em identidade-visual.css),
   só a OPACIDADE varia com o valor (maior valor = mais vibrante). */
const HEAT_HUE={gasto:'--heat-gasto', fat:'--heat-fat', roas:'--heat-roas', vendas:'--heat-vendas'};
function heat(v,lo,hi,kind){
  if(v==null||!isFinite(v)||hi===lo||!HEAT_HUE[kind]) return 'transparent';
  const t=Math.max(0,Math.min(1,(v-lo)/(hi-lo)));
  const c=hx2rgb(cvar(HEAT_HUE[kind]));
  return `rgba(${c[0]},${c[1]},${c[2]},${(0.06+0.5*t).toFixed(3)})`;
}
function toggleSet(set,key,ctrl){
  if(ctrl){ set.has(key)?set.delete(key):set.add(key); }
  else { const only=set.has(key)&&set.size===1; set.clear(); if(!only) set.add(key); }
}

/* ---------------- charts ---------------- */
const charts={};
const CHART_SERIES=['--cc1','--cc2','--cc3','--cc4','--cc5','--cc6','--cc7','--cc8','--cc9','--cc10'];
const cvar=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const chartPalette=()=>CHART_SERIES.map(v=>cvar(v)||'#888888');
const hx2rgb=h=>{h=(h||'').replace('#','').trim();if(h.length===3)h=h.split('').map(c=>c+c).join('');const n=parseInt(h||'888888',16);return [(n>>16)&255,(n>>8)&255,n&255];};
const cmuted=()=>cvar('--muted')||'#6B7280', cink=()=>cvar('--ink')||'#1A1D2E', cgrid=()=>cvar('--grid')||'#EEF0F5';
function destroy(id){ if(charts[id]){ charts[id].destroy(); delete charts[id]; } }
const FMT={brl:brl,pct:pct,num:numf,int:intf,roas:roasf};

/* combo: Vendas (barras) · Gasto/Faturamento (R$) · ROAS (eixo próprio) */
function comboChart(id, d){
  destroy(id); const el=document.getElementById(id); if(!el) return;
  const labels=d.map(x=>x.d.slice(5)), mut=cmuted(), gr=cgrid();
  charts[id]=new Chart(el,{
    data:{labels, datasets:[
      {type:'bar',label:'Vendas',data:d.map(x=>x.vendas),backgroundColor:cvar('--chart-vendas'),yAxisID:'y',borderRadius:3,order:3},
      {type:'line',label:'Gasto',data:d.map(x=>+(x.sp*taxf()).toFixed(2)),borderColor:cvar('--chart-gasto'),backgroundColor:cvar('--chart-gasto'),yAxisID:'y1',borderWidth:2,pointRadius:2,tension:.25,order:2},
      {type:'line',label:'Faturamento',data:d.map(x=>+x.fat.toFixed(2)),borderColor:cvar('--chart-faturamento'),backgroundColor:cvar('--chart-faturamento'),yAxisID:'y1',borderWidth:2,pointRadius:2,tension:.25,order:2},
      {type:'line',label:'ROAS',data:d.map(x=>{const g=x.sp*taxf();return g?+(x.fat/g).toFixed(2):null;}),borderColor:cink(),backgroundColor:cink(),yAxisID:'y2',borderWidth:2,pointRadius:2,spanGaps:true,tension:.25,order:0},
    ]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{labels:{color:cink(),boxWidth:10,usePointStyle:true,font:{size:11}}},
        tooltip:{callbacks:{label:c=>{const v=c.raw,ax=c.dataset.yAxisID; return c.dataset.label+': '+(ax==='y1'?brl(v):ax==='y2'?roasf(v):intf(v));}}}},
      scales:{x:{ticks:{color:mut,font:{size:10}},grid:{display:false}},
        y:{position:'left',ticks:{color:mut,font:{size:10}},grid:{color:gr},beginAtZero:true,title:{display:true,text:'Vendas',color:mut,font:{size:10}}},
        y1:{position:'right',ticks:{color:mut,font:{size:10}},grid:{display:false},beginAtZero:true,title:{display:true,text:'R$',color:mut,font:{size:10}}},
        y2:{position:'right',ticks:{color:mut,font:{size:10},callback:v=>numf(v)+'x'},grid:{display:false},beginAtZero:true,title:{display:true,text:'ROAS',color:mut,font:{size:10}}}}}
  });
}
/* linhas genéricas (1 ou 2 eixos) */
function multiLine(id, d, series, opts){
  destroy(id); const el=document.getElementById(id); if(!el) return;
  const labels=d.map(x=>x.d.slice(5)), mut=cmuted();
  const useR=series.some(s=>s.axis==='R');
  const datasets=series.map(s=>({label:s.label,data:d.map(s.fn),borderColor:s.color,backgroundColor:s.color,
    yAxisID:s.axis==='R'?'y1':'y',borderWidth:2,pointRadius:2,spanGaps:true,tension:.25,_fmt:FMT[s.fmt]||numf}));
  const scales={x:{ticks:{color:mut,font:{size:9}},grid:{display:false}},
    y:{position:'left',ticks:{color:mut,font:{size:9},callback:v=>(FMT[opts.L.fmt]||numf)(v)},grid:{color:cgrid()},grace:'10%'}};
  if(useR) scales.y1={position:'right',grid:{display:false},ticks:{color:mut,font:{size:9},callback:v=>(FMT[opts.R.fmt]||numf)(v)},grace:'10%'};
  charts[id]=new Chart(el,{type:'line',data:{labels,datasets},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{labels:{color:cink(),boxWidth:10,usePointStyle:true,font:{size:10}}},
        tooltip:{callbacks:{label:c=>c.dataset.label+': '+(c.dataset._fmt||numf)(c.raw)}}},
      scales}});
}
/* barras horizontais (faturamento por anúncio) */
const barLabels={id:'barLabels',afterDatasetsDraw(ch){const{ctx}=ch;ctx.save();ctx.font='600 11px Segoe UI,system-ui';ctx.fillStyle=cmuted();ctx.textBaseline='middle';
  const ds=ch.data.datasets[0], f=ds._fmt||intf;
  ch.getDatasetMeta(0).data.forEach((el,i)=>{const v=ds.data[i]; if(!v)return; ctx.fillText(f(v),el.x+5,el.y);});ctx.restore();}};
function hbar(id, items, valFn, color, top, fmtFn){
  destroy(id); const el=document.getElementById(id); if(!el) return;
  let arr=items.slice().sort((a,b)=>valFn(b)-valFn(a)); if(top) arr=arr.slice(0,top);
  const mut=cmuted(), f=fmtFn||intf;
  charts[id]=new Chart(el,{type:'bar', plugins:[barLabels],
    data:{labels:arr.map(x=>x.label), datasets:[{label:'v',data:arr.map(valFn),backgroundColor:color||'#1BAF7A',borderRadius:3,_fmt:f}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,layout:{padding:{right:44}},
      plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>f(c.raw)}}},
      scales:{x:{beginAtZero:true,ticks:{color:mut,font:{size:9}},grid:{color:cgrid()}},
              y:{ticks:{color:mut,font:{size:9}},grid:{display:false}}}}});
}
/* CAC por dia, por item de uma dimensão (campanha/conjunto/anúncio) - 1 linha por item.
   `dim` = 'camp' | 'adset' | 'ad'; usa os mesmos dados escopados da tabela acima. */
function cacDimChart(id, fM, fS, dim, selSet){
  destroy(id); const el=document.getElementById(id); if(!el) return;
  const spendTot={}; fM.forEach(r=>spendTot[r[dim]]=(spendTot[r[dim]]||0)+r.sp);
  const items=(selSet&&selSet.size)
    ? Object.keys(spendTot).filter(k=>selSet.has(k)).sort((a,b)=>spendTot[b]-spendTot[a])
    : Object.keys(spendTot).sort((a,b)=>spendTot[b]-spendTot[a]).slice(0,6);
  const dset=new Set(); fM.forEach(r=>r.d&&dset.add(r.d)); fS.forEach(r=>r.d&&dset.add(r.d));
  const days=[...dset].sort();
  const K=(c,dd)=>c+'\u0001'+dd, sp={}, vd={};
  fM.forEach(r=>{if(!r.d)return; sp[K(r[dim],r.d)]=(sp[K(r[dim],r.d)]||0)+r.sp;});
  fS.forEach(r=>{if(!r.d)return; vd[K(r[dim],r.d)]=(vd[K(r[dim],r.d)]||0)+r.main;});
  const PAL=chartPalette();
  const ds=items.map((c,i)=>({label:c.length>22?c.slice(0,22)+'…':c, _full:c,
    data:days.map(dd=>{const s=(sp[K(c,dd)]||0)*taxf(), v=vd[K(c,dd)]||0; return v?+(s/v).toFixed(2):null;}),
    borderColor:PAL[i%PAL.length],backgroundColor:PAL[i%PAL.length],borderWidth:2,pointRadius:1.5,spanGaps:true,tension:.25}));
  const mut=cmuted();
  charts[id]=new Chart(el,{type:'line',data:{labels:days.map(x=>x.slice(5)),datasets:ds},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{labels:{color:cink(),boxWidth:8,font:{size:9}}},
        tooltip:{callbacks:{label:c=>(c.dataset._full||c.dataset.label)+': '+brl(c.raw)}}},
      scales:{x:{ticks:{color:mut,font:{size:9},maxRotation:0,autoSkip:true,autoSkipPadding:8},grid:{display:false}},y:{ticks:{color:mut,font:{size:9},callback:v=>brl(v)},grid:{color:cgrid()},beginAtZero:true}}}});
}

/* ---------------- KPI cards ---------------- */
function kpiCard(k){ return `<div class="kpi ${k.hero?'hero':''}"><div class="kl"><span>${k.label}</span>${k.pill?`<span class="pill q">${k.pill}</span>`:''}</div><div class="kv">${k.val}</div><div class="ka">${k.aux||''}</div></div>`; }

/* ---------------- colunas das tabelas ---------------- */
const METRIC_COLS=[
  {key:'gasto',label:'Gasto',type:'brl',heat:'gasto'},   /* heatmap vermelho */
  {key:'cpm',label:'CPM',type:'brl'},
  {key:'ctr',label:'CTR',type:'pct'},
  {key:'cr',label:'CR',type:'pct'},
  {key:'vischk',label:'VisCHK',type:'pct'},
  {key:'convchk',label:'ConvCHK',type:'pct'},
  {key:'vendas',label:'Vendas',type:'int',heat:'vendas'}, /* heatmap azul */
  {key:'cac',label:'CAC',type:'brl'},
  {key:'fat',label:'Faturamento',type:'brl',heat:'fat'},  /* heatmap verde */
  {key:'ticket',label:'Ticket',type:'brl'},
  {key:'roas',label:'ROAS',type:'roas',heat:'roas'},      /* heatmap amarelo */
];
const DAILY_COLS=[{key:'date',label:'Data',type:'date'},{key:'wd',label:'Dia',type:'dim',w:64}].concat(METRIC_COLS);
const HCOLS=[{key:'dim',label:'',type:'dim',big:true}].concat(METRIC_COLS);
function metricCells(x,d){
  return {gasto:d.gasto, cpm:d.cpm, ctr:d.ctr, cr:d.cr, vischk:d.vischk, convchk:d.convchk,
    vendas:x.vendas, cac:d.cac, fat:x.fat, ticket:d.ticket, roas:d.roas};
}
function dailyCells(x,d,isTotal){
  return Object.assign({date:isTotal?null:x.d, wd:isTotal?'':weekday(x.d)}, metricCells(x,d));
}

/* ---------------- tabela Vendas por produto ---------------- */
function renderProdTable(id, salesSet){
  const mainCount=salesSet.reduce((s,r)=>s+r.main,0);
  const byProd={}; salesSet.forEach(r=>{ if(isMainProd(r.prod)) return; byProd[r.prod]=(byProd[r.prod]||0)+1; });
  const rows=[{k:'__main__', cells:{prod:MAIN_PRODUCT, vendas:mainCount, pctm:1}}];
  Object.entries(byProd).sort((a,b)=>b[1]-a[1]).forEach(([prod,c])=>{
    rows.push({k:prod, cells:{prod:prod, vendas:c, pctm:mainCount?c/mainCount:null}});
  });
  renderTable({id, cols:[{key:'prod',label:'Produto',type:'dim',big:true},{key:'vendas',label:'Vendas',type:'int',w:80},{key:'pctm',label:'% vs principal',type:'pct',w:120}], rows});
}

/* ---------------- funil + gráficos de conversão (comuns às 2 abas) ---------------- */
/* ---- comparativo período atual vs período anterior de MESMO tamanho ---- */
function prevWindow(){
  if(!STATE.from||!STATE.to) return null;
  const span=Math.round((new Date(STATE.to+'T00:00:00')-new Date(STATE.from+'T00:00:00'))/86400000)+1;
  if(!(span>=1)) return null;
  return {from:addDays(STATE.from,-span), to:addDays(STATE.from,-1), span};
}
const inRange=(d,a,b)=>d&&d>=a&&d<=b;
/* métricas em que MENOR é melhor (custo); nas demais, maior é melhor */
const GOOD_LOW={gasto:1,cpm:1,cpc:1,cpv:1,cpic:1,cac:1};
function deltaBadge(cur,prev,key){
  if(cur==null||prev==null||!isFinite(cur)||!isFinite(prev)||prev===0) return '';
  const p=((cur-prev)/Math.abs(prev))*100; if(!isFinite(p)) return '';
  const flat=Math.abs(p)<0.05, up=cur>prev;
  const good=flat?null:(GOOD_LOW[key]?!up:up);
  const cls=flat?'flat':(good?'good':'bad'), arrow=flat?'→':(up?'▲':'▼');
  return `<span class="delta ${cls}">${arrow} ${nf1.format(Math.abs(p))}%</span>`;
}
function renderFunnel(id, steps){
  document.getElementById(id).innerHTML=steps.map(s=>{
    const color=s[4]?`var(${s[4]})`:'var(--accent-blue)';
    const hi=(s[3]==='gasto'||s[3]==='fat');   // valores em destaque + contorno inteiro
    const border=hi?`border-color:${color}`:`border-left-color:${color}`;
    const secs=s[2].map(x=>`<div><span class="s-label">${x[0]}</span><span class="s-val${x[2]?' s-pill '+x[2]:''}">${x[1]}</span></div>`).join('');
    return `<div class="step" style="${border}">
      <div class="step-main"><div class="m-label">${s[0]}</div>
        <div class="m-val"${hi?` style="color:${color}"`:''}>${s[1]}</div>
        ${s[5]?`<div class="m-delta">${s[5]}</div>`:''}</div>
      <div class="secs">${secs}</div></div>`;
  }).join('');
}
function funnelSteps(t, tp){
  const d=derive(t), P=(k)=>tp?tp[k]:null, Pd=tp?derive(tp):null;
  return [
    ['Gasto Total', brl(d.gasto), [], 'gasto', '--heat-gasto', deltaBadge(d.gasto, Pd?Pd.gasto:null, 'gasto')],
    ['Impressões', intf(t.im), [['CPM',brl(d.cpm)]], 'impr', '--c6', deltaBadge(t.im, P('im'), 'im')],
    ['Cliques', intf(t.cl), [['CPC',brl(d.cpc)],['CTR',pct(d.ctr)]], 'cl', '--c1', deltaBadge(t.cl, P('cl'), 'cl')],
    ['Page Views', intf(t.pv), [['CPV',brl(d.cpv)],['CR',pct(d.cr)]], 'pv', '--c4', deltaBadge(t.pv, P('pv'), 'pv')],
    ['Checkouts', intf(t.ck), [['CPIC',brl(d.cpic)],['VisCHK',pct(d.vischk)]], 'ck', '--c3', deltaBadge(t.ck, P('ck'), 'ck')],
    ['Vendas', intf(t.vendas), [['CAC',brl(d.cac),'cac'],['ConvCHK',pct(d.convchk)]], 'vendas', '--c7', deltaBadge(t.vendas, P('vendas'), 'vendas')],
    ['Faturamento', brl(t.fat), [['ROAS',roasf(d.roas),'roas'],['Ticket Médio',brl(d.ticket)]], 'fat', '--heat-fat', deltaBadge(t.fat, P('fat'), 'fat')],
  ];
}
function convCharts(id1,id2,id3,dd){
  multiLine(id1, dd, [{label:'CPM',fn:x=>x.im?+((x.sp*taxf())/x.im*1000).toFixed(2):null,color:cvar('--chart-cpm'),fmt:'brl',axis:'L'},
     {label:'CTR',fn:x=>x.im?+(x.cl/x.im).toFixed(4):null,color:cvar('--chart-ctr'),fmt:'pct',axis:'R'}], {L:{fmt:'brl'},R:{fmt:'pct'}});
  multiLine(id2, dd, [{label:'CR',fn:x=>x.cl?+(x.pv/x.cl).toFixed(4):null,color:cvar('--chart-cr'),fmt:'pct',axis:'L'},
     {label:'VisCHK',fn:x=>x.pv?+(x.ck/x.pv).toFixed(4):null,color:cvar('--chart-vischk'),fmt:'pct',axis:'L'}], {L:{fmt:'pct'}});
  multiLine(id3, dd, [{label:'ConvLP',fn:x=>x.pv?+(x.vendasM/x.pv).toFixed(4):null,color:cvar('--chart-convlp'),fmt:'pct',axis:'L'},
     {label:'ConvCHK',fn:x=>x.ck?+(x.vendasM/x.ck).toFixed(4):null,color:cvar('--chart-vischk'),fmt:'pct',axis:'L'}], {L:{fmt:'pct'}});
}

/* ---------------- PAGE 1: Visão Geral ---------------- */
function renderGeral(){
  const fM=metaActive(), fS=salesActive();          // fS = todas as vendas do funil
  const t=totals(fS,fM), d=derive(t);
  const pw=prevWindow();
  const tp = pw ? totals(SALES.filter(s=>inRange(s.d,pw.from,pw.to)), META.filter(m=>inRange(m.d,pw.from,pw.to))) : null;
  renderFunnel('geralFunnel', funnelSteps(t, tp));
  const dd=daily(fS,fM);
  convCharts('gCpmCtr','gCrVis','gConv', dd);
  comboChart('gCombo', dd);
  renderProdTable('gProd', fS);

  const dl=dd.slice().reverse();
  renderTable({id:'gDaily', cols:DAILY_COLS,
    rows:dl.map(x=>{const dv=derive(x); return {k:x.d, cells:dailyCells(x,dv)};}),
    total:dailyCells(t,d,true),
    selectable:true, selSet:STATE.selDays,
    onSelect:(k,e)=>{ toggleSet(STATE.selDays,k,e&&(e.ctrlKey||e.metaKey)); syncDateInputs(); renderAll(); },
  });
}

/* ---------------- PAGE 2: Meta Ads ---------------- */
function metaScope(ex){ let fM=metaActive(), fS=salesActive().filter(s=>s.meta);   // só Meta Ads
  if(ex!=='C'&&STATE.mSelC.size){ fM=fM.filter(r=>STATE.mSelC.has(r.camp)); fS=fS.filter(r=>STATE.mSelC.has(r.camp)); }
  if(ex!=='A'&&STATE.mSelA.size){ fM=fM.filter(r=>STATE.mSelA.has(r.adset)); fS=fS.filter(r=>STATE.mSelA.has(r.adset)); }
  if(ex!=='D'&&STATE.mSelAd.size){ fM=fM.filter(r=>STATE.mSelAd.has(r.ad)); fS=fS.filter(r=>STATE.mSelAd.has(r.ad)); }
  return {fM,fS}; }
/* Cada dimensão (campanha/conjunto/anúncio) tem seu próprio conjunto de seleção,
   combinados em AND por metaScope. Um clique aqui só mexe no conjunto da própria
   dimensão — nunca limpa a seleção das outras tabelas (ver botões ✕ Filtro,
   que limpam uma dimensão de cada vez, e o "Remover Filtros" geral, que limpa tudo). */
function selDim(dim,key,ctrl){
  const s={C:STATE.mSelC,A:STATE.mSelA,D:STATE.mSelAd}[dim];
  if(ctrl){ s.has(key)?s.delete(key):s.add(key); }
  else { const sole=s.has(key)&&s.size===1; s.clear(); if(!sole) s.add(key); }
  renderMeta();
}
function metaPrevTotals(pw){
  let fM=META.filter(m=>inRange(m.d,pw.from,pw.to));
  let fS=SALES.filter(s=>s.meta && inRange(s.d,pw.from,pw.to));
  if(STATE.mSelC.size){fM=fM.filter(r=>STATE.mSelC.has(r.camp));fS=fS.filter(r=>STATE.mSelC.has(r.camp));}
  if(STATE.mSelA.size){fM=fM.filter(r=>STATE.mSelA.has(r.adset));fS=fS.filter(r=>STATE.mSelA.has(r.adset));}
  if(STATE.mSelAd.size){fM=fM.filter(r=>STATE.mSelAd.has(r.ad));fS=fS.filter(r=>STATE.mSelAd.has(r.ad));}
  return totals(fS,fM);
}
function renderMeta(){
  const F=metaScope(null), fM=F.fM, fS=F.fS;
  const t=totals(fS,fM), d=derive(t);
  const pw=prevWindow(); const tp = pw ? metaPrevTotals(pw) : null;
  renderFunnel('metaFunnel', funnelSteps(t, tp));

  const dd=daily(fS,fM);
  convCharts('mCpmCtr','mCrVis','mConv', dd);
  comboChart('mCombo', dd);
  const aggAd=buildAgg(fS,fM,'ad');
  hbar('mContent', Object.entries(aggAd).map(([label,a])=>({label,v:a.fat})), x=>x.v, cvar('--chart-faturamento'), 10, brl);
  renderProdTable('mProd', fS);

  const dl=dd.slice().reverse();
  renderTable({id:'tDaily', cols:DAILY_COLS,
    rows:dl.map(x=>{const dv=derive(x); return {k:x.d, cells:dailyCells(x,dv)};}),
    total:dailyCells(t,d,true),
    selectable:true, selSet:STATE.selDays,
    onSelect:(k,e)=>{ toggleSet(STATE.selDays,k,e&&(e.ctrlKey||e.metaKey)); syncDateInputs(); renderAll(); },
  });

  function hierRows(map){ return Object.entries(map).map(([k,a])=>{const dv=derive(a);
    return {k, cells:Object.assign({dim:k}, metricCells(a,dv))};}); }
  function totRowOf(tt){const dv=derive(tt);return Object.assign({dim:null}, metricCells(tt,dv));}
  const Sc=metaScope('C'), Sa=metaScope('A'), Sd=metaScope('D');
  renderTable({id:'tCamp', cols:HCOLS.map((c,i)=>i===0?{...c,label:'Campanha'}:c), rows:hierRows(buildAgg(Sc.fS,Sc.fM,'camp')), total:totRowOf(totals(Sc.fS,Sc.fM)),
    statusMap:CAMP_ACTIVE, selectable:true, selSet:STATE.mSelC, onSelect:(k,e)=>selDim('C',k,e&&(e.ctrlKey||e.metaKey))});
  renderTable({id:'tAdset', cols:HCOLS.map((c,i)=>i===0?{...c,label:'Conjunto',big:true}:c), rows:hierRows(buildAgg(Sa.fS,Sa.fM,'adset')), total:totRowOf(totals(Sa.fS,Sa.fM)),
    statusMap:ADSET_ACTIVE, selectable:true, selSet:STATE.mSelA, onSelect:(k,e)=>selDim('A',k,e&&(e.ctrlKey||e.metaKey))});
  renderTable({id:'tAd', cols:HCOLS.map((c,i)=>i===0?{...c,label:'Anúncio'}:c), rows:hierRows(buildAgg(Sd.fS,Sd.fM,'ad')), total:totRowOf(totals(Sd.fS,Sd.fM)),
    statusMap:AD_ACTIVE, selectable:true, selSet:STATE.mSelAd, onSelect:(k,e)=>selDim('D',k,e&&(e.ctrlKey||e.metaKey))});

  /* cada gráfico segue a dimensão da tabela acima (mesmos dados escopados);
     quando a própria dimensão tem seleção (clique na tabela), o gráfico mostra
     só as linhas selecionadas — senão cai no top-6 por gasto dentro do escopo herdado. */
  cacDimChart('chCamp', Sc.fM, Sc.fS, 'camp', STATE.mSelC);
  cacDimChart('chAdset', Sa.fM, Sa.fS, 'adset', STATE.mSelA);
  cacDimChart('chAd', Sd.fM, Sd.fS, 'ad', STATE.mSelAd);

  const vendas=fS.reduce((s,r)=>s+r.main,0);
  document.getElementById('qCount').textContent=vendas+' vendas · '+fS.length+' linhas';
  const rows=fS.slice().sort((a,b)=>(a.d<b.d?1:-1));
  renderTable({id:'tQual',
    cols:[{key:'d',label:'Data',type:'date'},{key:'nm',label:'Nome',type:'dim'},{key:'prod',label:'Produto',type:'dim',big:true},
      {key:'val',label:'Valor',type:'brl',w:110},{key:'camp',label:'Campanha',type:'dim',big:true},{key:'ad',label:'Anúncio',type:'dim',big:true},{key:'em',label:'E‑mail',type:'dim',w:200}],
    rows:rows.map((s,i)=>({k:'s'+i, cells:{d:s.d,nm:s.nm,prod:s.prod,val:s.val,camp:s.camp,ad:s.ad,em:s.em}}))});
}

/* ---------------- PAGE: Relatórios ----------------
   Reaproveita os mesmos dados/filtros das outras abas (metaActive/salesActive).
   Total  = todas as vendas do funil.  Tráfego = só Meta Ads (s.meta).
   Código de cor aplicado APENAS a CAC e ROAS (metas em build.py). */
const CAC_TARGET=B.cac_target, ROAS_TARGET=B.roas_target;
const REL_BAND_LO=(B.report_band_low!=null?B.report_band_low:0.7);
const REL_BAND_HI=(B.report_band_high!=null?B.report_band_high:1.3);
const AD_LINKS=DATA.ad_links||{};

/* ---- saúde do funil: histórico da conta (todo o período, sem filtro) ---- */
const HIST=derive(totals(SALES,META));
const HEALTH_GOAL_KEY='dm_cpic_goal';
STATE.cpicGoal=(()=>{ const v=parseFloat(localStorage.getItem(HEALTH_GOAL_KEY)); return (isFinite(v)&&v>0)?v:(HIST.cpic||null); })();
/* proporção histórica: quanto do CPIC vem de CPC/CPV — usada p/ escalar os tetos junto com a meta */
const HEALTH_RATIO_CPC=(HIST.cpic&&HIST.cpc)?HIST.cpc/HIST.cpic:null;
const HEALTH_RATIO_CPV=(HIST.cpic&&HIST.cpv)?HIST.cpv/HIST.cpic:null;
const HEALTH_VISCHK_MIN=HIST.vischk!=null?HIST.vischk*0.85:null; /* piso = 85% do VisCHK histórico da conta */
/* meta é digitada/exibida na moeda selecionada (USD/BRL), mas armazenada e usada
   nos cálculos sempre em USD — mesma convenção do resto do dashboard (ver brl()) */
const healthCurSym=()=>STATE.currency==='usd'?'US$':'R$';
const healthToDisplay=usd=>usd*(STATE.currency==='usd'?1:(FX_RATE||FX_FALLBACK));
const healthFromDisplay=v=>v/(STATE.currency==='usd'?1:(FX_RATE||FX_FALLBACK));
function healthPerf(actual,target,higherIsBetter){
  if(actual==null||!isFinite(actual)||!target||!isFinite(target)||target<=0) return null;
  return higherIsBetter ? actual/target : target/actual;
}
function healthBar(label,valTxt,perf,note){
  const pct=perf==null?0:Math.max(0,Math.min(100,Math.round(perf*100)));
  const cls=perf==null?'':(perf>=1?'hb-ok':(perf>=0.75?'hb-warn':'hb-bad'));
  return `<div class="health-bar-item"><div class="health-bar-head"><span>${label}${note?` <span class="health-bar-note">${note}</span>`:''}</span><b>${valTxt}</b></div>
    <div class="health-bar-track"><div class="health-bar-fill ${cls}" style="width:${pct}%"></div></div></div>`;
}
function renderHealthCard(d){
  const goal=STATE.cpicGoal;
  const tetoCpc=(goal&&HEALTH_RATIO_CPC)?goal*HEALTH_RATIO_CPC:null;
  const tetoCpv=(goal&&HEALTH_RATIO_CPV)?goal*HEALTH_RATIO_CPV:null;
  const minVischk=HEALTH_VISCHK_MIN;

  const pCpic=healthPerf(d.cpic,goal,false);
  const pCpc=healthPerf(d.cpc,tetoCpc,false);
  const pCpv=healthPerf(d.cpv,tetoCpv,false);
  const pVischk=healthPerf(d.vischk,minVischk,true);

  const comps=[[pCpic,0.5],[pCpc,0.2],[pCpv,0.15],[pVischk,0.15]].filter(c=>c[0]!=null);
  const wSum=comps.reduce((s,c)=>s+c[1],0);
  const score=wSum? Math.max(0,Math.min(100,Math.round(comps.reduce((s,c)=>s+Math.min(c[0],1.3)*c[1],0)/wSum*100))) : null;

  const band = score==null?{cls:'',lbl:'Sem dados'}:
    score>=100?{cls:'rc-cyan',lbl:'Excelente'}:
    score>=70?{cls:'rc-green',lbl:'Bom'}:
    score>=40?{cls:'rc-yellow',lbl:'Regular'}:
    {cls:'rc-red',lbl:'Crítico'};
  const ringColor = band.cls==='rc-cyan'?'var(--aqua)':band.cls==='rc-green'?'var(--good)':band.cls==='rc-yellow'?'var(--yellow)':band.cls==='rc-red'?'var(--red)':'var(--border)';

  document.getElementById('healthScore').textContent = score==null?'--':score;
  document.getElementById('healthRing').style.background = `conic-gradient(${ringColor} ${(score||0)*3.6}deg, var(--border) 0deg)`;
  const badgeEl=document.getElementById('healthBadge');
  badgeEl.textContent = score==null?'--':`${band.lbl} · ${score}/100`;
  badgeEl.className = 'health-badge '+band.cls;
  document.getElementById('healthDesc').textContent = goal ? 'ancorado na meta de CPIC (CPL‑A)' : 'defina a meta de CPIC (CPL‑A) abaixo p/ calcular a nota';

  const goalInput=document.getElementById('healthGoalInput');
  document.getElementById('healthGoalCur').textContent = healthCurSym();
  if(document.activeElement!==goalInput) goalInput.value = goal!=null? healthToDisplay(goal).toFixed(2) : '';

  document.getElementById('healthBars').innerHTML = [
    healthBar('CPIC qualif. · meta '+(goal!=null?brl(goal):'—'), brl(d.cpic), pCpic),
    healthBar('CPC · teto '+(tetoCpc!=null?brl(tetoCpc):'—'), brl(d.cpc), pCpc),
    healthBar('CPV · teto '+(tetoCpv!=null?brl(tetoCpv):'—'), brl(d.cpv), pCpv),
    healthBar('VisCHK · mín '+(minVischk!=null?pct(minVischk):'—'), pct(d.vischk), pVischk),
  ].join('');
}
if(!window.__healthGoalWired){
  window.__healthGoalWired=true;
  document.addEventListener('input',e=>{
    if(e.target&&e.target.id==='healthGoalInput'){
      const v=parseFloat(e.target.value);
      STATE.cpicGoal=(isFinite(v)&&v>0)?healthFromDisplay(v):null;
      if(STATE.cpicGoal!=null) localStorage.setItem(HEALTH_GOAL_KEY,String(STATE.cpicGoal));
      else localStorage.removeItem(HEALTH_GOAL_KEY);
      if(STATE.page==='rel'){ const fM=metaActive(), fSall=salesActive();
        renderHealthCard(derive(totals(fSall,fM))); }
    }
  });
}
/* desempenho vs meta: CAC menor=melhor (meta/valor); ROAS maior=melhor (valor/meta) */
function relPerf(v,kind){
  if(v==null||!isFinite(v)) return null;
  if(kind==='roas'){ return ROAS_TARGET?v/ROAS_TARGET:null; }
  return (CAC_TARGET&&v>0)?CAC_TARGET/v:null;
}
function relColor(v,kind){ const p=relPerf(v,kind); if(p==null) return '';
  if(p<REL_BAND_LO) return 'rc-red'; if(p<1) return 'rc-yellow';
  if(p<REL_BAND_HI) return 'rc-green'; return 'rc-cyan'; }
function relCard(label,val,hero){ return `<div class="rel-card${hero?' hero':''}"><div class="rl">${label}</div><div class="rv">${val}</div></div>`; }
function relCards(id,t){ const d=derive(t);
  document.getElementById(id).innerHTML=[
    relCard('Valor Gasto',brl(d.gasto)),
    relCard('Vendas',intf(t.vendas)),
    relCard('Faturamento',brl(t.fat)),
    relCard('CAC',`<span class="${relColor(d.cac,'cac')}">${brl(d.cac)}</span>`),
    relCard('Ticket Médio',brl(d.ticket)),
    relCard('ROAS',`<span class="${relColor(d.roas,'roas')}">${roasf(d.roas)}</span>`,true),
  ].join('');
}
/* tabela estática simples (cols/rows/foot = [{v,cls}]) — mantém a estética .dt */
function relRenderTable(id,cols,rows,foot){
  const el=document.getElementById(id); if(!el) return;
  const th='<thead><tr>'+cols.map(c=>`<th class="${c.cls||''}">${c.label}</th>`).join('')+'</tr></thead>';
  const tb='<tbody>'+(rows.length?rows.map(r=>'<tr>'+r.map(c=>`<td class="${c.cls||''}">${c.v}</td>`).join('')+'</tr>').join('')
    :`<tr><td class="dim" colspan="${cols.length}" style="color:var(--muted)">Sem dados no período.</td></tr>`)+'</tbody>';
  const tf=foot?('<tfoot><tr>'+foot.map(c=>`<td class="${c.cls||''}">${c.v}</td>`).join('')+'</tr></tfoot>'):'';
  el.innerHTML=th+tb+tf;
}
function adLink(name){ const u=AD_LINKS[name];
  return u?`<a class="rel-adlink" href="${esc(u)}" target="_blank" rel="noopener">Abrir ▸</a>`:'<span class="rel-adlink off">—</span>'; }
function relBriefKey(){ if(STATE.selDays.size) return null; return STATE.preset||null; }
function renderRelBrief(){
  const wrap=document.getElementById('relBrief'), stampEl=document.getElementById('relBriefStamp');
  const bf=DATA.briefings||{}, per=bf.periodos||{}, key=relBriefKey();
  stampEl.textContent = bf.generated_at ? `Briefing gerado por IA · última atualização ${bf.generated_at} · atualiza 1×/dia às 23h59` : '';
  if(!Object.keys(per).length){
    wrap.innerHTML='<div class="rel-brief-empty">O briefing por IA ainda não foi gerado. Ele é atualizado automaticamente 1×/dia às 23h59.</div>'; return; }
  if(!key || !per[key]){
    wrap.innerHTML='<div class="rel-brief-empty">Briefing disponível para os períodos predefinidos (Hoje, Ontem, 3&nbsp;dias, 7&nbsp;dias, 14&nbsp;dias, 30&nbsp;dias, Este mês, Mês passado, Todo período). Selecione um desses botões no topo.</div>'; return; }
  const item=per[key];
  wrap.innerHTML = item.html || item.texto || '<div class="rel-brief-empty">Sem conteúdo.</div>';
}
function renderRelatorios(){
  const fM=metaActive(), fSall=salesActive(), fSads=fSall.filter(s=>s.meta);
  const tTot=totals(fSall,fM), tAds=totals(fSads,fM);
  const dvT=derive(tTot), dvA=derive(tAds);

  /* cabeçalho do período */
  const pr=PRESETS.find(p=>p[0]===STATE.preset);
  document.getElementById('relPeriodName').textContent = STATE.selDays.size?'Dias selecionados':(pr?pr[1]:'Personalizado');
  let rangeTxt='';
  if(STATE.from&&STATE.to){ const nD=Math.round((new Date(STATE.to+'T00:00:00')-new Date(STATE.from+'T00:00:00'))/86400000)+1;
    rangeTxt=`${brdate(STATE.from)} a ${brdate(STATE.to)}`+(nD>0?` · ${nD} dia${nD>1?'s':''}`:''); }
  document.getElementById('relPeriodRange').textContent=rangeTxt;

  /* cards */
  relCards('relCardsTotal',tTot);
  relCards('relCardsAds',tAds);

  /* saúde do funil (CPIC/CPC/CPV/VisCHK vs. meta + histórico da conta) */
  renderHealthCard(dvT);

  /* visão por campanha (só Meta Ads) */
  const aggC=buildAgg(fSads,fM,'camp');
  const crows=Object.entries(aggC).sort((a,b)=>b[1].sp-a[1].sp).map(([name,ag])=>{ const d=derive(ag);
    return [{v:esc(name),cls:'dim'},{v:brl(d.gasto)},{v:intf(ag.vendas)},
      {v:roasf(d.roas),cls:relColor(d.roas,'roas')},{v:brl(d.cac),cls:relColor(d.cac,'cac')},
      {v:brl(d.cpm)},{v:pct(d.ctr)},{v:pct(d.cr)},{v:pct(d.vischk)},{v:pct(d.convchk)}]; });
  relRenderTable('relCamp',
    [{label:'Campanha',cls:'dim'},{label:'Gasto'},{label:'Venda'},{label:'ROAS'},{label:'CAC'},{label:'CPM'},{label:'CTR'},{label:'CR'},{label:'VisCHK'},{label:'ConvCHK'}],
    crows,
    [{v:'Total',cls:'dim'},{v:brl(dvA.gasto)},{v:intf(tAds.vendas)},{v:roasf(dvA.roas),cls:relColor(dvA.roas,'roas')},{v:brl(dvA.cac),cls:relColor(dvA.cac,'cac')},
     {v:brl(dvA.cpm)},{v:pct(dvA.ctr)},{v:pct(dvA.cr)},{v:pct(dvA.vischk)},{v:pct(dvA.convchk)}]);

  /* top / piores anúncios (só Meta Ads, com gasto no período) */
  const aggAd=buildAgg(fSads,fM,'ad');
  const ads=Object.entries(aggAd).filter(([n,ag])=>ag.sp>0).map(([name,ag])=>{ const d=derive(ag);
    return {name,gasto:d.gasto,vendas:ag.vendas,cac:d.cac,roas:d.roas}; });
  ads.sort((a,b)=>{ const ra=a.roas==null?-1:a.roas, rb=b.roas==null?-1:b.roas; if(rb!==ra) return rb-ra;
    const ca=a.cac==null?Infinity:a.cac, cb=b.cac==null?Infinity:b.cac; return ca-cb; });
  const top=ads.slice(0,5), topSet=new Set(top.map(a=>a.name));
  const worst=ads.filter(a=>!topSet.has(a.name)).slice(-5).reverse();
  const adCols=[{label:'Anúncio',cls:'dim'},{label:'Gasto'},{label:'Vendas'},{label:'CAC'},{label:'ROAS'},{label:'Link',cls:'dim'}];
  const adRows=list=>list.map(a=>[{v:esc(a.name),cls:'dim'},{v:brl(a.gasto)},{v:intf(a.vendas)},
    {v:brl(a.cac),cls:relColor(a.cac,'cac')},{v:roasf(a.roas),cls:relColor(a.roas,'roas')},{v:adLink(a.name),cls:'dim'}]);
  relRenderTable('relTop',adCols,adRows(top));
  relRenderTable('relWorst',adCols,adRows(worst));

  /* briefing do gestor (texto pré-gerado por IA) */
  renderRelBrief();
}

const esc=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

/* ---------------- date presets ---------------- */
const PRESETS=[
  ['hoje','Hoje',()=>[TODAY,TODAY]],
  ['ontem','Ontem',()=>[addDays(TODAY,-1),addDays(TODAY,-1)]],
  ['3d','3 dias',()=>[addDays(TODAY,-2),TODAY]],
  ['7d','7 dias',()=>[addDays(TODAY,-6),TODAY]],
  ['14d','14 dias',()=>[addDays(TODAY,-13),TODAY]],
  ['30d','30 dias',()=>[addDays(TODAY,-29),TODAY]],
  ['mes','Este mês',()=>{const [y,m]=TODAY.split('-');return [`${y}-${m}-01`,TODAY];}],
  ['mespass','Mês passado',()=>{const dt=new Date(TODAY+'T00:00:00');const f=new Date(dt.getFullYear(),dt.getMonth()-1,1);const l=new Date(dt.getFullYear(),dt.getMonth(),0);return [dstr(f),dstr(l)];}],
  ['todo','Máximo',()=>[B.date_min,B.date_max]],
];
/* rótulo do botão de período — mostra o intervalo aplicado dentro do próprio botão */
function syncDateInputs(){
  const el=document.getElementById('periodBtnLabel'); if(!el) return;
  if(STATE.selDays.size){ el.textContent=STATE.selDays.size+(STATE.selDays.size>1?' dias selecionados':' dia selecionado'); return; }
  const pr=PRESETS.find(p=>p[0]===STATE.preset);
  if(STATE.from&&STATE.to) el.textContent=brdate(STATE.from)+' – '+brdate(STATE.to)+(pr?' · '+pr[1]:'');
  else el.textContent='Selecionar período';
}
function applyPreset(id){ const p=PRESETS.find(x=>x[0]===id); if(!p)return; const [f,t]=p[2]();
  STATE.from=f; STATE.to=t; STATE.preset=id; STATE.selDays.clear(); ppClose(); syncDateInputs(); renderAll(); }

/* ---- popover do seletor de período (estilo Data Studio) ---- */
const MONTHS_PT=['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
const DOW_PT=['D','S','T','Q','Q','S','S'];
const PP={from:null,to:null,preset:'',fromView:'',toView:''};
function ymView(ds){ return (ds||TODAY).slice(0,7); }
function shiftView(view,delta){ const [y,m]=view.split('-').map(Number); const dt=new Date(y,m-1+delta,1); return dt.getFullYear()+'-'+pad(dt.getMonth()+1); }
function ppIsOpen(){ const pop=document.getElementById('periodPop'); return pop && !pop.hidden; }
function ppOpen(){
  PP.from=STATE.from; PP.to=STATE.to; PP.preset=STATE.selDays.size?'':STATE.preset;
  PP.fromView=ymView(STATE.from); PP.toView=ymView(STATE.to);
  document.getElementById('periodPop').hidden=false;
  document.getElementById('periodBtn').setAttribute('aria-expanded','true');
  ppRenderAll();
}
function ppClose(){ const pop=document.getElementById('periodPop'); if(pop) pop.hidden=true;
  const b=document.getElementById('periodBtn'); if(b) b.setAttribute('aria-expanded','false'); }
function ppRenderAll(){ ppRenderPresets(); ppRenderCal('from'); ppRenderCal('to'); ppRenderRange(); }
function ppRenderPresets(){
  const host=document.getElementById('ppPresets');
  host.innerHTML=PRESETS.map(p=>`<button class="pp-preset ${PP.preset===p[0]?'active':''}" data-p="${p[0]}">${p[1]}</button>`).join('');
  host.querySelectorAll('.pp-preset').forEach(c=>c.addEventListener('click',()=>{
    const p=PRESETS.find(x=>x[0]===c.dataset.p); const [f,t]=p[2]();
    PP.from=f; PP.to=t; PP.preset=p[0]; PP.fromView=ymView(f); PP.toView=ymView(t); ppRenderAll();
  }));
}
function ppRenderCal(side){
  const host=document.getElementById(side==='from'?'ppCalFrom':'ppCalTo');
  const view=side==='from'?PP.fromView:PP.toView;
  const [y,m]=view.split('-').map(Number);
  const startDow=new Date(y,m-1,1).getDay(), dim=new Date(y,m,0).getDate();
  let cells='';
  for(let i=0;i<startDow;i++) cells+='<span class="pp-day empty"></span>';
  for(let d=1;d<=dim;d++){
    const ds=view+'-'+pad(d);
    const inR=PP.from&&PP.to&&ds>=PP.from&&ds<=PP.to, isEdge=(ds===PP.from||ds===PP.to);
    const cls=['pp-day']; if(inR) cls.push('in'); if(ds===PP.from) cls.push('edge-l'); if(ds===PP.to) cls.push('edge-r'); if(isEdge) cls.push('sel');
    cells+=`<button class="${cls.join(' ')}" data-side="${side}" data-d="${ds}">${d}</button>`;
  }
  host.innerHTML=`<div class="pp-cal-head"><span class="pp-cal-title">${side==='from'?'Data de início':'Data de término'}</span></div>
    <div class="pp-cal-nav"><button class="pp-nav" data-nav="-1">‹</button><span class="pp-cal-month">${MONTHS_PT[m-1]} ${y}</span><button class="pp-nav" data-nav="1">›</button></div>
    <div class="pp-dow">${DOW_PT.map(x=>`<span>${x}</span>`).join('')}</div>
    <div class="pp-grid">${cells}</div>`;
  host.querySelectorAll('.pp-nav').forEach(b=>b.addEventListener('click',()=>{
    const nv=shiftView(view,+b.dataset.nav); if(side==='from') PP.fromView=nv; else PP.toView=nv; ppRenderCal(side);
  }));
  host.querySelectorAll('.pp-day[data-d]').forEach(b=>b.addEventListener('click',()=>ppPickDay(side,b.dataset.d)));
}
function ppPickDay(side,ds){
  PP.preset='';
  if(side==='from'){ PP.from=ds; if(PP.to&&PP.from>PP.to) PP.to=PP.from; }
  else { PP.to=ds; if(PP.from&&PP.to<PP.from) PP.from=PP.to; }
  ppRenderAll();
}
function ppRenderRange(){
  const el=document.getElementById('ppRange');
  if(PP.from&&PP.to){ const n=Math.round((new Date(PP.to+'T00:00:00')-new Date(PP.from+'T00:00:00'))/86400000)+1;
    el.textContent=brdate(PP.from)+' – '+brdate(PP.to)+(n>0?' · '+n+(n>1?' dias':' dia'):''); }
  else el.textContent='Selecione as datas';
}
function ppApply(){
  if(!PP.from||!PP.to){ ppClose(); return; }
  STATE.from=PP.from; STATE.to=PP.to; STATE.preset=PP.preset||''; STATE.selDays.clear();
  ppClose(); syncDateInputs(); renderAll();
}

/* ---------------- navigation & boot ---------------- */
function setPage(p){ STATE.page=p;
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.toggle('active',n.dataset.page===p));
  document.getElementById('page-geral').classList.toggle('active',p==='geral');
  document.getElementById('page-meta').classList.toggle('active',p==='meta');
  document.getElementById('page-rel').classList.toggle('active',p==='rel');
  document.getElementById('ptitle').textContent = p==='meta'?'Meta Ads':(p==='rel'?'Insights de IA':'Visão Geral');
  document.getElementById('navToggle').checked=false;
  history.replaceState(null,'', '#'+p);
  renderAll();
}
function renderAll(){ if(STATE.page==='meta') renderMeta(); else if(STATE.page==='rel') renderRelatorios(); else renderGeral(); }

/* Tema ESCURO é o padrão; só fica claro se o usuário tiver escolhido 'light'. */
function applyTheme(){ const t=localStorage.getItem('dm_theme'); if(t==='light') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme','dark'); }
applyTheme();
document.getElementById('themeBtn').addEventListener('click',()=>{ const dark=document.documentElement.getAttribute('data-theme')==='dark'; localStorage.setItem('dm_theme',dark?'light':'dark'); applyTheme(); renderAll(); });

document.querySelectorAll('.nav-item').forEach(n=>n.addEventListener('click',()=>setPage(n.dataset.page)));
document.getElementById('taxToggle').addEventListener('click',function(){ STATE.tax=!STATE.tax; this.classList.toggle('on',STATE.tax); renderAll(); });
function syncCurButtons(){
  document.getElementById('curUsdBtn').classList.toggle('active', STATE.currency==='usd');
  document.getElementById('curBrlBtn').classList.toggle('active', STATE.currency==='brl');
}
function setCurrency(c){ if(c!==STATE.currency){ STATE.currency=c; localStorage.setItem('dm_currency',c); syncCurButtons(); renderAll(); } }
document.getElementById('curUsdBtn').addEventListener('click',()=>setCurrency('usd'));
document.getElementById('curBrlBtn').addEventListener('click',()=>setCurrency('brl'));
/* seletor de período: abre/fecha popover, aplicar/cancelar, fechar ao clicar fora/Esc */
document.getElementById('periodBtn').addEventListener('click',e=>{ e.stopPropagation(); ppIsOpen()?ppClose():ppOpen(); });
document.getElementById('ppApply').addEventListener('click',ppApply);
document.getElementById('ppCancel').addEventListener('click',ppClose);
document.getElementById('periodPop').addEventListener('click',e=>e.stopPropagation());
document.addEventListener('click',()=>{ if(ppIsOpen()) ppClose(); });
document.addEventListener('keydown',e=>{ if(e.key==='Escape'&&ppIsOpen()) ppClose(); });
document.getElementById('clearBtn').addEventListener('click',()=>{ STATE.mSelC.clear();STATE.mSelA.clear();STATE.mSelAd.clear();STATE.selDays.clear(); applyPreset('mes'); });
/* botões ✕ Filtro de cada tabela (Campanhas/Conjuntos/Anúncios): limpam só a própria dimensão */
document.getElementById('clearCampBtn').addEventListener('click',()=>{ STATE.mSelC.clear(); renderMeta(); });
document.getElementById('clearAdsetBtn').addEventListener('click',()=>{ STATE.mSelA.clear(); renderMeta(); });
document.getElementById('clearAdBtn').addEventListener('click',()=>{ STATE.mSelAd.clear(); renderMeta(); });
document.getElementById('refreshBtn').addEventListener('click',function(){ this.classList.add('loading'); location.href=location.pathname+'?t='+Date.now()+location.hash; });

document.title=(B.client_sub?B.client_sub+' · ':'')+(B.client_name||'Dashboard');
document.getElementById('logoMain').textContent=B.client_name||'—';
document.getElementById('logoSub').textContent=B.client_sub||'';
document.getElementById('taxLabel').textContent=B.tax_label||'Imposto';
document.getElementById('mainProdNote').textContent=MAIN_PRODUCT;
document.getElementById('mainProdNoteG').textContent=MAIN_PRODUCT;
document.getElementById('mainProdNoteProdG').textContent=MAIN_PRODUCT;
document.getElementById('mainProdNoteProdM').textContent=MAIN_PRODUCT;
document.getElementById('updated').innerHTML='Última atualização:<br>'+B.generated_at_brt+' (BRT)';
document.getElementById('buildFoot').textContent='build __BUILD_ID__';
document.getElementById('buildFoot2').textContent='· build __BUILD_ID__';

syncDateInputs();
document.getElementById('taxToggle').classList.toggle('on', STATE.tax);  /* imposto Meta ON por padrão */
syncCurButtons(); curRateLabel();  /* BRL é o padrão; cotação já pode vir do cache (localStorage) antes do fetch responder */
setPage(location.hash==='#meta'?'meta':(location.hash==='#rel'?'rel':'geral'));

/* auto-refresh com cache-bust ~30 min */
setTimeout(()=>{ location.href=location.pathname+'?t='+Date.now()+location.hash; }, 30*60*1000);

