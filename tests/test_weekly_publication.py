from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, call, patch
from zoneinfo import ZoneInfo

import requests

from scraper.demo import build_demo_result
from scraper.weekly_article import build_weekly_article, next_week_start, publish_wordpress, sunday_publication_time


def response(status: int, payload: object) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    return result


class WeeklyPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.article = build_weekly_article(build_demo_result(), date(2026, 8, 31), ["pierre albouy"])
        self.session = Mock()
        self.session.get.return_value = response(200, [{"id": 42}])
        self.published = response(200, {"id": 42, "status": "publish", "link": "https://example.org/week/"})
        self.session.post.return_value = self.published
        self.sleep = patch("scraper.weekly_article.time.sleep").start()
        self.addCleanup(patch.stopall)

    def publish(self, **kwargs):
        return publish_wordpress(self.article, "https://example.org", "user", "secret", "publish",
                                 session=self.session, **kwargs)

    def test_503_publication_is_retried_on_same_post(self) -> None:
        self.session.post.side_effect = [response(503, {}), self.published]
        self.assertEqual(self.publish()["status"], "publish")
        self.assertEqual(self.session.post.call_count, 2)
        self.assertEqual(self.session.post.call_args_list[0], self.session.post.call_args_list[1])
        self.sleep.assert_called_once_with(10)

    def test_timeout_during_update_is_retried(self) -> None:
        self.session.post.side_effect = [requests.Timeout(), self.published]
        self.assertEqual(self.publish()["id"], 42)
        self.assertEqual(self.session.post.call_count, 2)

    def test_temporary_lookup_failure_is_retried(self) -> None:
        self.session.get.side_effect = [response(502, {}), response(200, [{"id": 42}])]
        self.assertEqual(self.publish()["action"], "updated")
        self.session.post.assert_called_once()

    def test_permanent_error_is_not_retried(self) -> None:
        self.session.post.return_value = response(401, {})
        with self.assertRaises(requests.HTTPError):
            self.publish()
        self.session.post.assert_called_once()
        self.sleep.assert_not_called()

    def test_persistent_503_fails_after_four_attempts(self) -> None:
        self.session.post.return_value = response(503, {})
        with self.assertRaises(requests.HTTPError):
            self.publish()
        self.assertEqual(self.session.post.call_count, 4)
        self.assertEqual(self.sleep.call_args_list, [call(10), call(30), call(60)])

    def test_create_draft_once_before_retrying_publication(self) -> None:
        self.session.get.return_value = response(200, [])
        self.session.post.side_effect = [response(201, {"id": 42}), response(503, {}), self.published]
        self.assertEqual(self.publish()["action"], "created")
        calls = self.session.post.call_args_list
        self.assertEqual(calls[0].args[0], "https://example.org/wp-json/wp/v2/posts")
        self.assertEqual(calls[0].kwargs["json"]["status"], "draft")
        self.assertEqual(calls[1].args[0], "https://example.org/wp-json/wp/v2/posts/42")
        self.assertEqual(calls[1], calls[2])

    def test_ambiguous_creation_is_not_blindly_repeated(self) -> None:
        self.session.get.return_value = response(200, [])
        self.session.post.side_effect = requests.Timeout()
        with self.assertRaises(requests.Timeout):
            self.publish()
        self.session.post.assert_called_once()
        self.sleep.assert_not_called()

    def test_recovery_keeps_published_article_and_manual_edits(self) -> None:
        result = self.publish(skip_published=True)
        self.assertEqual(result["reason"], "already_published")
        self.session.post.assert_not_called()

    def test_recovery_publishes_existing_draft(self) -> None:
        self.session.get.side_effect = [response(200, []), response(200, []), response(200, [{"id": 42}])]
        self.assertEqual(self.publish(skip_published=True)["action"], "updated")
        self.session.post.assert_called_once()

    def test_wrong_returned_status_is_an_error(self) -> None:
        self.session.post.return_value = response(200, {"id": 42, "status": "draft"})
        with self.assertRaisesRegex(ValueError, "Etat WordPress inattendu"):
            self.publish()

    def test_sunday_evening_targets_following_monday_in_summer_and_winter(self) -> None:
        paris = ZoneInfo("Europe/Paris")
        for month, day, monday in ((9, 27, date(2026, 9, 28)), (10, 25, date(2026, 10, 26))):
            for minute in (0, 20, 40):
                self.assertEqual(next_week_start(datetime(2026, month, day, 19, minute, tzinfo=paris)), monday)

    def test_workflow_has_local_schedule_recovery_and_error_artifacts(self) -> None:
        workflow = (Path(__file__).parents[1] / ".github/workflows/weekly-article.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "17 8,12,15,17 * * 0"', workflow)
        self.assertIn('timezone: "Europe/Paris"', workflow)
        self.assertIn('WEEK_ARGS+=(--skip-published --schedule-sunday)', workflow)
        self.assertIn('if: always()', workflow)

    def test_sunday_deadline_handles_both_clock_changes(self) -> None:
        for monday, utc_hour in ((date(2026, 3, 30), 17), (date(2026, 10, 26), 18)):
            with self.subTest(monday=monday):
                deadline = sunday_publication_time(monday)
                self.assertEqual(deadline.weekday(), 6)
                self.assertEqual(deadline.hour, 19)
                self.assertEqual(deadline.astimezone(timezone.utc).hour, utc_hour)

    def test_invalid_week_rejected_before_remote_requests(self) -> None:
        self.article.week_start = date(2026, 9, 1)
        with self.assertRaisesRegex(ValueError, "lundi"):
            self.publish(schedule_sunday=True)
        self.session.get.assert_not_called()

    def test_early_preparation_reserves_draft_then_schedules_not_publishes(self) -> None:
        self.session.get.return_value = response(200, [])
        self.session.post.side_effect = [response(201, {"id": 42}), response(200, {
            "id": 42, "status": "future", "date_gmt": "2026-08-30T17:00:00",
        })]
        result = self.publish(schedule_sunday=True, now=datetime(2026, 8, 30, 8, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "future")
        calls = self.session.post.call_args_list
        self.assertEqual(calls[0].kwargs["json"]["status"], "draft")
        self.assertEqual(calls[1].kwargs["json"]["status"], "future")
        self.assertEqual(calls[1].kwargs["json"]["date_gmt"], "2026-08-30T17:00:00")

    def test_later_preparation_updates_same_scheduled_article(self) -> None:
        self.session.get.side_effect = [response(200, []), response(200, [{"id": 42}])]
        self.session.post.return_value = response(200, {
            "id": 42, "status": "future", "date_gmt": "2026-08-30T17:00:00",
        })
        result = self.publish(schedule_sunday=True, now=datetime(2026, 8, 30, 13, tzinfo=timezone.utc))
        self.assertEqual(result["action"], "updated")
        self.session.post.assert_called_once()
        self.assertTrue(self.session.post.call_args.args[0].endswith("/42"))

    def test_late_preparation_publishes_immediately(self) -> None:
        self.session.get.side_effect = [response(200, []), response(200, [{"id": 42}])]
        result = self.publish(schedule_sunday=True, now=datetime(2026, 8, 30, 20, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "publish")
        self.assertEqual(self.session.post.call_args.kwargs["json"]["status"], "publish")

    def test_scheduling_never_reschedules_published_article(self) -> None:
        result = self.publish(schedule_sunday=True, now=datetime(2026, 8, 30, 8, tzinfo=timezone.utc))
        self.assertEqual(result["reason"], "already_published")
        self.session.post.assert_not_called()

    def test_wrong_schedule_date_is_an_error(self) -> None:
        self.session.get.side_effect = [response(200, []), response(200, [{"id": 42}])]
        self.session.post.return_value = response(200, {
            "id": 42, "status": "future", "date_gmt": "2026-08-30T19:00:00",
        })
        with self.assertRaisesRegex(ValueError, "date de publication"):
            self.publish(schedule_sunday=True, now=datetime(2026, 8, 30, 8, tzinfo=timezone.utc))

    def test_scheduling_cannot_publish_a_manual_draft(self) -> None:
        with self.assertRaisesRegex(ValueError, "status publish"):
            publish_wordpress(self.article, "https://example.org", "user", "secret", "draft",
                              session=self.session, schedule_sunday=True)
        self.session.get.assert_not_called()

    def test_empty_week_creates_no_scheduled_post(self) -> None:
        self.article.should_create = False
        self.session.get.return_value = response(200, [])
        self.assertEqual(self.publish(schedule_sunday=True)["reason"], "no_home_matches")
        self.session.post.assert_not_called()

    def test_cancellation_unschedules_existing_article_without_deleting(self) -> None:
        self.article.should_create = False
        self.session.get.side_effect = [response(200, []), response(200, [{"id": 42}])]
        self.session.post.return_value = response(200, {"id": 42, "status": "draft"})
        self.assertEqual(self.publish(schedule_sunday=True)["action"], "unscheduled")
        self.session.post.assert_called_once_with("https://example.org/wp-json/wp/v2/posts/42",
                                                  timeout=30, json={"status": "draft"})
        self.session.delete.assert_not_called()

    def test_cancellation_does_not_unpublish_existing_article(self) -> None:
        self.article.should_create = False
        self.assertEqual(self.publish(schedule_sunday=True)["reason"], "already_published")
        self.session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
