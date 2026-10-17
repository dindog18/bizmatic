/* Native POST forms retain Django's CSRF protection and work without JavaScript. */
document.querySelectorAll("form[data-busy]").forEach(form => {
  let pending = false;
  form.addEventListener("submit", async event => {
    if (pending) { event.preventDefault(); return; }
    pending = true;
    form.setAttribute("aria-busy", "true");
    const status = form.querySelector("[data-busy-status]");
    if (status) { status.hidden = false; status.textContent = form.dataset.busy; }
    if (event.submitter && event.submitter.value === "test") {
      event.preventDefault();
      // Keep unsaved credentials in the input while testing; never echo them from the server.
      const body = new FormData(form);
      body.set("intent", "test");
      const buttons = form.querySelectorAll("button[type=submit]");
      const result = form.querySelector("[data-test-result]");
      buttons.forEach(button => { button.disabled = true; });
      result.hidden = true;
      try {
        const response = await fetch(form.action || window.location.href, {
          method: "POST", body, credentials: "same-origin",
          headers: { "X-Requested-With": "XMLHttpRequest" }
        });
        let message = "Connection test failed. Reload the page and check your settings before retrying.";
        if (response.headers.get("content-type")?.includes("application/json")) {
          const data = await response.json();
          message = data.message || Object.values(data.errors || {}).flat().map(error => error.message).join(" ") || message;
        }
        result.textContent = message;
        result.className = `alert alert-${response.ok ? "success" : "danger"}`;
      } catch (_) {
        result.textContent = "The connection test could not be completed. Check your network and retry.";
        result.className = "alert alert-danger";
      } finally {
        result.hidden = false;
        result.focus();
        if (status) status.hidden = true;
        form.removeAttribute("aria-busy");
        buttons.forEach(button => { button.disabled = false; });
        pending = false;
      }
      return;
    }
    // Let the browser include the clicked button's intent before disabling it.
    window.setTimeout(() => {
      form.querySelectorAll("button[type=submit]").forEach(button => { button.disabled = true; });
    }, 0);
  });
});
window.addEventListener("pageshow", event => {
  if (event.persisted) window.location.reload();
});
