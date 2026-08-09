"""Kernlogik: Frage -> Notiz-Suche -> Sprachmodell -> gesprochene Antwort + Gedächtnis."""

import re
import threading
import time

from . import config, llm, memory

# Verlauf pro Alexa-Session wird in den Session-Attributen von Alexa gehalten;
# hier begrenzen wir nur die Länge.
MAX_HISTORY_MESSAGES = 8


def _sanitize_for_speech(text: str) -> str:
    """Entfernt Markdown/Sonderzeichen, damit Alexa sauber vorlesen kann."""
    text = re.sub(r"[*_#`>|]", "", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)  # Links -> nur Linktext
    text = re.sub(r"\s+", " ", text).strip()
    # Alexa erlaubt max. 8000 Zeichen, wir bleiben weit darunter
    return text[:1500]


def answer(question: str, history: list[dict]) -> tuple[str, list[dict]]:
    """Beantwortet eine Frage. Gibt (gesprochene Antwort, neuer Verlauf) zurück."""
    start = time.monotonic()
    context_chunks = memory.search(question, k=3)
    t_search = time.monotonic() - start
    context = "\n\n".join(
        f"[Notiz: {c['file']}]\n{c['text']}" for c in context_chunks
    ) or "(keine passenden Notizen gefunden)"

    messages = (
        [{"role": "system", "content": f"{config.SYSTEM_PROMPT}\n\nNotiz-Auszüge:\n{context}"}]
        + history[-MAX_HISTORY_MESSAGES:]
        + [{"role": "user", "content": question}]
    )

    reply = llm.chat(messages)
    t_total = time.monotonic() - start
    spoken_raw, facts = memory.extract_memories(reply)
    if facts:
        for fact in facts:
            memory.remember(fact)
        # Sofort im Hintergrund neu indexieren, damit nicht die nächste Frage
        # die Neu-Einbettung der geänderten Gedächtnis-Notiz bezahlen muss.
        threading.Thread(target=memory.refresh_index, daemon=True).start()
    # Alexa bricht nach ~8s ab (Lambda wartet 7s) — diese Zeile zeigt, wo die Zeit bleibt
    print(f"Timing: Suche {t_search:.1f}s, Modell {t_total - t_search:.1f}s, gesamt {t_total:.1f}s")
    spoken = _sanitize_for_speech(spoken_raw) or "Dazu fällt mir gerade nichts ein."
    new_history = history[-MAX_HISTORY_MESSAGES:] + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": spoken},
    ]
    return spoken, new_history
