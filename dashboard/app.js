import { EngineClient } from './api-client.js';
import { renderRisk, renderConfidence, renderScenarios } from './product-views.js';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const money = value => value == null ? 'Unknown' : new Intl.NumberFormat('en-AU', { style:'currency', currency:'AUD', maximumFractionDigits:0 }).format(value);
const percent = value => value == null ? 'Unknown' : `${(value * 100).toFixed(1)}%`;
const count = value => value == null ? 'Unknown' : Number(value).toLocaleString('en-AU');
const friendly = value => value == null ? 'Unknown' : String(value).replaceAll('_', ' ');
const decisionLabels = { selected:'Selected', not_selected:'Not selected', ineligible:'Ineligible' };
const scenarioLabels = { primary:'Primary · revenue', category_max30:'Category ≤ 30 merchants', category_max20:'Category ≤ 20 merchants', low_confidence_max10:'Low confidence ≤ 10', conservative:'Conservative · sensitivity' };
const engineLabels = { revenue:'Revenue', eligibility:'Eligibility', confidence:'Confidence', risk:'Risk', diversification:'Diversification', strategic_fit:'Strategic fit', portfolio:'Portfolio' };
const engineNotes = { revenue:'Next-28-day take-rate revenue estimate.', eligibility:'Historical inclusion rules and reason codes.', confidence:'Revenue reliability and individual intervals.', risk:'Native evidence and review prompts; no loss model.', diversification:'Operating-activity concentration evidence.', strategic_fit:'Configured business preferences, if available.', portfolio:'Saved shortlist and optimisation status.' };
const state = { catalog:null, snapshot:null, workflow:null, workflowError:null, page:'overview', pageIndex:0, selectedId:null, sort:'rank', direction:1, requestId:0, controller:null };
const controls = ['run', 'split', 'cutoff', 'scenario'];
const pageSize = 25;

function options(id, values, label = x => x, preferred = null) {
  const select = $(id), current = preferred ?? select.value;
  select.replaceChildren(...values.map(value => new Option(label(value), value)));
  select.value = values.includes(current) ? current : values.includes('primary') ? 'primary' : values[0] ?? '';
}
function runInfo() { return state.catalog?.runs.find(r => r.id === $('run').value); }
function splitInfo() { return runInfo()?.splits.find(s => s.id === $('split').value); }
function cascade(from) {
  if (from === 'run') options('split', runInfo()?.splits.map(s => s.id) ?? [], x => ({latest:'Latest recommendation',test:'Held-out test',validation:'Validation'}[x] ?? x));
  if (from === 'run' || from === 'split') {
    const info = splitInfo();
    options('cutoff', info?.cutoffs ?? []);
    options('scenario', info?.scenarios ?? [], x => scenarioLabels[x] ?? friendly(x));
    if (info?.error) throw new Error(info.error);
  }
}
function beginRequest() {
  state.controller?.abort();
  state.controller = new AbortController();
  state.requestId += 1;
  state.snapshot = null;
  state.workflow = null;
  state.workflowError = null;
  $('workspace').hidden = true;
  $('error').hidden = true;
  $('loading').hidden = false;
  $('feedback').textContent = '';
  $('connection-badge').className = 'pill neutral';
  $('connection-badge').textContent = 'Loading outputs';
  return { id:state.requestId, signal:state.controller.signal };
}
function showError(error) {
  $('workspace').hidden = true;
  $('loading').hidden = true;
  $('error').hidden = false;
  $('error-message').textContent = error.message;
  $('connection-badge').className = 'pill bad';
  $('connection-badge').textContent = 'Connection issue';
}
async function connect() {
  const request = beginRequest();
  const timeout = setTimeout(() => { if (request.id === state.requestId) state.controller?.abort(); }, 20000);
  controls.forEach(id => $(id).disabled = true);
  try {
    const client = new EngineClient($('source').value);
    const catalog = await client.catalog(request.signal);
    if (request.id !== state.requestId) return;
    state.catalog = catalog;
    if (!catalog.runs.length) throw new Error('No saved engine runs were found. Start the server with --engine-root pointing to the engine output directory.');
    options('run', catalog.runs.map(r => r.id));
    cascade('run');
    await loadSnapshot(client, request);
  } catch (error) {
    if (request.id === state.requestId) showError(error.name === 'AbortError' ? new Error('Loading timed out. Refresh after engine outputs are ready.') : error);
  } finally {
    clearTimeout(timeout);
    if (request.id === state.requestId) controls.forEach(id => $(id).disabled = false);
  }
}
async function loadSnapshot(client = new EngineClient($('source').value), request = beginRequest()) {
  const timeout = setTimeout(() => { if (request.id === state.requestId) state.controller?.abort(); }, 20000);
  try {
    const selection = Object.fromEntries(controls.map(id => [id, $(id).value]));
    const data = await client.snapshot(selection, request.signal);
    if (request.id !== state.requestId) return;
    state.snapshot = data;
    state.pageIndex = 0;
    $('loading').hidden = true;
    $('workspace').hidden = false;
    $('connection-badge').textContent = data.source === 'synthetic_demo' ? 'Synthetic demo' : 'Saved outputs loaded';
    $('connection-badge').className = `pill ${data.source === 'synthetic_demo' ? 'warn' : 'good'}`;
    $('feedback').textContent = data.source === 'synthetic_demo' ? 'Preview only · invented merchants and values. This is not an engine recommendation.' : data.warnings.length ? `${data.warnings.length} evidence caveat(s) · ${data.warnings[0]}` : '';
    const groups = data.groups;
    options('top-group', groups);
    options('group-filter', ['', ...groups], x => x || 'All groups');
    render();
    try {
      const comparison=await client.workflow(selection,request.signal);
      if (request.id!==state.requestId) return;
      if (comparison && comparison.source_fingerprint!==data.source_fingerprint) throw new Error('Outputs changed while loading. Refresh for a consistent scenario comparison.');
      state.workflow=comparison;
      state.workflowError=comparison ? null : 'Saved scenario comparisons are available with local engine outputs.';
    } catch(error) {
      if (request.id!==state.requestId) return;
      state.workflowError=error.message;
    }
    $('scenario-content').innerHTML=renderScenarios(state.workflow,state.workflowError);
  } catch (error) {
    if (request.id === state.requestId) showError(error.name === 'AbortError' ? new Error('Loading timed out. Retry when the source is available.') : error);
  } finally { clearTimeout(timeout); }
}

function setPage(page) {
  state.page = page;
  document.querySelectorAll('nav [data-page]').forEach(button => {
    if (button.dataset.page === page) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  document.querySelectorAll('.page').forEach(section => section.hidden = section.id !== page);
  $('page-title').textContent = { overview:'Portfolio overview', explorer:'Merchant explorer', risk:'Risk evidence', confidence:'Confidence review', scenarios:'Scenario comparison', engines:'Engine connections' }[page];
  $('page-subtitle').textContent = { overview:'Understand the shortlist. Inspect the evidence.', explorer:'Explore commercial value, eligibility and evidence separately.', risk:'Inspect coverage, review prompts and shared downstream evidence.', confidence:'Review uncertainty and source-supplied actions.', scenarios:'Compare saved selections, commercial cost and evidence coverage.', engines:'Inspect the output version and status of every component.' }[page];
}
function selected() { return state.snapshot.merchants.filter(m => m.decision === 'selected').sort((a,b) => a.rank - b.rank); }
function pill(label, kind='neutral') { return `<span class="pill ${kind}">${esc(label)}</span>`; }
function table(rows, sortable=false) {
  const headings = [['rank','Rank'],['name','Merchant'],['category','Operating activity'],['prediction','Est. revenue'],['confidence','Reliability'],['risk','Risk evidence'],['decision','Overall decision']];
  return `<table><thead><tr>${headings.map(([key,label]) => `<th${sortable ? ` aria-sort="${state.sort === key ? state.direction === 1 ? 'ascending' : 'descending' : 'none'}"` : ''}>${sortable ? `<button class="sort-button" data-sort="${key}">${label} ${state.sort === key ? state.direction === 1 ? '↑' : '↓' : '↕'}</button>` : label}</th>`).join('')}</tr></thead><tbody>${rows.length ? rows.map(m => `<tr${state.page === 'explorer' && m.id === state.selectedId ? ' class="active-row"' : ''}><td class="numeric">${m.displayRank ?? m.rank ?? '—'}</td><td><button class="merchant-link" data-merchant="${esc(m.id)}">${esc(m.name || 'Unresolved merchant')}<span class="small merchant-id">${esc(m.id)}</span></button></td><td class="category-cell">${esc(m.category ?? 'Unknown activity')}</td><td class="numeric">${money(m.prediction)}</td><td>${percent(m.confidence.reliability)}<div class="small">${esc(friendly(m.confidence.band))}</div></td><td>${pill(m.risk.review_50 == null ? 'Unknown' : m.risk.review_50 ? 'Review prompt' : 'Observed', m.risk.review_50 ? 'warn' : 'neutral')}</td><td>${pill(decisionLabels[m.decision], m.decision === 'selected' ? 'good' : 'neutral')}</td></tr>`).join('') : '<tr><td class="empty-cell" colspan="7">No merchants match this view. Change or reset the filters.</td></tr>'}</tbody></table>`;
}
function renderOverview() {
  const d = state.snapshot, rows = selected(), s = d.summary;
  $('hero-title').textContent = d.source === 'synthetic_demo' ? 'A preview of the decision workspace' : d.scenario === 'primary' ? 'Your revenue-led merchant shortlist' : 'A saved portfolio sensitivity';
  $('hero-description').textContent = `${scenarioLabels[d.scenario] ?? friendly(d.scenario)} · ${s.selected} merchants selected by the engine. ${d.split === 'latest' ? 'Future outcomes are not observable for this cutoff.' : 'Retrospective outcome evidence is shown separately from estimates.'}`;
  $('export').disabled = !d.export_allowed || !rows.length;
  const low = rows.filter(m => ['low','unresolved'].includes(m.confidence.band) || m.confidence.band == null).length;
  $('kpis').innerHTML = [ ['Selected merchants',count(s.selected),`${count(s.eligible)} historically eligible`], ['Estimated 28-day revenue',money(s.predicted_revenue),'Take-rate revenue · not profit'], ['Candidate universe',count(s.candidates),'Includes inactive and missing-master records'], ['Low / unknown confidence',count(low),'Selected merchants · evidence only'] ].map(([label,value,foot]) => `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div><div class="kpi-foot">${foot}</div></div>`).join('');
  const mix = new Map();
  rows.forEach(m => mix.set(m.category ?? 'Unknown', (mix.get(m.category ?? 'Unknown') ?? 0)+1));
  $('industry-mix').innerHTML = [...mix].sort((a,b) => b[1]-a[1]).slice(0,7).map(([name,n]) => `<div class="mix-row"><span class="mix-label" title="${esc(name)}">${esc(name)}</span><div class="bar-track"><span class="bar-fill" style="width:${Math.round(n / Math.max(rows.length,1)*100)}%"></span></div><span class="mix-value">${n} · ${Math.round(n / Math.max(rows.length,1)*100)}%</span></div>`).join('') + `<p class="evidence-note">${mix.size} operating activities${mix.size > 7 ? ' · showing the 7 largest' : ''}. Bars use the full selected portfolio as denominator.</p>`;
  const metrics = d.metrics;
  $('comparison').innerHTML = metrics ? [['Selected realised revenue',money(metrics.realised_revenue_aud)],['90-day baseline · same constraints',money(metrics.baseline_realised_same_constraints_aud)],['Difference vs baseline',money(metrics.delta_vs_baseline_aud)],['Oracle capture',percent(metrics.oracle_capture_same_constraints)]].map(([label,value])=>`<div class="metric-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('') + '<p class="evidence-note">Observed course outcomes for this date and scenario. Predictions and realised revenue are different measures.</p>' : `<div class="empty-evidence"><strong>${d.split === 'latest' ? 'Future outcome unavailable' : 'Evaluation not supplied'}</strong>${d.split === 'latest' ? 'The dataset ends at this cutoff. Realised revenue and forecast accuracy cannot be measured for this shortlist.' : 'This source has no evaluation record for the selected date and scenario.'}</div><p class="evidence-note">No inferred uplift or artificial baseline values are displayed.</p>`;
  $('priority-table').innerHTML = table(rows.slice(0,10));
  renderGroup();
}
function renderGroup() {
  if (!state.snapshot) return;
  const rows = state.snapshot.merchants.filter(m => m.group === $('top-group').value && m.group_rank != null).sort((a,b)=>a.group_rank-b.group_rank).map(m => ({...m, displayRank:m.group_rank}));
  $('group-table').innerHTML = table(rows) + (rows.length < 10 ? `<p class="evidence-note">${rows.length} group picks supplied; ${10-rows.length} fewer than ten. No replacements are fabricated.</p>` : '');
}
function filteredRows() {
  const q = $('search').value.trim().toLowerCase(), group = $('group-filter').value, decision = $('decision-filter').value, confidence = $('confidence-filter').value;
  return state.snapshot.merchants.filter(m => (!q || `${m.name ?? ''} ${m.id}`.toLowerCase().includes(q)) && (!group || m.group === group) && (!decision || (decision === 'group_top10' ? m.group_rank != null : m.decision === decision)) && (!confidence || (confidence === 'unknown' ? m.confidence.band == null || m.confidence.band === 'unresolved' : m.confidence.band === confidence))).sort((a,b) => {
    const get = m => ({rank:m.rank, name:m.name, category:m.category, prediction:m.prediction, confidence:m.confidence.reliability, risk:m.risk.review_50, decision:m.decision})[state.sort];
    const av=get(a), bv=get(b);
    if (av == null || bv == null) return av == null && bv == null ? a.id.localeCompare(b.id) : av == null ? 1 : -1;
    const delta = typeof av === 'string' ? av.localeCompare(bv) : Number(av)-Number(bv);
    return delta * state.direction || a.id.localeCompare(b.id);
  });
}
function renderExplorer() {
  if (!state.snapshot) return;
  const rows = filteredRows(), pages = Math.max(1,Math.ceil(rows.length/pageSize));
  state.pageIndex = Math.min(state.pageIndex,pages-1);
  if (!rows.some(m=>m.id===state.selectedId)) state.selectedId = rows[0]?.id ?? null;
  const start = state.pageIndex*pageSize;
  $('result-count').textContent = `${count(rows.length)} matching merchants · ${rows.length ? start+1 : 0}–${Math.min(start+pageSize,rows.length)} shown`;
  $('explorer-table').innerHTML = table(rows.slice(start,start+pageSize),true);
  $('page-count').textContent = `Page ${state.pageIndex+1} of ${pages}`;
  $('prev').disabled = state.pageIndex===0;
  $('next').disabled = state.pageIndex===pages-1;
  renderDetail(rows.find(m=>m.id===state.selectedId));
}
function block(title, entries) { return `<div class="evidence-block"><h3>${esc(title)}</h3><dl>${entries.map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl></div>`; }
function renderDetail(m) {
  if (!m) { $('detail').innerHTML='<div class="empty-evidence">No merchant selected. Reset filters to inspect a candidate.</div>'; return; }
  const c=m.confidence, r=m.risk, h=m.history;
  $('detail').innerHTML = `<div class="detail-top"><div><div class="eyebrow">MERCHANT EVIDENCE</div><h2>${esc(m.name || 'Unresolved merchant')}</h2><div class="small">${esc(m.id)} · ${esc(m.category ?? 'Unknown activity')}</div></div>${pill(decisionLabels[m.decision],m.decision==='selected'?'good':'neutral')}</div><p class="detail-description">${m.decision === 'selected' ? `Included in the saved ${esc(friendly(state.snapshot.scenario))} portfolio at rank ${m.rank}.` : m.eligible ? 'Historically eligible, outside the saved overall portfolio in this scenario.' : 'Outside the historical eligible universe. See the supplied rule reasons below.'} ${m.group_rank != null ? `Independent group rank: ${m.group_rank}.` : ''}</p><div class="detail-grid">${[
    block('Revenue', [['28-day estimate',money(m.prediction)],['Historical 90-day revenue',money(h.revenue)],['Revenue model',state.snapshot.champion]]),
    block('Eligibility', [['Historical eligibility',m.eligible?'Eligible':'Ineligible'],['Disposition',friendly(m.disposition)],['Rule reasons',friendly(m.reason_codes)]]),
    block('Confidence', [['Reliability',percent(c.reliability)],['Evidence band',friendly(c.band)],['Individual lower bound',money(c.lower)],['Individual upper bound',money(c.upper)]]),
    block('Risk evidence', [['Consumer native max',percent(r.consumer_probability_max)],['Merchant native max',percent(r.merchant_probability_max)],['Consumer coverage',percent(r.consumer_coverage)],['Merchant coverage',percent(r.merchant_coverage)],['Consumer recency (days)',count(r.consumer_recency_days)],['Merchant recency (days)',count(r.merchant_recency_days)],['Evidence status',friendly(r.evidence_status)],['50% review prompt',r.review_50==null?'Unknown':r.review_50?'Yes':'No']]),
    block('Diversification / history', [['Source hypothetical-add HHI vs primary',m.diversification.marginal_category_hhi==null?'Unknown':Number(m.diversification.marginal_category_hhi).toFixed(5)],['Orders',count(h.orders)],['Customers',count(h.customers)],['Active days',count(h.active_days)],['Repeat share',percent(h.repeat_rate)]]),
    block('Strategic fit / portfolio', [['Strategic status',friendly(m.strategy.status)],['Strategic score',m.strategy.score ?? 'Unknown'],['Portfolio rank',m.rank ?? 'Not selected'],['Group rank',m.group_rank ?? 'Not in group Top-10']])
  ].join('')}</div><p class="evidence-note">${esc(h.start ? `${String(h.start).slice(0,10)} – ${String(h.end).slice(0,10)} · ` : '')}Risk evidence is not predicted loss. Reliability is not a probability of correctness. Individual intervals do not establish a portfolio guarantee. No final onboarding decision is implied.</p>`;
}
function renderEngines() {
  const d=state.snapshot;
  $('connection-summary').innerHTML = `${pill(d.source_label)} ${pill(d.run)} ${pill(d.integrity,d.integrity==='VERIFIED_PARQUET_HASHES'?'good':'warn')}`;
  $('engine-grid').innerHTML = d.engines.map((e,i)=>`<article class="engine-card"><span class="engine-number">COMPONENT ${String(i+1).padStart(2,'0')}</span><h3>${esc(engineLabels[e.id] ?? friendly(e.id))}</h3>${pill(e.status==='CONNECTED'?'Output loaded':friendly(e.status),e.status==='CONNECTED'?'good':'warn')}<p>${esc(engineNotes[e.id] ?? 'Supplied engine output.')}</p><small>${count(e.rows)} rows at this cutoff<br>${esc(e.versions.join(' · ') || 'Version unavailable')}</small></article>`).join('');
  $('warnings').innerHTML = d.warnings.map(w=>`<div class="warning-row">${esc(w)}</div>`).join('') || '<p class="evidence-note">No additional source warnings supplied.</p>';
  $('source-checks').innerHTML = [['Source',d.source_label],['Adapter contract',`Dashboard API 1.0 · ${d.adapter || 'seven-engine-files-v1'}`],['Parquet integrity',d.integrity],['Source fingerprint',d.source_fingerprint],['Shared Risk interface',d.risk_interface?.contract ?? 'Unavailable'],['Execution mode',friendly(d.execution?.mode)],['Frozen code status',friendly(d.execution?.code_status)],['Changed engine files',(d.execution?.changed_files || []).join(' · ') || 'None recorded'],['Producer lineage',d.lineage?.producer_lineage || 'Historical freeze record'],['Snapshot lineage',d.lineage?.snapshot_id ?? 'Saved legacy run'],['Solver status',d.solver.status ?? 'Unknown'],['Solver gap',d.solver.gap ?? 'Unknown'],['Loaded at',new Date(d.loaded_at).toLocaleString('en-AU')],['Refresh behaviour','Read saved outputs; does not train or execute engines']].map(([k,v])=>`<div><strong>${esc(k)}</strong>${esc(v)}</div>`).join('');
}
function render() {
  const d=state.snapshot;
  $('provenance').innerHTML = `<span>${esc(d.source_label)} / ${esc(d.run)} · ${esc(d.cutoff)} · ${esc(friendly(d.split))}</span><span>Revenue: ${esc(d.champion)} · Solver: ${esc(d.solver.status ?? 'Unknown')}</span>`;
  renderOverview(); renderExplorer(); renderEngines(); setPage(state.page);
  renderEvidence();
  $('scenario-content').innerHTML=renderScenarios(state.workflow,state.workflowError);
}
function renderEvidence() {
  if (!state.snapshot) return;
  $('risk-content').innerHTML=renderRisk(state.snapshot,$('risk-scope').value);
  $('confidence-content').innerHTML=renderConfidence(state.snapshot,$('confidence-scope').value);
}
function resetFilters() { $('search').value=''; ['group-filter','decision-filter','confidence-filter'].forEach(id=>$(id).value=''); state.pageIndex=0; }
function exportShortlist() {
  if (!state.snapshot?.export_allowed) return;
  const d=state.snapshot;
  const url=`/api/export?${new URLSearchParams({run:d.run,split:d.split,cutoff:d.cutoff,scenario:d.scenario})}`;
  const link=document.createElement('a'); link.href=url; link.download=`${d.run}_${d.cutoff}_${d.scenario}_shortlist.csv`; link.textContent='Download shortlist CSV';
  $('feedback').replaceChildren(document.createTextNode('Shortlist export ready · '),link,document.createTextNode(` · ${d.summary.selected} merchants from ${d.cutoff}.`));
  // A real HTTP attachment is portable across embedded and ordinary browsers.
  link.click();
}

document.querySelectorAll('nav [data-page]').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.page)));
['refresh','retry'].forEach(id=>$(id).addEventListener('click',connect));
$('source').addEventListener('change',()=>{ resetFilters(); state.selectedId=null; connect(); });
controls.forEach(id=>$(id).addEventListener('change',()=>{ try { cascade(id); loadSnapshot(); } catch(error) { state.controller?.abort(); state.requestId+=1; state.snapshot=null; showError(error); } }));
$('top-group').addEventListener('change',renderGroup);
['search','group-filter','decision-filter','confidence-filter'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',()=>{state.pageIndex=0;renderExplorer();}));
$('reset-filters').addEventListener('click',()=>{resetFilters();renderExplorer();});
$('prev').addEventListener('click',()=>{state.pageIndex-=1;renderExplorer();});
$('next').addEventListener('click',()=>{state.pageIndex+=1;renderExplorer();});
$('explore-selected').addEventListener('click',()=>{resetFilters();$('decision-filter').value='selected';renderExplorer();setPage('explorer');});
$('export').addEventListener('click',exportShortlist);
['risk-scope','confidence-scope'].forEach(id=>$(id).addEventListener('change',renderEvidence));
document.addEventListener('click',event=>{
  const scenario=event.target.closest('[data-scenario]');
  if (scenario) { $('scenario').value=scenario.dataset.scenario; setPage('overview'); loadSnapshot(); }
  const sort=event.target.closest('[data-sort]');
  if (sort) { const key=sort.dataset.sort; state.direction=state.sort===key?-state.direction:key==='prediction'||key==='confidence'?-1:1;state.sort=key;state.pageIndex=0;renderExplorer(); }
  const merchant=event.target.closest('[data-merchant]');
  if (merchant) { if(state.page!=='explorer') resetFilters();state.selectedId=merchant.dataset.merchant;const index=filteredRows().findIndex(m=>m.id===state.selectedId);state.pageIndex=Math.max(0,Math.floor(index/pageSize));renderExplorer();setPage('explorer');$('detail').scrollIntoView({block:'start'}); }
});
if (new URLSearchParams(location.search).get('demo')==='1') $('source').value='demo';
connect();
