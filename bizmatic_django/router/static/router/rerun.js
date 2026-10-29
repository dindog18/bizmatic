/* Reassess a document with a new attempt; reuse its request ID after interruption. */
(() => {
  const ui = window.BizmaticRouterUI, e = ui.esc;
  ui.rerunRunning = false;
  ui.rerunRequests = new Map();
  ui.documentBusy = doc => ['queued', 'processing'].includes(doc.processing_status)
    || ui.state.logs.some(log => log.document_id === doc.id && ['queued', 'processing'].includes(log.status))
    || ui.state.routes.some(route => route.processing_status === 'processing'
      && ui.state.logs.some(log => log.id === route.log_id && log.document_id === doc.id));
  ui.canRetryRoute = route => {
    const log = ui.state.logs.find(row => row.id === route.log_id);
    const doc = ui.state.documents.find(row => row.id === log?.document_id);
    return doc && log.status === 'completed' && ui.latestLog(doc.id)?.id === log.id
      && log.source_revision === doc.revision && route.review_status !== 'rejected'
      && ['pending', 'failed'].includes(route.processing_status);
  };
  ui.rerunButton = doc => `<button class="btn btn-primary" type="button" data-action="rerun" data-id="${doc.id}" ${ui.documentBusy(doc) ? 'disabled' : ''}>Rerun routing</button>`;
  ui.showRerun = (docId, message = '') => {
    const doc = ui.state.documents.find(row => row.id === docId);
    if (!doc || ui.documentBusy(doc)) return;
    if (!ui.rerunRequests.has(docId)) ui.rerunRequests.set(docId, crypto.randomUUID());
    ui.openDialog('Rerun routing', `<form id="router-rerun-form" data-document-id="${docId}">
      <p>Assess <strong>${e(doc.name)}</strong> again using its latest saved extraction text and active routing rules. A new attempt is saved in routing history, and matched AP/AR destinations start extraction automatically.</p>
      <p class="text-600">If a saved destination only needs another extraction attempt, cancel and use Retry extraction. Existing accounting records are protected from duplicate creation.</p>
      ${doc.review_status !== 'approved' ? `<div class="alert alert-warning">This source document is ${e(doc.review_status)} and has not been approved.</div><label class="d-flex gap-2 mb-3"><input type="checkbox" name="allow_unapproved" class="form-check-input" required><span>Route this unapproved document anyway.</span></label>` : ''}
      <div class="alert alert-warning" id="router-rerun-error" role="alert" ${message ? '' : 'hidden'}>${e(message)}</div>
      <p id="router-rerun-progress" role="status" hidden>Routing and extracting AP/AR records… Please wait for the saved result.</p>
      <div class="d-flex justify-content-end gap-2"><button type="button" class="btn btn-falcon-default" data-action="close-dialog">Cancel</button><button type="submit" class="btn btn-primary">Start routing</button></div>
    </form>`);
  };
  ui.submitRerun = async form => {
    if (ui.rerunRunning) return;
    const docId = Number(form.dataset.documentId);
    const doc = ui.state.documents.find(row => row.id === docId);
    const override = Boolean(form.elements.allow_unapproved?.checked);
    if (doc.review_status !== 'approved' && !override) return;
    ui.rerunRunning = true;
    const dialog = document.getElementById('router-dialog');
    dialog.querySelectorAll('button, input').forEach(control => { control.disabled = true; });
    const errorBox = document.getElementById('router-rerun-error');
    errorBox.hidden = true;
    document.getElementById('router-rerun-progress').hidden = false;
    try {
      const result = await ui.request(ui.config.api.execute, {
        request_id: ui.rerunRequests.get(docId), document_ids: [docId],
        revisions: { [docId]: doc.revision }, allow_unapproved: override,
      });
      location.assign(result.redirect || ui.url('document', docId));
    } catch (error) {
      ui.rerunRunning = false;
      if (error.result?.confirmation_required) {
        Object.assign(doc, error.result.documents.find(row => row.id === docId));
        ui.showRerun(docId, error.message);
        return;
      }
      errorBox.textContent = `${error.message} Check routing history before retrying. Retrying this dialog reuses the same request.`;
      errorBox.hidden = false;
      document.getElementById('router-rerun-progress').hidden = true;
      dialog.querySelectorAll('button, input').forEach(control => { control.disabled = false; });
    }
  };
  document.getElementById('router-dialog').addEventListener('cancel', event => {
    if (ui.rerunRunning) event.preventDefault();
  });
})();
