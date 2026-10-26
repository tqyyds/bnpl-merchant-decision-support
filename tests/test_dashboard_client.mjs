import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { EngineClient, validateSnapshot } from '../dashboard/api-client.js';
import { renderRisk, renderConfidence, renderScenarios } from '../dashboard/product-views.js';

const fixture = JSON.parse(fs.readFileSync(new URL('../dashboard/demo.json', import.meta.url)));

test('normalised demo response validates without changing null evidence', () => {
  assert.equal(validateSnapshot(structuredClone(fixture)).merchants[0].risk.review_50, null);
});
test('unknown API version, duplicate merchants, malformed amounts and inconsistent summary fail', () => {
  for (const change of [data => data.api_version = '2.0', data => data.merchants.push(data.merchants[0]), data => data.merchants[0].prediction = '100', data => data.summary.selected = 11, data => data.metrics = {realised_revenue_aud: 100}]) {
    const data = structuredClone(fixture); change(data);
    assert.throws(() => validateSnapshot(data));
  }
});
test('source errors are surfaced and never silently fall back to demo', async () => {
  const original = globalThis.fetch;
  const calls = [];
  try {
    globalThis.fetch = async url => { calls.push(url); return new Response(JSON.stringify({error:'revenue: required fields missing'}), {status:422,headers:{'content-type':'application/json'}}); };
    await assert.rejects(new EngineClient('engine').snapshot({run:'changed'}), /required fields missing/);
    assert.deepEqual(calls, ['/api/snapshot?run=changed']);
  } finally { globalThis.fetch = original; }
});
test('static server mode explains how to start the engine bridge', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response('<html>404</html>', {status:404,headers:{'content-type':'text/html'}});
    await assert.rejects(new EngineClient().catalog(), /python -m dashboard.server/);
  } finally { globalThis.fetch = original; }
});
test('demo is loaded only when explicitly selected', async () => {
  const original = globalThis.fetch;
  try {
    let requested;
    globalThis.fetch = async url => {requested=url; return new Response(JSON.stringify(fixture), {headers:{'content-type':'application/json'}});};
    const data = await new EngineClient('demo').snapshot({});
    assert.equal(requested,'./demo.json');
    assert.equal(data.source,'synthetic_demo');
  } finally { globalThis.fetch = original; }
});

test('shared Risk rejects consumers bound to different evidence versions', () => {
  const data=structuredClone(fixture);
  data.risk_interface={contract:'risk-evidence-v1',binding_id:'one',consumers:{diversification:{binding_id:'one'},portfolio:{binding_id:'two'}}};
  data.merchants.forEach(m=>m.risk.binding_id='one');
  assert.throws(()=>validateSnapshot(data),/bindings disagree/);
  data.risk_interface.consumers.portfolio.binding_id='one';
  assert.equal(validateSnapshot(data),data);
});

test('unaccepted confidence keeps high-band merchants in the inspection queue and escapes source text', () => {
  const data=structuredClone(fixture);
  data.engines.find(e=>e.id==='confidence').status='INSUFFICIENT';
  data.merchants.filter(m=>m.decision==='selected').forEach(m=>{m.confidence.band='high';m.name='<script>private</script>';});
  const html=renderConfidence(data);
  assert.match(html,/10 merchants requiring evidence inspection/);
  assert.ok(!html.includes('<script>private</script>'));
  assert.match(html,/&lt;script&gt;private&lt;\/script&gt;/);
});

test('missing evidence and missing scenario results remain explicit', () => {
  assert.match(renderRisk(fixture),/unavailable/);
  assert.match(renderScenarios(null,'Source changed <retry>'),/Source changed &lt;retry&gt;/);
});

test('workflow requests bind run, split and cutoff and never load a demo fallback', async () => {
  const original=globalThis.fetch;
  try {
    let requested;
    globalThis.fetch=async url=>{requested=url;return new Response(JSON.stringify({api_version:'1.0',run:'fixture',split:'latest',cutoff:'2022-10-26',scenarios:[]}),{headers:{'content-type':'application/json'}});};
    await new EngineClient().workflow({run:'fixture',split:'latest',cutoff:'2022-10-26',scenario:'primary'});
    assert.equal(requested,'/api/workflow?run=fixture&split=latest&cutoff=2022-10-26');
    assert.equal(await new EngineClient('demo').workflow({}),null);
  } finally {globalThis.fetch=original;}
});
