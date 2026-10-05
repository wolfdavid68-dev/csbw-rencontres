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
UNKNOWN_VENUE = "Lieu à confirmer"
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


def event_title(match: Match) -> str:
    """Short widget title: home side first, CSBW team label and opponent without club codes."""
    if match.is_home:
        return f"{match.team} – {match.opponent}"
    return f"{match.opponent} – {match.team}"


def legacy_title(match: Match) -> str:
    return f"{match.home_team} - {match.away_team}"


def event_name(event: dict[str, Any]) -> str:
    value = event.get("name", event.get("event_name", ""))
    if isinstance(value, dict):
        value = value.get("raw", value.get("rendered", ""))
    return html.unescape(str(value)).strip()


def event_payload(
    match: Match,
    category_id: int,
    home_location_id: int | None,
    home_venue_patterns: list[str],
) -> dict[str, Any]:
    end = match.start + timedelta(hours=3)
    title = event_title(match)
    venue = html.escape(match.venue) if match.venue else UNKNOWN_VENUE
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
        "event_all_day": 0,
        # Matches read back from JSON carry a fixed offset ("UTC+02:00"): store the club's zone.
        "event_timezone": getattr(match.start.tzinfo, "key", "Europe/Paris"),
        "event_rsvp": 0,
        "event_active_status": 1,
        "event_private": 0,
        "event_categories": [category_id],
        "em_attributes": {"badnet": match.source_url},
    }
    if not match.time_known:
        # Keep the match on its day until ICbad publishes the time.
        payload.update({
            "event_end_date": match.start.date().isoformat(),
            "event_start_time": "00:00:00",
            "event_end_time": "23:59:59",
            "event_all_day": 1,
        })
    venue_lower = (match.venue or "").casefold()
    if (
        match.is_home
        and home_location_id is not None
        and (not match.venue or any(pattern.casefold() in venue_lower for pattern in home_venue_patterns))
    ):
        payload["location_id"] = home_location_id
    return payload


def event_content(event: dict[str, Any]) -> str:
    value = event.get("content", "")
    return str(value.get("raw", value.get("rendered", ""))) if isinstance(value, dict) else str(value)


def is_truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


def event_schedule(event: dict[str, Any]) -> tuple[bool, str, str | None] | None:
    """Stored day and start time of an event, or None when the API did not return them."""
    when = event.get("when")
    if not isinstance(when, dict) or not when.get("start_date"):
        return None
    if is_truthy(when.get("all_day")):
        return True, str(when["start_date"]), None
    return False, str(when["start_date"]), str(when.get("start_time") or "")[:5]


def payload_schedule(payload: dict[str, Any]) -> tuple[bool, str, str | None]:
    if payload["event_all_day"]:
        return True, payload["event_start_date"], None
    return False, payload["event_start_date"], payload["event_start_time"][:5]


def event_location_id(event: dict[str, Any]) -> int | None:
    location = event.get("location")
    if isinstance(location, dict) and location.get("id"):
        return int(location["id"])
    return None


def check_write(response: requests.Response, action: str) -> None:
    """Raise with the server's answer, which a bare HTTP status hides."""
    if response.status_code < 400:
        return
    detail = " ".join(re.sub(r"<[^>]+>", " ", response.text or "").split())[:300]
    raise ValueError(f"{action} refusee par WordPress (HTTP {response.status_code}) : {detail or 'reponse vide'}")


def marker_id(event: dict[str, Any]) -> str | None:
    content = event_content(event)
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
    recreated = 0
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
            # Keep editorial titles, descriptions and assigned venues on existing events,
            # except our own placeholder written before ICbad published the venue.
            content = event_content(current)
            preserved = []
            if event_name(current) not in (legacy_title(match), event_title(match)):
                preserved.append("event_name")
            if not (SYNC_MARKER.search(content) and UNKNOWN_VENUE in html.unescape(content)):
                preserved += ["content", "location_id"]
            stored = event_schedule(current)
            if SYNC_MARKER.search(content) and stored is not None and stored != payload_schedule(payload):
                # Events Manager ignores time changes on existing events through its API:
                # create the corrected event, then move ours to the trash.
                if "event_name" in preserved:
                    payload["event_name"] = event_name(current)
                if "content" in preserved:
                    payload["content"] = content
                    payload.pop("location_id", None)
                    if event_location_id(current) is not None:
                        payload["location_id"] = event_location_id(current)
                if not dry_run:
                    check_write(client.post(endpoint, json=payload, timeout=30), f"Creation de {match.id}")
                    check_write(client.delete(f"{endpoint}/{event_id}", timeout=30), f"Corbeille de {event_id}")
                recreated += 1
                continue
            for field in preserved:
                payload.pop(field, None)
            if not dry_run:
                check_write(client.patch(f"{endpoint}/{event_id}", json=payload, timeout=30), f"Mise a jour de {match.id}")
            updated += 1
        else:
            if not dry_run:
                check_write(client.post(endpoint, json=payload, timeout=30), f"Creation de {match.id}")
            created += 1

    return {
        "action": "dry_run" if dry_run else "synced",
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "matches": len(selected),
        "created": created,
        "updated": updated,
        "recreated": recreated,
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
            f"{result['created']} a creer, {result['updated']} deja presente(s), {result['recreated']} a recreer (heure modifiee)."
        )
    else:
        print(
            f"Bloc Interclub synchronise: {result['matches']} rencontre(s), "
            f"{result['created']} creee(s), {result['updated']} mise(s) a jour, {result['recreated']} recreee(s) a la nouvelle heure."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
