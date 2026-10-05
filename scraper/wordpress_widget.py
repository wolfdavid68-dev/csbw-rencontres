"""Read or update the Events Manager "Interclub" widget through the WordPress REST API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from requests.auth import HTTPBasicAuth


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIDGET_ID = "em_widget-10"
FORMAT_FILE = PROJECT_ROOT / "templates" / "interclub-widget-format.html"


def php_unserialize(data: bytes) -> Any:
    """Decode the PHP serialize() subset WordPress uses for widget settings."""

    def parse(pos: int) -> tuple[Any, int]:
        kind = data[pos:pos + 1]
        if kind == b"N":
            return None, pos + 2
        if kind in (b"i", b"b", b"d"):
            end = data.index(b";", pos)
            raw = data[pos + 2:end].decode()
            value: Any = int(raw) if kind == b"i" else bool(int(raw)) if kind == b"b" else float(raw)
            return value, end + 1
        if kind == b"s":
            colon = data.index(b":", pos + 2)
            length = int(data[pos + 2:colon])
            start = colon + 2
            return data[start:start + length].decode("utf-8"), start + length + 2
        if kind == b"a":
            colon = data.index(b":", pos + 2)
            count = int(data[pos + 2:colon])
            pos = colon + 2
            result: dict[Any, Any] = {}
            for _ in range(count):
                key, pos = parse(pos)
                value, pos = parse(pos)
                result[key] = value
            return result, pos + 1
        raise ValueError(f"Type PHP non pris en charge : {kind!r}")

    value, _ = parse(0)
    return value


def read_instance(client: requests.Session, base: str) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.get(f"{base}/wp-json/wp/v2/widgets/{WIDGET_ID}", params={"context": "edit"}, timeout=30)
    response.raise_for_status()
    widget = response.json()
    instance = widget.get("instance") or {}
    if isinstance(instance.get("raw"), dict):
        return widget, instance["raw"]
    if "encoded" not in instance:
        raise ValueError("Réglages du widget illisibles.")
    return widget, php_unserialize(base64.b64decode(instance["encoded"]))


def form_data(number: str, settings: dict[str, Any]) -> str:
    """Encode settings as the classic widget form so EM's update() receives every field."""
    fields = []
    for key, value in settings.items():
        if value is None or value is False:
            continue  # Unchecked checkbox: absent from a submitted form.
        if value is True:
            value = 1
        fields.append((f"widget-em_widget[{number}][{key}]", str(value)))
    return urlencode(fields)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lit ou met à jour le widget Interclub de WordPress.")
    parser.add_argument("--apply", action="store_true", help="Remplacer la mise en forme par celle du projet.")
    args = parser.parse_args()

    username = os.environ.get("WP_USERNAME", "")
    password = os.environ.get("WP_APPLICATION_PASSWORD", "")
    if not username or not password:
        print("Identifiants WordPress absents.", file=sys.stderr)
        return 1
    base = os.environ.get("WP_URL", "https://www.csbw.fr").rstrip("/")
    client = requests.Session()
    client.auth = HTTPBasicAuth(username, password)
    client.headers["User-Agent"] = "CSBW-Interclub-widget/1.0"

    try:
        widget, settings = read_instance(client, base)
        print(f"Widget {WIDGET_ID} ({widget.get('id_base')}, zone {widget.get('sidebar')}) :")
        print(json.dumps(settings, ensure_ascii=False, indent=2))
        if not args.apply:
            return 0

        new_format = FORMAT_FILE.read_text(encoding="utf-8").strip()
        updated = {**settings, "format": new_format}
        number = WIDGET_ID.rsplit("-", 1)[1]
        response = client.put(
            f"{base}/wp-json/wp/v2/widgets/{WIDGET_ID}",
            json={"form_data": form_data(number, updated)},
            timeout=30,
        )
        response.raise_for_status()
        _, saved = read_instance(client, base)
        changed = sorted(key for key in set(settings) | set(saved)
                         if key != "format" and settings.get(key) != saved.get(key))
        if saved.get("format", "").strip() != new_format:
            raise ValueError("WordPress n'a pas enregistré la nouvelle mise en forme.")
        print("Mise en forme du widget mise à jour.")
        if changed:
            print(f"Autres réglages modifiés par WordPress : {', '.join(changed)}")
    except Exception as error:
        print(f"Échec du widget Interclub : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
