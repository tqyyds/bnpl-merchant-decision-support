// The UI depends only on this versioned DTO, never engine-native field names.
export function validateSnapshot(data) {
  if (!data || data.api_version !== '1.0' || !Array.isArray(data.merchants) || !Array.isArray(data.engines) || !data.summary || !Array.isArray(data.groups) || !Array.isArray(data.warnings)) {
    throw new Error('Unsupported dashboard response. Update the API adapter for this schema version.');
  }
  const ids = new Set();
  for (const m of data.merchants) {
    if (typeof m.id !== 'string' || ids.has(m.id) || !['selected', 'not_selected', 'ineligible'].includes(m.decision) || !m.confidence || !m.risk || !m.history || !m.strategy || !m.diversification) {
      throw new Error('Invalid merchant response. Check the dashboard adapter contract.');
    }
    ids.add(m.id);
    for (const value of [m.prediction, m.rank, m.group_rank, m.confidence.lower, m.confidence.upper, m.confidence.reliability]) {
      if (value != null && (typeof value !== 'number' || !Number.isFinite(value) || value < 0)) throw new Error('Invalid numeric evidence in the dashboard response.');
    }
  }
  const selected = data.merchants.filter(m => m.decision === 'selected');
  if (data.summary.candidates !== ids.size || data.summary.selected !== selected.length || typeof data.summary.predicted_revenue !== 'number' || !Number.isFinite(data.summary.predicted_revenue)) throw new Error('Dashboard summary does not reconcile with its merchant records.');
  if (data.split === 'latest' && data.metrics != null) throw new Error('Latest recommendations cannot contain realised-outcome metrics.');
  if (data.risk_interface) {
    const r=data.risk_interface;
    if (r.contract!=='risk-evidence-v1' || !r.binding_id || r.consumers?.diversification?.binding_id!==r.binding_id || r.consumers?.portfolio?.binding_id!==r.binding_id || data.merchants.some(m=>m.risk.binding_id!==r.binding_id)) throw new Error('Risk source bindings disagree across downstream engines.');
  }
  return data;
}

export class EngineClient {
  constructor(mode = 'engine') { this.mode = mode; }
  async request(url, signal) {
    const response = await fetch(url, { signal, cache: 'no-store' });
    if (!response.headers.get('content-type')?.includes('application/json')) {
      throw new Error('Start the dashboard server with python -m dashboard.server; a static file server cannot read engines.');
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Connection failed (${response.status})`);
    return data;
  }
  async catalog(signal) {
    if (this.mode === 'demo') {
      const demo = await this.request('./demo.json', signal);
      return { api_version: '1.0', source: 'synthetic_demo', source_label: 'Synthetic demo', runs: [{ id: demo.run, splits: [{ id: demo.split, cutoffs: [demo.cutoff], scenarios: [demo.scenario] }] }] };
    }
    const data = await this.request('/api/catalog', signal);
    if (data.api_version !== '1.0' || !Array.isArray(data.runs)) throw new Error('Unsupported engine catalog version.');
    return data;
  }
  async snapshot(selection, signal) {
    const url = this.mode === 'demo' ? './demo.json' : `/api/snapshot?${new URLSearchParams(selection)}`;
    return validateSnapshot(await this.request(url, signal));
  }
  async workflow({run,split,cutoff}, signal) {
    if (this.mode==='demo') return null;
    const data=await this.request(`/api/workflow?${new URLSearchParams({run,split,cutoff})}`,signal);
    if (data.api_version!=='1.0' || !Array.isArray(data.scenarios) || data.run!==run || data.cutoff!==cutoff || data.split!==split) throw new Error('Invalid saved workflow comparison.');
    return data;
  }
}
