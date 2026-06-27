from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import get_pool
from models import HealthResponse
from routers.analyze import router as analyze_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield


app = FastAPI(title="EndpointGraph API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router)

# Remaining routers registered here as specs are implemented:
# from routers import services, endpoints, graph
# app.include_router(services.router)
# app.include_router(endpoints.router)
# app.include_router(graph.router)


@app.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "ok"}
