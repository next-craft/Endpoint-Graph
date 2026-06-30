import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import get_pool
from models import HealthResponse
from routers.analyze import router as analyze_router
from routers.services import router as services_router
from routers.endpoints import router as endpoints_router
from routers.graph import router as graph_router
from routers.repos import router as repos_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield


app = FastAPI(title="EndpointGraph API", lifespan=lifespan)

_origins = ["http://localhost:3000"]
_frontend_url = os.getenv("FRONTEND_URL")
if _frontend_url:
    _origins.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router)
app.include_router(services_router)
app.include_router(endpoints_router)
app.include_router(graph_router)
app.include_router(repos_router, prefix="/repos")


@app.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "ok"}
