"""RAG API 请求/响应 Pydantic 模型

遵循 RAG Response Contract v1（见 contracts/service/）。
所有响应必须携带 citations、evidence_ids、trace_id、release_id。
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# ── 证据锚点 ─────────────────────────────────────────────────────────────────

class EvidenceAnchor(BaseModel):
    """单条证据的源头引用，可追溯到具体文档位置"""
    source_id: str
    source_url: Optional[str] = None
    page_no: Optional[int] = None
    section_path: Optional[str] = None
    doc_version: Optional[str] = None
    modality: Literal["document", "audio", "video"] = "document"
    start_ts: Optional[float] = None   # 音视频起始时间戳（秒）
    end_ts: Optional[float] = None     # 音视频结束时间戳（秒）


# ── 检索结果片段 ─────────────────────────────────────────────────────────────

class RetrievedChunk(BaseModel):
    chunk_id: str
    content: str
    score: float = Field(ge=0.0, le=1.0)
    rerank_score: Optional[float] = None
    evidence_anchor: EvidenceAnchor


# ── 查询请求 ──────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    """RAG 查询请求"""
    query: str = Field(..., min_length=1, max_length=2048, description="用户问题")
    product_line: Optional[Literal[
        "northstar_workspace",
        "northstar_edge_gateway",
        "northstar_studio",
        "any"
    ]] = "any"
    modalities: List[Literal["document", "audio", "video"]] = ["document"]
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0.6, ge=0.0, le=1.0)
    session_id: Optional[str] = None
    idempotency_key: Optional[str] = None


# ── 查询响应 ──────────────────────────────────────────────────────────────────

class QueryResponse(BaseModel):
    """RAG 查询响应 — 符合 RAG Response Contract v1"""
    answer: str
    citations: List[str] = Field(
        description="可读引用列表，如 '[文档名, 第N页]'"
    )
    evidence_ids: List[str] = Field(
        description="chunk_id 列表，用于审计追踪"
    )
    retrieved_chunks: List[RetrievedChunk] = Field(
        description="原始检索结果，用于调试"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    answer_grounded: bool = Field(
        description="答案是否有证据支撑（confidence >= min_score）"
    )
    release_id: str
    trace_id: str
    session_id: Optional[str] = None


# ── 健康检查 ──────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    service: str
    version: str
    release_id: str
    checks: dict


# ── 管理接口 ──────────────────────────────────────────────────────────────────

class ReleaseInfoResponse(BaseModel):
    release_id: str
    data_release_id: str
    index_release_id: str
    prompt_release_id: str


# ── Week8 RAG contract models ────────────────────────────────────────────────

class Citation(BaseModel):
    evidence_id: str
    chunk_id: str
    section_id: Optional[str] = None
    doc_id: str
    source_id: str
    title: Optional[str] = None
    page_no: Optional[int] = None
    section_path: Optional[str] = None
    bbox: Optional[str] = None
    source_url: Optional[str] = None
    doc_version: Optional[str] = None
    quote: Optional[str] = None
    score: Optional[float] = None


class RetrievalContext(BaseModel):
    chunk_id: str
    content: str
    score: float
    citation: Citation


class RetrievalDebugItem(BaseModel):
    chunk_id: str
    vector_score: Optional[float] = None
    fts_score: Optional[float] = None
    rrf_score: Optional[float] = None
    rerank_score: Optional[float] = None
    final_score: float


class RetrievalDebugPayload(BaseModel):
    mode: Literal[
        "vector", "fts", "hybrid_rrf", "hybrid_rrf_rerank",
        "graph_local", "graph_global", "graph_multihop", "graph_drift",
    ] = "hybrid_rrf"
    rrf_k: int = 60
    rerank_enabled: bool = False
    rerank_fallback: bool = False
    filters_applied: dict
    results: List[RetrievalDebugItem]


class RagAnswerRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2048)
    tenant_id: Optional[str] = None
    product_line: Optional[str] = None
    actor_role: Optional[str] = None
    visibility_scope: Optional[str] = None
    entitlement_tier: Optional[str] = None
    status: Optional[str] = None
    quality_status: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    index_release_id: Optional[str] = None
    data_release_id: Optional[str] = None
    prompt_release_id: Optional[str] = None
    graph_release_id: Optional[str] = None
    retrieval_mode: Literal[
        "hybrid", "auto", "graph_local", "graph_global", "graph_multihop", "graph_drift"
    ] = "hybrid"
    max_graph_hops: int = Field(default=2, ge=1, le=3)
    include_debug: bool = False


class GraphRetrievalDebug(BaseModel):
    requested_mode: str
    selected_mode: str
    graph_release_id: Optional[str] = None
    route_confidence: float = Field(ge=0.0, le=1.0)
    route_reasons: List[str] = Field(default_factory=list)
    paths: List[dict] = Field(default_factory=list)
    communities: List[dict] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    fallback_reason: Optional[str] = None


class RagAnswerResponse(BaseModel):
    answer: str
    citations: List[Citation]
    evidence_ids: List[str]
    confidence: float = Field(ge=0.0, le=1.0)
    abstain_reason: Optional[str]
    release_id: str
    data_release_id: Optional[str]
    index_release_id: str
    prompt_release_id: str
    graph_release_id: Optional[str] = None
    retrieval_mode: str = "hybrid"
    generation_mode: Literal["llm", "deterministic_fallback", "not_invoked"]
    generation_provider: str
    generation_model: str
    trace_id: str
    retrieved_contexts: Optional[List[RetrievalContext]] = None
    retrieval_debug: Optional[RetrievalDebugPayload] = None
    graph_debug: Optional[GraphRetrievalDebug] = None
