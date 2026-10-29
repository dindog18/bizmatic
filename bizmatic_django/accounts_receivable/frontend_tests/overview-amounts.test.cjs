const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function render(mode, orders, currency = 'PHP') {
  const base = mode === 'ar' ? '/accounts-receivable/' : '/accounts-payable/';
  const config = { mode, resource: 'overview', recordId: null, screen: 'list',
    title: mode === 'ar' ? 'Accounts receivable' : 'Accounts payable', party: mode === 'ar' ? 'Customer' : 'Supplier',
    routes: Object.fromEntries(['overview', 'purchase-orders', 'delivery-receipts', 'invoices', 'payments', 'reconciliation', 'aging', 'configuration']
      .map(resource => [resource, resource === 'overview' ? base : base + resource + '/'])),
    sources: { documents: '/documents/', upload: '/documents/upload/', databases: '/databases/' } };
  const state = { today: '2026-10-28', parties: [], invoices: [], payments: [], allocations: [], reconciliation: [],
    'purchase-orders': orders, 'delivery-receipts': [] };
  const wrapper = { innerHTML: '', querySelector: () => ({ addEventListener() {} }) };
  const root = { innerHTML: '', before() {} };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/accounting/workspace.js'), 'utf8'), {
    window: { BizmaticAccounting: { state } }, URLSearchParams, URL,
    location: { search: '?currency=' + currency, href: 'http://localhost' + base, pathname: base },
    document: { getElementById: id => id === 'finance-config' ? { textContent: JSON.stringify(config) } : root,
      createElement: () => wrapper },
  });
  const metric = name => {
    const start = root.innerHTML.indexOf('class="kpi-label">' + name);
    assert.notEqual(start, -1, 'Missing metric: ' + name);
    return root.innerHTML.slice(start).match(/class="kpi-value">(.*?)<\/div>/s)[1].replace(/<[^>]*>/g, '');
  };
  return { html: root.innerHTML, currencies: wrapper.innerHTML, metric };
}

const orders = [
  { id: 1, status: 'draft', currency: 'PHP', amount: 100.10, lines: [{ total: 100.10 }, { total: 100.10 }] },
  { id: 2, status: 'open', currency: 'PHP', amount: 20.20, lines: [] },
  { id: 3, status: 'closed', currency: 'PHP', amount: 30.30, lines: [] },
  { id: 4, status: 'cancelled', currency: 'PHP', amount: 9999, lines: [] },
  { id: 5, status: 'open', currency: 'USD', amount: 70.40, lines: [] },
];

for (const mode of ['ap', 'ar']) {
  test(`${mode}: amounts use saved headers, selected currency, and order statuses`, () => {
    const result = render(mode, orders);
    assert.equal(result.metric('Total PO amount'), 'PHP150.60');
    assert.equal(result.metric('Open order amount'), 'PHP20.20');
    assert.match(result.html, new RegExp(`3 ${mode === 'ar' ? 'customer' : 'company'} POs`));
    assert.match(result.html, /1 open order/);
    assert.match(result.html, /purchase-orders\/\?status=open/);
    assert.match(result.currencies, /value="USD"/); // A currency found only on orders is selectable.
    assert.match(result.html, /Total (payables|receivables)/);
  });

  test(`${mode}: another currency excludes PHP and retains its own open amount`, () => {
    const result = render(mode, orders, 'USD');
    assert.equal(result.metric('Total PO amount'), 'USD70.40');
    assert.equal(result.metric('Open order amount'), 'USD70.40');
  });

  test(`${mode}: empty or cancelled-only order books display zero`, () => {
    for (const rows of [[], orders.filter(row => row.status === 'cancelled')]) {
      const result = render(mode, rows);
      assert.equal(result.metric('Total PO amount'), 'PHP0.00');
      assert.equal(result.metric('Open order amount'), 'PHP0.00');
    }
  });
}
