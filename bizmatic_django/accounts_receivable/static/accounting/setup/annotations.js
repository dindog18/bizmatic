/* Browser text-selection offsets and annotation anchors. Model execution lives in services/setup/. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.ConfigurationDocumentEngine=api;})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  const clean=value=>String(value??'').trim().replace(/^\*\*(.*?)\*\*$/s,'$1').replace(/^`(.*?)`$/s,'$1');
  const labelKey=value=>clean(value).replace(/^[\s#>*\-]+/,'').replace(/[*`_]/g,'').replace(/[:：]\s*$/,'').trim().toLowerCase();
  const type=field=>/Integer|Decimal|Float/.test(field.type)?'number':/Boolean/.test(field.type)?'boolean':'text';
  const labelText=value=>clean(value).replace(/^[*`_]+|[*`_]+$/g,'').replace(/[:：]\s*$/,'').trim();
  function labeled(line){
    const cells=line.trim().replace(/^\||\|$/g,'').split('|');
    if(cells.length>=2&&cells[0].trim())return {label:labelText(cells[0]),value:clean(cells.slice(1).join('|'))};
    const match=line.match(/^\s*(?:[-*>#]\s*)?(.{1,100}?)\s*[:：]\s*(.*)$/);
    return match?{label:labelText(match[1]),value:clean(match[2])}:null;
  }
  function annotate(text,start,end){
    let value=text.slice(start,end);const leading=value.length-value.trimStart().length;
    start+=leading;end-=value.length-value.trimEnd().length;value=text.slice(start,end);
    if(!value)return null;
    const lineStart=text.lastIndexOf('\n',start-1)+1,lineIndex=text.slice(0,lineStart).split('\n').length-1;
    const lines=text.split('\n'), pair=labeled(lines[lineIndex]||'');
    const prefix=text.slice(lineStart,start);
    let anchor;
    if(pair&&(/[:：|]/.test(prefix))){
      const occurrence=lines.slice(0,lineIndex+1).filter(line=>labelKey(labeled(line)?.label)===labelKey(pair.label)).length;
      anchor={kind:'label',label:pair.label,occurrence,lines:value.split('\n').length};
    }else anchor={kind:'line',index:lineIndex+1};
    return {start,end,value:clean(value),anchor};
  }
  return {annotate,type};
});
