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
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Telegram notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Data persistence
    data_dir: str = "data"

    # Agent personality
    agent_name: str = "Sophie"
    owner_name: str = "Boss"

    # xAI Voice Agent
    xai_voice_model: str = "grok-voice-latest"  # voice-think-fast-2.0 as of Aug 2026
    # Any id from GET /v1/tts/voices (lowercase). Female: ara, aurora, carina,
    # celeste, eve, iris, liora, luna, ursa. Male: rex, atlas, orion, leo, ...
    xai_voice: str = "eve"
    xai_voice_cost_per_minute: float = 0.08  # update from x.ai/api/voice pricing page

    # Server
    base_url: str = "http://localhost:8000"

    # Scheduling
    scheduling_enabled: bool = True
    scheduling_include_evenings: bool = True
    # Scott's calendar is Exchange Online (Microsoft 365 via GoDaddy), so the
    # Microsoft Graph backend is the default; "google" remains available.
    calendar_backend: str = "msgraph"

    # Microsoft Graph (calendar) — defaults borrowed from the career-ops email
    # scanner's .env when unset, since it is the same mailbox and app.
    ms_client_id: str = ""
    ms_tenant_id: str = "common"
    ms_token_path: str = "data/ms-token.json"

    # Google Calendar (alternative backend)
    google_calendar_id: str = "primary"
    google_token_path: str = "data/google-token.json"
    google_client_secret_path: str = "data/google-client-secret.json"

    # Grounding + career-ops integration
    career_ops_root: str = "D:/Claude/Career-ops"
    knowledge_path: str = "data/knowledge.md"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def _borrow_ms_credentials(self) -> "Settings":
        """Fill MS_CLIENT_ID/MS_TENANT_ID from the career-ops .env when unset —
        the email scanner already registered an app for this same mailbox."""
        if self.ms_client_id:
            return self
        import os
        import re

        env_path = os.path.join(self.career_ops_root, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, encoding="utf-8") as fh:
                    text = fh.read()
                cid = re.search(r"^MICROSOFT_CLIENT_ID=(.+)$", text, re.M)
                ten = re.search(r"^MICROSOFT_TENANT_ID=(.+)$", text, re.M)
                if cid:
                    self.ms_client_id = cid.group(1).strip()
                if ten:
                    self.ms_tenant_id = ten.group(1).strip()
            except OSError:
                pass
        return self

    @model_validator(mode="after")
    def _check_required_keys(self) -> "Settings":
        if self.llm_provider == LLMProvider.claude and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude")
        if self.llm_provider == LLMProvider.grok and not self.xai_api_key:
            raise ValueError("XAI_API_KEY is required when LLM_PROVIDER=grok")
        if self.llm_provider == LLMProvider.gemini and not self.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required when LLM_PROVIDER=gemini")
        if not self.twilio_auth_token:
            raise ValueError(
                "TWILIO_AUTH_TOKEN is required for Twilio signature validation"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
