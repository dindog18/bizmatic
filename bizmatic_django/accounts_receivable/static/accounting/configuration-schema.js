/* Presentation helpers only; destination fields come from the Django model catalog. */
window.BizmaticConfigurationSchema = (() => {
  const aliases = {
    customer_code:'customer_code', customer_name:'customer_name', supplier_code:'supplier_code', supplier_name:'supplier_name',
    customer:'customer_code', supplier:'supplier_code', po_reference_no:'po_number', dr_reference_no:'delivery_no',
    invoice_reference_no:'invoice_no', payment_reference_no:'payment_no', tax_identification_no:'tax_id',
    payment_terms_days:'terms_days', is_active:'active', delivery_status:'status', receipt_status:'status',
    invoice_status:'status', payment_status:'payment_status', item_code:'sku', unit_of_measure:'uom',
    quantity_ordered:'ordered_qty', quantity_invoiced:'billed_qty', quantity_stated:'stated_qty',
    quantity_received:'received_qty', quantity_accepted:'accepted_qty', quantity_rejected:'rejected_qty',
    amount_received:'received_amount', amount_paid:'paid_amount', total_amount:'gross_total', tax_amount:'vat_amount',
  };
  const sourceColumn = field => aliases[field.key] || field.key;
  const transform = field => field.type === 'lookup' ? 'lookup' : /DateTime/.test(field.type) ? 'datetime' : /Date/.test(field.type) ? 'date' : /Decimal|Float/.test(field.type) ? 'decimal' : /Integer/.test(field.type) ? 'integer' : /Boolean/.test(field.type) ? 'boolean' : /JSON/.test(field.type) ? 'json' : 'trim';
  const referenceField = target => target.fields.find(field => /reference_no$/.test(field.key) || /^(customer|supplier)_code$/.test(field.key));
  const requiredFields = target => [...new Set([...target.fields.filter(field=>field.required || field.type==='lookup' || /^(order_date|delivery_date|invoice_date|payment_date|currency|total_amount|amount_received|amount_paid)$/.test(field.key)).map(field=>field.key), referenceField(target)?.key].filter(Boolean))];
  const requiredLineFields = target => target.lineFields.filter(field=>field.required || ['item_code','unit_of_measure','quantity_ordered','quantity_invoiced','quantity_stated','quantity_received','quantity_accepted','unit_price','line_total'].includes(field.key)).map(field=>field.key);
  function blank(target, source='database') {
    return {
      id:null, name:'', description:'', target_entity:target.key, source_type:source, scope:'module',
      connection:'', table:'', columns:'', source_keys:'', line_table:'', line_columns:'', line_joins:'', include_lines:Boolean(target.lineModel),
      field_mappings:{}, line_item_mappings:{}, document_type:'', extraction_context:'', field_instructions:{}, line_field_instructions:{}, relation_lookups:Object.fromEntries(target.fields.filter(info=>info.type==='lookup').map(info=>[info.key,{match_field:info.key+'_code',on_missing:'review'}])), line_item_context:'', sample_text:'',
      encoding_rules:{date_format:'YYYY-MM-DD', decimal_separator:'.', thousands_separator:',', default_currency:'PHP', duplicate_policy:'review', missing_value_policy:'review', required_fields:requiredFields(target),line_required_fields:requiredLineFields(target)},
      assistant_messages:[], assistant_proposal:null, status:'draft', revision:1, submitted_snapshot:null, submitted_at:null,
    };
  }
  function sample(target) {
    const tableName={customer:'customers',supplier:'suppliers',purchase_order:'purchase_orders',delivery_receipt:'delivery_receipts',sales_invoice:'invoices',payment:'payments'}[target.key];
    return {connection:'Demo ERP (sample schema)',table:`public.${tableName}`,source_keys:'id',columns:['id',...new Set(target.fields.map(sourceColumn))].join('\n'),line_table:target.lineModel?`public.${tableName}_lines`:'',line_columns:target.lineModel?['id', 'header_id', ...new Set(target.lineFields.map(sourceColumn))].join('\n'):'',line_joins:target.lineModel?'id=header_id':''};
  }
  function initial(catalog) {
    const account=blank(catalog[0]);Object.assign(account,sample(catalog[0]),{id:1,name:`${catalog[0].label} · ERP mapping`,description:'Sample mapping. Complete the remaining fields and review before submitting.'});
    const first=catalog[0].fields[0];account.field_mappings[first.key]={source:sourceColumn(first),transform:transform(first),default:''};
    const invoice=blank(catalog.find(target=>target.key==='sales_invoice'),'document');
    Object.assign(invoice,{id:2,name:'Sales invoices · Document instructions',document_type:'Sales invoice',extraction_context:'Read the invoice header and totals. Keep invoice and purchase order references separate. Preserve the original reference number; do not invent missing values.',line_item_context:'Read each billed item as a separate line. Exclude subtotal and tax summary rows. Flag ambiguous quantities for review.'});
    return [account,invoice];
  }
  return {sourceColumn,transform,referenceField,requiredFields,requiredLineFields,blank,sample,initial};
})();
