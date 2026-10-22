/* Confirm the source selection, then execute routing through the server. */
(() => {
  const host = document.getElementById("document-routing");
  if (!host) return;
  const documents = JSON.parse(document.getElementById("document-routing-data").textContent);
  const dialog = document.getElementById("document-routing-dialog");
  let requestId, running = false;
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  let selected = [], scope = "document";
  const unapproved = () => selected.filter(doc => doc.review_status !== "approved");
  const list = rows => `<ul class="list-group list-group-flush document-routing-list">${rows.map(doc => `<li class="list-group-item px-0 d-flex justify-content-between gap-3"><span class="text-break">#${doc.id} · ${escape(doc.name)}</span><span class="badge badge-subtle-${doc.review_status === "approved" ? "success" : doc.review_status === "rejected" ? "danger" : "warning"} align-self-start">${escape(doc.review_status === "approved" ? "Approved" : doc.review_status === "rejected" ? "Rejected" : "Pending")}</span></li>`).join("")}</ul>`;
  const show = (title, body, buttons) => {
    dialog.innerHTML = `<div class="p-4"><div class="d-flex justify-content-between gap-3 mb-3"><h2 class="fs-8 mb-0" id="document-routing-title">${title}</h2><button type="button" class="btn-close" data-routing-action="cancel" aria-label="Close routing confirmation"></button></div>${body}<div class="alert alert-info fs-10 mt-3">The configured LLM will evaluate the saved extraction text against active routing rules. Results and attempt logs are saved for review.</div><div id="document-routing-error" class="alert alert-danger" role="alert" hidden></div><div class="d-flex justify-content-end flex-wrap gap-2 mt-4"><button type="button" class="btn btn-falcon-default" data-routing-action="cancel" autofocus>Cancel</button>${buttons}</div></div>`;
    if (!dialog.open) dialog.showModal();
    else dialog.querySelector('[data-routing-action="cancel"]').focus();
  };
  const start = rows => {
    selected = rows;
    requestId = crypto.randomUUID();
    if (!selected.length) return;
    const count = selected.length, pending = unapproved().length;
    show(`Route ${count === 1 ? "document" : `${count} documents`}?`, `<p class="text-600">${scope === "batch" ? "All documents in this batch are included, across every page." : "Confirm the documents to send to the routing workspace."}</p>${list(selected)}<p class="fs-10 mt-3 mb-0">${pending ? `${pending} document${pending === 1 ? " has" : "s have"} not been approved. An additional confirmation is required.` : "All selected documents have been approved."}</p>`, `<button type="button" class="btn btn-primary" data-routing-action="continue">${pending ? "Continue" : count === 1 ? "Route document" : "Route documents"}</button>`);
  };
  const submit = async override => {
    if (running || (unapproved().length && !override)) return;
    running = true;
    dialog.querySelectorAll("button").forEach(button => { button.disabled = true; });
    const error = document.getElementById("document-routing-error");
    error.hidden = true;
    const progress = document.createElement("p");
    progress.className = "text-primary mt-3";
    progress.setAttribute("role", "status");
    progress.textContent = "Routing documents… Please wait for the saved results.";
    dialog.querySelector(".p-4").append(progress);
    try {
      const response = await fetch(host.dataset.executeUrl, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": host.querySelector('[name="csrfmiddlewaretoken"]').value },
        body: JSON.stringify({ request_id: requestId, document_ids: selected.map(doc => doc.id),
          batch_id: scope === "batch" ? Number(host.dataset.batchId) : null,
          revisions: Object.fromEntries(selected.map(doc => [doc.id, doc.revision])), allow_unapproved: override }),
      });
      let result;
      try { result = await response.json(); } catch { throw new Error("The server response was interrupted. Check routing history or retry this same request."); }
      if (result.confirmation_required) {
        running = false;
        start(result.documents);
        const warning = document.getElementById("document-routing-error");
        warning.textContent = result.message;
        warning.hidden = false;
        return;
      }
      if (!response.ok) throw new Error(result.message || "Routing could not start.");
      location.assign(result.redirect || host.dataset.queueUrl);
    } catch (failure) {
      error.textContent = failure.message || "Routing could not complete. Check routing history, then retry.";
      error.hidden = false;
      progress.remove();
      dialog.querySelectorAll("button").forEach(button => { button.disabled = false; });
      running = false;
    }
  };
  dialog.addEventListener("cancel", event => { if (running) event.preventDefault(); });
  const updateSelection = () => {
    const boxes = [...document.querySelectorAll("[data-routing-select]")];
    const checked = boxes.filter(box => box.checked).length;
    document.querySelectorAll('[data-routing-trigger="selected"]').forEach(button => {
      button.disabled = !checked;
      button.textContent = checked ? `Route selected (${checked})` : "Route selected";
    });
    document.querySelectorAll("[data-routing-select-all]").forEach(box => {
      box.checked = Boolean(boxes.length) && checked === boxes.length;
      box.indeterminate = checked > 0 && checked < boxes.length;
    });
  };
  document.addEventListener("change", event => {
    if (event.target.matches("[data-routing-select-all]")) document.querySelectorAll("[data-routing-select]").forEach(box => { box.checked = event.target.checked; });
    if (event.target.matches("[data-routing-select],[data-routing-select-all]")) updateSelection();
  });
  document.addEventListener("click", event => {
    const trigger = event.target.closest("[data-routing-trigger]");
    if (trigger && !trigger.disabled && !running) {
      scope = trigger.dataset.routingTrigger;
      const ids = scope === "selected" ? [...document.querySelectorAll("[data-routing-select]:checked")].map(box => Number(box.value)) : scope === "document" ? [Number(trigger.dataset.documentId)] : documents.map(doc => doc.id);
      start(documents.filter(doc => ids.includes(doc.id)));
    }
    const action = event.target.closest("[data-routing-action]")?.dataset.routingAction;
    if (running) return;
    if (action === "cancel") dialog.close();
    if (action === "continue") {
      if (!unapproved().length) submit(false);
      else show("Route unapproved documents?", `<div class="alert alert-warning">The following documents have pending or rejected reviews. Routing them may use text that has not been verified.</div>${list(unapproved())}<p class="mt-3 mb-0">Do you still want to proceed with ${selected.length === 1 ? "this document" : `all ${selected.length} selected documents`}?</p>`, '<button type="button" class="btn btn-warning" data-routing-action="override">Route anyway</button>');
    }
    if (action === "override") submit(true);
  });
  updateSelection();
})();
