/* Record-first database setup using saved metadata, assistant proposals and read-only server tests. */
(() => {
  'use strict';
  const engine = window.ConfigurationQueryEngine;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const selected = (a,b) => a === b ? ' selected' : '';
  const sourceName=key=>({supplier_name:'supplier_company_name',customer_name:'customer_company_name',phone:'contact_number',payment_terms_days:'terms'}[key]||key);
  const sourceSchema=(sources,id)=>Object.fromEntries((sources.find(source=>String(source.id)===String(id))?.tables||[]).map(table=>[table.id,table]));
  const ops = [['eq','is'],['ne','is not'],['contains','contains'],['starts','starts with'],['gt','greater than'],['gte','at least'],['lt','less than'],['lte','at most'],['in','is one of'],['empty','is empty'],['not_empty','is not empty']];
  const btn = (label,action,extra='',style='btn-falcon-default') => `<button type='button' class='btn ${style} btn-sm' data-qaction='${action}' ${extra}>${label}</button>`;
  function mount(root, options) {
    const {destination,mode,target,api} = options;
    const fields = [...destination.fields.map(field => ({...field,id:'header:'+field.key,label:field.label})),...destination.lineFields.map(field => ({...field,id:'line:'+field.key,label:'Line · '+field.label}))];
    let state = options.state;
    let schema = sourceSchema(options.sources,state ? state.database : options.sources[0]?.id||'');
    const suggestedTable=()=>Object.keys(schema).map(id=>({id,score:destination.fields.filter(field=>schema[id].columns.some(column=>[field.key,sourceName(field.key)].includes(column.name))).reduce((sum,field)=>sum+(field.required?5:1),0)})).sort((a,b)=>b.score-a.score)[0]?.id||'';
    const usedIds=[...JSON.stringify(state||{}).matchAll(/\"id\":\"(?:table|filter|group)(\d+)\"/g)].map(match=>Number(match[1])+1);
    let serial = Math.max(state?.serial||1,...usedIds);
    const uid = prefix => prefix + serial++;
    function mappingsFor(table) {
      return fields.map(field => {
        const column = field.id.startsWith('header:') && schema[table]?.columns.find(column => [field.key,sourceName(field.key)].includes(column.name));
        return {...field,include:!!column || field.required,method:column ? 'column' : 'empty',column:column ? 'base.'+column.name : '',value:''};
      });
    }
    if (!state) state = {database:options.sources[0]?.id||'',table:suggestedTable(),keys:[],joins:[],filters:{id:'root',logic:'all',children:[]},sorts:[],distinct:false,limit:5,
      mappings:mappingsFor(suggestedTable()),section:'source',messages:[],draft:'',result:null,stale:false,confirmed:false,notice:'',mapSearch:'',mapFilter:'all',sourceRows:false};
    state.mappings=fields.map(field=>({include:field.required,method:'empty',column:'',value:'',...field,...state.mappings?.find(item=>item.id===field.id)}));
    state.messages ||= [];state.section ||= 'source';state.serial ||= 1;state.filters ||= {id:'root',logic:'all',children:[]};state.sorts ||= [];state.limit ||= 5;state.mapSearch ||= '';state.mapFilter ||= 'all';
    // Saved query rules omit editor identifiers. Restore them before binding the controls.
    function identifyFilters(group=state.filters, root=true) {
      group.id ||= root ? 'root' : uid('group');
      group.children.forEach(rule => {
        if (rule.children) identifyFilters(rule, false);
        else rule.id ||= uid('filter');
      });
    }
    identifyFilters();
    state.keyMode ||= 'auto';
    state.keyFields ||= [];
    state.keyEditor ||= false;
    const automaticKeys = () => (schema[state.table]?.columns||[]).filter(column=>column.key==='Primary key').map(column=>'base.'+column.name);
    function syncKeys() {state.keys=state.keyMode==='custom'?state.keyFields.map(field=>field.column):automaticKeys();}
    syncKeys();
    const columns = () => engine.available(schema,state);
    const findGroup = (id,group=state.filters) => {if(group.id===id)return group; for(const child of group.children){if(child.children){const found=findGroup(id,child);if(found)return found;}}};
    const findRule = (id,group=state.filters) => {for(const child of group.children){if(child.id===id)return child;if(child.children){const found=findRule(id,child);if(found)return found;}}};
    const removeRule = (id,group=state.filters) => {group.children=group.children.filter(child=>child.id!==id);group.children.filter(child=>child.children).forEach(child=>removeRule(id,child));};
    const countRules = (group=state.filters) => group.children.reduce((total,child)=>total+(child.children?countRules(child):1),0);
    const columnLabel = reference => {const column=columns().find(item=>item.ref===reference);return column ? (schema[column.table]?.name||'Table')+'.'+column.name+(column.alias==='base'?'':' ('+column.alias+')') : 'Choose a column';};
    const colOptions = (value, list=columns()) => `<option value=''>Choose a column</option>` + list.map(column => `<option value='${esc(column.ref)}'${selected(column.ref,value)}>${esc((schema[column.table]?.name||'Table')+'.'+column.name+(column.alias==='base'?'':' · '+column.alias))}</option>`).join('');
    const tableOptions = value => Object.keys(schema).map(name=>`<option value='${name}'${selected(name,value)}>${esc(schema[name].name)}</option>`).join('');
    const sources = () => [...(state.table?[{id:'base',table:state.table}]:[]),...state.joins];
    const sourceAlias = item => item.column ? item.column.split('.')[0] : item.tableAlias || '';
    function sourceOptions(value) {
      return "<option value=''>Choose a table</option>" + Object.keys(schema).map(table => {
        const connected = sources().filter(source => source.table === table);
        return (connected.length ? connected : [{id:'@table:'+table,table}]).map(source => `<option value='${source.id}'${selected(source.id,value)}>${esc(schema[table].name)}${connected.length>1?' · '+source.id:''}</option>`).join('');
      }).join('');
    }
    function sourcePicker(item, kind, id, label) {
      const alias = sourceAlias(item), value = kind==='map' && item.method!=='column' ? '@'+item.method : alias;
      const source = sources().find(source => source.id === alias);
      const manual = kind==='map' && item.method==='value', blank = kind==='map' && item.method==='empty';
      return `<div class='qb-source-picker'><div><label for='qb-${kind}-table-${id}'>Table${kind==='map'?' or value':''}</label><select id='qb-${kind}-table-${id}' class='form-select' aria-label='Table for ${esc(label)}' data-${kind}-table='${id}'>${sourceOptions(value)}${kind==='map'?`<option value='@value'${selected(value,'@value')}>Use a value I provide</option><option value='@empty'${selected(value,'@empty')}>Leave empty when unavailable</option>`:''}</select></div><div>${manual?`<label for='qb-map-value-${id}'>Value</label><input id='qb-map-value-${id}' class='form-control' aria-label='Value for ${esc(label)}' data-map-value='${id}' value='${esc(item.value)}'>`:blank?`<span class='qb-picker-note'>This field will be left empty.</span>`:`<label for='qb-${kind}-column-${id}'>Column</label><select id='qb-${kind}-column-${id}' class='form-select' aria-label='Column for ${esc(label)}' data-${kind}-column='${id}'${source?'':' disabled'}><option value=''>${source?'Choose a column':'Choose a table first'}</option>${(source?(schema[source.table]?.columns||[]):[]).map(column=>`<option value='${alias}.${column.name}'${selected(alias+'.'+column.name,item.column)}>${esc(column.name)}</option>`).join('')}</select>`}</div></div>`;
    }
    function chooseTable(item, value, mapping=false) {
      item.column=''; item.value=''; item.tableAlias='';
      if (mapping) item.method=value==='@value'?'value':value==='@empty'?'empty':'column';
      if (!value || value==='@value' || value==='@empty') return '';
      if (!value.startsWith('@table:')) {item.tableAlias=value;return '';}
      if(!state.table){state.table=value.slice(7);item.tableAlias='base';return 'Choose the source column for this field.';}
      const connection = engine.connectTable(schema,state,value.slice(7),()=>uid('table'));
      item.tableAlias=connection.alias;
      return connection.needsMatch ? 'Choose matching columns in Choose data to connect this table before testing.' : connection.added.length ? 'Connected '+connection.added.map(table=>schema[table].name).join(' → ')+'. Choose its column, then test the result.' : '';
    }
    function chooseColumn(item,value) {item.tableAlias=sourceAlias(item);item.column=value;}
    const included = () => state.mappings.filter(field=>field.include);
    const missing = () => included().filter(field=>field.method==='column'&&!columns().some(column=>column.ref===field.column)||field.required&&(field.method==='empty'||field.method==='value'&&!field.value));
    function dirty(message='') {api.changed();state.confirmed=false;if(state.result)state.stale=true;state.notice=message;}
    function filterRule(column='') {return {id:uid('filter'),column,tableAlias:column?column.split('.')[0]:'',operator:'eq',value:''};}
    function suggestJoin(table, from) {
      for (const source of sources().filter(source=>!from||source.id===from)) {
        const forward = (schema[source.table]?.references||[]).find(link=>link.table===table);
        if (forward) return forward.pairs.map(pair=>({left:source.id+'.'+pair.column,right:pair.target}));
        const reverse = (schema[table]?.references||[]).find(link=>link.table===source.table);
        if (reverse) return reverse.pairs.map(pair=>({left:source.id+'.'+pair.target,right:pair.column}));
      }
      return [{left:'',right:''}];
    }
    function addJoin(table=Object.keys(schema).find(id=>id!==state.table)||state.table,from) {
      const join = {id:uid('table'),table,type:'left',on:suggestJoin(table,from)};state.joins.push(join);return join;
    }
    function remapAvailable() {
      state.mappings.forEach(field=>{
        const preferred=sourceName(field.key);
        const column=columns().find(column=>[field.key,preferred].includes(column.name)&&(field.id.startsWith('line:')?(schema[column.table]?.name||'').match(/line|item|detail/i):!(schema[column.table]?.name||'').match(/line|item|detail/i)));
        if(column){field.include=true;field.method='column';field.column=column.ref;}
      });
    }
    function cleanReferences() {
      const valid = new Set(columns().map(column=>column.ref)), aliases = new Set(sources().map(source=>source.id));
      const cleanItem = item => {if(item.column&&!valid.has(item.column)){item.column='';item.value='';}if(!aliases.has(item.tableAlias))item.tableAlias='';};
      state.mappings.forEach(cleanItem);state.keyFields.forEach(cleanItem);
      const clean=group=>group.children.forEach(child=>child.children?clean(child):cleanItem(child));clean(state.filters);
      state.sorts.forEach(cleanItem);syncKeys();
    }
    function sourcePanel() {
      return `<div><label for='qb-database'>Database</label><select id='qb-database' class='form-select'><option value=''>Choose a database connection</option>${options.sources.map(source=>`<option value='${source.id}'${selected(String(state.database),String(source.id))}>${esc(source.name)}</option>`).join('')}</select><div class='my-2'>${btn('Refresh database schema','refresh-schema',state.database?'':'disabled')}</div><p class='lab-note mt-2'>Choose a table and column beside each field or row condition. Known table relationships will be connected for you.</p></div>
        <div class='qb-section-line'><div><strong>Table connections</strong><p class='lab-note mb-0'>Connections appear as you select tables. Review them here, or add a custom connection.</p></div>${btn('+ Add related table','add-join',state.table?'':'disabled')}</div>
        ${state.joins.length?`<div class='qb-joins'>${state.joins.map(joinPanel).join('')}</div>`:`<p class='qb-muted-state'>Fields currently use <strong>${esc(schema[state.table]?.name||'No table selected yet')}</strong>. Select another table in Map fields or Refine rows to connect more data.</p>`}
        <details class='lab-details'><summary>Browse source columns (${columns().length})</summary><label class='visually-hidden' for='qb-column-search'>Search source columns</label><input id='qb-column-search' class='form-control mt-2' placeholder='Search column names or tables'><div class='qb-column-list'>${columns().map(column=>`<div data-column-search='${esc((column.table+' '+column.name).toLowerCase())}'><code>${esc((schema[column.table]?.name||'Table')+'.'+column.name)}</code><span>${esc(column.key||column.type)}</span></div>`).join('')}</div></details>
        <div class='qb-next'>${btn('Continue to field mapping','section',"data-section='mapping'",'btn-primary')}</div>`;
    }
    function joinPanel(join,index) {
      const earlier = columns().filter(column=>column.alias==='base'||state.joins.slice(0,index).some(item=>item.id===column.alias));
      return `<div class='qb-join'><div class='qb-section-line'><strong>Connection ${index+1} <small class='text-muted'>${join.id}</small></strong>${btn('Remove','remove-join',`data-id='${join.id}' aria-label='Remove connection ${index+1}'`,'btn-link text-danger')}</div>
        <div class='qb-form-grid'><div><label for='qb-table-${join.id}'>Related table</label><select id='qb-table-${join.id}' class='form-select' data-join-table='${join.id}'>${tableOptions(join.table)}</select></div><div><label for='qb-kind-${join.id}'>When there is no match</label><select id='qb-kind-${join.id}' class='form-select' data-join-type='${join.id}'><option value='left'${selected(join.type,'left')}>Keep the existing row</option><option value='inner'${selected(join.type,'inner')}>Leave that row out</option></select></div></div>
        ${join.on.map((pair,pairIndex)=>`<div class='qb-match'><div><label for='qb-left-${join.id}-${pairIndex}'>Match this column</label><select id='qb-left-${join.id}-${pairIndex}' class='form-select' data-join-left='${join.id}' data-pair='${pairIndex}'>${colOptions(pair.left,earlier)}</select></div><span>equals</span><div><label for='qb-right-${join.id}-${pairIndex}'>To the related column</label><select id='qb-right-${join.id}-${pairIndex}' class='form-select' data-join-right='${join.id}' data-pair='${pairIndex}'><option value=''>Choose a column</option>${(schema[join.table]?.columns||[]).map(column=>`<option value='${column.name}'${selected(column.name,pair.right)}>${esc(column.name)}</option>`).join('')}</select></div>${pairIndex?btn('×','remove-pair',`data-id='${join.id}' data-index='${pairIndex}' aria-label='Remove matching pair ${pairIndex+1} from connection ${index+1}'`):''}</div>`).join('')}
        ${btn('+ Match another column','add-pair',`data-id='${join.id}'`,'btn-link')}<p class='lab-note mb-0'>Every matching pair must agree. Multiple matches can produce extra rows; the test will show them.</p></div>`;
    }
    function mappingPanel() {
      return `<div class='qb-section-line'><p class='lab-note mb-0'>Choose a table, then a column for each field. You can use different tables and uncheck optional fields.</p>${btn('Suggest matches','suggest-map')}</div>
        <div class='qb-form-grid my-3'><input id='qb-map-search' class='form-control' aria-label='Search field mappings' placeholder='Search fields or columns' value='${esc(state.mapSearch)}'><select id='qb-map-filter' class='form-select' aria-label='Show field mappings'><option value='all'${selected(state.mapFilter,'all')}>All fields (${fields.length})</option><option value='required'${selected(state.mapFilter,'required')}>Required fields</option><option value='missing'${selected(state.mapFilter,'missing')}>Needs mapping (${missing().length})</option></select></div>
        <div class='qb-mappings'>${state.mappings.map((field,index)=>`<div class='qb-map-row' data-map-row='${index}'><div><label class='qb-map-label'><input type='checkbox' data-map-include='${index}'${field.include?' checked':''}${field.required?' disabled':''}>${esc(field.label)}${field.required?'<small>Required</small>':''}</label></div><div class='qb-map-controls'>${field.include?sourcePicker(field,'map',index,field.label):"<span class='lab-note'>Not included in this query</span>"}</div></div>`).join('')}</div><p id='qb-no-mappings' class='lab-note' hidden>No fields match your search.</p>
        <details class='lab-details'><summary>Value conversions</summary>${state.mappings.filter(field=>field.include&&field.method==='column').map(field=>`<div class='qb-form-grid my-2'><label for='qb-transform-${field.id}'>${esc(field.label)}</label><select class='form-select' id='qb-transform-${field.id}' data-map-transform='${field.id}'><option value='identity'${selected(field.transform||'identity','identity')}>Automatic field conversion</option><option value='trim'${selected(field.transform,'trim')}>Trim surrounding spaces</option><option value='uppercase'${selected(field.transform,'uppercase')}>Uppercase</option><option value='json'${selected(field.transform,'json')}>Read JSON text</option></select></div>`).join('')}</details><div class='qb-next'>${btn('Continue to row filters','section',"data-section='filters'",'btn-primary')}</div>`;
    }
    function filterInput(rule) {
      if (['empty','not_empty'].includes(rule.operator)) return '<span class="lab-note">No value needed</span>';
      const column = columns().find(column => column.ref === rule.column);
      if (column?.type === 'boolean' && ['eq','ne'].includes(rule.operator)) return `<select class='form-select' aria-label='Filter value ${rule.id}' data-filter-value='${rule.id}'><option value=''>Choose Yes or No</option><option value='true'${selected(rule.value,'true')}>Yes</option><option value='false'${selected(rule.value,'false')}>No</option></select>`;
      return `<input class='form-control' aria-label='Filter value ${rule.id}' data-filter-value='${rule.id}' placeholder='${rule.operator==='in'?'Values separated by commas':column?.type==='date'?'YYYY-MM-DD':'Value'}' value='${esc(rule.value)}'>`;
    }
    function describeFilters(group=state.filters) {
      if (!group.children.length) return 'All rows';
      return '(' + group.children.map(rule => rule.children ? describeFilters(rule) : columnLabel(rule.column) + ' ' + (ops.find(op => op[0]===rule.operator)?.[1] || rule.operator) + (['empty','not_empty'].includes(rule.operator) ? '' : ' ' + rule.value)).join(group.logic==='any' ? ' OR ' : ' AND ') + ')';
    }
    function groupPanel(group,depth=0) {
      return `<div class='qb-filter-group${depth?' nested':''}'><div class='qb-section-line'><label class='qb-inline'>Match <select class='form-select' aria-label='Match conditions in group ${group.id}' data-group-logic='${group.id}'><option value='all'${selected(group.logic,'all')}>All conditions (AND)</option><option value='any'${selected(group.logic,'any')}>Any condition (OR)</option></select></label>${depth?btn('Remove group','remove-rule',`data-id='${group.id}'`,'btn-link text-danger'):''}</div>
        ${group.children.map(rule=>rule.children?groupPanel(rule,depth+1):`<div class='qb-condition'><div class='qb-condition-fields'>${sourcePicker(rule,'filter',rule.id,'filter '+rule.id)}<div class='qb-condition-values'><div><label for='qb-op-${rule.id}'>Comparison</label><select id='qb-op-${rule.id}' class='form-select' aria-label='Filter comparison ${rule.id}' data-filter-operator='${rule.id}'>${ops.map(([key,label])=>`<option value='${key}'${selected(key,rule.operator)}>${label}</option>`).join('')}</select></div><div><label>Value</label>${filterInput(rule)}</div></div></div>${btn('×','remove-rule',`data-id='${rule.id}' aria-label='Remove filter ${rule.id}'`)}</div>`).join('')}
        ${!group.children.length?'<p class="lab-note my-3">No conditions. All rows in this group are allowed.</p>':''}<div class='qb-inline'>${btn('+ Add condition','add-filter',`data-id='${group.id}'`)}${btn('+ Add condition group','add-group',`data-id='${group.id}'`,'btn-link')}</div></div>`;
    }
    function filtersPanel() {
      return `<div class='qb-section-line'><p class='lab-note'>Choose a table and column, then set the condition. Add more conditions or groups as needed. Filtering a related table can exclude rows without a match.</p>${countRules()?btn('Clear filters','clear-filters','','btn-link'):''}</div>${groupPanel(state.filters)}
        <details class='lab-details'${state.sorts.length||state.distinct?' open':''}><summary>Sorting & duplicate rows${state.sorts.length?' · '+state.sorts.length+' sort(s)':''}</summary>
        ${state.sorts.map((sort,index)=>`<div class='qb-sort'>${sourcePicker(sort,'sort',index,'sort '+(index+1))}<select class='form-select' aria-label='Sort direction ${index+1}' data-sort-direction='${index}'><option value='asc'${selected(sort.direction,'asc')}>Ascending</option><option value='desc'${selected(sort.direction,'desc')}>Descending</option></select>${btn('Remove','remove-sort',`data-index='${index}' aria-label='Remove sort ${index+1}'`)}</div>`).join('')}${btn('+ Add sort','add-sort','','btn-link')}
        <label class='qb-check mt-3'><input type='checkbox' id='qb-distinct'${state.distinct?' checked':''}>Hide exactly repeated output rows</label><p class='lab-note'>Rows with the same identifier but different values still need review.</p></details>`;
    }
    function assistantPanel() {
      return `<aside class='qb-assistant card'><div class='finance-card-head'><div><h2>Setup assistant</h2><p class='lab-note mb-0'>Ask for help or describe a change.</p></div>${btn('Reset chat','reset-chat','','btn-link')}</div><div class='finance-card-body'><div class='qb-understood'><strong>What this query will do</strong><p>${sources().length?'Use '+sources().map(source=>'<b>'+esc(schema[source.table]?.name||'Choose table')+'</b>').join(', ')+'.':'Choose a database, then select a table and column for each field.'}</p><p>${included().length} output fields · ${countRules()} conditions · ${state.sorts.length} sorts</p></div>
        <div class='lab-chat qb-chat' role='log' aria-label='Database setup conversation'><div class='lab-bubble'><small>CONFIGURATION ASSISTANT</small>Pick a table and column for each field. I can help you connect information from other tables or narrow down the rows.</div>${state.messages.map(message=>`<div class='lab-bubble ${message.role==='user'?'user':''}'><small>${message.role==='user'?'YOU':'CONFIGURATION ASSISTANT'}</small>${esc(message.text)}</div>`).join('')}</div>
        <div class='lab-suggestions'>${btn('Only active records','chat-active')}${btn('Add billing address','chat-address')}${btn('Explain this query','chat-explain')}</div><form id='qb-chat-form'><label for='qb-message'>Your instruction</label><textarea id='qb-message' class='form-control' rows='3' placeholder='e.g. Only active records with at least 30-day terms'>${esc(state.draft)}</textarea><div class='lab-chat-footer'><small>Uses your configured setup assistant.</small><button class='btn btn-primary btn-sm' type='submit'>Apply</button></div></form></div></aside>`;
    }
    function rowIdentityPanel() {
      return `<div class='qb-row-identity'>${btn('Advanced: row identification'+(state.keyMode==='custom'?' · Custom':''),'toggle-keys',`aria-expanded='${state.keyEditor}' aria-controls='qb-key-settings'`,'btn-link')}${state.keyEditor?`<div id='qb-key-settings' class='qb-key-settings'><p class='lab-note'>${state.keyMode==='auto'?'Rows are identified automatically using the primary key: <strong>'+esc(state.keys.map(columnLabel).join(' + '))+'</strong>. Choose custom columns only if your result needs a different identifier.':'Choose a table and column for each part of the identifier. The combined values must identify one result row.'}</p>${state.keyMode==='auto'?btn('Choose custom columns','custom-keys'):state.keyFields.map((field,index)=>`<div class='qb-key-row'>${sourcePicker(field,'key',index,'row identifier '+(index+1))}${state.keyFields.length>1?btn('Remove','remove-key',`data-index='${index}' aria-label='Remove row identifier ${index+1}'`,'btn-link text-danger'):''}</div>`).join('')+`<div class='qb-inline mt-2'>${btn('+ Add column','add-key')}${btn('Use automatic identification','auto-keys','','btn-link')}</div>`}</div>`:`<div id='qb-key-settings' hidden></div>`}</div>`;
    }
    function resultPanel() {
      const result=state.result;
      const headers=state.sourceRows?columns().map(column=>({id:column.ref,label:(schema[column.table]?.name||'Table')+'.'+column.name})):included();
      const rows=result?(state.sourceRows?result.rawRows:result.rows):[];
      // Keep the tested columns when current mappings change; never relabel stale values.
      const shownHeaders=result?.headers && !state.sourceRows ? result.headers : headers;
      const shownSourceHeaders=result?.sourceHeaders && state.sourceRows ? result.sourceHeaders : shownHeaders;
      return `<section class='card qb-results' id='qb-results'><div class='finance-card-head'><div><h2>Test your query</h2><p class='lab-note mb-0'>Preview records from your database in a read-only transaction.</p></div><span class='finance-status ${result&&!state.stale&&!result.issues.length&&result.count?'success':'info'}'>${state.stale?'Changed · test again':result?'Test complete':'Not tested'}</span></div><div class='finance-card-body'>
        <div class='qb-test-bar'><label class='qb-inline'>Preview <select class='form-select' id='qb-limit'><option value='5'${selected(state.limit,5)}>5 rows</option><option value='10'${selected(state.limit,10)}>10 rows</option><option value='25'${selected(state.limit,25)}>25 rows</option></select></label>${btn(result?'Run test again':'Test query','test-query','','btn-primary')}${result?`<span class='lab-note'>${result.count} matching row(s) · showing ${rows.length}</span>`:''}</div>
        ${result?.issues.length?`<div class='finance-callout warning mt-3' role='alert'><strong>Review these details</strong><ul class='mb-0'>${result.issues.map(issue=>`<li>${esc(issue)}</li>`).join('')}</ul>${result.duplicateCount||result.issues.some(issue=>/identifier|identify each result row/.test(issue))?btn('Review row identification','review-keys','','btn-link mt-2'):''}</div>`:''}
        ${!result?`<div class='qb-empty'><span class='fas fa-table' aria-hidden='true'></span><strong>Your mapped records will appear here</strong><p>Test the selected columns, table connections, and row conditions together.</p></div>`:!rows.length?`<div class='qb-empty'><strong>${result.issues.length?'Complete the query to see rows':'No matching rows'}</strong><p>${result.issues.length?'Check the details above, then run the test again.':'Try changing or clearing the row conditions. Your setup has not been saved.'}</p>${!result.issues.length?btn('Edit row filters','section',"data-section='filters'"):''}</div>`:`<div class='qb-section-line my-3'><strong>${state.sourceRows?'Joined source rows':'Your '+esc(destination.label.toLowerCase())}</strong>${btn(state.sourceRows?'Show mapped records':'Inspect source rows','toggle-result')}</div><div class='table-responsive' tabindex='0' aria-label='Query test results'><table class='table qb-result-table'><thead><tr>${shownSourceHeaders.map(field=>`<th scope='col'>${esc(field.label)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${shownSourceHeaders.map(field=>`<td>${row[field.id]===null||row[field.id]===undefined?'<span class="text-muted">—</span>':esc(row[field.id])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
        ${rowIdentityPanel()}<div class='qb-review-bar'><p class='lab-note mb-0'>${state.confirmed?'Configuration saved and activated.':'Review the result, then confirm and save the configuration. Testing never imports accounting records.'}</p>${btn('Review & save','review-query',canConfirm()?'':'disabled','btn-primary')}</div></div></section>`;
    }
    function canConfirm() {return state.result&&!state.stale&&!state.result.issues.length&&state.result.count>0&&api.hasReceipt()&&!state.confirmed;}
    function render() {
      const active = root.contains(document.activeElement) ? document.activeElement : null;
      const focusSelector = active?.id ? '#' + CSS.escape(active.id) : active?.getAttribute('aria-label') ? '[aria-label="' + CSS.escape(active.getAttribute('aria-label')) + '"]' : active?.dataset.qaction ? '[data-qaction="' + active.dataset.qaction + '"]' + (active.dataset.section ? '[data-section="' + active.dataset.section + '"]' : '') : null;
      state.serial=serial;
      const stages=[['source','1','Choose data',`${sources().length} table(s)`],['mapping','2','Map fields',`${included().length} included${missing().length?' · '+missing().length+' need attention':''}`],['filters','3','Refine rows',countRules()+' condition(s)']];
      root.innerHTML=`<div class='qb-intro'><span class='finance-status info'>Database setup</span><p>Build the record you want. Connect its data, choose the fields, then check a few rows.</p></div>${state.notice?`<div class='qb-notice' role='status'>${esc(state.notice)}</div>`:''}<div class='qb-layout'><div class='lab-stack'>${stages.map(([key,n,title,summary])=>`<section class='card qb-stage'><button class='qb-stage-toggle' data-qaction='section' data-section='${key}' aria-expanded='${state.section===key}' aria-controls='qb-panel-${key}'><span class='qb-step'>${n}</span><span><strong>${title}</strong><small>${esc(summary)}</small></span><span class='fas fa-chevron-${state.section===key?'up':'down'}' aria-hidden='true'></span></button>${state.section===key?`<div class='finance-card-body' id='qb-panel-${key}'>${key==='source'?sourcePanel():key==='mapping'?mappingPanel():filtersPanel()}</div>`:`<div id='qb-panel-${key}' hidden></div>`}</section>`).join('')}${resultPanel()}</div>${assistantPanel()}</div><dialog class='finance-dialog lab-dialog' id='qb-dialog' aria-labelledby='qb-dialog-title'></dialog>`;
      filterMappings();
      if (focusSelector) root.querySelector(focusSelector)?.focus({preventScroll:true});
    }
    function filterMappings() {
      let count=0;
      root.querySelectorAll('[data-map-row]').forEach(row=>{
        const field=state.mappings[Number(row.dataset.mapRow)];
        const text=(field.label+' '+field.column).toLowerCase();
        row.hidden=!text.includes(state.mapSearch.toLowerCase())||(state.mapFilter==='required'&&!field.required)||(state.mapFilter==='missing'&&!missing().includes(field));
        if(!row.hidden)count++;
      });
      const empty=root.querySelector('#qb-no-mappings');if(empty)empty.hidden=count>0;
    }
    function dialog(body, submit) {
      const element=root.querySelector('#qb-dialog');element.innerHTML=body;element.showModal();
      element.querySelector('[data-close]')?.addEventListener('click',()=>element.close());
      element.querySelector('form')?.addEventListener('submit',event=>{event.preventDefault();submit?.();});
      return element;
    }
    async function runTest(){
      try{state.result=await api.testDatabase(state,state.limit);state.stale=false;state.confirmed=false;state.notice='';render();root.querySelector('#qb-results').scrollIntoView({block:'nearest',behavior:'smooth'});}catch(error){api.error(error);}
    }
    async function applyMessage(text){
      if(!text.trim())return;
      try{const response=await api.chat(text);Object.assign(state,response.record.setup_data.database);identifyFilters();state.mappings=fields.map(field=>({include:field.required,method:'empty',column:'',value:'',...field,...state.mappings.find(item=>item.id===field.id)}));state.messages.push({role:'user',text},{role:'assistant',text:response.message});state.draft='';if(response.changed)dirty('Assistant changes are visible. Run a new test before saving.');render();}catch(error){api.error(error);}
    }
    async function review(){if(canConfirm()){try{if(await api.review(true)){state.confirmed=true;state.notice='Configuration saved and activated.';render();}}catch(error){api.error(error);}}}
    root.addEventListener('input',event=>{
      const el=event.target;
      if(el.id==='qb-message')state.draft=el.value;
      if(el.id==='qb-map-search'){state.mapSearch=el.value;filterMappings();}
      if(el.id==='qb-column-search')root.querySelectorAll('[data-column-search]').forEach(row=>{row.hidden=!row.dataset.columnSearch.includes(el.value.toLowerCase());});
      if(el.dataset.filterValue){findRule(el.dataset.filterValue).value=el.value;dirty();invalidateButtons();}
      if(el.dataset.mapValue!==undefined){state.mappings[Number(el.dataset.mapValue)].value=el.value;dirty();invalidateButtons();}
    });
    function invalidateButtons(){root.querySelectorAll('[data-qaction="review-query"]').forEach(button=>button.disabled=true);const badge=root.querySelector('#qb-results .finance-status');if(badge&&state.result){badge.textContent='Changed · test again';badge.className='finance-status info';}}
    root.addEventListener('change',async event=>{
      const el=event.target, data=el.dataset;let changed=true, notice='';
      if(el.id==='qb-database'){
        state.database=el.value;schema=sourceSchema(options.sources,state.database);state.table=suggestedTable();
        state.joins=[];state.keyMode='auto';state.keyFields=[];state.keyEditor=false;syncKeys();state.filters.children=[];state.sorts=[];state.mappings=mappingsFor(state.table);state.result=null;dirty('Source changed. Mappings were suggested again; related tables and row conditions were cleared.');render();return;
      }
      if(data.keyTable!==undefined)notice=chooseTable(state.keyFields[Number(data.keyTable)],el.value);
      else if(data.keyColumn!==undefined)chooseColumn(state.keyFields[Number(data.keyColumn)],el.value);
      else if(data.joinTable){const join=state.joins.find(join=>join.id===data.joinTable);join.table=el.value;join.auto=false;join.on=[{left:'',right:''}];const clear=item=>{if(sourceAlias(item)===join.id){item.column='';item.value='';item.tableAlias=join.id;}};state.mappings.forEach(clear);state.sorts.forEach(clear);state.keyFields.forEach(clear);const visit=group=>group.children.forEach(rule=>rule.children?visit(rule):clear(rule));visit(state.filters);cleanReferences();}
      else if(data.joinType){const join=state.joins.find(join=>join.id===data.joinType);join.auto=false;join.type=el.value;}
      else if(data.joinLeft){const join=state.joins.find(join=>join.id===data.joinLeft);join.auto=false;join.on[Number(data.pair)].left=el.value;}
      else if(data.joinRight){const join=state.joins.find(join=>join.id===data.joinRight);join.auto=false;join.on[Number(data.pair)].right=el.value;}
      else if(data.mapTransform)state.mappings.find(field=>field.id===data.mapTransform).transform=el.value;
      else if(data.mapInclude!==undefined)state.mappings[Number(data.mapInclude)].include=el.checked;
      else if(data.mapTable!==undefined)notice=chooseTable(state.mappings[Number(data.mapTable)],el.value,true);
      else if(data.mapColumn!==undefined)chooseColumn(state.mappings[Number(data.mapColumn)],el.value);
      else if(data.filterTable)notice=chooseTable(findRule(data.filterTable),el.value);
      else if(data.filterColumn){const rule=findRule(data.filterColumn);chooseColumn(rule,el.value);rule.value='';}
      else if(data.filterOperator)findRule(data.filterOperator).operator=el.value;
      else if(data.filterValue)findRule(data.filterValue).value=el.value;
      else if(data.groupLogic)findGroup(data.groupLogic).logic=el.value;
      else if(data.sortTable!==undefined)notice=chooseTable(state.sorts[Number(data.sortTable)],el.value);
      else if(data.sortColumn!==undefined)chooseColumn(state.sorts[Number(data.sortColumn)],el.value);
      else if(data.sortDirection!==undefined)state.sorts[Number(data.sortDirection)].direction=el.value;
      else if(el.id==='qb-distinct')state.distinct=el.checked;
      else if(el.id==='qb-limit')state.limit=Number(el.value);
      else if(el.id==='qb-map-filter'){state.mapFilter=el.value;filterMappings();changed=false;}
      else changed=false;
      if(changed){syncKeys();engine.pruneConnections(state);dirty(notice);render();}
    });
    root.addEventListener('submit',event=>{if(event.target.id==='qb-chat-form'){event.preventDefault();applyMessage(state.draft);}});
    root.addEventListener('click',async event=>{
      const button=event.target.closest('[data-qaction]');if(!button||button.disabled)return;
      const {qaction:action,id,index,section}=button.dataset;
      if(action==='refresh-schema'){try{const previous=schema;options.sources=(await api.refresh(state.database)).sources;schema=sourceSchema(options.sources,state.database);const current=id=>Object.keys(schema).find(key=>schema[key].name===previous[id]?.name)||'';state.table=current(state.table);state.joins.forEach(join=>join.table=current(join.table));state.joins=state.joins.filter(join=>join.table);cleanReferences();syncKeys();state.notice='Schema refreshed. Review tables and mappings before testing.';dirty(state.notice);render();}catch(error){api.error(error);}return;}
      if(action==='section'){state.section=state.section===section?'':section;render();return;}
      if(action==='toggle-keys'||action==='review-keys'){state.keyEditor=action==='review-keys'||!state.keyEditor;render();if(action==='review-keys')root.querySelector('#qb-key-settings').scrollIntoView({block:'nearest',behavior:'smooth'});return;}
      if(action==='test-query'){runTest();return;}
      if(action==='review-query'){review();return;}
      if(action==='toggle-result'){state.sourceRows=!state.sourceRows;render();return;}
      if(action==='reset-chat'){dialog(`<form><h2 id='qb-dialog-title'>Reset this conversation?</h2><p>Clear the messages. Your current query choices will stay in place. Use Start over above to reset the whole setup.</p><div class='lab-dialog-actions'><button type='button' class='btn btn-falcon-default' data-close>Cancel</button><button class='btn btn-primary' type='submit'>Reset chat</button></div></form>`,()=>{state.messages=[];state.draft='';api.clearChat();render();});return;}
      if(action.startsWith('chat-')){applyMessage({'chat-active':'Only active records','chat-address':'Add billing address','chat-explain':'Explain this query'}[action]);return;}
      if(action==='add-join'){addJoin();state.section='source';}
      else if(action==='remove-join'){
        const removed=new Set([id]);let size;
        do{size=removed.size;state.joins.forEach(join=>{if(join.on.some(pair=>removed.has(pair.left.split('.')[0])))removed.add(join.id);});}while(size!==removed.size);
        state.joins=state.joins.filter(join=>!removed.has(join.id));cleanReferences();dirty('Removed the connection and '+(removed.size-1)+' dependent connection(s). Review any mappings or filters that used them.');render();return;
      }
      else if(action==='add-pair'){const join=state.joins.find(join=>join.id===id);join.auto=false;join.on.push({left:'',right:''});}
      else if(action==='remove-pair'){const join=state.joins.find(join=>join.id===id);join.auto=false;join.on.splice(Number(index),1);}
      else if(action==='custom-keys'){state.keyMode='custom';state.keyFields=state.keys.map(column=>({column,tableAlias:column.split('.')[0]}));}
      else if(action==='auto-keys'){state.keyMode='auto';state.keyFields=[];}
      else if(action==='add-key')state.keyFields.push({column:'',tableAlias:''});
      else if(action==='remove-key')state.keyFields.splice(Number(index),1);
      else if(action==='suggest-map')remapAvailable();
      else if(action==='add-filter')findGroup(id).children.push(filterRule());
      else if(action==='add-group')findGroup(id).children.push({id:uid('group'),logic:'any',children:[filterRule()]});
      else if(action==='remove-rule')removeRule(id);
      else if(action==='clear-filters'){state.filters={id:'root',logic:'all',children:[]};}
      else if(action==='add-sort')state.sorts.push({column:'',tableAlias:'',direction:'asc'});
      else if(action==='remove-sort')state.sorts.splice(Number(index),1);
      syncKeys();engine.pruneConnections(state);dirty();render();
    });
    render();return state;
  }
  window.RecordSetupDatabase={mount};
})();
