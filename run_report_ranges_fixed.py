from __future__ import annotations

import json

import excel_metrics
import run_report_fixed as base
import run_report_ranges as ranges

# Keep the original dedupe function before replacing base._fix_html.
# This prevents the recursive monkey-patch that previously caused the workflow
# to fail with RecursionError.
_ORIGINAL_DEDUPE_FIX = base._fix_html


def _range_aware_fix_html(raw_html: bytes) -> tuple[bytes, int]:
    """Deduplicate positions, calculate Excel-identical metrics, inject range UI."""
    deduped, removed = _ORIGINAL_DEDUPE_FIX(raw_html)
    text = deduped.decode("utf-8")

    start, end, data = base._extract_const_d(text)
    if not isinstance(data, dict):
        raise RuntimeError("Detailed HTML const D payload is not an object")

    metrics_by_period, metrics_meta = excel_metrics.period_metrics(data)
    data["performanceMetricsByPeriod"] = metrics_by_period
    data["performanceMetricsMeta"] = metrics_meta
    data["riskFreeAnnual"] = float(metrics_meta.get("riskFreeAnnual", 0.0))

    compact = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    text = text[:start] + compact + text[end:]

    # Avoid duplicate injections if the HTML is processed more than once.
    if 'id="performance-range-style-v2"' not in text:
        text = text.replace(
            "</head>",
            ranges.PERFORMANCE_CSS
            + '\n<meta name="performance-ranges" content="excel-formulas-ytd-1y-2y-3y-5y-alltime-rf0">\n</head>',
            1,
        )
    if 'id="performance-range-fix-v2"' not in text:
        text = text.replace(
            "</body>",
            ranges.PERFORMANCE_JS + "\n</body>",
            1,
        )

    return text.encode("utf-8"), removed


def main() -> int:
    base._fix_html = _range_aware_fix_html
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
