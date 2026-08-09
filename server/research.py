"""Hintergrund-Recherche: Websuche -> Seiten lesen -> Zusammenfassung als Vault-Notiz.

Ablauf: Der Alexa-Handler startet run_research() in einem Thread und antwortet sofort.
Die Recherche läuft ohne Zeitdruck (kein Alexa-Limit), schreibt ihr Ergebnis nach
"Recherchen/" in den Obsidian-Vault und aktualisiert den Suchindex — danach findet
die normale Notiz-Suche die Ergebnisse ("Was hast du zu ... herausgefunden?").
"""

import re
import threading
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

from . import config, llm, memory

RESEARCH_FOLDER = config.RESEARCH_FOLDER

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

_SUMMARY_PROMPT = """Du bist ein gründlicher Recherche-Assistent. Unten stehen Web-Suchergebnisse und Textauszüge zum Thema "{topic}".

Schreibe daraus auf Deutsch eine Zusammenfassung als Fließtext:
- Nenne die konkreten Fakten aus den Quellen (was, wo, wann, wer, Preise, Zeiten), soweit vorhanden.
- 5 bis 15 Sätze, je nachdem wie viel die Quellen hergeben.
- Erfinde nichts dazu. Wenn die Quellen wenig oder nichts Brauchbares enthalten, schreibe das ehrlich.
"""


def _slugify(text: str, max_len: int = 60) -> str:
    text = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len] or "recherche"


def _fetch_page_text(url: str, max_chars: int = 4000) -> str:
    """Lädt eine Webseite und extrahiert den reinen Text. Fehler -> leerer String."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        return text[:max_chars]
    except Exception as exc:
        config.log(f"Recherche: Seite nicht lesbar ({url}): {exc!r}")
        return ""


def run_research(topic: str) -> None:
    """Führt die komplette Recherche aus und schreibt die Ergebnis-Notiz. Läuft im Thread."""
    config.log(f"Recherche gestartet: {topic}")
    try:
        results = list(DDGS().text(topic, region="de-de", max_results=8) or [])
    except Exception as exc:
        config.log(f"Recherche: Websuche fehlgeschlagen: {exc!r}")
        results = []

    material: list[str] = []
    sources: list[tuple[str, str]] = []
    for r in results:
        title, url, snippet = r.get("title", ""), r.get("href", ""), r.get("body", "")
        if url:
            sources.append((title or url, url))
        if snippet:
            material.append(f"[Suchtreffer: {title}]\n{snippet}")
    # Die drei besten Treffer komplett lesen — Snippets allein sind oft zu dünn
    for title, url in sources[:3]:
        page_text = _fetch_page_text(url)
        if page_text:
            material.append(f"[Seite: {title} — {url}]\n{page_text}")

    if material:
        try:
            summary = llm.chat(
                [
                    {"role": "system", "content": _SUMMARY_PROMPT.format(topic=topic)},
                    {"role": "user", "content": "\n\n".join(material)},
                ],
                timeout=300.0,
                num_predict=700,
            )
        except Exception as exc:
            config.log(f"Recherche: Zusammenfassung fehlgeschlagen: {exc!r}")
            summary = "Die Zusammenfassung ist fehlgeschlagen. Die Quellen unten enthalten das Rohmaterial."
    else:
        summary = "Die Websuche hat zu diesem Thema leider keine brauchbaren Ergebnisse geliefert."

    now = datetime.now()
    folder = config.VAULT_PATH / RESEARCH_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    note = folder / f"{now:%Y-%m-%d}-{_slugify(topic)}.md"
    lines = [
        f"# Recherche: {topic}",
        "",
        f"Recherchiert am {now:%d.%m.%Y um %H:%M} Uhr.",
        "",
        summary,
        "",
        "## Quellen",
    ] + [f"- [{title}]({url})" for title, url in sources]
    note.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config.log(f"Recherche abgeschlossen: {note.name}")
    memory.refresh_index()


def start_research(topic: str) -> None:
    threading.Thread(target=run_research, args=(topic,), daemon=True).start()


def create_reminder(api_endpoint: str, api_token: str, text: str, offset_seconds: int = 300) -> bool:
    """Legt über die Alexa-API eine gesprochene Erinnerung an (braucht die
    Reminders-Berechtigung des Skills). Gibt True bei Erfolg zurück."""
    payload = {
        "requestTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000"),
        "trigger": {"type": "SCHEDULED_RELATIVE", "offsetInSeconds": offset_seconds},
        "alertInfo": {"spokenInfo": {"content": [{"locale": "de-DE", "text": text}]}},
        "pushNotification": {"status": "ENABLED"},
    }
    resp = requests.post(
        f"{api_endpoint}/v1/alerts/reminders",
        json=payload,
        headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
        timeout=3,
    )
    if resp.status_code not in (200, 201):
        config.log(f"Erinnerung fehlgeschlagen ({resp.status_code}): {resp.text[:200]}")
        return False
    return True
