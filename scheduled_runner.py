from __future__ import annotations

import base64
import lzma
import py_compile
import subprocess
import sys
from pathlib import Path


def run(*args: str) -> None:
    print("$", " ".join(args), flush=True)
    subprocess.run(args, check=True)


def restore_report_engine() -> None:
    parts = sorted(Path("report_engine_parts").glob("part_*.b64"))
    if len(parts) != 7:
        raise RuntimeError(f"Expected 7 report engine parts, found {len(parts)}")
    encoded = "".join(p.read_text(encoding="ascii").strip() for p in parts)
    target = Path("report_engine.py")
    target.write_bytes(lzma.decompress(base64.b64decode(encoded)))
    print(f"Restored {target} from {len(parts)} parts ({target.stat().st_size} bytes)")


def repair_template() -> None:
    patch = Path("template_patch")
    target = Path("template_parts")
    for n in (6, 7, 8):
        pieces = [patch / f"t{n:02d}_0.b64", patch / f"t{n:02d}_1.b64"]
        if not all(p.exists() for p in pieces):
            raise RuntimeError(f"Missing template patch for chunk {n:02d}")
        content = "".join(p.read_text(encoding="ascii").strip() for p in pieces)
        if len(content) != 10800:
            raise RuntimeError(f"Invalid template chunk {n:02d}: {len(content)} bytes")
        (target / f"bullaware_template_{n:02d}.b64").write_text(content, encoding="ascii")
        print(f"Repaired template chunk {n:02d}")


def validate() -> None:
    for file_name in (
        "monitor.py",
        "monitor_slot.py",
        "report_engine.py",
        "run_report_fixed.py",
        "run_report_ranges.py",
        "run_report_ranges_fixed.py",
        "run_report_safe.py",
        "excel_metrics.py",
    ):
        py_compile.compile(file_name, doraise=True)
    print("Python validation OK")


def main() -> int:
    # Always refresh the eToro snapshot first. monitor_slot.py handles the
    # 10-minute text-summary slots and buy/sell notifications.
    run(sys.executable, "monitor_slot.py")

    restore_report_engine()
    repair_template()
    validate()

    # run_report_safe.py sends the HTML when due. On the dedicated 10-minute
    # cron FORCE_HTML_REPORT=true, so delivery is forced even if the previous
    # run started a little late.
    run(sys.executable, "run_report_safe.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
