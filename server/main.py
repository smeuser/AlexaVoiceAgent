"""FastAPI-Server: Alexa-Endpoint + lokaler Test-Endpoint.

Start (im Projektordner):
    uvicorn server.main:app --host 0.0.0.0 --port 8000
"""

import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from uvicorn.config import LOGGING_CONFIG

from . import agent, config, llm, memory, research
from .alexa import build_relay_handler, build_webservice_handler

# Uvicorns eigene Log-Zeilen (INFO: ... / Zugriffsprotokoll) bekommen dieselben
# Zeitstempel wie unsere config.log()-Meldungen.
LOGGING_CONFIG["formatters"]["default"]["fmt"] = "[%(asctime)s] %(levelprefix)s %(message)s"
LOGGING_CONFIG["formatters"]["access"]["fmt"] = (
    '[%(asctime)s] %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
)
for _formatter in LOGGING_CONFIG["formatters"].values():
    _formatter["datefmt"] = "%Y-%m-%d %H:%M:%S"
logging.config.dictConfig(LOGGING_CONFIG)

webservice_handler = build_webservice_handler()
relay_handler = build_relay_handler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.log("Lade Modelle und indexiere den Vault ...")
    await run_in_threadpool(llm.warmup)
    await run_in_threadpool(memory.refresh_index)
    config.log("Bereit.")
    yield


app = FastAPI(title="AlexaVoiceAgent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/alexa")
async def alexa_endpoint(request: Request):
    """Der Endpoint, den der Alexa-Skill aufruft (über den Cloudflare Tunnel)."""
    body = (await request.body()).decode("utf-8")
    headers = dict(request.headers)
    try:
        response = await run_in_threadpool(
            webservice_handler.verify_request_and_dispatch, headers, body
        )
        return JSONResponse(content=response)
    except Exception as exc:  # Signatur ungültig o.ä. -> Anfrage ablehnen
        config.log(f"Alexa-Anfrage abgelehnt: {exc!r}")
        return JSONResponse(content={"error": "invalid request"}, status_code=400)


@app.post("/relay")
async def relay_endpoint(request: Request):
    """Empfängt Alexa-Anfragen vom Alexa-hosted Vermittler-Skill (Lambda).

    Abgesichert über ein gemeinsames Geheimnis statt der Amazon-Signatur,
    denn die Lambda-Weiterleitung trägt keine Signatur-Header mehr.
    """
    if not config.RELAY_TOKEN or request.headers.get("x-relay-token") != config.RELAY_TOKEN:
        return JSONResponse(content={"error": "forbidden"}, status_code=403)
    body = (await request.body()).decode("utf-8")
    try:
        response = await run_in_threadpool(
            relay_handler.verify_request_and_dispatch, dict(request.headers), body
        )
        return JSONResponse(content=response)
    except Exception as exc:
        config.log(f"Relay-Anfrage fehlgeschlagen: {exc!r}")
        return JSONResponse(content={"error": "invalid request"}, status_code=400)


class ChatRequest(BaseModel):
    frage: str
    history: list[dict] = []


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """Zum Testen ohne Alexa, z.B.:
    curl -X POST localhost:8000/chat -H "Content-Type: application/json" -d "{\"frage\": \"Hallo, wer bist du?\"}"
    Auch Recherche-Aufträge funktionieren hier: "frage": "recherchiere ..."
    """
    from .alexa import RESEARCH_TRIGGER

    match = RESEARCH_TRIGGER.match(req.frage.strip())
    if match:
        topic = match.group(1).strip() or req.frage.strip()
        research.start_research(topic)
        return {"antwort": f"Recherche zu '{topic}' gestartet — Ergebnis landet im Vault unter Recherchen/."}

    spoken, history = await run_in_threadpool(agent.answer, req.frage, req.history)
    return {"antwort": spoken, "history": history}


if __name__ == "__main__":
    import uvicorn

    from . import config

    uvicorn.run(app, host=config.HOST, port=config.PORT)
