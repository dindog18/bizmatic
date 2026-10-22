/* Router-only browser state and shared presentation helpers. */
(() => {
  const config = JSON.parse(document.getElementById("router-config").textContent);
  const key = "bizmatic.router.preview.v1";
  let state;
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    if (saved?.version === 1 && ["destinations", "rules", "documents", "logs", "routes"].every(name => Array.isArray(saved[name]))) state = saved;
    } catch { /* Unavailable or corrupt browser storage starts with an empty preview. */ }
  const ui = window.BizmaticRouterUI = {
    config, key, state: state || { version: 1, destinations: [], rules: [], documents: [], logs: [], routes: [] },
    root: document.getElementById("router-root"), app: document.getElementById("router-app"),
    filters: { q: "", status: "", module: "", page: 1 }, renderers: {},
    esc: value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]),
    url: (name, id) => id === undefined ? config.routes[name] : config.routes[name].replace("/0/", `/${Number(id)}/`),
    nextId: rows => Math.max(0, ...rows.map(row => row.id)) + 1,
  };
  ui.moduleLabel = value => ({ accounts_payable: "Accounts payable", accounts_receivable: "Accounts receivable", inventory: "Inventory" })[value] || value.replace(/_/g, " ");
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
  ui.save = (message, redirect) => {
    let persisted = true;
    try { localStorage.setItem(key, JSON.stringify(ui.state)); } catch { persisted = false; }
    const text = persisted ? message : `${message} Browser storage is unavailable; changes will last until you leave this page.`;
    if (redirect && persisted) {
      try { sessionStorage.setItem(`${key}.notice`, text); } catch { /* Optional feedback. */ }
      window.location.assign(redirect);
    } else {
      if (redirect && !persisted) { ui.config.screen = redirect.includes("/rules/") ? "rules" : "destinations"; }
      ui.render(); ui.notice(text, !persisted);
    }
  };
  ui.heading = (title, description, action = "") => `<div class="router-heading"><div><h1>${ui.esc(title)}</h1><p>${ui.esc(description)}</p></div><div class="d-flex flex-wrap gap-2">${action}</div></div>`;
  ui.card = (title, content) => `<section class="card mb-4"><div class="card-header"><h2 class="fs-9 mb-0">${ui.esc(title)}</h2></div>${content}</section>`;
  ui.empty = (title, text, action = "") => `<div class="router-empty"><h2>${ui.esc(title)}</h2><p class="text-600">${ui.esc(text)}</p>${action}</div>`;
  ui.missing = list => ui.heading("Sample record unavailable", "This record may have been removed when the demo was reset.") + ui.card("Record unavailable", ui.empty("Choose another sample", "Return to the list to continue exploring.", `<a class="btn btn-primary" href="${ui.url(list)}">Back to list</a>`));
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
    dialog.showModal();
  };
})();
