import unittest
from urllib.parse import parse_qs

from scraper.wordpress_widget import form_data, php_unserialize, widget_summary, with_block, MANAGED_BLOCKS


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

    def test_events_block_is_appended_once_and_replaced(self):
        block = "<!-- csbw-events-widget:start -->\n<script>v1</script>\n<!-- csbw-events-widget:end -->"
        footer = with_block("</ul>\n<script>tri</script>", "csbw-events-widget", block)
        self.assertEqual(footer, "</ul>\n<script>tri</script>\n\n" + block)
        updated = with_block(footer, "csbw-events-widget", block.replace("v1", "v2"))
        self.assertEqual(updated.count("csbw-events-widget:start"), 1)
        self.assertIn("v2", updated)
        self.assertNotIn("v1", updated)
        self.assertTrue(updated.startswith("</ul>\n<script>tri</script>"))

    def test_other_blocks_are_kept_and_a_missing_template_is_removed(self):
        events = "<!-- csbw-events-widget:start -->\n<script>e</script>\n<!-- csbw-events-widget:end -->"
        popup = "<!-- csbw-fromage-popup:start -->\n<script>p</script>\n<!-- csbw-fromage-popup:end -->"
        footer = with_block(with_block("</ul>", "csbw-events-widget", events), "csbw-fromage-popup", popup)
        self.assertEqual(footer, "</ul>\n\n" + events + "\n\n" + popup)
        self.assertEqual(with_block(footer, "csbw-fromage-popup", None), "</ul>\n\n" + events)

    def test_popup_template_survives_the_widget_format(self):
        # WordPress may strip backslashes and Events Manager reads "#x" as a placeholder: keep both out.
        block = MANAGED_BLOCKS["csbw-fromage-popup"].read_text(encoding="utf-8")
        script = block.split("<script>", 1)[1].split("</script>", 1)[0]
        self.assertNotIn("\\", script)
        self.assertNotIn("#", script)
        self.assertNotIn("<", script)
        self.assertEqual(len(script.splitlines()), 1)
