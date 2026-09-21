"""Конфигурация из переменных окружения DOORAIN_*. Секреты только из окружения, не из Git."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_SECRET = "change-me"  # noqa: S105 — маркер незаданного секрета, production такое значение отклоняет


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOORAIN_", extra="ignore")

    env: Literal["dev", "test", "production"] = "dev"
    database_url: str = "postgresql+psycopg://doorain:doorain@postgres:5432/doorain"
    qdrant_url: str = "http://qdrant:6333"  # ":memory:" допустим только в тестах
    data_dir: Path = Path("/data")
    prompts_dir: Path = Path(__file__).resolve().parents[2] / "prompts"
    corpus_manifest: Path = next((x for x in (Path(__file__).resolve().parents[2] / "knowledge_base" / "manifest.yaml", Path(__file__).resolve().parents[3] / "knowledge_base" / "manifest.yaml") if x.is_file()), Path("knowledge_base/manifest.yaml"))

    # провайдеры: ollama = реальные локальные модели, test = детерминированные заглушки (маркируются в UI)
    provider_mode: Literal["ollama", "test"] = "ollama"
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    ollama_num_ctx: int = 4096
    ollama_num_predict: int = 640
    ollama_timeout_s: float = 300
    embed_model_path: str = "/models/bge-m3"
    reranker_model_path: str = "/models/mmarco-mMiniLMv2-L12-H384-v1"
    embed_max_len: int = 512
    embed_batch: int = 2

    # RAG (стартовые значения, подлежат калибровке — docs/evaluation.md)
    retrieval_top_k: int = 30
    rerank_keep: int = 12
    context_budget_tokens: int = 2000
    chars_per_token: float = 2.6
    min_rerank_score: float = 0.0
    threshold_source: str = "uncalibrated"
    partial_answer_margin: float = 1.5  # ниже порога, но выше (порог − margin) → ответ с оговоркой о неполноте оснований
    scope_override_min_score: float = 2.0  # насколько сильными должны быть найденные нормы, чтобы перевесить вердикт «вне области»
    # Риски: верхние границы уровней «низкий / средний / высокий» по P × S (выше — критический). Владелец может сдвинуть.
    risk_thresholds: tuple[int, int, int] = (4, 9, 15)
    max_new_risks_per_answer: int = 3  # защита от размывания внимания: лишние кандидаты с меньшим P × S пишутся в лог
    chunk_target_tokens: int = 700
    chunk_overlap_tokens: int = 60
    chunking_version: str = "npa-v1"

    # безопасность
    secret_key: SecretStr = SecretStr(PLACEHOLDER_SECRET)
    cookie_secure: bool = False
    session_ttl_hours: int = 24 * 7
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    trusted_proxy_cidrs: list[str] = []
    trusted_proxy_hosts: list[str] = []  # имена сервисов (например ["web"]): IP разрешаются через DNS Docker, без привязки к подсети
    single_user_mode: bool = False  # вход пропускается, всё работает под локальным пользователем; в production запрещено
    invite_ttl_days: int = 14
    owner_can_read_user_sessions: bool = True  # решение владельца стенда; каждый такой доступ пишется в журнал и виден пользователю
    login_ip_max_failures: int = 8
    login_account_max_failures: int = 20
    login_window_minutes: int = 15
    api_rate_per_minute: int = 300
    max_active_jobs: int = 3

    # загрузка файлов
    max_upload_mb: int = 25
    max_pdf_pages: int = 600
    max_extracted_chars: int = 6_000_000
    max_docx_unpacked_mb: int = 100

    # worker
    job_lease_s: int = 90
    job_max_attempts: int = 3
    worker_poll_s: float = 1.0

    @property
    def cookie_name(self) -> str:
        return "__Host-doorain_session" if self.cookie_secure else "doorain_session"

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        low, mid, high = self.risk_thresholds
        if not 1 <= low < mid < high < 25:
            raise ValueError("DOORAIN_RISK_THRESHOLDS: три возрастающие границы в диапазоне 1–24, например [4, 9, 15]")
        if self.env == "production":
            if self.secret_key.get_secret_value() in ("", PLACEHOLDER_SECRET) or len(self.secret_key.get_secret_value()) < 32:
                raise ValueError("DOORAIN_SECRET_KEY: задайте случайную строку не короче 32 символов")
            if not self.cookie_secure:
                raise ValueError("В production DOORAIN_COOKIE_SECURE должен быть true")
            if self.provider_mode != "ollama":
                raise ValueError("В production разрешён только provider_mode=ollama")
            if any(h in ("example.com", "your-domain.example") for h in self.allowed_hosts) or not self.allowed_hosts:
                raise ValueError("DOORAIN_ALLOWED_HOSTS содержит placeholder или пуст")
            if self.single_user_mode:
                raise ValueError("DOORAIN_SINGLE_USER_MODE недопустим в production: сервис доступен снаружи и обязан требовать вход")
        return self

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
