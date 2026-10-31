from django.test import SimpleTestCase

from .services.presentation import message_html, review


class DataReviewTests(SimpleTestCase):
    def test_empty_payload_has_no_displayed_values(self):
        self.assertEqual(review({}, {})["values"], [])

    def test_nested_required_fields_and_false_values_are_distinguished(self):
        schema = {"type": "object", "properties": {"order": {"$ref": "#/$defs/order"}}, "$defs": {"order": {"type": "object", "properties": {"direct_delivery": {"type": "boolean"}}, "required": ["direct_delivery", "manager_id"]}}}
        result = review({"order": {"direct_delivery": False}}, schema)
        self.assertEqual(result["values"][0]["value"], "No")
        self.assertEqual(result["missing"], [{"label": "Order › Manager id", "path": "order.manager_id"}])
        self.assertFalse(result["invalid"])

    def test_array_items_keep_their_identity_and_invalid_types_are_visible(self):
        schema = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"quantity": {"type": "integer"}}, "required": ["quantity"]}}}}
        result = review({"items": [{"quantity": "two"}, {}]}, schema)
        self.assertEqual(result["missing"][0]["path"], "items.1.quantity")
        self.assertEqual(result["invalid"][0]["label"], "Items › 1 › Quantity")

    def test_assistant_markdown_is_formatted_without_html_links_or_images(self):
        html = message_html('**Summary**\n\n- Value\n\n<script>alert(1)</script> ![tracking](https://example.com/pixel) [click](javascript:alert(1))')
        self.assertIn('<strong>Summary</strong>', html)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        self.assertNotIn('<a ', html)

    def test_long_payloads_are_bounded(self):
        self.assertEqual(len(review({str(i): i for i in range(200)}, {})["values"]), 100)
