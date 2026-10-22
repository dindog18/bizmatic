/* Browser-only routing requests. Saved review states are never changed here. */
(() => {
  const host = document.getElementById("document-routing");
  if (!host) return;
  const documents = JSON.parse(document.getElementById("document-routing-data").textContent);
  const dialog = document.getElementById("document-routing-dialog");
  const storageKey = "bizmatic.router.requests.v1";
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  let selected = [], scope = "document";
  const unapproved = () => selected.filter(doc => doc.review_status !== "approved");
  const list = rows => `<ul class="list-group list-group-flush document-routing-list">${rows.map(doc => `<li class="list-group-item px-0 d-flex justify-content-between gap-3"><span class="text-break">#${doc.id} · ${escape(doc.name)}</span><span class="badge badge-subtle-${doc.review_status === "approved" ? "success" : doc.review_status === "rejected" ? "danger" : "warning"} align-self-start">${escape(doc.review_status === "approved" ? "Approved" : doc.review_status === "rejected" ? "Rejected" : "Pending")}</span></li>`).join("")}</ul>`;
  const show = (title, body, buttons) => {
    dialog.innerHTML = `<div class="p-4"><div class="d-flex justify-content-between gap-3 mb-3"><h2 class="fs-8 mb-0" id="document-routing-title">${title}</h2><button type="button" class="btn-close" data-routing-action="cancel" aria-label="Close routing confirmation"></button></div>${body}<div class="alert alert-info fs-10 mt-3">Frontend preview: routing requests are saved in this browser.</div><div id="document-routing-error" class="alert alert-danger" role="alert" hidden></div><div class="d-flex justify-content-end flex-wrap gap-2 mt-4"><button type="button" class="btn btn-falcon-default" data-routing-action="cancel" autofocus>Cancel</button>${buttons}</div></div>`;
    if (!dialog.open) dialog.showModal();
    else dialog.querySelector('[data-routing-action="cancel"]').focus();
  };
  const start = rows => {
    selected = rows;
    if (!selected.length) return;
    const count = selected.length, pending = unapproved().length;
    show(`Route ${count === 1 ? "document" : `${count} documents`}?`, `<p class="text-600">${scope === "batch" ? "All documents in this batch are included, across every page." : "Confirm the documents to send to the routing workspace."}</p>${list(selected)}<p class="fs-10 mt-3 mb-0">${pending ? `${pending} document${pending === 1 ? " has" : "s have"} not been approved. An additional confirmation is required.` : "All selected documents have been approved."}</p>`, `<button type="button" class="btn btn-primary" data-routing-action="continue">${pending ? "Continue" : count === 1 ? "Route document" : "Route documents"}</button>`);
  };
  const submit = override => {
    // Only the explicit second confirmation may submit unapproved documents.
    if (unapproved().length && !override) return;
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "[]");
      const requests = Array.isArray(saved) ? saved : [];
      requests.unshift({ id: crypto.randomUUID(), scope, documents: selected,
        confirmed_unapproved: override, created_at: new Date().toISOString() });
      localStorage.setItem(storageKey, JSON.stringify(requests.slice(0, 20)));
    } catch {
      const error = document.getElementById("document-routing-error");
      error.textContent = "The preview request could not be saved. Enable browser storage and try again.";
      error.hidden = false;
      return;
    }
    dialog.close();
    window.location.assign(host.dataset.queueUrl);
  };
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
    if (trigger && !trigger.disabled) {
      scope = trigger.dataset.routingTrigger;
      const ids = scope === "selected" ? [...document.querySelectorAll("[data-routing-select]:checked")].map(box => Number(box.value)) : scope === "document" ? [Number(trigger.dataset.documentId)] : documents.map(doc => doc.id);
      start(documents.filter(doc => ids.includes(doc.id)));
    }
    const action = event.target.closest("[data-routing-action]")?.dataset.routingAction;
    if (action === "cancel") dialog.close();
    if (action === "continue") {
      if (!unapproved().length) submit(false);
      else show("Route unapproved documents?", `<div class="alert alert-warning">The following documents have pending or rejected reviews. Routing them may use text that has not been verified.</div>${list(unapproved())}<p class="mt-3 mb-0">Do you still want to proceed with ${selected.length === 1 ? "this document" : `all ${selected.length} selected documents`}?</p>`, '<button type="button" class="btn btn-warning" data-routing-action="override">Route anyway</button>');
    }
    if (action === "override") submit(true);
  });
  updateSelection();
})();
