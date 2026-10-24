/* Accounting workspace: saved records and explicit server actions. */
(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('finance-config').textContent);
  if (['configuration', 'llm-logs'].includes(config.resource)) return;
  const root = document.getElementById('finance-root');
  const reportCurrency = new URLSearchParams(location.search).get('currency') || 'PHP';
  const ar = config.mode === 'ar';
  const resource = config.resource;
  const extractionOnly = ['purchase-orders', 'delivery-receipts', 'invoices', 'payments'].includes(resource);
  const api = window.BizmaticAccounting;
  const data = api.state;
  const moneyCurrency = data[resource]?.find(row=>row.id===config.recordId)?.currency || reportCurrency;
  const today = new Date(data.today + 'T00:00:00');
  const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const icon = name => `<span class="fas fa-${name}" aria-hidden="true"></span>`;
  const money = value => Number(value || 0).toLocaleString('en-PH', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const compact = value => Number(value || 0).toLocaleString('en-PH', {maximumFractionDigits: 0});
  const label = value => String(value || '').replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase());
  const date = value => value ? new Date(`${value.slice(0, 10)}T00:00:00`).toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric'}) : '—';
  const find = (kind, id) => data[kind]?.find(row => row.id === Number(id));
  const party = record => find('parties', record.partyId);
  const partyName = record => party(record)?.name || 'Unassigned';
  const url = (kind, id = '', suffix = '') => `${config.routes[kind]}${id ? `${id}/` : ''}${suffix ? `${suffix}/` : ''}`;
  const a = (href, text, cls = '') => `<a class="${cls}" href="${esc(href)}">${text}</a>`;
  const button = (href, text, primary = false, symbol = '') => a(href, `${symbol ? icon(symbol) : ''}${text}`, `btn ${primary ? 'btn-primary' : 'btn-falcon-default'}`);
  const badge = status => {
    const tone = ['paid','cleared','matched','active','accepted','delivered','closed'].includes(status) ? 'success' : ['exception','disputed','rejected','reversed','overdue','void'].includes(status) ? 'danger' : ['partial','partially_paid','partially_accepted','pending','unpaid'].includes(status) ? 'warning' : status === 'open' || status === 'posted' ? 'info' : '';
    return `<span class="finance-status ${tone}">${esc(label(status))}</span>`;
  };
  const sourceLabel = source => ({document:'Document extraction', database:'Database extraction'}[source] || 'Source unavailable');
  const sourceBadge = source => `<span class="finance-source">${icon(source === 'database' ? 'database' : 'file-alt')}${sourceLabel(source)}</span>`;
  const titles = {parties: `${config.party}s`, 'purchase-orders': 'Purchase orders', 'delivery-receipts': 'Delivery receipts', invoices: 'Invoices', payments: 'Payments', reconciliation: 'Reconciliation', aging: 'Aging report'};
  const singulars = {parties: config.party.toLowerCase(), 'purchase-orders': 'purchase order', 'delivery-receipts': 'delivery receipt', invoices: 'invoice', payments: 'payment', reconciliation: 'reconciliation case'};
  const statuses = {
    parties: ['active','inactive'], 'purchase-orders': ['draft','open','cancelled','closed'],
    'delivery-receipts': ar ? ['pending','delivered','partially_accepted','rejected'] : ['pending','partial','accepted','rejected'],
    invoices: ['unpaid','partially_paid','paid'], payments: ['pending','cleared','reversed'], reconciliation: ['pending','partial','matched','exception'],
  };
  function toast(text) {
    const element = document.getElementById('finance-toast');
    element.textContent = text; element.hidden = false;
    setTimeout(() => { element.hidden = true; }, 4500);
  }
  function showError(text) {
    let element = document.getElementById('form-error');
    if (!element) { root.insertAdjacentHTML('afterbegin', '<div id="form-error" class="finance-form-error" role="alert" tabindex="-1"></div>'); element = document.getElementById('form-error'); }
    element.hidden = false; element.textContent = text; element.focus(); element.scrollIntoView({block:'center'});
  }
  const settled = invoice => invoice.settled;
  const balance = invoice => invoice.balance;
  const invoiceStatus = invoice => settled(invoice) >= invoice.amount && invoice.amount > 0 ? 'paid' : settled(invoice) > 0 ? 'partially_paid' : 'unpaid';
  const posted = invoice => !['draft','pending','void'].includes(invoice.invoiceStatus);
  const overdueDays = invoice => Math.max(0, Math.round((today - new Date(`${invoice.dueDate}T00:00:00`)) / 86400000));
  const outstanding = () => data.invoices.filter(invoice => invoice.currency===reportCurrency && posted(invoice) && balance(invoice) > 0);
  const available = (payment, component = 'cash') => Math.max(0, (component === 'cash' ? payment.amount : component === 'withholding' ? payment.withholding : payment.discountTaken) - data.allocations.filter(row => row.paymentId === payment.id).reduce((sum,row) => sum + row[component],0));
  const total = (rows, fn) => rows.reduce((sum, row) => sum + fn(row), 0);
  const statusOf = row => resource === 'invoices' ? invoiceStatus(row) : row.status;
  const breadcrumb = text => `<nav class="finance-breadcrumb" aria-label="Breadcrumb">${a(url('overview'), esc(config.title))}${icon('chevron-right')}${resource !== 'overview' ? a(url(resource), esc(titles[resource])) : ''}${text ? `${icon('chevron-right')}<span aria-current="page">${esc(text)}</span>` : ''}</nav>`;
  const heading = (title, description, actions = '') => `<header class="finance-heading"><div><h1>${esc(title)}</h1><p>${description}</p></div><div class="finance-actions">${actions}</div></header>`;
  const card = (title, body, action = '', subtitle = '') => `<section class="card mb-4"><div class="finance-card-head"><div><h2>${title}</h2>${subtitle ? `<div class="finance-card-subtitle">${subtitle}</div>` : ''}</div>${action}</div>${body}</section>`;
  const meta = (items, vertical = false) => `<dl class="finance-meta ${vertical ? 'vertical' : ''}">${items.map(([name,value]) => `<div><dt>${esc(name)}</dt><dd>${value}</dd></div>`).join('')}</dl>`;
  const kpi = (name, value, note, symbol, monetary = false) => `<div class="card finance-kpi"><div class="kpi-label">${esc(name)}${icon(symbol)}</div><div class="kpi-value">${monetary ? `<small>${esc(moneyCurrency)}</small>` : ''}${esc(value)}</div><div class="kpi-note">${esc(note)}</div></div>`;
  const empty = (title, description, action = '') => `<div class="finance-empty"><span class="empty-icon">${icon('search')}</span><h2>${esc(title)}</h2><p>${esc(description)}</p>${action}</div>`;

  function extractionActions() {
    return button(config.routes.configuration, 'Configure extraction', false, 'sliders-h') +
      button(config.sources.documents, 'Document extraction', true, 'file-alt') +
      button(config.sources.databases, 'Database extraction', false, 'database');
  }
  function extractionNotice() {
    return `<div class="finance-callout"><strong>Records from extraction</strong><div class="mt-1">Purchase orders, delivery receipts, sales invoices, and payments come from database extraction or document extraction. Review their source and extraction history to check record details. Retries do not overwrite existing accounting records.</div></div>`;
  }
  function sourceURL(record) {
    return record.sourceUrl || config.sources.documents;
  }

  function agingGroups() {
    return ['Current','1–30 days','31–60 days','61–90 days','90+ days'].map((name, index) => {
      const rows = outstanding().filter(invoice => { const days = overdueDays(invoice); return index === 0 ? days === 0 : index === 1 ? days > 0 && days <= 30 : index === 2 ? days > 30 && days <= 60 : index === 3 ? days > 60 && days <= 90 : days > 90; });
      return {name, rows, amount: total(rows, balance), color: ['#2c7be5','#75a9ed','#e4b546','#e88b49','#d45c68'][index]};
    });
  }
  function invoiceTable(rows, caption = 'Invoices') {
    return `<div class="table-responsive"><table class="table finance-table finance-invoice-summary"><caption class="visually-hidden">${esc(caption)}</caption><thead><tr><th>Invoice / ${config.party.toLowerCase()}</th><th>Due date</th><th>Payment status</th><th class="text-end">Outstanding (${esc(reportCurrency)})</th></tr></thead><tbody>${rows.map(row => `<tr><td>${a(url('invoices',row.id),esc(row.reference),'primary-link')}<span class="subtext">${esc(partyName(row))}</span></td><td>${date(row.dueDate)}${posted(row) && balance(row)>0 && overdueDays(row) ? `<span class="subtext text-danger">${overdueDays(row)} days overdue</span>` : ''}</td><td>${badge(invoiceStatus(row))}</td><td class="amount fw-semibold">${money(balance(row))}</td></tr>`).join('') || `<tr><td colspan="4">${empty('All caught up', 'No outstanding invoices in this view.')}</td></tr>`}</tbody></table></div>`;
  }
  function overview() {
    const open = outstanding();
    const late = open.filter(row => overdueDays(row) > 0);
    const exceptions = data.reconciliation.filter(row => row.status === 'exception');
    const unallocated = total(data.payments.filter(row => row.status !== 'reversed' && row.currency===reportCurrency), row => available(row));
    root.innerHTML = heading(config.title, ar ? 'Keep collections moving, from customer orders to the final payment.' : 'Know what you owe, resolve discrepancies, and prepare supplier payments.', extractionActions()) +
      `<div class="finance-kpis">${kpi(ar ? 'Total receivables' : 'Total payables', compact(total(open,balance)), `${open.length} open invoices · ${esc(reportCurrency)} only`, 'wallet', true)}${kpi('Overdue balance',compact(total(late,balance)),`${late.length} invoices need attention`,'clock',true)}${kpi(ar ? 'Unallocated receipts' : 'Unallocated payments',compact(unallocated),'Cash available across non-reversed payments','credit-card',true)}${kpi('Matching exceptions',exceptions.length,'Cases with document discrepancies','exclamation-triangle')}</div>` +
      `<div class="finance-grid">${card(ar ? 'Collection priorities' : 'Payment priorities', invoiceTable([...open].sort((a,b) => a.dueDate.localeCompare(b.dueDate)).slice(0,5)), a(url('invoices')+'?status=unpaid','View invoices '+icon('arrow-right')), 'Outstanding invoices, earliest due first')}
      <div>${card('Aging at a glance',`<div class="finance-card-body">${agingGroups().map(group => `<div class="finance-aging-row"><span>${group.name}</span><div class="finance-aging-bar"><span style="width:${total(open,balance) ? group.amount / total(open,balance) * 100 : 0}%;background:${group.color}"></span></div><strong class="text-end">${money(group.amount)}</strong></div>`).join('')}<p class="text-600 fs-11 mb-0 mt-3">Outstanding ${esc(reportCurrency)} · As of ${date(data.today)}</p></div>`,a(url('aging'),'Full report '+icon('arrow-right')))}
      ${card('Needs attention',`<div class="finance-card-body pt-0">${[
        [icon('exclamation-triangle'), `${exceptions.length} matching ${exceptions.length === 1 ? 'exception' : 'exceptions'}`, 'Compare ordered, accepted, and billed quantities.',url('reconciliation')+'?status=exception'],
        [icon('credit-card'),`${data.payments.filter(row => row.status === 'pending').length} pending payments`,'Pending payments do not reduce invoice balances.',url('payments')+'?status=pending'],
        [icon('file-import'),'Bring in source records','Review uploaded files or browse database metadata.',config.sources.documents],
      ].map(([symbol,title,description,href]) => `<div class="finance-attention"><span class="attention-icon">${symbol}</span><div>${a(href,esc(title),'fw-semibold')}<p>${description}</p></div></div>`).join('')}</div>`)}</div></div>` +
      card('Follow the document trail',`<div class="finance-card-body"><div class="finance-process">${[['purchase-orders','shopping-cart',ar ? 'Customer orders' : 'Company orders','Agreed quantities & prices'],['delivery-receipts','truck',ar ? 'Company deliveries' : 'Supplier deliveries','Received & accepted items'],['invoices','file-invoice-dollar',ar ? 'Sales invoices' : 'Supplier invoices','Billed amounts & balances'],['payments','credit-card',ar ? 'Customer receipts' : 'Company payments','Cash, tax & allocations']].map(([key,symbol,title,subtitle]) => a(url(key),`<span class="process-icon">${icon(symbol)}</span><div><strong>${title}</strong><small>${subtitle}</small></div>`)).join('')}</div></div>`) +
      `<div class="finance-grid equal">${card('Document extraction',`<div class="finance-card-body"><p class="text-600">Start with purchase orders, delivery receipts, invoices, and payment evidence.</p>${button(config.sources.documents,'Browse documents',false,'file-alt')} ${button(config.sources.upload,'Upload documents',false,'cloud-upload-alt')}</div>`)}${card('Database extraction',`<div class="finance-card-body"><p class="text-600">Inspect connections, tables, and source metadata for accounting imports.</p>${button(config.sources.databases,'Browse connections',false,'database')}<p class="text-600 fs-11 mt-3 mb-0">Use a submitted database configuration in Extraction setup to import records.</p></div>`)}</div>`;
  }

  let filters = new URLSearchParams(location.search);
  let page = Math.max(1, Number(filters.get('page')) || 1);
  const pageSize = 8;
  function filteredRows() {
    const query = (filters.get('q') || '').toLowerCase();
    let rows = data[resource].filter(row => {
      const search = `${row.reference} ${row.name || ''} ${row.email || ''} ${partyName(row)}`.toLowerCase();
      return (!query || search.includes(query)) && (!filters.get('status') || statusOf(row) === filters.get('status')) && (!filters.get('source') || row.source === filters.get('source')) && (!filters.get('party') || row.partyId === Number(filters.get('party')));
    });
    const sort = filters.get('sort') || 'date';
    const direction = filters.get('direction') === 'asc' ? 1 : -1;
    rows.sort((a,b) => {
      const first = sort === 'party' ? (a.name || partyName(a)) : sort === 'amount' ? (a.amount || 0) : sort === 'balance' ? balance(a) : a[sort] || '';
      const second = sort === 'party' ? (b.name || partyName(b)) : sort === 'amount' ? (b.amount || 0) : sort === 'balance' ? balance(b) : b[sort] || '';
      return (typeof first === 'number' ? first - second : String(first).localeCompare(String(second))) * direction;
    });
    return rows;
  }
  function updateQuery(key, value) {
    if (value) filters.set(key,value); else filters.delete(key);
    if (key !== 'page') { page = 1; filters.delete('page'); }
    history.replaceState(null,'',`${location.pathname}${filters.size ? '?' + filters.toString() : ''}`);
  }
  function tableHeaders() {
    const sort = (name,key,cls='') => `<th class="${cls}" scope="col" aria-sort="${(filters.get('sort') || 'date') === key ? filters.get('direction') === 'asc' ? 'ascending' : 'descending' : 'none'}"><button data-sort="${key}" type="button">${name} ${icon('sort')}</button></th>`;
    if (resource === 'parties') return `${sort(config.party,'party')}<th>Contact</th><th>Terms</th><th>Status</th><th class="text-end">Open balance (${esc(reportCurrency)})</th><th></th>`;
    if (resource === 'reconciliation') return `${sort('Case / '+config.party,'reference')}<th>Documents</th><th>Status</th><th class="text-end">Discrepancy</th><th></th>`;
    return `${sort('Reference / '+config.party,'reference')}${sort(resource === 'invoices' ? 'Due date' : 'Date',resource === 'invoices' ? 'dueDate' : 'date')}<th>${resource === 'invoices' ? 'Invoice / payment' : 'Status'}</th><th>Source</th>${resource === 'delivery-receipts' ? '<th class="text-end">Accepted / received</th>' : sort('Amount','amount','text-end')}${resource === 'invoices' ? sort('Outstanding','balance','text-end') : ''}<th></th>`;
  }
  function recordRow(row) {
    const primary = `${a(url(resource,row.id),esc(resource === 'parties' ? row.name : row.reference),'primary-link')}<span class="subtext">${esc(resource === 'parties' ? row.reference : partyName(row))}</span>`;
    if (resource === 'parties') return `<td>${primary}</td><td>${esc(row.contact)}<span class="subtext">${esc(row.email)}</span></td><td>Net ${row.terms} days</td><td>${badge(row.status)}</td><td class="amount">${money(total(outstanding().filter(invoice => invoice.partyId === row.id),balance))}</td><td>${a(url(resource,row.id),icon('chevron-right')+`<span class="visually-hidden">View ${esc(row.name)}</span>`)}</td>`;
    if (resource === 'reconciliation') return `<td>${primary}</td><td>${row.orderIds.length} PO · ${row.receiptIds.length} DR · ${row.invoiceIds.length} INV</td><td>${badge(row.status)}</td><td class="amount ${row.discrepancy > 0 ? 'text-danger' : ''}">${esc(row.currency)} ${money(row.discrepancy)}</td><td>${a(url(resource,row.id), 'Review '+icon('arrow-right'))}</td>`;
    return `<td>${primary}</td><td>${date(resource === 'invoices' ? row.dueDate : row.date)}${resource === 'invoices' && posted(row) && balance(row)>0 && overdueDays(row)>0 ? `<span class="subtext text-danger">${overdueDays(row)} days overdue</span>` : ''}</td><td>${resource === 'invoices' ? `${badge(row.invoiceStatus)}<div class="mt-1">${badge(invoiceStatus(row))}</div>` : badge(row.status)}</td><td>${sourceBadge(row.source)}</td><td class="amount">${resource === 'delivery-receipts' ? `${total(row.lines,line=>line.accepted)} / ${total(row.lines,line=>line.received)}` : esc(row.currency)+' '+money(row.amount)}</td>${resource === 'invoices' ? `<td class="amount fw-semibold">${money(balance(row))}</td>` : ''}<td>${a(url(resource,row.id),icon('chevron-right')+`<span class="visually-hidden">View ${esc(row.reference)}</span>`)}</td>`;
  }
  function renderRegisterTable() {
    const rows = filteredRows();
    page = Math.min(page, Math.max(1,Math.ceil(rows.length/pageSize)));
    const slice = rows.slice((page-1)*pageSize,page*pageSize);
    document.getElementById('register-table').innerHTML = rows.length ? `<div class="table-responsive"><table class="table finance-table"><caption class="visually-hidden">${esc(titles[resource])} · Saved records</caption><thead><tr>${tableHeaders()}</tr></thead><tbody>${slice.map(row=>`<tr>${recordRow(row)}</tr>`).join('')}</tbody></table></div><div class="finance-pagination"><span>${(page-1)*pageSize+1}–${Math.min(page*pageSize,rows.length)} of ${rows.length} records</span><div class="finance-actions"><button class="btn btn-falcon-default" type="button" data-page="${page-1}" ${page===1?'disabled':''}>${icon('chevron-left')} Previous</button><span>Page ${page} of ${Math.ceil(rows.length/pageSize)}</span><button class="btn btn-falcon-default" type="button" data-page="${page+1}" ${page*pageSize>=rows.length?'disabled':''}>Next ${icon('chevron-right')}</button></div></div>` : extractionOnly && !data[resource].length ? empty('No extracted '+titles[resource].toLowerCase(),'Review document or database extraction to populate this register.',`<div class="finance-actions justify-content-center">${extractionActions()}</div>`) : empty('No matching records','Try a different search or clear your filters.',`<button class="btn btn-falcon-default" type="button" data-clear>Clear filters</button>`);
    document.getElementById('record-count').textContent = rows.length;
    document.querySelectorAll('[data-status-tab]').forEach(tab=>{ const active=tab.dataset.statusTab===(filters.get('status') || ''); tab.classList.toggle('active',active); tab.setAttribute('aria-pressed',String(active)); });
  }
  function register() {
    const descriptions = {
      parties: ar ? 'Customer contacts, credit limits, terms, and open receivables.' : 'Supplier contacts, payment terms, and outstanding obligations.',
      'purchase-orders': ar ? 'Orders placed by customers, with agreed quantities and prices.' : 'Orders your company places with suppliers, including tax and other charges.',
      'delivery-receipts': ar ? 'Track deliveries to customers and the quantities they accepted.' : 'Review goods received from suppliers and any receiving discrepancies.',
      invoices: ar ? 'Company sales invoices, due dates, and payment allocations.' : 'Supplier invoices, due dates, and payment allocations.',
      payments: ar ? 'Customer receipts, clearing status, and unallocated balances.' : 'Company payments, clearing status, and unallocated balances.',
      reconciliation: 'Compare purchase orders, accepted deliveries, and invoice lines in one case.',
    };
    root.innerHTML = heading(titles[resource],descriptions[resource],`<button class="btn btn-falcon-default" id="export-csv" type="button">${icon('download')} Export</button>${extractionOnly ? extractionActions() : button(url(resource,'','new'),`New ${singulars[resource]}`,true,'plus')}`)+
      (extractionOnly ? extractionNotice() : '')+
      `<section class="card"><div class="finance-card-head"><h2>All ${titles[resource].toLowerCase()} <span class="badge badge-subtle-secondary ms-2" id="record-count"></span></h2><span class="text-600 fs-11">${resource==='parties' ? 'Account directory' : extractionOnly ? 'Extracted records' : 'Saved records'}</span></div>`+
      `<div class="finance-tabs" role="group" aria-label="Filter by status">${['',...statuses[resource]].map(status=>`<button type="button" data-status-tab="${status}" class="${(filters.get('status') || '')===status?'active':''}" aria-pressed="${(filters.get('status') || '')===status}">${status ? label(status) : 'All records'}</button>`).join('')}</div>`+
      `<form class="finance-toolbar" id="register-filters" role="search"><div class="finance-search"><label class="visually-hidden" for="register-search">Search ${titles[resource].toLowerCase()}</label><input type="search" id="register-search" class="form-control" placeholder="Search reference or ${resource==='parties'?'name':config.party.toLowerCase()}…" value="${esc(filters.get('q') || '')}"></div>${resource!=='parties'?`<label class="visually-hidden" for="party-filter">${config.party}</label><select class="form-select" id="party-filter"><option value="">All ${config.party.toLowerCase()}s</option>${data.parties.map(row=>`<option value="${row.id}" ${Number(filters.get('party'))===row.id?'selected':''}>${esc(row.name)}</option>`).join('')}</select>`:''}${!['parties','reconciliation'].includes(resource)?`<label class="visually-hidden" for="source-filter">Source</label><select class="form-select" id="source-filter"><option value="">All sources</option>${['document','database'].map(source=>`<option value="${source}" ${filters.get('source')===source?'selected':''}>${sourceLabel(source)}</option>`).join('')}</select>`:''}<button class="btn btn-link" type="button" data-clear>Clear filters</button></form><div id="register-table"></div></section>`;
    renderRegisterTable();
    root.querySelector('#register-filters').addEventListener('submit',event=>event.preventDefault());
    root.querySelector('#register-search').addEventListener('input',event=>{updateQuery('q',event.target.value);renderRegisterTable();});
    root.querySelector('#party-filter')?.addEventListener('change',event=>{updateQuery('party',event.target.value);renderRegisterTable();});
    root.querySelector('#source-filter')?.addEventListener('change',event=>{updateQuery('source',event.target.value);renderRegisterTable();});
    root.addEventListener('click',registerClick);
    root.querySelector('#export-csv').addEventListener('click',()=>exportCSV(filteredRows()));
  }
  function registerClick(event) {
    const tab = event.target.closest('[data-status-tab]');
    const sort = event.target.closest('[data-sort]');
    const paging = event.target.closest('[data-page]');
    if (tab) {updateQuery('status',tab.dataset.statusTab);renderRegisterTable();}
    if (sort) {const key=sort.dataset.sort;const direction=filters.get('sort')===key && filters.get('direction')==='asc'?'desc':'asc';updateQuery('sort',key);updateQuery('direction',direction);renderRegisterTable();}
    if (paging) {page=Number(paging.dataset.page);updateQuery('page',String(page));renderRegisterTable();}
    if (event.target.closest('[data-clear]')) {filters=new URLSearchParams();page=1;history.replaceState(null,'',location.pathname);root.removeEventListener('click',registerClick);register();}
  }
  function exportCSV(rows) {
    const values = [['Reference',config.party,'Status','Currency','Amount','Outstanding'],...rows.map(row=>[row.reference,row.name || partyName(row),statusOf(row),row.currency || '',row.amount || '',resource==='invoices'?balance(row):''])];
    const csv=values.map(row=>row.map(value=>`"${String(value).replace(/^[=+@-]/,"'$&").replaceAll('"','""')}"`).join(',')).join('\r\n');
    const href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8;'}));const link=document.createElement('a');link.href=href;link.download=`${config.mode}-${resource}.csv`;link.click();URL.revokeObjectURL(href);toast('Filtered records exported.');
  }

  function linesTable(record) {
    const receipt=resource==='delivery-receipts';
    return `<div class="table-responsive"><table class="table finance-table"><caption class="visually-hidden">${receipt?'Delivery quantities':'Document line items'}</caption><thead><tr><th>Item</th><th>Unit</th><th class="text-end">${receipt?'Stated':'Quantity'}</th>${receipt?'<th class="text-end">Received</th><th class="text-end">Accepted</th><th class="text-end">Rejected</th>':'<th class="text-end">Unit price</th><th class="text-end">Discount</th><th class="text-end">Tax</th><th class="text-end">Total</th>'}</tr></thead><tbody>${record.lines.map(line=>`<tr><td><strong>${esc(line.code)}</strong><span class="subtext">${esc(line.description)}</span></td><td>${esc(line.unit)}</td><td class="amount">${line.quantity}</td>${receipt?`<td class="amount">${line.received}</td><td class="amount">${line.accepted}</td><td class="amount ${line.rejected>0?'text-danger':''}">${line.rejected}</td>`:`<td class="amount">${money(line.price)}</td><td class="amount">${money(line.discount)}</td><td class="amount">${money(line.tax)}</td><td class="amount">${money(line.total)}</td>`}</tr>`).join('')}</tbody></table></div>`;
  }
  function totals(record) {
    return `<dl class="finance-totals"><div><dt>Subtotal</dt><dd>${money(record.subtotal)}</dd></div><div><dt>Discount</dt><dd>−${money(record.discount)}</dd></div><div><dt>Tax</dt><dd>${money(record.tax)}</dd></div>${!ar?`<div><dt>Other charges</dt><dd>${money(record.otherCharges)}</dd></div>`:''}<div class="grand"><dt>Total ${esc(record.currency)}</dt><dd>${money(record.amount)}</dd></div>${resource==='invoices'&&config.screen!=='form'?`<div><dt>Settled</dt><dd>${money(settled(record))}</dd></div><div class="grand"><dt>Outstanding ${esc(record.currency)}</dt><dd>${money(balance(record))}</dd></div>`:''}</dl>`;
  }
  function provenance(record) {
    const file=record.sourceName || `${record.reference}.pdf`;
    const documentURL=record.sourceUrl || config.sources.documents;
    let body;
    if (record.source==='database') body=meta([['Connection',esc(record.databaseName)],['Source table',`<code>${esc(record.sourceName)}</code>`],['Source record key',`<code>${esc(record.sourceKey)}</code>`],['Imported at',esc(record.importedAt || 'Not imported')]],true)+`<div class="mt-3">${button(config.sources.databases,'Browse database sources',false,'database')}</div>`;
    else if(record.source==='document') body=meta([['Source document',esc(file)],['Text extraction',esc(record.textLog || 'No extraction selected')],['LLM extraction',esc(record.llmLog || 'No extraction selected')],['Imported at',esc(record.importedAt || 'Not imported')]],true)+`<div class="mt-3">${button(documentURL,'Find source document',false,'file-alt')}</div>`;
    else body='<p class="text-600 mb-0">Source unavailable. Review the extraction workspace.</p>';
    return card('Source & provenance',`<div class="finance-card-body">${sourceBadge(record.source)}<div class="mt-3">${body}</div><div class="mt-3">${button(config.routes['llm-logs']+'?target='+({"purchase-orders":"purchase_order","delivery-receipts":"delivery_receipt",invoices:"sales_invoice",payments:"payment"}[resource])+'&record='+record.id,'View LLM attempts',false,'history')}</div><p class="fs-11 text-600 mt-3 mb-0">Source links identify the saved document or database connection used for this record.</p></div>`);
  }
  function relatedCases(record) {
    const key=resource==='purchase-orders'?'orderIds':resource==='delivery-receipts'?'receiptIds':'invoiceIds';
    const cases=data.reconciliation.filter(row=>row[key]?.includes(record.id));
    return card('Reconciliation cases',`<div class="finance-card-body">${cases.length?cases.map(row=>`<div class="d-flex justify-content-between gap-3 mb-2">${a(url('reconciliation',row.id),esc(row.reference),'fw-semibold')}${badge(row.status)}</div>`).join(''):'<p class="text-600 mb-0">This document is not linked to a case.</p>'}</div>`);
  }
  function allocationsTable(rows, paymentView=false) {
    return `<div class="table-responsive"><table class="table finance-table"><caption class="visually-hidden">Invoice payment allocations</caption><thead><tr><th>${paymentView?'Invoice':'Payment'}</th><th>Status</th><th class="text-end">Cash</th><th class="text-end">Withholding</th><th class="text-end">Discount</th><th class="text-end">Total</th></tr></thead><tbody>${rows.map(row=>{const record=find(paymentView?'invoices':'payments',paymentView?row.invoiceId:row.paymentId);const payment=find('payments',row.paymentId);return `<tr><td>${a(url(paymentView?'invoices':'payments',record.id),esc(record.reference),'primary-link')}</td><td>${badge(payment.status)}</td><td class="amount">${money(row.cash)}</td><td class="amount">${money(row.withholding)}</td><td class="amount">${money(row.discount)}</td><td class="amount">${money(row.cash+row.withholding+row.discount)}</td></tr>`;}).join('') || '<tr><td colspan="6" class="text-center p-4 text-600">No allocations yet. Allocate a payment to link it to an invoice.</td></tr>'}</tbody></table></div>`;
  }
  function detail(record) {
    let actions=extractionOnly ? button(sourceURL(record),record.source==='database'?'View database source':'View source document',false,record.source==='database'?'database':'file-alt') : button(url(resource,record.id,'edit'),'Edit details',false,'pen');
    if(resource==='payments' && record.status!=='reversed') actions+=button(url(resource,record.id,'allocate'),'Allocate payment',true,'link');
    if(resource==='reconciliation') actions+=button(url(resource,record.id,'match'),'Match line items',true,'check-double');
    if(resource==='invoices') actions+=button(url('payments')+'?party='+record.partyId,'View payments',true,'credit-card');
    root.innerHTML=breadcrumb(record.reference)+heading(resource==='parties'?record.name:record.reference,`${label(singulars[resource])} ${resource==='parties'?'· '+esc(record.reference):'· '+a(url('parties',record.partyId),esc(partyName(record)))}`,actions);
    if(extractionOnly) root.insertAdjacentHTML('beforeend',extractionNotice());
    if(resource==='parties') return partyDetail(record);
    if(resource==='reconciliation') return caseDetail(record);
    const isInvoice=resource==='invoices';const isPayment=resource==='payments';const isReceipt=resource==='delivery-receipts';
    const fields=[[config.party,a(url('parties',record.partyId),esc(partyName(record)))],['Date',date(record.date)],['Currency',esc(record.currency || '—')],['Status',badge(isInvoice?record.invoiceStatus:record.status)]];
    if(isInvoice) fields.push(['Due date',date(record.dueDate)],['Payment status',badge(invoiceStatus(record))]);
    if(resource==='purchase-orders') fields.push(['Expected delivery',date(record.expectedDate)]);
    if(isReceipt) fields.push(['Received by',esc(record.receivedBy)],['Received date',date(record.receivedDate)], [ar?'Delivery address':'Delivery location',esc(record.location)]);
    if(isPayment) fields.push(['Payment method',esc(record.method)],['Bank reference',esc(record.bankReference)],['Posting date',date(record.postingDate)],['Cleared at',esc(record.clearedAt || '—')],['Reversed at',esc(record.reversedAt || '—')]);
    let main=card('Record details',`<div class="finance-card-body">${meta(fields)}</div>`);
    if(isPayment) {
      main+=`<div class="finance-kpis" style="grid-template-columns:repeat(2,minmax(0,1fr))">${kpi(ar?'Cash received':'Cash paid',compact(record.amount),'Payment cash amount','credit-card',true)}${kpi('Unallocated cash',compact(available(record)),'Available for invoice allocation','link',true)}</div>`;
      if(record.status!=='cleared') main+=`<div class="finance-callout warning">${record.status==='reversed'?'Reversed payments do not settle invoices. '+esc(record.reversalReason):'This payment is pending. Its allocations will not reduce invoice balances until it is cleared.'}</div>`;
      main+=card('Invoice allocations',allocationsTable(data.allocations.filter(row=>row.paymentId===record.id),true));
    } else {
      main+=card(isReceipt?'Delivery quantities':'Line items',linesTable(record)+(isReceipt?'':totals(record)));
      if(isInvoice) main+=card('Payment allocations',allocationsTable(data.allocations.filter(row=>row.invoiceId===record.id)),a(url('payments')+'?party='+record.partyId,'View payments'));
    }
    main+=card('Notes',`<div class="finance-card-body text-600">${esc(record.notes || 'No notes added.')}</div>`);
    const evidence='';
    root.insertAdjacentHTML('beforeend',`<div class="finance-grid"><div>${main}</div><aside>${provenance(record)}${!isPayment?relatedCases(record):''}${evidence}</aside></div>`);
  }
  function partyDetail(record) {
    root.insertAdjacentHTML('beforeend', `<div class="finance-actions mb-3">${button(config.routes['llm-logs']+'?target='+(ar?'customer':'supplier')+'&record='+record.id,'View LLM attempts',false,'history')}</div>`);
    const invoices=data.invoices.filter(row=>row.partyId===record.id && row.currency===reportCurrency);
    root.insertAdjacentHTML('beforeend',`<div class="finance-grid"><div>${card('Account information',`<div class="finance-card-body">${meta([['Status',badge(record.status)],['Contact person',esc(record.contact)],['Email',esc(record.email)],['Phone',esc(record.phone)],['Tax identification no.',esc(record.taxId)],['Payment terms',`Net ${record.terms} days`],['Billing address',esc(record.address)],...(ar?[['Shipping address',esc(record.shippingAddress)],['Credit limit',`PHP ${money(record.creditLimit)}`]]:[])])}</div>`)}${card('Invoices',invoiceTable(invoices),a(url('invoices')+'?party='+record.id,'View all invoices'))}${card('Context & notes',`<div class="finance-card-body text-600">${esc(record.notes || 'No context added.')}</div>`)}</div><aside>${card('Account balance',`<div class="finance-card-body"><div class="fs-6 fw-semibold mb-2">${esc(reportCurrency)} ${money(total(invoices.filter(posted),balance))}</div><p class="text-600">Outstanding across posted or disputed invoices.</p>${button(url('invoices')+'?party='+record.id,'View invoices',true)}</div>`)}${card('Related records',`<div class="finance-card-body d-flex flex-column gap-3">${['purchase-orders','delivery-receipts','payments','reconciliation'].map(key=>a(url(key)+'?party='+record.id,`${titles[key]} <span class="float-end">${data[key].filter(row=>row.partyId===record.id).length} ${icon('arrow-right')}</span>`)).join('')}</div>`)}</aside></div>`);
  }
  function caseDetail(record) {
    const docs=[['purchase-orders','orderIds','Purchase orders'],['delivery-receipts','receiptIds','Delivery receipts'],['invoices','invoiceIds','Invoices']];
    root.insertAdjacentHTML('beforeend',`<div class="finance-kpis">${kpi('Reconciliation',label(record.status),'Document matching status','check-double')}${kpi('Discrepancy',compact(record.discrepancy),'Document mismatch amount in PHP','exclamation-triangle',true)}${kpi('Matched lines',record.matches.filter(row=>row.status==='matched').length,`${record.matches.length} invoice lines in this case`,'list')}${kpi('Currency',record.currency,'All linked documents share a currency','coins')}</div>`+
      (record.status==='exception'?'<div class="finance-callout warning">Accepted delivery quantities differ from the invoice. Open line matching to inspect the discrepancy before resolving this case.</div>':'')+
      `<div class="finance-grid"><div>${card('Documents in this case',`<div class="finance-card-body"><div class="finance-process" style="grid-template-columns:repeat(3,minmax(0,1fr))">${docs.map(([kind,key,title])=>`<div><h3 class="fs-10 mb-3">${title}</h3>${record[key].map(id=>{const row=find(kind,id);return `<div class="mb-3">${a(url(kind,id),esc(row.reference),'fw-semibold')}<div class="mt-2">${badge(kind==='invoices'?row.invoiceStatus:row.status)}</div></div>`;}).join('') || '<span class="text-600">No document linked</span>'}</div>`).join('')}</div></div>`)}${card('Line matches',matchSummary(record),a(url('reconciliation',record.id,'match'),'Open matching workspace '+icon('arrow-right')))}${card('Case notes',`<div class="finance-card-body">${esc(record.notes || 'No notes added.')}</div>`)}</div><aside>${card('Case details',`<div class="finance-card-body">${meta([[config.party,a(url('parties',record.partyId),esc(partyName(record)))],['Transaction date',date(record.date)],['Currency',record.currency],['Reconciled at',record.reconciledAt?date(record.reconciledAt):'Not recorded']],true)}</div>`)}<div class="finance-callout">Matching groups document lines. Payment allocation is tracked separately and determines the invoice balance.</div></aside></div>`);
  }
  function matchSummary(record) {
    return `<div class="table-responsive"><table class="table finance-table"><caption class="visually-hidden">Reconciliation line matches</caption><thead><tr><th>Invoice item</th><th>Order line</th><th>Receipt line</th><th class="text-end">Matched qty</th><th>Status</th></tr></thead><tbody>${record.matches.map(match=>{const invoice=find('invoices',match.invoiceId);const line=invoice.lines[match.invoiceLine];return `<tr><td>${esc(line.code)}<span class="subtext">${esc(invoice.reference)} · Line ${match.invoiceLine+1}</span></td><td>${esc(find('purchase-orders',match.orderId)?.reference || 'Unlinked')} · ${match.orderLine+1}</td><td>${esc(find('delivery-receipts',match.receiptId)?.reference || 'Unlinked')} · ${match.receiptLine+1}</td><td class="amount">${match.quantity}</td><td>${badge(match.status)}</td></tr>`;}).join('') || '<tr><td colspan="5" class="text-center p-4 text-600">No line matches. Open the matching workspace to link document lines.</td></tr>'}</tbody></table></div>`;
  }

  function field(name, title, value = '', type = 'text', options = {}) {
    const full = options.full ? ' full' : '';
    const required = options.required ? ' required' : '';
    const hint = options.hint ? `<small>${esc(options.hint)}</small>` : '';
    let input;
    if(options.choices) input=`<select class="form-select" name="${name}" id="field-${name}"${required}${options.multiple?' multiple size="5"':''}>${options.placeholder?'<option value="">Choose an option</option>':''}${options.choices.map(choice=>{const [key,text]=Array.isArray(choice)?choice:[choice,label(choice)];return `<option value="${esc(key)}" ${(Array.isArray(value)?value.map(String).includes(String(key)):String(key)===String(value))?'selected':''}>${esc(text)}</option>`;}).join('')}</select>`;
    else if(type==='textarea') input=`<textarea class="form-control" name="${name}" id="field-${name}" rows="3"${required}>${esc(value)}</textarea>`;
    else input=`<input class="form-control" type="${type}" name="${name}" id="field-${name}" value="${esc(value)}"${required}${type==='number'?` min="0" step="${options.step || '0.01'}"`:''}${type==='text'?' maxlength="255"':''}>`;
    return `<div class="finance-field${full}"><label for="field-${name}">${esc(title)}${options.required?' <span class="text-danger" aria-hidden="true">*</span>':''}</label>${input}${hint}</div>`;
  }
  const partyOptions = () => data.parties.map(row=>[row.id,`${row.name}${row.status==='inactive'?' (inactive)':''}`]);
  function documentsForParty(partyId, selected = {}, currency='PHP') {
    return [['purchase-orders','orderIds','Purchase orders'],['delivery-receipts','receiptIds','Delivery receipts'],['invoices','invoiceIds','Invoices']].map(([kind,key,title])=>field(key,title,selected[key] || [],'text', {full:true,multiple:true,choices:data[kind].filter(row=>row.partyId===Number(partyId) && (!row.currency || row.currency===currency)).map(row=>[row.id,row.reference]),hint:'Select one or more documents. Use Ctrl / Command to select multiple.'})).join('');
  }
  function form(record) {
    // Only account maintenance and reconciliation grouping are editable here.
    if (!config.canEncode || extractionOnly) {
      root.innerHTML = breadcrumb('Extraction required') + extractionNotice() + extractionActions();
      return;
    }
    const editing = Boolean(record);
    const draft = record || {reference:'', partyId:Number(filters.get('party')) || data.parties[0]?.id, date:data.today, currency:'PHP', status:'active', terms:30, creditLimit:0};
    let fields;
    let linkedDocuments = '';
    if (resource === 'parties') {
      fields = field('reference', `${config.party} code`, draft.reference, 'text', {required:true}) +
        field('name', `${config.party} name`, draft.name, 'text', {required:true}) +
        field('contact', 'Contact person', draft.contact) + field('email', 'Email', draft.email, 'email') +
        field('phone', 'Phone', draft.phone) + field('taxId', 'Tax identification no.', draft.taxId) +
        field('terms', 'Payment terms (days)', draft.terms, 'number', {required:true, step:'1'}) +
        (ar ? field('creditLimit', 'Credit limit (PHP)', draft.creditLimit, 'number') : '') +
        field('status', 'Account status', draft.status, 'text', {choices:statuses.parties}) +
        field('address', 'Billing address', draft.address, 'textarea', {full:true}) +
        (ar ? field('shippingAddress', 'Shipping address', draft.shippingAddress, 'textarea', {full:true}) : '');
    } else {
      fields =
        field('partyId', config.party, draft.partyId, 'text', {required:true, choices:partyOptions()}) +
        field('date', 'Transaction date', draft.date, 'date', {required:true}) +
        field('currency', 'Currency', draft.currency || 'PHP', 'text', {choices:[...new Set(['PHP',...data.invoices.map(row=>row.currency)])]});
      linkedDocuments = card('Extracted documents', `<div class="finance-card-body"><p class="text-600">Select existing extracted records for the same ${config.party.toLowerCase()} and currency. Add or correct source records in document or database extraction.</p><div class="finance-form-grid" id="case-document-fields">${documentsForParty(draft.partyId,draft,draft.currency)}</div><div class="finance-actions mt-3">${extractionActions()}</div></div>`);
    }
    root.innerHTML = breadcrumb(editing ? `Edit ${draft.reference}` : `New ${singulars[resource]}`) +
      heading(`${editing ? 'Edit' : 'New'} ${singulars[resource]}`, "Fields marked * are required. Changes are validated and saved to the database.") +
      `<form id="record-form"><div id="form-error" class="finance-form-error" role="alert" tabindex="-1" hidden></div>${card(resource === 'parties' ? 'Account information' : 'Case details', `<div class="finance-card-body"><div class="finance-form-grid">${fields}</div></div>`)}${linkedDocuments}${card(resource === 'parties' ? 'Extraction context' : 'Case notes', `<div class="finance-card-body">${field('notes', resource === 'parties' ? 'Account context' : 'Notes', draft.notes, 'textarea')}</div>`)}<div class="finance-form-footer"><span class="text-600 fs-10">${icon('flask')} Changes are saved to the database</span><div class="finance-actions">${button(editing ? url(resource,record.id) : url(resource), 'Cancel')}<button class="btn btn-primary" type="submit">${icon('check')} ${editing ? 'Save changes' : 'Create '+singulars[resource]}</button></div></div></form>`;
    if (resource === 'reconciliation') root.querySelector('[name="partyId"]').addEventListener('change', event => {
      root.querySelector('#case-document-fields').innerHTML = documentsForParty(event.target.value,{},root.querySelector('[name=currency]').value);
    });
    if(resource==='reconciliation')root.querySelector('[name=currency]').addEventListener('change',event=>{root.querySelector('#case-document-fields').innerHTML=documentsForParty(root.querySelector('[name=partyId]').value,{},event.target.value);});
    root.querySelector('#record-form').addEventListener('submit', async event => {
      event.preventDefault();
      const values = new FormData(event.currentTarget);
      const next = {...structuredClone(draft)};
      for (const [key,value] of values) next[key] = typeof value === 'string' ? value.trim() : value;
      if (resource === 'parties' && data[resource].some(row => row.id !== record?.id && row.reference.toLowerCase() === next.reference.toLowerCase() && (resource === 'parties' || row.partyId === Number(next.partyId)))) return showError('This reference already exists for this account. Use a unique reference.');
      if (resource === 'parties') {
        next.terms = Number(next.terms);
        next.creditLimit = Number(next.creditLimit || 0);
      } else {
        next.partyId = Number(next.partyId);
        if (!find('parties',next.partyId)) return showError('Choose an existing account.');
        for (const key of ['orderIds','receiptIds','invoiceIds']) next[key] = values.getAll(key).map(Number);
        if (!next.invoiceIds.length) return showError('Link at least one extracted invoice to create a reconciliation case.');
        if (!record || ['orderIds','receiptIds','invoiceIds'].some(key => JSON.stringify(record[key]) !== JSON.stringify(next[key]))) {
          next.matches = []; next.status = 'pending'; next.discrepancy = 0;
        }
      }
      try {
        const result = await api.post(resource, record?.id, {...next, revision:record?.revision});
        location.href = url(resource, result.id);
      } catch (error) { showError(error.message); }

    });
  }

  function allocate(payment) {
    if(payment.status==='reversed') {root.innerHTML=breadcrumb(payment.reference)+empty('This payment is reversed','Reversed payments cannot be allocated.',button(url('payments',payment.id),'Back to payment'));return;}
    const invoices=data.invoices.filter(invoice=>invoice.partyId===payment.partyId && invoice.currency===payment.currency && posted(invoice));
    const existing=data.allocations.filter(row=>row.paymentId===payment.id);
    root.innerHTML=breadcrumb('Allocate '+payment.reference)+heading('Allocate payment',`${esc(payment.reference)} · ${esc(partyName(payment))} · ${esc(payment.currency)}`,button(url('payments',payment.id),'Back to payment'))+
      `<div class="finance-kpis">${kpi(ar?'Cash received':'Cash paid',compact(payment.amount),'Available cash budget','credit-card',true)}${kpi('Withholding tax',compact(payment.withholding),'Available tax budget','receipt',true)}${kpi('Discount taken',compact(payment.discountTaken),'Available discount budget','tag',true)}${kpi('Payment status',label(payment.status),'Only cleared payments settle invoices','check-circle')}</div>`+
      `<div class="finance-callout">Allocate cash, withholding tax, and discounts independently. Only invoices for the same ${config.party.toLowerCase()} and currency appear. Saving replaces this payment's allocations.</div>`+
      `<form id="allocation-form"><div class="finance-form-error" id="form-error" role="alert" tabindex="-1" hidden></div>${card('Invoice allocations',invoices.length?`<div class="table-responsive"><table class="table finance-table"><caption class="visually-hidden">Allocate payment components to invoices</caption><thead><tr><th>Invoice</th><th class="text-end">Available balance PHP</th><th>Cash</th><th>Withholding tax</th><th>Discount</th><th class="text-end">Allocated PHP</th></tr></thead><tbody>${invoices.map(invoice=>{const current=existing.find(row=>row.invoiceId===invoice.id);const other=total(data.allocations.filter(row=>row.invoiceId===invoice.id && row.paymentId!==payment.id && find('payments',row.paymentId)?.status!=='reversed'),row=>row.cash+row.withholding+row.discount);return `<tr data-allocation="${invoice.id}" data-capacity="${Math.max(0,invoice.amount-other)}"><td>${a(url('invoices',invoice.id),esc(invoice.reference),'primary-link')}<span class="subtext">Due ${date(invoice.dueDate)}</span></td><td class="amount">${money(Math.max(0,invoice.amount-other))}</td>${['cash','withholding','discount'].map(component=>`<td><input type="number" class="form-control" min="0" step="0.01" name="${component}-${invoice.id}" data-component="${component}" aria-label="${esc(invoice.reference)} ${component}" value="${current?.[component] || 0}" required></td>`).join('')}<td class="amount" data-allocation-total></td></tr>`;}).join('')}</tbody></table></div><div class="finance-card-body border-top" id="allocation-summary" role="status"></div>`:empty('No eligible invoices','Review document or database extraction for an eligible invoice with the same account and currency.',extractionActions()))}<div class="finance-form-footer"><span class="text-600 fs-10">Pending allocations reserve amounts but do not settle invoices.</span><div class="finance-actions">${button(url('payments',payment.id),'Cancel')}<button type="submit" class="btn btn-primary" ${invoices.length?'':'disabled'}>${icon('check')} Save allocations</button></div></div></form>`;
    const read=()=>[...root.querySelectorAll('[data-allocation]')].map(row=>({paymentId:payment.id,invoiceId:Number(row.dataset.allocation),...Object.fromEntries([...row.querySelectorAll('input')].map(input=>[input.dataset.component,Number(input.value)]))}));
    const update=()=>{
      const rows=read();root.querySelectorAll('[data-allocation-total]').forEach((element,index)=>{const row=rows[index];element.textContent=money(row.cash+row.withholding+row.discount);});
      const summary=root.querySelector('#allocation-summary');if(summary) summary.innerHTML=`<div class="finance-actions justify-content-between"><span>Remaining cash <strong>PHP ${money(payment.amount-total(rows,row=>row.cash))}</strong></span><span>Remaining tax <strong>PHP ${money(payment.withholding-total(rows,row=>row.withholding))}</strong></span><span>Remaining discount <strong>PHP ${money(payment.discountTaken-total(rows,row=>row.discount))}</strong></span></div>`;
    };
    root.querySelector('#allocation-form').addEventListener('input',update);update();
    root.querySelector('#allocation-form').addEventListener('submit',async event=>{
      event.preventDefault();const rows=read();const cents=value=>Math.round(value*100);
      if(rows.some(row=>[row.cash,row.withholding,row.discount].some(value=>!Number.isFinite(value)||value<0))) return showError('Allocation amounts must be zero or greater.');
      if(cents(total(rows,row=>row.cash))>cents(payment.amount) || cents(total(rows,row=>row.withholding))>cents(payment.withholding) || cents(total(rows,row=>row.discount))>cents(payment.discountTaken)) return showError('Allocations exceed an available payment component. Check the cash, tax, and discount budgets.');
      if(rows.some(row=>cents(row.cash+row.withholding+row.discount)>cents(root.querySelector(`[data-allocation="${row.invoiceId}"]`).dataset.capacity))) return showError('An allocation exceeds the invoice balance after other payments.');
      try {
        await api.post('allocations', payment.id, {revision:payment.revision, allocations:rows.filter(row=>row.cash+row.withholding+row.discount>0)});
        location.href=url('payments',payment.id);
      } catch (error) { showError(error.message); }

    });
  }

  function matching(record) {
    const invoiceLines=record.invoiceIds.flatMap(invoiceId=>find('invoices',invoiceId).lines.map((line,index)=>({invoiceId,index,line})));
    const options=(kind,ids,selectedId,selectedLine)=>'<option value="">Select a line</option>'+ids.flatMap(id=>find(kind,id).lines.map((line,index)=>`<option value="${id}:${index}" ${id===selectedId&&index===selectedLine?'selected':''}>${esc(find(kind,id).reference)} · ${index+1} · ${esc(line.code)} · ${kind==='delivery-receipts'?'accepted '+line.accepted:'qty '+line.quantity}</option>`)).join('');
    root.innerHTML=breadcrumb('Match '+record.reference)+heading('Match document lines',`${esc(record.reference)} · ${esc(partyName(record))} · ${esc(record.currency)}`,button(url('reconciliation',record.id),'Back to case'))+
      '<div class="finance-callout">Link each invoice line to an order line and an accepted delivery line. Compare item codes, units, quantities, prices, tax, and discounts. Saved matches use the server’s quantity and price checks.</div>'+
      `<form id="match-form"><div id="form-error" class="finance-form-error" role="alert" tabindex="-1" hidden></div>${card('Three-way matching',`<div class="table-responsive"><table class="table finance-table"><caption class="visually-hidden">Compare purchase order, delivery receipt, and invoice lines</caption><thead><tr><th>Invoice line</th><th>Purchase order line</th><th>Delivery receipt line</th><th>Matched qty</th><th>Result</th></tr></thead><tbody>${invoiceLines.map(({invoiceId,index,line})=>{const match=record.matches.find(row=>row.invoiceId===invoiceId&&row.invoiceLine===index);return `<tr data-match-invoice="${invoiceId}" data-match-line="${index}"><td><strong>${esc(line.code)}</strong><span class="subtext">${esc(find('invoices',invoiceId).reference)} · Line ${index+1}</span><span class="subtext">Billed ${line.quantity} ${esc(line.unit)} × PHP ${money(line.price)}</span></td><td><select class="form-select" data-order aria-label="${esc(line.code)} purchase order line">${options('purchase-orders',record.orderIds,match?.orderId,match?.orderLine)}</select></td><td><select class="form-select" data-receipt aria-label="${esc(line.code)} delivery receipt line">${options('delivery-receipts',record.receiptIds,match?.receiptId,match?.receiptLine)}</select></td><td><input class="form-control finance-match-qty" type="number" min="0" max="${line.quantity}" step="0.0001" value="${match?.quantity ?? line.quantity}" data-quantity aria-label="${esc(line.code)} matched quantity" required></td><td data-match-result></td></tr>`;}).join('')}</tbody></table></div><div class="finance-card-body border-top" id="match-summary" role="status"></div>`,a(url('reconciliation',record.id,'edit'),'Edit linked documents'))}<div class="finance-form-footer"><span class="text-600 fs-10">Discrepancies remain visible as exceptions.</span><div class="finance-actions">${button(url('reconciliation',record.id),'Cancel')}<button class="btn btn-primary" type="submit">${icon('check-double')} Save matches</button></div></div></form>`;
    function evaluate() {
      const usedOrders=new Map();const usedReceipts=new Map();let discrepancy=0;
      const rows=[...root.querySelectorAll('[data-match-invoice]')].map(element=>{
        const invoiceId=Number(element.dataset.matchInvoice);const invoiceLine=Number(element.dataset.matchLine);const invoice=find('invoices',invoiceId).lines[invoiceLine];
        const [orderId,orderLine]=(element.querySelector('[data-order]').value || '').split(':').map(Number);
        const [receiptId,receiptLine]=(element.querySelector('[data-receipt]').value || '').split(':').map(Number);
        const quantity=Number(element.querySelector('[data-quantity]').value);
        const order=find('purchase-orders',orderId)?.lines[orderLine];const receipt=find('delivery-receipts',receiptId)?.lines[receiptLine];
        let status='pending';let reason='Select order and receipt lines';
        if(order&&receipt) {
          const orderKey=`${orderId}:${orderLine}`;const receiptKey=`${receiptId}:${receiptLine}`;
          // Other cases consume the same source quantities; the current case is replaced on save.
          const otherMatches=data.reconciliation.filter(row=>row.id!==record.id).flatMap(row=>row.matches).filter(row=>row.status==='matched');
          const otherOrdered=total(otherMatches.filter(row=>row.orderId===orderId&&row.orderLine===orderLine),row=>row.quantity);
          const otherAccepted=total(otherMatches.filter(row=>row.receiptId===receiptId&&row.receiptLine===receiptLine),row=>row.quantity);
          usedOrders.set(orderKey,(usedOrders.get(orderKey)||0)+quantity);usedReceipts.set(receiptKey,(usedReceipts.get(receiptKey)||0)+quantity);
          const itemMismatch=invoice.code!==order.code || invoice.code!==receipt.code || invoice.unit!==order.unit || invoice.unit!==receipt.unit;
          const priceMismatch=Math.abs(invoice.price-order.price)>.01 || Math.abs((invoice.taxRate || 0)-(order.taxRate || 0))>.0001 || Math.abs((invoice.discount/invoice.quantity)-(order.discount/order.quantity))>.01;
          const quantityMismatch=quantity>invoice.quantity || invoice.quantity>receipt.accepted || invoice.quantity>order.quantity || usedOrders.get(orderKey)+otherOrdered>order.quantity || usedReceipts.get(receiptKey)+otherAccepted>receipt.accepted;
          status=itemMismatch||priceMismatch||quantityMismatch?'exception':quantity<invoice.quantity?'pending':'matched';
          reason=itemMismatch?'Item code or unit differs':priceMismatch?'Price, tax, or discount differs':quantityMismatch?'Quantity exceeds available lines':quantity<invoice.quantity?'Partially matched':'All checks passed';
          discrepancy+=Math.max(0,invoice.quantity-Math.min(quantity,receipt.accepted))*invoice.price*(1+invoice.taxRate/100)+Math.abs(invoice.price-order.price)*quantity;
        }
        element.querySelector('[data-match-result]').innerHTML=`${badge(status)}<span class="subtext">${reason}</span>`;
        return {invoiceId,invoiceLine,orderId:orderId||null,orderLine:Number.isFinite(orderLine)?orderLine:null,receiptId:receiptId||null,receiptLine:Number.isFinite(receiptLine)?receiptLine:null,quantity,status};
      });
      const matched=rows.filter(row=>row.status==='matched').length;
      const status=rows.some(row=>row.status==='exception')?'exception':rows.length&&matched===rows.length?'matched':matched>0||rows.some(row=>row.orderId&&row.receiptId&&row.quantity>0)?'partial':'pending';
      root.querySelector('#match-summary').innerHTML=`<div class="finance-actions justify-content-between"><span>Case status ${badge(status)}</span><span>${matched} / ${rows.length} lines fully matched</span><strong>Discrepancy PHP ${money(discrepancy)}</strong></div>`;
      return {matches:rows,status,discrepancy:Math.round(discrepancy*100)/100};
    }
    root.querySelector('#match-form').addEventListener('input',evaluate);root.querySelector('#match-form').addEventListener('change',evaluate);evaluate();
    root.querySelector('#match-form').addEventListener('submit', async event => {
      event.preventDefault();
      const result=evaluate();
      const rows=result.matches.map(row=>({
        invoiceLineId:find('invoices',row.invoiceId).lines[row.invoiceLine].id,
        orderLineId:find('purchase-orders',row.orderId)?.lines[row.orderLine]?.id || null,
        receiptLineId:find('delivery-receipts',row.receiptId)?.lines[row.receiptLine]?.id || null,
        quantity:row.quantity,
      }));
      try { await api.post('matches', record.id, {revision:record.matchRevision,matches:rows}); location.href=url('reconciliation',record.id); }
      catch(error) { showError(error.message); }
    });
  }

  function aging() {
    const groups=agingGroups();
    root.innerHTML=heading(ar?'Receivables aging':'Payables aging',`Outstanding balances by days past due. ${esc(reportCurrency)} · As of ${date(data.today)}.`,`<button class="btn btn-falcon-default" type="button" id="export-aging">${icon('download')} Export aging</button>`)+
      `<div class="finance-kpis">${kpi('Outstanding balance',compact(total(outstanding(),balance)),`${outstanding().length} open invoices`,'wallet',true)}${kpi('Current',compact(groups[0].amount),'Not past due','calendar',true)}${kpi('Overdue',compact(total(groups.slice(1),group=>group.amount)),'Past the invoice due date','clock',true)}${kpi('Over 60 days',compact(groups[3].amount+groups[4].amount),'Aging beyond 60 days','exclamation-circle',true)}</div>`+
      card('Aging by '+config.party.toLowerCase(),`<div class="table-responsive"><table class="table finance-table"><caption class="visually-hidden">Outstanding ${esc(reportCurrency)} by account and days overdue</caption><thead><tr><th>${config.party}</th>${groups.map(group=>`<th class="text-end">${group.name}</th>`).join('')}<th class="text-end">Total</th></tr></thead><tbody>${data.parties.map(account=>{const amounts=groups.map(group=>total(group.rows.filter(row=>row.partyId===account.id),balance));return `<tr><td>${a(url('parties',account.id),esc(account.name),'primary-link')}</td>${amounts.map(amount=>`<td class="amount">${amount?money(amount):'—'}</td>`).join('')}<td class="amount fw-semibold">${money(total(amounts,amount=>amount))}</td></tr>`;}).join('')}<tr class="fw-bold"><td>Total PHP</td>${groups.map(group=>`<td class="amount">${money(group.amount)}</td>`).join('')}<td class="amount">${money(total(outstanding(),balance))}</td></tr></tbody></table></div>`)+
      card('Overdue invoices',invoiceTable(outstanding().filter(row=>overdueDays(row)>0).sort((a,b)=>a.dueDate.localeCompare(b.dueDate))),a(url('invoices'),'View invoice register'))+
      '<div class="finance-callout">Aging includes posted and disputed invoices. Draft, pending, and void invoices are excluded. Cash, withholding tax, and discounts reduce balances only when the payment is cleared.</div>';
    root.querySelector('#export-aging').addEventListener('click',()=>{
      const rows=[['Account',...groups.map(group=>group.name),'Total '+reportCurrency],...data.parties.map(account=>{const amounts=groups.map(group=>total(group.rows.filter(row=>row.partyId===account.id),balance));return [account.name,...amounts,total(amounts,amount=>amount)];})];
      const csv=rows.map(row=>row.map(value=>`"${String(value).replace(/^[=+@-]/,"'$&").replaceAll('"','""')}"`).join(',')).join('\r\n');const href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8;'}));const link=document.createElement('a');link.href=href;link.download=`${config.mode}-aging-${data.today}.csv`;link.click();URL.revokeObjectURL(href);
    });
  }

  const currencies=[...new Set(['PHP',...data.invoices.map(row=>row.currency),...data.payments.map(row=>row.currency)])].filter(Boolean);
  if(['overview','aging','parties'].includes(resource)) {
    const wrapper=document.createElement('div');wrapper.className='d-flex justify-content-end gap-2 mb-3';
    wrapper.innerHTML=`<label for="report-currency">Report currency</label><select id="report-currency" class="form-select w-auto">${currencies.map(value=>`<option ${value===reportCurrency?'selected':''} value="${esc(value)}">${esc(value)}</option>`).join('')}</select>`;
    root.before(wrapper);wrapper.querySelector('select').addEventListener('change',event=>{const url=new URL(location.href);url.searchParams.set('currency',event.target.value);location.href=url;});
  }
  const record=config.recordId!==null?find(resource,config.recordId):null;
  if(config.recordId!==null&&!record) root.innerHTML=breadcrumb('Record unavailable')+empty('This record is unavailable','Reload the page to see current records.',button(url(resource),'Back to '+titles[resource]));
  else if(resource==='overview') overview();
  else if(resource==='aging') aging();
  else if(config.screen==='form') form(record);
  else if(config.screen==='allocate') allocate(record);
  else if(config.screen==='match') matching(record);
  else if(config.screen==='detail') detail(record);
  else register();
})();
