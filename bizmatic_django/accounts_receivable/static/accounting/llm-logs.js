/* Saved accounting LLM history and accuracy reviews. */
(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('finance-config').textContent);
  const root = document.getElementById('finance-root');
  // Keep the active destination visible in the shared horizontal navigation.
  window.addEventListener('load', () => document.fonts.ready.then(() => {
    const nav = document.querySelector('.finance-nav');
    const active = nav?.querySelector('a[aria-current="page"]');
    if (!active) return;
    const reveal = () => { nav.scrollLeft = active.offsetLeft - nav.offsetLeft; };
    reveal();
    // Icon replacement and responsive resizing can change navigation widths.
    const observer = new ResizeObserver(reveal);
    observer.observe(active); observer.observe(nav);
  }), {once:true});
  const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const labels = {customer:'Customer', supplier:'Supplier', purchase_order:'Purchase order', delivery_receipt:'Delivery receipt', sales_invoice:'Sales invoice', payment:'Payment', extraction:'Record extraction', configuration:'Configuration assistance', database:'Database extraction', document:'Document extraction', queued:'Queued', processing:'Processing', completed:'Completed', failed:'Failed'};
  const resourceFor = {customer:'parties',supplier:'parties',purchase_order:'purchase-orders',delivery_receipt:'delivery-receipts',sales_invoice:'invoices',payment:'payments'};
  const relationFor = {customer:'customer',supplier:'supplier',purchase_order:'purchase_order',delivery_receipt:'delivery_receipt',sales_invoice:'sales_invoice',payment:'payment'};
  const link = (href, text, cls = '') => `<a class="${cls}" href="${esc(href)}">${text}</a>`;
  const detailURL = id => config.routes['llm-logs'] + id + '/';
  const localDate = value => value ? new Date(value).toLocaleString('en-GB', {dateStyle:'medium',timeStyle:'short'}) : '—';
  const badge = value => `<span class="finance-status ${({completed:'success',failed:'danger',queued:'warning',processing:'info'})[value] || ''}">${esc(labels[value] || value)}</span>`;
  const card = (title, body, action = '') => `<section class="card mb-3"><div class="finance-card-head"><h2>${esc(title)}</h2>${action}</div>${body}</section>`;
  const api = window.BizmaticAccounting;
  const state = {logs: api.state.logs || []};
  let storageError = '';
  window.BizmaticLLMLogs = {detailURL, configurationURL:id=>config.routes['llm-logs']+'?configuration='+id};
  if (config.resource !== 'llm-logs') return;
  const params = new URLSearchParams(location.search);
  const scope = {
    configuration:params.get('configuration'), target:params.get('target'), record:params.get('record'),
  };
  function scopedRows() {
    return state.logs.filter(row => (!scope.configuration || String(row.configuration) === scope.configuration) && (!scope.target || row.target_entity === scope.target) && (!scope.record || String(row[relationFor[row.target_entity]]) === scope.record));
  }
  const warning = () => storageError ? `<div class="alert alert-warning" role="alert">${esc(storageError)}</div>` : '';
  const notice = '';
  function list() {
    const rows = scopedRows();
    root.innerHTML = `<header class="finance-heading"><div><h1>LLM activity</h1><p>Inspect attempts, original context, output, errors, and your accuracy reviews.</p></div><div class="finance-actions">${link(config.routes.configuration,'Extraction setup','btn btn-falcon-default')}</div></header>${warning()}${notice}${Object.values(scope).some(Boolean)?`<div class="llm-scope">Filtered to ${scope.configuration?'configuration #'+esc(scope.configuration):esc(labels[scope.target] || 'record')+(scope.record?' #'+esc(scope.record):'')}. ${link(config.routes['llm-logs'],'View all activity')}</div>`:''}<div class="finance-kpis">${[['Attempts',rows.length],['Completed',rows.filter(row=>row.status==='completed').length],['Failed',rows.filter(row=>row.status==='failed').length],['Selected as accurate',rows.filter(row=>row.user_selected_accurate).length]].map(([title,count])=>`<div class="card finance-kpi"><div class="kpi-label">${title}</div><div class="kpi-value">${count}</div><div class="kpi-note">Saved attempts</div></div>`).join('')}</div>${card('Attempt history',`<form id="llm-filters" class="finance-toolbar llm-filters"><div><label for="llm-search">Search attempts</label><input class="form-control" id="llm-search" type="search" placeholder="Reference, provider, model, prompt"></div><div><label for="llm-status">Status</label><select class="form-select" id="llm-status"><option value="">All statuses</option>${['queued','processing','completed','failed'].map(value=>`<option value="${value}">${labels[value]}</option>`).join('')}</select></div><div><label for="llm-purpose">Purpose</label><select class="form-select" id="llm-purpose"><option value="">All purposes</option><option value="extraction">Record extraction</option><option value="configuration">Configuration assistance</option></select></div><button class="btn btn-falcon-default align-self-end" type="reset">Clear filters</button></form><div id="llm-table"></div>`)}`;
    const search = root.querySelector('#llm-search'), status = root.querySelector('#llm-status'), purpose = root.querySelector('#llm-purpose');
    search.value = params.get('q') || '';status.value = params.get('status') || '';purpose.value = params.get('purpose') || '';
    const renderRows = () => {
      const query = search.value.trim().toLowerCase();
      const filtered = rows.filter(row => (!status.value || row.status === status.value) && (!purpose.value || row.purpose === purpose.value) && JSON.stringify([row.llm_log_no,row.preview_reference,row.provider,row.model_name,row.request_payload,labels[row.target_entity]]).toLowerCase().includes(query)).sort((a,b) => b.created_at.localeCompare(a.created_at) || b.llm_log_no - a.llm_log_no);
      const next = new URLSearchParams();
      Object.entries({...scope,q:search.value,status:status.value,purpose:purpose.value}).forEach(([key,value])=>{if(value)next.set(key,value);});
      history.replaceState(null,'',config.routes['llm-logs']+(next.size?'?'+next:''));
      root.querySelector('#llm-table').innerHTML = `<div class="llm-count" role="status">${filtered.length} attempt(s)</div><div class="table-responsive"><table class="table finance-table llm-table"><caption class="visually-hidden">LLM attempt history, newest first</caption><thead><tr><th>Attempt / target</th><th>Status</th><th>Provider / model</th><th>Tokens in / out</th><th>Time</th><th>Accuracy review</th></tr></thead><tbody>${filtered.map(row=>`<tr><td>${link(detailURL(row.llm_log_no),'Attempt #'+row.llm_log_no,'primary-link')}<span class="subtext">${esc(row.preview_reference?.record_label || labels[row.target_entity])}</span><span class="subtext">${esc(labels[row.purpose])} · ${localDate(row.created_at)}</span></td><td>${badge(row.status)}</td><td>${esc(row.provider || 'Unavailable')}<span class="subtext">${esc(row.model_name || 'Unavailable')}</span></td><td>${row.input_tokens ?? '—'} / ${row.output_tokens ?? '—'}</td><td>${row.processing_time_ms === null || row.processing_time_ms === undefined?'—':esc(row.processing_time_ms)+' ms'}</td><td>${row.user_selected_accurate?'<span class="finance-status success">Selected as accurate</span>':'Not selected'}</td></tr>`).join('') || '<tr><td colspan="6"><div class="finance-empty"><h2>No attempts in this view</h2><p>Clear the filters or send a message from a configuration assistant to create an attempt.</p></div></td></tr>'}</tbody></table></div>`;
    };
    root.querySelector('#llm-filters').addEventListener('submit',event=>event.preventDefault());
    root.querySelector('#llm-filters').addEventListener('input',renderRows);
    root.querySelector('#llm-filters').addEventListener('change',renderRows);
    root.querySelector('#llm-filters').addEventListener('reset',()=>{search.value='';status.value='';purpose.value='';renderRows();});
    renderRows();
  }
  // Same allowlist approach as document-review.js: discard embedded HTML and images.
  function renderMarkdown(target, value) {
    if (!window.marked) { target.textContent = value; return; }
    const renderer = new marked.Renderer();
    renderer.html = ({text}) => esc(text);
    renderer.image = () => '';
    const parsed = new DOMParser().parseFromString(marked.parse(value, {renderer}), 'text/html');
    const allowed = new Set('P BR H1 H2 H3 H4 H5 H6 STRONG EM DEL CODE PRE UL OL LI TABLE THEAD TBODY TR TH TD BLOCKQUOTE A HR'.split(' '));
    const clean = node => {
      if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.textContent);
      const result = allowed.has(node.nodeName) ? document.createElement(node.nodeName.toLowerCase()) : document.createDocumentFragment();
      if (node.nodeName === 'A') {
        const href = node.getAttribute('href') || '';
        try { if (/^(https?:|mailto:)$/.test(new URL(href, location.href).protocol)) { result.href = href; result.rel = 'noopener noreferrer'; } } catch { /* Invalid links remain text. */ }
      }
      for (const child of node.childNodes) result.append(clean(child));
      return result;
    };
    target.replaceChildren(...[...parsed.body.childNodes].map(clean));
  }
  function detail() {
    const row = state.logs.find(log => log.llm_log_no === config.recordId);
    if (!row) {root.innerHTML = `<div class="finance-empty"><h1>Attempt unavailable</h1><p>This attempt is unavailable.</p>${link(config.routes['llm-logs'],'Back to LLM activity','btn btn-primary')}</div>`;return;}
    const recordId = row[relationFor[row.target_entity]];
    const relation = recordId?link(config.routes[resourceFor[row.target_entity]]+recordId+'/',esc(row.preview_reference?.record_label || labels[row.target_entity]+' #'+recordId)):'Not linked to an accounting record';
    const configuration = row.configuration?link(config.routes.configuration+row.configuration+'/',`Configuration #${row.configuration} · revision ${row.configuration_revision}`):'Not linked';
    const facts = [['Purpose',labels[row.purpose]],['Record type',labels[row.target_entity]],['Source',labels[row.source_type]],['Provider',row.provider || 'Unavailable'],['Model',row.model_name || 'Unavailable'],['Input / output tokens',`${row.input_tokens ?? '—'} / ${row.output_tokens ?? '—'}`],['Processing time',row.processing_time_ms === null || row.processing_time_ms === undefined?'—':row.processing_time_ms+' ms'],['Created',localDate(row.created_at)],['Updated',localDate(row.updated_at)]];
    const output = row.response_payload && Object.keys(row.response_payload).length ? JSON.stringify(row.response_payload,null,2) : row.markdown_text || '';
    const complete = row.status === 'completed' && Boolean(output);
    const disposition = row.review_metadata?.disposition;
    root.innerHTML = `<nav class="finance-breadcrumb" aria-label="Breadcrumb">${link(config.routes['llm-logs'],'LLM activity')}<span aria-hidden="true">/</span><span aria-current="page">Attempt #${row.llm_log_no}</span></nav><header class="finance-heading"><div><h1>LLM attempt #${row.llm_log_no}</h1><p>${esc(labels[row.target_entity])} · ${esc(labels[row.purpose])}</p></div><div class="finance-actions"><button class="btn btn-falcon-default" id="llm-export" type="button">Export attempt JSON</button>${link(config.routes['llm-logs'],'All activity','btn btn-falcon-default')}</div></header>${warning()}${notice}${row.error_message?`<div class="alert alert-danger" role="alert"><strong>Processing error:</strong> ${esc(row.error_message)}</div>`:''}<div class="llm-detail-grid"><div>${card('Attempt output',`<div class="llm-tabs" role="group" aria-label="Attempt output display"><button type="button" data-output="result" class="btn btn-primary btn-sm" aria-pressed="true">Result</button><button type="button" data-output="markdown" class="btn btn-falcon-default btn-sm" aria-pressed="false">Raw Markdown</button><button type="button" data-output="structured" class="btn btn-falcon-default btn-sm" aria-pressed="false">Structured output</button><button type="button" data-output="json" class="btn btn-falcon-default btn-sm" aria-pressed="false">Full log JSON</button></div><div id="llm-rendered" class="llm-rendered" hidden></div><pre id="llm-output" class="llm-json" tabindex="0">${esc(output || (row.status==='failed'?'No output was returned for this failed attempt.':'No output is available for this attempt yet.'))}</pre><div class="finance-card-body border-top"><p class="text-600">Review the result against the source and original context. Selecting accuracy records your review in the database; it does not apply changes or submit a configuration.</p><button class="btn btn-falcon-primary" id="llm-accuracy" type="button" ${complete?'':'disabled'}>${row.user_selected_accurate?'Clear accuracy selection':'Select as accurate'}</button><p class="mt-2 mb-0 text-600" id="llm-review-state" role="status">${row.user_selected_accurate?'Selected as accurate · '+localDate(row.reviewed_at):'Not selected as accurate'}</p>${disposition?`<p class="mt-2 mb-0">Proposal decision: <strong>${esc(disposition)}</strong>${row.review_metadata.applied_paths?.length?' · '+row.review_metadata.applied_paths.length+' change(s) applied':''}</p>`:''}</div>`,badge(row.status))}${card('Original request and context',`<details class="llm-disclosure" open><summary>Request and conversation at attempt time</summary><pre class="llm-json">${esc(JSON.stringify(row.request_payload,null,2))}</pre></details><details class="llm-disclosure"><summary>Configuration snapshot · original inputs</summary><pre class="llm-json">${esc(JSON.stringify(row.configuration_snapshot,null,2))}</pre></details>`)}</div><aside>${card('Extraction details',`<div class="finance-card-body"><dl class="finance-meta vertical">${facts.map(([label,value])=>`<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl></div>`)}${card('Related context',`<div class="finance-card-body"><dl class="finance-meta vertical"><div><dt>Configuration</dt><dd>${configuration}</dd></div><div><dt>Accounting record</dt><dd>${relation}</dd></div><div><dt>Source reference</dt><dd>${esc(row.preview_reference?.source_name || 'Current configuration draft')}</dd></div><div><dt>Original document LLM log</dt><dd>${esc(row.source_llm_log || 'No document OCR log linked')}</dd></div></dl>${row.source_type==='document'?link(config.sources.documents+'?q='+encodeURIComponent(row.preview_reference?.source_name || ''),'Find source in document extraction','btn btn-falcon-default mt-3'):link(config.sources.databases,'Browse database extraction','btn btn-falcon-default mt-3')}</div>`)}</aside></div>`;
    if (row.markdown_text) {
      renderMarkdown(root.querySelector('#llm-rendered'), row.markdown_text);
      root.querySelector('#llm-rendered').hidden = false;
      root.querySelector('#llm-output').hidden = true;
    }
    root.querySelectorAll('[data-output]').forEach(button=>button.addEventListener('click',()=>{
      const selected = button.dataset.output;
      const rendered = root.querySelector('#llm-rendered');
      const raw = root.querySelector('#llm-output');
      rendered.hidden = selected!=='result' || !row.markdown_text;
      raw.hidden = !rendered.hidden;
      raw.textContent = selected==='json'?JSON.stringify(row,null,2):selected==='markdown'?row.markdown_text || 'No Markdown was returned for this attempt.':output || 'No output is available for this attempt.';
      root.querySelectorAll('[data-output]').forEach(tab=>{tab.setAttribute('aria-pressed',String(tab===button));tab.classList.toggle('btn-primary',tab===button);tab.classList.toggle('btn-falcon-default',tab!==button);});
    }));
    root.querySelector('#llm-accuracy').addEventListener('click', async () => {
      if (!complete) return;
      try { const result=await api.post('accuracy', row.llm_log_no, {revision:row.revision,accurate:!row.user_selected_accurate}); Object.assign(row,result.record); detail(); }
      catch(error) { storageError=error.message; detail(); }
    });
    root.querySelector('#llm-export').addEventListener('click',()=>{
      const href = URL.createObjectURL(new Blob([JSON.stringify({model:`${config.mode==='ar'?'accounts_receivable':'accounts_payable'}.LLMExtractionLog`,log:row},null,2)],{type:'application/json'}));
      const anchor = document.createElement('a');anchor.href=href;anchor.download=`${config.mode}-llm-attempt-${row.llm_log_no}.json`;anchor.click();URL.revokeObjectURL(href);
    });
  }
  if (config.screen === 'detail') detail(); else list();
})();
