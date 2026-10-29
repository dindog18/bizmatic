const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

test('assistant rule updates can be tested directly and results with issues can be reviewed',async()=>{
  const handlers={};
  const root={innerHTML:'',contains:()=>false,querySelector:()=>null,
    addEventListener:(name,handler)=>{handlers[name]=handler;}};
  let receipt=false,tests=0;
  const rules={'header:customer':{method:'instruction',instruction:'Use the buyer code'}};
  const api={changed:()=>{receipt=false;},hasReceipt:()=>receipt,error:error=>{throw error;},
    chat:async()=>({changed:true,message:'Corrected the buyer rule.',record:{setup_data:{document:{
      rules:{'header:customer':{method:'instruction',instruction:'Map the buyer name to the account code'}},
      prompt:'Extract the buyer.',instructions:''}}}}),
    testDocument:async(state)=>{tests++;assert.match(state.rules['header:customer'].instruction,/account code/);receipt=true;
      return {passed:false,rows:[],issues:['Customer needs review'],record:{},lines:[]};}};
  const window={ConfigurationDocumentEngine:{}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/accounting/setup/documents.js'),'utf8'),
    {window,document:{activeElement:null},structuredClone});
  window.RecordSetupDocuments.mount(root,{api,documents:[],destination:{fields:[{key:'customer',label:'Customer',required:true}],lineFields:[]},
    state:{step:3,locked:true,text:'Buyer: Demo',prompt:'Extract the buyer.',rules,question:'Fix the buyer rule'}});
  // A chat correction must not disable the mapping test or demand regeneration.
  handlers.submit({target:{id:'da-help-form'},preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(root.innerHTML,/data-da='test' >Run mapping test|Run mapping test<\/button>/);
  assert.doesNotMatch(root.innerHTML,/data-da='test' disabled/);
  assert.doesNotMatch(root.innerHTML,/Rebuild the prompt before testing/);
  handlers.click({target:{closest:()=>({dataset:{da:'test'},disabled:false})}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(tests,1);
  assert.match(root.innerHTML,/data-da='review' >Review &amp; save|data-da='review' >Review & save/);
  assert.doesNotMatch(root.innerHTML,/data-da='review' disabled/);
});

for (const previousTest of ['missing', 'recheck failed', 'recheck passed']) {
  test(`exception mapping can be rerun beside its warning when the previous test is ${previousTest}`, async()=>{
    const handlers={},errors=[];
    const root={innerHTML:'',contains:()=>false,querySelector:()=>null,
      addEventListener:(name,handler)=>{handlers[name]=handler;}};
    let receipt=true,rechecks=0,tests=0,finishTest;
    const result={passed:true,issues:[],rows:[{key:'header:customer',label:'Customer',value:'BUYER',
      expected:'Buyer',required:true,status:'passed'}],record:{customer:'BUYER'},lines:[]};
    const api={changed:()=>{receipt=false;},hasReceipt:()=>receipt,error:error=>errors.push(error),
      acceptRecheck:token=>{assert.equal(token,'rechecked');receipt=true;},
      recheckDocument:async()=>{
        rechecks++;
        if(previousTest==='recheck failed')throw new Error('Run a new mapping test before applying exceptions.');
        return {...result,test_token:'rechecked'};
      },
      testDocument:async(state,text,expected)=>{
        tests++;
        assert.equal(state.rules['header:customer'].comparison,'format');
        assert.equal(state.prompt,'Extract the buyer.');
        assert.equal(text,'Buyer: Buyer');
        assert.equal(expected['header:customer'],'Buyer');
        await new Promise(resolve=>{finishTest=resolve;});
        receipt=true;
        return {...result,test_token:'new-test',llm_log_no:8};
      }};
    const window={ConfigurationDocumentEngine:{}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/accounting/setup/documents.js'),'utf8'),
      {window,document:{activeElement:null},structuredClone});
    window.RecordSetupDocuments.mount(root,{api,documents:[],
      destination:{fields:[{key:'customer',label:'Customer',required:true}],lineFields:[]},
      state:{step:3,locked:true,text:'Buyer: Buyer',prompt:'Extract the buyer.',
        rules:{'header:customer':{method:'instruction',instruction:'Use the buyer code',example:'Buyer'}},
        result:{...result,...(previousTest==='missing'?{}:{llm_log_no:7})}}});
    await handlers.change({target:{dataset:{comparison:'header:customer'},checked:true}});
    assert.equal(rechecks,previousTest==='missing'?0:1);
    assert.equal(tests,0,'Selecting an exception must not start a new model call');
    if(previousTest==='recheck passed'){
      assert.doesNotMatch(root.innerHTML,/Rerun mapping for exception/);
      assert.match(root.innerHTML,/data-da='review' >Review &amp; save|data-da='review' >Review & save/);
      return;
    }
    assert.equal(errors.length,previousTest==='recheck failed'?1:0);
    assert.match(root.innerHTML,/Rerun mapping for exception[\s\S]*?data-da='test' >Rerun mapping test/);
    assert.match(root.innerHTML,/data-da='review' disabled/);
    handlers.click({target:{closest:()=>({dataset:{da:'test'},disabled:false})}});
    assert.equal(tests,1);
    assert.equal(receipt,false);
    assert.match(root.innerHTML,/data-da='review' disabled/);
    finishTest();
    await new Promise(resolve=>setImmediate(resolve));
    assert.doesNotMatch(root.innerHTML,/Rerun mapping for exception/);
    assert.match(root.innerHTML,/data-da='review' >Review &amp; save|data-da='review' >Review & save/);
    assert.match(root.innerHTML,/Mapping test passed/);
    assert.equal(receipt,true);
  });
}
