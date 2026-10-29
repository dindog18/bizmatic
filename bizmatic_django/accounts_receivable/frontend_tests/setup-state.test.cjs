const {test}=require('node:test');
const assert=require('node:assert/strict');
const annotations=require('../static/accounting/setup/annotations.js');
const query=require('../static/accounting/setup/query-state.js');
test('selection offsets preserve exact values and identify Markdown labels',()=>{
 const text='😀 Header\n\n**Tax ID:** 123-456\nName: Example';const start=text.indexOf('123-456');
 const annotation=annotations.annotate(text,start,start+7);
 assert.equal(annotation.start,start);assert.equal(annotation.value,'123-456');assert.equal(annotation.anchor.label,'Tax ID');
 assert.equal(annotations.annotate('   ',0,3),null);
});
test('Markdown table and repeated-label selections retain the correct occurrence',()=>{
 const text='| Name | First |\n| Name | Second |';const start=text.indexOf('Second');
 const annotation=annotations.annotate(text,start,start+6);
 assert.equal(annotation.anchor.label,'Name');assert.equal(annotation.anchor.occurrence,2);
});
function schema(){return {
 customers:{name:'public.customers',columns:[{name:'id'}],references:[]},
 companies:{name:'public.companies',columns:[{name:'id'},{name:'customer_id'},{name:'tenant_id'}],references:[{table:'customers',pairs:[{column:'customer_id',target:'id'}]}]},
 branches:{name:'public.branches',columns:[{name:'id'},{name:'company_id'},{name:'tenant_id'}],references:[{table:'companies',pairs:[{column:'company_id',target:'id'},{column:'tenant_id',target:'tenant_id'}]}]},
 };}
function state(){return {table:'customers',joins:[],keys:['base.id'],mappings:[],filters:{children:[]},sorts:[]};}
test('multi-hop FK paths keep every part of composite relationships',()=>{
 const data=schema(),plan=state();let serial=0;const connected=query.connectTable(data,plan,'branches',()=>`table${++serial}`);
 assert.equal(connected.needsMatch,false);assert.equal(plan.joins.length,2);
 assert.deepEqual(plan.joins[1].on,[{left:'table1.id',right:'company_id'},{left:'table1.tenant_id',right:'tenant_id'}]);
 assert.equal(query.connectTable(data,plan,'companies',()=>`table${++serial}`).alias,'table1');assert.equal(plan.joins.length,2);
});
test('pending field and identifier choices retain their selected connections',()=>{
 const data=schema(),plan=state();let serial=0;const connected=query.connectTable(data,plan,'branches',()=>`table${++serial}`);
 plan.keyMode='custom';plan.keyFields=[{tableAlias:connected.alias,column:''}];query.pruneConnections(plan);assert.equal(plan.joins.length,2);
 plan.keyMode='auto';plan.keyFields=[];query.pruneConnections(plan);assert.equal(plan.joins.length,0);
});
test('unknown business relationships are not inferred through audit users',()=>{
 const data={a:{name:'public.customers',columns:[],references:[{table:'user',pairs:[{column:'encoder_id',target:'id'}]}]},b:{name:'public.branches',columns:[],references:[{table:'user',pairs:[{column:'encoder_id',target:'id'}]}]},user:{name:'public.auth_user',columns:[],references:[]}};
 const plan={...state(),table:'a'};let serial=0;
 assert.equal(query.connectTable(data,plan,'b',()=>`table${++serial}`).needsMatch,true);
 assert.deepEqual(plan.joins[0].on,[{left:'',right:''}]);
});
