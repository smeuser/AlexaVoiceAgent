"""Einmalige Freischaltung der Benachrichtigungen (Proactive Events) für den Skill.

Die Console-Oberfläche bietet dafür keinen Schalter; die Freischaltung geht nur
über Amazons Verwaltungs-API (SMAPI). Dieses Skript trägt die nötigen Einträge
(Berechtigung notifications:write + Event AMAZON.MessageAlert.Activated) in das
Skill-Manifest ein.

Voraussetzung: Einmalige Anmeldung über Amazons Kommandozeilenwerkzeug:
    npm install -g ask-cli
    ask configure        (Browser-Anmeldung mit dem Entwicklerkonto; die Frage
                          nach einem AWS-Konto mit "No" beantworten)

Aufruf danach (im Projektordner):
    .venv\\Scripts\\python.exe -m server.enable_notifications amzn1.ask.skill.DEINE-ID
"""

import json
import sys
import time
from pathlib import Path

import requests

ASK_CONFIG = Path.home() / ".ask" / "cli_config"
# Öffentlich bekannte Anmelde-Konstanten des ask-cli (stehen in dessen Quellcode);
# wir nutzen sie nur, um das vom ask-cli gespeicherte Login aufzufrischen.
LWA_CLIENT_ID = "amzn1.application-oa2-client.aad322b5faab44b980c8f87f94fbac56"
LWA_CLIENT_SECRET = "1642d8869b829dda3311d6c6539f3ead55192e3fc767b9071c888e60ef151cf9"
SMAPI = "https://api.amazonalexa.com"

PERMISSION = "alexa::devices:all:notifications:write"
EVENT = "AMAZON.MessageAlert.Activated"


def get_access_token() -> str:
    if not ASK_CONFIG.exists():
        sys.exit("Keine ask-cli-Anmeldung gefunden. Bitte zuerst 'ask configure' ausführen (siehe Docstring).")
    cfg = json.loads(ASK_CONFIG.read_text(encoding="utf-8"))
    refresh_token = cfg["profiles"]["default"]["token"]["refresh_token"]
    resp = requests.post(
        "https://api.amazon.com/auth/o2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": LWA_CLIENT_ID,
            "client_secret": LWA_CLIENT_SECRET,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("amzn1.ask.skill."):
        sys.exit("Aufruf: python -m server.enable_notifications <Skill-ID, beginnt mit amzn1.ask.skill....>")
    skill_id = sys.argv[1]
    headers = {"Authorization": f"Bearer {get_access_token()}"}
    url = f"{SMAPI}/v1/skills/{skill_id}/stages/development/manifest"

    print("Lade aktuelles Skill-Manifest ...")
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        sys.exit(f"Manifest laden fehlgeschlagen ({resp.status_code}): {resp.text[:500]}")
    manifest = resp.json()["manifest"]

    permissions = manifest.setdefault("permissions", [])
    if not any(p.get("name") == PERMISSION for p in permissions):
        permissions.append({"name": PERMISSION})
    events = manifest.setdefault("events", {})
    publications = events.setdefault("publications", [])
    if not any(p.get("eventName") == EVENT for p in publications):
        publications.append({"eventName": EVENT})
    # Amazon verlangt im events-Block zwingend einen Endpoint — wir übernehmen
    # den bestehenden Skill-Endpoint aus dem Manifest.
    if "endpoint" not in events:
        custom_endpoint = manifest.get("apis", {}).get("custom", {}).get("endpoint")
        if not custom_endpoint:
            sys.exit(
                "Im Manifest ist kein Skill-Endpoint hinterlegt (apis.custom.endpoint fehlt) — "
                "bitte melden, dann lösen wir das gemeinsam."
            )
        events["endpoint"] = custom_endpoint

    print("Schreibe aktualisiertes Manifest ...")
    resp = requests.put(
        url,
        headers={**headers, "Content-Type": "application/json"},
        json={"manifest": manifest},
        timeout=30,
    )
    if resp.status_code not in (200, 202):
        sys.exit(f"Manifest schreiben fehlgeschlagen ({resp.status_code}): {resp.text[:500]}")

    print("Angenommen — warte auf Amazons Verarbeitung ...")
    for _ in range(20):
        time.sleep(3)
        status = requests.get(f"{SMAPI}/v1/skills/{skill_id}/status?resource=manifest", headers=headers, timeout=15)
        state = status.json().get("manifest", {}).get("lastUpdateRequest", {}).get("status")
        print(f"  Status: {state}")
        if state == "SUCCEEDED":
            print("\nFertig! Der Skill darf jetzt Benachrichtigungen senden.")
            print("Nächste Schritte: In der Alexa-App beim Skill 'Benachrichtigungen' erlauben,")
            print("dann eine Recherche anstoßen — im server.log sollte 'Benachrichtigung verschickt' stehen.")
            return
        if state == "FAILED":
            sys.exit(json.dumps(status.json(), indent=2)[:1500])
    print("Status weiterhin unklar — bitte in der Developer Console nachsehen.")


if __name__ == "__main__":
    main()
