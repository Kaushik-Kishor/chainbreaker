from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.graph.neo4j_client import neo4j_client
from backend.utils.logger import setup_logger

logger = setup_logger("fastapi_main")


def create_app() -> FastAPI:
    app = FastAPI(
        title="ChainBreaker API",
        description="Graph-Driven Cyber Incident Detection, Forensic Analysis & Kill Chain Interruption",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup():
        neo4j_client.connect()
        logger.info("api_startup_complete")

    @app.on_event("shutdown")
    async def shutdown():
        await neo4j_client.close()
        logger.info("api_shutdown_complete")

    @app.get("/health")
    async def health():
        return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

    from backend.api.routes import graph, forensics, alerts, ml, agent, ws
    import asyncio
    
    @app.on_event("startup")
    async def start_mock_stream():
        # First ensure models are trained and ready
        ml.get_model_manager().auto_train_if_needed()
        # Then start the mock stream in background
        asyncio.create_task(ws.mock_telemetry_stream())

    app.include_router(graph.router, prefix="/api/graph", tags=["Graph"])
    app.include_router(forensics.router, prefix="/api/forensics", tags=["Forensics"])
    app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts"])
    app.include_router(ml.router, prefix="/api/ml", tags=["ML"])
    app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
    app.include_router(ws.router, prefix="/api/ws", tags=["WebSocket"])

    return app


app = create_app()
