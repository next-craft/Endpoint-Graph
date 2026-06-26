from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class AnalyzeRequest(BaseModel):
    repo_url: str


class AnalyzeResponse(BaseModel):
    status: str
    services: int
    endpoints: int
    edges: int


class ServiceOut(BaseModel):
    id: int
    name: str
    language: Optional[str]
    repo_url: Optional[str]


class EndpointOut(BaseModel):
    id: int
    service_id: int
    method: str
    path: str
    spec_source: Optional[str]


class ConsumerOut(BaseModel):
    service_name: str
    call_count: int
    last_seen_at: datetime
    source: str


class GraphNode(BaseModel):
    id: str
    name: str


class GraphEdge(BaseModel):
    source: str
    target: str
    endpoint_path: str
    endpoint_method: str
    call_count: int
    last_seen_at: datetime


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class HealthResponse(BaseModel):
    status: str
