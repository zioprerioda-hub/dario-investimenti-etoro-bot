from __future__ import annotations

import os
from datetime import datetime, timezone

import monitor


def _slot_due(last_sent: str | None) -> bool:
    """Send one portfolio summary per configured wall-clock slot.

    GitHub's cron is best-effort and may start a little early/late. The previous
    elapsed-seconds check could therefore miss the 10-minute boundary and wait
    until the next 5-minute run. Comparing time slots avoids that 15-minute gap.
    Manual workflow runs can explicitly force a summary for testing.
    """
    if os.getenv("FORCE_PORTFOLIO_SUMMARY", "").lower() in {"1", "true", "yes", "on"}:
        return True
    if not last_sent:
        return True

    try:
        previous = datetime.fromisoformat(last_sent.replace("Z", "+00:00"))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
    except Exception:
        return True

    now = datetime.now(timezone.utc)
    slot_seconds = max(60, monitor.PORTFOLIO_SUMMARY_MINUTES * 60)
    previous_slot = int(previous.timestamp() // slot_seconds)
    current_slot = int(now.timestamp() // slot_seconds)
    return current_slot > previous_slot


monitor.portfolio_summary_due = _slot_due

if __name__ == "__main__":
    raise SystemExit(monitor.main())
