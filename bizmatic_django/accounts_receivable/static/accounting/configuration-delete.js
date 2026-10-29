/* Shared, explicit deletion from AP/AR configuration lists and setup screens. */
(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('finance-config').textContent);
  const api = window.BizmaticAccounting;
  if (new URLSearchParams(location.search).get('deleted') === '1') {
    const message = document.createElement('p');
    message.className = 'finance-callout';
    message.setAttribute('role', 'status');
    message.textContent = 'Configuration deleted. Accounting records and historical attempts were preserved.';
    document.getElementById('finance-root').before(message);
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-delete-configuration]');
    if (!button || button.disabled) return;
    event.preventDefault();
    const id = Number(button.dataset.deleteConfiguration);
    const revision = Number(button.dataset.configurationRevision);
    const dialog = document.createElement('dialog');
    dialog.className = 'finance-dialog lab-dialog';
    dialog.setAttribute('aria-labelledby', 'configuration-delete-title');
    dialog.innerHTML = `<form><h2 id="configuration-delete-title">Delete configuration?</h2><p>Delete <strong data-name></strong>?</p><p>This removes the saved setup and its mapping rules. Accounting records, reconciliation links, migration/update history, and LLM activity are preserved.</p><p data-error class="text-danger" role="alert" hidden></p><div class="lab-dialog-actions"><button type="button" class="btn btn-falcon-default" data-cancel>Keep configuration</button><button type="submit" class="btn btn-danger">Delete configuration</button></div></form>`;
    dialog.querySelector('[data-name]').textContent = button.dataset.configurationName || 'this configuration';
    document.body.append(dialog);
    let busy = false;
    const close = () => { dialog.close(); dialog.remove(); button.focus(); };
    dialog.querySelector('[data-cancel]').addEventListener('click', close);
    dialog.addEventListener('cancel', event => { event.preventDefault(); if (!busy) close(); });
    dialog.querySelector('form').addEventListener('submit', async event => {
      event.preventDefault();
      if (busy) return;
      busy = true;
      dialog.querySelectorAll('button').forEach(item => item.disabled = true);
      try {
        await api.post('configuration-delete', id, {revision, confirmed:true});
        location.href = config.routes.configuration + '?deleted=1';
      } catch (error) {
        const message = dialog.querySelector('[data-error]');
        message.hidden = false;
        message.textContent = error.message || 'The configuration could not be deleted. Reload and try again.';
        busy = false;
        dialog.querySelectorAll('button').forEach(item => item.disabled = false);
      }
    });
    dialog.showModal();
  });
})();
