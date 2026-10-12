import unittest
from urllib.parse import parse_qs

from scraper.wordpress_widget import form_data, php_unserialize, widget_summary


class WidgetTests(unittest.TestCase):
    def test_reads_php_serialized_widget_settings(self):
        raw = 'a:4:{s:5:"title";s:9:"Interclub";s:5:"limit";i:5;s:10:"nolistwrap";b:0;s:6:"format";s:7:"<li>é</li>";}'
        raw = raw.replace('s:7:"<li>é</li>"', f's:{len("<li>é</li>".encode())}:"<li>é</li>"')
        self.assertEqual(
            php_unserialize(raw.encode()),
            {"title": "Interclub", "limit": 5, "nolistwrap": False, "format": "<li>é</li>"},
        )

    def test_form_data_keeps_every_field_and_omits_unchecked_boxes(self):
        encoded = form_data("10", {"title": "Interclub", "limit": 5, "nolistwrap": False, "all_events": True})
        self.assertEqual(
            parse_qs(encoded),
            {"widget-em_widget[10][title]": ["Interclub"], "widget-em_widget[10][limit]": ["5"],
             "widget-em_widget[10][all_events]": ["1"]},
        )

    def test_widget_summary_shows_block_content(self):
        widget = {"id": "block-3", "id_base": "block", "instance": {"raw": {"content": '<div id="csbw-manifestations-widget">Événements</div>'}}}
        summary = widget_summary(widget)
        self.assertIn("block-3", summary)
        self.assertIn("csbw-manifestations-widget", summary)
