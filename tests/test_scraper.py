from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scraper.demo import build_demo_result
from scraper.icbad import discover_competitions, parse_matches, parse_teams
from scraper.models import Competition, ScrapeResult
from scraper.render import apply_overrides, render_ics
from scraper.weekly_article import build_weekly_article, publish_wordpress
from scraper.wordpress_events import (
    event_payload,
    select_week_matches,
    sidebar_week_start,
    sync_events_manager_week,
)


FIXTURES = Path(__file__).parent / "fixtures"
PARIS = ZoneInfo("Europe/Paris")


class ScraperTests(unittest.TestCase):
    def test_demo_is_isolated_and_contains_upcoming_matches(self) -> None:
        result = build_demo_result()
        self.assertEqual(result.season, "2026-2027")
        self.assertEqual(len(result.matches), 6)
        self.assertEqual(sum(item.is_home for item in result.matches), 5)

    def test_weekly_article_groups_only_home_matches_at_pierre_albouy(self) -> None:
        article = build_weekly_article(
            build_demo_result(),
            date(2026, 8, 31),
            ["salle pierre albouy"],
        )
        self.assertTrue(article.should_create)
        self.assertEqual(len(article.matches), 3)
        self.assertIn("📅 Vendredi 4 septembre : 2 rencontres d’interclub à la salle Pierre Albouy", article.content)
        self.assertIn("📅 Dimanche 6 septembre : 1 rencontre d’interclub à la salle Pierre Albouy", article.content)
        self.assertIn("🕒 <strong>20h30</strong>", article.content)
        self.assertIn("CSBW 1 reçoit Badminton Club Mulhouse", article.content)
        self.assertIn("CSBW 3 reçoit Colmar Badminton Racing", article.content)
        self.assertIn("CSBW 5 reçoit Sundgau Badminton", article.content)
        self.assertNotIn("Volant des Trois Frontières", article.content)

    def test_weekly_article_skips_week_without_home_match(self) -> None:
        article = build_weekly_article(
            build_demo_result(),
            date(2026, 9, 7),
            ["salle pierre albouy"],
        )
        self.assertFalse(article.should_create)
        self.assertEqual(article.content, "")

    def test_wordpress_publish_updates_existing_weekly_article(self) -> None:
        article = build_weekly_article(
            build_demo_result(),
            date(2026, 8, 31),
            ["salle pierre albouy"],
        )

        class FakeResponse:
            def __init__(self, payload: object) -> None:
                self.payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> object:
                return self.payload

        class FakeSession:
            def __init__(self) -> None:
                self.auth = None
                self.headers: dict[str, str] = {}
                self.post_url = ""
                self.post_payload: dict | None = None

            def get(self, *args, **kwargs) -> FakeResponse:
                return FakeResponse([{"id": 42}])

            def post(self, url: str, json: dict, timeout: int) -> FakeResponse:
                self.post_url = url
                self.post_payload = json
                return FakeResponse(
                    {"id": 42, "status": "publish", "link": "https://www.csbw.fr/article-test/"}
                )

        session = FakeSession()
        result = publish_wordpress(
            article,
            "https://www.csbw.fr",
            "user",
            "application password",
            "publish",
            session=session,
        )
        self.assertEqual(result["action"], "updated")
        self.assertTrue(session.post_url.endswith("/posts/42"))
        self.assertEqual(session.post_payload["slug"], article.slug)

    def test_sidebar_switches_to_next_week_on_sunday_evening(self) -> None:
        self.assertEqual(
            sidebar_week_start(datetime(2026, 9, 16, 12, tzinfo=PARIS)),
            date(2026, 9, 14),
        )
        self.assertEqual(
            sidebar_week_start(datetime(2026, 9, 20, 12, tzinfo=PARIS)),
            date(2026, 9, 14),
        )
        self.assertEqual(
            sidebar_week_start(datetime(2026, 9, 20, 19, tzinfo=PARIS)),
            date(2026, 9, 21),
        )

    def test_sidebar_selects_all_matches_in_monday_to_sunday_week(self) -> None:
        matches = select_week_matches(build_demo_result().matches, date(2026, 9, 7))
        self.assertEqual(len(matches), 1)
        self.assertFalse(matches[0].is_home)

    def test_event_payload_uses_interclub_category_and_home_location(self) -> None:
        match = build_demo_result().matches[0]
        payload = event_payload(match, 9, 2, ["salle pierre albouy"])
        self.assertEqual(payload["event_categories"], [9])
        self.assertEqual(payload["location_id"], 2)
        self.assertIn(f"CSBW_SYNC:{match.id}", payload["content"])

    def test_event_sync_skips_when_events_manager_api_is_missing(self) -> None:
        class FakeResponse:
            status_code = 404

            def raise_for_status(self) -> None:
                raise AssertionError("404 must be handled as an unavailable API")

        class FakeSession:
            def __init__(self) -> None:
                self.auth = None
                self.headers: dict[str, str] = {}

            def get(self, *args, **kwargs) -> FakeResponse:
                return FakeResponse()

        result = sync_events_manager_week(
            build_demo_result().matches,
            week_start=date(2026, 8, 31),
            wordpress_url="https://www.csbw.fr",
            username="user",
            application_password="application password",
            category_id=9,
            home_location_id=2,
            home_venue_patterns=["salle pierre albouy"],
            session=FakeSession(),
        )
        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "events_manager_api_unavailable")

    def test_discovers_only_relevant_senior_competitions(self) -> None:
        competitions = discover_competitions(
            (FIXTURES / "home.html").read_text(encoding="utf-8"),
            league_code="GEST",
            committee_code="CD68",
            include_national=True,
        )
        self.assertEqual({item.id for item in competitions}, {"2600001", "2600100", "2600200"})

    def test_finds_and_deduplicates_csbw_teams(self) -> None:
        competition = Competition("2600200", "Interclubs Comité 68 D1", "https://icbad.ffbad.org/competition/2600200")
        teams = parse_teams(
            (FIXTURES / "competition.html").read_text(encoding="utf-8"),
            competition,
            club_code="68-CSBW",
        )
        self.assertEqual(len(teams), 1)
        self.assertEqual(teams[0].label, "CSBW 1")
        self.assertEqual(teams[0].division, "Interclubs Comité 68 D1 - Poule A")

    def test_parses_home_away_dates_and_scores(self) -> None:
        competition = Competition("2600200", "Interclubs Comité 68 D1", "https://icbad.ffbad.org/competition/2600200")
        team = parse_teams(
            (FIXTURES / "competition.html").read_text(encoding="utf-8"),
            competition,
            club_code="68-CSBW",
        )[0]
        matches = parse_matches(
            (FIXTURES / "team.html").read_text(encoding="utf-8"),
            team,
            club_code="68-CSBW",
            season_start_year=2026,
            timezone=PARIS,
            now=datetime(2026, 8, 1, tzinfo=PARIS),
        )
        self.assertEqual(len(matches), 2)
        self.assertTrue(matches[0].is_home)
        self.assertEqual(matches[0].start.isoformat(), "2026-09-25T20:30:00+02:00")
        self.assertIsNone(matches[0].score)
        self.assertFalse(matches[1].is_home)
        self.assertEqual(matches[1].start.isoformat(), "2027-01-16T20:00:00+01:00")
        self.assertEqual(matches[1].score, "3-5")

    def test_manual_override_updates_and_adds_matches(self) -> None:
        competition = Competition("2600200", "Interclubs Comité 68 D1", "https://icbad.ffbad.org/competition/2600200")
        team = parse_teams(
            (FIXTURES / "competition.html").read_text(encoding="utf-8"),
            competition,
            club_code="68-CSBW",
        )[0]
        base = parse_matches(
            (FIXTURES / "team.html").read_text(encoding="utf-8"),
            team,
            club_code="68-CSBW",
            season_start_year=2026,
            timezone=PARIS,
            now=datetime(2026, 8, 1, tzinfo=PARIS),
        )
        result = ScrapeResult("2026-2027", datetime(2026, 8, 1, tzinfo=PARIS), "ready", matches=base)
        manual = base[0].to_dict()
        manual.update({"id": "manual-1", "start": "2026-10-02T20:30:00+02:00", "opponent": "Club manuel"})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "overrides.json"
            path.write_text(
                json.dumps(
                    {
                        "delete": ["80002"],
                        "upsert": [
                            {"id": "80001", "season": "2026-2027", "venue": "Salle corrigée"},
                            manual,
                        ],
                    }
                ),
                encoding="utf-8",
            )
            apply_overrides(result, path)
        self.assertEqual({item.id for item in result.matches}, {"80001", "manual-1"})
        self.assertEqual(next(item for item in result.matches if item.id == "80001").venue, "Salle corrigée")

    def test_ics_contains_stable_event_ids(self) -> None:
        competition = Competition("2600200", "Interclubs Comité 68 D1", "https://icbad.ffbad.org/competition/2600200")
        team = parse_teams((FIXTURES / "competition.html").read_text(encoding="utf-8"), competition, "68-CSBW")[0]
        matches = parse_matches(
            (FIXTURES / "team.html").read_text(encoding="utf-8"), team, "68-CSBW", 2026, PARIS,
            datetime(2026, 8, 1, tzinfo=PARIS),
        )
        result = ScrapeResult("2026-2027", datetime(2026, 8, 1, tzinfo=PARIS), "ready", matches=matches)
        content = render_ics(result, "Europe/Paris")
        self.assertIn("UID:icbad-80001@csbw.fr", content)
        self.assertIn("DTSTART;TZID=Europe/Paris:20260925T203000", content)


if __name__ == "__main__":
    unittest.main()
