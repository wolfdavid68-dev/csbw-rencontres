"""Read-only check of the Events Manager API and existing ICbad links."""

from __future__ import annotations

import json
import os
import re
import sys

import requests
from requests.auth import HTTPBasicAuth


def main() -> int:
    username = os.environ.get("WP_USERNAME", "")
    password = os.environ.get("WP_APPLICATION_PASSWORD", "")
    if not username or not password:
        print("Identifiants WordPress absents.")
        return 1
    base = os.environ.get("WP_URL", "https://www.csbw.fr").rstrip("/")
    client = requests.Session()
    client.auth = HTTPBasicAuth(username, password)
    client.headers["User-Agent"] = "CSBW-Events-Connection-Check/1.0"
    checks = [
        ("Compte WordPress", "/wp-json/wp/v2/users/me", {}),
        ("Events Manager", "/wp-json/events-manager/v1/events", {
            "scope": "2026-09-28,2026-10-04", "category": 9,
            "context": "edit", "per_page": 100,
        }),
    ]
    failed = False
    for label, path, params in checks:
        response = client.get(base + path, params=params, timeout=30)
        print(f"{label}: HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            print("Reponse non JSON; contenu non affiche.")
            failed = True
            continue
        if not response.ok:
            print(json.dumps({key: data.get(key) for key in ("code", "message")}, ensure_ascii=False))
            failed = True
            continue
        if label == "Compte WordPress":
            print("Authentification valide.")
            continue
        if isinstance(data, dict):
            print("Champs de reponse: " + ", ".join(data))
            items = data.get("items", data.get("events", data.get("data")))
        else:
            items = data
        if not isinstance(items, list):
            print("Format de liste non reconnu par le collecteur.")
            failed = True
            continue
        print(f"Evenements retournes: {len(items)}")
        for event in items:
            if not isinstance(event, dict):
                continue
            # Report only public match identifiers, never account or booking data.
            links = sorted(set(re.findall(r"icbad\.ffbad\.org/rencontre/(\d+)", json.dumps(event))))
            print(json.dumps({
                "id": event.get("id"), "event_id": event.get("event_id"),
                "post_id": event.get("post_id"),
                "event_name": event.get("event_name"),
                "source_ids": links,
                "has_sync_marker": "CSBW_SYNC:" in str(event.get("content", "")),
                "fields": sorted(event),
            }, ensure_ascii=False))
    print("Test en lecture seule termine: aucune publication modifiee.")
    return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.RequestException:
        print("Echec reseau pendant le test de connexion.", file=sys.stderr)
        sys.exit(1)
