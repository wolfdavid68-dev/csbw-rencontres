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

    def delete(self, url, timeout):
        self.writes.append(("delete", url, None))
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

    def test_synced_placeholder_is_refreshed_once_icbad_publishes_the_venue(self):
        placeholder = {
            "id": 1240,
            "content": '<p>📍 Lieu à confirmer</p><p><a href="https://icbad.ffbad.org/rencontre/782029" '
                       'title="CSBW_SYNC:782029">Voir la fiche ICbad</a></p>',
        }
        session = Session([placeholder])
        self.sync(session)
        payload = session.writes[0][2]
        self.assertNotIn("event_name", payload)
        self.assertIn(self.match.venue, payload["content"])
        self.assertEqual(payload["location_id"], 2)
        self.assertEqual(payload["event_all_day"], 0)

    def test_generated_long_title_is_shortened_but_editorial_title_kept(self):
        generated = {
            "id": 1241,
            "name": f"{self.match.home_team} - {self.match.away_team}",
            "content": '<p><a href="https://icbad.ffbad.org/rencontre/782029" title="CSBW_SYNC:782029">ICbad</a></p>',
        }
        session = Session([generated])
        self.sync(session)
        self.assertEqual(session.writes[0][2]["event_name"], f"{self.match.team} – {self.match.opponent}")

        session = Session([self.event])
        self.sync(session)
        self.assertNotIn("event_name", session.writes[0][2])

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

    def synced_event(self, when):
        return {
            "id": 1250, "name": "Equipe renommée", "location": {"id": 35}, "when": when,
            "content": '<p>📍 Salle du club</p><p><a href="https://icbad.ffbad.org/rencontre/782029" '
                       'title="CSBW_SYNC:782029">Voir la fiche ICbad</a></p>',
        }

    def test_time_published_after_all_day_event_recreates_it(self):
        stored = self.synced_event({"all_day": True, "start_date": "2026-09-04", "start_time": "00:00:00"})
        session = Session([stored])
        result = self.sync(session)
        self.assertEqual((result["created"], result["updated"], result["recreated"]), (0, 0, 1))
        self.assertEqual([write[0] for write in session.writes], ["post", "delete"])
        payload = session.writes[0][2]
        self.assertEqual((payload["event_all_day"], payload["event_start_time"]), (0, "20:30:00"))
        self.assertEqual(payload["event_name"], "Equipe renommée")
        self.assertEqual(payload["content"], stored["content"])
        self.assertEqual(payload["location_id"], 35)
        self.assertTrue(session.writes[1][1].endswith("/events/1250"))

        session = Session([stored])
        self.assertEqual(self.sync(session, dry_run=True)["recreated"], 1)
        self.assertEqual(session.writes, [])

    def test_unchanged_time_or_manual_event_is_only_patched(self):
        for event in (
            self.synced_event({"all_day": "0", "start_date": "2026-09-04", "start_time": "20:30:00"}),
            {**self.event, "when": {"all_day": True, "start_date": "2026-09-04"}},
        ):
            session = Session([event])
            self.sync(session)
            self.assertEqual([write[0] for write in session.writes], ["patch"])

    def test_content_formats_and_ambiguous_links(self):
        self.assertEqual(marker_id({"content": {"rendered": self.event["content"]}}), "782029")
        self.assertEqual(marker_id({"content": 'title="CSBW_SYNC:manual-1"'}), "manual-1")
        with self.assertRaises(ValueError):
            marker_id({"content": self.event["content"] + ' https://icbad.ffbad.org/rencontre/99999'})


if __name__ == "__main__":
    unittest.main()
