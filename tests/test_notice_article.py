from datetime import date
import unittest

from scraper.notice_article import build_notice


class NoticeArticleTests(unittest.TestCase):
    def test_notice_names_the_day_and_escapes_the_reason(self):
        article = build_notice(date(2026, 10, 9), "Loto <mairie>")
        self.assertEqual(article.title, "⚠️ Pas d’entraînement vendredi 9 octobre")
        self.assertEqual(article.slug, "salle-pierre-albouy-occupee-2026-10-09")
        self.assertIn("<strong>vendredi 9 octobre</strong>", article.content)
        self.assertIn("Loto &lt;mairie&gt;", article.content)
        self.assertTrue(article.should_create)

    def test_reason_is_optional(self):
        self.assertEqual(build_notice(date(2026, 10, 9)).content.count("<p "), 3)


if __name__ == "__main__":
    unittest.main()
