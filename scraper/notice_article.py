"""Announce on WordPress that the Pierre Albouy hall is unavailable for training on a given day."""

from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import date

from .weekly_article import WeeklyArticle, format_day, publish_wordpress


PARAGRAPH = '<p style="font-size:18px;line-height:1.6;margin:0 0 16px;">'


def build_notice(day: date, reason: str = "") -> WeeklyArticle:
    day_label = format_day(day)
    paragraphs = [f"La salle Pierre Albouy sera occupée <strong>{html.escape(day_label)}</strong>."]
    if reason.strip():
        paragraphs.append(html.escape(reason.strip()))
    paragraphs += [
        "Il n’y aura donc <strong>pas d’entraînement</strong> dans la salle ce jour-là.",
        "Merci de votre compréhension. 🏸",
    ]
    return WeeklyArticle(
        should_create=True,
        week_start=day,
        week_end=day,
        title=f"⚠️ Pas d’entraînement {day_label}",
        slug=f"salle-pierre-albouy-occupee-{day.isoformat()}",
        excerpt=f"La salle Pierre Albouy sera occupée {day_label} : pas d’entraînement ce jour-là.",
        content="\n".join(f"{PARAGRAPH}{text}</p>" for text in paragraphs),
        matches=[],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Annonce que la salle Pierre Albouy est occupée.")
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="Jour concerné (AAAA-MM-JJ).")
    parser.add_argument("--reason", default="", help="Précision facultative affichée dans l'article.")
    parser.add_argument("--status", choices=("draft", "publish"), default="draft")
    args = parser.parse_args()

    article = build_notice(args.date, args.reason)
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
