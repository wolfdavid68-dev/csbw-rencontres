from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .models import Match, ScrapeResult


def build_demo_result(timezone_name: str = "Europe/Paris") -> ScrapeResult:
    timezone = ZoneInfo(timezone_name)
    generated_at = datetime(2026, 7, 10, 10, 0, tzinfo=timezone)

    def match(
        match_id: str,
        team_number: int,
        start: datetime,
        opponent: str,
        is_home: bool,
        venue: str,
        score: str | None = None,
        round_number: int = 1,
    ) -> Match:
        team = f"CSBW {team_number}"
        home_team = team if is_home else opponent
        away_team = opponent if is_home else team
        return Match(
            id=match_id,
            team_id=f"demo-{team_number}",
            team=team,
            team_code=f"68-CSBW-{team_number}",
            division=f"Interclubs seniors - Division {team_number}",
            round_number=round_number,
            start=start,
            home_team=home_team,
            away_team=away_team,
            opponent=opponent,
            is_home=is_home,
            venue=venue,
            score=score,
            source_url="https://icbad.ffbad.org/",
            source_status="Démonstration",
        )

    matches = [
        match(
            "demo-result-1",
            1,
            datetime(2026, 6, 5, 20, 30, tzinfo=timezone),
            "Badminton Club Mulhouse",
            True,
            "Salle Pierre Albouy, 68310 Wittelsheim",
            score="5-3",
            round_number=10,
        ),
        match(
            "demo-home-1",
            1,
            datetime(2026, 9, 4, 20, 30, tzinfo=timezone),
            "Badminton Club Mulhouse",
            True,
            "Salle Pierre Albouy, 68310 Wittelsheim",
        ),
        match(
            "demo-home-3",
            3,
            datetime(2026, 9, 4, 20, 30, tzinfo=timezone),
            "Colmar Badminton Racing",
            True,
            "Salle Pierre Albouy, 68310 Wittelsheim",
        ),
        match(
            "demo-home-5",
            5,
            datetime(2026, 9, 6, 10, 0, tzinfo=timezone),
            "Sundgau Badminton",
            True,
            "Salle Pierre Albouy, 68310 Wittelsheim",
        ),
        match(
            "demo-away-2",
            2,
            datetime(2026, 9, 11, 20, 0, tzinfo=timezone),
            "Volant des Trois Frontières",
            False,
            "La Comète, 68220 Hésingue",
            round_number=2,
        ),
        match(
            "demo-home-4",
            4,
            datetime(2026, 9, 18, 20, 30, tzinfo=timezone),
            "Badminton Club Reiningue",
            True,
            "Salle Pierre Albouy, 68310 Wittelsheim",
            round_number=3,
        ),
    ]
    return ScrapeResult(
        season="2026-2027",
        generated_at=generated_at,
        status="ready",
        matches=matches,
        warnings=["Données fictives utilisées uniquement pour l'aperçu."],
    )
