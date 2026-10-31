/* Server-provided routing records and shared presentation helpers. */
(() => {
  const config = JSON.parse(document.getElementById("router-config").textContent);
  const ui = window.BizmaticRouterUI = {
    config, state: JSON.parse(document.getElementById("router-state").textContent),
    root: document.getElementById("router-root"), app: document.getElementById("router-app"),
    filters: { q: "", status: "", module: "", page: 1 }, renderers: {},
    esc: value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]),
    url: (name, id) => id === undefined ? config.routes[name] : config.routes[name].replace("/0/", `/${Number(id)}/`),
  };
  ui.date = value => new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
  ui.moduleLabel = value => ({ encoder: "Encoder", accounts_payable: "Accounts payable", accounts_receivable: "Accounts receivable", inventory: "Inventory" })[value] || value.replace(/_/g, " ");
  ui.destination = id => ui.state.destinations.find(row => row.id === Number(id));
  ui.latestLog = docId => ui.state.logs.find(row => row.document_id === docId);
  ui.logRoutes = logId => ui.state.routes.filter(row => row.log_id === logId);
  ui.status = log => {
    if (!log) return "unrouted";
    if (log.status !== "completed") return log.status;
    const routes = ui.logRoutes(log.id);
    if (!routes.length) return "unmatched";
    if (routes.some(route => route.review_status === "pending")) return "pending";
    return routes.every(route => route.review_status === "rejected") ? "rejected" : "approved";
  };
  ui.label = value => ({ pending: "Needs review", approved: "Approved", rejected: "Rejected", unmatched: "No match", failed: "Failed", completed: "Completed", queued: "Queued", processing: "Processing", unrouted: "Not routed", active: "Active", inactive: "Inactive" })[value] || value;
  ui.badge = value => `<span class="badge badge-subtle-${({ pending: "warning", approved: "success", completed: "success", failed: "danger", rejected: "secondary", active: "success", processing: "info" })[value] || "secondary"}">${ui.esc(ui.label(value))}</span>`;
  ui.notice = (text, danger = false) => {
    const notice = document.getElementById("router-notice");
    notice.textContent = text;
    notice.className = `alert alert-${danger ? "warning" : "info"}`;
    notice.hidden = false;
  };
  ui.apiURL = (name, id, kind) => ui.config.api[name].replace("/0/", `/${Number(id)}/`).replace("/destinations/", `/${kind || "destinations"}/`);
  ui.pendingRequests = new Set();
  ui.request = async (url, data) => {
    if (ui.pendingRequests.has(url)) throw new Error("Please wait for the current save to finish.");
    ui.pendingRequests.add(url);
    try {
      const response = await fetch(url, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": config.csrfToken }, body: JSON.stringify(data) });
      let result;
      try { result = await response.json(); } catch { throw new Error("The server did not return a valid response. Reload and check the saved record before trying again."); }
      if (!response.ok) throw Object.assign(new Error(result.message || "The record could not be saved."), { result });
      return result;
    } finally { ui.pendingRequests.delete(url); }
  };
  ui.post = async (url, data) => (await ui.request(url, data)).record;
  ui.heading = (title, description, action = "") => `<div class="router-heading"><div><h1>${ui.esc(title)}</h1><p>${ui.esc(description)}</p></div><div class="d-flex flex-wrap gap-2">${action}</div></div>`;
  ui.card = (title, content) => `<section class="card mb-4"><div class="card-header"><h2 class="fs-9 mb-0">${ui.esc(title)}</h2></div>${content}</section>`;
  ui.empty = (title, text, action = "") => `<div class="router-empty"><h2>${ui.esc(title)}</h2><p class="text-600">${ui.esc(text)}</p>${action}</div>`;
  ui.missing = list => ui.heading("Record unavailable", "This saved record is unavailable.") + ui.card("Record unavailable", ui.empty("Choose another record", "Return to the list to continue exploring.", `<a class="btn btn-primary" href="${ui.url(list)}">Back to list</a>`));
  ui.table = (headings, rows) => `<div class="table-responsive"><table class="table router-table mb-0"><thead><tr>${headings.map(title => `<th scope="col">${title}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  ui.toolbar = ({ placeholder, statuses = [], modules = false }) => `<div class="router-toolbar"><label class="visually-hidden" for="router-search">Search</label><input id="router-search" class="form-control" type="search" placeholder="${ui.esc(placeholder)}" value="${ui.esc(ui.filters.q)}" data-filter="q">${modules ? `<label class="visually-hidden" for="router-module">Module</label><select id="router-module" class="form-select" data-filter="module"><option value="">All modules</option>${[...new Set(ui.state.destinations.map(dest => dest.module_name))].map(name => `<option value="${ui.esc(name)}" ${ui.filters.module === name ? "selected" : ""}>${ui.esc(ui.moduleLabel(name))}</option>`).join("")}</select>` : ""}${statuses.length ? `<label class="visually-hidden" for="router-status">Status</label><select id="router-status" class="form-select" data-filter="status"><option value="">All statuses</option>${statuses.map(value => `<option value="${value}" ${ui.filters.status === value ? "selected" : ""}>${ui.esc(ui.label(value))}</option>`).join("")}</select>` : ""}<button class="btn btn-falcon-default" type="button" data-action="clear-filters">Clear filters</button></div>`;
  ui.matches = (...values) => values.join(" ").toLowerCase().includes(ui.filters.q.trim().toLowerCase());
  ui.page = rows => {
    const count = rows.length, pages = Math.max(1, Math.ceil(count / 5));
    ui.filters.page = Math.min(ui.filters.page, pages);
    const start = (ui.filters.page - 1) * 5;
    return { rows: rows.slice(start, start + 5), footer: `<div class="router-pagination"><span>${count ? `${start + 1}–${Math.min(start + 5, count)} of ${count}` : "0 results"}</span><div class="d-flex gap-2"><button class="btn btn-sm btn-falcon-default" data-action="page" data-page="${ui.filters.page - 1}" ${ui.filters.page <= 1 ? "disabled" : ""}>Previous</button><button class="btn btn-sm btn-falcon-default" data-action="page" data-page="${ui.filters.page + 1}" ${ui.filters.page >= pages ? "disabled" : ""}>Next</button></div></div>` };
  };
  ui.openDialog = (title, content) => {
    const dialog = document.getElementById("router-dialog");
    dialog.innerHTML = `<div class="router-dialog-header"><h2 id="router-dialog-title">${ui.esc(title)}</h2><button type="button" class="btn-close" aria-label="Close dialog" data-action="close-dialog"></button></div><div class="router-dialog-body">${content}</div>`;
    if (!dialog.open) dialog.showModal();
  };
})();
