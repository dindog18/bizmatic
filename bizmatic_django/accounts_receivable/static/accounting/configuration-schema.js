/* Presentation helpers only; destination fields come from the Django model catalog. */
window.BizmaticConfigurationSchema = (() => {
  const transform = field => field.type === 'lookup' ? 'lookup' : /DateTime/.test(field.type) ? 'datetime' : /Date/.test(field.type) ? 'date' : /Decimal|Float/.test(field.type) ? 'decimal' : /Integer/.test(field.type) ? 'integer' : /Boolean/.test(field.type) ? 'boolean' : /JSON/.test(field.type) ? 'json' : 'trim';
  const referenceField = target => target.fields.find(field => /reference_no$/.test(field.key) || /^(customer|supplier)_code$/.test(field.key));
  const requiredFields = target => [...new Set([...target.fields.filter(field=>field.required || field.type==='lookup' || /^(order_date|delivery_date|invoice_date|payment_date|currency|total_amount|amount_received|amount_paid)$/.test(field.key)).map(field=>field.key), referenceField(target)?.key].filter(Boolean))];
  const requiredLineFields = target => [];
  function blank(target, source='database') {
    return {
      id:null, name:'', description:'', target_entity:target.key, source_type:source, scope:'module',
      connection:'', table:'', columns:'', source_keys:'', line_table:'', line_columns:'', line_joins:'', include_lines:false,
      field_mappings:{}, line_item_mappings:{}, document_type:'', extraction_context:'', field_instructions:{}, line_field_instructions:{}, relation_lookups:Object.fromEntries(target.fields.filter(info=>info.type==='lookup').map(info=>[info.key,{match_field:info.key+'_code',on_missing:'review'}])), line_item_context:'', sample_text:'',
      encoding_rules:{date_format:'YYYY-MM-DD', decimal_separator:'.', thousands_separator:',', default_currency:'PHP', duplicate_policy:'review', missing_value_policy:'review', required_fields:requiredFields(target),line_required_fields:requiredLineFields(target)},
      assistant_messages:[], assistant_proposal:null, status:'draft', revision:1, submitted_snapshot:null, submitted_at:null,
    };
  }
  return {transform,referenceField,requiredFields,requiredLineFields,blank};
})();
