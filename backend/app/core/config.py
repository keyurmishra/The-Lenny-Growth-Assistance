from enum import Enum
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --------------------------------------------------
    # LLM Provider
    # --------------------------------------------------

    llm_provider: LLMProvider = LLMProvider.OLLAMA

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # --------------------------------------------------
    # Database
    # --------------------------------------------------

    postgres_user: str = "lenny"
    postgres_password: str = "lenny_local_dev"
    postgres_db: str = "lenny_assistant"
    postgres_host: str = "postgres"
    postgres_port: int = 5432


    @property
    def database_url(self) -> str:

        password = quote_plus(self.postgres_password.strip())

        return (
            f"postgresql+asyncpg://"
            f"{self.postgres_user.strip()}:{password}"
            f"@{self.postgres_host.strip()}:"
            f"{self.postgres_port}/"
            f"{self.postgres_db.strip()}"
        )


    @property
    def database_url_sync(self) -> str:

        password = quote_plus(self.postgres_password.strip())

        return (
            f"postgresql://"
            f"{self.postgres_user.strip()}:{password}"
            f"@{self.postgres_host.strip()}:"
            f"{self.postgres_port}/"
            f"{self.postgres_db.strip()}"
        )


    # --------------------------------------------------
    # Embeddings
    # --------------------------------------------------

    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384


    # --------------------------------------------------
    # Retrieval
    # --------------------------------------------------

    retrieval_top_k: int = 5
    chunk_size: int = 512
    chunk_overlap: int = 50


    # --------------------------------------------------
    # Application
    # --------------------------------------------------

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_env: str = "development"
    log_level: str = "INFO"

    cors_origins: str = (
        "http://localhost:5173,"
        "http://localhost:3000"
    )


    @property
    def cors_origin_list(self) -> list[str]:

        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
        ]


    def get_active_model_name(self) -> str:

        if self.llm_provider == LLMProvider.OLLAMA:
            return self.ollama_model

        elif self.llm_provider == LLMProvider.ANTHROPIC:
            return self.anthropic_model

        elif self.llm_provider == LLMProvider.OPENAI:
            return self.openai_model

        return "unknown"


settings = Settings()