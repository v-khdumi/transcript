"""One-shot configuration preflight; not application or Azure health."""

import json
import time
from datetime import datetime, timezone


def main() -> int:
    started = time.perf_counter()
    outcome = "ready"
    reason = "configuration_accepted"
    exit_code = 0

    try:
        from transcript_app.config import load_settings

        load_settings()
    except RuntimeError:
        outcome = "not_ready"
        reason = "configuration_rejected"
        exit_code = 1
    except Exception:
        # Import and dependency failures are operational errors. Do not emit
        # exception text: upstream exceptions could contain sensitive values.
        outcome = "error"
        reason = "preflight_error"
        exit_code = 2

    print(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "transcript.configuration_preflight",
                "scope": "configuration_only",
                "outcome": outcome,
                "reason": reason,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
