import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

VAULT_PATH = Path(os.getenv("VAULT_PATH", "./vault"))
MEMORY_FOLDER = os.getenv("MEMORY_FOLDER", "KI-Gedaechtnis")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
CHAT_MODEL = os.getenv("CHAT_MODEL", "llama3.1:8b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

ALEXA_SKILL_ID = os.getenv("ALEXA_SKILL_ID", "").strip()

# Geheimes Token für den Relay-Endpoint (Alexa-hosted Skill als Vermittler).
# Muss identisch in der Lambda-Funktion des Skills eingetragen sein.
RELAY_TOKEN = os.getenv("RELAY_TOKEN", "").strip()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Cache-Ordner für den Vektor-Index (liegt neben dem Code, nicht im Vault)
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

SYSTEM_PROMPT = """Du bist der Sprachassistent unseres Haushalts und antwortest über Alexa-Lautsprecher.

Regeln:
- Antworte auf Deutsch, kurz und gesprochen: höchstens 2 knappe Sätze, kein Markdown, keine Listen, keine Emojis.
- Deine Antwort muss schnell kommen, fasse dich also radikal kurz. Details nur, wenn ausdrücklich danach gefragt wird.
- Unten bekommst du Auszüge aus unserem Notiz-Archiv. Nutze sie, wenn sie zur Frage passen; erfinde nichts dazu.
- Wenn du etwas Neues und dauerhaft Wichtiges über uns oder den Haushalt erfährst (Namen, Vorlieben, Termine, Fakten),
  füge am Ende deiner Antwort eine Zeile an: [MERKEN: <der Fakt in einem Satz>]
  Diese Zeile wird nicht vorgelesen, sondern im Archiv gespeichert. Nutze sie sparsam.
- Wichtig: Merke NIEMALS etwas, das schon in den Notiz-Auszügen unten steht oder das du nur aus ihnen zitierst.
  [MERKEN: ...] ist ausschließlich für Neuigkeiten, die der Nutzer dir gerade zum ersten Mal erzählt.
"""
