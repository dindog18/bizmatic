"""MVP accounting integration checks use a disposable DB and mocked providers."""

import json
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import Client, TestCase

from document_extraction.models import Document, DocExtractionLog
from router.models import RoutingDestination, RoutingRule, LLMRoutingLog, DocumentRoute
from router.services.handoff import process
from accounts_receivable.services import configuration, pages, records, imports
from accounts_receivable.services.catalog import model, party_key, revision
from accounts_receivable.services.configuration import snapshot


class BackendTests(TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {f"{prefix}_{key}": value for prefix in ("ACCOUNTS_PAYABLE", "ACCOUNTS_RECEIVABLE", "CONFIG_ASSISTANT")
                                                for key, value in {"LLM_PROVIDER": "ollama", "OLLAMA_MODEL": "test-accounting"}.items()})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.provider = AsyncMock()
        self.mock = patch("accounts_receivable.services.llm.invoke_with_llm", self.provider)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_modules_use_independent_llm_settings(self):
        from accounts_receivable.services.llm import run

        settings = {
            "ACCOUNTS_PAYABLE_LLM_PROVIDER": "openai",
            "ACCOUNTS_PAYABLE_OPENAI_MODEL": "ap-model",
            "ACCOUNTS_PAYABLE_MAX_OUTPUT_TOKENS": "500",
            "ACCOUNTS_PAYABLE_LLM_TIMEOUT_SECONDS": "45",
            "ACCOUNTS_RECEIVABLE_LLM_PROVIDER": "ollama",
            "ACCOUNTS_RECEIVABLE_OLLAMA_MODEL": "ar-model",
            "ACCOUNTS_RECEIVABLE_MAX_OUTPUT_TOKENS": "900",
            "ACCOUNTS_RECEIVABLE_LLM_TIMEOUT_SECONDS": "75",
        }
        with patch.dict(os.environ, settings):
            self.provider.return_value = {"choices": [{"message": {"content": "{}"}}]}
            ap_log, _ = run("ap", self.config("ap"), "extraction", "Configure", {})
            self.assertEqual(ap_log.model_name, "ap-model")
            self.assertEqual(self.provider.call_args.kwargs, {"config_prefix": "ACCOUNTS_PAYABLE", "timeout": 45})
            self.assertEqual(self.provider.call_args.args[1]["max_tokens"], 500)

            self.respond({})
            ar_log, _ = run("ar", self.config("ar"), "extraction", "Configure", {})
            self.assertEqual(ar_log.model_name, "ar-model")
            self.assertEqual(self.provider.call_args.kwargs, {"config_prefix": "ACCOUNTS_RECEIVABLE", "timeout": 75})
            self.assertEqual(self.provider.call_args.args[1]["options"]["num_predict"], 900)

    def test_both_assistants_use_dedicated_provider_and_log_in_their_module(self):
        settings = {"CONFIG_ASSISTANT_LLM_PROVIDER": "openai",
                    "CONFIG_ASSISTANT_OPENAI_MODEL": "assistant-model",
                    "CONFIG_ASSISTANT_MAX_OUTPUT_TOKENS": "600",
                    "CONFIG_ASSISTANT_LLM_TIMEOUT_SECONDS": "35"}
        with patch.dict(os.environ, settings):
            for mode, slug in [("ap", "accounts-payable"), ("ar", "accounts-receivable")]:
                row = self.config(mode)
                self.provider.return_value = {"choices": [{"message": {"content": json.dumps({"message": "Review this suggestion", "changes": []})}}]}
                response = self.client.post(f"/{slug}/api/assistant/{row.pk}/",
                                            {"revision": row.revision, "message": "Help configure this"}, content_type="application/json")
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(self.provider.call_args.args[0], "openai")
                self.assertEqual(self.provider.call_args.args[1]["max_tokens"], 600)
                self.assertEqual(self.provider.call_args.kwargs, {"config_prefix": "CONFIG_ASSISTANT", "timeout": 35})
                log = model(mode, "LLMExtractionLog").objects.get()
                self.assertEqual((log.provider, log.model_name, log.purpose, log.status),
                                 ("openai", "assistant-model", "configuration", "completed"))
                row.refresh_from_db()
                self.assertEqual(row.extraction_context, "Read labeled fields")

    def test_missing_assistant_model_does_not_use_module_extraction_model(self):
        from accounts_receivable.services.llm import run
        with patch.dict(os.environ, {"CONFIG_ASSISTANT_LLM_PROVIDER": "ollama", "CONFIG_ASSISTANT_OLLAMA_MODEL": ""}):
            log, result = run("ap", self.config("ap"), "configuration", "Configure", {})
        self.assertIsNone(result)
        self.assertEqual(log.status, "failed")
        self.assertIn("CONFIG_ASSISTANT", log.error_message)
        self.assertTrue(log.request_payload["messages"])
        self.provider.assert_not_called()

    def test_assistant_logs_request_response_usage_and_immutable_snapshot(self):
        row = self.config()
        proposal = {"message": "Review the context", "changes": []}
        self.respond(proposal)
        original_response = self.provider.return_value.copy()
        with self.assertLogs("config_assistant", level="INFO") as terminal:
            response = self.client.post(f"/accounts-receivable/api/assistant/{row.pk}/",
                {"revision": row.revision, "message": "Sensitive input for this request"}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        log = model("ar", "LLMExtractionLog").objects.get(pk=response.json()["llm_log_no"])
        self.assertEqual(log.status, "completed")
        self.assertEqual(log.configuration_revision, row.revision)
        self.assertEqual(log.response_payload, original_response)
        self.assertEqual(json.loads(log.markdown_text), proposal)
        self.assertEqual((log.input_tokens, log.output_tokens), (20, 30))
        self.assertGreaterEqual(log.processing_time_ms, 0)
        request = json.loads(log.request_payload["messages"][-1]["content"])
        self.assertEqual(request["message"], "Sensitive input for this request")
        self.assertEqual(request["configuration"], log.configuration_snapshot)
        self.assertNotIn("Sensitive input", " ".join(terminal.output))
        row.name = "Changed later"
        row.save()
        log.refresh_from_db()
        self.assertEqual(log.configuration_snapshot["name"], "Invoices")
        page = self.client.get(f"/accounts-receivable/llm-logs/{log.pk}/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["finance_state"]["logs"][0]["request_payload"], log.request_payload)

    def test_failed_assistant_proposals_have_accessible_logs_in_both_modules(self):
        for mode, slug in [("ap", "accounts-payable"), ("ar", "accounts-receivable")]:
            row = self.config(mode)
            self.respond({"message": "Invalid", "changes": [{"path": "unsupported", "after": "value"}]})
            response = self.client.post(f"/{slug}/api/assistant/{row.pk}/",
                {"revision": row.revision, "message": "Propose fields"}, content_type="application/json")
            self.assertEqual(response.status_code, 400)
            log = model(mode, "LLMExtractionLog").objects.get(pk=response.json()["llm_log_no"])
            self.assertEqual(log.status, "failed")
            self.assertIn("unsupported field", log.error_message)
            self.assertEqual(log.input_tokens, 20)
            self.assertTrue(log.response_payload)
            row.refresh_from_db()
            self.assertEqual(row.assistant_messages, [])
            self.assertEqual(row.revision, 1)
            self.assertEqual(self.client.get(f"/{slug}/llm-logs/{log.pk}/").status_code, 200)

    def test_assistant_save_failure_rolls_back_proposal_and_fails_log(self):
        row = self.config()
        self.respond({"message": "Valid response", "changes": []})
        original_save = type(row).save

        def fail_proposal_save(record, *args, **kwargs):
            if "assistant_messages" in kwargs.get("update_fields", []):
                raise RuntimeError("Private database details")
            return original_save(record, *args, **kwargs)

        with patch.object(type(row), "save", fail_proposal_save):
            response = self.client.post(f"/accounts-receivable/api/assistant/{row.pk}/",
                {"revision": row.revision, "message": "Help"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        log = model("ar", "LLMExtractionLog").objects.get(pk=response.json()["llm_log_no"])
        self.assertEqual(log.status, "failed")
        self.assertNotIn("Private database", log.error_message)
        row.refresh_from_db()
        self.assertEqual(row.assistant_messages, [])
        self.assertEqual(row.revision, 1)

    def config(self, mode="ar", target="sales_invoice"):
        key = party_key(mode)
        data = {"name": "Invoices", "description": "", "target_entity": target, "source_type": "document", key: None,
                "document_type": "Invoice", "extraction_context": "Read labeled fields", "line_item_context": "Read item rows",
                "encoding_rules": {"required_fields": [], "line_required_fields": [], "default_currency": "PHP", "duplicate_policy": "review"},
                "relation_lookups": {key: {"match_field": key+"_code", "on_missing": "review"}},
                "source_key_fields": [], "field_mappings": {}, "line_item_mappings": {}, "line_join_fields": [], "field_instructions": {}, "line_field_instructions": {}}
        return configuration.save(mode, data, submit=True)

    def route(self, mode="ar", document=None):
        if document is None:
            document = Document.objects.create(file_name="Invoice.txt", storage_path="/tmp/accounting-test.txt", document_type="text", review_status="approved", processing_status="completed")
        text = DocExtractionLog.objects.create(fk_document_no=document, markdown_text="Invoice INV-1 to C1, total PHP 100, 1 item at 100.")
        destination, _ = RoutingDestination.objects.get_or_create(module_name=model(mode, "sales_invoice")._meta.app_label, target_model=model(mode, "sales_invoice").__name__, defaults={"name": mode+" invoices"})
        log = LLMRoutingLog.objects.create(source_document=document, source_text_log=text, input_text=text.markdown_text, status="completed", source_revision=document.updated_at.isoformat())
        return DocumentRoute.objects.create(routing_log=log, destination=destination, review_status="approved")

    def account(self, mode="ar", code="C1"):
        key = party_key(mode)
        return model(mode, key).objects.create(**{key+"_code": code, key+"_name": "Account " + code})

    def output(self, mode="ar", **changes):
        record = {party_key(mode): "C1", "invoice_reference_no": "INV-1", "invoice_date": "2026-10-22", "due_date": "2026-11-22", "currency": "PHP", "subtotal": "100", "total_amount": "100", "invoice_status": "posted"}
        record.update(changes)
        return {"record": record, "lines": [{"line_no": 1, "item_code": "ITEM", "unit_of_measure": "pc", "quantity_invoiced": "1", "unit_price": "100", "line_total": "100"}], "issues": []}

    def respond(self, output):
        self.provider.return_value = {"message": {"content": json.dumps(output)}, "prompt_eval_count": 20, "eval_count": 30}

    def test_both_modules_save_records_lines_logs_and_retry_without_duplicates(self):
        for mode in ("ar", "ap"):
            self.account(mode)
            config = self.config(mode)
            route = self.route(mode)
            self.respond(self.output(mode))
            done = process(route.pk)
            self.assertEqual(done.processing_status, "completed", done.processing_error)
            invoice = model(mode, "sales_invoice").objects.get()
            self.assertEqual(invoice.lines.count(), 1)
            self.assertEqual(invoice.source_document_id, route.routing_log.source_document_id)
            log = model(mode, "LLMExtractionLog").objects.get()
            self.assertEqual(log.status, "completed")
            self.assertEqual(log.sales_invoice_id, invoice.pk)
            self.assertEqual(log.configuration_snapshot["revision"], config.revision)
            count = self.provider.call_count
            process(route.pk)
            self.assertEqual(self.provider.call_count, count)
            self.assertEqual(model(mode, "sales_invoice").objects.count(), 1)

    def test_rerouting_same_source_cannot_duplicate_an_invoice(self):
        self.account();self.config();route = self.route();self.respond(self.output())
        self.assertEqual(process(route.pk).processing_status, "completed")
        another = self.route(document=route.routing_log.source_document)
        failed = process(another.pk)
        self.assertEqual(failed.processing_status, "failed")
        self.assertIn("already created", failed.processing_error)
        self.assertEqual(model("ar", "sales_invoice").objects.count(), 1)

    def test_deleted_records_allow_reextraction_but_live_records_still_block_duplicates(self):
        for mode in ('ap', 'ar'):
            self.account(mode)
            key = party_key(mode)
            for target, resource, output in [
                ('sales_invoice', 'invoices', self.output(mode)),
                ('purchase_order', 'purchase-orders', {'record': {key: 'C1', 'po_reference_no': 'PO-1',
                    'order_date': '2026-10-22', 'currency': 'PHP', 'subtotal': '100', 'total_amount': '100'},
                    'lines': [{'line_no': 1, 'quantity_ordered': '1', 'unit_price': '100', 'line_total': '100'}], 'issues': []}),
                ('delivery_receipt', 'delivery-receipts', {'record': {key: 'C1', 'dr_reference_no': 'DR-1',
                    'delivery_date': '2026-10-22'}, 'lines': [], 'issues': []}),
                ('payment', 'payments', {'record': {key: 'C1', 'payment_reference_no': 'PAY-1',
                    'payment_date': '2026-10-22', 'currency': 'PHP',
                    'amount_paid' if mode == 'ap' else 'amount_received': '100'}, 'lines': [], 'issues': []}),
            ]:
                with self.subTest(mode=mode, target=target):
                    self.config(mode, target)
                    route = self.route(mode)
                    destination, _ = RoutingDestination.objects.get_or_create(
                        module_name=model(mode, target)._meta.app_label, target_model=model(mode, target).__name__,
                        defaults={'name': mode+target})
                    route.destination = destination
                    route.save()
                    self.respond(output)
                    done = process(route.pk)
                    self.assertEqual(done.processing_status, 'completed', done.processing_error)
                    original = model(mode, target).objects.get()
                    old_log = model(mode, 'LLMExtractionLog').objects.get(routing_route=route)
                    payload = {'revision': pages.document(original, target, mode)['revision'], 'confirmed': True}
                    records.delete_document(mode, resource, original.pk, payload)
                    old_log.refresh_from_db()
                    self.assertEqual(old_log.status, 'completed')
                    self.assertIsNone(getattr(old_log, target+'_id'))
                    another = self.route(mode, document=route.routing_log.source_document)
                    another.destination = destination
                    another.save()
                    recreated = process(another.pk)
                    self.assertEqual(recreated.processing_status, 'completed', recreated.processing_error)
                    self.assertEqual(model(mode, target).objects.count(), 1)
                    duplicate = self.route(mode, document=route.routing_log.source_document)
                    duplicate.destination = destination
                    duplicate.save()
                    blocked = process(duplicate.pk)
                    self.assertEqual(blocked.processing_status, 'failed')
                    self.assertIn('already created', blocked.processing_error)
                    self.assertEqual(model(mode, target).objects.count(), 1)

    def test_invalid_lines_roll_back_header_but_keep_attempt(self):
        self.account();self.config();route = self.route()
        output = self.output();output["lines"].append({**output["lines"][0], "quantity_invoiced": "-2"})
        self.respond(output)
        failed = process(route.pk)
        self.assertEqual(failed.processing_status, "failed")
        self.assertEqual(model("ar", "sales_invoice").objects.count(), 0)
        self.assertEqual(model("ar", "LLMExtractionLog").objects.get().status, "failed")

    def test_unknown_account_and_issues_do_not_create_records(self):
        self.config();route=self.route();self.respond(self.output())
        self.assertEqual(process(route.pk).processing_status, "failed")
        self.assertEqual(model("ar", "sales_invoice").objects.count(), 0)
        self.respond({**self.output(), "issues": ["Unreadable total"]})
        self.assertIn("Unreadable total", process(route.pk).processing_error)

    def test_unapproved_or_stale_source_is_blocked_before_provider(self):
        self.config();route=self.route();route.review_status="pending";route.save()
        with self.assertRaises(ValidationError):process(route.pk)
        route.review_status="approved";route.save()
        doc=route.routing_log.source_document;doc.file_name="changed";doc.save()
        with self.assertRaises(ValidationError):process(route.pk)
        self.provider.assert_not_called()

    def test_ambiguous_configuration_needs_explicit_selection(self):
        self.account();first=self.config();self.config();route=self.route();self.respond(self.output())
        self.assertEqual(process(route.pk).processing_status,"failed")
        self.provider.assert_not_called()
        self.assertEqual(process(route.pk, first.pk).processing_status,"completed")

    def test_edit_configuration_invalidates_submission_and_stale_edits(self):
        row=self.config();data=snapshot(row);data["name"]="New instructions"
        edited=configuration.save("ar",data,row.pk)
        self.assertEqual(edited.status,"draft")
        self.assertEqual(edited.submitted_snapshot["configuration"]["name"],"Invoices")
        with self.assertRaises(ValidationError):configuration.save("ar",data,row.pk)

    def test_assistant_proposal_is_logged_without_submitting_or_creating_records(self):
        row=self.config();self.respond({"message":"Proposed clearer context", "changes":[{"path":"extraction_context","after":"Read invoice label"}]})
        response=self.client.post(f"/accounts-receivable/api/assistant/{row.pk}/", {"revision":row.revision,"message":"Improve instructions"},content_type="application/json")
        self.assertEqual(response.status_code,200,response.content)
        row.refresh_from_db()
        self.assertEqual(row.extraction_context,"Read labeled fields")
        self.assertEqual(model("ar","sales_invoice").objects.count(),0)
        self.assertEqual(model("ar","LLMExtractionLog").objects.get().purpose,"configuration")

    def test_json_endpoints_require_csrf_and_persist_account_edits(self):
        response=Client(enforce_csrf_checks=True).post('/accounts-receivable/api/parties/', {},content_type='application/json')
        self.assertEqual(response.status_code,403)
        data={"reference":"C1","name":"Customer","status":"active","terms":30,"creditLimit":"1000"}
        response=self.client.post('/accounts-receivable/api/parties/',data,content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        row=model('ar','customer').objects.get();data.update(name='Changed',revision=revision(row))
        self.assertEqual(self.client.post(f'/accounts-receivable/api/parties/{row.pk}/',data,content_type='application/json').status_code,200)
        self.assertEqual(self.client.post(f'/accounts-receivable/api/parties/{row.pk}/',data,content_type='application/json').status_code,409)

    def test_all_pages_render_from_saved_data_and_have_no_fixtures(self):
        for mode,base in [('ar','accounts-receivable'),('ap','accounts-payable')]:
            self.account(mode);self.config(mode);route=self.route(mode);self.respond(self.output(mode));process(route.pk)
            for path in ['', 'configuration/', 'configuration/1/', 'llm-logs/', 'invoices/', 'invoices/1/', 'aging/']:
                response=self.client.get(f'/{base}/{path}')
                self.assertEqual(response.status_code,200,path)
                self.assertNotContains(response,'accounting/demo-data.js')
            data=pages.workspace_state(mode,'overview')
            self.assertEqual(data['invoices'][0]['balance'],100)

    def test_failed_allocation_preserves_previous_allocations(self):
        account=self.account();self.config();route=self.route();self.respond(self.output());process(route.pk)
        invoice=model('ar','sales_invoice').objects.get()
        payment=model('ar','payment').objects.create(customer=account,payment_reference_no='PAY1',currency='PHP',amount_received='100',payment_status='cleared')
        payment.refresh_from_db()
        records.save_allocations('ar',payment.pk,{'revision':revision(payment,records.allocations(payment)),'allocations':[{'invoiceId':invoice.pk,'cash':'40'}]})
        invoice.refresh_from_db();self.assertEqual(invoice.outstanding_balance,60)
        with self.assertRaises(ValidationError):records.save_allocations('ar',payment.pk,{'revision':revision(payment,records.allocations(payment)),'allocations':[{'invoiceId':invoice.pk,'cash':'200'}]})
        self.assertEqual(payment.invoice_allocations.get().cash_amount,40)

    def test_provider_failure_and_truncation_are_saved(self):
        self.account();self.config();route=self.route()
        self.provider.side_effect=RuntimeError('provider unavailable')
        self.assertEqual(process(route.pk).processing_status,'failed')
        self.provider.side_effect=None
        self.respond(self.output());self.provider.return_value['done_reason']='length'
        self.assertIn('output limit',process(route.pk).processing_error)
        self.assertEqual(model('ar','sales_invoice').objects.count(),0)

    def test_database_import_is_bounded_mapped_and_idempotent(self):
        from db_extraction.models import DatabaseSource, ExtractionRun, DatabaseSchema, DatabaseTable, DatabaseColumn
        source=DatabaseSource.objects.create(name='Test source',host='localhost',database_name='test',username='reader',password='')
        run=ExtractionRun.objects.create(source=source,status='completed')
        schema=DatabaseSchema.objects.create(run=run,name='public')
        table=DatabaseTable.objects.create(schema=schema,name='customers')
        for index,name in enumerate(['id','code','name'],1):DatabaseColumn.objects.create(table=table,name=name,ordinal_position=index,formatted_type='text')
        data={'name':'Customer imports','target_entity':'customer','source_type':'database','database_source':source.pk,'source_table':table.pk,'source_key_fields':['id'],
              'field_mappings':{'customer_code':{'source':'code','transform':'trim'},'customer_name':{'source':'name','transform':'trim'}},
              'encoding_rules':{'duplicate_policy':'skip'},'line_join_fields':[]}
        config=configuration.save('ar',data,submit=True)
        payload={'request_id':str(uuid4()),'revision':config.revision,'limit':10,'offset':0}
        with patch('accounts_receivable.services.imports.read_rows',return_value=[({'id':1,'code':' C1 ','name':'Customer'},[])]) as read:
            first=imports.execute('ar',config.pk,payload)
            self.assertEqual(first.status,'completed',first.result)
            self.assertEqual(model('ar','customer').objects.get().customer_code,'C1')
            repeated=imports.execute('ar',config.pk,payload)
            self.assertEqual(first.pk,repeated.pk)
            self.assertEqual(read.call_count,1)
            second=imports.execute('ar',config.pk,{**payload,'request_id':str(uuid4())})
            self.assertEqual(second.result['skipped'],[{'id':1}])
            self.assertEqual(len(pages.workspace_state('ar','configuration')['import_runs']),2)
        bad={**snapshot(config),'field_mappings':{'customer_code':{'source':'unknown'}}}
        with self.assertRaises(ValidationError):configuration.save('ar',bad,config.pk,submit=True)

    def test_case_and_matches_use_real_line_ids_and_server_validation(self):
        account=self.account();self.config();route=self.route();self.respond(self.output());process(route.pk)
        invoice=model('ar','sales_invoice').objects.get()
        order=model('ar','purchase_order').objects.create(customer=account,po_reference_no='PO1',order_date='2026-10-22',currency='PHP',subtotal='100',total_amount='100',status='open')
        receipt=model('ar','delivery_receipt').objects.create(customer=account,dr_reference_no='DR1',delivery_date='2026-10-22',delivery_status='delivered')
        order_line=model('ar','CustomerPurchaseOrderLine').objects.create(purchase_order=order,line_no=1,item_code='ITEM',unit_of_measure='pc',quantity_ordered='1',unit_price='100',line_total='100')
        receipt_line=model('ar','CompanyDeliveryReceiptLine').objects.create(delivery_receipt=receipt,line_no=1,item_code='ITEM',unit_of_measure='pc',quantity_stated='1',quantity_received='1',quantity_accepted='1')
        case=records.save_case('ar',{'partyId':account.pk,'date':'2026-10-22','currency':'PHP','orderIds':[order.pk],'receiptIds':[receipt.pk],'invoiceIds':[invoice.pk]})
        case.refresh_from_db()
        payload={'revision':revision(case,[records.case_membership(case),records.matches(case)]),'matches':[{'invoiceLineId':invoice.lines.get().pk,'orderLineId':order_line.pk,'receiptLineId':receipt_line.pk,'quantity':'1'}]}
        saved=records.save_matches('ar',case.pk,payload)
        self.assertEqual(saved.reconciliation_status,'matched')
        with self.assertRaises(ValidationError):records.save_matches('ar',case.pk,payload)

    def test_route_approval_endpoint_processes_and_links_accounting_record(self):
        self.account();self.config();route=self.route();route.review_status='pending';route.save()
        self.respond(self.output())
        response=self.client.post(f'/router/api/routes/{route.pk}/review/',{'revision':route.updated_at.isoformat(),'decision':'approved','review_notes':'Checked'},content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        result=response.json()['record']
        self.assertEqual(result['processing_status'],'completed')
        self.assertEqual(result['record_url'],'/accounts-receivable/invoices/1/')
        self.assertIn('/llm-logs/',result['history_url'])

    def route_request(self, modes=("ap", "ar")):
        document = Document.objects.create(file_name="Routed.txt", storage_path="/tmp/routed.txt",
                                          document_type="text", review_status="approved", processing_status="completed")
        DocExtractionLog.objects.create(fk_document_no=document, markdown_text="Invoice INV-1 for C1, total PHP 100.")
        destinations = []
        for mode in modes:
            destination = RoutingDestination.objects.create(name=mode + " invoices", module_name=model(mode, "sales_invoice")._meta.app_label,
                                                            target_model=model(mode, "sales_invoice").__name__)
            RoutingRule.objects.create(name=mode, destination=destination, instructions="Match this invoice.")
            destinations.append(destination)
        payload = {"request_id": str(uuid4()), "document_ids": [document.pk],
                   "revisions": {str(document.pk): document.updated_at.isoformat()}}
        response = {"message": {"content": json.dumps({"routes": [
            {"destination_id": destination.pk, "reason": "Matches the rule.", "confidence": 0.95}
            for destination in destinations]})}}
        return payload, response

    def test_routing_automatically_extracts_both_modules_and_replay_is_idempotent(self):
        for mode in ("ap", "ar"):
            self.account(mode)
            self.config(mode)
        payload, routing_response = self.route_request()
        self.provider.side_effect = lambda *args, **kwargs: {"message": {"content": json.dumps(
            self.output("ap" if kwargs["config_prefix"] == "ACCOUNTS_PAYABLE" else "ar"))}}
        with patch.dict(os.environ, {"ROUTER_LLM_PROVIDER": "ollama", "ROUTER_OLLAMA_MODEL": "routing-test"}), \
                patch("router.services.llm.invoke", new_callable=AsyncMock, return_value=routing_response) as routing_provider:
            response = self.client.post("/router/execute/", payload, content_type="application/json")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["accounting"]["completed"], 2)
            self.assertEqual(set(DocumentRoute.objects.values_list("processing_status", flat=True)), {"completed"})
            # Machine execution must not masquerade as a human review.
            self.assertEqual(set(DocumentRoute.objects.values_list("review_status", flat=True)), {"pending"})
            for mode in ("ap", "ar"):
                invoice = model(mode, "sales_invoice").objects.get()
                self.assertEqual(invoice.lines.count(), 1)
                log = model(mode, "LLMExtractionLog").objects.get()
                self.assertEqual(log.status, "completed")
                self.assertEqual(log.sales_invoice_id, invoice.pk)
                self.assertEqual(log.fk_document_no_id, payload["document_ids"][0])
            replay = self.client.post("/router/execute/", payload, content_type="application/json")
            self.assertEqual(replay.status_code, 200, replay.content)
            routing_provider.assert_awaited_once()
            self.assertEqual(self.provider.await_count, 2)
            self.assertEqual(DocumentRoute.objects.count(), 2)

    def test_failed_automatic_extraction_keeps_other_destination_and_can_be_retried(self):
        for mode in ("ap", "ar"):
            self.account(mode)
            self.config(mode)
        payload, routing_response = self.route_request()
        self.provider.side_effect = [RuntimeError("Provider unavailable"), {"message": {"content": json.dumps(self.output())}}]
        with patch.dict(os.environ, {"ROUTER_LLM_PROVIDER": "ollama", "ROUTER_OLLAMA_MODEL": "routing-test"}), \
                patch("router.services.llm.invoke", new_callable=AsyncMock, return_value=routing_response):
            response = self.client.post("/router/execute/", payload, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["accounting"], {"completed": 1, "failed": 1, "pending": 0, "processing": 0})
        self.assertEqual(LLMRoutingLog.objects.get().status, "completed")
        failed = DocumentRoute.objects.get(processing_status="failed")
        self.assertTrue(failed.processing_error)
        self.assertEqual(model("ar", "sales_invoice").objects.count(), 1)
        self.assertEqual(model("ap", "sales_invoice").objects.count(), 0)
        self.provider.side_effect = None
        self.respond(self.output("ap"))
        retry = self.client.post(f"/router/api/routes/{failed.pk}/review/", {
            "decision": "approved", "revision": failed.updated_at.isoformat()}, content_type="application/json")
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(retry.json()["record"]["processing_status"], "completed")

    def test_missing_automatic_configuration_is_reported_without_calling_accounting_provider(self):
        payload, routing_response = self.route_request(("ar",))
        with patch.dict(os.environ, {"ROUTER_LLM_PROVIDER": "ollama", "ROUTER_OLLAMA_MODEL": "routing-test"}), \
                patch("router.services.llm.invoke", new_callable=AsyncMock, return_value=routing_response):
            response = self.client.post("/router/execute/", payload, content_type="application/json")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["accounting"]["failed"], 1)
            self.assertIn("configuration", DocumentRoute.objects.get().processing_error)
            self.client.post("/router/execute/", payload, content_type="application/json")
        self.provider.assert_not_awaited()
        self.assertFalse(model("ar", "LLMExtractionLog").objects.exists())

    def test_automatic_processing_still_blocks_rejected_and_stale_routes(self):
        self.config()
        route = self.route()
        route.review_status = "rejected"
        route.save()
        with self.assertRaises(ValidationError):
            process(route.pk, automatic=True)
        route.review_status = "pending"
        route.save()
        document = route.routing_log.source_document
        document.file_name = "Changed.txt"
        document.save()
        from router.services.handoff import process_matches
        process_matches(route.routing_log_id)
        route.refresh_from_db()
        self.assertEqual(route.processing_status, "failed")
        self.assertIn("changed", route.processing_error)
        self.provider.assert_not_awaited()

    def test_explicit_retry_resumes_failed_pending_review_without_reclassifying(self):
        for mode in ("ap", "ar"):
            self.account(mode)
            first = self.config(mode)
            self.config(mode)  # Retry can choose among submitted configurations.
            route = self.route(mode)
            route.review_status = "pending"
            route.processing_status = "failed"
            route.processing_error = "Previous provider error"
            route.save()
            self.respond(self.output(mode))
            url = f"/router/api/routes/{route.pk}/process/"
            payload = {"revision": route.updated_at.isoformat(), "configuration_id": first.pk}
            with patch("router.services.llm.invoke", new_callable=AsyncMock) as classifier:
                response = self.client.post(url, payload, content_type="application/json")
                self.assertEqual(response.status_code, 200, response.content)
                result = response.json()["record"]
                self.assertEqual(result["processing_status"], "completed", result["processing_error"])
                self.assertEqual(result["review_status"], "pending")
                self.assertTrue(result["record_url"])
                calls = self.provider.await_count
                replay = self.client.post(url, payload, content_type="application/json")
                self.assertEqual(replay.status_code, 200, replay.content)
                self.assertEqual(self.provider.await_count, calls)
                classifier.assert_not_awaited()
            self.assertEqual(model(mode, "sales_invoice").objects.count(), 1)

    def test_explicit_retry_rejects_stale_revisions_rejected_and_superseded_routes(self):
        self.config()
        route = self.route()
        url = f"/router/api/routes/{route.pk}/process/"
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {}, content_type="application/json").status_code, 400)
        payload = {"revision": route.updated_at.isoformat()}
        route.review_notes = "Changed in another tab"
        route.save()
        self.assertEqual(self.client.post(url, payload, content_type="application/json").status_code, 409)
        route.review_status = "rejected"
        route.save()
        payload["revision"] = route.updated_at.isoformat()
        self.assertEqual(self.client.post(url, payload, content_type="application/json").status_code, 400)
        route.review_status = "pending"
        route.save()
        self.route(document=route.routing_log.source_document)
        payload["revision"] = route.updated_at.isoformat()
        self.assertEqual(self.client.post(url, payload, content_type="application/json").status_code, 400)
        self.provider.assert_not_awaited()

    def test_rerouting_waits_for_accounting_extraction_to_finish(self):
        payload, routing_response = self.route_request(("ar",))
        document = Document.objects.get(pk=payload["document_ids"][0])
        route = self.route(document=document)
        route.processing_status = "processing"
        route.save()
        with patch.dict(os.environ, {"ROUTER_LLM_PROVIDER": "ollama", "ROUTER_OLLAMA_MODEL": "routing-test"}), \
                patch("router.services.llm.invoke", new_callable=AsyncMock, return_value=routing_response) as classifier:
            response = self.client.post("/router/execute/", payload, content_type="application/json")
            self.assertEqual(response.status_code, 400, response.content)
            self.assertIn("AP/AR extraction", response.json()["message"])
            classifier.assert_not_awaited()
        self.assertEqual(LLMRoutingLog.objects.count(), 1)
        self.provider.assert_not_awaited()

    def test_all_supported_targets_create_the_correct_module_record(self):
        for mode in ('ap','ar'):
            self.account(mode)
            key=party_key(mode)
            targets={
                key:({'%s_code'%key:'C2','%s_name'%key:'New account'},[]),
                'purchase_order':({key:'C1','po_reference_no':'PO-2','order_date':'2026-10-22','currency':'PHP','subtotal':'100','total_amount':'100'},[{'line_no':1,'item_code':'ITEM','quantity_ordered':'1','unit_price':'100','line_total':'100'}]),
                'delivery_receipt':({key:'C1','dr_reference_no':'DR-2','delivery_date':'2026-10-22'},[{'line_no':1,'item_code':'ITEM','quantity_stated':'1','quantity_received':'1','quantity_accepted':'1'}]),
                'payment':({key:'C1','payment_reference_no':'PAY-2','payment_date':'2026-10-22','currency':'PHP',('amount_paid' if mode=='ap' else 'amount_received'):'100'},[]),
            }
            for target,(values,lines) in targets.items():
                config=self.config(mode,target)
                route=self.route(mode)
                destination=RoutingDestination.objects.create(name=mode+target,module_name=model(mode,target)._meta.app_label,target_model=model(mode,target).__name__)
                route.destination=destination;route.save()
                self.respond({'record':values,'lines':lines,'issues':[]})
                result=process(route.pk,config.pk)
                self.assertEqual(result.processing_status,'completed',result.processing_error)
                log=model(mode,'LLMExtractionLog').objects.get(routing_route=route)
                self.assertIsNotNone(getattr(log,target+'_id'))
                pages.workspace_state(mode,'overview')

    def test_totals_and_system_fields_cannot_be_invented_or_overridden(self):
        self.account();self.config();route=self.route()
        self.respond(self.output(total_amount='999'))
        self.assertIn('totals',process(route.pk).processing_error)
        self.respond(self.output(source_document=123))
        self.assertIn('system-managed',process(route.pk).processing_error)
        self.assertFalse(model('ar','sales_invoice').objects.exists())
