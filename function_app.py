from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import azure.functions as func

from azure_state import pull_state, push_state

app = func.FunctionApp()
log = logging.getLogger("thomaspj-azure-function")


def _copy_runtime(source: Path, target: Path) -> None:
    ignore = shutil.ignore_patterns(
        ".git",
        ".github",
        ".venv",
        ".python_packages",
        "__pycache__",
        "local.settings.json",
        "native-schedule-last.txt",
    )
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=ignore)


@app.timer_trigger(
    schedule="%TIMER_SCHEDULE%",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def thomaspj_report_timer(timer: func.TimerRequest) -> None:
    """Run the existing eToro monitor/report pipeline every configured interval.

    Azure Functions can run the deployed package read-only, while the existing
    report pipeline reconstructs files at runtime. For that reason each invocation
    works from a writable temporary copy and stores persistent JSON state in Azure
    Blob Storage.
    """
    if timer.past_due:
        log.warning("Azure timer invocation is past due; running it now")

    source = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="thomaspj-") as tmp:
        workdir = Path(tmp)
        _copy_runtime(source, workdir)
        pull_state(workdir)

        env = os.environ.copy()
        env.setdefault("ETORO_USERNAME", "thomaspj")
        env.setdefault("PORTFOLIO_EUR", "5000")
        env.setdefault("MIN_ALERT_EUR", "5")
        env.setdefault("PORTFOLIO_SUMMARY_MINUTES", "10")
        env.setdefault("HTML_REPORT_MINUTES", "10")
        env["FORCE_HTML_REPORT"] = "true"
        env["FORCE_PORTFOLIO_SUMMARY"] = "true"
        env.setdefault("REPORT_URL", "")
        env.setdefault("REPORT_DIR", "docs")
        env.setdefault("SEND_INITIAL_PORTFOLIO", "true")
        env.setdefault("RISK_FREE_ANNUAL", "0")
        env.setdefault("TREEMAP_HISTORY_HOURS", "12")
        env.setdefault("TREEMAP_HISTORY_LIMIT", "20")

        log.info("Starting scheduled_runner.py from Azure Functions")
        try:
            result = subprocess.run(
                [sys.executable, "scheduled_runner.py"],
                cwd=workdir,
                env=env,
                text=True,
                capture_output=True,
                timeout=8 * 60,
            )
            if result.stdout:
                log.info("runner stdout:\n%s", result.stdout[-20000:])
            if result.stderr:
                log.warning("runner stderr:\n%s", result.stderr[-20000:])
            if result.returncode != 0:
                raise RuntimeError(f"scheduled_runner.py exited with code {result.returncode}")
        finally:
            # Save whatever state was successfully produced, even if report delivery
            # failed after the eToro snapshot had already been updated.
            push_state(workdir)

        log.info("Azure scheduled run completed successfully")
