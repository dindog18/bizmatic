const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

for(const mode of ['ap','ar']) for(const resource of ['purchase-orders','invoices','delivery-receipts','payments']) {
  test(`${mode} ${resource}: deletion requires confirmation and redirects after success`, async () => {
    const base = mode === 'ar' ? '/accounts-receivable/' : '/accounts-payable/';
    const record = {id:1,partyId:1,reference:'DEMO',revision:'current',date:'2026-10-29',currency:'PHP',
      status:'pending',invoiceStatus:'draft',amount:0,settled:0,balance:0,lines:[],source:'',notes:''};
    const state={today:'2026-10-29',parties:[{id:1,name:'Example'}],invoices:[],payments:[],
      'purchase-orders':[],'delivery-receipts':[],reconciliation:[],allocations:[]};
    state[resource]=[record];
    const config={mode,resource,recordId:1,screen:'detail',title:'Accounting',party:mode==='ar'?'Customer':'Supplier',
      routes:Object.fromEntries(['parties','overview','purchase-orders','invoices','payments','delivery-receipts','llm-logs','configuration'].map(key=>[key,base+key+'/'])),
      sources:{documents:'/documents/',databases:'/databases/'}};
    let click, confirmed=false;
    const calls=[];
    const errorBox={hidden:true,focus(){},scrollIntoView(){}};
    const root={innerHTML:'',insertAdjacentHTML(_,html){this.innerHTML+=html;},querySelector(){return {addEventListener(_,handler){click=handler;}};}};
    const location={search:'',href:'http://localhost'+base};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/accounting/workspace.js'),'utf8'),{
      window:{confirm:()=>confirmed,BizmaticAccounting:{state,post:async(...args)=>{calls.push(args);return {deleted:true};}}},
      document:{getElementById:id=>id==='finance-config'?{textContent:JSON.stringify(config)}:id==='form-error'?errorBox:root},
      location,URLSearchParams,
    });
    assert.match(root.innerHTML,/Delete record/);
    await click();
    assert.equal(calls.length,0);
    confirmed=true;
    await click();
    assert.equal(calls[0][0],'record-delete');
    assert.equal(calls[0][1],1);
    assert.equal(calls[0][2].resource,resource);
    assert.equal(calls[0][2].revision,'current');
    assert.equal(calls[0][2].confirmed,true);
    assert.equal(location.href,base+resource+'/');
  });
}
