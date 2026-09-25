from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.auth import HTTPBasicAuth

from .models import Match


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNC_MARKER = re.compile(r"CSBW_SYNC:([^:\"']+)")
ICBAD_LINK = re.compile(r"https?://icbad\.ffbad\.org/rencontre/(\d+)(?=[/\s\"'<>?#]|$)")


def sidebar_week_start(now: datetime) -> date:
    """Switch to the next week on Sunday evening."""
    today = now.date()
    if today.weekday() == 6 and now.hour >= 18:
        return today + timedelta(days=1)
    return today - timedelta(days=today.weekday())


def select_week_matches(matches: list[Match], week_start: date) -> list[Match]:
    end_exclusive = week_start + timedelta(days=7)
    return sorted(
        (match for match in matches if week_start <= match.start.date() < end_exclusive),
        key=lambda item: (item.start, item.team, item.id),
    )


def event_payload(
    match: Match,
    category_id: int,
    home_location_id: int | None,
    home_venue_patterns: list[str],
) -> dict[str, Any]:
    end = match.start + timedelta(hours=3)
    title = f"{match.home_team} - {match.away_team}"
    venue = html.escape(match.venue) if match.venue else "Lieu à confirmer"
    source_url = html.escape(match.source_url, quote=True)
    content = (
        f"<p><strong>Rencontre d’interclub</strong><br>"
        f"{html.escape(match.division)}<br>"
        f"📍 {venue}</p>\n"
        f'<p><a href="{source_url}" title="CSBW_SYNC:{html.escape(match.id, quote=True)}">'
        "Voir la fiche ICbad</a></p>"
    )
    payload: dict[str, Any] = {
        "event_name": title,
        "content": content,
        "event_type": "single",
        "post_status": "publish",
        "event_start_date": match.start.date().isoformat(),
        "event_end_date": end.date().isoformat(),
        "event_start_time": match.start.strftime("%H:%M:%S"),
        "event_end_time": end.strftime("%H:%M:%S"),
        "event_timezone": str(match.start.tzinfo or "Europe/Paris"),
        "event_rsvp": 0,
        "event_active_status": 1,
        "event_private": 0,
        "event_categories": [category_id],
        "em_attributes": {"badnet": match.source_url},
    }
    venue_lower = (match.venue or "").casefold()
    if (
        match.is_home
        and home_location_id is not None
        and any(pattern.casefold() in venue_lower for pattern in home_venue_patterns)
    ):
        payload["location_id"] = home_location_id
    return payload


def marker_id(event: dict[str, Any]) -> str | None:
    value = event.get("content", "")
    content = str(value.get("raw", value.get("rendered", ""))) if isinstance(value, dict) else str(value)
    found = SYNC_MARKER.search(content)
    if found:
        return found.group(1)
    links = set(ICBAD_LINK.findall(html.unescape(content)))
    if len(links) == 1:
        return links.pop()
    if len(links) > 1:
        raise ValueError("Plusieurs rencontres ICbad dans un evenement : verification manuelle requise.")
    return None


def sync_events_manager_week(
    matches: list[Match],
    week_start: date,
    wordpress_url: str,
    username: str,
    application_password: str,
    category_id: int,
    home_location_id: int | None,
    home_venue_patterns: list[str],
    session: requests.Session | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not username or not application_password:
        raise ValueError("WP_USERNAME et WP_APPLICATION_PASSWORD sont requis.")

    selected = select_week_matches(matches, week_start)
    week_end = week_start + timedelta(days=6)
    client = session or requests.Session()
    client.auth = HTTPBasicAuth(username, application_password)
    client.headers.update({"User-Agent": "CSBW-Wittelsheim-interclubs-widget/1.0"})
    endpoint = f"{wordpress_url.rstrip('/')}/wp-json/events-manager/v1/events"
    response = client.get(
        endpoint,
        params={
            "scope": f"{week_start.isoformat()},{week_end.isoformat()}",
            "category": category_id,
            "context": "edit",
            "per_page": 100,
        },
        timeout=30,
    )
    if response.status_code == 404:
        return {
            "action": "skipped",
            "reason": "events_manager_api_unavailable",
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
        }
    response.raise_for_status()
    raw = response.json()
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Liste Events Manager non reconnue : synchronisation arretee.")
    # Refuse an incomplete page rather than risk creating duplicates.
    if len(items) >= 100:
        raise ValueError("Trop d'evenements pour une page : verification requise.")
    existing = {}
    for event in items:
        if not isinstance(event, dict):
            continue
        synced_id = marker_id(event)
        if synced_id is None:
            continue
        if synced_id in existing:
            raise ValueError(f"Rencontre ICbad {synced_id} presente plusieurs fois : synchronisation arretee.")
        existing[synced_id] = event

    created = 0
    updated = 0
    for match in selected:
        payload = event_payload(
            match,
            category_id=category_id,
            home_location_id=home_location_id,
            home_venue_patterns=home_venue_patterns,
        )
        current = existing.get(match.id)
        if current:
            event_id = current["id"]
            # Keep editorial titles, descriptions and assigned venues on existing events.
            for field in ("event_name", "content", "location_id"):
                payload.pop(field, None)
            if not dry_run:
                saved = client.patch(f"{endpoint}/{event_id}", json=payload, timeout=30)
                saved.raise_for_status()
            updated += 1
        else:
            if not dry_run:
                saved = client.post(endpoint, json=payload, timeout=30)
                saved.raise_for_status()
            created += 1

    return {
        "action": "dry_run" if dry_run else "synced",
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "matches": len(selected),
        "created": created,
        "updated": updated,
    }


def load_matches(path: Path) -> list[Match]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Match.from_dict(item) for item in payload.get("matches", [])]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronise le bloc Interclub de WordPress.")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.json")
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / "public" / "rencontres.json")
    parser.add_argument("--week-start", type=date.fromisoformat, help="Lundi ciblé (AAAA-MM-JJ).")
    parser.add_argument("--dry-run", action="store_true", help="Verifier sans publier ni modifier les evenements.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.resolve().read_text(encoding="utf-8"))
    timezone = ZoneInfo(config.get("timezone", "Europe/Paris"))
    week_start = args.week_start or sidebar_week_start(datetime.now(timezone))
    try:
        result = sync_events_manager_week(
            load_matches(args.data.resolve()),
            week_start=week_start,
            wordpress_url=os.environ.get("WP_URL", config.get("wordpress_url", "https://www.csbw.fr")),
            username=os.environ.get("WP_USERNAME", ""),
            application_password=os.environ.get("WP_APPLICATION_PASSWORD", ""),
            category_id=int(config.get("events_manager_category_id", 9)),
            home_location_id=config.get("events_manager_home_location_id"),
            home_venue_patterns=config.get("home_venue_patterns", ["salle pierre albouy"]),
            dry_run=args.dry_run,
        )
    except Exception as error:
        print(f"Echec de la synchronisation du bloc Interclub: {error}", file=sys.stderr)
        return 1

    if result["action"] == "skipped":
        print("Bloc Interclub non synchronise: API Events Manager indisponible.")
    elif result["action"] == "dry_run":
        print(
            f"Simulation sans modification: {result['matches']} rencontre(s), "
            f"{result['created']} a creer, {result['updated']} deja presente(s)."
        )
    else:
        print(
            f"Bloc Interclub synchronise: {result['matches']} rencontre(s), "
            f"{result['created']} creee(s), {result['updated']} mise(s) a jour."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
