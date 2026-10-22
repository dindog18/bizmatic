/* Compose the preview and wire local interactions. All requests remain GET-only. */
(() => {
  const ui = window.BizmaticRouterUI, e = ui.esc;
  ui.reviewDrafts = {};
  ui.configurationDirty = false;

  ui.renderers.queue = () => {
    const docs = ui.state.documents;
    const pending = docs.filter(doc => ui.status(ui.latestLog(doc.id)) === "pending").length;
    const multi = docs.filter(doc => ui.logRoutes(ui.latestLog(doc.id)?.id).length > 1).length;
    const unmatched = docs.filter(doc => ui.status(ui.latestLog(doc.id)) === "unmatched").length;
    const metrics = [["Sample documents", docs.length, "Across the routing workspace"], ["Needs review", pending, "Check proposed destinations"], ["Multiple destinations", multi, "Documents with more than one route"], ["No match", unmatched, "Review or add a destination"]];
    const filtered = docs.filter(doc => {
      const log = ui.latestLog(doc.id), routes = ui.logRoutes(log?.id);
      return ui.matches(doc.name, doc.party, doc.type, doc.batch) && (!ui.filters.status || ui.status(log) === ui.filters.status) && (!ui.filters.module || routes.some(route => ui.destination(route.destination_id)?.module_name === ui.filters.module));
    });
    const page = ui.page(filtered);
    const rows = page.rows.map(doc => {
      const log = ui.latestLog(doc.id), routes = ui.logRoutes(log?.id);
      return `<tr><td><div class="router-file"><span class="router-file-icon"><span class="fas fa-file-alt" aria-hidden="true"></span></span><div><a class="fw-semibold" href="${ui.url("document", doc.id)}">${e(doc.name)}</a><div class="router-subtext">${e(doc.party)} · ${e(doc.batch)}</div></div></div></td><td>${e(doc.type)}</td><td><div class="router-destinations">${routes.length ? routes.map(route => `<span class="router-tag">${e(ui.destination(route.destination_id)?.name || "Unknown destination")}</span>`).join("") : '<span class="text-600">—</span>'}</div></td><td>${ui.badge(ui.status(log))}</td><td><a href="${ui.url("document", doc.id)}">${ui.status(log) === "pending" ? "Review" : "View"}</a></td></tr>`;
    });
    return ui.heading("Document routing", "Review where extracted documents belong, and guide the router with clear rules.", `<a class="btn btn-falcon-default" href="${ui.config.documentsUrl}">Open documents</a>`) + ui.routingRequests() + `<div class="router-metrics">${metrics.map(([label, value, note]) => `<div class="card router-metric"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join("")}</div>` + ui.card("Routing queue", ui.toolbar({ placeholder: "Search document, company or batch", statuses: ["pending", "approved", "rejected", "unmatched", "failed"], modules: true }) + (rows.length ? ui.table(["Document", "Document type", "Destinations", "Review status", "Action"], rows) : ui.empty("No documents found", "Try another search or clear the filters.", '<button class="btn btn-falcon-default" type="button" data-action="clear-filters">Clear filters</button>')) + page.footer);
  };

  ui.render = () => {
    const active = document.activeElement;
    const focus = active?.id;
    const selection = active instanceof HTMLInputElement ? active.selectionStart : null;
    const screen = ui.config.screen;
    const renderer = screen.startsWith("destination_") ? ui.renderers.destinationForm : screen.startsWith("rule_") ? ui.renderers.ruleForm : ui.renderers[screen];
    ui.root.innerHTML = renderer();
    const tab = screen === "document" ? "queue" : screen === "log" ? "logs" : screen.startsWith("destination_") ? "destinations" : screen.startsWith("rule_") ? "rules" : screen;
    ui.app.querySelectorAll(".router-tabs a").forEach(link => {
      if (link.dataset.screen === tab) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    const heading = ui.root.querySelector("h1");
    if (heading) document.title = `${heading.textContent} | Bizmatic`;
    if (focus) {
      const next = document.getElementById(focus);
      if (next) { next.focus({ preventScroll: true }); if (selection !== null && next instanceof HTMLInputElement) next.setSelectionRange(selection, selection); }
    }
  };

  ui.app.addEventListener("input", event => {
    const target = event.target;
    if (target.matches("input[data-filter]")) { ui.filters[target.dataset.filter] = target.value; ui.filters.page = 1; ui.render(); }
    if (target.closest("#router-config-form")) ui.configurationDirty = true;
    const form = target.closest("[data-review-form]");
    if (form) {
      const route = ui.state.routes.find(row => row.id === Number(form.dataset.routeId));
      if (target.value !== route.review_notes) ui.reviewDrafts[route.id] = target.value;
      else delete ui.reviewDrafts[route.id];
    }
    if (target.id === "manual-reason") target.setCustomValidity("");
  });
  ui.app.addEventListener("change", event => {
    const target = event.target;
    if (target.matches("select[data-filter]")) { ui.filters[target.dataset.filter] = target.value; ui.filters.page = 1; ui.render(); }
    if (target.closest("#router-config-form")) ui.configurationDirty = true;
  });

  ui.app.addEventListener("click", event => {
    const button = event.target.closest("[data-action]");
    if (!button || button.disabled) return;
    const id = Number(button.dataset.id);
    switch (button.dataset.action) {
      case "clear-filters": ui.filters = { q: "", status: "", module: "", page: 1 }; ui.render(); break;
      case "page": ui.filters.page = Number(button.dataset.page); ui.render(); break;
      case "toggle": {
        const row = ui.state[button.dataset.kind].find(item => item.id === id);
        row.is_active = !row.is_active;
        ui.save(`${row.name} ${row.is_active ? "enabled" : "disabled"} in this browser.`);
        break;
      }
      case "add-route": ui.showAddRoute(Number(button.dataset.logId)); break;
      case "close-dialog": document.getElementById("router-dialog").close(); break;
      case "accuracy": {
        const log = ui.state.logs.find(row => row.id === id);
        log.user_selected_accurate = !log.user_selected_accurate;
        ui.save(log.user_selected_accurate ? "Sample response marked accurate." : "Accuracy feedback removed.");
        break;
      }
      case "download-log": {
        const log = ui.state.logs.find(row => row.id === id);
        const blob = new Blob([JSON.stringify({ ...log, reviewed_routes: ui.logRoutes(id) }, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob), link = document.createElement("a");
        link.href = url; link.download = `demo-routing-${id}.json`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        break;
      }
      case "reset":
        ui.openDialog("Reset the routing demo?", '<p>This restores the sample documents, rules, destinations, and review decisions in this browser.</p><div class="d-flex justify-content-end gap-2"><button type="button" class="btn btn-falcon-default" data-action="close-dialog">Cancel</button><button type="button" class="btn btn-danger" data-action="confirm-reset">Reset demo</button></div>');
        break;
      case "confirm-reset": {
        try { localStorage.removeItem(ui.key); sessionStorage.removeItem(`${ui.key}.notice`); } catch { /* In-memory reset still works. */ }
        ui.state = structuredClone(window.BizmaticRouterDemo);
        ui.filters = { q: "", status: "", module: "", page: 1 };
        ui.reviewDrafts = {}; ui.configurationDirty = false;
        document.getElementById("router-dialog").close();
        ui.render(); ui.notice("Routing demo reset to its original sample data.");
        break;
      }
    }
  });

  ui.app.addEventListener("submit", event => {
    event.preventDefault();
    const form = event.target;
    if (form.id === "router-config-form") ui.submitConfiguration(form);
    if (form.matches("[data-review-form]")) {
      const route = ui.state.routes.find(row => row.id === Number(form.dataset.routeId));
      route.review_notes = String(new FormData(form).get("review_notes")).trim();
      const decision = event.submitter?.value || "notes";
      if (decision !== "notes") route.review_status = decision;
      delete ui.reviewDrafts[route.id];
      ui.save(`${ui.destination(route.destination_id).name}: ${decision === "notes" ? "notes saved" : ui.label(decision).toLowerCase()} in this browser.`);
    }
    if (form.id === "router-add-route-form") {
      const data = new FormData(form), reason = String(data.get("reason")).trim();
      if (!reason) { const field = form.elements.reason; field.setCustomValidity("Enter a reason for adding this destination."); field.reportValidity(); return; }
      ui.state.routes.push({ id: ui.nextId(ui.state.routes), log_id: Number(form.dataset.logId), destination_id: Number(data.get("destination_id")), confidence: null, reason, review_status: "pending", review_notes: "" });
      document.getElementById("router-dialog").close(); ui.save("Destination added to this sample review.");
    }
  });
  window.addEventListener("beforeunload", event => {
    if (ui.configurationDirty || Object.keys(ui.reviewDrafts).length) { event.preventDefault(); event.returnValue = ""; }
  });
  ui.render();
  try {
    const notice = sessionStorage.getItem(`${ui.key}.notice`);
    if (notice) { ui.notice(notice); sessionStorage.removeItem(`${ui.key}.notice`); }
  } catch { /* Optional saved feedback. */ }
})();
