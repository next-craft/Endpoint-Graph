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
    file_path: Optional[str]
    function_name: Optional[str]


class ConsumerOut(BaseModel):
    service_name: str
    caller_function_name: Optional[str]
    caller_file_path: Optional[str]
    call_count: int
    last_seen_at: datetime
    source: str


class GraphNode(BaseModel):
    id: str
    node_type: str
    label: str
    function_name: Optional[str]
    method: Optional[str]
    path: Optional[str]
    file_path: Optional[str]
    service_name: str
    service_id: int


class GraphEdge(BaseModel):
    source: str
    target: str
    call_count: int
    last_seen_at: datetime


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    service_count: int
    endpoint_count: int


class RepoOut(BaseModel):
    name: str
    full_name: str
    private: bool
    updated_at: str
    tracked: bool
    last_analyzed_at: datetime | None
    service_id: int | None


class HealthResponse(BaseModel):
    status: str
