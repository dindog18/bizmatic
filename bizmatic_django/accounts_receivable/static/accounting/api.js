/* Small shared client for CSRF-protected accounting actions. */
window.BizmaticAccounting = (() => {
  const config = JSON.parse(document.getElementById('finance-config').textContent);
  const state = JSON.parse(document.getElementById('finance-state').textContent);
  let busy = false;
  async function post(action, id, values) {
    if (busy) throw new Error('Wait for the current action to finish.');
    busy = true;
    const controls = [...document.querySelectorAll('button,input,select,textarea')].filter(control => !control.disabled);
    controls.forEach(control => control.disabled = true);
    try {
      const url = config.api.replace('/action/', '/' + action + '/') + (id ? id + '/' : '');
      const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json','X-CSRFToken':config.csrfToken}, body:JSON.stringify(values)});
      let result;
      try {
        result = await response.json();
      } catch {
        const status = `HTTP ${response.status}`;
        if ([408, 504].includes(response.status)) {
          throw new Error(`${status}: The server or proxy timed out waiting for the request. Check LLM activity before retrying; prompt generation may have finished. Ask the server administrator to align proxy and application timeouts with the configured LLM timeout.`);
        }
        if ([502, 503].includes(response.status)) {
          throw new Error(`${status}: The application server is unavailable or stopped before returning a result. Check LLM activity before retrying and ask the administrator to inspect the application and proxy logs.`);
        }
        if (response.status === 403) {
          throw new Error(`${status}: The server rejected this request. Reload the page and try again; if it persists, check CSRF and proxy settings.`);
        }
        throw new Error(`${status}: The server returned an unexpected non-JSON response. Check the saved state before retrying and ask the administrator to inspect the application and proxy logs.`);
      }
      if (!result || typeof result !== 'object' || Array.isArray(result)) {
        throw new Error(`HTTP ${response.status}: The server returned an invalid response. Reload and check the saved state before retrying.`);
      }
      if (!response.ok) {
        const error = new Error(result.message || 'The action could not be saved.');
        error.llmLogNo = result.llm_log_no;
        throw error;
      }
      return result;
    } catch (error) {
      if (error instanceof Error) throw error;
      throw new Error(error.message || 'The server could not be reached. Reload to check the saved state.');
    } finally { busy = false; controls.forEach(control => control.disabled = false); }
  }
  return {state, post};
})();
