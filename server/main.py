"""DOS (DigiQuench OS) server: one container, five layers.

  /            layer 1  the Agent Console (static single-page app)
  /api/*       the control plane the console talks to
  dq.clients   layer 2  client configuration
  dq.data      layer 3  data gate, inventory, lineage
  dq.factory, dq.runs   layer 4  agents on the Google ADK
  dq.plugins, dq.governance   layer 5  safety, security, governance

Run locally:   DQ_MODEL_MODE=mock uvicorn main:app --reload --port 8080
Run with Gemini: export GOOGLE_API_KEY=...  &&  uvicorn main:app --port 8080"""
import logging
import os
import pathlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import asyncio

from dq import config, plant, response
from dq.api import build_auth_router, build_router
from dq.app_api import build_app_router, build_public_router
from dq.auth import read_token, seed_users
from dq.clients import as_client, client_file_users, list_clients, manufacturing_clients, seed_clients
from dq.context import actor_var, client_var, role_var, user_var
from dq.runs import RunManager
from dq.spec import AgentSpec, load_catalog
from dq.store import get_store

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("dq")
HERE = pathlib.Path(__file__).resolve().parent


def setup_tracing() -> None:
    """Send the ADK's OpenTelemetry spans to Cloud Trace when running on Google Cloud."""
    if not config.PROJECT or os.getenv("DQ_TRACE", "1") == "0":
        return
    try:
        from opentelemetry import trace  # noqa: PLC0415
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter  # noqa: PLC0415
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

        provider = TracerProvider(resource=Resource.create({"service.name": "dq-platform"}))
        provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter(project_id=config.PROJECT)))
        trace.set_tracer_provider(provider)
        log.info("Cloud Trace export enabled for project %s", config.PROJECT)
    except Exception as exc:  # tracing must never stop the server from starting
        log.warning("Cloud Trace export not enabled: %s", exc)


class ContextMiddleware:
    """Pure ASGI middleware: puts the caller's client and role into context variables for the whole request.
    Everything underneath (store, policy(), ds(), audit) reads them from there."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            auth = headers.get("authorization", "")
            payload = read_token(auth[7:]) if auth.lower().startswith("bearer ") else None
            if payload:  # signed in: client, role and user come ONLY from the signed token
                client_var.set(payload["c"])
                role_var.set(payload["r"])
                actor_var.set(payload["u"])
                user_var.set({"username": payload["u"], "name": payload["n"], "role": payload["r"], "technician_id": payload.get("t")})
            elif config.AUTH_MODE == "headers":  # automated tests and local scripts only
                role = headers.get("x-dq-role") or "owner"
                client_var.set(headers.get("x-dq-client") or config.TENANT)
                role_var.set(role)
                actor_var.set(headers.get("x-dq-actor") or ("console-user" if "x-dq-role" not in headers else f"{role}@{client_var.get()}"))
                user_var.set({"username": actor_var.get(), "name": actor_var.get(), "role": role, "technician_id": headers.get("x-dq-technician")})
            else:
                client_var.set(config.TENANT)
                role_var.set("anonymous")
                actor_var.set("anonymous")
                user_var.set(None)
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    setup_tracing()
    seeded = seed_clients()
    users = seed_users(client_file_users())
    catalog = load_catalog()
    for c in list_clients():  # agents added through the Agent Builder, per client
        with as_client(c["id"]):
            for doc in get_store().list("custom_specs", limit=500):
                catalog[doc["id"]] = AgentSpec(**doc["spec"])
    manager = RunManager(catalog)
    app = FastAPI(title="DOS - DigiQuench OS", version="0.3.0")
    app.add_middleware(CORSMiddleware, allow_origins=config.ALLOW_ORIGINS, allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(ContextMiddleware)
    log.info("Clients: %d (%d seeded now), users seeded now: %d", len(list_clients()), seeded, users)
    app.include_router(build_auth_router())
    app.include_router(build_public_router())  # DOS app: companies, role cards, sign-in with a login code
    app.include_router(build_router(catalog, manager))
    app.include_router(build_app_router(catalog, manager))  # DOS app: home, Agent Studio, launcher, Ask DOS, layers

    @app.on_event("startup")
    async def start_plant_loop():
        # The live plant: telemetry every 2 seconds for every manufacturing client; confirmed alarms start the
        # six-agent downtime response; unacknowledged work orders are escalated.
        if config.PLANT_LOOP:
            app.state.plant_task = asyncio.create_task(plant.run_loop(
                on_alarm=lambda cid, inc: response.respond(manager, cid, inc),
                tick_check=response.check_escalations, clients=manufacturing_clients))
    app.state.manager, app.state.catalog = manager, catalog

    @app.get("/healthz")
    def healthz():
        return JSONResponse({"status": "ok", "agents": len(catalog), "mode": config.MODEL_MODE, "store": config.STORE})

    @app.get("/health")  # Cloud Run keeps /healthz for itself on the public address; this one reaches DOS
    def health():
        return healthz()

    console = HERE / "console"
    if console.exists():
        app.mount("/assets", StaticFiles(directory=console), name="assets")

        @app.get("/")
        def index():
            # no-cache: after every deployment browsers fetch the newest app instead of a saved copy
            return FileResponse(console / "index.html", headers={"Cache-Control": "no-cache"})

    log.info("DOS ready: %d agents, mode=%s, store=%s", len(catalog), config.MODEL_MODE, config.STORE)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
