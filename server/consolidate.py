"""Konsolidiert das KI-Gedächtnis: Duplikate raus, inhaltlich Gleiches zusammenfassen.

Aufruf auf dem Server-PC (im Projektordner, Ollama muss laufen):

    .venv\\Scripts\\python.exe -m server.consolidate

Ergebnis: Alle Einträge aus KI-Gedaechtnis/*.md werden bereinigt und in
KI-Gedaechtnis/Gedaechtnis.md zusammengeführt. Die bisherigen Dateien werden
zu ".bak"-Dateien umbenannt (bleiben als Backup erhalten, werden aber nicht
mehr indexiert). Gelegentlich ausführen, wenn sich Einträge angesammelt haben.
"""

import re
from datetime import datetime

from . import config, llm, memory

_PROMPT = """Du bereinigst die Gedächtnis-Liste eines Haushalts-Assistenten.

Regeln:
- Fasse Einträge zusammen, die inhaltlich dasselbe aussagen; behalte dabei das älteste Datum.
- Entferne NICHTS, was eine eigenständige Information ist — im Zweifel behalten.
- Verändere die Fakten inhaltlich nicht, korrigiere höchstens Grammatik.
- Gib NUR die bereinigte Liste aus, eine Zeile pro Eintrag, exakt im Format:
- <Datum> — <Fakt>
"""


def main() -> None:
    folder = config.VAULT_PATH / config.MEMORY_FOLDER
    entries = memory.collect_memory_entries()
    if not entries:
        print("Keine Gedächtnis-Einträge gefunden.")
        return
    print(f"{len(entries)} Einträge gefunden.")

    # Schritt 1: wortgleiche Duplikate entfernen (ältestes Datum gewinnt)
    seen: dict[str, tuple[str, str]] = {}
    for date, fact in sorted(entries):
        key = memory._normalize(fact)
        if key not in seen:
            seen[key] = (date, fact)
    unique = list(seen.values())
    print(f"Nach Wortlaut-Bereinigung: {len(unique)} Einträge.")

    # Schritt 2: inhaltliche Zusammenfassung durch das Sprachmodell
    listing = "\n".join(f"- {date} — {fact}" for date, fact in unique)
    consolidated = unique
    try:
        reply = llm.chat(
            [{"role": "system", "content": _PROMPT}, {"role": "user", "content": listing}],
            timeout=300.0,
            num_predict=2000,
        )
        parsed = [
            (m.group(1), m.group(2).strip())
            for line in reply.splitlines()
            if (m := memory._ENTRY_PATTERN.match(line.strip()))
        ]
        # Plausibilitätsbremse: Wenn das Modell zu viel wegwirft, lieber nicht vertrauen
        if parsed and len(parsed) >= len(unique) * 0.5:
            consolidated = parsed
            print(f"Nach inhaltlicher Zusammenfassung: {len(consolidated)} Einträge.")
        else:
            print("Modell-Antwort unplausibel — behalte die Wortlaut-Bereinigung.")
    except Exception as exc:
        print(f"Zusammenfassung fehlgeschlagen ({exc!r}) — behalte die Wortlaut-Bereinigung.")

    # Schritt 3: alte Dateien sichern, konsolidierte Datei schreiben
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    for path in sorted(folder.glob("*.md")):
        path.rename(path.with_name(f"{path.name}.{stamp}.bak"))
    target = folder / "Gedaechtnis.md"
    lines = [f"# KI-Gedächtnis (konsolidiert am {datetime.now():%d.%m.%Y})", ""]
    lines += [f"- {date} — {fact}" for date, fact in consolidated]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Fertig: {target} geschrieben, alte Dateien als *.{stamp}.bak gesichert.")
    print("Der Server-Index aktualisiert sich bei der nächsten Anfrage von selbst.")


if __name__ == "__main__":
    main()
