"""Vermittler-Code für einen Alexa-hosted Skill.

Diesen kompletten Inhalt in der Alexa Developer Console im Reiter "Code"
in die Datei lambda_function.py kopieren (den vorhandenen Inhalt ersetzen),
die beiden Werte unten anpassen, dann "Save" und "Deploy" klicken.

Die Lambda-Funktion empfängt jede Alexa-Anfrage und reicht sie unverändert
an den Server im Heimnetz weiter (über den Cloudflare Tunnel). Die Antwort
des Servers geht unverändert an Alexa zurück.
"""

import json
import urllib.error
import urllib.request

# --- HIER ANPASSEN ---------------------------------------------------------
SERVER_URL = "https://alexa.DEINE-DOMAIN.de/relay"
RELAY_TOKEN = "HIER-DAS-GLEICHE-TOKEN-WIE-IN-DER-ENV-DATEI"
# ---------------------------------------------------------------------------


def _speak(text):
    """Notfall-Antwort, falls der Heimserver nicht erreichbar ist."""
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": True,
        },
    }


def lambda_handler(event, context):
    data = json.dumps(event).encode("utf-8")
    req = urllib.request.Request(
        SERVER_URL,
        data=data,
        headers={"Content-Type": "application/json", "X-Relay-Token": RELAY_TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=7) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"Heimserver nicht erreichbar: {exc!r}")
        return _speak("Der Computer zu Hause antwortet gerade nicht. Versuche es später noch einmal.")
    except Exception as exc:
        print(f"Relay-Fehler: {exc!r}")
        return _speak("Da ist etwas schiefgegangen.")
