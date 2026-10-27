/* Table-first, ordered query preparation. PostgreSQL executes all data steps. */
(() => {
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy=value=>JSON.parse(JSON.stringify(value));
  const selected=(a,b)=>String(a)===String(b)?' selected':'';
  const types=[['text','ABC','Text'],['integer','123','Whole number'],['decimal','1.2','Decimal number'],['date','◷','Date'],['datetime','◷','Date and time'],['boolean','T/F','True / false'],['json','{}','JSON']];
  const operations=[['merge','Merge tables','link'],['json_expand','Expand JSON','expand-arrows-alt'],['select','Choose columns','columns'],['rename','Rename column','pen'],['type','Change type','font'],['filter','Filter rows','filter'],['sort','Sort rows','sort-amount-down'],['trim','Trim text','align-left'],['uppercase','Uppercase','text-height'],['replace','Replace values','exchange-alt'],['deduplicate','Remove duplicates','copy']];
  const operators=[['eq','equals'],['ne','does not equal'],['contains','contains'],['starts','starts with'],['gt','greater than'],['gte','at least'],['lt','less than'],['lte','at most'],['empty','is empty'],['not_empty','is not empty'],['in','is one of (comma separated)']];
  const button=(label,action,extra='',style='btn-falcon-default')=>`<button type='button' class='btn ${style} btn-sm' data-pq='${action}' ${extra}>${label}</button>`;
  function mount(root,options) {
    const {api,destination}=options;
    let sources=options.sources;
    const fields=[...destination.fields.map(f=>({...f,id:'header:'+f.key})),...destination.lineFields.map(f=>({...f,id:'line:'+f.key,label:'Line · '+f.label}))];
    const sourceFor=id=>sources.find(source=>String(source.id)===String(id));
    let state=options.state||{database:sources[0]?.id||'',table:'',mappings:[],keys:[]};
    const schema=()=>Object.fromEntries((sourceFor(state.database)?.tables||[]).map(table=>[String(table.id),table]));
    const pk=table=>(schema()[table]?.columns||[]).filter(col=>col.key==='Primary key').map(col=>'base.'+col.name);
    const freshMappings=()=>fields.map(f=>({id:f.id,include:f.required,method:'empty',column:'',value:'',transform:'identity'}));
    const baseColumns=()=> (schema()[state.table]?.columns||[]).map(c=>({id:'base.'+c.name,label:c.name,type:c.type==='number'?(/int/.test(c.formatted_type)?'integer':'decimal'):/json/.test(c.formatted_type)?'json':c.type==='date'?'date':c.type==='boolean'?'boolean':'text',lineage:[]}));
    let serial=1,version=0,busy=false,dialogDraft=null,editIndex=null,pendingSource=null;
    const uid=()=>{let id;do{id='s'+serial++;}while(state.pipeline.steps.some(step=>step.id===id));return id;};
    if(!state.pipeline){
      const old=copy(state),steps=[];
      state.pipeline={version:1,sourceKeys:old.keyMode==='custom'?old.keys||[]:pk(state.table),steps};
      const append=(type,values)=>{const step={id:uid(),type,name:operations.find(item=>item[0]===type)?.[1]||type,...values};steps.push(step);return step;};
      for(const join of old.joins||[])steps.push({id:join.id,type:'merge',name:'Merge '+(schema()[join.table]?.name||'related table'),table:String(join.table),join:join.type,on:copy(join.on),asText:false});
      const active=(old.mappings||[]).filter(m=>m.include&&m.method==='json'&&m.id.startsWith('line:'));
      if(old.lineItems&&active.length){
        const step=append('json_expand',{column:old.lineItems.column,path:old.lineItems.path||'',mode:'array',fields:active.map((m,i)=>({name:m.id.split(':')[1]||('item_'+i),path:m.path||''}))});
        active.forEach((m,i)=>{const original=state.mappings.find(item=>item.id===m.id);original.method='column';original.column=step.id+'.'+step.fields[i].name;delete original.path;});
      }
      for(const mapping of state.mappings||[]){
        if(!mapping.include&&mapping.method==='json'){mapping.method='empty';mapping.column='';}
        if(mapping.method==='json'){
          const step=append('json_expand',{column:mapping.column,path:'',mode:'record',fields:[{name:mapping.id.split(':')[1],path:mapping.path||''}]});
          mapping.method='column';mapping.column=step.id+'.'+step.fields[0].name;delete mapping.path;
        }
        if(mapping.id==='line:line_no'&&['sequence','number'].includes(mapping.method))mapping.method='number';
        if(mapping.include&&['trim','uppercase'].includes(mapping.transform))append(mapping.transform,{column:mapping.column});
        mapping.transform='identity';
      }
      if(old.filters?.children?.length)append('filter',{rules:copy(old.filters)});
      if(old.sorts?.length)append('sort',{sorts:copy(old.sorts)});
      if(old.distinct)append('deduplicate',{columns:[]});
      state.converted=!!options.state;
      state.joins=[];state.filters={logic:'all',children:[]};state.sorts=[];state.distinct=false;delete state.lineItems;
      if(state.converted)state.notice='Your saved mappings are preserved. The table connections, JSON fields and filters are now Applied steps. Review the prepared data before saving.';
    }
    state.mappings=fields.map(field=>({id:field.id,include:field.required,method:'empty',column:'',value:'',transform:'identity',...(state.mappings||[]).find(m=>m.id===field.id)}));
    state.view||='transform';state.selectedStep=state.pipeline.steps.length;state.selectedColumn||='';state.preview=null;state.result=null;state.offset=0;state.pageSize=50;state.tableSearch||='';state.mapSearch||='';state.previewError='';
    function columnsAt(count=state.pipeline.steps.length){
      let columns=baseColumns();
      for(const step of state.pipeline.steps.slice(0,count)){
        if(step.type==='merge'){
          const related=schema()[step.table];
          columns.push(...(related?.columns||[]).filter(c=>!step.columns||step.columns.includes(c.name)).map(c=>({id:step.id+'.'+c.name,label:(related?.name.split('.').pop()||'Related')+'.'+c.name,type:/json/.test(c.formatted_type)?'json':c.type==='number'?'decimal':c.type,lineage:[step.id]})));
        }else if(step.type==='json_expand')columns.push(...(step.fields||[]).map(f=>({id:step.id+'.'+f.name,label:f.name,type:'text',lineage:[step.id]})));
        else if(step.type==='select')columns=(step.columns||[]).map(id=>columns.find(c=>c.id===id)).filter(Boolean);
        else if(step.type==='rename')columns=columns.map(c=>c.id===step.column?{...c,label:step.label}:c);
        else if(['type','trim','uppercase','replace'].includes(step.type))columns=columns.map(c=>c.id===step.column?{...c,type:step.type==='type'?step.dataType:'text'}:c);
      }
      return columns;
    }
    const colOptions=(value,columns=columnsAt())=>`<option value=''>Choose a column</option>`+columns.map(c=>`<option value='${esc(c.id)}'${selected(c.id,value)}>${esc(c.label)}</option>`).join('');
    const tableOptions=value=>`<option value=''>Choose a table</option>`+Object.values(schema()).map(t=>`<option value='${esc(t.id)}'${selected(t.id,value)}>${esc(t.name)}</option>`).join('');
    function changed(message=''){
      version++;state.preview=null;state.result=null;state.previewError='';state.offset=0;state.notice=message;api.changed();
      root.querySelectorAll('[data-pq="review"]').forEach(button=>button.disabled=true);
    }
    function missing(){const columns=columnsAt();return fields.filter(field=>{const m=state.mappings.find(m=>m.id===field.id);return m.include&&m.method==='column'&&!columns.some(c=>c.id===m.column)||field.required&&(!m.include||m.method==='empty'||m.method==='value'&&m.value==='');});}
    const display=value=>value==null?'null':typeof value==='object'?JSON.stringify(value):String(value);
    const sample=column=>state.preview?.step===state.pipeline.steps.length?state.preview.rows.find(row=>row[column]!=null)?.[column]:undefined;
    function stepSummary(step){
      const column=columnsAt().find(c=>c.id===step.column)?.label||step.column||'';
      if(step.type==='merge')return (schema()[step.table]?.name||'Choose table')+' · '+(step.join==='inner'?'matching rows':'all main rows');
      if(step.type==='json_expand')return column+' → '+(step.fields?.length||0)+' fields · '+(step.mode==='array'?'item rows':'record');
      if(step.type==='filter')return (step.rules?.children?.length||0)+' conditions';
      if(step.type==='select')return (step.columns?.length||0)+' columns kept';
      if(step.type==='sort')return (step.sorts||[]).map(s=>(columnsAt().find(c=>c.id===s.column)?.label||s.column)+' '+s.direction).join(', ');
      if(step.type==='type')return column+' → '+(types.find(t=>t[0]===step.dataType)?.[2]||'Choose type');
      if(step.type==='rename')return column+' → '+step.label;
      if(step.type==='deduplicate')return 'Compare '+(step.columns?.length||'all')+' columns within each source record';
      return column;
    }
    function navigator(){return `<aside class='pq-navigator' aria-label='Source navigator'><h3><span class='fas fa-database' aria-hidden='true'></span> Source tables <small>${Object.keys(schema()).length}</small></h3><label class='visually-hidden' for='pq-table-search'>Find a source table</label><input id='pq-table-search' class='form-control' placeholder='Find a table…' value='${esc(state.tableSearch)}'><div class='pq-tables'>${Object.values(schema()).map(table=>`<button type='button' data-pq-table='${esc(table.id)}' class='pq-table-choice${String(table.id)===String(state.table)?' active':''}' aria-pressed='${String(table.id)===String(state.table)}' ${!table.name.toLowerCase().includes(state.tableSearch.toLowerCase())?'hidden':''}><span class='fas fa-table' aria-hidden='true'></span><span>${esc(table.name)}</span></button>`).join('')||'<p class="lab-note p-3">Refresh the schema to discover tables.</p>'}</div></aside>`;}
    function stepsPanel(){return `<aside class='pq-steps' aria-label='Query settings'><h3>Query settings</h3><p class='lab-note'>${esc(destination.label)} · ${state.pipeline.steps.length} transformation(s)</p><h4>APPLIED STEPS</h4><ol><li class='${state.selectedStep===0?'active':''}'><button type='button' data-pq-step='0'><span class='fas fa-database' aria-hidden='true'></span><span>Source<small>${esc(schema()[state.table]?.name||'Choose a table')}</small></span></button></li>${state.pipeline.steps.map((step,i)=>`<li class='${state.selectedStep===i+1?'active':''}'><button type='button' data-pq-step='${i+1}' aria-current='${state.selectedStep===i+1?'step':'false'}'><span class='pq-step-no'>${i+1}</span><span>${esc(step.name)}<small>${esc(stepSummary(step))}</small></span></button><button type='button' class='pq-step-edit' data-pq-edit='${i}' aria-label='Edit ${esc(step.name)}'><span class='fas fa-cog' aria-hidden='true'></span></button></li>`).join('')}</ol><p class='lab-note mt-3'>Select a step to preview its result. Steps run from top to bottom. New transformations are added at the end.</p>${state.selectedStep?`<div class='pq-step-actions'>${button('Edit','edit')}${button('↑','up',`aria-label='Move selected step earlier' ${state.selectedStep===1?'disabled':''}`)}${button('↓','down',`aria-label='Move selected step later' ${state.selectedStep===state.pipeline.steps.length?'disabled':''}`)}${button('Remove','remove','','btn-outline-danger')}</div>`:''}<details class='lab-details'><summary>Source identity</summary><p class='lab-note'>Original identifiers are retained through every step, including type changes and column removal.</p><label for='pq-source-keys'>Identifier columns</label><select multiple id='pq-source-keys' class='form-select' size='5'>${baseColumns().map(c=>`<option value='${esc(c.id)}'${state.pipeline.sourceKeys.includes(c.id)?' selected':''}>${esc(c.label)}</option>`).join('')}</select><p class='lab-note'>Use Ctrl / ⌘ to select a composite identifier. Primary keys are suggested.</p></details></aside>`;}
    function grid(){
      const columns=state.preview?.columns||columnsAt(state.selectedStep),rows=state.preview?.rows||[];
      const head=columns.map(c=>`<th scope='col' class='${state.selectedColumn===c.id?'selected':''}'><button type='button' data-pq-column='${esc(c.id)}' aria-haspopup='menu' aria-expanded='false' title='Select ${esc(c.label)}'><span class='pq-type-badge'>${esc(types.find(t=>t[0]===c.type)?.[1]||'ABC')}</span>${esc(c.label)}<span class='fas fa-caret-down' aria-hidden='true'></span></button></th>`).join('');
      return `<div class='pq-formula'><span class='pq-fx' aria-hidden='true'>ƒx</span><span>${state.selectedStep?esc(stepSummary(state.pipeline.steps[state.selectedStep-1])):esc(schema()[state.table]?.name||'Select a source table to begin')}</span><span class='pq-readonly'><span class='fas fa-lock' aria-hidden='true'></span> Read only</span></div>${state.previewError?`<div class='pq-error' role='alert'><strong>Preview needs attention</strong><p>${esc(state.previewError)}</p><small>Select an earlier step to inspect where the data changes.</small></div>`:''}<div class='pq-grid-scroll' tabindex='0' role='region' aria-label='Prepared data preview; scroll for more columns'><table class='pq-grid'><thead><tr><th scope='col' class='pq-row-index'>#</th>${head}</tr></thead><tbody>${rows.map((row,i)=>`<tr><th scope='row' class='pq-row-index'>${state.offset+i+1}</th>${columns.map(c=>{const value=row[c.id];return `<td class='${value==null?'pq-null':typeof value==='object'?'pq-structured':''}' title='${esc(display(value).slice(0,1200))}'><span>${esc(display(value).slice(0,240))}</span></td>`;}).join('')}</tr>`).join('')||`<tr><td colspan='${columns.length+1}' class='pq-empty'><span class='fas fa-table' aria-hidden='true'></span><strong>${busy?'Loading preview…':state.preview?'No rows at this step':'Your data preview'}</strong><p>${state.preview?'Change filters or go to an earlier step.':'Choose a table, then refresh the preview. Add transformations before matching accounting fields.'}</p></td></tr>`}</tbody></table></div><footer class='pq-grid-footer'><span>${columns.length} columns · ${rows.length} preview rows ${state.preview?.has_more?'· more available':''}</span><div><label class='pq-page-size'>Rows / page<select id='pq-page-size' class='form-select' ${busy?'disabled':''}>${[25,50,100].map(n=>`<option${selected(n,state.pageSize)}>${n}</option>`).join('')}</select></label>${button('Previous','prev',state.offset===0||busy?'disabled':'')}${button('Next','next',!state.preview?.has_more||busy?'disabled':'')}</div></footer><p class='pq-grid-note'>Preview is a page of source rows, not the entire dataset. Filters, sorts, merges and JSON expansion run at the source database.</p>`;
    }
    function transform(){return `<div class='pq-ribbon' role='toolbar' aria-label='Data transformations'>${operations.map(([type,label,icon])=>button(`<span class='fas fa-${icon}' aria-hidden='true'></span>${label}`,'add',`data-kind='${type}' ${!state.table||busy?'disabled':''}`)).join('')}</div><div class='pq-editor-layout'>${navigator()}<section class='pq-data' aria-label='Data preparation'><div class='pq-data-heading'><div><strong>${esc(schema()[state.table]?.name||'Choose your source')}</strong><small>${state.selectedStep===state.pipeline.steps.length?'Final prepared data':'Preview through '+(state.selectedStep?esc(state.pipeline.steps[state.selectedStep-1].name):'Source')}</small></div>${button(`<span class='fas fa-sync-alt' aria-hidden='true'></span> Refresh preview`,'preview',!state.table||busy?'disabled':'','btn-primary')}</div>${grid()}</section>${stepsPanel()}</div><div class='pq-bottom'><p class='lab-note'>Prepare the rows and columns first. Match the final columns to ${esc(destination.label.toLowerCase())} fields when the result looks correct.</p>${button('Continue to field matching <span class="fas fa-arrow-right" aria-hidden="true"></span>','mapping',!state.table?'disabled':'','btn-primary')}</div>`;}
    function mapping(){
      const columns=columnsAt(),bad=missing();
      return `<section class='pq-matching'><div class='pq-match-heading'><div><h3>Match fields to ${esc(destination.label.toLowerCase())}</h3><p class='lab-note'>Use columns from the last Applied step. Header values must remain consistent within one source identifier. Every line field is optional.</p></div><div class='pq-inline-actions'>${button('Refresh examples','preview',busy?'disabled':'')}${button('Suggest field matches','suggest')}</div></div><label for='pq-map-search' class='visually-hidden'>Find an accounting field</label><input id='pq-map-search' class='form-control mb-3' placeholder='Find an accounting field…' value='${esc(state.mapSearch)}'><div class='pq-match-scroll'><table class='table finance-table pq-match-table'><thead><tr><th>Accounting field</th><th>Prepared column or value</th><th>Preview example</th></tr></thead><tbody>${fields.map(field=>{const m=state.mappings.find(m=>m.id===field.id);const current=!m.include?'@empty':m.method==='column'?m.column:m.method==='number'?'@number':m.method==='value'?'@value':'@empty';return `<tr data-pq-map-row='${esc(field.id)}' ${!field.label.toLowerCase().includes(state.mapSearch.toLowerCase())?'hidden':''}><th scope='row'><label for='pq-match-${esc(field.id)}'>${esc(field.label)} ${field.required?'<small class="pq-required">Required</small>':'<small class="pq-optional">Optional</small>'}</label></th><td><select id='pq-match-${esc(field.id)}' class='form-select${bad.includes(field)?' is-invalid':''}' data-pq-map='${esc(field.id)}' aria-label='Match ${esc(field.label)}'><option value='@empty'${selected(current,'@empty')}>${field.required?'Choose a prepared column':'Not supplied'}</option>${columns.map(c=>`<option value='${esc(c.id)}'${selected(current,c.id)}>${esc(c.label)}</option>`).join('')}${m.method==='column'&&!columns.some(c=>c.id===m.column)?`<option value='${esc(m.column)}' selected>Unavailable: ${esc(m.column)}</option>`:''}<option value='@value'${selected(current,'@value')}>Use a constant value</option>${field.key==='line_no'?`<option value='@number'${selected(current,'@number')}>Generate line number automatically</option>`:''}</select>${m.method==='value'?`<input class='form-control mt-2' aria-label='Constant for ${esc(field.label)}' data-pq-value='${esc(field.id)}' value='${esc(m.value)}'>`:''}${field.key==='line_no'?'<small class="lab-note">Omit this field to generate numbers for actual items.</small>':''}</td><td class='pq-example'>${esc(m.method==='column'?(sample(m.column)===undefined?'Refresh examples':display(sample(m.column)).slice(0,100)):m.method==='value'?m.value:m.method==='number'?'1, 2, 3…':'—')}</td></tr>`;}).join('')}</tbody></table></div><div class='pq-bottom'>${button('← Back to data preparation','transform')}<div><span class='lab-note'>${bad.length?bad.length+' field(s) need a match':'Field matches ready for validation'}</span> ${button('Validate mapped records','validate',bad.length||busy?'disabled':'','btn-primary')}</div></div><div id='qb-results' class='pq-validation'>${state.result?`<h3>Mapped record validation</h3><p>${state.result.count} source record(s) checked${state.result.has_more?' · more available':''}.</p>${state.result.issues.length?`<div class='finance-callout warning'><strong>Resolve these details</strong><ul>${state.result.issues.map(issue=>`<li>${esc(issue)}</li>`).join('')}</ul></div>`:'<div class="finance-callout">The sample passed accounting validation. Review every record before migrating and saving.</div>'}<div class='pq-match-scroll'><table class='table finance-table'><thead><tr>${state.result.headers.map(h=>`<th>${esc(h.label)}</th>`).join('')}</tr></thead><tbody>${state.result.rows.slice(0,50).map(row=>`<tr>${state.result.headers.map(h=>`<td>${esc(display(row[h.id]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'<p class="lab-note">Validation checks the selected accounting fields and account matches. It does not save records.</p>'}${button('Review full migration','review',!api.hasMigrationReceipt()||busy?'disabled':'','btn-primary')}</div></section>`;
    }
    function render(){
      root.innerHTML=`<section class='card pq-builder' aria-label='Database query builder' aria-busy='${busy}'><header class='pq-header'><div><span class='pq-eyebrow'>GET & TRANSFORM DATA</span><h2>Database query builder</h2></div><div class='pq-connection'><label for='pq-database'>Database connection</label><select id='pq-database' class='form-select' ${busy?'disabled':''}>${sources.map(s=>`<option value='${esc(s.id)}'${selected(s.id,state.database)}>${esc(s.name)}</option>`).join('')}</select>${button('Refresh schema','schema',busy?'disabled':'')}</div></header><nav class='pq-tabs' aria-label='Query preparation stages'><button type='button' data-pq='transform' aria-current='${state.view==='transform'?'step':'false'}' class='${state.view==='transform'?'active':''}'><span>1</span> Transform data</button><button type='button' data-pq='mapping' aria-current='${state.view==='mapping'?'step':'false'}' class='${state.view==='mapping'?'active':''}' ${!state.table?'disabled':''}><span>2</span> Match accounting fields <small>Final step</small></button></nav>${state.notice?`<div class='pq-notice' role='status'>${esc(state.notice)}</div>`:''}${state.view==='mapping'?mapping():transform()}<dialog class='finance-dialog lab-dialog pq-dialog' aria-labelledby='pq-dialog-title'></dialog></section>`;
    }
    async function refresh(offset=0){
      if(busy||!state.table)return;
      const revision=version,step=state.selectedStep;busy=true;state.previewError='';render();
      try{const result=await api.previewDatabase({step,offset,limit:state.pageSize});if(revision!==version||step!==state.selectedStep)return;state.preview=result;state.offset=offset;}
      catch(error){if(revision===version)state.previewError=error.message;}
      finally{busy=false;render();}
    }
    function filterEditor(group,path=''){
      return `<div class='pq-filter-group'><label>Match <select class='form-select' data-filter-logic='${path}'>${[['all','all conditions (AND)'],['any','any condition (OR)']].map(([v,l])=>`<option value='${v}'${selected(v,group.logic)}>${l}</option>`).join('')}</select></label>${group.children.map((rule,i)=>{const address=path?path+'.'+i:String(i);return rule.children?`<div>${filterEditor(rule,address)}${button('Remove group','filter-remove',`data-path='${address}'`)}</div>`:`<div class='pq-filter-row'><select aria-label='Filter column' class='form-select' data-filter-column='${address}'>${colOptions(rule.column,dialogColumns())}</select><select aria-label='Filter operation' class='form-select' data-filter-operator='${address}'>${operators.map(([v,l])=>`<option value='${v}'${selected(v,rule.operator)}>${l}</option>`).join('')}</select><input aria-label='Filter value' class='form-control' data-filter-value='${address}' value='${esc(rule.value)}' ${['empty','not_empty'].includes(rule.operator)?'disabled':''}>${button('×','filter-remove',`data-path='${address}' aria-label='Remove filter condition'`)}</div>`;}).join('')}<div class='pq-inline-actions'>${button('+ Condition','filter-add',`data-path='${path}'`)}${button('+ Group','filter-group',`data-path='${path}'`)}</div></div>`;
    }
    const dialogColumns=()=>columnsAt(editIndex==null?state.pipeline.steps.length:editIndex);
    const field=(label,html)=>`<label>${label}${html}</label>`;
    function dialogBody(){
      const step=dialogDraft,columns=dialogColumns(),choose=field('Column',`<select name='column' class='form-select' required>${colOptions(step.column,columns)}</select>`);
      if(step.type==='merge'){
        const related=schema()[step.table];
        return field('Related table',`<select name='table' id='pq-merge-table' class='form-select' required>${tableOptions(step.table)}</select>`)+field('Rows to keep',`<select name='join' class='form-select'><option value='left'${selected('left',step.join)}>Left join · keep all main rows</option><option value='inner'${selected('inner',step.join)}>Inner join · keep matching rows</option></select>`)+`<p class='lab-note'>Match the main data to the related table using PK / FK columns. Multiple related matches produce additional rows.</p>${(step.on||[]).map((pair,i)=>`<div class='pq-merge-pair'><select class='form-select' data-merge-left='${i}' aria-label='Main matching column ${i+1}' required>${colOptions(pair.left,columns)}</select><span>=</span><select class='form-select' data-merge-right='${i}' aria-label='Related matching column ${i+1}' required><option value=''>Related column</option>${(related?.columns||[]).map(c=>`<option value='${esc(c.name)}'${selected(c.name,pair.right)}>${esc(c.name)}${c.key?' · PK':''}</option>`).join('')}</select>${button('×','merge-remove',`data-index='${i}' aria-label='Remove matching pair'`)}</div>`).join('')}${button('+ Matching pair','merge-add')}<label class='pq-check'><input type='checkbox' name='asText' ${step.asText?'checked':''}>Compare matching identifiers as text</label><fieldset><legend>Related columns to expand</legend><div class='pq-checklist'>${(related?.columns||[]).map(c=>`<label><input type='checkbox' name='columns' value='${esc(c.name)}' ${!step.columns||step.columns.includes(c.name)?'checked':''}>${esc(c.name)}</label>`).join('')}</div></fieldset>`;
      }
      if(step.type==='json_expand')return choose+field('Expand as',`<select name='mode' class='form-select'><option value='array'${selected('array',step.mode)}>Array of items → additional rows</option><option value='record'${selected('record',step.mode)}>JSON object → additional columns</option></select>`)+field('Path to collection or object',`<input name='path' class='form-control' value='${esc(step.path||'')}' placeholder='/DATA (leave blank for root JSON)'>`)+field('Output fields · one per line: column name = JSON pointer',`<textarea name='fields' class='form-control' rows='6' required placeholder='Item code = /MODEL&#10;Quantity = /QUANTITY&#10;Unit price = /PRICE'>${esc((step.fields||[]).map(f=>f.name+' = '+f.path).join('\n'))}</textarea>`)+button('Discover fields from preview','discover')+`<p class='lab-note'>Paths are relative to each item. Preview this column before discovering fields. Empty arrays retain the header without creating item rows. Missing item fields become empty values. Expanded values start as text; add Change type for numbers and dates.</p>`;
      if(['select','deduplicate'].includes(step.type))return `<p class='lab-note'>${step.type==='select'?'Keep and order the columns needed in the prepared table. Original record identifiers stay available internally.':'Remove rows with the same selected values within each original source record. Repeated JSON items stay separate unless you add this step.'}</p><div class='pq-inline-actions'>${button('Select all','select-all')}${button('Clear','select-none')}</div><div class='pq-checklist'>${columns.map(c=>`<label><input type='checkbox' name='columns' value='${esc(c.id)}' ${!step.columns?.length||step.columns.includes(c.id)?'checked':''}>${esc(c.label)}</label>`).join('')}</div>`;
      if(step.type==='filter')return filterEditor(step.rules);
      if(step.type==='sort')return `<p class='lab-note'>The first column has the highest priority. Source identity is used to break ties.</p>${step.sorts.map((sort,i)=>`<div class='pq-sort-row'><select class='form-select' data-sort-column='${i}' aria-label='Sort column ${i+1}' required>${colOptions(sort.column,columns)}</select><select class='form-select' data-sort-direction='${i}' aria-label='Sort direction ${i+1}'><option value='asc'${selected(sort.direction,'asc')}>Ascending</option><option value='desc'${selected(sort.direction,'desc')}>Descending</option></select>${button('×','sort-remove',`data-index='${i}' aria-label='Remove sort column'`)}</div>`).join('')}${button('+ Sort column','sort-add')}`;
      if(step.type==='rename')return choose+field('New display name',`<input name='label' class='form-control' value='${esc(step.label||'')}' required maxlength='100'>`);
      if(step.type==='type')return choose+field('Data type',`<select name='dataType' class='form-select'>${types.map(([v,,l])=>`<option value='${v}'${selected(v,step.dataType)}>${l}</option>`).join('')}</select>`)+`<div class='pq-form-grid'>${field('Date format (date conversion)',`<select name='dateFormat' class='form-select'>${['YYYY-MM-DD','DD/MM/YYYY','MM/DD/YYYY'].map(f=>`<option${selected(f,step.dateFormat||'YYYY-MM-DD')}>${f}</option>`).join('')}</select>`)}${field('Decimal separator',`<select name='decimal' class='form-select'><option value='.'${selected(step.decimal||'.','.')}>Dot · 1234.56</option><option value=','${selected(step.decimal,',')}>Comma · 1234,56</option></select>`)}${field('Thousands separator',`<select name='thousands' class='form-select'>${[['','None'],[',','Comma'],['.','Dot'],[' ','Space']].map(([v,l])=>`<option value='${v}'${selected(v,step.thousands||'')}>${l}</option>`).join('')}</select>`)}</div><p class='lab-note'>Blank numeric/date values become null; text conversion preserves spacing. Invalid values stop the preview and migration; they are never silently replaced. Whole numbers must have no fractional part.</p>`;
      if(step.type==='replace')return choose+field('Find text',`<input name='find' class='form-control' value='${esc(step.find||'')}' required>`)+field('Replace with',`<input name='replacement' class='form-control' value='${esc(step.replacement||'')}'>`);
      return choose;
    }
    function renderDialog(){const dialog=root.querySelector('dialog');dialog.innerHTML=`<form id='pq-step-form'><h2 id='pq-dialog-title'>${editIndex==null?'Add':'Edit'} ${esc(operations.find(o=>o[0]===dialogDraft.type)?.[1]||'step')}</h2><div class='pq-dialog-error' role='alert' hidden></div>${field('Step name',`<input name='name' class='form-control' maxlength='100' value='${esc(dialogDraft.name)}' required>`)}${dialogBody()}<div class='lab-dialog-actions'>${button('Cancel','cancel')}<button type='submit' class='btn btn-primary'>${editIndex==null?'Add step':'Save step'}</button></div></form>`;if(!dialog.open)dialog.showModal();}
    function openStep(kind,index=null){
      editIndex=index;
      const column=state.selectedColumn||columnsAt().find(c=>kind!=='json_expand'||c.type==='json')?.id||columnsAt()[0]?.id||'';
      dialogDraft=index==null?{id:uid(),type:kind,name:operations.find(o=>o[0]===kind)[1],column,dataType:'text',mode:'array',path:'',fields:[],on:[{left:column,right:''}],join:'left',asText:false,rules:{logic:'all',children:[{column,operator:'eq',value:''}]},sorts:[{column,direction:'asc'}]}:copy(state.pipeline.steps[index]);
      renderDialog();
    }
    function readDraft(){
      const form=root.querySelector('#pq-step-form');if(!form)return;
      const data=new FormData(form);
      for(const name of ['name','column','table','join','mode','path','label','dataType','decimal','thousands','dateFormat','find','replacement'])if(data.has(name))dialogDraft[name]=data.get(name);
      if(['select','deduplicate','merge'].includes(dialogDraft.type))dialogDraft.columns=data.getAll('columns');
      if(dialogDraft.type==='merge')dialogDraft.asText=data.has('asText');
      if(dialogDraft.type==='json_expand')dialogDraft.fields=String(data.get('fields')||'').split('\n').filter(line=>line.trim()).map(line=>{const at=line.indexOf('=');if(at<0)throw new Error('Enter each JSON field as column name = /path.');return {name:line.slice(0,at).trim(),path:line.slice(at+1).trim()};});
    }
    const filterAt=path=>path===''?dialogDraft.rules:path.split('.').reduce((g,i)=>g.children[Number(i)],dialogDraft.rules);
    function suggestJoin(table){
      const related=schema()[table],columns=dialogColumns(),connected=[{id:'base',table:state.table},...state.pipeline.steps.slice(0,editIndex??state.pipeline.steps.length).filter(s=>s.type==='merge').map(s=>({id:s.id,table:s.table}))];
      for(const source of connected){
        const forward=schema()[source.table]?.references.find(r=>String(r.table)===String(table));
        if(forward&&forward.pairs.every(p=>columns.some(c=>c.id===source.id+'.'+p.column)))return forward.pairs.map(p=>({left:source.id+'.'+p.column,right:p.target}));
        const reverse=related?.references.find(r=>String(r.table)===String(source.table));
        if(reverse&&reverse.pairs.every(p=>columns.some(c=>c.id===source.id+'.'+p.target)))return reverse.pairs.map(p=>({left:source.id+'.'+p.target,right:p.column}));
      }
      return [{left:'',right:''}];
    }
    function discover(){
      readDraft();if(!state.preview||state.preview.step!==(editIndex??state.pipeline.steps.length))throw new Error('Preview the data immediately before this step, then discover its JSON fields.');
      const found=new Set();
      for(const row of state.preview.rows){
        let value=row[dialogDraft.column];try{if(typeof value==='string')value=JSON.parse(value);}catch{continue;}
        for(const part of (dialogDraft.path||'').split('/').slice(1))value=value?.[part.replace(/~1/g,'/').replace(/~0/g,'~')];
        const items=Array.isArray(value)?value:[value];
        for(const item of items.slice(0,20))if(item&&typeof item==='object'&&!Array.isArray(item))Object.keys(item).forEach(key=>found.add(key));
      }
      if(!found.size)throw new Error('No object fields found in this preview. Check the JSON column and collection path (for example /DATA).');
      dialogDraft.fields=[...found].slice(0,100).map((name,i)=>({name:name.length<=24?name:'field_'+(i+1),path:'/'+name.replace(/~/g,'~0').replace(/\//g,'~1')}));renderDialog();
    }
    function sourceChange(database,table){
      state.database=database;state.table=table;state.pipeline={version:1,sourceKeys:pk(table),steps:[]};state.mappings=freshMappings();state.selectedStep=0;state.selectedColumn='';changed();render();
    }
    function requestSource(database,table){
      if(!state.pipeline.steps.length&&!state.mappings.some(m=>m.include&&m.method!=='empty')){sourceChange(database,table);return;}
      pendingSource={database,table};const dialog=root.querySelector('dialog');dialog.innerHTML=`<h2 id='pq-dialog-title'>Change the source?</h2><p>Changing the main table clears this editor’s transformations and field matches. The saved configuration is updated only after migration review and confirmation.</p><div class='lab-dialog-actions'>${button('Keep current source','cancel')}${button('Change source','confirm-source','','btn-primary')}</div>`;dialog.showModal();
    }
    root.addEventListener('submit',event=>{
      if(event.target.id!=='pq-step-form')return;event.preventDefault();
      try{readDraft();if(['select','deduplicate','merge'].includes(dialogDraft.type)&&!dialogDraft.columns.length)throw new Error('Select at least one column.');if(dialogDraft.type==='json_expand'&&!dialogDraft.fields.length)throw new Error('Add at least one JSON field.');
        if(editIndex==null)state.pipeline.steps.push(copy(dialogDraft));else state.pipeline.steps[editIndex]=copy(dialogDraft);
        root.querySelector('dialog').close();state.selectedStep=editIndex==null?state.pipeline.steps.length:editIndex+1;changed('Step saved. Refresh the preview to inspect its result.');render();
      }catch(error){const box=root.querySelector('.pq-dialog-error');box.hidden=false;box.textContent=error.message;}
    });
    root.addEventListener('input',event=>{
      const el=event.target;
      if(el.id==='pq-table-search'){state.tableSearch=el.value;root.querySelectorAll('[data-pq-table]').forEach(button=>button.hidden=!schema()[button.dataset.pqTable].name.toLowerCase().includes(el.value.toLowerCase()));}
      else if(el.id==='pq-map-search'){state.mapSearch=el.value;root.querySelectorAll('[data-pq-map-row]').forEach(row=>row.hidden=!fields.find(f=>f.id===row.dataset.pqMapRow).label.toLowerCase().includes(el.value.toLowerCase()));}
      else if(el.dataset.pqValue){state.mappings.find(m=>m.id===el.dataset.pqValue).value=el.value;changed();root.querySelectorAll('[data-pq="validate"]').forEach(button=>button.disabled=!!missing().length||busy);}
      else if(el.dataset.filterValue!==undefined)filterAt(el.dataset.filterValue).value=el.value;
    });
    root.addEventListener('change',event=>{
      const el=event.target,d=el.dataset;
      if(el.id==='pq-database'){const value=el.value;el.value=state.database;requestSource(value,'');}
      else if(el.id==='pq-page-size'){state.pageSize=Number(el.value);refresh();}
      else if(el.id==='pq-source-keys'){state.pipeline.sourceKeys=[...el.selectedOptions].map(o=>o.value);changed();render();}
      else if(d.pqMap){const m=state.mappings.find(m=>m.id===d.pqMap);m.include=el.value!=='@empty';m.method=el.value==='@empty'?'empty':el.value==='@number'?'number':el.value==='@value'?'value':'column';m.column=m.method==='column'?el.value:'';changed();render();}
      else if(el.id==='pq-merge-table'){readDraft();dialogDraft.table=el.value;dialogDraft.on=suggestJoin(el.value);dialogDraft.columns=null;renderDialog();}
      else if(d.mergeLeft!==undefined)dialogDraft.on[Number(d.mergeLeft)].left=el.value;
      else if(d.mergeRight!==undefined)dialogDraft.on[Number(d.mergeRight)].right=el.value;
      else if(d.sortColumn!==undefined)dialogDraft.sorts[Number(d.sortColumn)].column=el.value;
      else if(d.sortDirection!==undefined)dialogDraft.sorts[Number(d.sortDirection)].direction=el.value;
      else if(d.filterLogic!==undefined)filterAt(d.filterLogic).logic=el.value;
      else if(d.filterColumn!==undefined)filterAt(d.filterColumn).column=el.value;
      else if(d.filterOperator!==undefined){readDraft();filterAt(d.filterOperator).operator=el.value;renderDialog();}
    });
    root.addEventListener('click',async event=>{
      const el=event.target.closest('button');if(!el||el.disabled)return;
      const d=el.dataset;
      try{
        if(d.pqTable){if(d.pqTable!==String(state.table))requestSource(state.database,d.pqTable);return;}
        if(d.pqStep!==undefined){state.selectedStep=Number(d.pqStep);state.preview=null;state.offset=0;render();await refresh();return;}
        if(d.pqEdit!==undefined){openStep(state.pipeline.steps[Number(d.pqEdit)].type,Number(d.pqEdit));return;}
        if(d.pqColumn){
          state.selectedColumn=d.pqColumn;root.querySelectorAll('th.selected').forEach(th=>th.classList.remove('selected'));el.closest('th').classList.add('selected');
          root.querySelector('.pq-column-menu')?.remove();
          const host=root.querySelector('.pq-data'),menu=document.createElement('div');menu.className='pq-column-menu';menu.setAttribute('role','menu');menu.setAttribute('aria-label','Column actions');
          menu.innerHTML=`<div><strong>${esc(columnsAt(state.selectedStep).find(c=>c.id===d.pqColumn)?.label||d.pqColumn)}</strong>${button('×','close-column-menu',"aria-label='Close column actions'")}</div>${[['filter','Filter rows'],['asc','Sort ascending'],['desc','Sort descending'],['type','Change type'],['rename','Rename column'],['json_expand','Expand JSON']].map(([kind,label])=>button(label,'column-action',`data-kind='${kind}' role='menuitem'`)).join('')}`;
          host.append(menu);el.setAttribute('aria-expanded','true');menu.querySelector('[role=menuitem]')?.focus();const anchor=el.getBoundingClientRect(),rect=host.getBoundingClientRect();menu.style.top=(anchor.bottom-rect.top)+'px';menu.style.left=Math.max(0,Math.min(anchor.left-rect.left,rect.width-230))+'px';return;
        }
        const action=d.pq;
        if(action==='close-column-menu')root.querySelector('.pq-column-menu')?.remove();
        else if(action==='column-action'){
          root.querySelector('.pq-column-menu')?.remove();
          if(['asc','desc'].includes(d.kind)){state.pipeline.steps.push({id:uid(),type:'sort',name:'Sort rows',sorts:[{column:state.selectedColumn,direction:d.kind}]});state.selectedStep=state.pipeline.steps.length;changed('Sort added. Refresh the preview to inspect its result.');render();}
          else openStep(d.kind);
        }
        else if(action==='transform'||action==='mapping'){state.view=action;state.selectedStep=state.pipeline.steps.length;if(state.preview?.step!==state.selectedStep)state.preview=null;render();}
        else if(action==='preview')await refresh();
        else if(action==='prev')await refresh(Math.max(0,state.offset-state.pageSize));
        else if(action==='next')await refresh(state.offset+state.pageSize);
        else if(action==='add')openStep(d.kind);
        else if(action==='edit'&&state.selectedStep)openStep(state.pipeline.steps[state.selectedStep-1].type,state.selectedStep-1);
        else if(action==='remove'&&state.selectedStep){state.pipeline.steps.splice(state.selectedStep-1,1);state.selectedStep=Math.min(state.selectedStep,state.pipeline.steps.length);changed('Step removed. Later steps and field matches may need adjustment.');render();}
        else if(['up','down'].includes(action)&&state.selectedStep){const i=state.selectedStep-1,j=i+(action==='up'?-1:1);[state.pipeline.steps[i],state.pipeline.steps[j]]=[state.pipeline.steps[j],state.pipeline.steps[i]];state.selectedStep=j+1;changed('Step order changed. Refresh the preview to check dependent columns.');render();}
        else if(action==='cancel'){root.querySelector('dialog').close();pendingSource=null;}
        else if(action==='confirm-source'&&pendingSource){sourceChange(pendingSource.database,pendingSource.table);pendingSource=null;}
        else if(action==='select-all'||action==='select-none')root.querySelectorAll("dialog input[name='columns']").forEach(input=>input.checked=action==='select-all');
        else if(action==='merge-add'){readDraft();dialogDraft.on.push({left:'',right:''});renderDialog();}
        else if(action==='merge-remove'){readDraft();dialogDraft.on.splice(Number(d.index),1);renderDialog();}
        else if(action==='sort-add'){readDraft();dialogDraft.sorts.push({column:'',direction:'asc'});renderDialog();}
        else if(action==='sort-remove'){readDraft();dialogDraft.sorts.splice(Number(d.index),1);renderDialog();}
        else if(action==='filter-add'||action==='filter-group'){readDraft();filterAt(d.path).children.push(action==='filter-add'?{column:'',operator:'eq',value:''}:{logic:'all',children:[{column:'',operator:'eq',value:''}]});renderDialog();}
        else if(action==='filter-remove'){readDraft();const parts=d.path.split('.'),i=Number(parts.pop());filterAt(parts.join('.')).children.splice(i,1);renderDialog();}
        else if(action==='discover')discover();
        else if(action==='suggest'){
          const aliases={supplier:['supplier_code','supplier_company_name'],customer:['customer_code','customer_company_name'],po_reference_no:['purchase_order_no','po_number'],order_date:['order_date','creation_date'],item_code:['MODEL','item_code'],quantity_ordered:['QUANTITY'],unit_price:['PRICE'],line_total:['TOTAL_PRICE']};
          for(const field of fields){const m=state.mappings.find(m=>m.id===field.id);if(m.include&&m.method!=='empty')continue;const names=[field.key,...(aliases[field.key]||[])].map(s=>s.toLowerCase());const matches=columnsAt().filter(c=>names.includes(c.id.split('.').pop().toLowerCase())||names.includes(c.label.toLowerCase()));if(matches.length===1){m.method='column';m.column=matches[0].id;m.include=true;}}
          changed('Unambiguous name matches were suggested. Review account identity and every required field before validating.');render();
        }else if(action==='validate'){
          busy=true;render();try{state.result=await api.testDatabase(state,5);state.notice='Sample validation complete. Full migration review checks every matching record.';}finally{busy=false;render();}
        }else if(action==='review'){await api.review(true);render();}
        else if(action==='schema'){
          const previous=schema();busy=true;render();
          try{
            const result=await api.refresh(state.database);sources=result.sources;
            const latest=new Map(Object.values(schema()).map(table=>[table.name,String(table.id)]));
            state.table=latest.get(previous[state.table]?.name)||'';
            for(const step of state.pipeline.steps)if(step.type==='merge')step.table=latest.get(previous[step.table]?.name)||'';
            changed('Schema refreshed. Tables now use the latest snapshot; preview each step to check for changed or removed columns.');
          }finally{busy=false;render();}
        }
      }catch(error){if(root.querySelector('dialog')?.open&&root.querySelector('.pq-dialog-error')){const box=root.querySelector('.pq-dialog-error');box.hidden=false;box.textContent=error.message;}else api.error(error);}
    });
    root.addEventListener('keydown',event=>{
      const menu=root.querySelector('.pq-column-menu');if(!menu)return;
      if(event.key==='Escape'){
        menu.remove();for(const button of root.querySelectorAll('[data-pq-column]'))if(button.dataset.pqColumn===state.selectedColumn){button.setAttribute('aria-expanded','false');button.focus();}
      }else if(['ArrowDown','ArrowUp'].includes(event.key)&&menu.contains(event.target)){
        event.preventDefault();const items=[...menu.querySelectorAll('[role=menuitem]')],i=items.indexOf(document.activeElement);items[(i+(event.key==='ArrowDown'?1:items.length-1))%items.length]?.focus();
      }
    });
    render();
    return state;
  }
  window.RecordSetupDatabase={mount};
})();
