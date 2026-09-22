from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SIRALOOM"
    app_env: str = "development"
    api_version: str = "v1"
    log_level: str = "INFO"

    database_url: str
    redis_url: str

    artifact_root: str = "/data/siraloom/artifacts"

    genebe_enabled: bool = False
    genebe_email: str | None = None
    genebe_api_key: str | None = None
    genebe_base_url: str = (
        "https://api.genebe.net/cloud/api-public/v1"
    )
    genebe_timeout_seconds: float = 60.0
    genebe_max_batch: int = 1000
    genebe_retry_attempts: int = 3
    genebe_retry_backoff_seconds: float = 2.0
    genebe_retry_max_backoff_seconds: float = 30.0
    genebe_gnomad_resource_version: str = (
        "4.1-provider-aggregate"
    )

    gnomad_enabled: bool = False
    gnomad_graphql_endpoint: str = (
        "https://gnomad.broadinstitute.org/api"
    )
    gnomad_dataset_id: str = "gnomad_r4"
    gnomad_graphql_delay_seconds: float = 0.0

    # Optional local reference resources.
    #
    # Production/on-prem installations should normally provide these.
    reference_fasta: str | None = None
    reference_fai: str | None = None

    # Development/integration fallback.
    #
    # When enabled, SIRALOOM can use Ensembl REST for reference sequence
    # retrieval instead of requiring a local FASTA/FAI.
    reference_remote_enabled: bool = False
    reference_remote_grch38_endpoint: str = (
        "https://rest.ensembl.org"
    )
    reference_remote_grch37_endpoint: str = (
        "https://grch37.rest.ensembl.org"
    )
    reference_remote_timeout_seconds: float = 20.0
    reference_remote_window_flank: int = 1000
    reference_remote_retry_attempts: int = 3
    reference_remote_retry_backoff_seconds: float = 1.5

    public_base_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:3000"

    firebase_project_id: str | None = None
    firebase_credentials_path: str | None = None
    firebase_auth_required: bool = False
    firebase_issuer: str | None = None
    firebase_storage_enabled: bool = False
    firebase_storage_bucket: str | None = None

    celery_concurrency: int = 2
    celery_worker_max_tasks_per_child: int = 20
    celery_worker_prefetch_multiplier: int = 1

    partition_default_resource_class: str = "LIGHT"
    partition_scheduler_cpu_capacity: float = 2.0
    partition_scheduler_memory_mb: int = 4096
    partition_lease_seconds: int = 900
    partition_max_attempts: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
