from __future__ import annotations

import run_report_ranges_fixed as report


if __name__ == "__main__":
    try:
        raise SystemExit(report.main())
    except RuntimeError as exc:
        # A scheduled 5-minute monitor run is valid even when the 10-minute HTML
        # report is not due yet. In that case report_engine exits normally without
        # calling Telegram sendDocument; the wrapper used to turn that into a hard
        # workflow failure, preventing state.json from being persisted.
        if "did not attempt to send an HTML document" in str(exc):
            print("HTML report not due on this run; continuing so monitor state is persisted.")
            raise SystemExit(0)
        raise
