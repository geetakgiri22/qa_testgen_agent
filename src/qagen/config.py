"""Central configuration: environment variables + drive_config.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class OllamaSettings:
    base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://localhost:11434"))
    model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "qwen2.5:3b"))
    timeout: int = field(default_factory=lambda: int(_env("OLLAMA_TIMEOUT_SEC", "300")))
    num_ctx: int = field(default_factory=lambda: int(_env("OLLAMA_NUM_CTX", "4096")))
    num_predict: int = field(default_factory=lambda: int(_env("OLLAMA_NUM_PREDICT", "1500")))
    temperature: float = field(default_factory=lambda: float(_env("OLLAMA_TEMPERATURE", "0.2")))

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/chat"

    @property
    def tags_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/tags"


@dataclass(frozen=True)
class GenerationSettings:
    max_req_chars: int = field(default_factory=lambda: int(_env("MAX_REQ_CHARS_PER_CALL", "1800")))
    max_tests_per_req: int = field(default_factory=lambda: int(_env("MAX_TESTS_PER_REQUIREMENT", "12")))


@dataclass(frozen=True)
class LangSmithSettings:
    enabled: bool = field(default_factory=lambda: _env_bool("LANGSMITH_TRACING", False))
    api_key: str = field(default_factory=lambda: _env("LANGSMITH_API_KEY", ""))
    endpoint: str = field(default_factory=lambda: _env("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"))
    agent_id: str = field(default_factory=lambda: _env("LANGSMITH_AGENT_ID", "qatestcasegeneratoragent"))
    agent_environment: str = field(default_factory=lambda: _env("LANGSMITH_AGENT_ENVIRONMENT", "local"))


@dataclass(frozen=True)
class Settings:
    ollama: OllamaSettings = field(default_factory=OllamaSettings)
    generation: GenerationSettings = field(default_factory=GenerationSettings)
    langsmith: LangSmithSettings = field(default_factory=LangSmithSettings)
    drive_config_path: Path = field(
        default_factory=lambda: ROOT / _env("DRIVE_CONFIG_PATH", "drive_config.yaml")
    )
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    log_file: Path = field(default_factory=lambda: ROOT / _env("LOG_FILE", "logs/app.log"))


def load_settings() -> Settings:
    return Settings()


def load_drive_config(path: Path | None = None) -> dict:
    """Load drive_config.yaml. Raises FileNotFoundError / ValueError with clear messages."""
    path = Path(path) if path else load_settings().drive_config_path
    if not path.exists():
        raise FileNotFoundError(f"Drive config not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    if "google_drive" not in cfg:
        raise ValueError("drive_config.yaml must contain a 'google_drive' section")
    return cfg
