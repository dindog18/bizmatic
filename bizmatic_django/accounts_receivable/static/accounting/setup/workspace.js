/* Production Record First workspace. Source editors own UI state; the server owns validation and saving. */
(() => {
  'use strict';
  const config=JSON.parse(document.getElementById('finance-config').textContent);
  const root=document.getElementById('finance-root');
  const transport=window.BizmaticAccounting;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy=value=>JSON.parse(JSON.stringify(value));
  const sessions=new Map();
  let context,active,target,source;
  const parameters=new URLSearchParams(location.search);
  const mandatory={date_format:'YYYY-MM-DD',decimal_separator:'.',thousands_separator:',',default_currency:'PHP',duplicate_policy:'review',missing_value_policy:'review'};
  const currentCatalog=()=>context.catalog.find(item=>item.key===target);
  const key=()=>target+':'+source;
  function fresh(){return {profile:{name:currentCatalog().label+' '+(source==='database'?'database':'document')+' setup',description:'',target_entity:target,source_type:source,revision:1,[config.mode==='ap'?'supplier':'customer']:null,encoding_rules:{...mandatory}},editor:null,messages:[],testToken:null,hasUnsaved:true};}
  function legacyDatabase(record){
    const definition=currentCatalog(),lineAlias=record.line_source_table?'lines':'base';
    const mappings=[...definition.fields.map(field=>({...field,group:'header'})),...definition.lineFields.map(field=>({...field,group:'line'}))].map(field=>{
      const old=(field.group==='line'?record.line_item_mappings:record.field_mappings)?.[field.key];
      return {id:field.group+':'+field.key,include:!!old||field.required,method:old?.source?'column':old&&Object.hasOwn(old,'default')?'value':'empty',column:old?.source?(field.group==='line'?lineAlias:'base')+'.'+old.source:'',value:old?.default??'',transform:old?.transform||'identity'};
    });
    const keys=(record.source_key_fields||[]).map(key=>'base.'+key);
    return {database:String(record.database_source||''),table:String(record.source_table||''),mappings,keys,keyMode:keys.length?'custom':'auto',keyFields:keys.map(column=>({column,tableAlias:'base'})),filters:{id:'root',logic:'all',children:[]},sorts:[],distinct:false,joins:record.line_source_table?[{id:'lines',table:String(record.line_source_table),type:'left',auto:false,on:(record.line_join_fields||[]).map(pair=>({left:'base.'+pair.header_column,right:pair.line_column}))}]:[]};
  }
  function payload(){
    const profile={...active.profile,target_entity:target,source_type:source,encoding_rules:{...mandatory,...active.profile.encoding_rules}};
    const editor=active.editor;
    if(source==='document'){
      const document={};
      for(const name of ['text','prompt','rules','instructions','line_context'])document[name]=editor?.[name]??(name==='rules'?{}:'');
      if(!editor?.locked)document.text=editor?.draft||document.text;
      profile.setup_data={version:1,document};
      profile.sample_text=document.text;profile.extraction_context=document.prompt;profile.document_type=profile.document_type||currentCatalog().label;
      profile.field_mappings={};profile.line_item_mappings={};profile.source_key_fields=[];profile.line_join_fields=[];
      profile.database_source=null;profile.source_table=null;profile.line_source_table=null;
    }else{
      const database={};
      for(const name of ['database','table','keys','keyMode','keyFields','joins','mappings','filters','sorts','distinct'])database[name]=editor?.[name];
      database.mappings=(database.mappings||[]).map(item=>Object.fromEntries(['id','include','method','column','value','tableAlias','transform'].filter(name=>item[name]!==undefined).map(name=>[name,item[name]])));
      profile.setup_data={version:1,database};profile.database_source=database.database||null;
    }
    return {configuration:copy(profile)};
  }
  function changed(){active.testToken=null;active.hasUnsaved=true;const savedStatus=document.getElementById('setup-saved-status');if(savedStatus&&active.profile.id)savedStatus.textContent='Unsaved changes';root.querySelectorAll('[data-da="review"],[data-qaction="review-query"],[data-setup="import"]').forEach(button=>button.disabled=true);if(active.editor?.result){active.editor.stale=true;const queryStatus=root.querySelector('#qb-results .finance-status');if(queryStatus){queryStatus.textContent='Changed · test again';queryStatus.className='finance-status info';}const documentStatus=root.querySelector('.da-result-table')?.closest('.finance-card-body')?.querySelector('[role="status"] strong');if(documentStatus)documentStatus.textContent='Changed · test again';}const warning=document.getElementById('setup-import-warning');if(warning)warning.hidden=false;}
  function showError(error){
    const box=document.getElementById('setup-error');box.hidden=false;box.innerHTML=esc(error.message||'The action failed. Please retry.')+(error.llmLogNo?` <a href='${config.routes['llm-logs']+error.llmLogNo+'/'}'>View attempt #${error.llmLogNo}</a>`:'');box.focus();
  }
  async function post(action,extra={},id=active?.profile.id){
    const status=document.getElementById('setup-request-status');
    if(status){status.textContent=({'setup-generate':'Generating the extraction prompt…','setup-test':'Testing the current mappings…','setup-chat':'Asking the configuration assistant…','setup-context':'Loading schema and document choices…'})[action]||'Checking the configuration…';status.hidden=false;}
    try{const result=await transport.post(action,id||null,extra);document.getElementById('setup-error').hidden=true;return result;}finally{if(status)status.hidden=true;}
  }
  function updateAddress(){
    const path=active.profile.id?config.routes.configuration+active.profile.id+'/':config.configurationCreate;
    history.replaceState(null,'',path+'?target='+encodeURIComponent(target)+'&source='+source);
  }
  function reflectSaved(){
    const status=document.getElementById('setup-saved-status');status.textContent=active.hasUnsaved&&active.profile.id?'Unsaved changes':active.profile.status==='submitted'?'Saved & active':active.profile.id?'Saved draft':'Unsaved configuration';
    const name=document.getElementById('setup-name');if(name)name.value=active.profile.name;
    updateAddress();renderImport();
  }
  function renderImport(){
    const host=document.getElementById('setup-import-root');
    if(!host)return;
    host.innerHTML=source==='database'&&active.profile.id&&active.profile.status==='submitted'?`<section class='card setup-profile mt-3'><h2 class='fs-9'>Import saved database records</h2><p class='lab-note mb-0'>Uses the activated configuration. Review the preview before creating accounting records.</p><p class='finance-callout warning' id='setup-import-warning' ${active.hasUnsaved?'':'hidden'}>Save and activate your changes before importing this configuration.</p><div class='finance-form-grid'><div><label for='setup-import-limit'>Maximum records</label><input id='setup-import-limit' type='number' class='form-control' min='1' max='100' value='50'></div><div><label for='setup-import-offset'>Start after</label><input id='setup-import-offset' type='number' class='form-control' min='0' value='0'></div></div><div><button type='button' class='btn btn-primary' data-setup='import' ${active.hasUnsaved?'disabled':''}>Review database import</button></div>${active.importResult?`<pre class='setup-review-json' role='status'>${esc(JSON.stringify(active.importResult,null,2))}</pre>`:''}</section>`:'';
  }
  async function importRecords(){
    if(active.hasUnsaved)return;
    const limit=Number(root.querySelector('#setup-import-limit').value),offset=Number(root.querySelector('#setup-import-offset').value);
    if(!Number.isInteger(limit)||limit<1||limit>100||!Number.isInteger(offset)||offset<0){showError(new Error('Choose 1–100 records and a nonnegative starting offset.'));return;}
    const dialog=document.getElementById('setup-review-dialog');dialog.innerHTML=`<form><h2 id='setup-review-title'>Import these database records?</h2><p>Use <strong>${esc(active.profile.name)}</strong> to import up to ${limit} records, starting after ${offset}. Existing records follow the saved duplicate policy. Review the results for any records needing attention.</p><div class='lab-dialog-actions'><button type='button' class='btn btn-falcon-default' data-cancel>Keep reviewing</button><button type='submit' class='btn btn-primary'>Confirm import</button></div></form>`;dialog.showModal();dialog.querySelector('[data-cancel]').addEventListener('click',()=>dialog.close());dialog.querySelector('form').addEventListener('submit',async event=>{event.preventDefault();try{active.importRequest ||= crypto.randomUUID();const result=await post('import',{revision:active.profile.revision,request_id:active.importRequest,limit,offset});active.importResult=result;active.importRequest=null;dialog.close();renderImport();}catch(error){dialog.close();showError(error);}});
  }
  async function review(submit){
    const body={...payload(),submit,test_token:active.testToken};
    const reviewed=await post('setup-review',body);
    const dialog=document.getElementById('setup-review-dialog');
    dialog.innerHTML=`<form><h2 id='setup-review-title'>Is this configuration correct?</h2><p>Review ${esc(currentCatalog().label.toLowerCase())} · ${source==='document'?'Document extraction':'Database extraction'}.</p><dl class='lab-summary'><div><dt>Configuration</dt><dd>${esc(reviewed.record.name)}</dd></div><div><dt>Workspace</dt><dd>${esc(config.title)}</dd></div><div><dt>Save as</dt><dd>${submit?'Active configuration · test passed':'Draft · extraction stays inactive'}</dd></div></dl><details class='lab-details'><summary>Review field rules and instructions</summary><pre class='setup-review-json'>${esc(JSON.stringify(reviewed.record.setup_data,null,2))}</pre></details><p class='finance-callout mt-3'>Saving stores this configuration. ${submit?'The reviewed rules will be available to extraction and imports.':'A passing test and another confirmation are required before activation.'} No accounting records are created here.</p><label class='da-confirm'><input type='checkbox' id='setup-confirm-check' required>I checked the configuration, mappings, and test results.</label><div class='lab-dialog-actions'><button type='button' class='btn btn-falcon-default' data-cancel>Keep editing</button><button type='submit' class='btn btn-primary' id='setup-confirm-save' disabled>Confirm & save${submit?'':' draft'}</button></div></form>`;
    dialog.showModal();
    return await new Promise(resolve=>{
      dialog.querySelector('[data-cancel]').addEventListener('click',()=>{dialog.close();resolve(false);});
      dialog.addEventListener('cancel',()=>resolve(false),{once:true});
      dialog.querySelector('#setup-confirm-check').addEventListener('change',event=>{dialog.querySelector('#setup-confirm-save').disabled=!event.target.checked;});
      dialog.querySelector('form').addEventListener('submit',async event=>{
        event.preventDefault();if(!dialog.querySelector('#setup-confirm-check').checked)return;
        try{const result=await post('setup-save',{...payload(),submit,test_token:active.testToken,confirmation_token:reviewed.confirmation_token,confirmed:true,messages:active.messages});active.profile=result.record;active.testToken=null;active.hasUnsaved=false;active.importRequest=null;dialog.close();reflectSaved();resolve(true);}catch(error){showError(error);dialog.close();resolve(false);}
      });
    });
  }
  function editorApi(){return {
    error:showError,changed,clearChat:()=>{active.messages=[];},hasReceipt:()=>!!active.testToken,review,
    document:id=>post('setup-document',{document_id:id},null),
    generate:()=>post('setup-generate',payload()),
    testDocument:async (editor,text,expected)=>{const result=await post('setup-test',{...payload(),text,expected});active.testToken=result.test_token;return result;},
    testDatabase:async (editor,limit)=>{const result=await post('setup-test',{...payload(),limit});active.testToken=result.test_token;return result;},
    refresh:async id=>{const result=await post('setup-context',{inspect_source:id});context.sources=result.sources;changed();return result;},
    chat:async message=>{const result=await post('setup-chat',{...payload(),message,messages:active.messages});active.messages=result.messages;Object.assign(active.profile,result.record);reflectSaved();if(result.changed)changed();return result;},
  };}
  function render(){
    const definition=currentCatalog();
    root.innerHTML=`<div class='lab'><header class='finance-heading lab-heading'><div><span class='finance-eyebrow'>RECORD FIRST · EXTRACTION SETUP</span><h1 class='mt-2'>Set up ${esc(definition.label.toLowerCase())}</h1><p>${source==='document'?'Choose sample text. Highlight values. Generate and test the extraction prompt.':'Choose your database. Map the record. Refine and test the query.'}</p></div><span class='finance-status info' id='setup-saved-status'></span></header><div id='setup-error' class='finance-callout warning' role='alert' tabindex='-1' hidden></div><div class='finance-callout' id='setup-request-status' role='status' hidden></div><section class='card lab-scope' aria-label='Configuration selection'><div><label for='setup-workspace'>Workspace</label><select id='setup-workspace' class='form-select'><option value='ap'${config.mode==='ap'?' selected':''}>Accounts payable</option><option value='ar'${config.mode==='ar'?' selected':''}>Accounts receivable</option></select></div><div><label for='setup-record'>Record type</label><select id='setup-record' class='form-select'>${context.catalog.map(item=>`<option value='${item.key}'${item.key===target?' selected':''}>${esc(item.label)}</option>`).join('')}</select></div><fieldset><legend>Extraction source</legend><div class='lab-source-toggle'>${[['database','Database'],['document','Documents']].map(([value,label])=>`<label class='lab-source-choice${source===value?' active':''}'><input type='radio' name='setup-source' value='${value}'${source===value?' checked':''}>${label}</label>`).join('')}</div></fieldset><button type='button' class='btn btn-link lab-reset' data-setup='reset'>Start over</button></section><section class='card setup-profile'><div><label for='setup-name'>Configuration name</label><input id='setup-name' class='form-control' value='${esc(active.profile.name)}' maxlength='160' required></div><details><summary>Scope & formatting</summary><div class='finance-form-grid mt-3'><div><label for='setup-party'>Applies to</label><select id='setup-party' class='form-select'><option value=''>All ${config.party.toLowerCase()}s</option>${transport.state.parties.map(party=>`<option value='${party.id}'${String(active.profile[config.mode==='ap'?'supplier':'customer']||'')===String(party.id)?' selected':''}>${esc(party.reference+' · '+party.name)}</option>`).join('')}</select></div>${definition.fields.some(field=>field.type==='lookup')?`<div><label for='setup-lookup'>Match ${config.party.toLowerCase()} by</label><select id='setup-lookup' class='form-select'>${[[config.mode==='ap'?'supplier_code':'customer_code','Account code'],[config.mode==='ap'?'supplier_name':'customer_name','Account name'],['tax_identification_no','Tax ID']].map(([value,label])=>`<option value='${value}'${(active.profile.relation_lookups?.[config.mode==='ap'?'supplier':'customer']?.match_field||(config.mode==='ap'?'supplier_code':'customer_code'))===value?' selected':''}>${label}</option>`).join('')}</select></div>`:''}<div><label for='setup-date'>Source date format</label><select id='setup-date' class='form-select'>${['YYYY-MM-DD','DD/MM/YYYY','MM/DD/YYYY'].map(value=>`<option${active.profile.encoding_rules?.date_format===value?' selected':''}>${value}</option>`).join('')}</select></div><div><label for='setup-currency'>Default currency</label><input id='setup-currency' class='form-control' maxlength='3' value='${esc(active.profile.encoding_rules?.default_currency||'PHP')}'></div><div><label for='setup-duplicates'>Already imported records</label><select id='setup-duplicates' class='form-select'><option value='review'>Hold for review</option><option value='skip'${active.profile.encoding_rules?.duplicate_policy==='skip'?' selected':''}>Skip</option></select></div><div class='finance-span-full'><label for='setup-description'>Business instructions</label><textarea id='setup-description' class='form-control' rows='2'>${esc(active.profile.description)}</textarea></div></div></details><div class='setup-profile-actions'><button type='button' class='btn btn-falcon-default btn-sm' data-setup='draft'>Review & save draft</button><a href='${config.routes.configuration}'>All configurations</a></div></section><div id='setup-${source}-root'></div><div id='setup-import-root'></div><dialog id='setup-review-dialog' class='finance-dialog lab-dialog' aria-labelledby='setup-review-title'></dialog><dialog id='setup-reset-dialog' class='finance-dialog lab-dialog' aria-labelledby='setup-reset-title'></dialog></div>`;
    reflectSaved();
    const api=editorApi();
    if(source==='document')active.editor=window.RecordSetupDocuments.mount(root.querySelector('#setup-document-root'),{destination:definition,state:active.editor,documents:context.documents,api});
    else active.editor=window.RecordSetupDatabase.mount(root.querySelector('#setup-database-root'),{destination:definition,mode:config.mode,target,state:active.editor,sources:context.sources,api});
  }
  function select(nextTarget,nextSource){
    sessions.set(key(),active);target=nextTarget;source=nextSource;active=sessions.get(key())||fresh();render();
  }
  root.addEventListener('change',event=>{
    const el=event.target;
    if(el.id==='setup-workspace'){
      const nextTarget=['supplier','customer'].includes(target)?el.value==='ap'?'supplier':'customer':target;
      location.href='/accounts-'+(el.value==='ap'?'payable':'receivable')+'/configuration/new/?target='+nextTarget+'&source='+source;
    }else if(el.id==='setup-record')select(el.value,source);
    else if(el.name==='setup-source')select(target,el.value);
    else if(el.id==='setup-party'){active.profile[config.mode==='ap'?'supplier':'customer']=el.value?Number(el.value):null;changed();}
    else if(el.id==='setup-lookup'){active.profile.relation_lookups={[config.mode==='ap'?'supplier':'customer']:{match_field:el.value,on_missing:'review'}};changed();}
    else if(el.id==='setup-date'){active.profile.encoding_rules.date_format=el.value;changed();}
    else if(el.id==='setup-duplicates'){active.profile.encoding_rules.duplicate_policy=el.value;changed();}
  });
  root.addEventListener('input',event=>{
    const el=event.target;
    if(el.id==='setup-import-limit'||el.id==='setup-import-offset')active.importRequest=null;
    if(el.id==='setup-name'){active.profile.name=el.value;changed();}
    else if(el.id==='setup-description'){active.profile.description=el.value;changed();}
    else if(el.id==='setup-currency'){active.profile.encoding_rules.default_currency=el.value.toUpperCase();changed();}
  });
  root.addEventListener('click',async event=>{
    const button=event.target.closest('[data-setup]');if(!button)return;
    if(button.dataset.setup==='import'){await importRecords();}
    else if(button.dataset.setup==='draft'){try{if(await review(false))render();}catch(error){showError(error);}}
    else if(button.dataset.setup==='reset'){
      const dialog=root.querySelector('#setup-reset-dialog');dialog.innerHTML=`<form><h2 id='setup-reset-title'>Reset this setup?</h2><p>Clear this conversation and its annotations, prompt, or query. The workspace, record type, and extraction source stay selected. ${active.profile.id?'The saved configuration returns to draft; earlier submissions remain in its audit history.':''}</p><div class='lab-dialog-actions'><button type='button' class='btn btn-falcon-default' data-cancel>Keep editing</button><button type='submit' class='btn btn-danger'>Reset setup</button></div></form>`;dialog.showModal();dialog.querySelector('[data-cancel]').addEventListener('click',()=>dialog.close());dialog.querySelector('form').addEventListener('submit',async event=>{event.preventDefault();try{let profile;if(active.profile.id){profile=(await post('configuration-reset-context',{selection:{target_entity:target,source_type:source},revision:active.profile.revision,confirmed:true})).record;}active=fresh();if(profile)active.profile=profile;sessions.set(key(),active);render();}catch(error){dialog.close();showError(error);}});
    }
  });
  async function start(){
    try{context=await transport.post('setup-context',config.recordId,{});const record=context.record;
      target=record?.target_entity||parameters.get('target')||parameters.get('record')||(config.mode==='ap'?'supplier':'customer');
      if(!context.catalog.some(item=>item.key===target))target=context.catalog[0].key;
      source=record?.source_type||(['document','database'].includes(parameters.get('source'))?parameters.get('source'):'document');
      active=fresh();if(record){active.profile=record;active.hasUnsaved=false;active.messages=record.assistant_messages||[];active.editor=record.setup_data?.[source]||null;if(!active.editor&&source==='database')active.editor=legacyDatabase(record);if(!record.setup_data?.version)active.hasUnsaved=true;if(!active.editor&&source==='document'&&record.sample_text)active.editor={text:record.sample_text,prompt:record.extraction_context,rules:{}};}
      sessions.set(key(),active);render();
    }catch(error){root.innerHTML=`<div class='finance-callout warning' role='alert'>${esc(error.message)}</div>`;}
  }
  start();
})();
