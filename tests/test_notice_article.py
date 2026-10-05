from datetime import date
import unittest

from scraper.notice_article import build_notice, format_days


class NoticeArticleTests(unittest.TestCase):
    def test_notice_names_the_day_and_escapes_the_reason(self):
        article = build_notice([date(2026, 10, 9)], "Loto <mairie>")
        self.assertEqual(article.title, "⚠️ Pas d’entraînement vendredi 9 octobre")
        self.assertEqual(article.slug, "salle-pierre-albouy-occupee-2026-10-09")
        self.assertIn("<strong>vendredi 9 octobre</strong>", article.content)
        self.assertIn("Loto &lt;mairie&gt;", article.content)
        self.assertIn("ce jour-là", article.content)
        self.assertTrue(article.should_create)

    def test_reason_and_alternative_are_optional(self):
        self.assertEqual(build_notice([date(2026, 10, 9)]).content.count("<p "), 3)

    def test_several_days_with_a_fallback_hall_keep_the_first_day_slug(self):
        article = build_notice([date(2026, 10, 11), date(2026, 10, 9)], alternative="Dimanche : salle Zurcher.")
        self.assertEqual(article.title, "⚠️ Salle Pierre Albouy occupée vendredi 9 et dimanche 11 octobre")
        self.assertEqual(article.slug, "salle-pierre-albouy-occupee-2026-10-09")
        self.assertIn("ces jours-là", article.content)
        self.assertIn("👉 Dimanche : salle Zurcher.", article.content)

    def test_days_across_months(self):
        self.assertEqual(format_days([date(2026, 10, 30), date(2026, 11, 1)]),
                         "vendredi 30 octobre et dimanche 1 novembre")


if __name__ == "__main__":
    unittest.main()
