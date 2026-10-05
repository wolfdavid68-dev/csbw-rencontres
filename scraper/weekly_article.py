from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.auth import HTTPBasicAuth

from .demo import build_demo_result
from .icbad import ICBadClient, normalize
from .models import Match, ScrapeResult
from .render import apply_overrides
from .wordpress_events import sync_events_manager_week


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


def sunday_publication_time(week_start: date) -> datetime:
    if week_start.weekday() != 0:
        raise ValueError("La semaine ciblee doit commencer un lundi.")
    sunday = week_start - timedelta(days=1)
    return datetime(sunday.year, sunday.month, sunday.day, 19, tzinfo=ZoneInfo("Europe/Paris"))


def load_calendar(path: Path) -> ScrapeResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") != "ready":
        raise ValueError("Le calendrier n'est pas pret pour la publication.")
    return ScrapeResult(
        season=data["season"],
        generated_at=datetime.fromisoformat(data["generated_at"]),
        status=data["status"],
        matches=[Match.from_dict(item) for item in data["matches"]],
        warnings=data.get("warnings", []),
    )


def format_day(value: date) -> str:
    return f"{FRENCH_WEEKDAYS[value.weekday()]} {value.day} {FRENCH_MONTHS[value.month - 1]}"


def format_week(value: date, end: date) -> str:
    if value.month == end.month and value.year == end.year:
        return f"du {value.day} au {end.day} {FRENCH_MONTHS[end.month - 1]}"
    return f"du {value.day} {FRENCH_MONTHS[value.month - 1]} au {end.day} {FRENCH_MONTHS[end.month - 1]}"


def is_pierre_albouy(match: Match, patterns: list[str]) -> bool:
    if not match.is_home:
        return False
    # ICbad leaves the venue empty until the time is published: the club only receives at home.
    if not match.venue:
        return True
    venue = normalize(match.venue)
    return any(normalize(pattern) in venue for pattern in patterns)


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
    title = "🏸 Interclubs de la semaine"
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

    sections: list[str] = [
        '<p style="font-size:17px;line-height:1.6;margin:0 0 6px;">'
        f'<strong>{html.escape(week_label.capitalize())}</strong></p>',
        '<p style="font-size:16px;line-height:1.6;margin:0 0 20px;">'
        '📍 Salle Pierre Albouy</p>',
    ]
    for day, matches in sorted(grouped.items()):
        count = len(matches)
        count_label = "1 rencontre" if count == 1 else f"{count} rencontres"
        day_label = format_day(day).capitalize()
        sections.append(
            '<h2 style="font-size:20px;font-weight:600;line-height:1.5;margin:22px 0 16px;'
            'padding:0 0 12px;border-bottom:2px solid #d00000;">'
            f'📅 {html.escape(day_label)} : <span style="white-space:nowrap;">{count_label}</span></h2>'
        )
        for match in matches:
            time_label = match.start.strftime("%H h %M") if match.time_known else "Horaire à confirmer"
            team = html.escape(match.team)
            opponent = html.escape(match.opponent)
            link = html.escape(match.source_url, quote=True)
            sections.append(
                '<p style="font-size:18px;line-height:1.8;margin:0 0 16px;overflow-wrap:anywhere;">'
                f'🕒 <strong>{time_label}</strong><br>'
                f'<a href="{link}" style="color:inherit;text-decoration:underline;'
                'text-decoration-color:#d00000;text-underline-offset:4px;">'
                f'<strong>{team} reçoit {opponent}</strong></a></p>'
            )

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


def wordpress_request(client: requests.Session, method: str, url: str, **kwargs: Any) -> requests.Response:
    """Retry only reads and updates of a known post, never a creation."""
    delays = (10, 30, 60)
    for attempt in range(len(delays) + 1):
        try:
            response = getattr(client, method)(url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as error:
            if isinstance(error, requests.HTTPError):
                status_code = error.response.status_code if error.response is not None else None
                if status_code not in (429, 500, 502, 503, 504):
                    raise
            if attempt == len(delays):
                raise
            print(f"WordPress temporairement indisponible : nouvelle tentative dans {delays[attempt]} s.",
                  file=sys.stderr)
            time.sleep(delays[attempt])
    raise AssertionError("Unreachable")


def publish_wordpress(
    article: WeeklyArticle,
    wordpress_url: str,
    username: str,
    application_password: str,
    status: str,
    session: requests.Session | None = None,
    skip_published: bool = False,
    schedule_sunday: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not article.should_create and not schedule_sunday:
        return {"action": "skipped", "reason": "no_home_matches"}
    if not username or not application_password:
        raise ValueError("WP_USERNAME et WP_APPLICATION_PASSWORD sont requis.")
    if schedule_sunday and status != "publish":
        raise ValueError("La programmation du dimanche exige --status publish.")
    publish_at = sunday_publication_time(article.week_start) if schedule_sunday else None
    current_time = now or datetime.now(timezone.utc)
    if current_time.utcoffset() is None:
        raise ValueError("L'heure courante doit avoir un fuseau horaire.")

    client = session or requests.Session()
    client.auth = HTTPBasicAuth(username, application_password)
    client.headers.update({"User-Agent": "CSBW-Wittelsheim-weekly-article/1.0"})
    endpoint = f"{wordpress_url.rstrip('/')}/wp-json/wp/v2/posts"
    existing: list[dict[str, Any]] = []
    for post_status in ("publish", "future", "draft", "pending", "private"):
        existing_response = wordpress_request(
            client, "get", endpoint,
            params={"slug": article.slug, "status": post_status, "context": "edit"},
        )
        existing = existing_response.json()
        if existing:
            break
    if existing and post_status == "publish" and (skip_published or schedule_sunday) and status == "publish":
        return {
            "action": "skipped",
            "reason": "already_published",
            "id": existing[0]["id"],
            "status": "publish",
            "link": existing[0].get("link"),
        }
    if not article.should_create:
        if existing and post_status == "future":
            post = wordpress_request(client, "post", f"{endpoint}/{existing[0]['id']}",
                                     json={"status": "draft"}).json()
            if post.get("status") != "draft":
                raise ValueError("WordPress n'a pas confirme l'annulation de la programmation.")
            return {"action": "unscheduled", "reason": "no_home_matches", "id": post["id"],
                    "status": "draft", "link": post.get("link")}
        return {"action": "skipped", "reason": "no_home_matches"}
    if publish_at is not None:
        status = "future" if current_time < publish_at else "publish"
    post_data = {
        "title": article.title,
        "slug": article.slug,
        "excerpt": article.excerpt,
        "content": article.content,
        "status": status,
    }
    if publish_at is not None:
        post_data["date_gmt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    if existing:
        post_id = existing[0]["id"]
        action = "updated"
    else:
        # Reserve one draft first: publication retries then target its stable ID.
        # An ambiguous creation failure must not trigger a second POST /posts.
        response = client.post(endpoint, json={**post_data, "status": "draft"}, timeout=30)
        response.raise_for_status()
        post_id = response.json()["id"]
        action = "created"
    response = wordpress_request(client, "post", f"{endpoint}/{post_id}", json=post_data)
    post = response.json()
    # A retry may finish after the publication deadline has passed.
    published_when_due = (publish_at is not None and post.get("status") == "publish"
                          and (now or datetime.now(timezone.utc)) >= publish_at)
    if post.get("status") != status and not published_when_due:
        raise ValueError(f"Etat WordPress inattendu : {post.get('status')!r}, attendu : {status!r}.")
    if publish_at is not None and post.get("status") == "future" and post.get("date_gmt") != post_data["date_gmt"]:
        raise ValueError("WordPress n'a pas confirme la date de publication demandee.")
    return {
        "action": action,
        "id": post.get("id"),
        "status": post.get("status"),
        "date_gmt": post.get("date_gmt"),
        "link": post.get("link"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crée l'article hebdomadaire d'occupation de la salle.")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.json")
    parser.add_argument("--season", type=int)
    parser.add_argument("--week-start", type=date.fromisoformat, help="Lundi ciblé, au format AAAA-MM-JJ.")
    parser.add_argument("--output-dir", type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true")
    source.add_argument("--data", type=Path, help="Calendrier deja collecte, partage avec le bloc Interclub.")
    parser.add_argument("--no-delay", action="store_true")
    parser.add_argument("--publish-wordpress", action="store_true")
    parser.add_argument("--skip-published", action="store_true",
                        help="Conserver un article deja publie lors des rattrapages automatiques.")
    parser.add_argument("--schedule-sunday", action="store_true",
                        help="Programmer dans WordPress le dimanche precedent a 19 h (Paris).")
    parser.add_argument("--sync-events", action="store_true", help="Synchroniser les evenements avant de publier l'article.")
    parser.add_argument("--status", choices=("draft", "pending", "private", "publish"), default="publish")
    args = parser.parse_args()
    if args.schedule_sunday and args.status != "publish":
        parser.error("--schedule-sunday exige --status publish")
    return args


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.resolve().read_text(encoding="utf-8"))
    timezone = ZoneInfo(config.get("timezone", "Europe/Paris"))
    week_start = args.week_start or next_week_start(datetime.now(timezone))
    output_dir = args.output_dir or Path("build-weekly-demo" if args.demo else "build-weekly")
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    try:
        if args.schedule_sunday:
            sunday_publication_time(week_start)
        if args.demo:
            result = build_demo_result(config.get("timezone", "Europe/Paris"))
        elif args.data:
            result = load_calendar(args.data.resolve())
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
        event_sync = None
        if args.sync_events:
            if args.demo:
                raise ValueError("La synchronisation des evenements est interdite en mode demonstration.")
            event_sync = sync_events_manager_week(
                result.matches,
                week_start=week_start,
                wordpress_url=os.environ.get("WP_URL", config.get("wordpress_url", "https://www.csbw.fr")),
                username=os.environ.get("WP_USERNAME", ""),
                application_password=os.environ.get("WP_APPLICATION_PASSWORD", ""),
                category_id=int(config.get("events_manager_category_id", 9)),
                home_location_id=config.get("events_manager_home_location_id"),
                home_venue_patterns=config.get("home_venue_patterns", ["salle pierre albouy"]),
            )
            if event_sync["action"] != "synced":
                raise ValueError("Events Manager indisponible : publication de l'article arretee.")
            print(
                f"Interclubs synchronises avant l'article: {event_sync['created']} cree(s), "
                f"{event_sync['updated']} mis a jour."
            )
        if args.publish_wordpress:
            publication = publish_wordpress(
                article,
                wordpress_url=os.environ.get("WP_URL", config.get("wordpress_url", "https://www.csbw.fr")),
                username=os.environ.get("WP_USERNAME", ""),
                application_password=os.environ.get("WP_APPLICATION_PASSWORD", ""),
                status=args.status,
                skip_published=args.skip_published,
                schedule_sunday=args.schedule_sunday,
            )
            print(f"WordPress: {publication.get('action')}, etat={publication.get('status')}, "
                  f"date UTC={publication.get('date_gmt')}.")
        result_payload = article.to_dict()
        if publication:
            result_payload["wordpress"] = publication
        if event_sync:
            result_payload["events_manager"] = event_sync
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
