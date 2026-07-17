"""Ollama bridge router for the FastAPI backend.

This is the ONLY public path from Streamlit Cloud (via ngrok) to the local
Ollama instance on the laptop. Raw Ollama is never exposed through ngrok;
the FastAPI server forwards to ``OLLAMA_BASE_URL`` (default
``http://127.0.0.1:11434``). When ``API_TOKEN`` is set, every route requires
``Authorization: Bearer <API_TOKEN>``. The token is read from the environment
and is never logged or returned in responses.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/ollama", tags=["ollama"])

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
_API_TOKEN = os.getenv("API_TOKEN", "")


def check_auth(authorization: str | None) -> None:
    """Require a valid bearer token when API_TOKEN is configured."""
    if not _API_TOKEN:
        return
    expected = f"Bearer {_API_TOKEN}"
    if authorization != expected:
        # Do not echo the token or the failure reason.
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/status")
async def ollama_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    check_auth(authorization)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            response.raise_for_status()
            data = response.json()

        models = data.get("models", [])
        model_names = [
            item.get("name")
            for item in models
            if isinstance(item, dict) and item.get("name")
        ]

        return {
            "available": True,
            "model": OLLAMA_MODEL,
            "model_available": OLLAMA_MODEL in model_names,
            "models": models,
            "model_names": model_names,
        }

    except Exception as exc:
        # Never raise: FastAPI must stay up even if Ollama is down.
        return {
            "available": False,
            "model": OLLAMA_MODEL,
            "error": str(exc),
        }


class GenerateRequest(BaseModel):
    prompt: str
    model: str | None = None
    system: str | None = None
    temperature: float = 0.3


@router.post("/generate")
async def ollama_generate(
    request: GenerateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    check_auth(authorization)

    prompt = request.prompt
    if request.system:
        prompt = f"{request.system}\n\n{request.prompt}"

    payload = {
        "model": request.model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": request.temperature,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()

        return {
            "ok": True,
            "model": payload["model"],
            "response": data.get("response", ""),
            "raw": data,
        }

    except Exception as exc:
        return {
            "ok": False,
            "model": payload["model"],
            "error": str(exc),
        }


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None
    temperature: float = 0.3


@router.post("/chat")
async def ollama_chat(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    check_auth(authorization)

    payload = {
        "model": request.model or OLLAMA_MODEL,
        "messages": [message.model_dump() for message in request.messages],
        "stream": False,
        "options": {
            "temperature": request.temperature,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {})
        content = message.get("content", "") if isinstance(message, dict) else ""

        return {
            "ok": True,
            "model": payload["model"],
            "message": content,
            "raw": data,
        }

    except Exception as exc:
        return {
            "ok": False,
            "model": payload["model"],
            "error": str(exc),
        }
