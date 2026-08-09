# AlexaVoiceAgent

A language model hosted on a local windows server with a 8gb vram machine. the language model should get a memory with obsidian and then we want to attach this language model with Alexa through a self made Alexa skill.

Ein lokales Sprachmodell auf deinem Windows-PC, mit Gedächtnis in einem Obsidian-Vault,
erreichbar über die Alexa Echos im Haushalt.

```
Echo ──► Alexa Cloud ──► Cloudflare Tunnel ──► FastAPI-Server (dieser Code)
                                                   ├─► Ollama (Sprachmodell, lokal)
                                                   └─► Obsidian-Vault (Gedächtnis, lesen + schreiben)
```

**So fühlt es sich an:** „Alexa, öffne mein gehirn“ → danach kannst du frei Fragen stellen.
Das Modell nutzt deine Obsidian-Notizen als Wissen und legt neue Fakten selbstständig unter
`KI-Gedaechtnis/` im Vault ab – dort kannst du sie in Obsidian ansehen und bearbeiten.

> **Wichtig zu wissen:** Alexa selbst lässt sich nicht ersetzen. Das Modell lebt hinter einem
> sogenannten Skill mit eigenem Aufrufnamen („mein gehirn“, änderbar). Außerdem wartet Alexa
> maximal ca. 8 Sekunden auf eine Antwort – deshalb halten wir Antworten kurz und das Modell
> dauerhaft im Grafikspeicher.

---

## 1. Ollama und Modelle installieren (Windows)

1. [Ollama für Windows](https://ollama.com/download) herunterladen und installieren.
2. In der Eingabeaufforderung (cmd) die Modelle laden:

```bash
ollama pull llama3.1:8b
```

```bash
ollama pull nomic-embed-text
```

`llama3.1:8b` (ca. 4,9 GB) passt gut in 6–8 GB VRAM und spricht ordentlich Deutsch.
Alternative zum Ausprobieren: `qwen3:8b`. Das Modell trägst du in der `.env` ein.
`nomic-embed-text` ist das kleine Embedding-Modell für die Notiz-Suche.

Kurztest: `ollama run llama3.1:8b` und etwas auf Deutsch fragen (mit `/bye` beenden).

## 2. Diesen Server einrichten

Voraussetzung: [Python 3.11+](https://www.python.org/downloads/) (beim Installieren „Add to PATH“ anhaken).

Im Projektordner:

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate && pip install -r requirements.txt
```

Dann `.env.example` nach `.env` kopieren und anpassen – vor allem `VAULT_PATH`
(der Ordner deines Obsidian-Vaults). Falls du noch keinen Vault hast: einfach in
Obsidian einen neuen anlegen und den Pfad eintragen.

Server starten:

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Beim ersten Start werden die Modelle geladen und der Vault indexiert (kann je nach
Notizmenge etwas dauern). Testen ohne Alexa:

```bash
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "{\"frage\": \"Hallo! Was weisst du ueber uns?\"}"
```

## 3. Cloudflare Tunnel (macht den Server für Alexa erreichbar)

Der Alexa-Skill läuft in Amazons Cloud und braucht eine öffentliche HTTPS-Adresse.
Der Tunnel stellt sie bereit, ohne dass du Ports im Router öffnen musst.

1. Kostenloses Konto auf [cloudflare.com](https://dash.cloudflare.com) anlegen.
2. Eine eigene Domain bei Cloudflare registrieren (ab ca. 5 €/Jahr) oder eine vorhandene
   Domain zu Cloudflare umziehen.
3. Im Cloudflare-Dashboard: **Zero Trust → Networks → Tunnels → Create a tunnel** („Cloudflared“).
4. Den angezeigten Windows-Installationsbefehl auf deinem PC ausführen – er installiert
   `cloudflared` als Windows-Dienst (startet damit automatisch mit dem PC).
5. Im Tunnel einen **Public Hostname** anlegen, z.B.
   `alexa.deine-domain.de` → Service `http://localhost:8000`.

Test im Browser (auch vom Handy aus dem Mobilfunknetz): `https://alexa.deine-domain.de/health`
sollte `{"status":"ok"}` zeigen.

## 4. Alexa-Skill anlegen

1. Auf [developer.amazon.com/alexa](https://developer.amazon.com/alexa/console/ask) mit
   **demselben Amazon-Konto anmelden, das auf deinen Echos eingerichtet ist** – dann ist der
   Skill automatisch auf allen deinen Geräten verfügbar, ohne Veröffentlichung.
2. **Create Skill**: Name z.B. „Hausgehirn“, Sprache **Deutsch (DE)**, Typ **Custom**,
   Hosting **Provision your own**.
3. Links **Interaction Model → JSON Editor** öffnen und den Inhalt von
   [skill/interaction-model-de-DE.json](skill/interaction-model-de-DE.json) einfügen.
   (Den Aufrufnamen „mein gehirn“ kannst du dort ändern – er muss aus mindestens zwei
   Wörtern bestehen und darf nicht „Alexa“, „Echo“ o.ä. enthalten.) Dann **Save** und **Build Model**.
4. Links **Endpoint**: **HTTPS** auswählen, als Default Region deine Tunnel-Adresse eintragen:
   `https://alexa.deine-domain.de/alexa`
   Als Zertifikatstyp: **„My development endpoint has a certificate from a trusted certificate
   authority“** (Cloudflare liefert ein gültiges Zertifikat).
5. Oben auf der Endpoint-Seite steht **Your Skill ID** (`amzn1.ask.skill....`) – diese in die
   `.env` als `ALEXA_SKILL_ID` eintragen und den Server neu starten.
6. Im Tab **Test** den Skill-Test auf **Development** stellen. Dort kannst du erst per Text
   testen: „öffne mein gehirn“.

Dann am Echo: **„Alexa, öffne mein gehirn“** – und losfragen. Innerhalb der Sitzung kannst du
direkt weitersprechen; mit „Stopp“ beendest du sie.

## Plan B: Alexa-hosted Skill als Vermittler (Relay) — **so läuft es bei uns**

Dieser Weg ist bei uns produktiv im Einsatz, weil der direkte HTTPS-Endpoint-Weg aus
Abschnitt 4 auf unserem Konto nie funktioniert hat (siehe unten).

Falls Amazon selbst gehostete HTTPS-Endpoints auf deinem Konto nicht aufruft
(bekanntes Kontoproblem, Symptom: „Ich kann den angeforderten Skill nicht erreichen“,
obwohl der Endpoint nachweislich erreichbar ist), gibt es einen robusten Umweg:
Der Skill läuft als **Alexa-hosted Skill** in Amazons Cloud und besteht nur aus einem
winzigen Vermittler ([skill/lambda_relay.py](skill/lambda_relay.py)), der jede Anfrage
durch den Cloudflare Tunnel an deinen Server weiterreicht (Endpoint `/relay`).

Einrichtung:

1. Langes Zufalls-Token erzeugen und in der `.env` als `RELAY_TOKEN` eintragen,
   Server neu starten.
2. In der Developer Console einen Skill anlegen: **Custom** + Hosting
   **Alexa-hosted (Python)** + Template **Start from Scratch**.
3. **Interaction Model → JSON Editor**: Inhalt von
   [skill/interaction-model-de-DE.json](skill/interaction-model-de-DE.json) einfügen
   → Save → Build. (Achtung: Der Aufrufname darf nicht gleichzeitig in einem zweiten
   Skill verwendet werden.)
4. Reiter **Code**: Inhalt von `lambda_function.py` komplett durch
   [skill/lambda_relay.py](skill/lambda_relay.py) ersetzen, oben `SERVER_URL`
   (Tunnel-Adresse mit `/relay`) und `RELAY_TOKEN` eintragen → **Save** → **Deploy**.
5. Testen wie gehabt. Ein `ALEXA_SKILL_ID`-Eintrag ist bei diesem Weg optional;
   die Absicherung übernimmt das Token.

## 5. Autostart (empfohlen)

Damit alles nach einem Neustart des PCs von selbst läuft:

- **cloudflared** läuft als Windows-Dienst (startet schon vor der Anmeldung).
- **Ollama** startet sich selbst bei der Benutzer-Anmeldung (Autostart-App).
- **Der FastAPI-Server** wird über eine kleine Skriptdatei im Autostart-Ordner
  gestartet: `Win + R` → `shell:startup` → dort eine Datei `hausgeist.vbs` anlegen
  (Vorlage: [skill/hausgeist.vbs.example](skill/hausgeist.vbs.example), Pfade anpassen):

  ```vbs
  Set sh = CreateObject("WScript.Shell")
  sh.CurrentDirectory = "C:\Pfad\zum\Projekt"
  sh.Run "cmd /c .venv\Scripts\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000 >> server.log 2>&1", 0, False
  ```

  Der Server läuft damit unsichtbar; alle Ausgaben (Startmeldungen, Timing-Zeilen,
  „Gemerkt: …“) landen in `server.log` im Projektordner. Test ohne Neustart:
  Doppelklick auf die Datei, dann `curl http://localhost:8000/health`.

**Bewährte Neustart-Routine** (z.B. nach `git pull` oder `.env`-Änderung):

```bat
taskkill /im python.exe /f
```

…dann Doppelklick auf `hausgeist.vbs` und 1–2 Minuten Warmup abwarten.

**Zwei Lehren aus der Praxis:**

- `pythonw.exe -m uvicorn …` beendet sich sofort wieder (uvicorns Logging verträgt
  den konsolenlosen Modus nicht) — deshalb der Umweg über `cmd /c` mit verstecktem
  Fenster und Logdatei. Auch die Aufgabenplanung war damit nicht zum Laufen zu bringen.
- Der Hausgeist ist erst **nach der Benutzer-Anmeldung** erreichbar, nicht schon am
  Anmeldebildschirm. Für echten Dauerbetrieb: automatische Anmeldung (`netplwiz`)
  einrichten und in den Energieoptionen den **Energiesparmodus auf „Nie“** stellen
  (Bildschirm aus ist okay — Standby macht den Server unerreichbar).

## Bedienung am Echo

- **Gespräch starten:** „Alexa, öffne mein hausgeist“ → Begrüßung → frei weiterfragen,
  solange der blaue Ring leuchtet (ohne „Alexa“ davor). Beenden mit „Stopp“; nach
  ~8 Sekunden Stille endet die Sitzung von selbst.
- **Abkürzung:** „Alexa, frage mein hausgeist, was wir am Wochenende vorhatten“ —
  Frage und Antwort in einem Rutsch, ohne Begrüßung.
- **Merken:** „…merke dir, dass die Mülltonnen dienstags rauskommen.“
- Sätze innerhalb der Sitzung sollten mit einem der trainierten Muster beginnen
  (was/wie/wer/wann/warum/wo/ob/frage/sag mir/erzähl mir/ich möchte wissen/merke
  dir/notiere) — normale Fragen erfüllen das automatisch. Passt ein Satz nicht,
  bleibt die Sitzung trotzdem offen, einfach neu formulieren.
- Alexa gibt dem Skill maximal ~8 Sekunden pro Antwort. Die `Timing:`-Zeilen in
  `server.log` zeigen, wie nah man am Limit ist.

## Wie das Gedächtnis funktioniert

- **Lesen:** Vor jeder Antwort durchsucht der Server deinen Vault (semantische Suche über
  Embeddings) und gibt dem Modell die passendsten Notiz-Abschnitte mit. Geänderte Notizen
  werden automatisch neu indexiert.
- **Schreiben/Lernen:** Erkennt das Modell einen dauerhaft wichtigen Fakt (oder sagst du
  „merke dir …“), legt es ihn als Zeile in `KI-Gedaechtnis/JJJJ-MM.md` im Vault ab. Beim
  nächsten Gespräch wird diese Notiz mit durchsucht – so „lernt“ das System.
- Du kannst das Gedächtnis jederzeit in Obsidian öffnen, korrigieren oder löschen.

## Wenn etwas hakt

- **Alexa sagt „…antwortet nicht“ / „da ist etwas schiefgegangen“:** Meist ein Timeout.
  Prüfe, ob `/health` über die Tunnel-Adresse erreichbar ist und ob die Antwort im
  `/chat`-Test unter ~6 Sekunden liegt. Das Warmup beim Serverstart muss durchgelaufen
  sein („Bereit.“ in `server.log`). Die Meldung „Der Computer zu Hause antwortet gerade
  nicht“ kommt vom Lambda-Vermittler (Server zu langsam/nicht erreichbar); „Entschuldigung,
  da ist etwas schiefgegangen…“ kommt vom Server selbst (Fehler steht dann im Log).
- **`No module named uvicorn`:** Die Pakete sind nicht in der Projekt-venv installiert —
  `.venv\Scripts\python.exe -m pip install -r requirements.txt` (der Server muss mit
  genau der venv laufen, die in der Autostart-Datei steht).
- **Antworten sind langsam:** In `server.log` die `Timing:`- und `Suche-Detail:`-Zeilen
  ansehen. `ollama ps` muss das Chat-Modell mit „100% GPU“ zeigen und das Embedding-Modell
  auf CPU. Notfalls kleineres Modell (`llama3.2:3b` in der `.env`).
- **Folgeanfragen plötzlich langsamer als die erste:** Das Modell merkt sich vermutlich
  bei jeder Antwort denselben Fakt neu (sichtbar an `Gemerkt:`-Zeilen im Log und Duplikaten
  in `KI-Gedaechtnis/`) — Duplikate im Vault löschen; der System-Prompt verbietet das zwar,
  kleine Modelle ignorieren es aber gelegentlich.
- **QuickEdit-Falle:** Bei manuell gestartetem Server friert ein Klick ins cmd-Fenster den
  Prozess ein, bis Enter/Esc gedrückt wird (Symptom: alle Anfragen timen aus).
