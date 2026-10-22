/* Display browser-only requests made from the extraction workspace. */
(() => {
  const ui = window.BizmaticRouterUI, e = ui.esc;
  ui.routingRequests = () => {
    let requests;
    try { requests = JSON.parse(localStorage.getItem("bizmatic.router.requests.v1") || "[]"); } catch { return ""; }
    if (!Array.isArray(requests)) return "";
    requests = requests.filter(request => Array.isArray(request.documents) && request.documents.length).slice(0, 5);
    if (!requests.length) return "";
    const rows = requests.map(request => {
      const docs = request.documents.filter(doc => Number.isSafeInteger(doc.id) && doc.id > 0);
      const links = docs.map(doc => `<a href="${ui.config.documentsUrl}${doc.id}/">#${doc.id} · ${e(doc.name)}</a>`);
      const unapproved = docs.filter(doc => doc.review_status !== "approved").length;
      const names = docs.length === 1 ? links[0] : `<details><summary>${docs.length} documents</summary><ul class="ps-3 mt-2 mb-0">${links.map(link => `<li>${link}</li>`).join("")}</ul></details>`;
      return `<tr><td>${names}<div class="router-subtext">${e(request.created_at)}</div></td><td>${request.scope === "batch" ? "Batch" : request.scope === "selected" ? "Selected documents" : "Document"}</td><td>${unapproved ? `${unapproved} unapproved · ${request.confirmed_unapproved ? "override confirmed" : "confirmation needed"}` : "All approved"}</td><td><span class="badge badge-subtle-info">Preview only</span></td></tr>`;
    });
    return ui.card("Recent routing requests", '<div class="card-body border-top text-600 fs-10">Requests from the document workspace are saved locally for this frontend preview. Routing execution is not connected yet. Showing the latest five requests.</div>' + ui.table(["Documents", "Requested from", "Review check", "State"], rows));
  };
})();
