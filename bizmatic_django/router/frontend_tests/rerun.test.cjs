const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function setup(request, review = 'approved') {
  const doc = { id: 7, name: 'Demo order', revision: 'source-v1', review_status: review, processing_status: 'completed' };
  const controls = [{ disabled: false }];
  const elements = {
    'router-dialog': { querySelectorAll: () => controls, addEventListener() {} },
    'router-rerun-error': { hidden: true, textContent: '' },
    'router-rerun-progress': { hidden: true },
  };
  const ui = { state: { documents: [doc], logs: [], routes: [] }, config: { api: { execute: '/router/execute/' } },
    esc: value => String(value), request, url: (_, id) => `/router/documents/${id}/`,
    openDialog: (_, content) => { ui.dialogContent = content; } };
  let redirect;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/router/rerun.js'), 'utf8'), {
    window: { BizmaticRouterUI: ui }, document: { getElementById: id => elements[id] },
    crypto: { randomUUID: () => 'fixed-request-id' }, location: { assign: url => { redirect = url; } },
  });
  const form = { dataset: { documentId: '7' }, elements: { allow_unapproved: { checked: false } } };
  return { ui, doc, form, controls, elements, redirect: () => redirect };
}

test('an interrupted rerun keeps its request ID and prevents overlapping submits', async () => {
  const calls = [];
  let rejectFirst;
  const app = setup((url, payload) => {
    calls.push({ url, payload });
    if (calls.length === 1) return new Promise((_, reject) => { rejectFirst = reject; });
    return Promise.resolve({ redirect: '/router/documents/7/' });
  });
  app.ui.showRerun(7);
  const pending = app.ui.submitRerun(app.form);
  assert.equal(app.controls[0].disabled, true);
  assert.equal(app.elements['router-rerun-progress'].hidden, false);
  await app.ui.submitRerun(app.form);
  assert.equal(calls.length, 1);
  rejectFirst(new Error('Connection interrupted'));
  await pending;
  assert.equal(app.controls[0].disabled, false);
  assert.match(app.elements['router-rerun-error'].textContent, /Connection interrupted/);
  app.ui.showRerun(7);
  await app.ui.submitRerun(app.form);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].payload.request_id, calls[1].payload.request_id);
  assert.equal(calls[1].payload.revisions[7], 'source-v1');
  assert.equal(app.redirect(), '/router/documents/7/');
});

test('a changed source requires confirmation using its new review and revision', async () => {
  const calls = [];
  const app = setup(async (_, payload) => {
    calls.push(payload);
    if (calls.length === 1) throw Object.assign(new Error('The source changed'), { result: {
      confirmation_required: true, documents: [{ id: 7, revision: 'source-v2', review_status: 'rejected' }],
    } });
    return { redirect: '/router/documents/7/' };
  });
  app.ui.showRerun(7);
  await app.ui.submitRerun(app.form);
  assert.equal(app.doc.revision, 'source-v2');
  assert.match(app.ui.dialogContent, /Route this unapproved document anyway/);
  await app.ui.submitRerun(app.form);
  assert.equal(calls.length, 1);
  app.form.elements.allow_unapproved.checked = true;
  await app.ui.submitRerun(app.form);
  assert.equal(calls[1].revisions[7], 'source-v2');
  assert.equal(calls[1].allow_unapproved, true);
  assert.equal(calls[0].request_id, calls[1].request_id);
});
