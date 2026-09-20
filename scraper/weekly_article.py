from __future__ import annotations

import argparse
import html
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.auth import HTTPBasicAuth

from .demo import build_demo_result
from .icbad import ICBadClient, normalize
from .models import Match, ScrapeResult
from .render import apply_overrides


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRENCH_WEEKDAYS = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


@dataclass(slots=True)
class WeeklyArticle:
    should_create: bool
    week_start: date
    week_end: date
    title: str
    slug: str
    excerpt: str
    content: str
    matches: list[Match]

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_create": self.should_create,
            "week_start": self.week_start.isoformat(),
            "week_end": self.week_end.isoformat(),
            "title": self.title,
            "slug": self.slug,
            "excerpt": self.excerpt,
            "content": self.content,
            "matches": [item.to_dict() for item in self.matches],
        }


def next_week_start(now: datetime) -> date:
    today = now.date()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def format_day(value: date) -> str:
    return f"{FRENCH_WEEKDAYS[value.weekday()]} {value.day} {FRENCH_MONTHS[value.month - 1]}"


def format_week(value: date, end: date) -> str:
    if value.month == end.month and value.year == end.year:
        return f"du {value.day} au {end.day} {FRENCH_MONTHS[end.month - 1]}"
    return f"du {value.day} {FRENCH_MONTHS[value.month - 1]} au {end.day} {FRENCH_MONTHS[end.month - 1]}"


def is_pierre_albouy(match: Match, patterns: list[str]) -> bool:
    venue = normalize(match.venue or "")
    return match.is_home and any(normalize(pattern) in venue for pattern in patterns)


def build_weekly_article(
    result: ScrapeResult,
    week_start: date,
    venue_patterns: list[str],
) -> WeeklyArticle:
    week_end = week_start + timedelta(days=6)
    end_exclusive = week_start + timedelta(days=7)
    selected = sorted(
        (
            match
            for match in result.matches
            if week_start <= match.start.date() < end_exclusive
            and is_pierre_albouy(match, venue_patterns)
        ),
        key=lambda item: (item.start, item.team, item.id),
    )
    week_label = format_week(week_start, week_end)
    title = f"Salle Pierre Albouy partiellement occupée - semaine {week_label}"
    slug = f"occupation-salle-pierre-albouy-{week_start.isoformat()}"

    if not selected:
        return WeeklyArticle(
            should_create=False,
            week_start=week_start,
            week_end=week_end,
            title=title,
            slug=slug,
            excerpt="Aucun interclub à domicile à la salle Pierre Albouy cette semaine.",
            content="",
            matches=[],
        )

    grouped: dict[date, list[Match]] = {}
    for match in selected:
        grouped.setdefault(match.start.date(), []).append(match)

    sections: list[str] = []
    for day, matches in sorted(grouped.items()):
        count = len(matches)
        count_label = "Un interclub" if count == 1 else f"{count} interclubs"
        sections.append(
            f"<h2>{count_label} ce {html.escape(format_day(day))} "
            "à la salle Pierre Albouy</h2>"
        )
        sections.append("<ul>")
        for match in matches:
            time_label = match.start.strftime("%Hh%M")
            team = html.escape(match.team)
            opponent = html.escape(match.opponent)
            link = html.escape(match.source_url, quote=True)
            sections.append(
                f'<li><strong>{time_label}</strong> - '
                f'<a href="{link}">{team} reçoit {opponent}</a></li>'
            )
        sections.append("</ul>")

    total_label = "Un interclub est prévu" if len(selected) == 1 else f"{len(selected)} interclubs sont prévus"
    excerpt = f"{total_label} à la salle Pierre Albouy pendant la semaine {week_label}."
    return WeeklyArticle(
        should_create=True,
        week_start=week_start,
        week_end=week_end,
        title=title,
        slug=slug,
        excerpt=excerpt,
        content="\n".join(sections),
        matches=selected,
    )


def write_preview(article: WeeklyArticle, output_dir: Path, demo: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = article.to_dict()
    payload["demo"] = demo
    (output_dir / "article.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    badge = '<p class="demo">APERÇU TEST - données fictives</p>' if demo else ""
    empty = "<p>Aucun article ne sera créé pour cette semaine.</p>" if not article.should_create else ""
    document = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(article.title)}</title>
  <style>
    body {{ margin: 0; background: #f2f3f5; color: #202124; font: 16px/1.55 system-ui, sans-serif; letter-spacing: 0; }}
    main {{ width: min(100% - 24px, 760px); margin: 24px auto; padding: 24px; background: #fff; border-top: 4px solid #c91424; }}
    h1 {{ margin: 0 0 24px; font-size: clamp(1.5rem, 4vw, 2.2rem); line-height: 1.2; }}
    h2 {{ margin: 24px 0 8px; font-size: 1.2rem; }}
    ul {{ margin: 0; padding-left: 22px; }}
    li {{ margin: 7px 0; }}
    a {{ color: #315c8c; text-underline-offset: 2px; }}
    .demo {{ display: inline-block; margin: 0 0 14px; padding: 5px 8px; background: #fff0d8; color: #7a4b00; font-size: .78rem; font-weight: 750; }}
    @media (max-width: 520px) {{ main {{ margin: 0; width: 100%; min-height: 100vh; padding: 18px; }} }}
  </style>
</head>
<body>
  <main>
    {badge}
    <h1>{html.escape(article.title)}</h1>
    {article.content}
    {empty}
  </main>
</body>
</html>
"""
    (output_dir / "index.html").write_text(document, encoding="utf-8")


def publish_wordpress(
    article: WeeklyArticle,
    wordpress_url: str,
    username: str,
    application_password: str,
    status: str,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    if not article.should_create:
        return {"action": "skipped", "reason": "no_home_matches"}
    if not username or not application_password:
        raise ValueError("WP_USERNAME et WP_APPLICATION_PASSWORD sont requis.")

    client = session or requests.Session()
    client.auth = HTTPBasicAuth(username, application_password)
    client.headers.update({"User-Agent": "CSBW-Wittelsheim-weekly-article/1.0"})
    endpoint = f"{wordpress_url.rstrip('/')}/wp-json/wp/v2/posts"
    existing_response = client.get(
        endpoint,
        params={
            "slug": article.slug,
            "status": "publish,future,draft,pending,private",
            "context": "edit",
        },
        timeout=30,
    )
    existing_response.raise_for_status()
    existing = existing_response.json()
    post_data = {
        "title": article.title,
        "slug": article.slug,
        "excerpt": article.excerpt,
        "content": article.content,
        "status": status,
    }

    if existing:
        response = client.post(f"{endpoint}/{existing[0]['id']}", json=post_data, timeout=30)
        action = "updated"
    else:
        response = client.post(endpoint, json=post_data, timeout=30)
        action = "created"
    response.raise_for_status()
    post = response.json()
    return {
        "action": action,
        "id": post.get("id"),
        "status": post.get("status"),
        "link": post.get("link"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crée l'article hebdomadaire d'occupation de la salle.")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.json")
    parser.add_argument("--season", type=int)
    parser.add_argument("--week-start", type=date.fromisoformat, help="Lundi ciblé, au format AAAA-MM-JJ.")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--no-delay", action="store_true")
    parser.add_argument("--publish-wordpress", action="store_true")
    parser.add_argument("--status", choices=("draft", "pending", "private", "publish"), default="publish")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.resolve().read_text(encoding="utf-8"))
    timezone = ZoneInfo(config.get("timezone", "Europe/Paris"))
    week_start = args.week_start or next_week_start(datetime.now(timezone))
    output_dir = args.output_dir or Path("build-weekly-demo" if args.demo else "build-weekly")
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    try:
        if args.demo:
            result = build_demo_result(config.get("timezone", "Europe/Paris"))
        else:
            season = args.season or int(config["season_start_year"])
            result = ICBadClient(config, no_delay=args.no_delay).scrape(season)
            overrides_path = PROJECT_ROOT / config.get("manual_overrides_file", "overrides.json")
            apply_overrides(result, overrides_path)
        article = build_weekly_article(
            result,
            week_start,
            config.get("home_venue_patterns", ["salle pierre albouy"]),
        )
        write_preview(article, output_dir, demo=args.demo)
        publication = None
        if args.publish_wordpress:
            publication = publish_wordpress(
                article,
                wordpress_url=os.environ.get("WP_URL", config.get("wordpress_url", "https://www.csbw.fr")),
                username=os.environ.get("WP_USERNAME", ""),
                application_password=os.environ.get("WP_APPLICATION_PASSWORD", ""),
                status=args.status,
            )
        result_payload = article.to_dict()
        if publication:
            result_payload["wordpress"] = publication
        (output_dir / "result.json").write_text(
            json.dumps(result_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as error:
        print(f"Echec de l'article hebdomadaire: {error}", file=sys.stderr)
        return 1

    if article.should_create:
        print(f"Article pret: {len(article.matches)} rencontre(s), slug={article.slug}.")
    else:
        print("Aucune rencontre a domicile: aucun article a creer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
