"""Anbindung an Ollama (Chat + Embeddings)."""

import requests

from . import config


def chat(messages: list[dict], timeout: float = 20.0) -> str:
    """Schickt einen Chatverlauf an Ollama und gibt die Antwort als Text zurück."""
    resp = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={
            "model": config.CHAT_MODEL,
            "messages": messages,
            "stream": False,
            # Modell 30 Min. im VRAM halten, sonst dauert jede Antwort zu lange für Alexa
            "keep_alive": "30m",
            "options": {
                "num_predict": 220,  # kurze Antworten erzwingen (Alexa liest vor)
                "temperature": 0.6,
            },
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def embed(texts: list[str], timeout: float = 60.0) -> list[list[float]]:
    """Erzeugt Embedding-Vektoren für eine Liste von Texten."""
    resp = requests.post(
        f"{config.OLLAMA_URL}/api/embed",
        json={"model": config.EMBED_MODEL, "input": texts, "keep_alive": "30m"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def warmup() -> None:
    """Lädt beide Modelle ins VRAM, damit die erste Alexa-Anfrage nicht ins Timeout läuft."""
    try:
        embed(["warmup"])
        chat([{"role": "user", "content": "Sag nur: bereit."}], timeout=120.0)
    except requests.RequestException as exc:
        print(f"Warnung: Ollama-Warmup fehlgeschlagen: {exc}")
