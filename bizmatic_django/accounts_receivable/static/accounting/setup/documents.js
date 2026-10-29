/* Record-first documents: annotation UI, CONFIG_ASSISTANT prompt generation and server-verified tests. */
(() => {
  'use strict';
  const engine=window.ConfigurationDocumentEngine;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const button=(label,action,extra='',style='btn-falcon-default')=>`<button type='button' class='btn ${style} btn-sm' data-da='${action}' ${extra}>${label}</button>`;
  const card=(title,subtitle,body,actions='')=>`<section class='card da-card'><div class='finance-card-head'><div><h2>${title}</h2>${subtitle?`<p class='lab-note mb-0'>${subtitle}</p>`:''}</div>${actions}</div><div class='finance-card-body'>${body}</div></section>`;
  function mount(root,options){
    const {destination,api,documents}=options;
    let state=options.state;
    let rebuilding=false;
    const fields=[...destination.fields.map(field=>({...field,key:'header:'+field.key})),...destination.lineFields.map(field=>({...field,key:'line:'+field.key,label:'Line · '+field.label}))];
    const freshRules=()=>Object.fromEntries(fields.map(field=>[field.key,{method:field.required?'unmapped':'empty',annotation:null,value:''}]));
    const defaults={step:1,sourceMode:documents.length?'sample':'paste',sample:documents[0]?.id||'',draft:'',text:'',locked:false,rules:freshRules(),active:fields[0].key,selection:null,prompt:'',promptStale:false,result:null,stale:false,confirmed:false,testSource:'annotated',testDraft:'',customExpected:{},notice:'',messages:[],question:'',instructions:'',line_context:''};
    const loaded=state;
    state={...defaults,...state,rules:{...freshRules(),...state?.rules}};
    function normalizeRules(){
      Object.values(state.rules).forEach(rule=>{
        if(rule?.method==='instruction'&&!Object.hasOwn(rule,'instruction')&&typeof rule.value==='string'){rule.instruction=rule.value;delete rule.value;}
      });
    }
    normalizeRules();
    fields.filter(field=>field.key.startsWith('line:')&&state.rules[field.key]?.method==='unmapped').forEach(field=>state.rules[field.key]={method:'empty',annotation:null,value:''});
    if(loaded?.text&&!loaded.step){state.draft=loaded.text;state.sourceMode='paste';state.locked=true;state.step=loaded.prompt?3:2;}
    function colorAttributes(key){
      const name=key.split(':').pop(),index=fields.findIndex(field=>field.key===key);
      const known={supplier_code:['#1d4ed8','#eff6ff','#bfdbfe'],customer_code:['#1d4ed8','#eff6ff','#bfdbfe'],supplier_name:['#15803d','#f0fdf4','#bbf7d0'],customer_name:['#15803d','#f0fdf4','#bbf7d0'],tax_identification_no:['#7c3aed','#f5f3ff','#ddd6fe'],billing_address:['#c2410c','#fff7ed','#fed7aa'],contact_person:['#0f766e','#f0fdfa','#99f6e4'],email:['#be185d','#fdf2f8','#fbcfe8'],phone:['#b91c1c','#fef2f2','#fecaca'],payment_terms_days:['#a16207','#fefce8','#fef08a'],is_active:['#475569','#f8fafc','#cbd5e1']};
      const hue=Math.round(index*137.508)%360,colors=known[name]||[`hsl(${hue},55%,32%)`,`hsl(${hue},65%,97%)`,`hsl(${hue},65%,83%)`];
      return `data-field-color='${esc(key)}' style='--da-field-ink:${colors[0]};--da-field-tint:${colors[1]};--da-field-highlight:${colors[2]}'`;
    }
    const fieldFor=key=>fields.find(field=>field.key===key);
    const ruleFor=()=>state.rules[state.active];
    const requiredMissing=()=>fields.filter(field=>field.required&&(state.rules[field.key].method==='unmapped'||state.rules[field.key].method==='empty'||state.rules[field.key].method==='constant'&&!String(state.rules[field.key].value??'').trim()||state.rules[field.key].method==='instruction'&&!state.rules[field.key].instruction?.trim()));
    function invalidate(mapping=false){api.changed();state.confirmed=false;if(mapping)state.customExpected={};if(state.result)state.stale=true;if(mapping&&state.prompt)state.promptStale=true;}
    const ready=()=>state.locked&&!requiredMissing().length;
    const testText=()=>state.testSource==='annotated'?state.text:state.testDraft;
    function expectations(){
      const expected=state.testSource==='annotated'?Object.fromEntries(fields.map(field=>{const rule=state.rules[field.key];return [field.key,rule.method==='extract'?rule.annotation?.value:rule.method==='constant'?rule.value:rule.method==='instruction'?rule.example:null];})):{};
      return {...expected,...state.customExpected};
    }
    const snapshot=()=>JSON.stringify([state.prompt,testText(),expectations(),state.promptStale,state.rules]);
    const canSubmit=()=>state.result&&!state.stale&&state.result.snapshot===snapshot()&&!state.confirmed&&api.hasReceipt();
    function steps(){return `<nav class='da-steps card' aria-label='Document setup steps'>${[['Choose text','Choose or paste an extraction'],['Annotate','Highlight and map values'],['Prompt & test','Check every field']].map(([label,description],index)=>`<button type='button' data-da='step' data-step='${index+1}' ${index===1&&!state.locked||index===2&&!ready()?'disabled':''} ${state.step===index+1?"aria-current='step'":''}><span>${index+1}</span><div><strong>${label}</strong><small>${description}</small></div></button>`).join('')}</nav>`;}
    function help(){return card('Setup assistant','Configuration assistant',`<div class='da-help-copy'>${state.messages.length?state.messages.slice(-3).map(message=>`<p>${esc(message)}</p>`).join(''):`<p>${state.step===1?'Choose an extracted document or paste your own text. You can edit either before annotating.':state.step===2?'Highlight only the value, then choose its destination field. All line item fields are optional. Leave them empty when no item data is available. Other optional fields can stay empty too.':'Test the generated rules against the annotated sample or another extraction. Review every result before submitting.'}</p>`}</div><form id='da-help-form'><label for='da-question'>Ask about this setup</label><textarea id='da-question' class='form-control' rows='2' placeholder='e.g. What is still missing?'>${esc(state.question)}</textarea><div class='da-actions mt-2'>${button('What is missing?','help-missing','','btn-link')}<button type='submit' class='btn btn-falcon-default btn-sm'>Ask</button></div></form>`);}
    function chooseText(){return `<div class='da-layout'><div>${card('1. Choose your sample text','Use text that has already been extracted from a document.',`<div class='da-source-choices' role='group' aria-label='Sample text source'>${button('Choose extracted document','source-sample',`aria-pressed='${state.sourceMode==='sample'}'`,state.sourceMode==='sample'?'btn-primary':'btn-falcon-default')}${button('Paste my text','source-paste',`aria-pressed='${state.sourceMode==='paste'}'`,state.sourceMode==='paste'?'btn-primary':'btn-falcon-default')}</div>${state.sourceMode==='sample'?`<label for='da-sample'>Extracted document</label><select id='da-sample' class='form-select mb-3'>${documents.map(document=>`<option value='${document.id}'${String(state.sample)===String(document.id)?' selected':''}>${esc(document.name)} · extraction #${document.id}</option>`).join('')}</select>`:`<p class='lab-note'>Paste plain text or Markdown. It stays editable until you use it for annotation.</p>`}<label for='da-source-text'>Extracted document text</label><textarea id='da-source-text' class='form-control da-source-text' rows='17' spellcheck='false' placeholder='Paste the extracted document here…'>${esc(state.draft)}</textarea>${state.locked?`<p class='lab-note mt-2'>Changing the text clears its highlights, generated prompt, and previous test.</p>`:''}<div class='da-actions mt-3'><span class='lab-note'>${state.sourceMode==='sample'?'Extracted text is editable. The original document stays available.':'Paste text from your document extraction.'}</span>${state.locked?button('Keep original text','cancel-edit'):''}${button(state.locked?'Use updated text':'Use text & annotate','lock-text',state.draft.trim()?'':'disabled','btn-primary')}</div>` )}</div><aside>${help()}</aside></div>`;}
    function markedText(){
      const highlights=fields.filter(field=>state.rules[field.key].method==='extract').map(field=>({...state.rules[field.key].annotation,field})).filter(item=>Number.isInteger(item.start)&&item.end<=state.text.length);
      const points=[...new Set([0,state.text.length,...highlights.flatMap(item=>[item.start,item.end])])].sort((a,b)=>a-b);
      return points.slice(0,-1).map((start,index)=>{const end=points[index+1],matches=highlights.filter(item=>item.start<=start&&item.end>=end),chosen=matches.find(item=>item.field.key===state.active)||matches[0];const text=esc(state.text.slice(start,end));return chosen?`<mark ${colorAttributes(chosen.field.key)} class='${chosen.field.key===state.active?'active':''}'>${text}</mark>`:text;}).join('')+'\n';
    }
    function selectionBar(){return `<div class='da-selection' id='da-selection' ${colorAttributes(state.active)} aria-live='polite'><div><small>${state.selection?'Selected value':'Highlight a value in the document'}</small><strong>${state.selection?esc(state.selection.value):'Then assign it to a destination field.'}</strong></div><div class='da-mobile-target'><label for='da-target'>Map selection to</label><select id='da-target' class='form-select'>${fields.map(field=>`<option value='${field.key}'${state.active===field.key?' selected':''}>${esc(field.label)} · ${field.required?'Required':'Optional'}</option>`).join('')}</select></div>${button('Map to '+esc(fieldFor(state.active).label),'annotate',state.selection?'':'disabled','btn-primary')}</div>`;}
    function fieldPanel(){
      const field=fieldFor(state.active),rule=ruleFor();
      return card('Destination fields',`${fields.filter(field=>field.required).length-requiredMissing().length} of ${fields.filter(field=>field.required).length} required fields mapped`, `<p class='lab-note'>Each field’s color matches its document highlights. Choose a field before or after highlighting a value. Optional fields stay empty until mapped.</p><div class='da-field-list' role='group' aria-label='Destination fields to annotate'>${fields.map(field=>{const rule=state.rules[field.key];return `<button type='button' data-da='field' data-key='${field.key}' ${colorAttributes(field.key)} class='da-field${field.key===state.active?' active':''}' aria-pressed='${field.key===state.active}'><span><strong><i class='da-color-swatch' aria-hidden='true'></i>${esc(field.label)}</strong><small>${rule.method==='extract'?esc(rule.annotation.value):rule.method==='constant'?'Approved value: '+esc(rule.value):rule.method==='instruction'?'Rule: '+esc(rule.instruction):rule.method==='empty'?'Leave empty if unavailable':'Highlight a value to map'}</small></span><span class='da-badge ${field.required?'required':'optional'}'>${field.required?'Required':'Optional'}</span></button>`;}).join('')}</div><div class='da-field-settings' ${colorAttributes(field.key)}><strong><i class='da-color-swatch' aria-hidden='true'></i>${esc(field.label)}</strong><label for='da-field-method' class='mt-2'>How to fill this field</label><select id='da-field-method' class='form-select'><option value='extract'${['extract','unmapped'].includes(rule.method)?' selected':''}>Use highlighted document text</option><option value='constant'${rule.method==='constant'?' selected':''}>Use an approved value</option><option value='instruction'${rule.method==='instruction'?' selected':''}>Describe an extraction rule</option>${!field.required?`<option value='empty'${rule.method==='empty'?' selected':''}>Leave empty if unavailable</option>`:''}</select>${rule.method==='instruction'?`<label for='da-field-instruction' class='mt-2'>Extraction rule</label><textarea id='da-field-instruction' class='form-control' rows='3' placeholder='e.g. Number the item rows from 1'>${esc(rule.instruction||'')}</textarea><label for='da-rule-example' class='mt-2'>Expected example value (optional)</label><input id='da-rule-example' class='form-control' value='${esc(rule.example||'')}'>`:rule.method==='constant'?`<label for='da-constant' class='mt-2'>Approved value</label><input id='da-constant' class='form-control' value='${esc(rule.value)}' placeholder='${engine.type(field)==='boolean'?'Yes or No':engine.type(field)==='number'?'e.g. 30':'Enter a value'}'>`:rule.method==='extract'?`<p class='lab-note mt-2 mb-1'>Highlighted: <strong>${esc(rule.annotation.value)}</strong></p>${rule.annotation.anchor.kind==='label'?`<label for='da-anchor'>Document label</label><input id='da-anchor' class='form-control' value='${esc(rule.annotation.anchor.label)}'><small class='lab-note'>Uses this label on other documents, rather than copying the example value.</small>`:`<p class='finance-callout warning'>This value uses line ${rule.annotation.anchor.index}. Labeled values are more reliable across different documents.</p>`}${button('Clear highlight','clear-annotation','','btn-link mt-2')}`:`<p class='lab-note mt-2 mb-0'>${rule.method==='empty'?'The prompt will include this field as null.':'Highlight only the value in the document, then select Map to '+esc(field.label)+'.'}</p>`}</div>`);
    }
    function annotationStep(){return `<div class='da-layout'><div class='lab-stack'>${card('2. Highlight the values to map','The text is locked for annotation. Select text with your mouse, or use Shift + arrow keys.',`${selectionBar()}<div class='da-paper'><pre class='da-mirror' id='da-mirror' aria-hidden='true'>${markedText()}</pre><textarea id='da-annotation-text' class='da-annotation-text' readonly spellcheck='false' aria-label='Document text for annotation'>${esc(state.text)}</textarea></div><div class='da-legend' aria-label='Annotation color key'>${fields.filter(field=>state.rules[field.key].method==='extract').map(field=>`<button type='button' class='da-color-key' data-da='field' data-key='${field.key}' ${colorAttributes(field.key)} aria-pressed='${state.active===field.key}'><i class='da-color-swatch' aria-hidden='true'></i>${esc(field.label)}</button>`).join('')||'<span>Each field has its own color, shown in the field panel.</span>'}</div><div class='da-actions'><span class='lab-note'>${requiredMissing().length?requiredMissing().length+' required field(s) still need a value.':'Required fields are ready. Review the optional fields you need.'}</span>${button(state.prompt?'Continue to prompt & test':'Create prompt & test','create-prompt',ready()?'':'disabled','btn-primary')}</div>`,button('Edit text','edit-text'))}</div><aside class='lab-stack'>${fieldPanel()}${help()}</aside></div>`;}
    function comparisonControl(row){
      const rule=state.rules[row.key];
      if(!rule||['empty','constant'].includes(rule.method))return `<small class='lab-note'>${rule?.method==='constant'?'Approved value must match.':'Must follow the empty-field rule.'}</small>`;
      const exempt=rule.comparison==='format';
      return `<label class='da-exception-toggle'><input type='checkbox' data-comparison='${row.key}' aria-label='Allow expected-value exception for ${esc(row.label)}'${exempt?' checked':''}><span>Allow expected-value exception<small>${exempt?'Expected value is not required. Accounting checks still apply.':'Skip expected-value matching for this field.'}</small></span></label>`;
    }
    function resultPanel(){
      const result=state.result;
      return card('Mapping test results','Compare expected values, or tick an exception for an intentional conversion. Exceptions are checked automatically.',`${!result?`<div class='da-empty'>Run the mapping test to see the extracted record.</div>`:`<div class='finance-callout ${result.passed&&!state.stale?'success':'warning'}' role='status'><div class='da-feedback-heading'><strong>${state.stale?'Changed · test again':result.passed?'Mapping test passed':'Mapping test needs attention'}</strong>${!result.passed?button(rebuilding?'Rebuilding…':'Rebuild from test results','rebuild-results',rebuilding||state.stale?'disabled':'','btn-primary'):''}</div><p class='mb-0 mt-1'>${state.stale?'Your previous result is shown below. Retest the latest prompt and text.':result.passed?'Required values and accounting checks passed. Expected values match after normalization or have a recorded exception.':result.rows.length?'Correct the highlighted fields, prompt rules, or expected values, then test again.':esc(result.issues.join(' '))}</p>${!result.passed?`<ul class='mt-2 mb-0'>${result.issues.map(issue=>`<li>${esc(issue)}</li>`).join('')}</ul><p class='lab-note mt-3 mb-0'>Rebuilding uses these results to improve the prompt. Account setup, expected values, and formatting may still need correction. Review the prompt, then test again.</p>`:''}</div>${result.notes?.length?`<div class='finance-callout mt-3' role='status'><strong>Conversions checked</strong><ul class='mb-0 mt-2'>${result.notes.map(note=>`<li>${esc(note)}</li>`).join('')}</ul></div>`:''}${result.rows.length?`<div class='table-responsive' tabindex='0' aria-label='Mapping test results'><table class='table da-result-table'><thead><tr><th scope='col'>Destination field</th><th scope='col'>Mapped result</th><th scope='col'>Expected value</th><th scope='col'>Exception</th><th scope='col'>Check</th></tr></thead><tbody>${result.rows.map(row=>`<tr class='${row.status!=='passed'?'da-row-attention':''}'><th scope='row'>${esc(row.label)}<small>${row.required?'Required':'Optional'}</small></th><td>${row.value===null?'<span class="text-muted">null</span>':esc(row.value)}</td><td><input class='form-control' aria-label='Expected ${esc(row.label)}' data-expected='${row.key}' value='${esc(state.customExpected[row.key]??row.expected??'')}' placeholder='${row.hasExpected?'':'Enter expected value'}'${state.rules[row.key]?.comparison==='format'&&!['empty','constant'].includes(state.rules[row.key]?.method)?' disabled':''}></td><td>${comparisonControl(row)}</td><td><span class='da-badge ${row.status==='passed'?'passed':'required'}'>${row.status==='passed'?(row.comparison==='format'?'Exception applied':row.comparison_note?'Equivalent':'Matched'):row.status==='review'?'Review':'Check'}</span>${row.issue?`<small>${esc(row.issue)}</small>`:''}${row.comparison_note?`<small>${esc(row.comparison_note)}</small>`:''}</td></tr>`).join('')}</tbody></table></div>`:''}<details class='lab-details'><summary>Mapped record and line items</summary><pre class='da-json'>${esc(JSON.stringify({record:result.record,lines:result.lines||[]},null,2))}</pre></details>`}<div class='da-actions da-submit-bar'><span class='lab-note'>${state.confirmed?'Configuration saved and activated.':'Review the latest test results before saving. You can save with issues after acknowledging them.'}</span>${button(state.confirmed?'Saved & active':'Review & save','review',canSubmit()?'':'disabled','btn-primary')}</div>`);
    }
    function promptStep(){return `<div class='lab-stack'><div class='da-layout'><div>${card('3. Create and test your prompt','Built from your annotations, approved values, and empty-field rules.',`<label for='da-prompt'>Extraction and mapping prompt</label><textarea id='da-prompt' class='form-control da-prompt' rows='16' spellcheck='false'>${esc(state.prompt)}</textarea><p class='lab-note mt-2'>Prompt generation, questions, and document tests use your configured setup assistant. Expected answers are kept out of the model request.</p>${state.promptStale?`<p class='finance-callout warning'>Field rules changed. You can test them now; rebuilding the prompt is optional.</p>`:''}<div class='da-actions'>${button('Back to annotations','back-annotations','','btn-link')}${button('Rebuild from annotations','rebuild-prompt')}</div>`)}</div><aside class='lab-stack'>${card('Test document','Try the annotated sample or another extracted document.',`<label for='da-test-source'>Text to test</label><select id='da-test-source' class='form-select mb-3'><option value='annotated'${state.testSource==='annotated'?' selected':''}>My annotated document</option>${documents.map(document=>`<option value='saved:${document.id}'${state.testSource==='saved:'+document.id?' selected':''}>${esc(document.name)} · #${document.id}</option>`).join('')}<option value='paste'${state.testSource==='paste'?' selected':''}>Paste another extraction</option></select><label for='da-test-text'>Extracted text for testing</label><textarea id='da-test-text' class='form-control da-test-text' rows='11' ${state.testSource!=='paste'?'readonly':''} placeholder='Paste a different extraction to test your mappings…'>${esc(testText())}</textarea>${state.testSource==='paste'?`<p class='lab-note mt-2'>After testing, enter expected values in the results table to verify the mappings.</p>`:''}<div class='da-actions mt-3'><span class='lab-note'>All ${fields.length} fields are checked.</span>${button(state.result?'Run mapping test again':'Run mapping test','test','','btn-primary')}</div>`)}${help()}</aside></div>${resultPanel()}</div>`;}
    function render(){
      const active=root.contains(document.activeElement)?document.activeElement:null,focus=active?.id?active.id:null;
      root.innerHTML=`${steps()}${state.notice?`<div class='qb-notice' role='status'>${esc(state.notice)}</div>`:''}${state.step===1?chooseText():state.step===2?annotationStep():promptStep()}<dialog id='da-dialog' class='finance-dialog lab-dialog' aria-labelledby='da-dialog-title'></dialog>`;
      if(focus)root.querySelector('#'+CSS.escape(focus))?.focus({preventScroll:true});
      const text=root.querySelector('#da-annotation-text');
      if(text&&state.selection)text.setSelectionRange(state.selection.start,state.selection.end);
    }
    function captureSelection(event){
      if(event.target.id!=='da-annotation-text')return;
      const area=event.target;
      const selection=engine.annotate(state.text,area.selectionStart,area.selectionEnd);
      if(state.selection?.start===selection?.start&&state.selection?.end===selection?.end)return;
      state.selection=selection;
      const old=root.querySelector('#da-selection');if(old)old.outerHTML=selectionBar();
    }
    ['select','mouseup','keyup','touchend'].forEach(name=>root.addEventListener(name,captureSelection));
    root.addEventListener('scroll',event=>{if(event.target.id==='da-annotation-text'){const mirror=root.querySelector('#da-mirror');if(mirror){mirror.scrollTop=event.target.scrollTop;mirror.scrollLeft=event.target.scrollLeft;}}},true);
    function updateTestState(){
      root.querySelectorAll('[data-da="review"]').forEach(control=>control.disabled=true);
      const status=root.querySelector('.da-result-table')?.closest('.finance-card-body')?.querySelector('[role="status"] strong');if(status)status.textContent='Changed · test again';
    }
    function enterStep(step){
      if(step===2&&!state.locked||step===3&&!ready())return;
      state.step=step;
      if(step===3&&!state.prompt){state.step=2;return;}
      if(step===1){state.draft=state.text||state.draft;state.editing=state.locked;}
      state.notice='';render();root.querySelector('.da-steps [aria-current]')?.focus({preventScroll:false});
    }
    let recheckVersion=0;
    async function applyExceptions(){
      const version=++recheckVersion,before=snapshot(),log=state.result?.llm_log_no;
      if(!log)return;
      state.notice='Checking the existing mapped result…';render();
      try{
        const result=await api.recheckDocument(testText(),expectations(),log);
        if(version!==recheckVersion||snapshot()!==before)return;
        state.result=result;state.result.snapshot=snapshot();state.stale=false;state.confirmed=false;
        api.acceptRecheck(result.test_token);
        state.notice=result.passed?'Exceptions applied. You can now review and save.':'Exceptions applied. You can review and save with the remaining issues.';
        render();
      }catch(error){if(version===recheckVersion){state.notice='Could not apply exceptions. Review the error above.';render();api.error(error);}}
    }
    async function runTest(){
      try{state.promptStale=false;state.result=await api.testDocument(state,testText(),expectations());state.result.snapshot=snapshot();state.stale=false;state.confirmed=false;state.notice='';render();root.querySelector('.da-result-table, .da-submit-bar')?.scrollIntoView({block:'nearest',behavior:'smooth'});}catch(error){api.error(error);}
    }
    async function generatePrompt(){
      if(!ready())return;
      try{const result=await api.generate(state);state.prompt=result.prompt;state.promptStale=false;invalidate();state.step=3;render();root.querySelector('.da-steps [aria-current]')?.focus();}catch(error){api.error(error);}
    }
    async function rebuildFromResults(){
      if(rebuilding||!state.result||state.result.passed||state.stale)return;
      const before=snapshot();
      const feedback={text:testText(),issues:state.result.issues,rows:state.result.rows.map(row=>({key:row.key,value:row.value,expected:state.customExpected[row.key]??row.expected,issue:row.issue}))};
      rebuilding=true;render();
      try{
        const result=await api.generate(state,feedback);
        if(snapshot()!==before)throw new Error('The setup changed while rebuilding. Run the mapping test again before rebuilding.');
        state.prompt=result.prompt;state.promptStale=false;invalidate();
        state.notice='Prompt rebuilt from test results. Review it, then run the mapping test again. Account setup and expected-value issues may still need correction.';
        state.step=3;
      }catch(error){api.error(error);}
      finally{rebuilding=false;render();}
      root.querySelector('#da-prompt')?.focus();
    }
    async function helpReply(){
      if(!state.question.trim())return;
      try{const response=await api.chat(state.question);const updated=response.record.setup_data.document;const previousPrompt=state.prompt,previousRules=JSON.stringify(state.rules),previousInstructions=state.instructions;Object.assign(state,updated);state.rules={...freshRules(),...state.rules};normalizeRules();state.messages.push(response.message);state.question='';if(response.changed){const rulesChanged=previousRules!==JSON.stringify(state.rules)||previousInstructions!==state.instructions;invalidate(rulesChanged&&previousPrompt===state.prompt);state.promptStale=false;}render();}catch(error){api.error(error);}
    }
    root.addEventListener('input',event=>{
      const el=event.target;
      if(el.id==='da-source-text'){state.draft=el.value;root.querySelector('[data-da="lock-text"]').disabled=!el.value.trim();}
      else if(el.id==='da-prompt'){state.prompt=el.value;invalidate();updateTestState();}
      else if(el.id==='da-test-text'&&state.testSource==='paste'){state.testDraft=el.value;invalidate();updateTestState();}
      else if(el.id==='da-constant'){ruleFor().value=el.value;invalidate(true);root.querySelectorAll('[data-da="create-prompt"], [data-da="step"][data-step="3"]').forEach(control=>control.disabled=!ready());}
      else if(el.id==='da-field-instruction'){ruleFor().instruction=el.value;invalidate(true);root.querySelectorAll('[data-da="create-prompt"],[data-da="step"][data-step="3"]').forEach(control=>control.disabled=!ready());}
      else if(el.id==='da-rule-example'){ruleFor().example=el.value;invalidate(true);}
      else if(el.id==='da-anchor'){ruleFor().annotation.anchor.label=el.value;invalidate(true);}
      else if(el.dataset.expected){state.customExpected[el.dataset.expected]=el.value;invalidate();updateTestState();}
      else if(el.id==='da-question')state.question=el.value;
    });
    root.addEventListener('change',async event=>{
      const el=event.target;
      if(el.dataset.comparison){state.rules[el.dataset.comparison].comparison=el.checked?'format':'normalized';invalidate();await applyExceptions();}
      else if(el.id==='da-target'){state.active=el.value;render();}
      else if(el.id==='da-sample'){state.sample=el.value;try{const document=await api.document(state.sample);state.draft=document.text;render();}catch(error){api.error(error);}}
      else if(el.id==='da-field-method'){
        const rule=ruleFor();rule.method=el.value==='extract'&&!rule.annotation?'unmapped':el.value;
        if(el.value!=='extract')rule.annotation=null;
        invalidate(true);render();
      }
      else if(el.id==='da-test-source'){state.testSource=el.value;state.customExpected={};state.result=null;state.confirmed=false;state.stale=false;api.changed();if(el.value.startsWith('saved:')){try{const document=await api.document(el.value.slice(6));state.testDraft=document.text;}catch(error){api.error(error);}}else state.testDraft='';render();}
    });
    root.addEventListener('submit',event=>{if(event.target.id==='da-help-form'){event.preventDefault();helpReply();}});
    root.addEventListener('click',async event=>{
      const control=event.target.closest('[data-da]');if(!control||control.disabled)return;
      const action=control.dataset.da;
      if(action==='step')enterStep(Number(control.dataset.step));
      else if(action==='source-sample'||action==='source-paste'){const next=action==='source-sample'?'sample':'paste';if(state.sourceMode!==next){state.sourceMode=next;state.draft='';if(next==='sample'&&state.sample){try{state.draft=(await api.document(state.sample)).text;}catch(error){api.error(error);}}render();}}
      else if(action==='lock-text'){
        if(!state.draft.trim())return;
        if(state.text!==state.draft){state.text=state.draft;state.rules=freshRules();state.selection=null;state.prompt='';state.promptStale=false;state.result=null;state.customExpected={};state.confirmed=false;state.stale=false;api.changed();}
        state.locked=true;state.editing=false;enterStep(2);
      }
      else if(action==='cancel-edit')enterStep(2);
      else if(action==='edit-text')enterStep(1);
      else if(action==='field'){state.active=control.dataset.key;render();}
      else if(action==='annotate'){
        if(!state.selection)return;
        state.rules[state.active]={method:'extract',annotation:structuredClone(state.selection),value:''};
        invalidate(true);state.notice=fieldFor(state.active).label+' mapped. The highlighted value is now part of the extraction rule.';state.selection=null;render();
      }
      else if(action==='clear-annotation'){const field=fieldFor(state.active);state.rules[state.active]={method:field.required?'unmapped':'empty',annotation:null,value:''};invalidate(true);render();}
      else if(action==='create-prompt'){if(state.prompt)enterStep(3);else await generatePrompt();}
      else if(action==='back-annotations')enterStep(2);
      else if(action==='rebuild-prompt')await generatePrompt();
      else if(action==='rebuild-results')await rebuildFromResults();
      else if(action==='test')runTest();
      else if(action==='help-missing'){state.question='What is missing?';helpReply();}
      else if(action==='review'){if(canSubmit()){try{if(await api.review(true)){state.confirmed=true;state.notice='Configuration saved and activated.';render();}}catch(error){api.error(error);}}}
    });
    render();if(!state.draft&&!state.text&&state.sourceMode==='sample'&&state.sample)api.document(state.sample).then(document=>{state.draft=document.text;render();}).catch(api.error);return state;
  }
  window.RecordSetupDocuments={mount};
})();
