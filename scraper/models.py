from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Competition:
    id: str
    name: str
    url: str


@dataclass(slots=True)
class Team:
    id: str
    name: str
    code: str
    label: str
    competition: str
    division: str
    url: str


@dataclass(slots=True)
class Match:
    id: str
    team_id: str
    team: str
    team_code: str
    division: str
    round_number: int | None
    start: datetime
    home_team: str
    away_team: str
    opponent: str
    is_home: bool
    venue: str | None
    score: str | None
    source_url: str
    source_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["start"] = self.start.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Match":
        values = dict(data)
        if isinstance(values.get("start"), str):
            values["start"] = datetime.fromisoformat(values["start"])
        return cls(**values)


@dataclass(slots=True)
class ScrapeResult:
    season: str
    generated_at: datetime
    status: str
    competitions: list[Competition] = field(default_factory=list)
    teams: list[Team] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "generated_at": self.generated_at.isoformat(),
            "status": self.status,
            "warnings": self.warnings,
            "competitions": [asdict(item) for item in self.competitions],
            "teams": [asdict(item) for item in self.teams],
            "matches": [item.to_dict() for item in self.matches],
        }
