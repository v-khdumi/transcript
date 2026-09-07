"""Persists a finished transcription session to disk (JSON + plain text).

Use an application-controlled output directory. Exclusive creation protects
individual filenames, not untrusted ancestor directories. POSIX creation modes
are subject to the host filesystem; Windows requires appropriate directory ACLs.
This store does not provide encryption or transactional two-file writes.
"""

import json
import os
from contextlib import ExitStack
from datetime import datetime
from itertools import count
from typing import Any


def _private_opener(path: str, flags: int) -> int:
    """Apply restrictive permissions at creation without changing the umask."""
    return os.open(path, flags, 0o600)


class SessionStore:
    def __init__(self, output_dir: str = "transcripts"):
        self.output_dir = output_dir

    def save(self, entries: list[dict[str, Any]], speaker_mapping: dict[str, str]) -> tuple[str, str]:
        # Validate serialization before creating any session files. Formatting
        # matches the existing JSON and plain-text exports, including Unicode.
        json_content = json.dumps(
            {"speakers": speaker_mapping, "entries": entries},
            ensure_ascii=False,
            indent=2,
        )
        txt_content = "".join(
            f"[{entry['time']}] {entry['speaker']}: {entry['text']}\n"
            for entry in entries
        )

        # Existing directories are deliberately not chmod'ed. For nested custom
        # paths, the caller must also secure any pre-existing or parent folders.
        os.makedirs(self.output_dir, mode=0o700, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for attempt in count():
            suffix = "" if attempt == 0 else f"_{attempt}"
            basename = f"transcript_{timestamp}{suffix}"
            json_path = os.path.join(self.output_dir, f"{basename}.json")
            txt_path = os.path.join(self.output_dir, f"{basename}.txt")

            with ExitStack() as files:
                try:
                    json_file = files.enter_context(
                        open(json_path, "x", encoding="utf-8", opener=_private_opener)
                    )
                except FileExistsError:
                    # Exclusive creation also rejects dangling symlinks.
                    continue

                try:
                    txt_file = files.enter_context(
                        open(txt_path, "x", encoding="utf-8", opener=_private_opener)
                    )
                except FileExistsError:
                    # Release only our empty reservation, never the existing
                    # text file. Close first for compatibility with Windows.
                    files.close()
                    os.unlink(json_path)
                    continue

                json_file.write(json_content)
                txt_file.write(txt_content)

            return json_path, txt_path
