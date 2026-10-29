const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function client(response) {
  const controls = [{disabled:false}];
  const window = {};
  const config = {api:'/accounts-receivable/api/action/',csrfToken:'test'};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/accounting/api.js'),'utf8'), {
    window, Error, fetch:async()=>response,
    document:{getElementById:id=>({textContent:JSON.stringify(id==='finance-config'?config:{})}),querySelectorAll:()=>controls},
  });
  return {api:window.BizmaticAccounting,controls};
}

for(const [status,expected] of [[504,/HTTP 504.*timed out/],[502,/HTTP 502.*application server/],[503,/HTTP 503.*application server/],[403,/HTTP 403.*rejected/],[500,/HTTP 500.*non-JSON/],[200,/HTTP 200.*non-JSON/]]) {
  test(`HTML response ${status} gives a useful error and releases controls`,async()=>{
    const {api,controls} = client({status,ok:status===200,json:async()=>{throw new SyntaxError("Unexpected token '<'");}});
    await assert.rejects(api.post('setup-generate',null,{}),expected);
    assert.equal(controls[0].disabled,false);
    await assert.rejects(api.post('setup-generate',null,{}),expected); // The request lock is released too.
  });
}
test('JSON validation errors retain the saved LLM attempt link',async()=>{
  const {api} = client({status:400,ok:false,json:async()=>({message:'Review needed',llm_log_no:3})});
  await assert.rejects(api.post('setup-generate',null,{}),error=>error.message==='Review needed'&&error.llmLogNo===3);
});
test('successful JSON responses pass through unchanged',async()=>{
  const result={record:{id:3}};
  const {api}=client({status:200,ok:true,json:async()=>result});
  assert.equal(await api.post('setup-generate',null,{}),result);
});
