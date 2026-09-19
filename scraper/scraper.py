from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .demo import build_demo_result
from .icbad import ICBadClient
from .render import apply_overrides, write_outputs


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Génère le calendrier senior CSBW depuis ICbad.")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.json")
    parser.add_argument("--season", type=int, help="Année de début de saison, par exemple 2026.")
    parser.add_argument("--output-dir", type=Path, help="Dossier de sortie à la place de config.json.")
    parser.add_argument("--no-delay", action="store_true", help="Désactive les pauses (tests locaux uniquement).")
    parser.add_argument("--demo", action="store_true", help="Génère un aperçu fictif sans interroger ICbad.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    season = args.season or int(config["season_start_year"])
    default_output = Path("build-demo") if args.demo else Path(config.get("output_dir", "public"))
    output_dir = args.output_dir or default_output
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    overrides_path = Path(config.get("manual_overrides_file", "overrides.json"))
    if not overrides_path.is_absolute():
        overrides_path = PROJECT_ROOT / overrides_path

    try:
        if args.demo:
            result = build_demo_result(config.get("timezone", "Europe/Paris"))
            render_config = {**config, "site_title": "Aperçu test - Rencontres seniors du CSBW"}
        else:
            result = ICBadClient(config, no_delay=args.no_delay).scrape(season)
            apply_overrides(result, overrides_path)
            render_config = config
        write_outputs(result, output_dir, PROJECT_ROOT / "templates", render_config)
        logo_source = PROJECT_ROOT / "assets" / "csbw-192.png"
        if logo_source.exists():
            shutil.copy2(logo_source, output_dir / "csbw-192.png")
    except Exception as error:
        print(f"Echec de la mise a jour ICbad: {error}", file=sys.stderr)
        return 1

    logical_teams = len({team.code for team in result.teams})
    print(
        f"Saison {result.season}: {logical_teams} equipe(s), "
        f"{len(result.matches)} rencontre(s), etat={result.status}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
