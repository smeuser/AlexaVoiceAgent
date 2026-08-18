# Schnittstellen-Spezifikation: Erreichbarkeit des Hausgeist-Servers

Stand: 2026-08-18. Beschreibt, wie der lokal laufende Server aus dem Internet erreicht
wird, welche Routen er anbietet, wer sie aufrufen darf und welche Anforderungen dabei
gelten. Die Einrichtungs-Klickanleitung steht im [README](../README.md); dieses Dokument
ist die Referenz für den *Vertrag* zwischen den Komponenten.

## 1. Komponenten und Datenfluss

```
Echo ──► Alexa Cloud ──► Alexa-hosted Skill (Lambda, skill/lambda_relay.py)
                                   │  HTTPS, Header X-Relay-Token
                                   ▼
                     Cloudflare Edge (https://alexa.smeuser.net)
                                   │  Cloudflare Tunnel (ausgehende Verbindung vom PC)
                                   ▼
                     cloudflared (Windows-Dienst auf dem Hausgeist-PC)
                                   │  http://localhost:8000
                                   ▼
                     FastAPI-Server (Windows-Dienst "Hausgeist", server/main.py)
                                   ├─► Ollama (localhost:11434)
                                   └─► Obsidian-Vault (Dateisystem)
```

| Komponente | Wo | Aufgabe |
|---|---|---|
| Alexa-hosted Skill (Lambda) | AWS, Region EU (Irland) | Nimmt Alexa-Anfragen entgegen, reicht sie unverändert an den Server weiter, gibt die Antwort zurück. Timeout 7 s, danach Notfallantwort. |
| Cloudflare Edge + Tunnel | Cloudflare | Öffentliche HTTPS-Adresse mit gültigem Zertifikat. Der PC baut die Verbindung **ausgehend** auf – keine Portfreigabe im Router. |
| cloudflared | Windows-Dienst | Hält den Tunnel; leitet Anfragen des Public Hostname an `http://localhost:8000`. |
| FastAPI-Server | Windows-Dienst `Hausgeist` | Die eigentliche Anwendung. |

**Konkrete Werte** (nicht im Repo, sondern im Cloudflare-Dashboard bzw. der `.env`):

- Public Hostname: `alexa.smeuser.net` (Zone `smeuser.net`, liegt vollständig bei Cloudflare;
  Domain wird ausschließlich für dieses Projekt genutzt)
- Tunnel-Typ: „Cloudflared“ (remote verwaltet, Konfiguration im Dashboard unter
  Zero Trust → Networks → Tunnels); Zugangs-Token liegt in der lokalen Dienstkonfiguration
- Ziel-Service im Tunnel: `http://localhost:8000`
- Server bindet `0.0.0.0:8000` (`.env`: `HOST`, `PORT`)

## 2. Routen des Servers

| Route | Methode | Aufrufer | Absicherung | Zweck |
|---|---|---|---|---|
| `/health` | GET | Monitoring, Browser-Tests, Menschen | keine (gibt nur `{"status":"ok"}` preis) | Erreichbarkeitstest, auch von außen |
| `/relay` | POST | **Nur** die Lambda des Alexa-hosted Skills | Header `X-Relay-Token` muss `RELAY_TOKEN` aus der `.env` entsprechen; sonst 403 | Produktiver Alexa-Weg. Nimmt Alexa-Request-Envelopes entgegen; `AlexaSkillEvent.*` (Verwaltungsereignisse) werden nur geloggt und quittiert |
| `/alexa` | POST | Amazon direkt (HTTPS-Endpoint-Weg) | Amazon-Signatur + Zeitstempel + Skill-ID | **Nicht produktiv genutzt** – Amazon ruft auf diesem Konto keine eigenen HTTPS-Endpoints auf. Bleibt als Fallback bestehen |
| `/chat` | POST | Entwickler:innen im Heimnetz | **Nur lokale/private Absender**; Anfragen über den Tunnel (erkennbar am Header `CF-Connecting-IP`) werden mit 403 abgewiesen | Test-Endpoint ohne Alexa, kann auch Recherchen auslösen |

Alle anderen Pfade liefern 404 (`/`) bzw. 405 (falsche Methode).

**Öffentlich über den Tunnel wirksam sind damit nur `/health` und `/relay`** (sowie das
signaturgeschützte `/alexa`). Es gibt keine Route, über die ungeschützt Inhalte des Vaults
gelesen oder das Sprachmodell benutzt werden können.

## 3. Der `/relay`-Vertrag (Lambda ↔ Server)

- **Request:** Die Lambda sendet den kompletten Alexa-Request-Envelope als JSON-Body
  (`Content-Type: application/json`) mit dem Header `X-Relay-Token: <RELAY_TOKEN>`.
- **Response:** Der Server antwortet mit dem Alexa-Response-JSON (Status 200), das die
  Lambda unverändert an Alexa zurückgibt. Bei ungültigem Token: 403 `{"error":"forbidden"}`;
  bei nicht verarbeitbarer Anfrage: 400 `{"error":"invalid request"}`.
- **Zeitbudget:** Alexa wartet insgesamt ~8 s. Die Lambda wartet **7 s** auf den Server,
  danach spricht sie selbst eine Notfallantwort („Der Computer zu Hause antwortet gerade
  nicht …“). Der Server muss also inklusive Modellantwort **deutlich unter 7 s** bleiben
  (Richtwert aus der Praxis: ~5–6 s mit `llama3.1:8b`, ~2–3 s mit `llama3.2:3b`).
- **Geheimnis-Verwaltung:** `RELAY_TOKEN` steht an genau zwei Stellen – `.env` auf dem
  Server und als Konstante in `lambda_function.py` des Skills (Code-Tab der Developer
  Console). Beim Rotieren beide ändern; die Lambda braucht danach *Save + Deploy*, der
  Server einen Neustart.

## 4. Anforderungen an den Zugang von außen

1. **TLS von einer vertrauenswürdigen CA** – Cloudflare stellt das Zertifikat automatisch
   für Domain und Subdomains erster Ebene (`*.smeuser.net`) aus. Tiefere Ebenen
   (`x.alexa.smeuser.net`) wären *nicht* abgedeckt.
2. **Durchlässig für Rechenzentrums-Traffic:** Die Aufrufe kommen aus AWS (Lambda), nicht
   von Browsern. Cloudflare-Schutzfunktionen, die automatisierte Zugriffe blocken (Bot Fight
   Mode, Browser Integrity Check, hohe Security Levels), müssen für diese Zone aus bleiben
   bzw. dürfen `/relay` nicht treffen. Symptom bei Verstoß: Lambda-Timeout, Alexa sagt
   „Der Computer zu Hause antwortet gerade nicht“, im Serverlog kommt nichts an.
3. **Keine Portfreigabe, kein DynDNS** – die Verbindung geht ausschließlich vom PC nach
   außen; der Router bleibt geschlossen.
4. **Der Tunnel darf ruhig immer offen sein**, auch wenn der Server pausiert (z.B. GPU
   anderweitig genutzt): Ohne Server antwortet Cloudflare mit „Bad Gateway“ (502), die
   Lambda fängt das ab.

## 5. Betrieb und Diagnose

| Symptom von außen | Bedeutung | Prüfen |
|---|---|---|
| `{"status":"ok"}` auf `/health` | Kette komplett gesund | – |
| Cloudflare „Bad Gateway“ (502/530) | Tunnel steht, aber Server antwortet nicht | Server-Dienst läuft? Warmup nach Kaltstart (2–4 Min) abwarten; `server.log` |
| Cloudflare-Fehler 1033 / „Tunnel error“ | cloudflared nicht verbunden | `sc query cloudflared`; Dashboard: Tunnel-Status HEALTHY? |
| DNS nicht auflösbar | Public Hostname fehlt/falsch | Dashboard → Tunnel → Public Hostname |
| Alexa: „Der Computer zu Hause antwortet gerade nicht“ | Lambda erreicht Server nicht in 7 s | Erreichbarkeit + Antwortzeit (`Timing:`-Zeilen im Log) |
| Alexa: „Entschuldigung, da ist etwas schiefgegangen“ | Server erreicht, Fehler in der Verarbeitung | Fehlerzeile im `server.log` |

Nützliche Kommandos auf dem PC:

```bat
sc query cloudflared
sc query Hausgeist
curl http://localhost:8000/health
curl -X POST https://alexa.smeuser.net/relay -H "Content-Type: application/json" -d "{}"
```

Der letzte Befehl muss von außen `{"error":"forbidden"}` (403) liefern – das beweist,
dass die Route bis zum Server durchgeht *und* der Token-Schutz greift.

## 6. Bekannte Einschränkungen und Entscheidungen

- **Warum ein Lambda-Vermittler statt direktem HTTPS-Endpoint:** Auf dem verwendeten
  Amazon-Entwicklerkonto ruft Alexa keine selbst gehosteten HTTPS-Endpoints auf (mit drei
  verschiedenen, nachweislich erreichbaren Endpoints reproduziert – eigene Domain,
  trycloudflare, ngrok – während Alexa-hosted Skills funktionieren). Der Vermittler umgeht
  das. Sollte Amazon das Konto reparieren, wäre `/alexa` der direkte Weg.
- **Warum eine Zweitdomain:** Die Hauptdomain samt E-Mail liegt bei einem anderen Anbieter
  und soll unangetastet bleiben; `smeuser.net` liegt komplett bei Cloudflare, so greift
  Zertifikat + Tunnel + DNS ohne Nameserver-Umzug ineinander.
- **Weitere Anwendungen über denselben Tunnel:** Möglich – pro Anwendung ein weiterer
  Public Hostname (z.B. `foo.smeuser.net` → `http://localhost:PORT`) im selben Tunnel.
  Jede Anwendung braucht ihre eigene Absicherung; der Tunnel selbst authentifiziert nichts.
