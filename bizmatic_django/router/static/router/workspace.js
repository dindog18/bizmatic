/* Compose routing screens and persist human configuration and review actions. */
(() => {
  const ui = window.BizmaticRouterUI, e = ui.esc;
  ui.reviewDrafts = {};
  ui.configurationDirty = false;

  ui.renderers.queue = () => {
    const docs = ui.state.documents;
    const pending = docs.filter(doc => ui.status(ui.latestLog(doc.id)) === "pending").length;
    const multi = docs.filter(doc => ui.logRoutes(ui.latestLog(doc.id)?.id).length > 1).length;
    const unmatched = docs.filter(doc => ui.status(ui.latestLog(doc.id)) === "unmatched").length;
    const metrics = [["Routed documents", docs.length, "Most recent 500 routed documents"], ["Needs review", pending, "Check proposed destinations"], ["Multiple destinations", multi, "Documents with more than one route"], ["No match", unmatched, "Review or add a destination"]];
    const filtered = docs.filter(doc => {
      const log = ui.latestLog(doc.id), routes = ui.logRoutes(log?.id);
      return ui.matches(doc.name, doc.party, doc.type, doc.batch) && (!ui.filters.status || ui.status(log) === ui.filters.status) && (!ui.filters.module || routes.some(route => ui.destination(route.destination_id)?.module_name === ui.filters.module));
    });
    const page = ui.page(filtered);
    const rows = page.rows.map(doc => {
      const log = ui.latestLog(doc.id), routes = ui.logRoutes(log?.id);
      return `<tr><td><div class="router-file"><span class="router-file-icon"><span class="fas fa-file-alt" aria-hidden="true"></span></span><div><a class="fw-semibold" href="${ui.url("document", doc.id)}">${e(doc.name)}</a><div class="router-subtext">${e(doc.party)} · ${e(doc.batch)}</div></div></div></td><td>${e(doc.type)}</td><td><div class="router-destinations">${routes.length ? routes.map(route => `<span class="router-tag">${e(ui.destination(route.destination_id)?.name || "Unknown destination")}</span>`).join("") : '<span class="text-600">—</span>'}</div></td><td>${ui.badge(ui.status(log))}</td><td><a href="${ui.url("document", doc.id)}">${ui.status(log) === "pending" ? "Review" : "View"}</a></td></tr>`;
    });
    return ui.heading("Document routing", "Review where extracted documents belong, and guide the router with clear rules.", `<a class="btn btn-falcon-default" href="${ui.config.documentsUrl}">Open documents</a>`) + `<div class="router-metrics">${metrics.map(([label, value, note]) => `<div class="card router-metric"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join("")}</div>` + ui.card("Routing queue", ui.toolbar({ placeholder: "Search document, company or batch", statuses: ["pending", "approved", "rejected", "unmatched", "failed"], modules: true }) + (rows.length ? ui.table(["Document", "Document type", "Destinations", "Review status", "Action"], rows) : ui.empty("No documents found", "Try another search or clear the filters.", '<button class="btn btn-falcon-default" type="button" data-action="clear-filters">Clear filters</button>')) + page.footer);
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
    if (target.id === "router-module_name") ui.changeDestinationModule(target.form);
    if (target.closest("#router-config-form")) ui.configurationDirty = true;
  });

  ui.app.addEventListener("click", async event => {
    const button = event.target.closest("[data-action]");
    if (!button || button.disabled) return;
    const id = Number(button.dataset.id);
    try {
      switch (button.dataset.action) {
      case "clear-filters": ui.filters = { q: "", status: "", module: "", page: 1 }; ui.render(); break;
      case "page": ui.filters.page = Number(button.dataset.page); ui.render(); break;
      case "toggle": {
        const row = ui.state[button.dataset.kind].find(item => item.id === id);
        const saved = await ui.post(ui.apiURL("toggle", row.id, button.dataset.kind), { is_active: !row.is_active, revision: row.revision });
        Object.assign(row, saved);
        ui.render(); ui.notice(`${row.name} ${row.is_active ? "enabled" : "disabled"}.`);
        break;
      }
      case "add-route": ui.showAddRoute(Number(button.dataset.logId)); break;
      case "close-dialog": document.getElementById("router-dialog").close(); break;
      case "accuracy": {
        const log = ui.state.logs.find(row => row.id === id);
        const saved = await ui.post(ui.apiURL("accuracy", id), { accurate: !log.user_selected_accurate, revision: log.revision });
        Object.assign(log, saved);
        ui.render(); ui.notice(log.user_selected_accurate ? "Routing response marked accurate." : "Accuracy feedback removed.");
        break;
      }
      case "download-log": {
        const log = ui.state.logs.find(row => row.id === id);
        const blob = new Blob([JSON.stringify({ ...log, reviewed_routes: ui.logRoutes(id) }, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob), link = document.createElement("a");
        link.href = url; link.download = `routing-${id}.json`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        break;
      }

    }
    } catch (error) { ui.notice(error.message, true); }
  });

  ui.app.addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.target;
    if (form.id === "router-config-form") ui.submitConfiguration(form);
    try {
      if (form.matches("[data-review-form]")) {
        const route = ui.state.routes.find(row => row.id === Number(form.dataset.routeId));
        const decision = event.submitter?.value || "notes";
        const saved = await ui.post(ui.apiURL("review", route.id), {
          review_notes: String(new FormData(form).get("review_notes")).trim(), decision, revision: route.revision,
        });
        Object.assign(route, saved);
        delete ui.reviewDrafts[route.id];
        ui.render(); ui.notice(`${ui.destination(route.destination_id).name}: ${decision === "notes" ? "notes saved" : ui.label(decision).toLowerCase()}.`);
      }
      if (form.id === "router-add-route-form") {
        const data = new FormData(form), reason = String(data.get("reason")).trim();
        if (!reason) { const field = form.elements.reason; field.setCustomValidity("Enter a reason for adding this destination."); field.reportValidity(); return; }
        const route = await ui.post(ui.apiURL("addRoute", form.dataset.logId), { destination_id: Number(data.get("destination_id")), reason });
        ui.state.routes.push(route);
        document.getElementById("router-dialog").close(); ui.render(); ui.notice("Destination added for review.");
      }
    } catch (error) { ui.notice(error.message, true); }

  });
  window.addEventListener("beforeunload", event => {
    if (ui.configurationDirty || Object.keys(ui.reviewDrafts).length) { event.preventDefault(); event.returnValue = ""; }
  });
  ui.render();
})();
