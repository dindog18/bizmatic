/* Synthetic fixtures only. No application data or accounting API is accessed. */
window.BizmaticFinanceDemo = function (mode) {
  const ar = mode === 'ar';
  const names = ar
    ? ['Northstar Retail Inc.', 'Meridian Trading Co.', 'Cedar & Coast Supply', 'Pacific Home Stores', 'Atlas Commercial Corp.', 'Summit Distribution']
    : ['Evergreen Industrial Supply', 'Pacific Packaging Corp.', 'Vertex Office Solutions', 'Harbor Logistics Inc.', 'Cobalt Equipment Co.', 'Lighthouse Materials'];
  const parties = names.map((name, i) => ({
    id: i + 1, reference: `${ar ? 'CUS' : 'SUP'}-${String(i + 1).padStart(4, '0')}`, name,
    contact: ['Alex Rivera', 'Sam Cruz', 'Jamie Santos', 'Morgan Reyes', 'Taylor Lim', 'Robin Tan'][i],
    email: `accounts@${['northstar', 'meridian', 'cedarcoast', 'pacifichome', 'atlas', 'summit'][i]}.example`,
    phone: '+63 2 8555 0100', taxId: '000-000-000-000 (sample)',
    address: ['Makati City', 'Quezon City', 'Pasig City', 'Taguig City', 'Cebu City', 'Davao City'][i] + ', Philippines',
    shippingAddress: 'Receiving warehouse, Metro Manila', terms: [30, 30, 45, 15, 30, 60][i],
    creditLimit: [500000, 300000, 750000, 250000, 500000, 1000000][i],
    status: i === 5 ? 'inactive' : 'active', notes: 'Synthetic account for the interactive accounting preview.',
  }));
  const data = {parties, 'purchase-orders': [], 'delivery-receipts': [], invoices: [], payments: [], reconciliation: [], allocations: []};
  for (let i = 1; i <= 12; i++) {
    const partyId = (i - 1) % 6 + 1;
    const dueDate = ['2026-09-15', '2026-10-10', '2026-10-18', '2026-10-25', '2026-11-05', '2026-11-20'][(i - 1) % 6];
    const invoiceDate = new Date(`${dueDate}T00:00:00Z`);
    invoiceDate.setUTCDate(invoiceDate.getUTCDate() - parties[partyId - 1].terms);
    const source = i % 3 === 0 ? 'database' : 'document';
    const lines = [
      {code: 'PKG-100', description: 'Heavy-duty storage containers', unit: 'pcs', quantity: 20 + i * 2, price: 850, discount: 0, taxRate: 12},
      {code: 'PKG-210', description: 'Protective packaging sets', unit: 'sets', quantity: 40, price: 320, discount: 0, taxRate: 12},
      {code: 'PKG-305', description: 'Warehouse labeling kits', unit: 'sets', quantity: 10, price: 480, discount: 0, taxRate: 12},
    ];
    const subtotal = lines.reduce((total, line) => total + line.quantity * line.price, 0);
    const tax = Math.round(subtotal * 12) / 100;
    const amount = subtotal + tax;
    const common = {id: i, partyId, currency: 'PHP', source, sourceName: `public.${ar ? 'customer' : 'supplier'}_invoices`,
      sourceKey: `{"invoice_id": ${1000 + i}}`, importedAt: '2026-10-20 09:30', textLog: `TXT-DEMO-${i}`, llmLog: `LLM-DEMO-${i}`,
      date: invoiceDate.toISOString().slice(0, 10), lines: structuredClone(lines), subtotal, tax, discount: 0, otherCharges: 0, amount,
      notes: 'Delivery to the main receiving warehouse. All values are sample data.'};
    const po = {...structuredClone(common), reference: `${ar ? 'CPO' : 'PO'}-2026-${String(100 + i)}`, status: i > 10 ? 'draft' : i < 4 ? 'closed' : 'open', expectedDate: '2026-10-25'};
    const receipt = {...structuredClone(common), reference: `${ar ? 'CDR' : 'SDR'}-2026-${String(200 + i)}`, status: i === 2 ? (ar ? 'partially_accepted' : 'partial') : i > 10 ? 'pending' : ar ? 'delivered' : 'accepted',
      receivedBy: 'Jamie Santos', receivedDate: common.date, location: 'Main warehouse, Makati',
      lines: lines.map((line, index) => ({...line, received: line.quantity, accepted: i === 2 && index === 0 ? line.quantity - 2 : line.quantity, rejected: i === 2 && index === 0 ? 2 : 0}))};
    const invoice = {...structuredClone(common), date: invoiceDate.toISOString().slice(0, 10), reference: `${ar ? 'SI' : 'BILL'}-2026-${String(400 + i)}`, dueDate,
      invoiceStatus: i === 12 ? (ar ? 'draft' : 'pending') : !ar && i === 2 ? 'disputed' : 'posted'};
    const payment = {...structuredClone(common), reference: `${ar ? 'RCPT' : 'PAY'}-2026-${String(600 + i)}`, status: i > 9 ? 'pending' : i === 8 ? 'reversed' : 'cleared',
      amount: i % 3 === 0 ? amount : Math.round(amount * .4 * 100) / 100,
      withholding: 0, discountTaken: 0, method: i % 2 ? 'Bank transfer' : 'Check', bankReference: `DEMO-BNK-${800 + i}`, postingDate: common.date,
      clearedAt: i <= 9 && i !== 8 ? '2026-10-20 14:00' : '', reversedAt: i === 8 ? '2026-10-20 15:00' : '', reversalReason: i === 8 ? 'Duplicate sample payment' : ''};
    data['purchase-orders'].push(po);
    data['delivery-receipts'].push(receipt);
    data.invoices.push(invoice);
    data.payments.push(payment);
    if (i <= 9) data.allocations.push({paymentId: i, invoiceId: i, cash: payment.amount, withholding: 0, discount: 0});
    data.reconciliation.push({...structuredClone(common), reference: `${ar ? 'AR' : 'AP'}-REC-${String(i).padStart(4, '0')}`, status: i === 2 ? 'exception' : i > 10 ? 'pending' : i === 10 ? 'partial' : 'matched',
      orderIds: [i], receiptIds: [i], invoiceIds: [i], discrepancy: i === 2 ? 1904 : 0,
      matches: lines.map((line, index) => ({invoiceId: i, invoiceLine: index, orderId: i, orderLine: index, receiptId: i, receiptLine: index, quantity: i === 2 && index === 0 ? line.quantity - 2 : line.quantity, status: i > 10 ? 'pending' : i === 2 && index === 0 ? 'exception' : 'matched'}))});
  }
  data.payments.push({...structuredClone(data.payments[0]), id: 13, reference: `${ar ? 'RCPT' : 'PAY'}-2026-613`, status: 'cleared', amount: 30000});
  for (const [kind, table] of [['purchase-orders', 'purchase_orders'], ['delivery-receipts', 'delivery_receipts'], ['invoices', 'invoices'], ['payments', 'payments']]) {
    for (const record of data[kind]) {
      record.sourceName = record.source === 'database' ? `public.${ar ? 'customer' : 'supplier'}_${table}` : record.source === 'document' ? `${record.reference}.pdf` : '';
    }
  }
  return data;
};
