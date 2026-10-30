from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    qloo_api_key: str = ""
    qloo_base_url: str = "https://hackathon.api.qloo.com"
    qloo_timeout_seconds: float = 15
    qloo_cache_ttl_seconds: int = 3600
    database_url: str = "sqlite:///./stockrescue.db"
    cors_origins: str = "http://localhost:3000"
    # JSON object mapping SHA-256 bearer-token hashes to retailer IDs. Raw tokens never live in env.
    retailer_api_token_hashes: str = "{}"
    qloo_requests_per_minute: int = 15
    rescue_runs_per_minute: int = 5

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        # Render/Heroku style URLs
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
