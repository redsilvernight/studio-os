from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDIO_", env_file=".env")

    database_url: str = "postgresql+asyncpg://studio:studio@localhost:5432/studio"

    s3_endpoint_url: str = "http://localhost:9000"
    # Endpoint baked into presigned URLs — must be reachable from client machines,
    # not the in-cluster service name. See docs/DECISIONS.md DEC-0004.
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "studio-transfers"
    s3_access_key: str = "studio"
    s3_secret_key: str = "studio-dev-secret"
    s3_region: str = "us-east-1"
    presigned_url_ttl_seconds: int = 900

    heartbeat_interval_seconds: int = 30
    heartbeat_offline_after_seconds: int = 90


def get_settings() -> Settings:
    return Settings()
