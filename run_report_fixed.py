from __future__ import annotations

import copy
import json
import os
import runpy
from pathlib import Path
from typing import Any

import requests

TELEGRAM_HOST = "api.telegram.org"


class _DummyTelegramResponse:
    status_code = 200
    text = '{"ok":true,"result":{"message_id":0}}'

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"ok": True, "result": {"message_id": 0}}


def _instrument_key(row: dict[str, Any]) -> str | None:
    for key in ("instrumentId", "instrumentID", "instrument_id"):
        value = row.get(key)
        if value not in (None, ""):
            return f"iid:{value}"
    for key in ("symbol", "ticker", "symbolFull"):
        value = row.get(key)
        if value not in (None, ""):
            return f"sym:{str(value).strip().upper()}"
    return None


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _merge_position_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse several eToro positionIds for the same instrument into one asset row."""
    if len(rows) == 1:
        result = copy.deepcopy(rows[0])
        result.setdefault("positionCount", int(result.get("positionCount") or 1))
        return result

    result = copy.deepcopy(rows[0])

    weights: list[float] = []
    for row in rows:
        weight = _num(row.get("investmentPct"))
        if weight is None:
            weight = _num(row.get("weightPct"))
        weights.append(abs(weight) if weight is not None else 1.0)
    total_weight = sum(weights) or float(len(rows))

    # Fields representing exposure/value are additive when multiple positionIds
    # belong to the same listed instrument.
    for field in (
        "investmentPct",
        "weightPct",
        "targetEur",
        "portfolioValue",
        "investedAmount",
        "investmentAmount",
        "exposure",
        "units",
        "quantity",
    ):
        values = [_num(row.get(field)) for row in rows]
        if any(value is not None for value in values):
            result[field] = sum(value or 0.0 for value in values)

    # Percentage/rate fields must be combined as exposure-weighted averages,
    # otherwise splitting one stock into many eToro positionIds distorts the tile.
    for field in (
        "openRate",
        "netProfit",
        "deviationPct",
        "unrealizedReturnPct",
        "returnPct",
        "profitPct",
        "priceChangePct",
        "weightedChange",
    ):
        pairs = [
            (value, weight)
            for row, weight in zip(rows, weights)
            if (value := _num(row.get(field))) is not None
        ]
        if pairs:
            denom = sum(weight for _, weight in pairs) or float(len(pairs))
            result[field] = sum(value * weight for value, weight in pairs) / denom

    timestamps = [
        str(row.get("openTimestamp"))
        for row in rows
        if row.get("openTimestamp") not in (None, "")
    ]
    if timestamps:
        result["openTimestamp"] = min(timestamps)

    # Current market data is instrument-level, so the latest non-empty value is fine.
    for field in (
        "marketPrice",
        "currentPrice",
        "lastPrice",
        "price",
        "volume",
        "peRatio",
        "sector",
        "industry",
        "logo",
        "logoUrl",
    ):
        for row in reversed(rows):
            if row.get(field) not in (None, ""):
                result[field] = row[field]
                break

    directions = [row.get("isBuy") for row in rows if row.get("isBuy") is not None]
    if directions and all(direction is directions[0] for direction in directions):
        result["isBuy"] = directions[0]
    elif directions:
        signed = sum(weight if direction is True else -weight for direction, weight in zip(directions, weights[: len(directions)]))
        result["isBuy"] = signed >= 0

    result["positionCount"] = sum(int(row.get("positionCount") or 1) for row in rows)
    return result


def _aggregate_list(items: list[Any]) -> tuple[list[Any], int]:
    rows = [item for item in items if isinstance(item, dict)]
    if len(rows) != len(items) or len(rows) < 2:
        return items, 0

    keys = [_instrument_key(row) for row in rows]
    if not all(keys):
        return items, 0
    if len(set(keys)) == len(keys):
        return items, 0

    order: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for key, row in zip(keys, rows):
        assert key is not None
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(row)

    merged = [_merge_position_rows(grouped[key]) for key in order]
    removed = len(items) - len(merged)
    return merged, removed


def _aggregate_dict(value: dict[str, Any]) -> tuple[dict[str, Any], int]:
    if len(value) < 2 or not all(isinstance(row, dict) for row in value.values()):
        return value, 0

    rows = list(value.values())
    keys = [_instrument_key(row) for row in rows]
    if not all(keys) or len(set(keys)) == len(keys):
        return value, 0

    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    order: list[str] = []
    for original_key, instrument_key, row in zip(value.keys(), keys, rows):
        assert instrument_key is not None
        if instrument_key not in grouped:
            order.append(instrument_key)
            grouped[instrument_key] = []
        grouped[instrument_key].append((original_key, row))

    result: dict[str, Any] = {}
    for instrument_key in order:
        group = grouped[instrument_key]
        # Keep one real positionId key for compatibility with code that expects a mapping.
        output_key = group[0][0]
        result[output_key] = _merge_position_rows([row for _, row in group])

    return result, len(value) - len(result)


def _should_aggregate(path: tuple[str, ...]) -> bool:
    context = ".".join(path).lower()
    if any(word in context for word in ("trade", "closed", "history", "activity", "feed", "event", "series", "chart")):
        return False
    return any(word in context for word in ("position", "portfolio", "treemap", "holding", "allocation", "diversification", "asset"))


def _dedupe_embedded_data(value: Any, path: tuple[str, ...] = ()) -> tuple[Any, int]:
    removed = 0

    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            child_path = path + (str(key),)
            child_value, child_removed = _dedupe_embedded_data(child, child_path)
            removed += child_removed

            if _should_aggregate(child_path):
                if isinstance(child_value, list):
                    child_value, extra = _aggregate_list(child_value)
                    removed += extra
                elif isinstance(child_value, dict):
                    child_value, extra = _aggregate_dict(child_value)
                    removed += extra

            cleaned[key] = child_value
        return cleaned, removed

    if isinstance(value, list):
        cleaned_list: list[Any] = []
        for index, child in enumerate(value):
            child_value, child_removed = _dedupe_embedded_data(child, path + (str(index),))
            cleaned_list.append(child_value)
            removed += child_removed
        return cleaned_list, removed

    return value, removed


def _extract_const_d(html_text: str) -> tuple[int, int, Any]:
    marker = "const D = "
    marker_pos = html_text.find(marker)
    if marker_pos < 0:
        raise RuntimeError("Detailed HTML does not contain 'const D = ' data block")

    start = marker_pos + len(marker)
    while start < len(html_text) and html_text[start].isspace():
        start += 1
    if start >= len(html_text) or html_text[start] not in "[{":
        raise RuntimeError("Unexpected const D data format")

    opening = html_text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(html_text)):
        char = html_text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                end = index + 1
                return start, end, json.loads(html_text[start:end])

    raise RuntimeError("Unable to find end of const D JSON block")


def _fix_html(raw_html: bytes) -> tuple[bytes, int]:
    text = raw_html.decode("utf-8")
    start, end, data = _extract_const_d(text)
    fixed_data, removed = _dedupe_embedded_data(data)

    compact = json.dumps(fixed_data, ensure_ascii=False, separators=(",", ":"))
    # Avoid ever closing the script tag from embedded text.
    compact = compact.replace("</", "<\\/")
    fixed = text[:start] + compact + text[end:]

    # Small marker makes it easy to verify which Telegram file contains the fix.
    fixed = fixed.replace(
        "</head>",
        '<meta name="portfolio-dedupe" content="instrument-level-v1">\n</head>',
        1,
    )
    return fixed.encode("utf-8"), removed


def _document_payload(files: Any) -> tuple[str, bytes] | None:
    if not isinstance(files, dict) or "document" not in files:
        return None

    item = files["document"]
    filename = "portfolio_report.html"
    obj: Any = item

    if isinstance(item, tuple):
        if item and item[0]:
            filename = str(item[0])
        if len(item) >= 2:
            obj = item[1]

    if not filename.lower().endswith((".html", ".htm")):
        name = getattr(obj, "name", "")
        if name and str(name).lower().endswith((".html", ".htm")):
            filename = Path(str(name)).name
        else:
            return None

    if hasattr(obj, "read"):
        try:
            current = obj.tell()
        except Exception:
            current = None
        try:
            obj.seek(0)
        except Exception:
            pass
        payload = obj.read()
        if current is not None:
            try:
                obj.seek(current)
            except Exception:
                pass
    elif isinstance(obj, (bytes, bytearray)):
        payload = bytes(obj)
    elif isinstance(obj, str) and Path(obj).exists():
        payload = Path(obj).read_bytes()
        filename = Path(obj).name
    else:
        return None

    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return filename, bytes(payload)


def main() -> int:
    real_post = requests.post
    real_session_post = requests.sessions.Session.post
    captured: list[dict[str, Any]] = []

    def intercept(url: str, *args: Any, **kwargs: Any) -> Any:
        if TELEGRAM_HOST in str(url) and "/sendDocument" in str(url):
            document = _document_payload(kwargs.get("files"))
            if document is not None:
                filename, payload = document
                captured.append(
                    {
                        "filename": filename,
                        "payload": payload,
                        "data": copy.deepcopy(kwargs.get("data") or {}),
                        "json": copy.deepcopy(kwargs.get("json") or {}),
                    }
                )
                print(f"Captured original Telegram HTML before sending: {filename} ({len(payload)} bytes)")
                return _DummyTelegramResponse()
        return real_post(url, *args, **kwargs)

    def intercept_session(session: requests.Session, url: str, *args: Any, **kwargs: Any) -> Any:
        if TELEGRAM_HOST in str(url) and "/sendDocument" in str(url):
            document = _document_payload(kwargs.get("files"))
            if document is not None:
                filename, payload = document
                captured.append(
                    {
                        "filename": filename,
                        "payload": payload,
                        "data": copy.deepcopy(kwargs.get("data") or {}),
                        "json": copy.deepcopy(kwargs.get("json") or {}),
                    }
                )
                print(f"Captured original Telegram HTML before sending: {filename} ({len(payload)} bytes)")
                return _DummyTelegramResponse()
        return real_session_post(session, url, *args, **kwargs)

    requests.post = intercept
    requests.sessions.Session.post = intercept_session

    exit_code = 0
    try:
        try:
            runpy.run_path("report_engine.py", run_name="__main__")
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
    finally:
        requests.post = real_post
        requests.sessions.Session.post = real_session_post

    if exit_code != 0:
        raise RuntimeError(f"report_engine.py exited with status {exit_code}")
    if not captured:
        raise RuntimeError("report_engine.py did not attempt to send an HTML document")

    original = captured[-1]
    fixed_payload, removed = _fix_html(original["payload"])
    if removed <= 0:
        print("No duplicate instrument rows found in embedded portfolio data; sending validated HTML unchanged.")
    else:
        print(f"Collapsed {removed} duplicate instrument rows before Telegram delivery.")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Missing Telegram credentials")

    data = dict(original.get("data") or {})
    if original.get("json") and not data:
        data.update(original["json"])
    data["chat_id"] = data.get("chat_id") or chat_id

    filename = original["filename"]
    response = real_post(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=data,
        files={"document": (filename, fixed_payload, "text/html")},
        timeout=60,
    )
    response.raise_for_status()
    print(f"Sent corrected HTML to Telegram: {filename} ({len(fixed_payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
