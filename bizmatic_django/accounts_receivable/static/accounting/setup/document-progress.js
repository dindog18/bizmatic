/* Browser drafts resume document setup without activating an extraction configuration. */
(() => {
  'use strict';
  const prefix='bizmatic:document-setup:v1:';
  const maxAge=7*24*60*60*1000;
  const receiptAge=30*60*1000;
  const fields=['step','sourceMode','sample','draft','text','locked','rules','active','prompt',
    'promptStale','result','stale','testSource','testDraft','customExpected','messages',
    'question','instructions','line_context'];
  const key=scope=>prefix+JSON.stringify([scope.mode,scope.target,scope.id||'new']);
  function create(storage,now=Date.now){
    function remove(scope){storage.removeItem(key(scope));}
    function save(scope,session){
      const editor=Object.fromEntries(fields.filter(name=>session.editor[name]!==undefined)
        .map(name=>[name,session.editor[name]]));
      // A signed test receipt still expires on the server; saving UI progress
      // must not extend its lifetime on every keystroke or refresh.
      const receipt=session.testToken?{token:session.testToken,at:session.testedAt}:null;
      storage.setItem(key(scope),JSON.stringify({version:1,at:now(),revision:scope.revision,
        profile:session.profile,editor,messages:session.messages,hasUnsaved:session.hasUnsaved,receipt}));
    }
    function load(scope){
      const raw=storage.getItem(key(scope));
      if(!raw)return null;
      let value;
      try{value=JSON.parse(raw);}catch(_){remove(scope);return null;}
      const object=value=>value&&typeof value==='object'&&!Array.isArray(value);
      if(!object(value)||value.version!==1||!Number.isFinite(value.at)||value.at>now()||now()-value.at>maxAge||
        value.revision!==scope.revision||!object(value.profile)||!object(value.editor)||
        ![1,2,3].includes(value.editor.step)||!object(value.editor.rules)||
        typeof value.editor.text!=='string'||typeof value.editor.prompt!=='string'||
        value.profile.source_type!=='document'||value.profile.target_entity!==scope.target||
        (value.profile.id||null)!==(scope.id||null)){
        remove(scope);return null;
      }
      const session={profile:value.profile,editor:value.editor,messages:value.messages||[],
        hasUnsaved:value.hasUnsaved!==false,testToken:null,testedAt:null};
      const receipt=value.receipt;
      if(typeof receipt?.token==='string'&&Number.isFinite(receipt.at)&&receipt.at<=now()&&now()-receipt.at<receiptAge){
        session.testToken=receipt.token;session.testedAt=receipt.at;
      }else if(session.editor.result){
        session.editor.stale=true;
      }
      return session;
    }
    return {save,load,remove};
  }
  window.DocumentSetupProgress={create};
})();
