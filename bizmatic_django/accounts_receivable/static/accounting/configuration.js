/* Reviewed accounting configurations backed by Django. */
(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('finance-config').textContent);
  if (config.resource !== 'configuration') return;
  const root = document.getElementById('finance-root');
  const catalog = config.configurationCatalog;
  const schema = window.BizmaticConfigurationSchema;
  const activity = window.BizmaticLLMLogs;
  const api = window.BizmaticAccounting;
  const baseURL = config.routes.configuration;
  const parameters = new URLSearchParams(location.search);
  const partyKey = config.mode === 'ar' ? 'customer' : 'supplier';
  const parties = api.state.parties;
  const state = {profiles:api.state.profiles, pending:null};
  let draft = null;
  let dirty = false;
  const importRuns = api.state.import_runs || [];
  let step = Math.min(3,Math.max(0,Math.trunc(Number(parameters.get('step'))) || 0));
  let chatInput = '';
  let chatFeedback = '';
  let assistantErrorLog = null;
  let chatBusy = false;
  let showAdvanced = false;
  let review = null;
  let sampleDocument = '';
  let example = null;
  let selectedTarget = '';
  let selectedSource = '';
  let contextInfo = null;
  let contextBusy = false;
  let contextFeedback = '';
  let lastCleared = null;
  let resetBusy = false;
  let contextVersion = 0;
  const sessions = new Map();
  const selection = () => ({target_entity:selectedTarget,source_type:selectedSource});
  const sessionKey = () => `${selectedTarget}:${selectedSource}`;
  const targetLabel = target => target.key==='sales_invoice'?'Invoices':target.label;
  const esc = (value='') => String(value ?? '').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const icon = name => `<span class="fas fa-${name}" aria-hidden="true"></span>`;
  const link = (href,text,primary=false) => `<a class="btn ${primary?'btn-primary':'btn-falcon-default'}" href="${esc(href)}">${text}</a>`;
  const targetFor = profile => catalog.find(target=>target.key===profile.target_entity);
  const sourceLabel = value => value==='database'?'Database mapping':'Document context';
  const scopeLabel = profile => profile.scope==='module'?`All ${config.party.toLowerCase()}s (module default)`:`${parties.find(p=>String(p.id)===profile.scope)?.name || 'Account unavailable'}`;
  const splitColumns = text => [...new Set(String(text || '').split(/[\n,]/).map(value=>value.trim()).filter(Boolean))];
  const joinPairs = text => String(text || '').split(',').map(pair=>pair.split('=').map(value=>value.trim())).filter(pair=>pair.length===2 && pair.every(Boolean)).map(([header_column,line_column])=>({header_column,line_column}));
  function set(object,path,value) { const keys=path.split('.'); const last=keys.pop(); let parent=object; for(const key of keys) parent=parent[key] ||= {}; parent[last]=value; }
  const status = profile => `<span class="finance-status ${profile.status==='submitted'?'success':'info'}">${profile.status==='submitted'?'Submitted':'Draft'}</span>`;
  function notify(message) { const element=document.getElementById('finance-toast'); element.textContent=message; element.hidden=false; setTimeout(()=>{element.hidden=true;},4500); }
  function persist() {
    const saved=root.querySelector('#config-save-state');if(saved)saved.textContent='Unsaved changes';
    const output=root.querySelector('#config-output');if(output&&draft)output.textContent=JSON.stringify(payload(),null,2);
    return true;
  }
  function error(message) { let element=root.querySelector('#config-error');if(!element){root.insertAdjacentHTML('afterbegin','<div id="config-error" class="finance-form-error" role="alert" tabindex="-1"></div>');element=root.querySelector('#config-error');}element.hidden=false;element.textContent=message;element.focus(); }
  function edited() {
    dirty = true;
    review = null;
    example = null;
    root.querySelector('[data-sample-output]')?.remove();
    if(draft.status==='submitted')draft.status='draft';
    if(draft.id===null)state.pending=draft;
    persist();
  }
  function rememberURL() { const route=draft.id===null?config.configurationCreate:baseURL+draft.id+'/';history.replaceState(null,'',`${route}?step=${step}&target=${draft.target_entity}&source=${draft.source_type}`); }
  async function saveDraft() {
    if(!review)return;
    try {
      const result=await api.post(review.submit?'submit':'configuration',draft.id,{
        configuration:payload().configuration, messages:draft.assistant_messages,
        confirmation_token:review.token, confirmed:true, submit:review.submit,
      });
      Object.assign(draft,result.record);dirty=false;review=null;
      if(!state.profiles.some(row=>row.id===draft.id))state.profiles.push(draft);
      state.pending=null;rememberURL();render();notify('Your confirmed configuration has been saved.');
    } catch(problem) {root.querySelector('#config-confirm-error').textContent=problem.message;}
  }
  async function requestReview(submit) {
    const version=contextVersion;
    try {
      const result=await api.post('configuration-review',draft.id,{configuration:payload().configuration,submit});
      if(version!==contextVersion)return;
      review={token:result.confirmation_token,submit};
      render();root.querySelector('#configuration-submit').showModal();
    } catch(problem) {if(version===contextVersion)error(problem.message);}
  }
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
    root.innerHTML=`<header class="finance-heading"><div><h1>Extraction configuration</h1><p>Define how source data becomes ${config.party.toLowerCase()}s, orders, deliveries, invoices, and payments.</p></div><div class="finance-actions">${link(config.configurationCreate+'?fresh=1',icon('plus')+' New configuration',true)}</div></header><div class="finance-callout">Configure the inputs here. Extracted accounting records remain read-only. Chat builds your working configuration. Review the guide and confirm before saving.</div><div class="config-targets">${catalog.map(target=>{const count=state.profiles.filter(p=>p.target_entity===target.key).length;return `<a class="config-target" href="${esc(config.configurationCreate+'?target='+target.key)}">${icon({customer:'address-book',supplier:'address-book',purchase_order:'shopping-cart',delivery_receipt:'truck',sales_invoice:'file-invoice-dollar',payment:'credit-card'}[target.key])}<strong>${esc(target.label)}</strong><small>${count} configuration${count===1?'':'s'} · Configure ${icon('arrow-right')}</small></a>`;}).join('')}</div>${state.pending?`<div class="finance-callout">You have an unfinished configuration for ${esc(targetFor(state.pending).label.toLowerCase())}. ${link(config.configurationCreate,'Continue draft')}</div>`:''}${card('Your configurations',`<div class="finance-toolbar"><label class="visually-hidden" for="config-search">Search configurations</label><input class="form-control" type="search" id="config-search" placeholder="Search name, target, or source"></div><div id="configuration-list"></div>`)}`;
    const renderRows=query=>{const rows=state.profiles.filter(profile=>`${profile.name} ${targetFor(profile).label} ${sourceLabel(profile.source_type)}`.toLowerCase().includes(query.toLowerCase()));root.querySelector('#configuration-list').innerHTML=`<div class="table-responsive"><table class="table finance-table"><caption class="visually-hidden">Saved extraction configurations</caption><thead><tr><th>Configuration</th><th>Target</th><th>Source</th><th>Status</th><th class="config-actions-heading">Actions</th></tr></thead><tbody>${rows.map(profile=>`<tr><td><a class="primary-link" href="${baseURL+profile.id+'/'}">${esc(profile.name || 'Untitled configuration')}</a><span class="subtext">${esc(scopeLabel(profile))} · Revision ${profile.revision}</span></td><td>${esc(targetFor(profile).label)}</td><td>${sourceLabel(profile.source_type)}</td><td>${status(profile)}</td><td class="config-actions-cell"><div class="config-row-actions" role="group" aria-label="Actions for ${esc(profile.name)}"><a class="btn btn-falcon-default btn-sm" href="${baseURL+profile.id+'/'}" aria-label="Configure ${esc(profile.name)}">${icon('sliders-h')}Configure</a><span class="config-action-divider" aria-hidden="true"></span><button type="button" class="btn btn-outline-danger btn-sm" aria-label="Delete ${esc(profile.name)}" data-delete-configuration="${profile.id}" data-configuration-revision="${profile.revision}" data-configuration-name="${esc(profile.name)}">${icon('trash-alt')}Delete</button></div></td></tr>`).join('') || '<tr><td colspan="5" class="text-center p-4 text-600">No matching configurations. Create one using the button above.</td></tr>'}</tbody></table></div>`;};
    renderRows('');root.querySelector('#config-search').addEventListener('input',event=>renderRows(event.target.value));
  }
  function sourceStep() {
    const target=targetFor(draft);
    const common=`<div class="finance-form-grid">${field('name','Configuration name',draft.name,{required:true,full:true,placeholder:'e.g. Sales invoices · ERP mapping'})}${field('scope','Applies to',draft.scope,{choices:[['module',`All ${config.party.toLowerCase()}s`],...parties.map(p=>[p.id,p.name])]})}${field('description','Purpose / existing business context',draft.description,{textarea:true,full:true,placeholder:'Describe this data source, document layout, or business convention.'})}</div>`;
    const tables=api.state.tables.filter(table=>String(table.source_id)===String(draft.database_source));
    const choices=[['','Choose a table'],...tables.map(table=>[table.id,table.label])];
    const source=draft.source_type==='database'?`<div class="finance-callout">Choose saved schema metadata, then map its columns. Imports read only the selected tables.</div><div class="finance-form-grid">${field('database_source','Database connection',draft.database_source || '',{required:true,choices:[['','Choose a connection'],...api.state.sources.map(source=>[source.id,source.name])]})}${field('source_table','Header table',draft.source_table || '',{required:true,choices})}${field('source_keys','Header record key columns',draft.source_keys,{required:true,full:true,placeholder:'id, company_id'})}<div class="full"><label>Header columns</label><pre>${esc(draft.columns)}</pre></div>${target.lineModel?`${field('line_source_table','Line table',draft.line_source_table || '',{required:true,choices})}${field('line_joins','Header → line join',draft.line_joins,{required:true,placeholder:'id=invoice_id'})}<div class="full"><label>Line columns</label><pre>${esc(draft.line_columns)}</pre></div>`:''}</div>`:`<div class="finance-form-grid">${field('document_type','Document type / layout',draft.document_type,{required:true,full:true})}${field('sample_text','Optional example text',draft.sample_text,{textarea:true,full:true,rows:5,hint:'Used as configuration context only.'})}</div>`;
    return card('1. Record and source',`<div class="finance-card-body">${common}<hr class="my-4">${source}</div>`);
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
    return card('2. Write extraction instructions',`<div class="finance-card-body"><div class="finance-form-grid">${field('extraction_context','Overall extraction context',draft.extraction_context,{required:true,textarea:true,full:true,rows:6,placeholder:'Explain the document layout, reference labels, date conventions, and what must be flagged for user review.'})}${target.lineModel?field('line_item_context','Line item instructions (optional)',draft.line_item_context,{required:false,textarea:true,full:true,rows:4,placeholder:'Explain repeated item rows, units, accepted quantities, taxes, and rows to exclude.'}):''}</div></div><details class="config-disclosure" open><summary>Field-specific guidance · ${esc(target.model)}</summary><div class="config-instructions mt-3">${instructions(target.fields)}</div></details>${target.lineModel?`<details class="config-disclosure"><summary>Line-specific field guidance</summary><div class="config-instructions mt-3">${instructions(target.lineFields,true)}</div></details>`:''}`);
  }
  function rulesStep() {
    const target=targetFor(draft);const choices=draft.source_type==='document'?`<div class="config-instructions mt-3">${target.fields.map(info=>`<label class="form-check"><input class="form-check-input" type="checkbox" data-required="${info.key}" ${draft.encoding_rules.required_fields.includes(info.key)?'checked':''} ${info.required?'disabled':''}><span class="form-check-label">Require ${esc(info.label.toLowerCase())} <code>${esc(info.key)}</code></span></label>`).join('')}</div>`:'';
    const lineChoices=target.lineModel?`<p class="config-note mt-3">All line item fields are optional. Records can be saved without line items.</p>`:'';
    return card('3. Encoding and review rules',`<div class="finance-card-body"><p class="text-600">Configure normalization and validation for extracted records. Document duplicates always require review; database imports can skip existing source rows.</p><div class="finance-form-grid">${field('encoding_rules.date_format','Source date format',draft.encoding_rules.date_format,{choices:['YYYY-MM-DD','DD/MM/YYYY','MM/DD/YYYY']})}${field('encoding_rules.default_currency','Default currency',draft.encoding_rules.default_currency,{maxlength:3,hint:'Three-letter uppercase currency code, e.g. PHP.'})}${field('encoding_rules.decimal_separator','Decimal separator',draft.encoding_rules.decimal_separator,{choices:[['.','Period · 1,234.56'],[',','Comma · 1.234,56']]})}${field('encoding_rules.thousands_separator','Thousands separator',draft.encoding_rules.thousands_separator,{choices:[['','None'],[',','Comma'],['.','Period'],[' ','Space']]})}${field('encoding_rules.duplicate_policy','When a reference already exists',draft.encoding_rules.duplicate_policy,{choices:[['review','Ask the user to review'],['skip','Skip duplicate database rows']]})}${field('encoding_rules.missing_value_policy','When required information is missing','review',{choices:[['review','Hold for user review']]})}</div>${target.fields.filter(info=>info.type==='lookup').map(info=>`<div class="mt-3">${field('relation_lookups.'+info.key+'.match_field',info.label+' lookup field',draft.relation_lookups[info.key]?.match_field || partyKey+'_code',{choices:[[partyKey+'_code',config.party+' code'],['tax_identification_no','Tax identification no.'],[partyKey+'_name',config.party+' name']],hint:'Unknown or ambiguous matches are held for review; this does not create accounts.'})}</div>`).join('')}${choices}${lineChoices}<div class="finance-callout mt-4 mb-0">Account identifiers must resolve to an existing ${config.party.toLowerCase()} using your selected lookup field. Unknown accounts, ambiguous dates, and missing required values are held for review. The assistant cannot submit configurations or create accounting records.</div></div>`);
  }
  function validation() {
    const target=targetFor(draft);const issues=[];
    const add=(message,at)=>issues.push({message,step:at});
    if(!draft.name.trim())add('Give this configuration a name.',0);
    if(draft.name.length>160)add('Keep the configuration name within 160 characters.',0);
    if(draft.source_type==='database') {
      const columns=splitColumns(draft.columns);const lineColumns=splitColumns(draft.line_columns);
      if(!draft.connection.trim())add('Choose a saved database connection.',0);
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
      model:`${config.mode==='ar'?'accounts_receivable':'accounts_payable'}.ExtractionConfiguration`,
      unresolved_references:reference,
      configuration:{name:draft.name,description:draft.description,target_entity:draft.target_entity,source_type:draft.source_type,[partyKey]:draft.scope==='module'?null:Number(draft.scope),
        database_source:database&&draft.database_source?Number(draft.database_source):null,source_table:database&&draft.source_table?Number(draft.source_table):null,line_source_table:database&&draft.line_source_table?Number(draft.line_source_table):null,
        source_schema_snapshot:{...reference,header_columns:database?splitColumns(draft.columns):[],line_columns:database&&draft.include_lines?splitColumns(draft.line_columns):[]},
        source_key_fields:database?splitColumns(draft.source_keys):[],field_mappings:mappings,
        line_item_mappings:database&&draft.include_lines?normalizedMappings(target.lineFields,draft.line_item_mappings):{},line_join_fields:database&&draft.include_lines?joinPairs(draft.line_joins):[],relation_lookups:lookups,
        document_type:database?'':draft.document_type,extraction_context:database?'':draft.extraction_context,field_instructions:database?{}:draft.field_instructions,line_field_instructions:database?{}:draft.line_field_instructions,line_item_context:database?'':draft.line_item_context,sample_text:database?'':draft.sample_text,
        encoding_rules:structuredClone(draft.encoding_rules),assistant_messages:structuredClone(draft.assistant_messages),assistant_proposal:structuredClone(draft.assistant_proposal || {}),
        status:statusOverride || draft.status,revision:draft.revision,submitted_at:submittedAt || draft.submitted_at,submitted_by:null},
    };
  }
  function reviewStep() {
    const issues=validation();const output=payload();
    return card('4. Review your configuration',`<div class="finance-card-body">${issues.length?`<div class="config-validation" role="status"><strong>${issues.length} item${issues.length===1?'':'s'} to complete</strong><ul>${issues.map(issue=>`<li><a href="#" data-goto-step="${issue.step}">${esc(issue.message)}</a></li>`).join('')}</ul></div>`:'<div class="config-submitted">Configuration fields are complete. Review the output below before submitting.</div>'}<dl class="config-review-list"><div><dt>Destination model</dt><dd>${esc(targetFor(draft).model)}</dd></div><div><dt>Source</dt><dd>${sourceLabel(draft.source_type)}</dd></div><div><dt>Scope</dt><dd>${esc(scopeLabel(draft))}</dd></div><div><dt>Required fields</dt><dd>${draft.encoding_rules.required_fields.length} header · ${draft.encoding_rules.line_required_fields.length} line</dd></div></dl><div class="finance-callout mb-0">This checks configuration completeness and names against the columns you supplied. Submission validates the saved schema, fields, and rules. Only submitted configurations are used for extraction.</div></div><details class="config-disclosure" open><summary>Configuration output · exact current draft</summary><pre class="config-json mt-3" id="config-output">${esc(JSON.stringify(output,null,2))}</pre></details>${draft.submitted_snapshot?`<details class="config-disclosure"><summary>Last user-submitted snapshot · revision ${draft.submitted_snapshot.configuration.revision}</summary><pre class="config-json mt-3">${esc(JSON.stringify(draft.submitted_snapshot,null,2))}</pre></details>`:''}`,`<button class="btn btn-falcon-default btn-sm" type="button" data-export>${icon('download')} Export JSON</button>`);
  }
  function stashSession() {
    if(draft)sessions.set(`${draft.target_entity}:${draft.source_type}`,{draft,dirty,chatInput,sampleDocument,example,contextInfo,contextFeedback,lastCleared});
  }
  async function selectSetup(target,source) {
    if(chatBusy || contextBusy || resetBusy)return;
    contextVersion++;
    stashSession();selectedTarget=target;selectedSource=source;
    draft=null;dirty=false;chatInput='';chatFeedback='';assistantErrorLog=null;sampleDocument='';example=null;review=null;contextInfo=null;contextFeedback='';lastCleared=null;showAdvanced=false;step=0;
    if(!target || !source){render();return;}
    const previous=sessions.get(sessionKey());
    if(previous){({draft,dirty,chatInput,sampleDocument,example,contextInfo,contextFeedback,lastCleared}=previous);}
    else draft=schema.blank(catalog.find(item=>item.key===target),source);
    rememberURL();render();
    if(!contextInfo)await refreshContext();
  }
  async function refreshContext(inspect=false) {
    if(!draft || chatBusy || contextBusy)return;
    contextBusy=true;contextFeedback='Refreshing selected requirements and source metadata…';render();
    try {
      const result=await api.post('configuration-context',draft.id,{selection:selection(),configuration:payload().configuration,inspect_schema:inspect});
      contextInfo=result;
      const current=catalog.findIndex(item=>item.key===selectedTarget);
      if(current>=0)catalog[current]=result.catalog[0];
      if(selectedSource==='database'){
        api.state.sources=result.sources;
        // Keep pinned snapshots visible until the user explicitly selects a newer table.
        api.state.tables=[...api.state.tables.filter(table=>!result.tables.some(next=>next.id===table.id)),...result.tables];
      }
      contextFeedback=inspect?'Database schema refreshed. Choose a table from the new snapshot to use it.':'Context refreshed. Your answers and conversation are unchanged.';
      review=null;example=null;
    } catch(problem){contextFeedback=problem.message;}
    finally {contextBusy=false;render();}
  }
  function selectionPanel() {
    return `<section class="card config-selection mb-3" aria-label="Choose extraction setup"><div class="finance-card-head"><div><h2>What would you like to configure?</h2><div class="finance-card-subtitle">Choose a record type and extraction source. Each combination has its own chat in this page.</div></div></div><div class="finance-card-body"><fieldset><legend>1. Record type</legend><div class="config-selection-options">${catalog.map(target=>`<button type="button" class="btn btn-falcon-default" data-select-target="${target.key}" aria-pressed="${selectedTarget===target.key}">${esc(targetLabel(target))}</button>`).join('')}</div></fieldset><fieldset class="mt-3"><legend>2. Extraction source</legend><div class="config-selection-options">${[['document','file-alt','Document extraction'],['database','database','Database setup']].map(([key,symbol,label])=>`<button type="button" class="btn btn-falcon-default" data-select-source="${key}" aria-pressed="${selectedSource===key}">${icon(symbol)} ${label}</button>`).join('')}</div></fieldset>${draft?`<div class="config-session-bar"><strong>${esc(targetLabel(targetFor(draft)))} · ${selectedSource==='database'?'Database setup':'Document extraction'}</strong><div class="finance-actions"><button type="button" class="btn btn-falcon-default btn-sm" data-refresh-context>Refresh context</button><button type="button" class="btn btn-falcon-default btn-sm" data-clear-chat>Clear chat</button><button type="button" class="btn btn-outline-danger btn-sm" data-reset-context ${chatBusy || contextBusy?'disabled':''}>Reset context</button>${lastCleared?'<button type="button" class="btn btn-link btn-sm" data-undo-clear>Undo clear</button>':''}</div></div><p class="config-note">Refresh keeps your answers. Clear chat removes only working conversation history. Reset context clears the conversation and all setup answers, including saved context, after confirmation.</p><p class="config-note" role="status">${esc(contextFeedback)}</p>`:''}</div></section>`;
  }
  function requirementsPanel() {
    const target=targetFor(draft);const database=selectedSource==='database';
    const required=draft.encoding_rules.required_fields;
    const rows=(fields,line=false)=>fields.map(info=>{
      const needed=info.required || (line?draft.encoding_rules.line_required_fields:required).includes(info.key);
      const mapping=(line?draft.line_item_mappings:draft.field_mappings)[info.key];
      const note=database?(mapping?.source?`Column: ${mapping.source}`:mapping?.default?`Default: ${mapping.default}`:'Not mapped'):(line?draft.line_field_instructions:draft.field_instructions)[info.key] || 'Uses overall instructions';
      return `<tr><td><strong>${esc(info.label)}</strong><code>${esc(info.key)}</code></td><td>${esc(info.type)}${info.choices?.length?`<small>${esc(info.choices.map(choice=>choice[0]).join(', '))}</small>`:''}</td><td>${needed?'Required':'Optional'}</td><td>${esc(note)}</td></tr>`;
    }).join('');
    const sourceChoices=api.state.sources || [];
    const tables=api.state.tables.filter(table=>String(table.source_id)===String(draft.database_source));
    const select=(path,label,choices,value)=>`<div><label class="form-label" for="context-${path}">${label}</label><select class="form-select" id="context-${path}" data-path="${path}"><option value="">Choose ${label.toLowerCase()}</option>${choices.map(item=>`<option value="${item.id}" ${String(value)===String(item.id)?'selected':''}>${esc(item.label || item.name)}</option>`).join('')}</select></div>`;
    return `<section class="card config-requirements mb-3" aria-label="Selected setup requirements"><div class="finance-card-head"><h2>What ${esc(targetLabel(target).toLowerCase())} ${database?'database setup':'document extraction'} needs</h2></div><div class="finance-card-body"><div class="config-parameter-list">${(contextInfo?.parameters || []).map(name=>`<span>${esc(name.replaceAll('_',' '))}</span>`).join('')}</div><p class="config-note">${esc((contextInfo?.features || []).join(' · '))}</p>${database?`<div class="config-scope-fields finance-form-grid">${select('database_source','Database connection',sourceChoices,draft.database_source)}${select('source_table','Header table',tables,draft.source_table)}${target.lineModel?select('line_source_table','Line table',tables,draft.line_source_table):''}</div><button type="button" class="btn btn-falcon-default btn-sm mt-2" data-refresh-schema ${draft.database_source?'':'disabled'}>Refresh database schema</button><p class="config-note">${sourceChoices.length?'Choose a connection and table, then describe how its columns map to the fields below.':'No enabled database connections. Add one in Database connections, then refresh context.'}</p><details><summary>Available source columns</summary><p>Header: ${esc(draft.columns || 'Select a header table')}</p>${target.lineModel?`<p>Lines: ${esc(draft.line_columns || 'Select a line table')}</p>`:''}</details>`:''}<p class="config-note"><strong>Required fields:</strong> ${esc(target.fields.filter(info=>info.required || required.includes(info.key)).map(info=>info.label).join(', ') || 'No additional required fields')}</p><details class="config-field-reference"><summary>Destination fields, types and current guidance (${target.fields.length}${target.lineFields.length?` + ${target.lineFields.length} line fields`:''})</summary><div class="table-responsive"><table class="table finance-table"><thead><tr><th>Field</th><th>Type / choices</th><th>Requirement</th><th>${database?'Mapping':'Guidance'}</th></tr></thead><tbody>${rows(target.fields)}</tbody></table></div>${target.lineModel?`<h3>Line item fields</h3><div class="table-responsive"><table class="table finance-table"><thead><tr><th>Field</th><th>Type / choices</th><th>Requirement</th><th>${database?'Mapping':'Guidance'}</th></tr></thead><tbody>${rows(target.lineFields,true)}</tbody></table></div>`:''}</details></div></section>`;
  }
  function clearContext() {
    if(chatBusy || contextBusy || resetBusy)return;
    contextVersion++;
    lastCleared={draft:structuredClone(draft),dirty,chatInput,sampleDocument,example};
    draft.assistant_messages=[];
    chatInput='';chatFeedback='';assistantErrorLog=null;sampleDocument='';edited();render();
    notify('Chat cleared. Your configuration answers are preserved.');
  }
  function resetDialog() {
    return `<dialog class="config-submit" id="configuration-reset" aria-labelledby="configuration-reset-title" aria-describedby="configuration-reset-description"><h2 id="configuration-reset-title">Reset this chat’s context?</h2><p id="configuration-reset-description">Start fresh for <strong>${esc(targetLabel(targetFor(draft)))}</strong> · ${draft.source_type==='database'?'Database setup':'Document extraction'}. This clears the conversation and all working answers, including the name, business context, account scope, selected tables, mappings, instructions, custom rules, and example text.</p><p>${draft.id===null?'This unsaved setup will return to its defaults. No configuration will be created.':'The reset is saved immediately and survives a reload. This configuration will return to draft and will not be used for extraction until you review and confirm it again.'}</p><p class="config-note">The record type and extraction source stay selected. Other chats, accounting records, database connections, and audit history are kept. Previous audit snapshots are not sent to the assistant.</p><div id="config-reset-error" class="config-feedback" role="alert"></div><div class="finance-actions justify-content-end"><button type="button" class="btn btn-falcon-default" data-cancel-reset autofocus>Keep context</button><button type="button" class="btn btn-danger" data-confirm-reset>Reset context</button></div></dialog>`;
  }
  async function resetContext() {
    if(chatBusy || contextBusy || resetBusy)return;
    const dialog=root.querySelector('#configuration-reset');
    resetBusy=true;contextVersion++;
    dialog.querySelectorAll('button').forEach(button=>{button.disabled=true;});
    dialog.querySelector('[data-confirm-reset]').textContent='Resetting…';
    dialog.querySelector('#config-reset-error').textContent='';
    dialog.setAttribute('aria-busy','true');
    try {
      const result=await api.post('configuration-reset-context',draft.id,{selection:selection(),revision:draft.revision,confirmed:true});
      draft={...schema.blank(targetFor(result.record),result.record.source_type),...result.record};
      dirty=false;chatInput='';chatFeedback='Context reset. Tell me what you want to configure.';
      assistantErrorLog=null;sampleDocument='';example=null;review=null;lastCleared=null;
      contextFeedback='Context reset. Previous answers and conversation have been cleared.';
      showAdvanced=false;step=0;state.pending=null;
      if(draft.id!==null)state.profiles=state.profiles.map(row=>row.id===draft.id?draft:row);
      stashSession();rememberURL();dialog.close();render();
      root.querySelector('#config-chat-input').focus();
      notify('Context reset. The assistant will start fresh for this selection.');
    } catch(problem) {
      dialog.querySelector('#config-reset-error').textContent=problem.message;
      dialog.querySelectorAll('button').forEach(button=>{button.disabled=false;});
      dialog.querySelector('[data-confirm-reset]').textContent='Reset context';
      dialog.removeAttribute('aria-busy');
    } finally {resetBusy=false;}
  }
  function assistant() {
    const messages=draft.assistant_messages;
    return `<section class="config-assistant card" aria-label="Configuration conversation"><div class="finance-card-head"><div><h2>${icon('comments')} Let’s build your extraction setup</h2><div class="finance-card-subtitle">${esc(targetLabel(targetFor(draft)))} · ${draft.source_type==='database'?'Database setup':'Document extraction'}</div></div><span class="finance-status info">${esc(config.mode.toUpperCase())} assistant</span></div><div class="config-chat-log" id="config-chat-log" role="log" aria-live="polite" aria-busy="${chatBusy}">${messages.length?messages.map(message=>`<div class="config-chat-message ${message.role==='user'?'user':''}"><small>${message.role==='user'?'You':'Configuration assistant'}</small>${esc(message.content)}</div>`).join(''):`<div class="config-chat-message"><small>Configuration assistant</small>Let’s configure ${esc(targetLabel(targetFor(draft)).toLowerCase())} using ${draft.source_type==='database'?'your database':'documents'}.<br><br>Tell me about ${draft.source_type==='database'?'the connection, tables and column mappings':'the document layout, field labels and formatting'}, and any special rules. I’ll build the configuration and keep the guide beside this conversation up to date.<br><br>You can also ask me to explain a field or help choose a rule.</div>`}${chatBusy?'<div class="config-chat-message" role="status">Thinking through your setup…</div>':''}</div><div class="config-chat-prompts">${[`Help me configure ${targetLabel(targetFor(draft)).toLowerCase()}`,draft.source_type==='database'?'Which tables and columns do I need?':'Which document fields do I need?','What information is still missing?'].map(prompt=>`<button class="btn btn-falcon-default btn-sm" type="button" data-chat-prompt="${prompt}" ${chatBusy?'disabled':''}>${prompt}</button>`).join('')}</div><form id="config-chat-form" class="config-chat-controls"><label for="config-chat-input" class="form-label">Your message</label><textarea id="config-chat-input" class="form-control" rows="3" maxlength="4000" ${chatBusy?'disabled':''} placeholder="e.g. We receive supplier invoices as PDFs. Dates are DD/MM/YYYY and amounts are in PHP.">${esc(chatInput)}</textarea><div class="config-feedback" role="status">${esc(chatFeedback)}${assistantErrorLog?`<a href="${esc(activity.detailURL(assistantErrorLog))}">View attempt #${esc(assistantErrorLog)}</a>`:''}</div><div class="config-composer-footer"><span class="config-note">Nothing is saved until you review and confirm. Assistant attempts are logged.</span><button class="btn btn-primary" type="submit" ${chatBusy?'disabled':''}>${icon('paper-plane')} ${chatBusy?'Thinking…':'Send message'}</button></div></form></section>`;
  }
  async function propose(message) {
    assistantErrorLog=null;
    try {
      const result=await api.post('configuration-chat',draft.id,{configuration:payload().configuration,selection:selection(),messages:draft.assistant_messages,message});
      const defaults=schema.blank(targetFor(result.record),result.record.source_type);
      draft={...defaults,...result.record,encoding_rules:{...defaults.encoding_rules,...result.record.encoding_rules}};
      if(selectedSource==='database'){api.state.sources=result.sources;api.state.tables=result.tables;}
      edited();return true;
    } catch(problem){chatFeedback=problem.message;assistantErrorLog=problem.llmLogNo || null;return false;}
  }
  function bindAssistant() {
    const form=root.querySelector('#config-chat-form');
    form.querySelector('textarea').addEventListener('input',event=>{chatInput=event.target.value;});
    const send=async message=>{
      if(chatBusy)return;
      if(!message.trim()){chatFeedback='Write a message or choose a suggested prompt.';render();return;}
      chatBusy=true;chatFeedback='';render();
      const success=await propose(message.trim());
      chatBusy=false;chatInput=success?'':message;render();
      root.querySelector('#config-chat-input').focus();
      const log=root.querySelector('#config-chat-log');log.scrollTop=log.scrollHeight;
    };
    form.addEventListener('submit',event=>{event.preventDefault();send(chatInput);});
    root.querySelectorAll('[data-chat-prompt]').forEach(button=>button.addEventListener('click',()=>send(button.dataset.chatPrompt)));
  }
  function guide() {
    const target=targetFor(draft);const issues=validation();
    const entry=(label,value)=>`<div><dt>${esc(label)}</dt><dd>${esc(value || 'Not provided yet')}</dd></div>`;
    const fields=(items)=>Object.entries(items).map(([key,value])=>`${key}: ${typeof value==='object'?JSON.stringify(value):value}`).join('\n');
    return `<aside class="config-guide card" id="configuration-guide" tabindex="-1" aria-label="Configuration guide"><div class="finance-card-head"><div><h2>${icon('clipboard-check')} What I’ve understood</h2><div class="finance-card-subtitle">Your working configuration · ${dirty?'unsaved changes':draft.id?'saved':'not saved'}</div></div></div><div class="finance-card-body"><dl class="config-guide-list">${entry('Configuration name',draft.name)}${entry('Record type',target.label)}${entry('Source',sourceLabel(draft.source_type))}${entry('Applies to',scopeLabel(draft))}${draft.description?entry('Business context',draft.description):''}${draft.source_type==='database'?`${entry('Database',draft.connection)}${entry('Header table',draft.table)}${entry('Record keys',draft.source_keys)}${target.lineModel?entry('Line table / joins',[draft.line_table,draft.line_joins].filter(Boolean).join(' · ')):''}`:`${entry('Document layout',draft.document_type)}${entry('Extraction instructions',draft.extraction_context)}${target.lineModel?entry('Line item instructions',draft.line_item_context):''}`}<div><dt>Formatting rules</dt><dd>${esc(draft.encoding_rules.default_currency)} · ${esc(draft.encoding_rules.date_format)}<br>Decimal: ${esc(draft.encoding_rules.decimal_separator)} · Thousands: ${esc(draft.encoding_rules.thousands_separator || 'none')}</dd></div>${entry('Duplicate / missing values',`${draft.encoding_rules.duplicate_policy} / ${draft.encoding_rules.missing_value_policy}`)}</dl><details class="config-guide-details"><summary>Fields, mappings & account lookups</summary><pre>${esc(fields(draft.source_type==='database'?draft.field_mappings:draft.field_instructions) || 'No field-specific guidance yet.')}</pre><strong>Line fields</strong><pre>${esc(fields(draft.source_type==='database'?draft.line_item_mappings:draft.line_field_instructions) || 'No line-specific guidance yet.')}</pre><strong>Account lookups</strong><pre>${esc(fields(draft.relation_lookups))}</pre><strong>Required header fields</strong><p>${esc(draft.encoding_rules.required_fields.join(', ') || 'Model requirements only')}</p><strong>Required line fields</strong><p>${esc('None · all line item fields are optional')}</p></details>${issues.length?`<div class="config-validation mt-3"><strong>Still to clarify</strong><ul>${issues.slice(0,6).map(issue=>`<li>${esc(issue.message)}</li>`).join('')}${issues.length>6?`<li>And ${issues.length-6} more — open the detailed review.</li>`:''}</ul></div>`:'<div class="config-submitted mt-3">Ready for your review. Check the details before saving.</div>'}<button class="btn btn-primary w-100" type="button" data-submit-review>Review & save configuration</button><button class="btn btn-link w-100 mt-2" type="button" data-save-draft>Review & save as draft</button></div></aside>`;
  }
  function samplePanel() {
    if(draft.source_type!=='document')return '';
    return `<details class="card config-sample mt-3" ${example?'open':''}><summary>Try one document <span>Preview the extraction format before saving</span></summary><div class="finance-card-body"><label class="form-label" for="config-sample-document">Use an existing extracted document</label><select id="config-sample-document" class="form-select mb-3"><option value="">Use the example text below</option>${(api.state.sample_documents || []).map(doc=>`<option value="${doc.pk}" ${String(doc.pk)===sampleDocument?'selected':''}>${esc(doc.fk_document_no__file_name)} · extraction #${doc.pk}</option>`).join('')}</select><label class="form-label" for="config-sample-text">Example document text</label><textarea id="config-sample-text" rows="4" class="form-control" placeholder="Paste the text of one document">${esc(draft.sample_text)}</textarea><button type="button" class="btn btn-falcon-default mt-3" data-preview-document>Preview one document</button><p class="config-note">Uses your current instructions. This preview does not create an accounting record.</p>${example?`<div data-sample-output><div class="config-validation">Sample output — check values and issues before relying on this setup.</div><pre class="config-json">${esc(JSON.stringify(example.preview,null,2))}</pre><a href="${esc(activity.detailURL(example.llm_log_no))}">View preview attempt</a></div>`:''}</div></details>`;
  }
  function submissionDialog() {
    return `<dialog class="config-submit" id="configuration-submit" aria-labelledby="configuration-submit-title"><form id="configuration-submit-form"><h2 id="configuration-submit-title">Is everything correct?</h2><p>Review <strong>${esc(draft.name)}</strong> for ${esc(targetFor(draft).label.toLowerCase())}. ${review?.submit?'Confirming saves and activates this setup for extraction.':'Confirming saves a draft for later; it is not active for extraction.'}</p><dl class="config-guide-list config-confirm-summary mb-3">${[
      ['Source',draft.source_type==='database'?`${draft.connection} · ${draft.table}`:draft.document_type],
      ['Account scope',scopeLabel(draft)],
      ['Instructions',draft.source_type==='database'?`${Object.keys(draft.field_mappings).length} header mappings; keys: ${draft.source_keys}`:draft.extraction_context],
      ['Line items',draft.source_type==='database'?[draft.line_table,draft.line_joins].filter(Boolean).join(' · '):draft.line_item_context],
      ['Formatting',`${draft.encoding_rules.default_currency} · ${draft.encoding_rules.date_format}`],
      ['Review rules',`Duplicates: ${draft.encoding_rules.duplicate_policy}; missing values: ${draft.encoding_rules.missing_value_policy}`],
    ].filter(([,value])=>value).map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl><details class="config-guide-details mb-3"><summary>View every configuration field</summary><pre class="config-json">${esc(JSON.stringify(payload().configuration,null,2))}</pre></details><label class="form-check mb-3"><input class="form-check-input" type="checkbox" id="config-review-confirmation" required><span class="form-check-label">The source, fields, instructions, and rules are correct. Save this configuration.</span></label><div id="config-confirm-error" class="config-feedback" role="alert"></div><div class="finance-actions justify-content-end"><button class="btn btn-falcon-default" type="button" data-cancel-submit>Keep editing</button><button class="btn btn-primary" id="config-confirm-submit" type="submit" disabled>Confirm & save${review?.submit?' configuration':' draft'}</button></div></form></dialog>`;
  }
  function importControls() {
    if(draft.source_type!=='database')return '';
    const history=importRuns.filter(run=>run.configuration_id===draft.id);
    const historyMarkup=history.map(run=>`<details class="mt-2"><summary>Import #${run.id} · ${esc(run.status)} · ${esc(new Date(run.created_at).toLocaleString())}</summary><pre class="config-json">${esc(JSON.stringify(run.result,null,2))}</pre></details>`).join('');
    if(draft.status!=='submitted')return historyMarkup?`<section class="card p-3 mb-3"><h2 class="fs-9">Recent imports</h2>${historyMarkup}</section>`:'';
    return `<section class="card p-3 mb-3"><h2 class="fs-9">Update data</h2><p>Review all matching records in the saved setup before updating accounting data.</p><a class="btn btn-primary" href="${baseURL+draft.id+'/'}">Open data update setup</a>${historyMarkup}</section>`;
  }
  function render() {
    if(!draft){root.innerHTML=`<header class="finance-heading"><div><h1>Set up extraction</h1><p>Select what you want to configure before starting a conversation.</p></div></header>${selectionPanel()}<div class="finance-callout">Select both a record type and an extraction source to see the required fields and start its chat.</div>`;return;}
    root.innerHTML=`<nav class="finance-breadcrumb" aria-label="Breadcrumb"><a href="${baseURL}">Extraction setup</a>${icon('chevron-right')}<span aria-current="page">${esc(draft.name || 'New configuration')}</span></nav><header class="finance-heading"><div><h1>${draft.id===null?'Set up extraction with a conversation':esc(draft.name)}</h1><p>Tell us what you need. Build your configuration together, then confirm the details.</p></div><div class="finance-actions"><a class="btn btn-falcon-default config-guide-jump" href="#configuration-guide">View configuration guide</a><span id="config-header-status">${status(draft)}</span></div></header>${selectionPanel()}${requirementsPanel()}<div id="config-error" class="finance-form-error" role="alert" tabindex="-1" hidden></div><div id="config-submission-banner">${draft.submitted_snapshot?'<div class="config-submitted">Your last confirmed setup is preserved. Changes here need a new review and confirmation.</div>':''}</div>${importControls()}<div class="config-layout config-chat-layout"><div>${assistant()}${samplePanel()}<button type="button" class="btn btn-link config-advanced-toggle mt-3" data-toggle-advanced aria-expanded="${showAdvanced}">${icon('sliders-h')} ${showAdvanced?'Hide':'Open'} detailed settings</button>${showAdvanced?`<section class="mt-3"><ol class="config-stepper" aria-label="Configuration steps">${['Record & source',draft.source_type==='database'?'Field mapping':'Instructions','Encoding rules','Detailed review'].map((title,index)=>`<li><button type="button" data-goto-step="${index}" ${step===index?'aria-current="step"':''}>${title}</button></li>`).join('')}</ol><form class="config-form" id="configuration-main" novalidate>${[sourceStep,mappingStep,rulesStep,reviewStep][step]()}</form></section>`:''}</div>${guide()}</div>${submissionDialog()}${resetDialog()}`;
    bindAssistant();
    root.querySelector('#configuration-reset').addEventListener('cancel',event=>{if(resetBusy)event.preventDefault();});
    const dialog=root.querySelector('#configuration-submit');
    root.querySelector('#config-review-confirmation').addEventListener('change',event=>{root.querySelector('#config-confirm-submit').disabled=!event.target.checked;});
    root.querySelector('[data-cancel-submit]').addEventListener('click',()=>dialog.close());
    root.querySelector('#configuration-submit-form').addEventListener('submit',async event=>{
      event.preventDefault();
      if(root.querySelector('#config-review-confirmation').checked)await saveDraft();
    });
    root.querySelector('#config-sample-document')?.addEventListener('change',event=>{sampleDocument=event.target.value;example=null;root.querySelector('[data-sample-output]')?.remove();});
    root.querySelector('#config-sample-text')?.addEventListener('input',event=>{draft.sample_text=event.target.value;edited();});
    if(chatBusy || contextBusy)root.querySelectorAll('button,input,select,textarea').forEach(control=>control.disabled=true);
  }
  function inputChange(element) {
    const path=element.dataset.path;
    set(draft,path,element.type==='checkbox'?element.checked:element.value);
    if(['database_source','source_table','line_source_table'].includes(path)) {
      if(path==='database_source'){draft.source_table=null;draft.line_source_table=null;draft.source_keys='';draft.line_joins='';draft.field_mappings={};draft.line_item_mappings={};}
      if(path==='source_table'){draft.source_keys='';draft.line_joins='';draft.field_mappings={};}
      if(path==='line_source_table'){draft.line_joins='';draft.line_item_mappings={};}
      const header=api.state.tables.find(table=>String(table.id)===String(draft.source_table));
      const lines=api.state.tables.find(table=>String(table.id)===String(draft.line_source_table));
      draft.connection=api.state.sources.find(source=>String(source.id)===String(draft.database_source))?.name || '';
      draft.table=header?.name || '';draft.columns=(header?.columns || []).join('\n');
      draft.line_table=lines?.name || '';draft.line_columns=(lines?.columns || []).join('\n');draft.include_lines=Boolean(lines);
      edited();render();return;
    }
    edited();
    if(path==='include_lines')render();else refreshIndicators();
  }
  function refreshIndicators() {
    const element=root.querySelector('#config-header-status');if(element)element.innerHTML=status(draft);
    const current=root.querySelector('.config-guide');if(current)current.outerHTML=guide();
    const requirements=root.querySelector('.config-requirements');if(requirements)requirements.outerHTML=requirementsPanel();
  }
  function exportJSON() {
    const result=draft.status==='submitted'?draft.submitted_snapshot:payload();
    const href=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const anchor=document.createElement('a');anchor.href=href;anchor.download=`${config.mode}-${draft.target_entity}-configuration-r${draft.revision}.json`;anchor.click();URL.revokeObjectURL(href);notify('Configuration JSON exported.');
  }
  root.addEventListener('submit',event=>{if(event.target.id==='configuration-main')event.preventDefault();});
  root.addEventListener('input',event=>{
    const element=event.target;
    if(element.matches('#configuration-main [data-path], .config-scope-fields [data-path]')&&element.tagName!=='SELECT'&&element.type!=='checkbox')inputChange(element);
  });
  root.addEventListener('change',event=>{
    const element=event.target;
    if(element.matches('#configuration-main [data-path], .config-scope-fields [data-path]')&&(element.tagName==='SELECT'||element.type==='checkbox'))inputChange(element);
    if(element.matches('[data-required]')) {
      const name=element.dataset.required;
      const group=element.dataset.requiredGroup==='line'?'line_required_fields':'required_fields';
      draft.encoding_rules[group]=element.checked?[...new Set([...draft.encoding_rules[group],name])]:draft.encoding_rules[group].filter(value=>value!==name);
      edited();refreshIndicators();
    }
  });
  root.addEventListener('click',event=>{
    const action=event.target.closest('button,a');if(!action)return;
    if(action.hasAttribute('data-select-target')) {selectSetup(action.dataset.selectTarget,selectedSource);return;}
    if(action.hasAttribute('data-select-source')) {selectSetup(selectedTarget,action.dataset.selectSource);return;}
    if(!draft || resetBusy)return;
    if(action.hasAttribute('data-refresh-context'))refreshContext();
    else if(action.hasAttribute('data-refresh-schema'))refreshContext(true);
    else if(action.hasAttribute('data-clear-chat'))clearContext();
    else if(action.hasAttribute('data-reset-context')) {
      if(chatBusy || contextBusy)return;
      contextVersion++;review=null;
      root.querySelector('#configuration-reset').showModal();
    }
    else if(action.hasAttribute('data-cancel-reset'))root.querySelector('#configuration-reset').close();
    else if(action.hasAttribute('data-confirm-reset'))resetContext();
    else if(action.hasAttribute('data-undo-clear')&&lastCleared&&!chatBusy&&!contextBusy){contextVersion++;({draft,dirty,chatInput,sampleDocument,example}=lastCleared);lastCleared=null;review=null;render();}
    else if(action.hasAttribute('data-goto-step')) {event.preventDefault();step=Number(action.dataset.gotoStep);showAdvanced=true;rememberURL();render();root.querySelector('.config-stepper [aria-current="step"]').focus();}


    else if(action.hasAttribute('data-toggle-advanced')) {showAdvanced=!showAdvanced;render();}
    else if(action.hasAttribute('data-preview-document')) {
      const version=contextVersion;
      api.post('configuration-preview',draft.id,{configuration:payload().configuration,text_log_id:sampleDocument || null}).then(result=>{
        if(version!==contextVersion)return;
        draft.sample_text=result.sample_text;edited();example=result;render();
      }).catch(problem=>{if(version===contextVersion)error(problem.message);});
    }
    else if(action.hasAttribute('data-save-draft'))requestReview(false);
    else if(action.hasAttribute('data-export'))exportJSON();
    else if(action.hasAttribute('data-submit-review'))requestReview(true);
  });
  window.addEventListener('finance-llm-storage-error',event=>error(event.detail));

  const previewNote=document.querySelector('.finance-preview-note > span:nth-child(2)');
  previewNote.textContent='Chat builds an unsaved setup. Review and confirm to save. Assistant attempts are logged.';
  window.addEventListener('beforeunload',event=>{if(dirty || [...sessions.values()].some(session=>session.dirty && session.draft!==draft)){event.preventDefault();event.returnValue='';}});
  if(config.screen==='list')list();
  else {
    if(config.recordId!==null)draft=state.profiles.find(profile=>profile.id===config.recordId);
    else {
      selectedTarget=catalog.some(target=>target.key===parameters.get('target'))?parameters.get('target'):'';
      selectedSource=['document','database'].includes(parameters.get('source'))?parameters.get('source'):'';
      selectSetup(selectedTarget,selectedSource);return;
    }
    if(!draft){root.innerHTML=`<div class="finance-empty"><h1>Configuration unavailable</h1><p>Reload to see current configurations.</p>${link(baseURL,'Back to configurations')}</div>`;return;}
    selectedTarget=draft.target_entity;selectedSource=draft.source_type;
    draft.encoding_rules.line_required_fields = [];
    draft.line_field_instructions ||= {};
    draft.relation_lookups ||= {};
    render();refreshContext();
  }
})();
