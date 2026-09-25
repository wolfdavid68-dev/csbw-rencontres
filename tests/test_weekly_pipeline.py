from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scraper import weekly_article
from scraper.demo import build_demo_result


class WeeklyPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.calendar = self.root / "rencontres.json"
        self.result = build_demo_result()
        self.calendar.write_text(json.dumps(self.result.to_dict()), encoding="utf-8")
        self.argv = [
            "weekly_article", "--data", str(self.calendar),
            "--week-start", "2026-08-31",
            "--output-dir", str(self.root / "preview"),
            "--sync-events", "--publish-wordpress",
        ]

    def test_load_calendar_preserves_dates_and_matches(self) -> None:
        result = weekly_article.load_calendar(self.calendar)
        self.assertEqual(result.matches, self.result.matches)
        self.assertEqual(result.generated_at, self.result.generated_at)

    def test_calendar_not_ready_prevents_all_remote_actions(self) -> None:
        self.result.status = "pending"
        self.calendar.write_text(json.dumps(self.result.to_dict()), encoding="utf-8")
        with (
            patch("sys.argv", self.argv),
            patch.object(weekly_article, "sync_events_manager_week") as sync,
            patch.object(weekly_article, "publish_wordpress") as publish,
        ):
            self.assertEqual(weekly_article.main(), 1)
        sync.assert_not_called()
        publish.assert_not_called()

    def test_shared_calendar_synced_before_article_without_second_scrape(self) -> None:
        calls = []

        def synchronize(matches, **kwargs):
            calls.append("events")
            self.assertEqual(matches, self.result.matches)
            self.assertEqual(kwargs["week_start"], date(2026, 8, 31))
            return {"action": "synced", "created": 0, "updated": 3}

        def publish_article(article, **kwargs):
            calls.append("article")
            self.assertEqual(article.week_start, date(2026, 8, 31))
            self.assertEqual(len(article.matches), 3)
            return {"action": "updated", "id": 42}

        with (
            patch("sys.argv", self.argv),
            patch.object(weekly_article, "ICBadClient") as client,
            patch.object(weekly_article, "sync_events_manager_week", side_effect=synchronize),
            patch.object(weekly_article, "publish_wordpress", side_effect=publish_article),
        ):
            self.assertEqual(weekly_article.main(), 0)
        client.assert_not_called()
        self.assertEqual(calls, ["events", "article"])
        output = json.loads((self.root / "preview" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(output["events_manager"]["action"], "synced")
        self.assertEqual(output["wordpress"]["id"], 42)

    def test_sync_failure_prevents_article_publication(self) -> None:
        for outcome in (ValueError("Sync failed"), {"action": "skipped"}):
            with self.subTest(outcome=outcome):
                with (
                    patch("sys.argv", self.argv),
                    patch.object(weekly_article, "sync_events_manager_week") as sync,
                    patch.object(weekly_article, "publish_wordpress") as publish,
                ):
                    if isinstance(outcome, Exception):
                        sync.side_effect = outcome
                    else:
                        sync.return_value = outcome
                    self.assertEqual(weekly_article.main(), 1)
                publish.assert_not_called()

    def test_week_without_home_match_still_syncs_events(self) -> None:
        self.argv[self.argv.index("2026-08-31")] = "2026-09-07"
        with (
            patch("sys.argv", self.argv),
            patch.object(weekly_article, "sync_events_manager_week",
                         return_value={"action": "synced", "created": 1, "updated": 0}) as sync,
            patch.object(weekly_article.requests, "Session") as session,
        ):
            self.assertEqual(weekly_article.main(), 0)
        sync.assert_called_once()
        session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
