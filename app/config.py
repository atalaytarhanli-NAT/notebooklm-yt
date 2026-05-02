from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_token: str = "change-me-in-production"
    notebooklm_auth_json: str = ""
    notebooklm_home: str = "/tmp/notebooklm"
    artifacts_dir: str = "/tmp/notebooklm-artifacts"
    cors_origins: str = "*"
    render_api_key: str = ""
    render_service_id: str = ""
    firecrawl_api_key: str = ""


settings = Settings()
