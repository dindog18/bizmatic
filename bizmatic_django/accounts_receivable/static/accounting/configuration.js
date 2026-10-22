/* Configuration UX prototype: no fetch, provider calls, imports, or server writes. */
(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('finance-config').textContent);
  if (config.resource !== 'configuration') return;
  const root = document.getElementById('finance-root');
  const catalog = config.configurationCatalog;
  const schema = window.BizmaticConfigurationSchema;
  const activity = window.BizmaticLLMLogs;
  const storageKey = `bizmatic-configuration-v1-${config.mode}`;
  const baseURL = config.routes.configuration;
  const parameters = new URLSearchParams(location.search);
  const partyKey = config.mode === 'ar' ? 'customer' : 'supplier';
  let parties;
  try { parties = JSON.parse(sessionStorage.getItem(`bizmatic-finance-v2-${config.mode}`))?.parties; } catch { /* Use synthetic accounts below. */ }
  parties = Array.isArray(parties) ? parties : window.BizmaticFinanceDemo(config.mode).parties;
  let state;
  try { state = JSON.parse(sessionStorage.getItem(storageKey)); } catch { /* New local preview. */ }
  if (!state || !Array.isArray(state.profiles)) state = {profiles:schema.initial(catalog), pending:null};
  let draft = null;
  let step = Math.min(3,Math.max(0,Math.trunc(Number(parameters.get('step'))) || 0));
  let chatInput = '';
  let chatFeedback = '';
  const esc = (value='') => String(value ?? '').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const icon = name => `<span class="fas fa-${name}" aria-hidden="true"></span>`;
  const link = (href,text,primary=false) => `<a class="btn ${primary?'btn-primary':'btn-falcon-default'}" href="${esc(href)}">${text}</a>`;
  const targetFor = profile => catalog.find(target=>target.key===profile.target_entity);
  const sourceLabel = value => value==='database'?'Database mapping':'Document context';
  const scopeLabel = profile => profile.scope==='module'?`All ${config.party.toLowerCase()}s (module default)`:`${parties.find(p=>String(p.id)===profile.scope)?.name || 'Account unavailable'} (sample account)`;
  const splitColumns = text => [...new Set(String(text || '').split(/[\n,]/).map(value=>value.trim()).filter(Boolean))];
  const joinPairs = text => String(text || '').split(',').map(pair=>pair.split('=').map(value=>value.trim())).filter(pair=>pair.length===2 && pair.every(Boolean)).map(([header_column,line_column])=>({header_column,line_column}));
  const get = (object,path) => path.split('.').reduce((value,key)=>value?.[key],object) ?? '';
  function set(object,path,value) { const keys=path.split('.'); const last=keys.pop(); let parent=object; for(const key of keys) parent=parent[key] ||= {}; parent[last]=value; }
  const same = (a,b) => JSON.stringify(a)===JSON.stringify(b);
  const status = profile => `<span class="finance-status ${profile.status==='submitted'?'success':'info'}">${profile.status==='submitted'?'Submitted · preview':'Draft'}</span>`;
  function notify(message) { const element=document.getElementById('finance-toast'); element.textContent=message; element.hidden=false; setTimeout(()=>{element.hidden=true;},4500); }
  function persist() {
    try { sessionStorage.setItem(storageKey,JSON.stringify(state)); const saved=root.querySelector('#config-save-state');if(saved)saved.textContent='Saved in this tab';const output=root.querySelector('#config-output');if(output&&draft)output.textContent=JSON.stringify(payload(),null,2);return true; }
    catch { const saved=root.querySelector('#config-save-state');if(saved)saved.textContent='Could not save locally';error('Browser storage is unavailable. Export your draft to keep it before leaving this page.');return false; }
  }
  function error(message) { let element=root.querySelector('#config-error');if(!element){root.insertAdjacentHTML('afterbegin','<div id="config-error" class="finance-form-error" role="alert" tabindex="-1"></div>');element=root.querySelector('#config-error');}element.hidden=false;element.textContent=message;element.focus(); }
  function edited() {
    if(draft.status==='submitted'){draft.revision+=1;draft.status='draft';}
    if(draft.id===null)state.pending=draft;
    persist();
  }
  function hasContent(profile) {
    return Boolean(profile.name || profile.description || profile.table || profile.columns || profile.document_type || profile.extraction_context || profile.sample_text || profile.assistant_messages.length || Object.keys(profile.field_mappings).length || !same(profile.encoding_rules,schema.blank(targetFor(profile)).encoding_rules));
  }
  function assignId(profile) { if(profile.id===null){profile.id=Math.max(0,...state.profiles.map(p=>p.id))+1;state.profiles.push(profile);if(state.pending===profile)state.pending=null;} }
  function rememberURL() { const route=draft.id===null?config.configurationCreate:baseURL+draft.id+'/';history.replaceState(null,'',`${route}?step=${step}`); }
  function saveDraft() { assignId(draft); if(persist()){rememberURL();render();notify('Configuration draft saved in this tab.');} }
  function field(path,label,value='',options={}) {
    const id='config-'+path.replaceAll('.','-');
    const common=`id="${id}" aria-label="${esc(label)}" data-path="${path}" aria-required="${Boolean(options.required)}" class="${options.code?'config-code-input ':''}${options.choices?'form-select':'form-control'}"`;
    let control;
    if(options.choices)control=`<select ${common} ${options.disabled?'disabled':''}>${options.choices.map(choice=>{const [key,text]=Array.isArray(choice)?choice:[choice,choice];return `<option value="${esc(key)}" ${String(key)===String(value)?'selected':''}>${esc(text)}</option>`;}).join('')}</select>`;
    else if(options.textarea)control=`<textarea ${common} rows="${options.rows || 3}" placeholder="${esc(options.placeholder || '')}">${esc(value)}</textarea>`;
    else control=`<input ${common} type="text" value="${esc(value)}" maxlength="${options.maxlength || 255}" placeholder="${esc(options.placeholder || '')}" ${options.list?`list="${options.list}"`:''}>`;
    return `<div class="finance-field ${options.full?'full':''}"><label for="${id}">${esc(label)}${options.required?' <span aria-hidden="true" class="text-danger">*</span>':''}</label>${control}${options.hint?`<small>${esc(options.hint)}</small>`:''}</div>`;
  }
  const card = (title,body,action='')=>`<section class="card mb-3"><div class="finance-card-head"><h2>${title}</h2>${action}</div>${body}</section>`;
  function list() {
    root.innerHTML=`<header class="finance-heading"><div><h1>Extraction configuration</h1><p>Define how source data becomes ${config.party.toLowerCase()}s, orders, deliveries, invoices, and payments.</p></div><div class="finance-actions">${link(config.configurationCreate+'?fresh=1',icon('plus')+' New configuration',true)}</div></header><div class="finance-callout">Configure the inputs here. Extracted accounting records remain read-only. Assistant suggestions become draft changes only when you apply them; final submission is always yours.</div><div class="config-targets">${catalog.map(target=>{const count=state.profiles.filter(p=>p.target_entity===target.key).length;return `<a class="config-target" href="${esc(config.configurationCreate+'?target='+target.key)}">${icon({customer:'address-book',supplier:'address-book',purchase_order:'shopping-cart',delivery_receipt:'truck',sales_invoice:'file-invoice-dollar',payment:'credit-card'}[target.key])}<strong>${esc(target.label)}</strong><small>${count} configuration${count===1?'':'s'} · Configure ${icon('arrow-right')}</small></a>`;}).join('')}</div>${state.pending?`<div class="finance-callout">You have an unfinished configuration for ${esc(targetFor(state.pending).label.toLowerCase())}. ${link(config.configurationCreate,'Continue draft')}</div>`:''}${card('Your configurations',`<div class="finance-toolbar"><label class="visually-hidden" for="config-search">Search configurations</label><input class="form-control" type="search" id="config-search" placeholder="Search name, target, or source"></div><div id="configuration-list"></div>`)}`;
    const renderRows=query=>{const rows=state.profiles.filter(profile=>`${profile.name} ${targetFor(profile).label} ${sourceLabel(profile.source_type)}`.toLowerCase().includes(query.toLowerCase()));root.querySelector('#configuration-list').innerHTML=`<div class="table-responsive"><table class="table finance-table"><caption class="visually-hidden">Local extraction configuration profiles</caption><thead><tr><th>Configuration</th><th>Target</th><th>Source</th><th>Status</th><th></th></tr></thead><tbody>${rows.map(profile=>`<tr><td><a class="primary-link" href="${baseURL+profile.id+'/'}">${esc(profile.name || 'Untitled configuration')}</a><span class="subtext">${esc(scopeLabel(profile))} · Revision ${profile.revision}</span></td><td>${esc(targetFor(profile).label)}</td><td>${sourceLabel(profile.source_type)}</td><td>${status(profile)}</td><td><a href="${baseURL+profile.id+'/'}">Configure ${icon('arrow-right')}</a></td></tr>`).join('') || '<tr><td colspan="5" class="text-center p-4 text-600">No matching configurations. Create one using the button above.</td></tr>'}</tbody></table></div>`;};
    renderRows('');root.querySelector('#config-search').addEventListener('input',event=>renderRows(event.target.value));
  }
  function sourceStep() {
    const target=targetFor(draft);
    const common=`<div class="finance-form-grid">${field('name','Configuration name',draft.name,{required:true,full:true,placeholder:'e.g. Sales invoices · ERP mapping'})}${field('target_entity','Record type',draft.target_entity,{choices:catalog.map(t=>[t.key,t.label]),disabled:draft.id!==null,hint:draft.id!==null?'Create a new configuration to target another record type.':''})}${field('scope','Applies to',draft.scope,{choices:[['module',`All ${config.party.toLowerCase()}s`],...parties.map(p=>[p.id,p.name+' (sample)'])]})}${field('description','Purpose / existing business context',draft.description,{textarea:true,full:true,placeholder:'Describe this data source, document layout, or business convention.'})}</div>`;
    const toggle=`<div class="config-source-toggle" role="group" aria-label="Configuration source"><button type="button" data-source="database" aria-pressed="${draft.source_type==='database'}">${icon('database')} Database mapping</button><button type="button" data-source="document" aria-pressed="${draft.source_type==='document'}">${icon('file-alt')} Document extraction context</button></div>`;
    const source=draft.source_type==='database'?`<div class="finance-callout">Describe the header and line tables, then map their columns. This preview uses editable sample schema metadata; it does not connect to a database.</div><div class="finance-actions mb-3"><button class="btn btn-falcon-default" type="button" data-use-sample>${icon('table')} Use sample schema</button>${link(config.sources.databases,'Browse database connections')}</div><div class="finance-form-grid">${field('connection','Connection reference',draft.connection,{required:true,placeholder:'ERP connection name'})}${field('table','Header table (schema.table)',draft.table,{required:true,code:true,placeholder:'public.invoices'})}${field('source_keys','Header record key columns',draft.source_keys,{required:true,full:true,code:true,placeholder:'id, company_id',hint:'Comma-separated columns. Composite keys are supported.'})}${field('columns','Header columns',draft.columns,{required:true,textarea:true,full:true,code:true,rows:5,placeholder:'One column per line',hint:'Paste observed column names or use the sample. Suggestions use this list, not a live schema.'})}${target.lineModel?`<div class="full"><label class="form-check"><input class="form-check-input" type="checkbox" data-path="include_lines" ${draft.include_lines?'checked':''}><span class="form-check-label">Configure ${esc(target.lineModel)} line items</span></label></div>${draft.include_lines?`${field('line_table','Line table (schema.table)',draft.line_table,{required:true,code:true})}${field('line_joins','Header → line join',draft.line_joins,{required:true,code:true,placeholder:'id=invoice_id',hint:'Pairs such as id=invoice_id, company_id=company_id.'})}${field('line_columns','Line columns',draft.line_columns,{required:true,textarea:true,full:true,code:true,rows:4,placeholder:'One column per line'})}`:''}`:''}</div>`:`<div class="finance-callout">Describe what to read, how to distinguish similar fields, and when to request review. These instructions configure future extraction; no documents are processed here.</div><div class="finance-form-grid">${field('document_type','Document type / layout',draft.document_type,{required:true,full:true,placeholder:'e.g. Sales invoice · Supplier A layout'})}${field('sample_text','Optional example text',draft.sample_text,{textarea:true,full:true,rows:5,placeholder:'Paste a short example to give the assistant more context.',hint:'Used as configuration context only. This preview does not extract data from the example.'})}</div><div class="finance-actions mt-3">${link(config.sources.documents,'Browse documents')}${link(config.sources.upload,'Open document upload')}</div>`;
    return card('1. Record and source',`<div class="finance-card-body">${common}<hr class="my-4">${toggle}${source}</div>`);
  }
  function mappingTable(fields,line=false) {
    const map=line?draft.line_item_mappings:draft.field_mappings;
    const prefix=line?'line_item_mappings':'field_mappings';const listId=line?'config-line-columns':'config-header-columns';
    const options=['trim','identity','uppercase','date','datetime','decimal','integer','boolean','json','lookup'];
    return `<datalist id="${listId}">${splitColumns(line?draft.line_columns:draft.columns).map(column=>`<option value="${esc(column)}"></option>`).join('')}</datalist><div class="table-responsive"><table class="table finance-table config-map-table"><caption class="visually-hidden">${line?'Line item':'Header'} field mappings</caption><thead><tr><th>Destination field</th><th>Source column</th><th>Transform</th><th>Default</th><th>Required</th></tr></thead><tbody>${fields.map(fieldInfo=>{const value=map[fieldInfo.key] || {};return `<tr><td><strong>${esc(fieldInfo.label)}</strong>${fieldInfo.required?' <span class="text-danger">*</span>':''}<code>${esc(fieldInfo.key)}</code>${fieldInfo.type==='lookup'?`<span class="subtext">Lookup: ${esc(draft.relation_lookups[fieldInfo.key]?.match_field || partyKey+'_code')}</span>`:''}</td><td><input class="form-control config-code-input" data-path="${prefix}.${fieldInfo.key}.source" list="${listId}" aria-label="${line?'Line ':''}${esc(fieldInfo.key)} source column" value="${esc(value.source || '')}" placeholder="Select or enter column"></td><td><select class="form-select" data-path="${prefix}.${fieldInfo.key}.transform" aria-label="${line?'Line ':''}${esc(fieldInfo.key)} transform" ${fieldInfo.type==='lookup'?'disabled':''}>${options.map(option=>`<option value="${option}" ${(value.transform || schema.transform(fieldInfo))===option?'selected':''}>${{identity:'As is',trim:'Trim text',uppercase:'Uppercase',date:'Date',datetime:'Date & time',decimal:'Decimal',integer:'Integer',boolean:'Boolean',json:'JSON',lookup:'Account lookup'}[option]}</option>`).join('')}</select></td><td><input class="form-control config-default" data-path="${prefix}.${fieldInfo.key}.default" aria-label="${line?'Line ':''}${esc(fieldInfo.key)} default" value="${esc(value.default ?? '')}" placeholder="Optional"></td><td class="text-center"><input class="form-check-input" type="checkbox" data-required="${fieldInfo.key}" data-required-group="${line?'line':'header'}" aria-label="Require ${line?'line ':''}${esc(fieldInfo.key)}" ${(line?draft.encoding_rules.line_required_fields:draft.encoding_rules.required_fields).includes(fieldInfo.key)?'checked':''} ${fieldInfo.required?'disabled':''}></td></tr>`;}).join('')}</tbody></table></div>`;
  }
  function mappingStep() {
    const target=targetFor(draft);
    if(draft.source_type==='database')return card('2. Map source columns',`<div class="finance-card-body"><p class="text-600 mb-0">Map columns to <code>${esc(target.model)}</code>. Required destination fields need a source or a default. Account relationships use your configured lookup rules; external IDs are not copied into local foreign keys.</p></div>${mappingTable(target.fields)}${target.lineModel&&draft.include_lines?`<details class="config-disclosure" open><summary>Line item mappings · ${esc(target.lineModel)}</summary><div class="mt-3">${mappingTable(target.lineFields,true)}</div></details>`:''}<div class="finance-card-body"><p class="config-note mb-0">Need a starting point? Ask the assistant to suggest mappings from the column names you provided. Existing mappings are preserved unless you explicitly choose to replace them.</p></div>`);
    const instructions=(fields,line=false)=>fields.map(fieldInfo=>`<div class="config-instruction"><label for="${line?'line-instruction':'instruction'}-${fieldInfo.key}">${esc(fieldInfo.label)}<code aria-hidden="true">${esc(fieldInfo.key)}</code></label><textarea class="form-control" rows="2" id="${line?'line-instruction':'instruction'}-${fieldInfo.key}" data-path="${line?'line_field_instructions':'field_instructions'}.${fieldInfo.key}" placeholder="Optional: where to find this field, aliases, and ambiguity rules">${esc((line?draft.line_field_instructions:draft.field_instructions)[fieldInfo.key] || '')}</textarea></div>`).join('');
    return card('2. Write extraction instructions',`<div class="finance-card-body"><div class="finance-form-grid">${field('extraction_context','Overall extraction context',draft.extraction_context,{required:true,textarea:true,full:true,rows:6,placeholder:'Explain the document layout, reference labels, date conventions, and what must be flagged for user review.'})}${target.lineModel?field('line_item_context','Line item instructions',draft.line_item_context,{required:true,textarea:true,full:true,rows:4,placeholder:'Explain repeated item rows, units, accepted quantities, taxes, and rows to exclude.'}):''}</div></div><details class="config-disclosure" open><summary>Field-specific guidance · ${esc(target.model)}</summary><div class="config-instructions mt-3">${instructions(target.fields)}</div></details>${target.lineModel?`<details class="config-disclosure"><summary>Line-specific field guidance</summary><div class="config-instructions mt-3">${instructions(target.lineFields,true)}</div></details>`:''}`);
  }
  function rulesStep() {
    const target=targetFor(draft);const choices=draft.source_type==='document'?`<div class="config-instructions mt-3">${target.fields.map(info=>`<label class="form-check"><input class="form-check-input" type="checkbox" data-required="${info.key}" ${draft.encoding_rules.required_fields.includes(info.key)?'checked':''} ${info.required?'disabled':''}><span class="form-check-label">Require ${esc(info.label.toLowerCase())} <code>${esc(info.key)}</code></span></label>`).join('')}</div>`:'';
    const lineChoices=draft.source_type==='document'&&target.lineModel?`<h3 class="fs-10 mt-4">Required line item fields</h3><div class="config-instructions mt-3">${target.lineFields.map(info=>`<label class="form-check"><input class="form-check-input" type="checkbox" data-required="${info.key}" data-required-group="line" ${draft.encoding_rules.line_required_fields.includes(info.key)?'checked':''} ${info.required?'disabled':''}><span class="form-check-label">Require line ${esc(info.label.toLowerCase())} <code>${esc(info.key)}</code></span></label>`).join('')}</div>`:'';
    return card('3. Encoding and review rules',`<div class="finance-card-body"><p class="text-600">Configure normalization and review behavior for future data entry. These settings do not encode or import accounting records in this preview.</p><div class="finance-form-grid">${field('encoding_rules.date_format','Source date format',draft.encoding_rules.date_format,{choices:['YYYY-MM-DD','DD/MM/YYYY','MM/DD/YYYY']})}${field('encoding_rules.default_currency','Default currency',draft.encoding_rules.default_currency,{maxlength:3,hint:'Three-letter uppercase currency code, e.g. PHP.'})}${field('encoding_rules.decimal_separator','Decimal separator',draft.encoding_rules.decimal_separator,{choices:[['.','Period · 1,234.56'],[',','Comma · 1.234,56']]})}${field('encoding_rules.thousands_separator','Thousands separator',draft.encoding_rules.thousands_separator,{choices:[['','None'],[',','Comma'],['.','Period'],[' ','Space']]})}${field('encoding_rules.duplicate_policy','When a reference already exists',draft.encoding_rules.duplicate_policy,{choices:[['review','Ask the user to review'],['skip','Skip duplicate records'],['update_existing','Propose updates for user review']]})}${field('encoding_rules.missing_value_policy','When required information is missing','review',{choices:[['review','Hold for user review']]})}</div>${target.fields.filter(info=>info.type==='lookup').map(info=>`<div class="mt-3">${field('relation_lookups.'+info.key+'.match_field',info.label+' lookup field',draft.relation_lookups[info.key]?.match_field || partyKey+'_code',{choices:[[partyKey+'_code',config.party+' code'],['tax_identification_no','Tax identification no.'],[partyKey+'_name',config.party+' name']],hint:'Unknown or ambiguous matches are held for review; this does not create accounts.'})}</div>`).join('')}${choices}${lineChoices}<div class="finance-callout mt-4 mb-0">Account identifiers must resolve to an existing ${config.party.toLowerCase()} using your selected lookup field. Unknown accounts, ambiguous dates, and missing required values are held for review. The assistant cannot submit configurations or create accounting records.</div></div>`);
  }
  function validation() {
    const target=targetFor(draft);const issues=[];
    const add=(message,at)=>issues.push({message,step:at});
    if(!draft.name.trim())add('Give this configuration a name.',0);
    if(draft.name.length>160)add('Keep the configuration name within 160 characters.',0);
    if(draft.source_type==='database') {
      const columns=splitColumns(draft.columns);const lineColumns=splitColumns(draft.line_columns);
      if(!draft.connection.trim())add('Enter a connection reference or choose the sample schema.',0);
      if(!draft.table.trim())add('Enter the header table name.',0);
      if(!columns.length)add('Provide header column names so mappings can be checked.',0);
      const keys=splitColumns(draft.source_keys);
      if(!keys.length)add('Choose at least one source record key.',0);
      keys.filter(key=>!columns.includes(key)).forEach(key=>add(`Header key “${key}” is not in the provided columns.`,0));
      for(const fieldInfo of target.fields) {
        const mapping=draft.field_mappings[fieldInfo.key] || {};
        const hasDefault=String(mapping.default ?? '').trim()!=='' || (fieldInfo.key==='currency'&&draft.encoding_rules.default_currency);
        if(draft.encoding_rules.required_fields.includes(fieldInfo.key)&&!mapping.source&&!hasDefault)add(`Map ${fieldInfo.label.toLowerCase()} or supply a default.`,1);
        if(mapping.source&&!columns.includes(mapping.source))add(`“${mapping.source}” for ${fieldInfo.key} is not in the provided header columns.`,1);
        if(fieldInfo.type==='lookup'&&mapping.default)add(`Use a source account code, rather than a raw default ID, for ${fieldInfo.key}.`,1);
      }
      if(target.lineModel&&draft.include_lines) {
        if(!draft.line_table.trim())add('Enter the line table name.',0);
        if(!lineColumns.length)add('Provide line column names.',0);
        const pairs=joinPairs(draft.line_joins);
        if(!pairs.length || pairs.length!==draft.line_joins.split(',').filter(value=>value.trim()).length)add('Use valid header=line column pairs for the line join.',0);
        pairs.forEach(pair=>{if(!columns.includes(pair.header_column)||!lineColumns.includes(pair.line_column))add(`Join ${pair.header_column}=${pair.line_column} must use columns from the two provided tables.`,0);});
        target.lineFields.forEach(fieldInfo=>{const mapping=draft.line_item_mappings[fieldInfo.key] || {};if(draft.encoding_rules.line_required_fields.includes(fieldInfo.key)&&!mapping.source&&String(mapping.default ?? '').trim()==='')add(`Map required line field ${fieldInfo.key}.`,1);if(mapping.source&&!lineColumns.includes(mapping.source))add(`“${mapping.source}” is not in the provided line columns.`,1);});
      }
    } else {
      if(!draft.document_type.trim())add('Specify the document type or layout.',0);
      if(!draft.extraction_context.trim())add('Write overall extraction instructions.',1);
      if(target.lineModel&&!draft.line_item_context.trim())add('Describe how to identify and interpret line items.',1);
    }
    if(!/^[A-Z]{3}$/.test(draft.encoding_rules.default_currency))add('Use a three-letter uppercase currency code.',2);
    if(draft.encoding_rules.thousands_separator&&draft.encoding_rules.thousands_separator===draft.encoding_rules.decimal_separator)add('Decimal and thousands separators must differ.',2);
    return issues;
  }
  function normalizedMappings(fields,mappings) {
    return Object.fromEntries(fields.filter(fieldInfo=>{const value=mappings[fieldInfo.key];return value&&(value.source || String(value.default ?? '')!=='');}).map(fieldInfo=>{
      const value=mappings[fieldInfo.key];return [fieldInfo.key,{source:value.source || '',transform:fieldInfo.type==='lookup'?'lookup':value.transform || schema.transform(fieldInfo),default:value.default ?? ''}];
    }));
  }
  function payload(statusOverride=null,submittedAt=null) {
    const target=targetFor(draft);const database=draft.source_type==='database';
    const mappings=database?normalizedMappings(target.fields,draft.field_mappings):{};
    const lookups=Object.fromEntries(target.fields.filter(info=>info.type==='lookup').map(info=>[info.key,{match_field:draft.relation_lookups[info.key]?.match_field || `${partyKey}_code`,on_missing:'review'}]));
    const reference={account_scope:scopeLabel(draft),connection:database?draft.connection:'',header_table:database?draft.table:'',line_table:database&&draft.include_lines?draft.line_table:''};
    return {
      preview_only:true, model:`${config.mode==='ar'?'accounts_receivable':'accounts_payable'}.ExtractionConfiguration`,
      unresolved_references:reference,
      configuration:{name:draft.name,description:draft.description,target_entity:draft.target_entity,source_type:draft.source_type,[partyKey]:null,
        database_source:null,source_table:null,line_source_table:null,
        source_schema_snapshot:{...reference,preview_only:true,header_columns:database?splitColumns(draft.columns):[],line_columns:database&&draft.include_lines?splitColumns(draft.line_columns):[]},
        source_key_fields:database?splitColumns(draft.source_keys):[],field_mappings:mappings,
        line_item_mappings:database&&draft.include_lines?normalizedMappings(target.lineFields,draft.line_item_mappings):{},line_join_fields:database&&draft.include_lines?joinPairs(draft.line_joins):[],relation_lookups:lookups,
        document_type:database?'':draft.document_type,extraction_context:database?'':draft.extraction_context,field_instructions:database?{}:draft.field_instructions,line_field_instructions:database?{}:draft.line_field_instructions,line_item_context:database?'':draft.line_item_context,sample_text:database?'':draft.sample_text,
        encoding_rules:structuredClone(draft.encoding_rules),assistant_messages:structuredClone(draft.assistant_messages),assistant_proposal:structuredClone(draft.assistant_proposal || {}),
        status:statusOverride || draft.status,revision:draft.revision,submitted_at:submittedAt || draft.submitted_at,submitted_by:null},
    };
  }
  function reviewStep() {
    const issues=validation();const output=payload();
    return card('4. Review your configuration',`<div class="finance-card-body">${issues.length?`<div class="config-validation" role="status"><strong>${issues.length} item${issues.length===1?'':'s'} to complete</strong><ul>${issues.map(issue=>`<li><a href="#" data-goto-step="${issue.step}">${esc(issue.message)}</a></li>`).join('')}</ul></div>`:'<div class="config-submitted">Configuration fields are complete. Review the output below before submitting this preview.</div>'}<dl class="config-review-list"><div><dt>Destination model</dt><dd>${esc(targetFor(draft).model)}</dd></div><div><dt>Source</dt><dd>${sourceLabel(draft.source_type)}</dd></div><div><dt>Scope</dt><dd>${esc(scopeLabel(draft))}</dd></div><div><dt>Required fields</dt><dd>${draft.encoding_rules.required_fields.length} header · ${draft.encoding_rules.line_required_fields.length} line</dd></div></dl><div class="finance-callout mb-0">This checks configuration completeness and names against the columns you supplied. Live schema checks, sample extraction, database ID resolution, and activation require the future backend. Submitting here saves a reviewed snapshot in this tab only.</div></div><details class="config-disclosure" open><summary>Configuration output · exact current draft</summary><pre class="config-json mt-3" id="config-output">${esc(JSON.stringify(output,null,2))}</pre></details>${draft.submitted_snapshot?`<details class="config-disclosure"><summary>Last user-submitted snapshot · revision ${draft.submitted_snapshot.configuration.revision}</summary><pre class="config-json mt-3">${esc(JSON.stringify(draft.submitted_snapshot,null,2))}</pre></details>`:''}`,`<button class="btn btn-falcon-default btn-sm" type="button" data-export>${icon('download')} Export JSON</button>`);
  }
  function fingerprint() {
    const {assistant_messages,assistant_proposal,status,revision,id,submitted_snapshot,submitted_at,...context}=draft;
    return JSON.stringify(context);
  }
  function assistant() {
    const mapped=Object.values(draft.field_mappings).filter(value=>value.source || value.default).length;
    const messages=draft.assistant_messages;
    const proposal=draft.assistant_proposal;
    const proposalMarkup=proposal?`<section class="config-proposal" aria-label="Assistant proposed changes"><div class="config-proposal-head"><strong>Proposed changes</strong><div class="config-note mt-1">Choose what to apply. Replacements of existing input start unchecked.</div></div><div class="config-proposal-changes">${proposal.changes.map((change,index)=>`<div class="config-proposal-row"><input class="form-check-input" type="checkbox" id="proposal-${index}" data-proposal-index="${index}" ${change.selected?'checked':''}><label for="proposal-${index}"><strong>${esc(change.label)}</strong>${change.before?`<span class="proposal-before">Current: ${esc(change.before)}</span>`:'<span class="text-600 d-block mt-1">Currently empty</span>'}<span class="proposal-after">Proposed: ${esc(change.after)}</span></label></div>`).join('')}</div><div class="config-proposal-footer"><button class="btn btn-primary btn-sm" type="button" data-apply-proposal>Apply selected to draft</button><button class="btn btn-link btn-sm" type="button" data-dismiss-proposal>Dismiss</button></div></section>`:'';
    return `<aside class="config-assistant"><section class="card"><div class="finance-card-head"><div><h2>${icon('magic')} Configuration assistant</h2><div class="finance-card-subtitle">Chat → proposed output → your review</div></div><span class="badge badge-subtle-secondary">Preview</span></div><div class="config-context">Uses your current ${esc(targetFor(draft).label.toLowerCase())} draft: ${mapped} mapped fields, ${draft.extraction_context.length} context characters, business notes, example text, rules, and conversation history.<br><strong>Local demo suggestions · No LLM is connected.</strong></div><div class="config-chat-log" id="config-chat-log" role="log" aria-live="polite">${messages.length?messages.map(message=>`<div class="config-chat-message ${message.role==='user'?'user':''}"><small>${message.role==='user'?'You':'Assistant preview'}</small>${esc(message.content)}${message.llm_log_no?`<a class="d-block mt-2" href="${activity.detailURL(message.llm_log_no)}">View attempt #${message.llm_log_no}</a>`:''}</div>`).join(''):'<div class="config-chat-message"><small>Assistant preview</small>Describe how your data is organized. I can propose mappings, extraction instructions, dates, and currency rules. I will preserve your existing inputs and show changes for you to accept.</div>'}</div><a class="llm-history-link" href="${draft.id===null?config.routes['llm-logs']:activity.configurationURL(draft.id)}">View ${draft.id===null?'all LLM activity':'this configuration’s attempt history'}</a><div class="config-chat-prompts">${(draft.source_type==='database'?['Suggest unmapped fields','Use PHP and DD/MM/YYYY','Explain review gaps']:['Draft extraction context','Use PHP and DD/MM/YYYY','Explain review gaps']).map(prompt=>`<button class="btn btn-falcon-default btn-sm" type="button" data-chat-prompt="${prompt}">${prompt}</button>`).join('')}</div>${proposalMarkup}<form id="config-chat-form" class="config-chat-controls"><label class="visually-hidden" for="config-chat-input">Message the configuration assistant</label><textarea id="config-chat-input" class="form-control mb-2" rows="3" maxlength="4000" placeholder="e.g. Map invoice_reference_no to invoice_no. Keep my current notes.">${esc(chatInput)}</textarea><div class="config-feedback" role="status">${esc(chatFeedback)}</div><button class="btn btn-primary w-100" type="submit">${icon('paper-plane')} Send message</button><p class="config-note mb-0">Suggestions never submit, activate, or import anything. Final submission is a separate user action.</p></form></section></aside>`;
  }
  function renderAssistant() {
    const old=root.querySelector('.config-assistant');if(old)old.outerHTML=assistant();bindAssistant();
  }
  function propose(message) {
    assignId(draft); rememberURL();
    const started = performance.now();
    const original = structuredClone(payload().configuration);
    const request = {message, conversation:structuredClone(draft.assistant_messages)};
    const target=targetFor(draft);const changes=[];let unmatched=[];
    const add=(path,title,value)=>{const before=get(draft,path);if(!same(before,value)&&!changes.some(change=>change.path===path))changes.push({path,label:title,before:structuredClone(before),after:value,selected:before==='' || before===null});};
    const currency=message.match(/(?:currency|use|in|set(?:\s+to)?)\s+([A-Z]{3})\b/i);
    if(currency)add('encoding_rules.default_currency','Default currency',currency[1].toUpperCase());
    const requestedDate=message.match(/YYYY-MM-DD|DD\/MM\/YYYY|MM\/DD\/YYYY/i);
    if(requestedDate)add('encoding_rules.date_format','Source date format',requestedDate[0].toUpperCase());
    const explain=/explain|review gaps|what.*missing/i.test(message);
    if(!explain&&draft.source_type==='database') {
      const explicit=[...message.matchAll(/(?:map\s+)?([a-z][a-z0-9_]+)\s*(?:to|=)\s*([a-z][a-z0-9_]+)/gi)];
      for(const [,destination,column] of explicit) {
        const info=target.fields.find(fieldInfo=>fieldInfo.key===destination);
        if(info&&splitColumns(draft.columns).includes(column))add(`field_mappings.${destination}.source`,`${info.label} source column`,column);
        else if(info)unmatched.push(column);
      }
      if(/suggest|unmapped|mapping|map fields|map.*column/i.test(message)) {
        const required=target.fields.filter(info=>draft.encoding_rules.required_fields.includes(info.key)).map(info=>({info,line:false}));
        const requiredLines=draft.include_lines?target.lineFields.filter(info=>draft.encoding_rules.line_required_fields.includes(info.key)).map(info=>({info,line:true})):[];
        const remaining=[...target.fields.filter(info=>!draft.encoding_rules.required_fields.includes(info.key)).map(info=>({info,line:false})),...(draft.include_lines?target.lineFields.filter(info=>!draft.encoding_rules.line_required_fields.includes(info.key)).map(info=>({info,line:true})):[])];
        for(const {info,line} of [...required,...requiredLines,...remaining]) {
          const path=`${line?'line_item_mappings':'field_mappings'}.${info.key}.source`;
          const current=get(draft,`${line?'line_item_mappings':'field_mappings'}.${info.key}`);
          if(current?.source || String(current?.default ?? '')!=='')continue;
          const columns=splitColumns(line?draft.line_columns:draft.columns);
          const column=columns.find(value=>value===schema.sourceColumn(info)) || columns.find(value=>value===info.key);
          if(column)add(path,`${line?'Line · ':''}${info.label} source column`,column);
          if(changes.length>=20)break;
        }
      }
    }
    if(!explain&&draft.source_type==='document'&&!currency&&!requestedDate) {
      const template=/draft|suggest|context|instructions/i.test(message)?`Extract ${target.label.toLowerCase()} from the labeled header and totals. Preserve identifiers exactly. Use the configured date and number formats. Resolve ${config.party.toLowerCase()} identifiers using the configured account lookup rules. Leave ambiguous or missing required values for user review.${draft.description.trim()?' Business context: '+draft.description.trim():''}${draft.sample_text.trim()?' Treat the supplied example as a layout reference; do not reuse its values for another document.':''}`:`Additional user guidance: ${message}`;
      if(!draft.extraction_context.includes(template))add('extraction_context','Overall extraction context',draft.extraction_context.trim()?draft.extraction_context.trim()+'\n\n'+template:template);
      if(target.lineModel&&!draft.line_item_context.trim())add('line_item_context','Line item instructions','Read one item per row; preserve item code, unit, and stated quantities. Do not treat subtotal, discount, or tax summary rows as items. Keep accepted and rejected delivery quantities separate and flag ambiguous rows.');
      const reference=schema.referenceField(target);
      if(reference&&!draft.field_instructions[reference.key])add(`field_instructions.${reference.key}`,`${reference.label} guidance`,`Read the labeled ${reference.label.toLowerCase()}. Preserve punctuation and leading zeros. Do not substitute another document's reference.`);
    }
    const issues=validation();
    const kept=Object.values(draft.field_mappings).filter(value=>value.source).length;
    let response=explain?issues.length?`Your draft has ${issues.length} review item(s):\n${issues.map(issue=>'• '+issue.message).join('\n')}\nI have not changed your inputs.`:'Your configuration fields are complete. Review the output yourself before submitting the preview. No live schema or extraction check has run.':changes.length?`I considered your current business notes, ${kept} existing mappings, extraction instructions, example text, rules, and conversation. I prepared ${changes.length} proposed change(s). Existing values are kept unless you explicitly select a replacement. Review and apply the changes below; this does not submit the configuration.`:'I kept your current inputs. No supported change was found. For database mappings, provide column names and try “Suggest unmapped fields” or “Map invoice_reference_no to invoice_no”. For document instructions, describe what should be read. This is a local preview, not a live LLM.';
    if(unmatched.length)response+=`\nThese requested columns are not in your provided schema: ${unmatched.join(', ')}. Add them to the schema if correct, then ask again.`;
    const run=activity.append({configuration:draft.id,configuration_revision:draft.revision,target_entity:draft.target_entity,source_type:draft.source_type,purpose:'configuration',provider:null,model_name:null,status:'completed',configuration_snapshot:original,request_payload:request,response_payload:{message:response,changes:structuredClone(changes)},markdown_text:response,input_tokens:null,output_tokens:null,processing_time_ms:Math.max(0,Math.round(performance.now()-started)),error_message:null,fk_document_no:null,source_llm_log:null,preview_reference:{record_label:draft.name || 'Untitled configuration',source_name:draft.source_type==='document'?draft.document_type:draft.table}});
    const proposal=changes.length?{baseContext:fingerprint(),changes,created_at:new Date().toISOString(),llm_log_no:run.llm_log_no}:null;
    draft.assistant_messages.push({role:'user',content:message},{role:'assistant',content:response,llm_log_no:run.llm_log_no});
    draft.assistant_proposal=proposal;persist();
  }
  function bindAssistant() {
    const form=root.querySelector('#config-chat-form');
    form.querySelector('textarea').addEventListener('input',event=>{chatInput=event.target.value;});
    const send=message=>{if(!message.trim()){chatFeedback='Write a message or choose a suggested prompt.';renderAssistant();return;}chatInput='';chatFeedback='';propose(message.trim());renderAssistant();};
    form.addEventListener('submit',event=>{event.preventDefault();send(chatInput);});
    root.querySelectorAll('[data-chat-prompt]').forEach(button=>button.addEventListener('click',()=>send(button.dataset.chatPrompt)));
    root.querySelectorAll('[data-proposal-index]').forEach(input=>input.addEventListener('change',()=>{draft.assistant_proposal.changes[Number(input.dataset.proposalIndex)].selected=input.checked;persist();}));
    root.querySelector('[data-dismiss-proposal]')?.addEventListener('click',()=>{activity.review(draft.assistant_proposal.llm_log_no,{disposition:'dismissed',decided_at:new Date().toISOString()});draft.assistant_proposal=null;persist();renderAssistant();});
    root.querySelector('[data-apply-proposal]')?.addEventListener('click',()=>{
      const proposal=draft.assistant_proposal;
      if(proposal.baseContext!==fingerprint()){chatFeedback='Your inputs changed after this proposal. Ask again so new suggestions use your latest draft.';renderAssistant();return;}
      const selected=proposal.changes.filter(change=>change.selected);
      if(!selected.length){chatFeedback='Select at least one proposed change to apply.';renderAssistant();return;}
      selected.forEach(change=>set(draft,change.path,change.after));
      activity.review(proposal.llm_log_no,{disposition:'applied to draft',applied_paths:selected.map(change=>change.path),decided_at:new Date().toISOString()});
      draft.assistant_messages.push({role:'assistant',content:`Applied ${selected.length} selected change(s) to your draft. All other inputs remain as you left them. Review and submit the configuration yourself when ready.`});
      draft.assistant_proposal=null;edited();chatFeedback='';render();notify('Selected suggestions applied to draft. Not submitted.');
    });
  }
  function submissionDialog() {
    return `<dialog class="config-submit" id="configuration-submit" aria-labelledby="configuration-submit-title"><form method="dialog" id="configuration-submit-form"><h2 id="configuration-submit-title">Submit this configuration?</h2><p>Submit <strong>${esc(draft.name)}</strong>, revision ${draft.revision}, for ${esc(targetFor(draft).label.toLowerCase())} using ${sourceLabel(draft.source_type).toLowerCase()}.</p><div class="finance-callout">This is a frontend preview. Your reviewed snapshot is saved in this browser tab. It is not sent to a server or activated for extraction. Unapplied assistant suggestions are not applied.</div><label class="form-check mb-3"><input class="form-check-input" type="checkbox" id="config-review-confirmation" required><span class="form-check-label">I reviewed the source, fields, instructions, and rules and want to submit this preview.</span></label><div class="finance-actions justify-content-end"><button class="btn btn-falcon-default" value="cancel" type="button" data-cancel-submit>Keep editing</button><button class="btn btn-primary" id="config-confirm-submit" type="submit" disabled>${icon('check')} Confirm submission</button></div></form></dialog>`;
  }
  function render() {
    const target=targetFor(draft);
    root.innerHTML=`<nav class="finance-breadcrumb" aria-label="Breadcrumb"><a href="${baseURL}">Extraction setup</a>${icon('chevron-right')}<span aria-current="page">${esc(draft.name || 'New configuration')}</span></nav><header class="finance-heading"><div><h1>${draft.id===null?'New configuration':esc(draft.name || 'Untitled configuration')}</h1><p>${esc(target.label)} · ${sourceLabel(draft.source_type)} · Revision ${draft.revision}</p></div><div class="finance-actions"><a class="btn btn-falcon-default config-assistant-jump" href="#config-chat-input">${icon('magic')} Ask assistant</a><span id="config-header-status">${status(draft)}</span><button class="btn btn-falcon-default" type="button" data-save-draft>${icon('save')} Save locally</button></div></header><div class="finance-callout">Guided setup preview. Configuration drafts and chat suggestions stay in this tab. Database queries, document processing, live LLM calls, and server submissions are not connected.</div><div id="config-submission-banner">${draft.status==='submitted'?`<div class="config-submitted">You submitted revision ${draft.revision} locally on ${esc(new Date(draft.submitted_at).toLocaleString())}. Editing a field or applying a suggestion creates a new draft revision and preserves this snapshot.</div>`:draft.submitted_snapshot?'<div class="config-submitted">Editing a new draft revision. The last user-submitted snapshot remains unchanged.</div>':''}</div><div class="config-layout"><div><ol class="config-stepper" aria-label="Configuration steps">${['Record & source',draft.source_type==='database'?'Field mapping':'Instructions','Encoding rules','Review & submit'].map((title,index)=>`<li><button type="button" data-goto-step="${index}" ${step===index?'aria-current="step"':''}>${index+1}. ${title}</button></li>`).join('')}</ol><form class="config-form" id="configuration-main" novalidate><div id="config-error" class="finance-form-error" role="alert" tabindex="-1" hidden></div>${[sourceStep,mappingStep,rulesStep,reviewStep][step]()}</form><div class="finance-form-footer"><div><span class="config-progress">Step ${step+1} of 4</span><span class="config-saved d-block" id="config-save-state">Saved in this tab</span></div><div class="finance-actions">${step?`<button class="btn btn-falcon-default" type="button" data-goto-step="${step-1}">${icon('arrow-left')} Back</button>`:link(baseURL,'All configurations')}${step<3?`<button class="btn btn-primary" type="button" data-goto-step="${step+1}">Continue ${icon('arrow-right')}</button>`:`<button class="btn btn-primary" type="button" data-submit-review ${validation().length || draft.status==='submitted'?'disabled':''}>${icon('check-circle')} ${draft.status==='submitted'?'Submitted · preview':'Review & submit'}</button>`}</div></div></div>${assistant()}</div>${submissionDialog()}`;
    bindAssistant();
    const dialog=root.querySelector('#configuration-submit');
    root.querySelector('#config-review-confirmation').addEventListener('change',event=>{root.querySelector('#config-confirm-submit').disabled=!event.target.checked;});
    root.querySelector('[data-cancel-submit]').addEventListener('click',()=>dialog.close());
    root.querySelector('#configuration-submit-form').addEventListener('submit',event=>{
      event.preventDefault();
      if(!root.querySelector('#config-review-confirmation').checked || validation().length)return;
      const previous=structuredClone(draft);
      assignId(draft);draft.status='submitted';draft.submitted_at=new Date().toISOString();
      draft.submitted_snapshot=payload('submitted',draft.submitted_at);
      draft.submitted_snapshot.configuration.assistant_proposal={};
      if(!persist()){Object.assign(draft,previous);return;}
      dialog.close();rememberURL();render();notify('You submitted the preview configuration. No backend action ran.');
    });
  }
  function inputChange(element) {
    const path=element.dataset.path;
    if(path==='target_entity'&&element.value!==draft.target_entity) {
      const next=catalog.find(target=>target.key===element.value);
      const previousSource=draft.source_type;
      if(hasContent(draft))assignId(draft);
      draft=schema.blank(next,previousSource);state.pending=draft;persist();rememberURL();render();return;
    }
    set(draft,path,element.type==='checkbox'?element.checked:element.value);edited();
    if(path==='include_lines')render();else refreshIndicators();
  }
  function refreshIndicators() {
    const element=root.querySelector('#config-header-status');if(element)element.innerHTML=status(draft);
    const context=root.querySelector('.config-context');
    if(context)context.innerHTML=`Uses your current ${esc(targetFor(draft).label.toLowerCase())} draft: ${Object.values(draft.field_mappings).filter(value=>value.source || value.default).length} mapped fields, ${draft.extraction_context.length} context characters, business notes, example text, rules, and conversation history.<br><strong>Local demo suggestions · No LLM is connected.</strong>`;
    if(draft.status==='draft'&&draft.submitted_snapshot){const banner=root.querySelector('#config-submission-banner');if(banner)banner.innerHTML='<div class="config-submitted">Editing a new draft revision. The last user-submitted snapshot remains unchanged.</div>';}
  }
  function exportJSON() {
    const result=draft.status==='submitted'?draft.submitted_snapshot:payload();
    const href=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const anchor=document.createElement('a');anchor.href=href;anchor.download=`${config.mode}-${draft.target_entity}-configuration-r${draft.revision}.json`;anchor.click();URL.revokeObjectURL(href);notify('Configuration JSON exported. No server submission ran.');
  }
  root.addEventListener('submit',event=>{if(event.target.id==='configuration-main')event.preventDefault();});
  root.addEventListener('input',event=>{
    const element=event.target;
    if(element.matches('#configuration-main [data-path]')&&element.tagName!=='SELECT'&&element.type!=='checkbox')inputChange(element);
  });
  root.addEventListener('change',event=>{
    const element=event.target;
    if(element.matches('#configuration-main [data-path]')&&(element.tagName==='SELECT'||element.type==='checkbox'))inputChange(element);
    if(element.matches('[data-required]')) {
      const name=element.dataset.required;
      const group=element.dataset.requiredGroup==='line'?'line_required_fields':'required_fields';
      draft.encoding_rules[group]=element.checked?[...new Set([...draft.encoding_rules[group],name])]:draft.encoding_rules[group].filter(value=>value!==name);
      edited();refreshIndicators();
    }
  });
  root.addEventListener('click',event=>{
    const action=event.target.closest('button,a');if(!action)return;
    if(action.hasAttribute('data-goto-step')) {event.preventDefault();step=Number(action.dataset.gotoStep);rememberURL();render();root.querySelector('.config-stepper [aria-current="step"]').focus();}
    else if(action.hasAttribute('data-source')) {if(draft.source_type!==action.dataset.source){draft.source_type=action.dataset.source;edited();render();}}
    else if(action.hasAttribute('data-use-sample')) {Object.assign(draft,schema.sample(targetFor(draft)));edited();render();notify('Sample schema loaded. No database connection was made.');}
    else if(action.hasAttribute('data-save-draft'))saveDraft();
    else if(action.hasAttribute('data-export'))exportJSON();
    else if(action.hasAttribute('data-submit-review')) {if(validation().length){step=3;render();return;}root.querySelector('#configuration-submit').showModal();}
  });
  window.addEventListener('finance-llm-storage-error',event=>error(event.detail));
  document.getElementById('reset-demo').hidden=true;
  const previewNote=document.querySelector('.finance-preview-note > span:nth-child(2)');
  previewNote.textContent='Configuration preview. Drafts, chat history, and reviewed snapshots stay in this browser tab. No imports, provider calls, or server submissions run.';
  if(config.screen==='list')list();
  else {
    if(config.recordId!==null)draft=state.profiles.find(profile=>profile.id===config.recordId);
    else {
      const requested=catalog.find(target=>target.key===parameters.get('target')) || catalog[0];
      if(state.pending&&parameters.get('fresh')!=='1'&&(!parameters.get('target')||state.pending.target_entity===requested.key)&&(!parameters.get('source')||state.pending.source_type===parameters.get('source')))draft=state.pending;
      else {if(state.pending&&hasContent(state.pending)){assignId(state.pending);}draft=schema.blank(requested,parameters.get('source')==='document'?'document':'database');state.pending=draft;persist();}
    }
    if(!draft){root.innerHTML=`<div class="finance-empty"><h1>Configuration unavailable</h1><p>This local draft may belong to another tab.</p>${link(baseURL,'Back to configurations')}</div>`;return;}
    if(config.recordId===null)rememberURL();
    draft.encoding_rules.line_required_fields ||= schema.requiredLineFields(targetFor(draft));
    draft.line_field_instructions ||= {};
    draft.relation_lookups ||= {};
    render();
  }
})();
