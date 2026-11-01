"""Counted service: website, REST API (API keys), MCP server and A2A agent, all on one origin.

    uv run counted-api            # http://localhost:8080
      /                 website (what, why, how, live demo, results, API docs)
      /docs             OpenAPI reference (auto-generated)
      /v1/...           REST API
      /mcp              MCP server (streamable HTTP)
      /a2a              Agent-to-Agent endpoint (agent card at /a2a/.well-known/agent-card.json)
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__, budget
from ..agents.interviewer import CaseSession, build_interviewer
from ..pipeline import assess
from ..tools.facts import disaster_context, geocode
from . import keys
from .mcp_server import mcp

log = logging.getLogger("counted.api")
ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
RESULTS = ROOT / "evals" / "results"
ADMIN_TOKEN = os.getenv("COUNTED_ADMIN_TOKEN", "")

mcp_app = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Counted API",
    version=__version__,
    summary="Find the disaster hidden inside a death. Drafts for certifiers; never certifies.",
    description=(
        "Counted interviews a bereaved family (or reads a caseworker's account), checks FEMA and National Weather "
        "Service records, and applies the CDC disaster death-certification guidance with a three-seat examiner "
        "panel (deterministic CDC decision tree, Claude, Amazon Nova) and an adjudicator. It returns a determination "
        "(direct / indirect / not_related / possible), a draft certifier statement, a FEMA Funeral Assistance packet "
        "and a surveillance record.\n\nAuthenticate with `x-api-key`. Get a key with `POST /v1/keys`."
    ),
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(budget.BudgetExceeded)
def _over_budget(_: Request, exc: budget.BudgetExceeded):
    return JSONResponse({"detail": str(exc)}, status_code=429)

app.mount("/mcp", mcp_app)


# ------------------------------------------------------------------ helpers

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request, per_hour: int = 30) -> None:
    ip = request.client.host if request.client else "?"
    q, now = _hits[ip], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= per_hour:
        raise HTTPException(429, "Demo limit reached for this hour. Get a free API key at POST /v1/keys.")
    q.append(now)


def require_key(x_api_key: str | None = Header(default=None)) -> dict:
    rec = keys.lookup(x_api_key)
    if not rec:
        raise HTTPException(401, "Missing or invalid x-api-key. Get one with POST /v1/keys.")
    return rec


# ------------------------------------------------------------------ models

class KeyRequest(BaseModel):
    name: str = Field(description="Who is using the key (organisation or project).", examples=["Harris County 211"])
    role: str = Field(default="service", description="service | caseworker | certifier (certifier needs the admin token)")


class AssessRequest(BaseModel):
    account: str = Field(description="What happened, in the family's or caseworker's words.",
                         examples=["My mother, 78, lived at 4602 Kiam St, Houston, TX. During Winter Storm Uri the power went "
                                   "out Feb 15 and her oxygen machine stopped. She died at home on 2021-02-17."])
    language: str = Field(default="en", description="en | es: language of the family packet")


class TurnRequest(BaseModel):
    message: str = ""
    consent: bool | None = Field(default=None, description="Family consent for Counted to prepare a determination.")


class InterviewStart(BaseModel):
    language: str = "en"
    role: str = "family"


# ------------------------------------------------------------------ keys + assessment

@app.post("/v1/keys", tags=["Access"], summary="Get an API key (shown once)")
def create_key(body: KeyRequest, request: Request, x_admin_token: str | None = Header(default=None)):
    rate_limit(request, per_hour=10)
    if body.role == "certifier" and (not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN):
        raise HTTPException(403, "Certifier keys are issued only to verified medical examiners and coroners.")
    try:
        return keys.issue(body.name, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/assess", tags=["Assessment"], summary="Assess one death (API key)")
def assess_endpoint(body: AssessRequest, key: dict = Depends(require_key)):
    return assess(body.account, language=body.language)


@app.post("/v1/demo/assess", tags=["Assessment"], summary="Assess one death (public demo, rate-limited)")
def demo_assess(body: AssessRequest, request: Request):
    rate_limit(request)
    return assess(body.account, language=body.language)


@app.get("/v1/records", tags=["Public records"], summary="FEMA declaration + NWS warnings for a place and date")
def records(address: str, date_of_death: date, request: Request):
    rate_limit(request, per_hour=120)
    place = geocode(address) or {}
    ctx = disaster_context(place.get("state"), place.get("county"), date_of_death, place.get("lat"), place.get("lon"))
    return {"place": place, **ctx.model_dump(mode="json")}


# ------------------------------------------------------------------ live interviews

_sessions: dict[str, dict[str, Any]] = {}
_sessions_lock = threading.Lock()


def _snapshot(s: CaseSession) -> dict:
    return {
        "id": s.id,
        "facts": s.facts.model_dump(mode="json"),
        "context": s.context.model_dump(mode="json") if s.context else None,
        "panel": s.panel.model_dump(mode="json") if s.panel else None,
        "documents": s.documents or None,
        "events": s.events[-60:],
    }


@app.post("/v1/interviews", tags=["Interview"], summary="Start an interview session")
def start_interview(body: InterviewStart, request: Request):
    rate_limit(request)
    s = CaseSession(role="family" if body.role not in ("caseworker",) else body.role)
    s.facts.language = body.language
    with _sessions_lock:
        if len(_sessions) > 500:  # simple cap for the public demo
            oldest = sorted(_sessions, key=lambda k: _sessions[k]["updated"])[:100]
            for k in oldest:
                _sessions.pop(k, None)
        _sessions[s.id] = {"agent": build_interviewer(), "session": s, "lock": threading.Lock(), "updated": time.time(), "pending": []}
    greeting = ("Lamento mucho su pérdida. Estoy aquí para ayudarle a documentar lo que pasó, a su ritmo. ¿Quién era la persona y qué relación tenía con usted?"
                if body.language == "es" else
                "I'm so sorry for your loss. I'm here to help document what happened, at your pace. Can you tell me who passed away and how you were related?")
    return {"id": s.id, "reply": greeting, "case": _snapshot(s)}


@app.post("/v1/interviews/{sid}/turn", tags=["Interview"], summary="Send the next message")
def interview_turn(sid: str, body: TurnRequest, request: Request):
    rate_limit(request, per_hour=200)
    budget.spend()
    entry = _sessions.get(sid)
    if not entry:
        raise HTTPException(404, "Interview not found or expired.")
    s: CaseSession = entry["session"]
    with entry["lock"]:
        state = {"session": s, "role": s.role, "consent": body.consent}
        agent = entry["agent"]
        if entry["pending"] and body.consent is not None:
            prompt = [{"interruptResponse": {"interruptId": i, "response": "yes" if body.consent else "no"}} for i in entry["pending"]]
            entry["pending"] = []
        else:
            prompt = body.message
        result = agent(prompt, invocation_state=state)
        entry["updated"] = time.time()
        interrupts = getattr(result, "interrupts", None) or []
        if interrupts:
            entry["pending"] = [i.id for i in interrupts]
            return {"id": sid, "reply": interrupts[0].reason if isinstance(interrupts[0].reason, str) else
                    "May Counted prepare a draft determination for the medical examiner?", "needs_consent": True, "case": _snapshot(s)}
        return {"id": sid, "reply": str(result).strip(), "needs_consent": False, "case": _snapshot(s)}


@app.get("/v1/interviews/{sid}", tags=["Interview"], summary="Get the live case file")
def get_interview(sid: str):
    entry = _sessions.get(sid)
    if not entry:
        raise HTTPException(404, "Interview not found or expired.")
    return _snapshot(entry["session"])


# ------------------------------------------------------------------ evidence

@app.get("/v1/results", tags=["Evidence"], summary="Latest evaluation summary")
def results():
    f = RESULTS / "latest.json"
    if not f.exists():
        raise HTTPException(404, "No evaluation has been run yet.")
    return JSONResponse(json.loads(f.read_text(encoding="utf-8")))


@app.get("/v1/results/rows", tags=["Evidence"], summary="Per-circumstance breakdown for one replay set")
def result_rows(set: str = "uri_replay"):
    latest = json.loads((RESULTS / "latest.json").read_text(encoding="utf-8"))
    rows: dict[str, dict] = {}
    for line in (RESULTS / latest["tag"] / "predictions.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["set"] != set:
            continue
        b = rows.setdefault(r["row"] or "?", {"row": r["row"], "official": defaultdict(int), "counted": defaultdict(int), "direct_only": defaultdict(int)})
        b["official"][r["label"]] += 1
        for sysname in ("counted", "direct_only"):
            if sysname in r["pred"]:
                b[sysname][r["pred"][sysname]] += 1
    return list(rows.values())


@app.get("/v1/samples", tags=["Evidence"], summary="Sample accounts for the demo")
def samples():
    return json.loads((WEB / "samples.json").read_text(encoding="utf-8"))


@app.get("/v1/health", tags=["Access"])
def health():
    return {"ok": True, "version": __version__}


# ------------------------------------------------------------------ A2A + website

def _mount_a2a() -> None:
    try:
        from strands import Agent, tool
        from strands.multiagent.a2a import A2AServer

        @tool
        def assess_disaster_death(account: str, language: str = "en") -> dict:
            """Assess whether a death was directly or indirectly caused by a declared disaster (CDC guidance).

            Args:
                account: What happened: age, place, date of death, disaster, circumstances.
                language: en | es
            """
            r = assess(account, language=language)
            return {"determination": r["panel"]["final"], "fema_declaration": r["context"].get("declaration"),
                    "certifier_statement": r["documents"]["certifier_statement"]}

        def factory(_ctx: str) -> Agent:
            from ..agents.panel import bedrock
            from ..config import INTERVIEW_MODEL
            return Agent(name="Counted", description="Determines whether a death was directly or indirectly caused by a "
                         "declared US disaster, following CDC guidance, and drafts the certifier statement.",
                         model=bedrock(INTERVIEW_MODEL), tools=[assess_disaster_death], callback_handler=None)

        base = os.getenv("COUNTED_PUBLIC_URL", "http://localhost:8080")
        server = A2AServer(agent_factory=factory, http_url=f"{base}/a2a", serve_at_root=True)
        app.mount("/a2a", server.to_starlette_app())
    except Exception as exc:  # A2A is additive; the API must still start without it
        log.warning("A2A endpoint disabled: %s", exc)


_mount_a2a()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    # Behind a load balancer, rate limits must see the visitor's address, not the balancer's.
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8080")),
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
