"""Application configuration.

Every value comes from environment variables (prefix ``NVB_``) so the same
artifact runs unchanged on the VMware VM, the migrated OpenShift VM and in
OpenShift containers. No production secrets have defaults.
"""

from __future__ import annotations

import os
import socket
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

from app import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NVB_", env_file=None, extra="ignore")

    # --- Identity / environment -------------------------------------------------
    environment_label: str = Field(
        default="Not configured",
        description="Shown on the operations page, e.g. 'VMware VM', 'OpenShift VM', 'OpenShift Containers'.",
    )
    app_version: str = __version__
    instance_id: str | None = None  # defaults to hostname:pid

    # --- Database -----------------------------------------------------------------
    # Either a full SQLAlchemy URL, or discrete components (preferred on OpenShift
    # where the password comes from a Secret).
    database_url: str | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "nvb"
    db_user: str = "nvb_app"
    db_password: str | None = None
    db_sslmode: str = "prefer"
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    db_connect_timeout_seconds: int = Field(default=3, ge=1, le=30)
    db_statement_timeout_ms: int = Field(default=10000, ge=100, le=120000)

    # Optional elevated credentials used ONLY by the CLI (migrate / seed / reset).
    migration_database_url: str | None = None
    db_migration_user: str | None = None
    db_migration_password: str | None = None

    # --- HTTP / security -----------------------------------------------------------
    cookie_secure: bool = True  # set false only for plain-http local development
    session_idle_timeout_minutes: int = Field(default=15, ge=1, le=240)
    session_absolute_timeout_minutes: int = Field(default=480, ge=5, le=1440)
    cors_origins: str = ""  # comma separated; empty = same-origin only (no CORS headers)
    login_max_failures_per_user: int = Field(default=5, ge=1, le=100)
    login_max_failures_per_ip: int = Field(default=50, ge=1, le=10000)
    login_window_minutes: int = Field(default=15, ge=1, le=1440)
    argon2_time_cost: int = Field(default=3, ge=1, le=10)
    argon2_memory_cost_kib: int = Field(default=65536, ge=1024, le=1048576)
    argon2_parallelism: int = Field(default=1, ge=1, le=8)
    max_transfer_minor: int = Field(default=50_000_000, ge=100)  # 500,000.00 EGP

    # --- Sign-up, password reset, cash operations ----------------------------------
    self_registration_enabled: bool = True
    registration_max_per_ip_per_hour: int = Field(default=10, ge=1, le=10000)
    password_reset_ttl_minutes: int = Field(default=15, ge=1, le=1440)
    account_setup_ttl_hours: int = Field(default=24, ge=1, le=720)
    max_deposit_minor: int = Field(default=10_000_000, ge=100)      # 100,000.00 EGP
    max_withdrawal_minor: int = Field(default=5_000_000, ge=100)    # 50,000.00 EGP

    # --- Observability -------------------------------------------------------------
    log_level: str = "INFO"
    metrics_token: str | None = None  # if set, /metrics requires "Authorization: Bearer <token>"
    metrics_allow_unauthenticated: bool = False  # only for local dev; VM uses nginx to block /metrics

    # Optional, read-only Prometheus/Thanos integration for the operations page.
    prometheus_url: str | None = None
    prometheus_token_file: str | None = None
    prometheus_ca_file: str | None = None
    prometheus_namespace: str | None = None
    prometheus_deployment: str = "nvb-app"
    prometheus_timeout_seconds: float = Field(default=3.0, gt=0, le=15)

    # --- Synthetic CPU workload (demo only, disabled by default) ------------------
    demo_workload_enabled: bool = False
    demo_workload_max_concurrency: int = Field(default=2, ge=1, le=16)
    demo_workload_queue_timeout_seconds: float = Field(default=10.0, ge=0, le=30)
    demo_workload_max_seconds: float = Field(default=5.0, gt=0, le=30)
    # ~3000 simulations is roughly 150-250 ms of one CPU core on a typical x86 server
    # core; calibrate per environment (see docs/SCALING_DEMO.md).
    demo_workload_simulations: int = Field(default=3000, ge=10, le=20000)

    # --- Extension integration API (additive, DISABLED by default) -------------------
    # When disabled the /internal/v1 router is not registered at all, so existing
    # behaviour is unchanged. Clients authenticate with scoped bearer credentials whose
    # SHA-256 digests (never the raw tokens) are listed in a JSON file mounted from a
    # Secret. Several digests per client allow overlap during rotation.
    integration_enabled: bool = False
    integration_clients_file: str | None = None
    integration_max_concurrent_exports: int = Field(default=2, ge=1, le=16)
    integration_export_queue_timeout_seconds: float = Field(default=2.0, ge=0, le=30)
    integration_max_page_size: int = Field(default=1000, ge=10, le=5000)
    integration_max_period_days: int = Field(default=400, ge=1, le=3660)
    # A statement period may end no later than now - settle seconds. Postings take
    # posted_at before acquiring the account row lock, so a row with posted_at just
    # before "now" can still commit slightly later. See docs in integration_exports.
    integration_settle_seconds: int = Field(default=300, ge=0, le=86400)
    integration_discovery_max_page_size: int = Field(default=500, ge=1, le=5000)

    # --- Static frontend -----------------------------------------------------------
    static_dir: str | None = None

    # --- Demo data guard ------------------------------------------------------------
    allow_demo_reset: bool = False

    @field_validator("db_sslmode")
    @classmethod
    def _sslmode(cls, v: str) -> str:
        allowed = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
        if v not in allowed:
            raise ValueError(f"db_sslmode must be one of {sorted(allowed)}")
        return v

    @property
    def resolved_instance_id(self) -> str:
        return self.instance_id or f"{socket.gethostname()}:{os.getpid()}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def sqlalchemy_url(self) -> URL:
        if self.database_url:
            return make_url(self.database_url)
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"sslmode": self.db_sslmode},
        )

    def migration_sqlalchemy_url(self) -> URL:
        if self.migration_database_url:
            return make_url(self.migration_database_url)
        if self.db_migration_user:
            return self.sqlalchemy_url().set(
                username=self.db_migration_user, password=self.db_migration_password
            )
        return self.sqlalchemy_url()


@lru_cache
def get_settings() -> Settings:
    return Settings()
