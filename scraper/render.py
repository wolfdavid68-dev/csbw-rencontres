from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Match, ScrapeResult


def apply_overrides(result: ScrapeResult, overrides_path: Path) -> None:
    if not overrides_path.exists():
        return
    payload = json.loads(overrides_path.read_text(encoding="utf-8"))
    deleted = {str(item) for item in payload.get("delete", [])}
    by_id = {item.id: item for item in result.matches if item.id not in deleted}

    for patch in payload.get("upsert", []):
        patch = dict(patch)
        match_id = str(patch.get("id", "")).strip()
        if not match_id:
            raise ValueError("Chaque surcharge manuelle doit avoir un champ 'id'.")
        if patch.get("season") and patch["season"] != result.season:
            continue
        patch.pop("season", None)

        if match_id in by_id:
            values = by_id[match_id].to_dict()
            values.update(patch)
            by_id[match_id] = Match.from_dict(values)
        else:
            is_home = bool(patch.get("is_home", True))
            team = patch.get("team", "CSBW")
            opponent = patch.get("opponent", "Adversaire à confirmer")
            values = {
                "id": match_id,
                "team_id": "manual",
                "team": team,
                "team_code": patch.get("team_code", "68-CSBW"),
                "division": patch.get("division", "Rencontre ajoutée manuellement"),
                "round_number": patch.get("round_number"),
                "start": patch["start"],
                "home_team": patch.get("home_team", team if is_home else opponent),
                "away_team": patch.get("away_team", opponent if is_home else team),
                "opponent": opponent,
                "is_home": is_home,
                "venue": patch.get("venue"),
                "score": patch.get("score"),
                "source_url": patch.get("source_url", "https://www.csbw.fr/"),
                "source_status": patch.get("source_status", "Ajout manuel"),
            }
            by_id[match_id] = Match.from_dict(values)

    result.matches = sorted(by_id.values(), key=lambda item: (item.start, item.team, item.id))
    if result.matches:
        result.status = "ready"


def _ics_escape(value: str | None) -> str:
    return (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_datetime(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S")


def render_ics(result: ScrapeResult, timezone_name: str) -> str:
    stamp = result.generated_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CSBW Wittelsheim//Rencontres seniors//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:CSBW - Rencontres {result.season}",
        f"X-WR-TIMEZONE:{timezone_name}",
    ]
    for match in result.matches:
        home_label = match.team if match.is_home else match.opponent
        away_label = match.opponent if match.is_home else match.team
        summary = f"Badminton : {home_label} - {away_label}"
        description = f"{match.division} - Journée {match.round_number or '-'}"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:icbad-{_ics_escape(match.id)}@csbw.fr",
                f"DTSTAMP:{stamp}",
                f"DTSTART;TZID={timezone_name}:{_ics_datetime(match.start)}",
                f"DTEND;TZID={timezone_name}:{_ics_datetime(match.start + timedelta(hours=3))}",
                f"SUMMARY:{_ics_escape(summary)}",
                f"DESCRIPTION:{_ics_escape(description)}",
                f"LOCATION:{_ics_escape(match.venue)}",
                f"URL:{_ics_escape(match.source_url)}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_outputs(
    result: ScrapeResult,
    output_dir: Path,
    template_dir: Path,
    config: dict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    data = result.to_dict()
    (output_dir / "rencontres.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "calendrier.ics").write_text(
        render_ics(result, config.get("timezone", "Europe/Paris")),
        encoding="utf-8",
        newline="",
    )

    now = result.generated_at
    upcoming = [match for match in result.matches if match.start >= now]
    past = [match for match in result.matches if match.start < now]
    def team_sort_key(label: str) -> tuple[str, int, str]:
        number = re.search(r"(\d+)$", label)
        prefix = re.sub(r"\s*\d+$", "", label)
        return (prefix, int(number.group(1)) if number else 9999, label)

    teams = sorted({match.team for match in result.matches}, key=team_sort_key)

    def present(match: Match) -> dict:
        values = match.to_dict()
        values["date_label"] = match.start.strftime("%d/%m/%Y")
        values["time_label"] = match.start.strftime("%Hh%M")
        values["weekday_label"] = [
            "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"
        ][match.start.weekday()]
        values["maps_url"] = (
            f"https://www.google.com/maps/search/?api=1&query={quote_plus(match.venue)}"
            if match.venue
            else None
        )
        return values

    environment = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = environment.get_template("page.html.j2")
    rendered = template.render(
        title=config.get("site_title", "Rencontres seniors du CSBW"),
        season=result.season,
        status=result.status,
        warnings=result.warnings,
        generated_label=now.strftime("%d/%m/%Y à %Hh%M"),
        upcoming=[present(item) for item in upcoming],
        past=[present(item) for item in reversed(past)],
        teams=teams,
        total=len(result.matches),
    )
    rendered = re.sub(r"\n{3,}", "\n\n", rendered).strip() + "\n"
    (output_dir / "index.html").write_text(rendered, encoding="utf-8")
