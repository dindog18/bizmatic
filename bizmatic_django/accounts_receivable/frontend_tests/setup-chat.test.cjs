const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function panel(){
  const handlers={},input={focus(){},setSelectionRange(){}},log={scrollHeight:12};
  return {handlers,isConnected:true,innerHTML:'',querySelector:selector=>selector==='textarea'?input:log,
    addEventListener:(name,handler)=>handlers[name]=handler};
}
function create(api){
  const window={};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/accounting/setup/chat.js'),'utf8'),{window,document:{activeElement:null}});
  return window.SetupAssistantChat.create(api);
}
const click=(root,action)=>root.handlers.click({target:{closest:()=>({dataset:{chat:action}})}});
const submit=root=>root.handlers.submit({target:{matches:()=>true},preventDefault(){}});
test('saved chat escapes messages, survives remount and clears without touching setup inputs',async()=>{
  let clears=0,sends=0;
  const chat=create({label:'AP · Suppliers · Documents',
    load:async()=>({messages:[{role:'assistant',content:'<img src=x onerror=alert(1)>'}],chat_revision:3}),
    send:async(message,revision)=>{sends++;assert.equal(message,'hello');assert.equal(revision,3);
      return {messages:[{role:'user',content:'hello'},{role:'assistant',content:'Hello!'}],chat_revision:4};},
    clear:async revision=>{clears++;assert.equal(revision,4);return {messages:[],chat_revision:5};}});
  const first=panel();chat.mount(first);await tick();
  assert.match(first.innerHTML,/&lt;img src=x/);assert.doesNotMatch(first.innerHTML,/<img/);
  first.handlers.input({target:{id:'setup-chat-message',value:'hello'}});
  const second=panel();first.isConnected=false;chat.mount(second);
  assert.match(second.innerHTML,/>hello<\/textarea>/);
  submit(second);submit(second);await tick();assert.equal(sends,1);
  assert.match(second.innerHTML,/Hello!/);
  click(second,'clear');assert.equal(clears,0);assert.match(second.innerHTML,/Your setup inputs will be kept/);
  click(second,'confirm-clear');await tick();assert.equal(clears,1);
  assert.doesNotMatch(second.innerHTML,/Hello!/);
});
test('an in-flight reply updates the remounted panel and failures retain the typed message',async()=>{
  let finish;
  const chat=create({label:'AR · Customers · Database',load:async()=>({messages:[],chat_revision:0}),
    send:()=>new Promise(resolve=>{finish=resolve;}),clear:async()=>{throw Error('unused');}});
  const first=panel();chat.mount(first);await tick();
  first.handlers.input({target:{id:'setup-chat-message',value:'hello'}});submit(first);
  const second=panel();first.isConnected=false;chat.mount(second);
  finish({messages:[{role:'user',content:'hello'},{role:'assistant',content:'Welcome'}],chat_revision:1});await tick();
  assert.match(second.innerHTML,/Welcome/);assert.doesNotMatch(second.innerHTML,/Thinking…/);
  const failed=create({label:'AP',load:async()=>({messages:[],chat_revision:0}),send:async()=>{throw Error('Try again');}});
  const root=panel();failed.mount(root);await tick();root.handlers.input({target:{id:'setup-chat-message',value:'Keep my question'}});submit(root);await tick();
  assert.match(root.innerHTML,/Try again/);assert.match(root.innerHTML,/Keep my question/);
});
