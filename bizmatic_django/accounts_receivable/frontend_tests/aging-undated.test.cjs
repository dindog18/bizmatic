const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

for (const mode of ['ap', 'ar']) test(`${mode}: undated invoices remain in aging totals and CSV`, async () => {
  const base = mode === 'ar' ? '/accounts-receivable/' : '/accounts-payable/';
  const config = { mode, resource: 'aging', recordId: null, screen: 'list', title: 'Accounting',
    party: mode === 'ar' ? 'Customer' : 'Supplier',
    routes: Object.fromEntries(['overview', 'purchase-orders', 'delivery-receipts', 'invoices', 'payments', 'reconciliation', 'aging', 'parties', 'configuration'].map(key => [key, base + key + '/'])),
    sources: { documents: '/documents/', upload: '/documents/upload/', databases: '/databases/' } };
  const state = { today: '2026-10-28', parties: [{id: 1, name: 'Example'}],
    invoices: [{id: 1, partyId: 1, currency: 'PHP', invoiceStatus: 'posted', dueDate: '', balance: 100, amount: 100, settled: 0},
      {id: 2, partyId: 1, currency: 'PHP', invoiceStatus: 'posted', dueDate: '2026-10-18', balance: 50, amount: 50, settled: 0}],
    payments: [], allocations: [], reconciliation: [], 'purchase-orders': [], 'delivery-receipts': [] };
  let exportClick, blob;
  const root = { innerHTML: '', before() {}, querySelector: () => ({ addEventListener: (_, cb) => { exportClick = cb; } }) };
  const mockURL = class extends URL {};
  mockURL.createObjectURL = value => { blob = value; return 'blob:test'; };
  mockURL.revokeObjectURL = () => {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/accounting/workspace.js'), 'utf8'), {
    window: { BizmaticAccounting: { state } }, URLSearchParams, URL: mockURL, Blob,
    location: { search: '', href: 'http://localhost' + base, pathname: base },
    document: { getElementById: id => id === 'finance-config' ? { textContent: JSON.stringify(config) } : root,
      createElement: tag => tag === 'a' ? { click() {} } : { innerHTML: '', querySelector: () => ({ addEventListener() {} }) } },
  });
  assert.match(root.innerHTML, /Undated/);
  assert.match(root.innerHTML, /100\.00/);
  assert.match(root.innerHTML, /150\.00/);
  assert.match(root.innerHTML, /Overdue[\s\S]*?50\.00/);
  exportClick();
  const csv = await blob.text();
  assert.match(csv, /"Undated"/);
  assert.match(csv, /"Example","0","50","0","0","0","100","150"/);
});
