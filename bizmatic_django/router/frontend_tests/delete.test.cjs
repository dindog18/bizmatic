const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
function setup(screen) {
  const destination={id:1,name:'Synthetic destination',module_name:'encoder',target_model:'EncoderJob',description:'Synthetic',is_active:true,revision:'revision-1'};
  const rule={id:2,name:'Synthetic rule',destination_id:1,instructions:'Synthetic match',examples:'',document_type:'',is_active:true,revision:'revision-2'};
  const ui={config:{screen,recordId:screen==='rule_edit'?2:1,destinationCatalog:[{value:'encoder',label:'Encoder',targets:[{value:'EncoderJob',label:'Encoder job'}]}]},state:{destinations:[destination],rules:[rule]},renderers:{},filters:{},esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),url:(name,id)=>`/${name}/${id??''}`,moduleLabel:v=>v,badge:v=>v,heading:(a,b,c='')=>a+b+c,card:(a,b)=>a+b,toolbar:()=>'',table:(_,rows)=>rows.join(''),empty:()=>'',matches:()=>true,page:rows=>({rows,footer:''}),destination:()=>destination,openDialog:(title,html)=>{ui.dialog={title,html}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/router/configuration.js'),'utf8'),{window:{BizmaticRouterUI:ui}});
  return ui;
}
test('delete is visible in both routing registers and edit form footers',()=>{
  for(const [screen,renderer,label] of [['destinations','destinations','Delete'],['rules','rules','Delete'],['destination_edit','destinationForm','Delete destination'],['rule_edit','ruleForm','Delete rule']]){
    const ui=setup(screen);const html=ui.renderers[renderer]();
    assert.match(html,/data-action="delete-configuration"/);
    assert.ok(html.includes(`>${label}</button>`),screen);
  }
});
test('new configuration forms do not offer deletion',()=>{
  for(const [screen,renderer] of [['destination_create','destinationForm'],['rule_create','ruleForm']]) assert.doesNotMatch(setup(screen).renderers[renderer](),/data-action="delete-configuration"/);
});
test('confirmation identifies the saved record and explains unsaved edits',()=>{
  const ui=setup('rule_edit');ui.configurationDirty=true;ui.showDeleteConfiguration('rules',2);
  assert.match(ui.dialog.html,/Synthetic rule/);assert.match(ui.dialog.html,/Unsaved edits will be discarded/);assert.match(ui.dialog.html,/data-revision="revision-2"/);
});
test('Encoder rule form restores its configured connection and permitted operation',()=>{
  const ui=setup('rule_edit');
  ui.state.encoder_connections=[{id:8,name:'Synthetic MCP',tools:[{name:'encode_receipt',label:'Encode receipt'}]}];
  Object.assign(ui.state.rules[0],{encoder_connection:8,encoder_tool:'encode_receipt'});
  const html=ui.renderers.ruleForm();
  assert.match(html,/<div id="router-encoder-fields" >/);
  assert.match(html,/name="encoder_connection" required/);
  assert.match(html,/<option value="8" selected>Synthetic MCP/);
  assert.match(html,/<option value="encode_receipt" selected>Encode receipt/);
  assert.match(html,/External execution still requires confirmation/);
});
test('AP and AR rule forms hide and disable Encoder configuration inputs',()=>{
  for(const module of ['accounts_payable','accounts_receivable']){
    const ui=setup('rule_edit');ui.state.destinations[0].module_name=module;
    const html=ui.renderers.ruleForm();
    assert.match(html,/<div id="router-encoder-fields" hidden>/);
    assert.match(html,/name="encoder_connection" disabled/);
    assert.match(html,/name="encoder_tool" disabled/);
  }
});
