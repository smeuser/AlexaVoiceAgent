"""Gedächtnis: Obsidian-Vault als durchsuchbares Archiv (RAG) + Schreiben neuer Erinnerungen.

Der Vault ist ein normaler Ordner mit Markdown-Dateien. Wir zerlegen jede Datei in
Abschnitte, berechnen Embeddings über Ollama und suchen per Kosinus-Ähnlichkeit.
Der Index wird gecacht und nur für geänderte Dateien neu berechnet.
"""

import json
import re
import threading
import time
from datetime import datetime

import numpy as np

from . import config, llm

_INDEX_FILE = config.CACHE_DIR / "vault_index.json"
_lock = threading.Lock()

# In-Memory-Index: Liste von {"file", "mtime", "text", "vector"}
_chunks: list[dict] = []
_matrix: np.ndarray | None = None  # normalisierte Vektoren, eine Zeile pro Chunk
_cache: dict | None = None  # {relpath: {"mtime": float, "chunks": [...]}}, Spiegel der Cache-Datei
_built = False  # wurde der In-Memory-Index schon einmal aufgebaut?


def _split_into_chunks(text: str, max_len: int = 800) -> list[str]:
    """Zerlegt eine Notiz an Absatzgrenzen in Stücke von grob max_len Zeichen."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) + 2 <= max_len:
            current = f"{current}\n\n{p}" if current else p
        else:
            if current:
                chunks.append(current)
            current = p[:max_len]
    if current:
        chunks.append(current)
    return chunks


def _load_cache() -> dict:
    if _INDEX_FILE.exists():
        try:
            return json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def refresh_index() -> None:
    """Gleicht den Index mit dem Vault ab; nur neue/geänderte Dateien werden neu eingebettet.

    Ohne Änderungen im Vault kostet der Aufruf nur ein paar Datei-Stats (Millisekunden) —
    Cache-Datei und Vektor-Matrix werden nur bei tatsächlichen Änderungen angefasst.
    """
    global _cache, _chunks, _matrix, _built
    with _lock:
        if _cache is None:
            _cache = _load_cache()  # einmalig beim Start von der Platte

        if not config.VAULT_PATH.is_dir():
            config.log(f"Warnung: Vault-Pfad nicht gefunden: {config.VAULT_PATH}")
            _cache, _chunks, _matrix, _built = {}, [], None, True
            return

        new_cache: dict = {}
        changed = False
        for path in sorted(config.VAULT_PATH.rglob("*.md")):
            rel = str(path.relative_to(config.VAULT_PATH))
            mtime = path.stat().st_mtime
            cached = _cache.get(rel)
            if cached and cached["mtime"] == mtime:
                new_cache[rel] = cached
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            texts = _split_into_chunks(text)
            vectors = llm.embed(texts) if texts else []
            new_cache[rel] = {
                "mtime": mtime,
                "chunks": [{"text": t, "vector": v} for t, v in zip(texts, vectors)],
            }
            changed = True
            config.log(f"Indexiert: {rel} ({len(texts)} Abschnitte)")

        if len(new_cache) != len(_cache):
            changed = True  # Dateien wurden gelöscht

        _cache = new_cache
        if not changed and _built:
            return

        _INDEX_FILE.write_text(json.dumps(_cache), encoding="utf-8")
        _chunks = [
            {"file": rel, "text": c["text"], "vector": c["vector"]}
            for rel, entry in _cache.items()
            for c in entry["chunks"]
        ]
        if _chunks:
            m = np.array([c["vector"] for c in _chunks], dtype=np.float32)
            norms = np.linalg.norm(m, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            _matrix = m / norms
        else:
            _matrix = None
        _built = True


def search(query: str, k: int = 4) -> list[dict]:
    """Liefert die k relevantesten Notiz-Abschnitte zur Frage."""
    t0 = time.monotonic()
    refresh_index()
    t1 = time.monotonic()
    if _matrix is None:
        return []
    q = np.array(llm.embed([query])[0], dtype=np.float32)
    t2 = time.monotonic()
    config.log(f"Suche-Detail: Vault-Abgleich {t1 - t0:.2f}s, Frage-Embedding {t2 - t1:.2f}s")
    norm = np.linalg.norm(q)
    if norm == 0:
        return []
    scores = _matrix @ (q / norm)
    top = np.argsort(-scores)[:k]
    return [
        {"file": _chunks[i]["file"], "text": _chunks[i]["text"], "score": float(scores[i])}
        for i in top
        if scores[i] > 0.3
    ]


_ENTRY_PATTERN = re.compile(r"^-\s*(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)\s*—\s*(.+)$")


def _normalize(text: str) -> str:
    """Für den Wortlaut-Vergleich: Kleinschreibung, ohne Satzzeichen/Mehrfach-Leerzeichen."""
    text = re.sub(r"[^\wäöüß ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def collect_memory_entries() -> list[tuple[str, str]]:
    """Liest alle Gedächtnis-Einträge als (Datum, Fakt) aus dem Gedächtnis-Ordner."""
    folder = config.VAULT_PATH / config.MEMORY_FOLDER
    entries: list[tuple[str, str]] = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.md")):
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = _ENTRY_PATTERN.match(line.strip())
                if m:
                    entries.append((m.group(1), m.group(2).strip()))
    return entries


def _is_already_known(fact: str) -> bool:
    """True, wenn der Fakt wortgleich oder inhaltlich schon im Gedächtnis steht."""
    existing = [f for _, f in collect_memory_entries()][-300:]  # Obergrenze als Kostenbremse
    if not existing:
        return False
    norm = _normalize(fact)
    if any(_normalize(f) == norm for f in existing):
        return True
    # Inhaltlicher Vergleich über Embeddings (läuft auf der CPU, im Hintergrund-Thread)
    vectors = np.array(llm.embed(existing + [fact]), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms
    similarities = vectors[:-1] @ vectors[-1]
    return bool(similarities.max() >= 0.92)


def remember(fact: str) -> None:
    """Hängt einen neuen Fakt an die Gedächtnis-Notiz des aktuellen Monats an —
    außer er ist (wortgleich oder inhaltlich) schon bekannt."""
    try:
        if _is_already_known(fact):
            config.log(f"Nicht gemerkt (schon bekannt): {fact.strip()}")
            return
    except Exception as exc:
        config.log(f"Duplikat-Prüfung fehlgeschlagen, merke trotzdem: {exc!r}")
    folder = config.VAULT_PATH / config.MEMORY_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    note = folder / f"{now:%Y-%m}.md"
    line = f"- {now:%Y-%m-%d %H:%M} — {fact.strip()}\n"
    if not note.exists():
        note.write_text(f"# KI-Gedächtnis {now:%Y-%m}\n\n{line}", encoding="utf-8")
    else:
        with note.open("a", encoding="utf-8") as f:
            f.write(line)
    config.log(f"Gemerkt: {fact.strip()}")


def extract_memories(reply: str) -> tuple[str, list[str]]:
    """Trennt [MERKEN: ...]-Zeilen von der vorzulesenden Antwort."""
    facts = re.findall(r"\[MERKEN:\s*(.+?)\]", reply, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\[MERKEN:.+?\]", "", reply, flags=re.IGNORECASE | re.DOTALL).strip()
    return cleaned, [f.strip() for f in facts if f.strip()]
