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
