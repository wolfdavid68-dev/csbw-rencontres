from __future__ import annotations

import json
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, call, patch
from zoneinfo import ZoneInfo

import requests

from scraper.demo import build_demo_result
from scraper.weekly_article import build_weekly_article, next_week_start, publish_wordpress


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
        self.assertIn('cron: "0,20,40 19 * * 0"', workflow)
        self.assertIn('timezone: "Europe/Paris"', workflow)
        self.assertIn('WEEK_ARGS+=(--skip-published)', workflow)
        self.assertIn('if: always()', workflow)


if __name__ == "__main__":
    unittest.main()
