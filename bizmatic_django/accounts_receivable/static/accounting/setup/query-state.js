/* Query field options and declared relationship paths. Actual queries execute on the server. */
(function (root, factory) {
  const engine = factory();
  if (typeof module === 'object' && module.exports) module.exports = engine;
  else root.ConfigurationQueryEngine = engine;
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  const ref = (alias,column) => alias+'.'+column;
  function available(schema, query) {
    const sources = [{id:'base', table:query.table}, ...query.joins];
    return sources.flatMap(source => (schema[source.table]?.columns || []).map(column => ({...column, ref:ref(source.id, column.name), alias:source.id, table:source.table})));
  }
  // Connect a table through declared foreign keys, never coincidental column names.
  function connectTable(schema, query, table, nextId) {
    const sources = [{id:'base',table:query.table}, ...query.joins];
    const existing = sources.find(source => source.table === table);
    if (existing) return {alias:existing.id, added:[], needsMatch:false};
    if (!schema[table]) return {alias:'', added:[], needsMatch:true};
    const edges = [];
    Object.entries(schema).forEach(([from,definition]) => (definition.references || []).forEach(link => {
      if (!schema[link.table]) return;
      const technical=id=>/(^|\.)(auth_|django_)/.test(schema[id]?.name||id);
      if(!technical(table)&&(technical(from)||technical(link.table)))return;
      const pairs=link.pairs||[{column:link.column,target:link.target}];
      edges.push({from,to:link.table,pairs:pairs.map(pair=>({left:pair.column,right:pair.target}))});
      edges.push({from:link.table,to:from,pairs:pairs.map(pair=>({left:pair.target,right:pair.column}))});
    }));
    const queue = sources.map(source => ({table:source.table,alias:source.id,path:[]}));
    const seen = new Set(sources.map(source => source.table));
    let route;
    while (queue.length && !route) {
      const current = queue.shift();
      for (const edge of edges.filter(edge => edge.from === current.table)) {
        if (seen.has(edge.to)) continue;
        const next = {table:edge.to,alias:current.alias,path:[...current.path,edge]};
        if (edge.to === table) {route=next;break;}
        seen.add(edge.to);queue.push(next);
      }
    }
    if (!route) {
      const join = {id:nextId(),table,type:'left',auto:true,on:[{left:'',right:''}]};
      query.joins.push(join);
      return {alias:join.id,added:[table],needsMatch:true};
    }
    let alias = route.alias;
    const added = [];
    for (const edge of route.path) {
      const join = {id:nextId(),table:edge.to,type:'left',auto:true,on:edge.pairs.map(pair=>({left:ref(alias,pair.left),right:pair.right}))};
      query.joins.push(join);alias=join.id;added.push(edge.to);
    }
    return {alias,added,needsMatch:false};
  }
  function pruneConnections(query) {
    const used = new Set(['base']);
    const use = reference => {if(reference)used.add(reference.split('.')[0]);};
    query.keys.forEach(use);
    if(query.lineItems?.column)use(query.lineItems.column);
    if (query.keyMode === 'custom') (query.keyFields || []).forEach(field => use(field.column || field.tableAlias));
    query.mappings.filter(field => field.include && ['column','json'].includes(field.method)).forEach(field => use(field.column || field.tableAlias));
    const visit = group => group.children.forEach(rule => rule.children ? visit(rule) : use(rule.column || rule.tableAlias));
    visit(query.filters);
    query.sorts.forEach(sort => use(sort.column || sort.tableAlias));
    query.joins.filter(join => !join.auto).forEach(join => used.add(join.id));
    let size;
    do {size=used.size;query.joins.filter(join => used.has(join.id)).forEach(join => join.on.forEach(pair => use(pair.left)));} while (size!==used.size);
    query.joins = query.joins.filter(join => used.has(join.id));
  }
  return {available,connectTable,pruneConnections};
});
