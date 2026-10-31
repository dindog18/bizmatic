/* Progressive enhancement; every operation remains a backend CSRF-protected form. */
(() => {
  'use strict';
  document.querySelectorAll('form[data-busy]').forEach(form => {
    form.addEventListener('submit', () => {
      if (!form.checkValidity()) return;
      const status = form.querySelector('[data-busy-status]');
      if (status) { status.hidden = false; status.textContent = form.dataset.busy; }
      // Do not disable submit controls: their name/value selects the server action.
      form.setAttribute('aria-busy', 'true');
    });
  });
  const connectionForm = document.querySelector('[data-connection-form]');
  if (connectionForm) {
    const transport = connectionForm.elements.transport;
    const groups = {stdio: ['command', 'arguments', 'working_directory', 'environment', 'environment_passthrough', 'clear_environment'],
      streamable_http: ['server_url', 'bearer_token_env_var', 'http_headers', 'clear_http_headers', 'env_http_headers']};
    const updateTransport = () => {
      for (const [kind, names] of Object.entries(groups)) for (const name of names) {
        const row = connectionForm.querySelector(`[data-field="${name}"]`);
        if (!row) continue;
        row.hidden = transport.value !== kind;
        row.querySelectorAll('input, textarea, select').forEach(input => { input.disabled = row.hidden; });
      }
    };
    transport.addEventListener('change', updateTransport);
    updateTransport();
  }
  if (connectionForm) connectionForm.addEventListener('submit', async event => {
    if (event.submitter?.value !== 'test') return;
    event.preventDefault();
    const result = connectionForm.querySelector('[data-test-result]');
    const buttons = connectionForm.querySelectorAll('button[type="submit"], button[name="intent"]');
    const body = new FormData(connectionForm);
    body.set('intent', 'test');
    buttons.forEach(button => { button.disabled = true; });
    try {
      const response = await fetch(connectionForm.action || location.href, {method: 'POST', body,
        credentials: 'same-origin', headers: {'Accept': 'application/json'}});
      const data = await response.json();
      result.className = `alert alert-${response.ok ? 'success' : 'danger'}`;
      result.textContent = data.message;
    } catch {
      result.className = 'alert alert-danger';
      result.textContent = 'The connection test could not finish. Check server availability and try again.';
    } finally {
      result.hidden = false;
      result.focus();
      buttons.forEach(button => { button.disabled = false; });
      connectionForm.removeAttribute('aria-busy');
      connectionForm.querySelector('[data-busy-status]').hidden = true;
    }
  });
  const form = document.querySelector('[data-operation-form]');
  if (form) {
    form.elements.connection.addEventListener('change', () => {
      const url = new URL(window.location.href);
      url.searchParams.set('connection', form.elements.connection.value);
      window.location.assign(url);
    });
  }
})();

/* Chat helpers fill the composer only; every request and correction remains explicit. */
(() => {
  const chat = document.getElementById('encoder-chat');
  if (!chat) return;
  const composer = document.getElementById('chat-message');
  const thread = chat.querySelector('[role="log"]');
  if (location.hash === '#encoder-chat') thread.scrollTop = thread.scrollHeight;
  chat.addEventListener('click', event => {
    const prompt = event.target.closest('[data-chat-prompt]');
    const retry = event.target.closest('[data-chat-retry]');
    if (prompt) composer.value = prompt.dataset.chatPrompt;
    if (retry) {
      let previous = retry.closest('article').previousElementSibling;
      while (previous && !previous.classList.contains('encoder-chat-message-user') && !previous.classList.contains('encoder-chat-message-routing')) previous = previous.previousElementSibling;
      if (previous) composer.value = previous.querySelector('.encoder-message').textContent.trim();
    }
    if (prompt || retry) { composer.focus(); composer.scrollIntoView({block:'center'}); }
  });
  document.querySelectorAll('form[action$="/chat/"]').forEach(form => form.addEventListener('submit', event => {
    if (form.dataset.submitting) { event.preventDefault(); return; }
    form.dataset.submitting = 'true';
    form.setAttribute('aria-busy', 'true');
    const status = form.querySelector('[data-busy-status]');
    if (status) { status.hidden = false; status.textContent = 'Thinking… Your current payload is unchanged.'; }
    setTimeout(() => { document.querySelectorAll('form[action$="/chat/"] button').forEach(button => { button.disabled = true; }); }, 0);
  }));
})();
