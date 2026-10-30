/* One saved, advice-only conversation per workspace / record type / source. */
(() => {
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function create(api){
    let root,messages=[],revision=0,loaded=false,busy=false,draft='',error='',confirmClear=false;
    function render(){
      if(!root?.isConnected)return;
      const focused=root.querySelector('textarea')===document.activeElement;
      const position=focused?root.querySelector('textarea').selectionStart:null;
      root.innerHTML=`<section class="card setup-chat" aria-label="Setup assistant"><div class="finance-card-head"><div><h2>Setup assistant</h2><p class="lab-note mb-0">${esc(api.label)}</p></div><button type="button" class="btn btn-link btn-sm" data-chat="clear" ${busy||!loaded||!messages.length?'disabled':''}>Clear chat</button></div><div class="finance-card-body"><p class="lab-note">Ask about your current inputs. Replies offer guidance; edit the setup controls to make changes.</p><div class="setup-chat-log" role="log" aria-label="Setup conversation" aria-live="polite" aria-busy="${busy}" tabindex="0">${messages.length?messages.map(message=>`<div class="setup-chat-message ${message.role==='user'?'user':''}"><small>${message.role==='user'?'You':'Setup assistant'}</small><div>${esc(message.content)}</div></div>`).join(''):`<p class="lab-note">${loaded?'Ask a question about this setup to begin. Your conversation is saved automatically.':'Loading conversation…'}</p>`}${busy&&loaded?'<p role="status">Thinking…</p>':''}</div>${confirmClear?'<div class="finance-callout"><p>Clear this conversation? Your setup inputs will be kept.</p><button type="button" class="btn btn-danger btn-sm" data-chat="confirm-clear">Clear conversation</button> <button type="button" class="btn btn-falcon-default btn-sm" data-chat="cancel-clear">Keep chat</button></div>':''}<p class="lab-note text-danger" role="alert">${esc(error)}</p>${error?'<button type="button" class="btn btn-link btn-sm" data-chat="reload">Reload chat</button>':''}<form class="setup-chat-form"><label for="setup-chat-message">Message</label><textarea id="setup-chat-message" class="form-control" rows="3" maxlength="4000" placeholder="e.g. What is still missing?" ${busy||!loaded?'disabled':''}>${esc(draft)}</textarea><div class="lab-chat-footer"><small>Saved for this workspace, record type and source.</small><button type="submit" class="btn btn-primary btn-sm" ${busy||!loaded?'disabled':''}>${busy?'Thinking…':'Send'}</button></div></form></div></section>`;
      const log=root.querySelector('.setup-chat-log');log.scrollTop=log.scrollHeight;
      if(focused&&!busy){const input=root.querySelector('textarea');input.focus({preventScroll:true});input.setSelectionRange(position,position);}
    }
    function accept(result){messages=result.messages;revision=result.chat_revision;loaded=true;}
    async function load(){
      if(busy)return;
      busy=true;error='';render();
      try{accept(await api.load());}catch(problem){error=problem.message;}
      finally{busy=false;render();}
    }
    async function send(){
      if(busy||!loaded||!draft.trim())return;
      busy=true;error='';confirmClear=false;render();
      try{accept(await api.send(draft,revision));draft='';}
      catch(problem){error=problem.message;}
      finally{busy=false;render();root?.querySelector('textarea')?.focus({preventScroll:true});}
    }
    async function clear(){
      if(busy||!loaded)return;
      busy=true;error='';confirmClear=false;render();
      try{accept(await api.clear(revision));}catch(problem){error=problem.message;}
      finally{busy=false;render();}
    }
    return {mount(element){
      root=element;render();
      root.addEventListener('input',event=>{if(event.target.id==='setup-chat-message')draft=event.target.value;});
      root.addEventListener('submit',event=>{if(event.target.matches('.setup-chat-form')){event.preventDefault();send();}});
      root.addEventListener('click',event=>{
        const action=event.target.closest('[data-chat]')?.dataset.chat;
        if(action==='clear'){confirmClear=true;render();}
        else if(action==='cancel-clear'){confirmClear=false;render();}
        else if(action==='confirm-clear')clear();
        else if(action==='reload')load();
      });
      if(!loaded)load();
    }};
  }
  window.SetupAssistantChat={create};
})();
