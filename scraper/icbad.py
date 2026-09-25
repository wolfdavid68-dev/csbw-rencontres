from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Competition, Match, ScrapeResult, Team


BASE_URL = "https://icbad.ffbad.org/"
SENIOR_EXCLUSIONS = (
    "jeune",
    "veteran",
    "corpo",
    "minibad",
    "poussin",
    "benjamin",
    "minime",
    "cadet",
)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().lower()


def clean_text(value: str | Tag | None) -> str:
    if value is None:
        return ""
    if isinstance(value, Tag):
        value = value.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", str(value)).strip()


def is_senior_competition(name: str) -> bool:
    simplified = normalize(name)
    return "interclub" in simplified and not any(
        excluded in simplified for excluded in SENIOR_EXCLUSIONS
    )


def competition_from_link(link: Tag) -> Competition | None:
    href = link.get("href", "")
    match = re.search(r"/competition/(\d+)", href)
    if not match:
        return None
    return Competition(
        id=match.group(1),
        name=clean_text(link),
        url=urljoin(BASE_URL, href),
    )


def discover_competitions(
    html: str,
    league_code: str,
    committee_code: str,
    include_national: bool = True,
    extra_ids: Iterable[str] = (),
) -> list[Competition]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Competition] = {}

    def add_links(container: Tag | None, recursive: bool = True) -> None:
        if container is None:
            return
        for link in container.find_all("a", href=re.compile(r"/competition/\d+"), recursive=recursive):
            competition = competition_from_link(link)
            if competition and is_senior_competition(competition.name):
                found[competition.id] = competition

    if include_national:
        for link in soup.find_all("a", href=re.compile(r"/competition/\d+")):
            label = normalize(clean_text(link))
            if "interclubs nationaux" in label or "phase finale n" in label:
                competition = competition_from_link(link)
                if competition and is_senior_competition(competition.name):
                    found[competition.id] = competition

    league_menu = soup.find("ul", attrs={"data-accueil-menu-id": league_code})
    if league_menu:
        for item in league_menu.find_all("li", recursive=False):
            direct_link = item.find("a", href=re.compile(r"/competition/\d+"), recursive=False)
            if direct_link:
                competition = competition_from_link(direct_link)
                if competition and is_senior_competition(competition.name):
                    found[competition.id] = competition

    committee_menu = soup.find("ul", attrs={"data-accueil-menu-id": committee_code})
    add_links(committee_menu)

    for competition_id in extra_ids:
        competition_id = str(competition_id).strip()
        if competition_id and competition_id not in found:
            found[competition_id] = Competition(
                id=competition_id,
                name=f"Compétition ICbad {competition_id}",
                url=urljoin(BASE_URL, f"competition/{competition_id}"),
            )

    return sorted(found.values(), key=lambda item: (normalize(item.name), item.id))


def parse_teams(html: str, competition: Competition, club_code: str) -> list[Team]:
    soup = BeautifulSoup(html, "html.parser")
    competition_name = clean_text(soup.find("h1")) or competition.name
    found: dict[str, Team] = {}

    for link in soup.find_all("a", href=re.compile(r"/equipe/\d+")):
        label = clean_text(link)
        if normalize(club_code) not in normalize(label):
            continue

        id_match = re.search(r"/equipe/(\d+)", link.get("href", ""))
        code_match = re.search(r"\(([^()]*CSBW[^()]*)\)", label, re.IGNORECASE)
        if not id_match or not code_match:
            continue

        code = clean_text(code_match.group(1))
        number_match = re.search(r"CSBW-+(\d+)", code, re.IGNORECASE)
        team_label = f"CSBW {number_match.group(1)}" if number_match else code
        pool_heading = link.find_previous("h2")
        pool = clean_text(pool_heading) if pool_heading else ""
        division = competition_name
        if pool and normalize(pool) not in normalize(competition_name):
            division = f"{competition_name} - {pool}"

        found[id_match.group(1)] = Team(
            id=id_match.group(1),
            name=re.sub(r"\s*\([^()]*CSBW[^()]*\)\s*$", "", label, flags=re.IGNORECASE),
            code=code,
            label=team_label,
            competition=competition_name,
            division=division,
            url=urljoin(BASE_URL, link.get("href", "")),
        )

    return sorted(found.values(), key=lambda item: (item.label, item.id))


def _season_datetime(
    value: str,
    season_start_year: int,
    timezone: ZoneInfo,
) -> datetime:
    match = re.search(r"(\d{1,2})/(\d{1,2})\s*(?:à|a)\s*(\d{1,2}):(\d{2})", normalize(value))
    if not match:
        raise ValueError(f"Date ICbad non reconnue: {value}")
    day, month, hour, minute = (int(part) for part in match.groups())
    year = season_start_year if month >= 7 else season_start_year + 1
    return datetime(year, month, day, hour, minute, tzinfo=timezone)


def parse_matches(
    html: str,
    team: Team,
    club_code: str,
    season_start_year: int,
    timezone: ZoneInfo,
    now: datetime,
) -> list[Match]:
    soup = BeautifulSoup(html, "html.parser")
    schedule = None
    for table in soup.find_all("table"):
        headers = normalize(" ".join(clean_text(header) for header in table.find_all("th")))
        if all(label in headers for label in ("journee", "date", "lieu", "resultat")):
            schedule = table
            break

    if schedule is None:
        return []

    matches: list[Match] = []
    for row in schedule.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 6:
            continue
        date_link = cells[1].find("a", href=re.compile(r"/rencontre/\d+"))
        if date_link is None:
            continue

        id_match = re.search(r"/rencontre/(\d+)", date_link.get("href", ""))
        if id_match is None:
            continue
        try:
            start = _season_datetime(clean_text(date_link), season_start_year, timezone)
        except ValueError:
            continue

        round_match = re.search(r"J\s*(\d+)", clean_text(cells[0]), re.IGNORECASE)
        home_team = clean_text(cells[3])
        away_team = clean_text(cells[5])
        score_match = re.search(r"(\d+)\s*-\s*(\d+)", clean_text(cells[4]))
        score = f"{score_match.group(1)}-{score_match.group(2)}" if score_match else None
        if start > now and score == "0-0":
            score = None

        is_home = normalize(club_code) in normalize(home_team)
        opponent = away_team if is_home else home_team
        opponent = re.sub(r"\s*\([^()]+\)\s*$", "", opponent).strip()
        status_node = cells[0].find(class_=re.compile(r"rencontre-statut"))
        source_status = clean_text(status_node.get("title")) if status_node else None

        matches.append(
            Match(
                id=id_match.group(1),
                team_id=team.id,
                team=team.label,
                team_code=team.code,
                division=team.division,
                round_number=int(round_match.group(1)) if round_match else None,
                start=start,
                home_team=home_team,
                away_team=away_team,
                opponent=opponent,
                is_home=is_home,
                venue=clean_text(cells[2]) or None,
                score=score,
                source_url=urljoin(BASE_URL, date_link.get("href", "")),
                source_status=source_status,
            )
        )

    return sorted(matches, key=lambda item: (item.start, item.team, item.id))


class ICBadClient:
    def __init__(self, config: dict, no_delay: bool = False) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "CSBW-Wittelsheim-calendar/1.0 "
                    "(+https://www.csbw.fr/; webmaster calendar fetch)"
                )
            }
        )
        retries = Retry(
            total=4,
            connect=4,
            read=4,
            status=4,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.timeout = int(config.get("request_timeout_seconds", 30))
        self.delay = 0.0 if no_delay else float(config.get("request_delay_seconds", 1.0))
        self._has_requested = False

    def get(self, url: str, params: dict | None = None) -> str:
        if self._has_requested and self.delay:
            time.sleep(self.delay)
        response = self.session.get(url, params=params, timeout=self.timeout)
        self._has_requested = True
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def scrape(self, season_start_year: int | None = None) -> ScrapeResult:
        season_start_year = int(season_start_year or self.config["season_start_year"])
        timezone = ZoneInfo(self.config.get("timezone", "Europe/Paris"))
        now = datetime.now(timezone)
        season = f"{season_start_year}-{season_start_year + 1}"

        homepage = self.get(BASE_URL, params={"switchSaison": season_start_year})
        competitions = discover_competitions(
            homepage,
            league_code=self.config.get("league_code", "GEST"),
            committee_code=self.config.get("committee_code", "CD68"),
            include_national=bool(self.config.get("include_national_competitions", True)),
            extra_ids=self.config.get("competition_ids", []),
        )

        result = ScrapeResult(
            season=season,
            generated_at=now,
            status="awaiting_publication",
            competitions=competitions,
        )
        if not competitions:
            result.warnings.append(
                "Les compétitions Grand Est / Comité 68 ne sont pas encore publiées sur ICbad."
            )
            return result

        teams_by_id: dict[str, Team] = {}
        for competition in competitions:
            html = self.get(competition.url)
            for team in parse_teams(html, competition, self.config["club_code"]):
                teams_by_id[team.id] = team
        result.teams = sorted(teams_by_id.values(), key=lambda item: (item.label, item.id))
        if not result.teams:
            result.status = "awaiting_teams"
            result.warnings.append(
                "Aucune équipe senior CSBW n'est encore inscrite dans les compétitions publiées."
            )
            return result

        matches_by_id: dict[str, Match] = {}
        for team in result.teams:
            html = self.get(team.url)
            for match in parse_matches(
                html,
                team=team,
                club_code=self.config["club_code"],
                season_start_year=season_start_year,
                timezone=timezone,
                now=now,
            ):
                matches_by_id[match.id] = match
        result.matches = sorted(matches_by_id.values(), key=lambda item: (item.start, item.team, item.id))
        result.status = "ready" if result.matches else "awaiting_schedule"
        if not result.matches:
            result.warnings.append("Les équipes sont publiées, mais leur calendrier est encore vide.")
        return result
