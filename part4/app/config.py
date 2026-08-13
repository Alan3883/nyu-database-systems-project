"""Part IV configuration.

Every setting is resolved from the environment. No credential is stored in
this file or anywhere else in version control. For local development the
values are placed in part4/.env, which .gitignore excludes; part4/.env.example
documents the required names.

Three roots matter, and they are deliberately separate:

    WORKSPACE   the course directory that holds every project part.
                Placed on sys.path so `import part4...` resolves.

    PART4       this part's own tree: application, jobs, tests, model
                registry, evidence, scripts.

    LAKE        the Part II data lake and the Part III ml package. Part IV
                reads the lake and reuses the ml modules; it does not own
                them, and it never writes into their source directories.
                Every DATA_ASSET.RelativePath is relative to this root.

Keeping them apart is what lets Part IV sit beside Parts II and III rather
than inside them, while still resolving DS010 through the same catalogue
the Part III pipeline uses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# part4/app/config.py -> part4/app -> part4 -> the course workspace
PART4 = Path(__file__).resolve().parents[1]
WORKSPACE = PART4.parent


def _load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines into os.environ without overwriting real vars.

    A deliberately small reader: the project should not gain a dependency
    for four lines of parsing, and an unexpected .env format should fail
    visibly here rather than silently inside a library.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(PART4 / ".env")


def lake_root() -> Path:
    """Resolve the Part II data lake, which is also the Part III package root."""
    override = os.environ.get("PART4_LAKE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return WORKSPACE / "part2_data_lake"


def database_url() -> str:
    """Return the SQLAlchemy URL for the Part III PostgreSQL database."""
    explicit = os.environ.get("PART4_DB_URL")
    if explicit:
        return explicit
    user = os.environ.get("PGUSER", "postgres")
    password = os.environ.get("PGPASSWORD", "")
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    name = os.environ.get("PGDATABASE", "part3")
    credential = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql+psycopg://{credential}{host}:{port}/{name}"


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the application and the pipeline jobs."""

    # --- database ----------------------------------------------------
    db_url: str = field(default_factory=database_url)
    # Pool sized for a single-process demonstration server. The point of
    # pooling here is to avoid a TCP handshake and authentication round
    # trip on every request, not to serve high concurrency.
    pool_size: int = int(os.environ.get("PART4_POOL_SIZE", "5"))
    max_overflow: int = int(os.environ.get("PART4_MAX_OVERFLOW", "5"))
    pool_pre_ping: bool = True
    echo_sql: bool = os.environ.get("PART4_ECHO_SQL", "0") == "1"

    # --- roots -------------------------------------------------------
    workspace: Path = WORKSPACE
    part4: Path = PART4
    lake: Path = field(default_factory=lake_root)

    # --- data lake and model registry --------------------------------
    # The DS010 source watched by the monitor, relative to the lake root.
    # Overridable so the retraining tests can point at a fixture instead
    # of the raw asset.
    watch_source: str = os.environ.get(
        "PART4_WATCH_SOURCE", "raw/unstructured_documents/chr_2025_national_report.pdf")
    version_dir: str = "raw/unstructured_documents/versions"
    ml_config: str = "ml/config.yaml"
    # Part IV owns its model registry and its logs; Part III's ml/models
    # directory is never written to by this code.
    model_registry: str = "model_registry"
    log_dir: str = "logs"
    poll_interval_seconds: int = int(os.environ.get("PART4_POLL_SECONDS", "60"))

    # --- application -------------------------------------------------
    host: str = os.environ.get("PART4_HOST", "127.0.0.1")
    port: int = int(os.environ.get("PART4_PORT", "5055"))
    page_size: int = int(os.environ.get("PART4_PAGE_SIZE", "25"))
    # Demonstration rating factor. Named so no reader mistakes it for a
    # filed insurance rate.
    demo_rate_per_1000_limit: float = 4.25
    demo_deductible_credit: float = 0.05

    # --- lake-relative paths -----------------------------------------
    @property
    def watch_path(self) -> Path:
        return self.lake / self.watch_source

    @property
    def version_path(self) -> Path:
        return self.lake / self.version_dir

    @property
    def ml_config_path(self) -> Path:
        return self.lake / self.ml_config

    # --- part4-relative paths ----------------------------------------
    @property
    def registry_path(self) -> Path:
        return self.part4 / self.model_registry

    @property
    def log_path(self) -> Path:
        return self.part4 / self.log_dir

    def lake_file(self, relative_path: str) -> Path:
        """Resolve a DATA_ASSET.RelativePath against the lake root."""
        return self.lake / relative_path


CONFIG = Config()
