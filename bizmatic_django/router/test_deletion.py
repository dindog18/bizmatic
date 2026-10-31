"""Confirmed, revision-aware configuration deletion preserves routing history."""
from django.test import Client, TestCase
from django.urls import reverse

from document_extraction.models import Document
from .models import DocumentRoute, LLMRoutingLog, RoutingDestination, RoutingRule


class RoutingDeletionTests(TestCase):
    def setUp(self):
        self.destination = RoutingDestination.objects.create(name="Unused destination", module_name="encoder", target_model="EncoderJob")
        self.rule = RoutingRule.objects.create(name="Unused rule", destination=self.destination, instructions="Synthetic matching rule")

    def delete(self, kind, row, **data):
        return self.client.post(reverse("ROUTER:configuration_delete", args=[kind, row.pk]), {"revision": row.updated_at.isoformat(), "confirmed": True, "delete_associated_rules": kind == "destinations", **data}, content_type="application/json")

    def test_deletion_requires_post_csrf_confirmation_and_current_revision(self):
        url = reverse("ROUTER:configuration_delete", args=["rules", self.rule.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url, {}).status_code, 403)
        self.assertEqual(self.delete("rules", self.rule, confirmed=False).status_code, 400)
        self.assertEqual(self.delete("rules", self.rule, revision="stale").status_code, 409)
        self.assertTrue(RoutingRule.objects.filter(pk=self.rule.pk).exists())
        self.assertEqual(self.delete("unknown", self.rule).status_code, 404)
        self.assertEqual(self.delete("destinations", self.destination, delete_associated_rules=False).status_code, 400)
        self.assertTrue(RoutingRule.objects.filter(pk=self.rule.pk).exists())

    def test_destination_deletion_removes_associated_rules_and_keeps_prior_snapshot(self):
        document = Document.objects.create(file_name="Synthetic", document_type="text", storage_path="/tmp/unused.txt")
        snapshot = [{"rule_no": self.rule.pk, "instructions": self.rule.instructions, "destination_id": self.destination.pk}]
        log = LLMRoutingLog.objects.create(source_document=document, rules_snapshot=snapshot, status="completed")
        response = self.delete("destinations", self.destination)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(RoutingRule.objects.filter(destination=self.destination).exists())
        log.refresh_from_db()
        self.assertEqual(log.rules_snapshot, snapshot)
        self.assertFalse(RoutingDestination.objects.filter(is_deleted=False).exists())
        self.assertTrue(LLMRoutingLog.objects.filter(pk=log.pk).exists())

    def test_destination_deletion_retains_route_history(self):
        self.rule.delete()
        document = Document.objects.create(file_name="Synthetic", document_type="text", storage_path="/tmp/unused.txt")
        log = LLMRoutingLog.objects.create(source_document=document, status="completed")
        route = DocumentRoute.objects.create(routing_log=log, destination=self.destination)
        response = self.delete("destinations", self.destination)
        self.assertEqual(response.status_code, 200)
        self.destination.refresh_from_db()
        self.assertTrue(self.destination.is_deleted)
        self.assertFalse(self.destination.is_active)
        self.assertTrue(DocumentRoute.objects.filter(pk=route.pk).exists())
        response = self.client.get(reverse("ROUTER:document", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        archived = next(row for row in response.context["router_state"]["destinations"] if row["id"] == self.destination.pk)
        self.assertTrue(archived["is_deleted"])
        self.assertEqual(archived["name"], self.destination.name)

    def test_deletion_is_exposed_in_configuration_pages(self):
        for name in ("destinations", "rules"):
            response = self.client.get(reverse("ROUTER:" + name))
            self.assertEqual(response.status_code, 200)
            self.assertIn("delete", response.context["router_config"]["api"])
            self.assertContains(response, "configuration.js?v=routing-encoder-prep-6")
            self.assertContains(response, "Delete opens a confirmation" if name == "destinations" else "Review the rule name")


    def test_deleted_destination_is_hidden_and_cannot_be_enabled_but_target_can_be_recreated(self):
        self.assertEqual(self.delete("destinations", self.destination).status_code, 200)
        state = self.client.get(reverse("ROUTER:destinations")).context["router_state"]
        self.assertNotIn(self.destination.pk, [row["id"] for row in state["destinations"]])
        self.assertEqual(self.client.get(reverse("ROUTER:destination_edit", args=[self.destination.pk])).status_code, 404)
        self.destination.refresh_from_db()
        response = self.client.post(reverse("ROUTER:configuration_toggle", args=["destinations", self.destination.pk]), {"revision": self.destination.updated_at.isoformat(), "is_active": True}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        replacement = RoutingDestination.objects.create(name="Replacement", module_name="encoder", target_model="EncoderJob")
        self.assertNotEqual(replacement.pk, self.destination.pk)

    def test_cascade_rolls_back_if_destination_cannot_be_saved(self):
        from unittest.mock import patch
        with patch.object(RoutingDestination, "save", side_effect=RuntimeError("Synthetic database failure")):
            with self.assertRaises(RuntimeError):
                self.delete("destinations", self.destination)
        self.assertTrue(RoutingRule.objects.filter(pk=self.rule.pk).exists())
        self.destination.refresh_from_db()
        self.assertFalse(self.destination.is_deleted)
