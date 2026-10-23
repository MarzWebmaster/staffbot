"""OpenAI-compatible LLM proxy for customer Hermes containers.

Every model call from a customer container comes here with the customer's
proxy token. The proxy authenticates the customer, enforces the package
(models, quota, BYOK), applies guardrails, calls the provider with a key the
container never sees, and records usage for every round of the agent loop.
"""
import json
import logging
from typing import AsyncIterator, Optional

import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, get_db
from app.llm_proxy import guardrails
from app.llm_proxy.routing import Route, RoutingError, managed_route, resolve_route
from app.llm_proxy.tokens import parse_token
from app.models.client import Client
from app.models.package import Package
from app.models.subscription import Subscription
from app.models.token_usage import TokenUsageLog
from app.services.audit import log_audit
from app.services.content_moderation import moderate_message

logger = logging.getLogger("llm_proxy")
app = FastAPI(title="StaffBot.my LLM Proxy", version="1.0.0")

# Core tools for the StaffBot Hermes plugin are served here too, so customer
# containers only ever need to reach this one platform endpoint.
from app.routers.agent_tools import router as agent_tools_router  # noqa: E402
app.include_router(agent_tools_router, prefix="/api/v1/agent-tools", tags=["Agent Tools"])

UPSTREAM_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
# Fields some clients send that providers reject or that we must not forward
STRIPPED_FIELDS = {"api_key", "base_url", "client_id"}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": code, "code": code}})


class Caller:
    def __init__(self, client: Client, pkg: Package, sub: Optional[Subscription]):
        self.client, self.pkg, self.sub = client, pkg, sub


async def authenticate(authorization: Optional[str], db: AsyncSession) -> Caller | JSONResponse:
    token = (authorization or "").removeprefix("Bearer ").strip()
    parsed = parse_token(token)
    if not parsed:
        return _error(401, "invalid_api_key", "Invalid StaffBot token.")
    client_id, version = parsed
    client = (await db.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if not client or (client.llm_token_version or 1) != version:
        return _error(401, "invalid_api_key", "Token revoked.")
    if client.status != "active":
        return _error(403, "account_inactive", f"Account is {client.status}.")
    pkg = (await db.execute(select(Package).where(Package.name == client.package))).scalar_one_or_none()
    if not pkg:
        return _error(403, "no_package", "No active package.")
    sub = (await db.execute(select(Subscription).where(Subscription.client_id == client_id))).scalar_one_or_none()
    return Caller(client, pkg, sub)


def _quota_exceeded(sub: Optional[Subscription]) -> Optional[str]:
    if not sub or sub.status != "active":
        return "No active subscription."
    quota, used = sub.managed_token_quota or 0, sub.managed_token_used or 0
    if quota > 0 and used >= quota:
        return "Managed token quota used up. Top up, upgrade, or add your own API key."
    return None


async def record_usage(client_id: int, route: Route, usage: dict, status: str = "success") -> None:
    """Log one upstream call and charge managed quota. Own session: safe after streaming."""
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or prompt + completion)
    async with async_session_factory() as db:
        db.add(TokenUsageLog(
            client_id=client_id, provider=route.provider, model=route.model,
            input_tokens=prompt, output_tokens=completion, total_tokens=total, endpoint="llm-proxy",
        ))
        if route.key_source == "managed" and total:
            await db.execute(
                update(Subscription)
                .where(Subscription.client_id == client_id)
                .values(managed_token_used=Subscription.managed_token_used + total)
            )
        await db.commit()
    await log_audit(
        client_id=client_id, action="llm_call", resource=f"provider:{route.provider}",
        detail={"model": route.model, "requested_model": route.requested_model, "key_source": route.key_source,
                "input_tokens": prompt, "output_tokens": completion, "total_tokens": total},
        status=status,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "llm-proxy"}


@app.get("/v1/models")
async def list_models(authorization: Optional[str] = Header(None), db: AsyncSession = Depends(get_db)):
    caller = await authenticate(authorization, db)
    if isinstance(caller, JSONResponse):
        return caller
    models = [m for m in (caller.pkg.allowed_models or []) if m != "*"]
    if not models:
        try:
            models = [(await managed_route(db, caller.pkg, "")).model]
        except RoutingError as e:
            return _error(e.status, e.code, e.message)
    return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "staffbot"} for m in models]}


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    caller = await authenticate(authorization, db)
    if isinstance(caller, JSONResponse):
        return caller
    try:
        body = await request.json()
    except Exception:
        return _error(400, "invalid_request", "Body must be JSON.")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return _error(400, "invalid_request", "messages is required.")
    client_id = caller.client.id
    stream = bool(body.get("stream"))

    try:
        route = await resolve_route(db, client_id, caller.pkg, str(body.get("model") or ""))
    except RoutingError as e:
        return _error(e.status, e.code, e.message)

    if route.key_source == "managed":
        reason = _quota_exceeded(caller.sub)
        if reason:
            await log_audit(client_id=client_id, action="llm_call", resource="quota", detail={"reason": reason}, status="blocked")
            return _error(402, "quota_exceeded", reason)

    # Input guardrail: once per user turn
    user_text = guardrails.latest_user_turn(messages)
    if user_text:
        violation = await moderate_message(message=user_text, client_id=client_id, db=db)
        if violation:
            await db.commit()
            await log_audit(client_id=client_id, action="llm_call", resource="moderation",
                            detail={"categories": violation.get("categories", [])}, status="blocked")
            refusal = guardrails.refusal_completion(route.model, violation["message"])
            if stream:
                return StreamingResponse(_refusal_stream(refusal), media_type="text/event-stream")
            return refusal

    payload = {k: v for k, v in body.items() if k not in STRIPPED_FIELDS}
    payload["model"] = route.model
    payload["messages"] = guardrails.with_policy(messages, await guardrails.policy_prompt(db))
    if stream:
        payload["stream_options"] = {**(payload.get("stream_options") or {}), "include_usage": True}

    url = route.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {route.api_key}", "Content-Type": "application/json"}
    extra = {"X-StaffBot-Model": route.model}
    if route.substituted:
        extra["X-StaffBot-Model-Substituted"] = route.requested_model or "(none)"

    if stream:
        return StreamingResponse(
            _stream_upstream(url, headers, payload, client_id, route),
            media_type="text/event-stream", headers=extra,
        )

    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as http:
            resp = await http.post(url, headers=headers, json=payload)
    except httpx.HTTPError as e:
        logger.warning("upstream error for client %s: %s", client_id, e)
        return _error(502, "upstream_unavailable", "LLM provider unreachable.")
    if resp.status_code != 200:
        await log_audit(client_id=client_id, action="llm_call", resource=f"provider:{route.provider}",
                        detail={"model": route.model, "upstream_status": resp.status_code}, status="failure")
        return _passthrough_error(resp, (route.api_key,))
    data = resp.json()
    await record_usage(client_id, route, data.get("usage") or {})
    return JSONResponse(guardrails.redact_completion(data, (route.api_key,)), headers=extra)


def _passthrough_error(resp: httpx.Response, secrets: tuple) -> JSONResponse:
    try:
        content = resp.json()
    except Exception:
        content = {"error": {"message": resp.text[:500], "type": "upstream_error"}}
    # Never echo the provider key back if the upstream includes it
    return JSONResponse(status_code=resp.status_code, content=json.loads(guardrails.redact(json.dumps(content), secrets)))


async def _refusal_stream(refusal: dict) -> AsyncIterator[bytes]:
    text = refusal["choices"][0]["message"]["content"]
    chunk = {"id": refusal["id"], "object": "chat.completion.chunk", "model": refusal["model"],
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}
    yield f"data: {json.dumps(chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"


def _estimate_usage(payload: dict, completion_chars: int) -> dict:
    """Fallback when a provider streams without a usage chunk (~4 chars/token)."""
    prompt = len(json.dumps(payload.get("messages", []))) // 4
    completion = completion_chars // 4
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


async def _stream_upstream(url: str, headers: dict, payload: dict, client_id: int, route: Route) -> AsyncIterator[bytes]:
    usage: dict = {}
    completion_chars = 0
    status = "success"
    secrets = (route.api_key,)
    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as http:
            async with http.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    status = "failure"
                    body = guardrails.redact((await resp.aread()).decode(errors="replace"), secrets)[:500]
                    err = {"error": {"message": body, "type": "upstream_error", "code": resp.status_code}}
                    yield f"data: {json.dumps(err)}\n\n".encode()
                    yield b"data: [DONE]\n\n"
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        if line:
                            yield (line + "\n").encode()
                        else:
                            yield b"\n"
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        yield b"data: [DONE]\n\n"
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        yield (line + "\n\n").encode()
                        continue
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        completion_chars += len(delta.get("content") or "")
                        completion_chars += len(json.dumps(delta.get("tool_calls"))) if delta.get("tool_calls") else 0
                    yield f"data: {json.dumps(guardrails.redact_chunk(chunk, secrets))}\n\n".encode()
    except httpx.HTTPError as e:
        status = "failure"
        logger.warning("upstream stream error for client %s: %s", client_id, e)
        err = {"error": {"message": "LLM provider unreachable.", "type": "upstream_unavailable"}}
        yield f"data: {json.dumps(err)}\n\n".encode()
    finally:
        if status == "success":
            await record_usage(client_id, route, usage or _estimate_usage(payload, completion_chars))
