"""FastAPI-Server: Alexa-Endpoint + lokaler Test-Endpoint.

Start (im Projektordner):
    uvicorn server.main:app --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import agent, llm, memory
from .alexa import build_webservice_handler

webservice_handler = build_webservice_handler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Lade Modelle und indexiere den Vault ...")
    await run_in_threadpool(llm.warmup)
    await run_in_threadpool(memory.refresh_index)
    print("Bereit.")
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
        print(f"Alexa-Anfrage abgelehnt: {exc!r}")
        return JSONResponse(content={"error": "invalid request"}, status_code=400)


class ChatRequest(BaseModel):
    frage: str
    history: list[dict] = []


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """Zum Testen ohne Alexa, z.B.:
    curl -X POST localhost:8000/chat -H "Content-Type: application/json" -d "{\"frage\": \"Hallo, wer bist du?\"}"
    """
    spoken, history = await run_in_threadpool(agent.answer, req.frage, req.history)
    return {"antwort": spoken, "history": history}


if __name__ == "__main__":
    import uvicorn

    from . import config

    uvicorn.run(app, host=config.HOST, port=config.PORT)
