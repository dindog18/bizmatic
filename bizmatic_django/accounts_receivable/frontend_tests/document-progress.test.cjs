const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const directory=path.join(__dirname,'../static/accounting/setup');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function storage(){
  const values=new Map();
  return {values,getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
}
function node(){return {innerHTML:'',textContent:'',hidden:true,disabled:false,handlers:{},
  contains:()=>false,querySelectorAll:()=>[],querySelector:()=>null,focus(){},
  addEventListener(name,handler){this.handlers[name]=handler;}};}
async function page(savedStorage,mode='ar',record=null,target='purchase_order'){
  const root=node(),editor=node(),nodes=new Map(),calls=[];
  for(const id of ['setup-saved-status','setup-progress-status','setup-name','setup-delete-configuration',
    'setup-update-root','setup-error','setup-request-status','setup-migration-report'])nodes.set(id,node());
  const reset=node(),form=node(),cancel=node();
  reset.showModal=()=>{};reset.close=()=>{};
  reset.querySelector=selector=>selector==='form'?form:cancel;
  const review=node(),reviewForm=node(),confirm=node(),save=node();
  review.showModal=()=>{};review.close=()=>{};
  review.querySelector=selector=>selector==='form'?reviewForm:selector==='#setup-confirm-check'?confirm:
    selector==='#setup-confirm-save'?save:cancel;
  nodes.set('setup-review-dialog',review);
  root.querySelector=selector=>selector==='#setup-document-root'?editor:selector==='#setup-reset-dialog'?reset:null;
  editor.querySelector=selector=>selector==='[data-da="lock-text"]'?node():null;
  const config={mode,recordId:record?.id||null,title:mode,party:'Customer',
    configurationCreate:`/${mode}/configuration/new/`,routes:{configuration:`/${mode}/configuration/`}};
  const document={activeElement:null,getElementById:id=>id==='finance-root'?root:id==='finance-config'?
    {textContent:JSON.stringify(config)}:nodes.get(id)};
  const field={key:'po_number',label:'PO number',required:true,type:'CharField'};
  const result={passed:true,issues:[],rows:[{key:'header:po_number',label:'PO number',required:true,
    value:'PO-001',expected:'PO-001',status:'passed'}],record:{po_number:'PO-001'},lines:[],llm_log_no:7,test_token:'signed-test'};
  const window={SetupAssistantChat:{create:()=>({mount(){}})},localStorage:savedStorage,ConfigurationDocumentEngine:require('../static/accounting/setup/annotations.js'),
    BizmaticAccounting:{state:{parties:[]},post:async(action,id,body)=>{
      calls.push({action,id,body});
      if(action==='setup-context')return {record,documents:[],catalog:['purchase_order','payment'].map(key=>({key,label:key,fields:[field],lineFields:[]}))};
      if(action==='setup-generate')return {prompt:'Extract the PO number.'};
      if(action==='setup-test')return result;
      if(action==='setup-review')return {record:body.configuration,confirmation_token:'reviewed'};
      if(action==='setup-save')return {record:{...body.configuration,id:9,revision:2,status:'submitted'}};
      throw new Error(`Unexpected server call: ${action}`);
    }}};
  const context=vm.createContext({window,document,location:{search:`?target=${target}&source=document`},
    history:{replaceState(){}},URLSearchParams,structuredClone,console});
  for(const file of ['document-progress.js','documents.js','workspace.js'])vm.runInContext(fs.readFileSync(path.join(directory,file),'utf8'),context);
  await tick();
  const input=(id,value)=>editor.handlers.input({target:{id,value,dataset:{}}});
  const change=(id,value)=>editor.handlers.change({target:{id,value,dataset:{}}});
  const click=(da,extra={})=>editor.handlers.click({target:{closest:()=>({dataset:{da,...extra},disabled:false})}});
  return {root,editor,nodes,calls,input,change,click,form,reviewForm,confirm,
    reset:()=>root.handlers.click({target:{closest:()=>({dataset:{setup:'reset'}})}})};
}

for(const mode of ['ap','ar'])test(`${mode}: refreshing resumes the document wizard after text, annotation, prompt and test`,async()=>{
  const saved=storage();
  let app=await page(saved,mode);
  app.input('da-source-text','PO: PO-001');
  app=await page(saved,mode);
  assert.match(app.editor.innerHTML,/data-step='1'[^>]*aria-current='step'/);
  assert.match(app.editor.innerHTML,/PO: PO-001/);
  await app.click('lock-text');
  app=await page(saved,mode);
  assert.match(app.editor.innerHTML,/data-step='2'[^>]*aria-current='step'/);
  app.editor.handlers.select({target:{id:'da-annotation-text',selectionStart:4,selectionEnd:10}});
  await app.click('annotate');
  app=await page(saved,mode);
  assert.match(app.editor.innerHTML,/Highlighted: <strong>PO-001<\/strong>/);
  await app.click('create-prompt');
  app=await page(saved,mode);
  assert.match(app.editor.innerHTML,/data-step='3'[^>]*aria-current='step'/);
  assert.match(app.editor.innerHTML,/Extract the PO number\./);
  assert.equal(app.calls.length,1,'Restoring progress must not generate a prompt or run a model');
  await app.click('test');await tick();
  app=await page(saved,mode);
  assert.match(app.editor.innerHTML,/Mapping test passed/);
  assert.match(app.editor.innerHTML,/data-da='review' >Review & save/);
  app.input('da-prompt','Extract the order reference.');
  app=await page(saved,mode);
  assert.match(app.editor.innerHTML,/Extract the order reference\./);
  assert.match(app.editor.innerHTML,/data-da='review' disabled/);
  assert.match(app.nodes.get('setup-progress-status').textContent,/Progress saved in this browser/);
  await app.reset();await app.form.handlers.submit({preventDefault(){}});
  app=await page(saved,mode);
  assert.match(app.editor.innerHTML,/data-step='1'[^>]*aria-current='step'/);
  assert.doesNotMatch(app.editor.innerHTML,/PO-001|Extract the order reference/);
});

test('drafts stay separate between AP, AR and record types',async()=>{
  const saved=storage();
  const ar=await page(saved);ar.input('da-source-text','AR PO draft');await ar.click('lock-text');
  const ap=await page(saved,'ap');assert.doesNotMatch(ap.editor.innerHTML,/AR PO draft/);
  const payment=await page(saved,'ar',null,'payment');assert.doesNotMatch(payment.editor.innerHTML,/AR PO draft/);
  const arAgain=await page(saved);assert.match(arAgain.editor.innerHTML,/AR PO draft/);
});

test('browser quota failures leave the wizard usable and show that progress was not saved',async()=>{
  const saved=storage();saved.setItem=()=>{throw new Error('Quota exceeded');};
  const app=await page(saved);app.input('da-source-text','PO: PO-001');await app.click('lock-text');
  assert.match(app.editor.innerHTML,/data-step='2'[^>]*aria-current='step'/);
  assert.match(app.nodes.get('setup-progress-status').textContent,/could not be saved/);
});

test('a changed server revision discards stale browser edits to an existing configuration',async()=>{
  const saved=storage(),record={id:9,revision:1,source_type:'document',target_entity:'purchase_order',name:'Saved PO',encoding_rules:{}};
  const first=await page(saved,'ar',record);first.input('da-source-text','Old revision draft');await first.click('lock-text');
  const same=await page(saved,'ar',record);assert.match(same.editor.innerHTML,/Old revision draft/);
  const updated=await page(saved,'ar',{...record,revision:2});assert.doesNotMatch(updated.editor.innerHTML,/Old revision draft/);
  const fresh=await page(saved);assert.doesNotMatch(fresh.editor.innerHTML,/Old revision draft/);
});

test('confirming and saving clears the new-configuration progress without deleting other drafts',async()=>{
  const saved=storage(),ap=await page(saved,'ap');ap.input('da-source-text','Separate AP draft');
  const app=await page(saved);app.input('da-source-text','PO: PO-001');await app.click('lock-text');
  app.editor.handlers.select({target:{id:'da-annotation-text',selectionStart:4,selectionEnd:10}});
  await app.click('annotate');await app.click('create-prompt');await app.click('test');await tick();
  const pendingReview=app.click('review');await tick();app.confirm.checked=true;
  await app.reviewForm.handlers.submit({preventDefault(){}});await pendingReview;
  assert.match(app.editor.innerHTML,/Configuration saved and activated/);
  const empty=await page(saved);assert.doesNotMatch(empty.editor.innerHTML,/PO-001/);
  const separate=await page(saved,'ap');assert.match(separate.editor.innerHTML,/Separate AP draft/);
});

for(const mode of ['ap','ar'])test(`${mode}: profile edits after activation survive refresh and require another test`,async()=>{
  const party=mode==='ap'?'supplier':'customer';
  const cases=[
    ['input','setup-name','Updated PO setup',profile=>profile.name],
    ['input','setup-description','Use the buyer reference',profile=>profile.description],
    ['input','setup-currency','usd',profile=>profile.encoding_rules.default_currency,'USD'],
    ['change','setup-party','42',profile=>profile[party],42],
    ['change','setup-date','DD/MM/YYYY',profile=>profile.encoding_rules.date_format],
    ['change','setup-lookup',party+'_name',profile=>profile.relation_lookups[party].match_field],
  ];
  for(const [event,id,value,read,expected=value] of cases){
    const saved=storage(),app=await page(saved,mode);
    app.input('da-source-text','PO: PO-001');await app.click('lock-text');
    app.editor.handlers.select({target:{id:'da-annotation-text',selectionStart:4,selectionEnd:10}});
    await app.click('annotate');await app.click('create-prompt');await app.click('test');await tick();
    const pendingReview=app.click('review');await tick();app.confirm.checked=true;
    await app.reviewForm.handlers.submit({preventDefault(){}});await pendingReview;
    assert.match(app.editor.innerHTML,/Configuration saved and activated/);
    const record=structuredClone({...app.calls.find(call=>call.action==='setup-save').body.configuration,id:9,revision:2,status:'submitted'});
    const serverSnapshot=JSON.stringify(record);
    app.root.handlers[event]({target:{id,value,dataset:{}}});
    const cached=[...saved.values.values()].map(raw=>JSON.parse(raw)).find(item=>item.profile.id===9);
    assert.ok(cached,`${id}: edits to the activated configuration must be cached`);
    assert.equal(read(cached.profile),expected,id);
    assert.equal(cached.hasUnsaved,true,id);
    assert.equal(cached.receipt,null,`${id}: profile edits invalidate the test receipt`);
    const restored=await page(saved,mode,record);
    assert.equal(restored.nodes.get('setup-saved-status').textContent,'Unsaved changes',id);
    assert.match(restored.editor.innerHTML,/data-step='3'[^>]*aria-current='step'/,id);
    assert.match(restored.editor.innerHTML,/data-da='review' disabled/,id);
    assert.doesNotMatch(restored.editor.innerHTML,/Configuration saved and activated/,id);
    const roundTrip=[...saved.values.values()].map(raw=>JSON.parse(raw)).find(item=>item.profile.id===9);
    assert.equal(read(roundTrip.profile),expected,`${id}: refresh retains the edited value`);
    assert.equal(JSON.stringify(record),serverSnapshot,`${id}: autosave must not change the server record`);
  }
});

function draftStore(saved,time){
  const window={};vm.runInNewContext(fs.readFileSync(path.join(directory,'document-progress.js'),'utf8'),{window});
  return window.DocumentSetupProgress.create(saved,()=>time.value);
}
const scope={mode:'ar',target:'purchase_order',id:null,revision:1};
function draft(){return {profile:{source_type:'document',target_entity:'purchase_order',revision:1},messages:[],
  editor:{step:3,rules:{},text:'PO: PO-001',prompt:'Extract.',result:{passed:true}},testToken:'signed',testedAt:100};}

test('refreshing and saving progress never extends a mapping test receipt',()=>{
  const saved=storage(),time={value:100},store=draftStore(saved,time),session=draft();
  store.save(scope,session);time.value+=29*60*1000;
  const restored=store.load(scope);assert.equal(restored.testToken,'signed');store.save(scope,restored);
  time.value+=2*60*1000;
  const expired=store.load(scope);assert.equal(expired.testToken,null);assert.equal(expired.editor.stale,true);
});

test('expired and malformed browser drafts are discarded',()=>{
  const saved=storage(),time={value:100},store=draftStore(saved,time);store.save(scope,draft());
  time.value+=8*24*60*60*1000;assert.equal(store.load(scope),null);
  store.save(scope,draft());const key=[...saved.values.keys()][0];saved.setItem(key,'{incomplete');
  assert.equal(store.load(scope),null);assert.equal(saved.values.size,0);
  saved.setItem(key,'null');assert.equal(store.load(scope),null);
});
