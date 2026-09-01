"""Loads app configuration from environment variables / .env file."""

import os
from dataclasses import dataclass

import dotenv

dotenv.load_dotenv()


@dataclass
class Settings:
    speech_key: str
    speech_region: str | None
    speech_endpoint: str | None
    language: str


def load_settings() -> Settings:
    key = os.getenv("AZURE_SPEECH_KEY")
    region = os.getenv("AZURE_SPEECH_REGION")
    endpoint = os.getenv("AZURE_SPEECH_ENDPOINT")
    language = os.getenv("AZURE_SPEECH_LANGUAGE", "ro-RO")

    if not key:
        raise RuntimeError(
            "AZURE_SPEECH_KEY lipsește. Configurează cheia resursei Azure AI Foundry "
            "Speech în fișierul .env (vezi .env.example)."
        )
    if not region and not endpoint:
        raise RuntimeError(
            "Trebuie setat AZURE_SPEECH_REGION sau AZURE_SPEECH_ENDPOINT în .env."
        )

    return Settings(
        speech_key=key,
        speech_region=region,
        speech_endpoint=endpoint,
        language=language,
    )
