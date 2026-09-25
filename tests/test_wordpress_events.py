from datetime import date, datetime
import unittest

from scraper.demo import build_demo_result
from scraper.wordpress_events import marker_id, sync_events_manager_week


class Response:
    status_code = 200

    def __init__(self, items):
        self.items = items

    def json(self):
        return {"items": self.items}

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, items):
        self.headers = {}
        self.items = items
        self.writes = []

    def get(self, *args, **kwargs):
        return Response(self.items)

    def patch(self, url, json, timeout):
        self.writes.append(("patch", url, json))
        return Response([])

    def post(self, url, json, timeout):
        self.writes.append(("post", url, json))
        return Response([])


class EventSyncTests(unittest.TestCase):
    def setUp(self):
        self.match = build_demo_result().matches[0]
        self.match.start = datetime.fromisoformat("2026-09-04T20:30:00+02:00")
        self.match.id = "782029"
        self.match.source_url = "https://icbad.ffbad.org/rencontre/782029"
        self.event = {
            "id": 1231, "post_id": 6584,
            "name": "R1 - CSBW 1 - Musau 2",
            "content": '<p><a href="https://icbad.ffbad.org/rencontre/782029">ICbad</a></p>',
            "location": {"id": 35},
        }

    def sync(self, session, dry_run=False):
        return sync_events_manager_week(
            [self.match], date(2026, 8, 31), "https://www.csbw.fr",
            "test", "test", 9, 2, ["pierre albouy"],
            session=session, dry_run=dry_run,
        )

    def test_manual_event_is_reused_and_editorial_fields_are_preserved(self):
        session = Session([self.event])
        result = self.sync(session)
        self.assertEqual((result["created"], result["updated"]), (0, 1))
        method, url, payload = session.writes[0]
        self.assertEqual(method, "patch")
        self.assertTrue(url.endswith("/events/1231"))
        for field in ("event_name", "content", "location_id"):
            self.assertNotIn(field, payload)

    def test_dry_run_never_writes_existing_or_new_events(self):
        for items in ([self.event], []):
            session = Session(items)
            result = self.sync(session, dry_run=True)
            self.assertEqual(result["action"], "dry_run")
            self.assertEqual(session.writes, [])
            self.assertEqual(result["created"], int(not items))

    def test_duplicate_sources_stop_before_any_write(self):
        session = Session([self.event, {**self.event, "id": 1232}])
        with self.assertRaisesRegex(ValueError, "plusieurs fois"):
            self.sync(session)
        self.assertEqual(session.writes, [])

    def test_content_formats_and_ambiguous_links(self):
        self.assertEqual(marker_id({"content": {"rendered": self.event["content"]}}), "782029")
        self.assertEqual(marker_id({"content": 'title="CSBW_SYNC:manual-1"'}), "manual-1")
        with self.assertRaises(ValueError):
            marker_id({"content": self.event["content"] + ' https://icbad.ffbad.org/rencontre/99999'})


if __name__ == "__main__":
    unittest.main()
