import os
import json
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.rag import rag_engine, vector_store
from app.user_profile import fetch_user_profile

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODEL_ID = os.getenv("MODEL_ID", "google/gemini-2.0-flash-001")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

# Persistent HTTP client — connection pooling for OpenRouter API
_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize RAG on startup, manage HTTP client."""
    global _http_client
    _http_client = httpx.AsyncClient(timeout=60.0)
    try:
        rag_engine.initialize_rag()
    except Exception as e:
        logger.error("Failed to initialize RAG on startup: %s", e)
    yield
    await _http_client.aclose()
    _http_client = None


app = FastAPI(title="Gymble AI", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    user_id: Optional[str] = None
    user_context: Optional[dict] = None
    token: Optional[str] = None
    temperature: Optional[float] = 0.7

@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not set")

    # Kullanıcı context'ini belirle
    user_context = req.user_context or {}

    # user_id varsa API Gateway'den profil çek
    if req.user_id and not user_context:
        profile = await fetch_user_profile(req.user_id, req.token)
        if profile:
            user_context = profile
            logger.info("Profil API Gateway'den alındı: user_id=%s", req.user_id)

    latest_user_msg = ""
    for m in reversed(req.messages):
        if m.role == "user":
            latest_user_msg = m.content
            break

    # --- KÜFÜR / ARGO FİLTRESİ ---
    bad_words = ["göt", "amk", "siktir", "oç", "piç", "yavşak", "amcık", "orosbu", "orospu", "yarrak", "amına", "sik", "meme ucu"]
    msg_lower = latest_user_msg.lower()
    if any(word in msg_lower for word in bad_words):
        async def event_generator_profanity():
            yield f"data: {json.dumps({'content': 'Üzgünüm, bu tür uygunsuz ifadeler içeren veya ahlaki kurallara uymayan sorulara yanıt veremem. Lütfen daha uygun bir soru sorun.'})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(event_generator_profanity(), media_type="text/event-stream")


    messages = []
    system_prompt = rag_engine.build_system_prompt(latest_user_msg, user_context or None)
    messages.append({"role": "system", "content": system_prompt})
    messages.extend([{"role": m.role, "content": m.content} for m in req.messages])

    payload = {
        "model": MODEL_ID,
        "messages": messages,
        "temperature": req.temperature,
        "stream": True,
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Dietitian Chatbot v2",
    }

    async def event_generator():
        client = _http_client or httpx.AsyncClient(timeout=60.0)
        try:
            async with client.stream("POST", OPENROUTER_BASE_URL, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    yield f"data: {json.dumps({'error': 'OpenRouter API Error'})}\n\n"
                    return

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            yield "data: [DONE]\n\n"
                            break
                        try:
                            chunk = json.loads(data)
                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            content = choices[0].get("delta", {}).get("content", "")
                            if content:
                                yield f"data: {json.dumps({'content': content})}\n\n"
                        except (json.JSONDecodeError, IndexError):
                            continue
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/health")
async def health():
    return {"status": "ok", "rag_ready": rag_engine.is_ready(), "model": MODEL_ID}
