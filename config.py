from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


class LLMProvider(str, Enum):
    claude = "claude"
    grok = "grok"
    gemini = "gemini"


class Settings(BaseSettings):
    # LLM provider selection
    llm_provider: LLMProvider = LLMProvider.claude
    llm_model: Optional[str] = None  # override default model per provider

    # Anthropic
    anthropic_api_key: str = ""

    # xAI (Grok)
    xai_api_key: str = ""

    # Google (Gemini)
    google_api_key: str = ""

    # Twilio
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str

    # Agent personality
    agent_name: str = "Sophie"
    owner_name: str = "Boss"

    # Server
    base_url: str = "http://localhost:8000"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def _check_active_provider_key(self) -> "Settings":
        if self.llm_provider == LLMProvider.claude and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude")
        if self.llm_provider == LLMProvider.grok and not self.xai_api_key:
            raise ValueError("XAI_API_KEY is required when LLM_PROVIDER=grok")
        if self.llm_provider == LLMProvider.gemini and not self.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required when LLM_PROVIDER=gemini")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
