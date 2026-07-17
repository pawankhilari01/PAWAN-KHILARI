"""Central, environment-driven configuration for the EDT Platform.

All configuration is 12-factor: read from environment variables (backed by Vault
in production via the External Secrets Operator). Never hard-code secrets.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelTier(str, Enum):
    """Claude model tiers used for cost/quality routing (see Cost Optimization Agent)."""

    REASONING = "claude-opus-4-8"      # deep reasoning, critique, synthesis, go/no-go
    DEFAULT = "claude-sonnet-5"        # workhorse for most agents
    FAST = "claude-haiku-4-5"          # cheap/fast extraction, classification, formatting


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDT_LLM_", extra="ignore")

    anthropic_api_key: str = Field(default="", description="Anthropic API key (from Vault).")
    default_tier: ModelTier = ModelTier.DEFAULT
    max_output_tokens: int = 8192
    temperature: float = 0.4
    # Prompt caching + extended thinking toggles.
    enable_prompt_caching: bool = True
    enable_extended_thinking: bool = True
    thinking_budget_tokens: int = 4000


class StoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDT_STORE_", extra="ignore")

    postgres_dsn: str = "postgresql+asyncpg://edt:edt@localhost:5432/edt"
    # Durable run-history store. Defaults to a local SQLite file so history survives
    # restarts with zero infrastructure; in production set this to the async Postgres
    # DSN (e.g. postgresql+asyncpg://edt:...@rds/edt) for a shared, HA history store.
    history_url: str = "sqlite+aiosqlite:///./data/edt.db"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "edt-artifacts"


class EventSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDT_EVENT_", extra="ignore")

    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"
    topic_prefix: str = "edt"


class RAGSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDT_RAG_", extra="ignore")

    embedding_model: str = "voyage-3"
    embedding_dim: int = 1024
    rerank_model: str = "rerank-2"
    hybrid_alpha: float = 0.5           # weight between dense (1.0) and BM25 (0.0)
    top_k_retrieve: int = 40
    top_k_rerank: int = 8
    enable_contextual_retrieval: bool = True
    enable_graph_rag: bool = True


class GovernanceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDT_GOV_", extra="ignore")

    require_phase_approval: bool = True         # human-in-the-loop gate per phase
    require_executive_approval: bool = True     # gate before executive deliverables
    default_confidence_threshold: float = 0.72  # below -> reflect/retry or escalate
    max_agent_retries: int = 3
    per_run_token_budget: int = 5_000_000       # hard cap; Cost Agent enforces
    per_run_usd_budget: float = 250.0
    enable_pii_redaction: bool = True
    oidc_issuer: str = "https://keycloak.internal/realms/edt"
    oidc_audience: str = "edt-platform"


class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDT_OBS_", extra="ignore")

    otlp_endpoint: str = "http://localhost:4317"
    service_name: str = "edt-platform"
    environment: str = "dev"
    langfuse_host: str = "http://localhost:3000"
    log_level: str = "INFO"


class Settings(BaseSettings):
    """Root settings aggregating all subsystem settings."""

    model_config = SettingsConfigDict(extra="ignore")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    store: StoreSettings = Field(default_factory=StoreSettings)
    event: EventSettings = Field(default_factory=EventSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)
    governance: GovernanceSettings = Field(default_factory=GovernanceSettings)
    obs: ObservabilitySettings = Field(default_factory=ObservabilitySettings)


@lru_cache
def get_settings() -> Settings:
    """Return a cached, process-wide Settings instance."""
    return Settings()
