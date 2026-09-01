"""Persists a finished transcription session to disk (JSON + plain text)."""

import json
import os
from datetime import datetime
from typing import Any


class SessionStore:
    def __init__(self, output_dir: str = "transcripts"):
        self.output_dir = output_dir

    def save(self, entries: list[dict[str, Any]], speaker_mapping: dict[str, str]) -> tuple[str, str]:
        os.makedirs(self.output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = os.path.join(self.output_dir, f"transcript_{timestamp}.json")
        txt_path = os.path.join(self.output_dir, f"transcript_{timestamp}.txt")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {"speakers": speaker_mapping, "entries": entries},
                f,
                ensure_ascii=False,
                indent=2,
            )

        with open(txt_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(f"[{entry['time']}] {entry['speaker']}: {entry['text']}\n")

        return json_path, txt_path
