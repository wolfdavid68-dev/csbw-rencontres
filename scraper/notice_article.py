"""Announce on WordPress that the Pierre Albouy hall is unavailable for training on given days."""

from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import date

from .weekly_article import FRENCH_MONTHS, FRENCH_WEEKDAYS, WeeklyArticle, format_day, publish_wordpress


PARAGRAPH = '<p style="font-size:18px;line-height:1.6;margin:0 0 16px;">'


def format_days(days: list[date]) -> str:
    """"vendredi 9 et dimanche 11 octobre", keeping the month on each day when it changes."""
    if len({(day.year, day.month) for day in days}) > 1:
        labels = [format_day(day) for day in days]
    else:
        labels = [f"{FRENCH_WEEKDAYS[day.weekday()]} {day.day}" for day in days]
        labels[-1] += f" {FRENCH_MONTHS[days[-1].month - 1]}"
    return labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} et {labels[-1]}"


def build_notice(days: list[date], reason: str = "", alternative: str = "") -> WeeklyArticle:
    days = sorted(set(days))
    days_label = format_days(days)
    these_days = "ce jour-là" if len(days) == 1 else "ces jours-là"
    paragraphs = [f"La salle Pierre Albouy sera occupée <strong>{html.escape(days_label)}</strong>."]
    if reason.strip():
        paragraphs.append(html.escape(reason.strip()))
    paragraphs.append(f"Il n’y aura donc <strong>pas d’entraînement</strong> dans la salle {these_days}.")
    if alternative.strip():
        paragraphs.append(f"👉 {html.escape(alternative.strip())}")
    paragraphs.append("Merci de votre compréhension. 🏸")
    # With a replacement session, "no training" would overstate it: name the hall instead.
    title = (f"⚠️ Salle Pierre Albouy occupée {days_label}" if alternative.strip()
             else f"⚠️ Pas d’entraînement {days_label}")
    return WeeklyArticle(
        should_create=True,
        week_start=days[0],
        week_end=days[-1],
        title=title,
        slug=f"salle-pierre-albouy-occupee-{days[0].isoformat()}",
        excerpt=f"La salle Pierre Albouy sera occupée {days_label} : pas d’entraînement dans la salle {these_days}.",
        content="\n".join(f"{PARAGRAPH}{text}</p>" for text in paragraphs),
        matches=[],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Annonce que la salle Pierre Albouy est occupée.")
    parser.add_argument("--date", required=True, help="Jour(s) concerné(s), AAAA-MM-JJ séparés par des virgules.")
    parser.add_argument("--reason", default="", help="Précision facultative affichée dans l'article.")
    parser.add_argument("--alternative", default="", help="Solution de repli facultative (autre salle...).")
    parser.add_argument("--status", choices=("draft", "publish"), default="draft")
    args = parser.parse_args()

    days = [date.fromisoformat(value.strip()) for value in args.date.split(",") if value.strip()]
    article = build_notice(days, args.reason, args.alternative)
    print(f"Titre : {article.title}\n{article.content}")
    try:
        result = publish_wordpress(
            article,
            wordpress_url=os.environ.get("WP_URL", "https://www.csbw.fr"),
            username=os.environ.get("WP_USERNAME", ""),
            application_password=os.environ.get("WP_APPLICATION_PASSWORD", ""),
            status=args.status,
        )
    except Exception as error:
        print(f"Echec de l'annonce : {error}", file=sys.stderr)
        return 1
    print(f"WordPress: {result['action']}, etat={result.get('status')}, id={result.get('id')}, lien={result.get('link')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
