/* Destination and rule forms save validated configuration to Django. */
(() => {
  const ui = window.BizmaticRouterUI, e = ui.esc;
  const createLink = (name, label) => `<a class="btn btn-primary" href="${ui.url(name)}"><span class="fas fa-plus me-2" aria-hidden="true"></span>${label}</a>`;
  const filter = (row, destination) => (!ui.filters.status || (row.is_active ? "active" : "inactive") === ui.filters.status) && (!ui.filters.module || destination?.module_name === ui.filters.module);
  const toggle = (kind, row) => `<button class="btn btn-sm btn-falcon-default" type="button" data-action="toggle" data-kind="${kind}" data-id="${row.id}" aria-label="${row.is_active ? "Disable" : "Enable"} ${e(row.name)}">${row.is_active ? "Disable" : "Enable"}</button>`;

  const deleteButton = (kind, row, label = "Delete") => `<button class="btn btn-sm btn-outline-danger" type="button" data-action="delete-configuration" data-kind="${kind}" data-id="${row.id}" aria-label="Delete ${e(row.name)}">${label}</button>`;
  ui.showDeleteConfiguration = (kind, id) => {
    const row = ui.state[kind].find(item => item.id === id);
    if (!row) return;
    ui.openDialog(`Delete ${kind === 'rules' ? 'routing rule' : 'destination'}`, `<form id="router-delete-form" data-kind="${kind}" data-id="${id}" data-revision="${e(row.revision)}"><p>Delete <strong>${e(row.name)}</strong>? This cannot be undone.</p>${ui.configurationDirty ? '<p class="text-warning">Unsaved edits will be discarded if you delete this record.</p>' : ''}<p class="text-600">${kind === 'rules' ? 'Past routing attempts retain their rule snapshots.' : 'Deleting this destination will also delete ALL associated routing rules. Past routing history and related accounting or Encoder records will be retained.'}</p><div id="router-delete-error" class="alert alert-danger" role="alert" tabindex="-1" hidden></div><div class="d-flex justify-content-end gap-2"><button type="button" class="btn btn-falcon-default" data-action="close-dialog">Cancel</button><button type="submit" class="btn btn-danger">Delete ${kind === 'rules' ? 'rule' : 'destination'}</button></div></form>`);
  };

  ui.renderers.destinations = () => {
    const filtered = ui.state.destinations.filter(row => filter(row, row) && ui.matches(row.name, row.module_name, row.target_model, row.description));
    const page = ui.page(filtered);
    const rows = page.rows.map(row => `<tr><td><a class="fw-semibold" href="${ui.url("destination_edit", row.id)}">${e(row.name)}</a><div class="router-subtext">${e(row.description)}</div></td><td>${e(ui.moduleLabel(row.module_name))}<div class="router-subtext"><code>${e(row.module_name)}</code></div></td><td><code>${e(row.target_model)}</code></td><td>${ui.badge(row.is_active ? "active" : "inactive")}</td><td><div class="d-flex gap-2 align-items-center">${toggle("destinations", row)}${deleteButton("destinations", row)}</div></td></tr>`);
    return ui.heading("Routing destinations", "Choose the modules and record types that documents can belong to.", createLink("destination_create", "Add destination")) + ui.card("Configured destinations", ui.toolbar({ placeholder: "Search destinations or record types", statuses: ["active", "inactive"], modules: true }) + (rows.length ? ui.table(["Destination", "Module", "Record type", "Status", "Actions"], rows) : ui.empty("No destinations found", "Try another search or add a destination.", createLink("destination_create", "Add destination"))) + page.footer);
  };

  ui.renderers.rules = () => {
    const filtered = ui.state.rules.filter(row => filter(row, ui.destination(row.destination_id)) && ui.matches(row.name, row.document_type, row.instructions, ui.destination(row.destination_id)?.name));
    const page = ui.page(filtered);
    const rows = page.rows.map(row => {
      const dest = ui.destination(row.destination_id);
      return `<tr><td><a class="fw-semibold" href="${ui.url("rule_edit", row.id)}">${e(row.name)}</a><div class="router-subtext">${e(row.document_type || "Any document type")}</div></td><td>${e(dest?.name)}<div class="router-subtext">${e(ui.moduleLabel(dest?.module_name || ""))}</div></td><td>${e(row.instructions.slice(0, 115))}${row.instructions.length > 115 ? "…" : ""}</td><td>${ui.badge(row.is_active ? "active" : "inactive")}${!dest?.is_active ? '<div class="router-subtext">Destination inactive</div>' : ""}</td><td><div class="d-flex gap-2 align-items-center">${toggle("rules", row)}${deleteButton("rules", row)}</div></td></tr>`;
    });
    return ui.heading("Routing rules", "Give the router clear examples and instructions for every destination.", createLink("rule_create", "Add routing rule")) + ui.card("Human-configured rules", ui.toolbar({ placeholder: "Search rules, document types or instructions", statuses: ["active", "inactive"], modules: true }) + (rows.length ? ui.table(["Rule", "Destination", "Instructions", "Status", "Actions"], rows) : ui.empty("No rules found", "Clear your filters or create a rule for a destination.", createLink("rule_create", "Add routing rule"))) + page.footer);
  };

  const field = (label, name, value, help = "", options = {}) => `<div class="mb-3"><label class="form-label" for="router-${name}">${label}${options.required ? ' <span class="text-danger" aria-hidden="true">*</span>' : ""}</label>${options.textarea ? `<textarea class="form-control" id="router-${name}" name="${name}" ${options.required ? "required" : ""} ${help ? `aria-describedby="help-${name}"` : ""}>${e(value)}</textarea>` : `<input class="form-control" id="router-${name}" name="${name}" value="${e(value)}" maxlength="${options.max || 160}" ${options.required ? "required" : ""} ${options.pattern ? `pattern="${options.pattern}"` : ""} ${help ? `aria-describedby="help-${name}"` : ""}>`}${help ? `<div id="help-${name}" class="form-text">${help}</div>` : ""}</div>`;
  const activeField = row => `<div class="form-check form-switch mb-3"><input class="form-check-input" id="router-active" name="is_active" type="checkbox" ${row.is_active ? "checked" : ""}><label class="form-check-label" for="router-active">Active</label></div>`;
  const formFooter = (list, row) => `<div class="card-footer d-flex flex-wrap justify-content-end gap-2">${row?.id ? `<div class="me-auto">${deleteButton(list, row, list === "rules" ? "Delete rule" : "Delete destination")}</div>` : ""}<a class="btn btn-falcon-default" href="${ui.url(list)}">Cancel</a><button class="btn btn-primary" type="submit">Save ${list === "rules" ? "rule" : "destination"}</button></div>`;

  const catalog = ui.config.destinationCatalog;
  const targetChoices = (moduleName, saved) => {
    const targets = [...(catalog.find(module => module.value === moduleName)?.targets || [])];
    if (saved?.module_name === moduleName && saved.target_model && !targets.some(target => target.value === saved.target_model)) {
      targets.push({ value: saved.target_model, label: `${saved.target_model} · Existing destination` });
    }
    return targets;
  };
  const targetOptions = (targets, value, hasModule) => `<option value="">${hasModule ? "Choose a target model" : "Choose a module first"}</option>${targets.map(target => `<option value="${e(target.value)}" ${value === target.value ? "selected" : ""}>${e(target.label)}${target.label === target.value ? "" : ` (${e(target.value)})`}</option>`).join("")}`;
  const destinationSelectors = row => {
    const modules = [...catalog];
    if (row.module_name && !modules.some(module => module.value === row.module_name)) {
      modules.push({ value: row.module_name, label: `${row.module_name} · Existing destination` });
    }
    return `<div class="mb-3"><label class="form-label" for="router-module_name">Module name <span class="text-danger" aria-hidden="true">*</span></label><select class="form-select" id="router-module_name" name="module_name" required aria-describedby="help-module_name"><option value="">Choose a module</option>${modules.map(module => `<option value="${e(module.value)}" ${row.module_name === module.value ? "selected" : ""}>${e(module.label)}</option>`).join("")}</select><div class="form-text" id="help-module_name">Select Accounts payable, Accounts receivable or Encoder to receive the document.</div></div><div class="mb-3"><label class="form-label" for="router-target_model">Target model <span class="text-danger" aria-hidden="true">*</span></label><select class="form-select" id="router-target_model" name="target_model" required aria-describedby="help-target_model" ${row.module_name ? "" : "disabled"}>${targetOptions(targetChoices(row.module_name, row), row.target_model, Boolean(row.module_name))}</select><div class="form-text" id="help-target_model">Choose a record type from the selected module.</div></div>`;
  };
  ui.changeDestinationModule = form => {
    const moduleName = form.elements.module_name.value;
    const saved = ui.state.destinations.find(row => row.id === Number(form.dataset.id));
    const target = form.elements.target_model;
    target.innerHTML = targetOptions(targetChoices(moduleName, saved), "", Boolean(moduleName));
    target.disabled = !moduleName;
  };

  ui.renderers.destinationForm = () => {
    const editing = ui.config.screen === "destination_edit";
    const row = editing ? ui.destination(ui.config.recordId) : { name: "", module_name: "", target_model: "", description: "", is_active: true };
    if (!row) return ui.missing("destinations");
    return ui.heading(editing ? "Edit destination" : "Add destination", "Define one module and record type that a document can be routed to.") + `<div class="router-form-layout"><form class="card router-form" id="router-config-form" data-kind="destinations" data-id="${editing ? row.id : ""}"><div class="card-header"><h2 class="fs-9 mb-0">Destination details</h2></div><div class="card-body"><div id="router-form-error" class="alert alert-danger" role="alert" tabindex="-1" hidden></div>${field("Name", "name", row.name, "A clear name that reviewers can recognize.", { required: true })}${destinationSelectors(row)}${field("Description", "description", row.description, "Explain the purpose of this destination.", { textarea: true })}${activeField(row)}</div>${formFooter("destinations", row)}</form><aside class="router-form-help"><h2>Room for more modules</h2><p>Each destination identifies one record type in one module. You can configure several destinations within the same module.</p><p>A single document can belong to multiple destinations. For example, a delivery receipt may support supplier matching and inventory receiving.</p><hr><p class="mb-0">Configuration is saved in the application database. Use the Routing rules tab to describe which documents should match.</p></aside></div>`;
  };

  const encoderFields = row => {
    const active = ui.destination(Number(row.destination_id))?.module_name === 'encoder';
    const connections = ui.state.encoder_connections || [];
    const connection = connections.find(item => item.id === Number(row.encoder_connection));
    return `<div id="router-encoder-fields" ${active ? '' : 'hidden'}><p class="text-600 fs-10">Routing prepares and validates the payload automatically. Missing values are handled in Encoder chat. External execution still requires confirmation.</p><label class="form-label" for="router-encoder-connection">MCP connection *</label><select class="form-select mb-3" id="router-encoder-connection" name="encoder_connection" ${active ? 'required' : 'disabled'}><option value="">Choose an MCP connection</option>${connections.map(item=>`<option value="${item.id}" ${item.id===Number(row.encoder_connection)?'selected':''}>${e(item.name)}</option>`).join('')}</select><label class="form-label" for="router-encoder-tool">Permitted operation *</label><select class="form-select mb-3" id="router-encoder-tool" name="encoder_tool" ${active ? 'required' : 'disabled'}><option value="">Choose a permitted operation</option>${(connection?.tools || []).map(tool=>`<option value="${e(tool.name)}" ${tool.name===row.encoder_tool?'selected':''}>${e(tool.label)}</option>`).join('')}</select><p class="form-text">Only enabled connections and permitted tools are listed. Configure and test them in Encoder → MCP connections.</p></div>`;
  };
  ui.changeEncoderScope = form => {
    const row = {destination_id:Number(form.elements.destination_id.value), encoder_connection:form.elements.encoder_connection?.value, encoder_tool:''};
    document.getElementById('router-encoder-fields').outerHTML = encoderFields(row);
  };
  ui.renderers.ruleForm = () => {
    const editing = ui.config.screen === "rule_edit";
    const row = editing ? ui.state.rules.find(rule => rule.id === ui.config.recordId) : { name: "", destination_id: "", document_type: "", instructions: "", examples: "", is_active: true };
    if (!row) return ui.missing("rules");
    return ui.heading(editing ? "Edit routing rule" : "Add routing rule", "Describe the documents that belong at a destination, using plain language.") + `<div class="router-form-layout"><form class="card router-form" id="router-config-form" data-kind="rules" data-id="${editing ? row.id : ""}"><div class="card-header"><h2 class="fs-9 mb-0">Rule details</h2></div><div class="card-body"><div id="router-form-error" class="alert alert-danger" role="alert" tabindex="-1" hidden></div>${field("Rule name", "name", row.name, "", { required: true })}<div class="mb-3"><label class="form-label" for="router-destination">Destination <span class="text-danger" aria-hidden="true">*</span></label><select id="router-destination" name="destination_id" class="form-select" required><option value="">Choose a destination</option>${ui.state.destinations.map(dest => `<option value="${dest.id}" ${row.destination_id === dest.id ? "selected" : ""}>${e(dest.name)} · ${e(ui.moduleLabel(dest.module_name))}${dest.is_active ? "" : " (inactive)"}</option>`).join("")}</select></div>${encoderFields(row)}${field("Document type", "document_type", row.document_type, "Business type, such as delivery receipt or sales invoice. Optional.", { max: 100 })}${field("Routing instructions", "instructions", row.instructions, "Explain who issued the document, who received it, and when this destination should be excluded.", { textarea: true, required: true })}${field("Examples", "examples", row.examples, "Give positive and negative examples to reduce ambiguity.", { textarea: true })}${activeField(row)}</div>${formFooter("rules", row)}</form><aside class="router-form-help"><h2>Make the distinction clear</h2><p>“Sales invoice” can describe a supplier invoice or a company invoice. Describe the issuer and recipient to tell them apart.</p><p><strong>Example instruction</strong><br>Include invoices issued by a supplier to Bizmatic Trading. Exclude invoices issued by Bizmatic Trading to customers.</p><hr><p class="mb-0">Rules can overlap across modules. Disabling a rule keeps it available for editing. Existing attempt snapshots stay as they were.</p></aside></div>`;
  };

  ui.submitConfiguration = async form => {
    const data = new FormData(form), kind = form.dataset.kind, id = Number(form.dataset.id);
    const error = message => { const node = document.getElementById("router-form-error"); node.textContent = message; node.hidden = false; node.focus(); };
    const row = Object.fromEntries([...data.entries()].map(([key, value]) => [key, String(value).trim()]));
    row.is_active = data.has("is_active");
    if (!row.name || (kind === "rules" && !row.instructions)) return error("Enter a name and complete the required fields.");
    if (kind === "destinations") {
      if (!row.module_name || !row.target_model) return error("Choose a module and a target model.");
      if (ui.state.destinations.some(dest => dest.id !== id && dest.module_name.toLowerCase() === row.module_name.toLowerCase() && dest.target_model.toLowerCase() === row.target_model.toLowerCase())) return error("This module and model already have a destination. Edit the existing destination instead.");
    } else {
      row.destination_id = Number(row.destination_id);
      if (!ui.destination(row.destination_id)) return error("Choose an existing destination.");
    }
    const current = id ? ui.state[kind].find(item => item.id === id) : null;
    row.revision = current?.revision;
    const controls = [...form.elements];
    const disabled = controls.map(control => control.disabled);
    controls.forEach(control => { control.disabled = true; });
    try {
      await ui.post(ui.apiURL(id ? "configurationEdit" : "configuration", id, kind), row);
      ui.configurationDirty = false;
      location.assign(ui.url(kind));
    } catch (failure) {
      controls.forEach((control, index) => { control.disabled = disabled[index]; });
      error(failure.message);
    }

  };
})();
