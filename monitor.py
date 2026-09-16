from __future__ import annotations

import html
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ETORO_BASE = "https://public-api.etoro.com/api/v1"
TELEGRAM_BASE = "https://api.telegram.org"

STATE_PATH = Path(os.getenv("STATE_PATH", "state.json"))
REPORT_DIR = Path(os.getenv("REPORT_DIR", "docs"))
REPORT_DATA_PATH = REPORT_DIR / "report.json"

USERNAME = os.getenv("ETORO_USERNAME", "thomaspj").strip()
PORTFOLIO_EUR = float(os.getenv("PORTFOLIO_EUR", "5000"))
MIN_ALERT_EUR = float(os.getenv("MIN_ALERT_EUR", "5"))
PORTFOLIO_SUMMARY_MINUTES = max(1, int(os.getenv("PORTFOLIO_SUMMARY_MINUTES", "10")))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "25"))
SEND_INITIAL_PORTFOLIO = os.getenv("SEND_INITIAL_PORTFOLIO", "true").lower() in {"1", "true", "yes", "on"}
REPORT_URL = os.getenv(
    "REPORT_URL",
    "https://zioprerioda-hub.github.io/dario-investimenti-etoro-bot/",
).strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("thomaspj-monitor")


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


ETORO_API_KEY = required_env("ETORO_API_KEY")
ETORO_USER_KEY = required_env("ETORO_USER_KEY")
TELEGRAM_BOT_TOKEN = required_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = required_env("TELEGRAM_CHAT_ID")


class Etoro:
    def __init__(self) -> None:
        self.s = requests.Session()

    def headers(self) -> dict[str, str]:
        return {
            "x-api-key": ETORO_API_KEY,
            "x-user-key": ETORO_USER_KEY,
            "x-request-id": str(uuid.uuid4()),
            "accept": "application/json",
            "user-agent": "ThomasPJ-Mirror-Monitor/2.0",
        }

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        r = self.s.get(
            f"{ETORO_BASE}{path}",
            headers=self.headers(),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 429:
            retry = r.headers.get("Retry-After", "60")
            raise RuntimeError(f"eToro rate limit (429), Retry-After={retry}")
        r.raise_for_status()
        return r.json()

    def live_portfolio(self, username: str) -> dict[str, Any]:
        data = self.get(f"/user-info/people/{username}/portfolio/live")
        if not isinstance(data, dict) or not isinstance(data.get("positions"), list):
            raise RuntimeError("Unexpected eToro live portfolio response")
        return data

    def instrument_info(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        ids = sorted(set(ids))
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            if not chunk:
                continue
            data = self.get(
                "/market-data/instruments",
                {"instrumentIds": ",".join(str(x) for x in chunk)},
            )
            for row in data.get("instrumentDisplayDatas", []):
                if isinstance(row, dict) and row.get("instrumentID") is not None:
                    result[int(row["instrumentID"])] = row
        return result

    def market_rates(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        ids = sorted(set(ids))
        for i in range(0, len(ids), 100):
            chunk = ids[i:i + 100]
            if not chunk:
                continue
            data = self.get(
                "/market-data/instruments/rates",
                {"instrumentIds": ",".join(str(x) for x in chunk)},
            )
            for row in data.get("rates", []):
                if isinstance(row, dict) and row.get("instrumentID") is not None:
                    result[int(row["instrumentID"])] = row
        return result


def tg_send(text: str) -> None:
    url = f"{TELEGRAM_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()


def report_link_line() -> str:
    if not REPORT_URL:
        return ""
    safe_url = html.escape(REPORT_URL, quote=True)
    return f'🌐 <a href="{safe_url}">Apri report live HTML</a>'


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {
            "initialized": False,
            "positions": {},
            "updated_at": None,
            "last_portfolio_summary_at": None,
        }
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError
        state.setdefault("initialized", False)
        state.setdefault("positions", {})
        state.setdefault("last_portfolio_summary_at", None)
        return state
    except Exception:
        log.warning("state.json unreadable; starting fresh")
        return {
            "initialized": False,
            "positions": {},
            "updated_at": None,
            "last_portfolio_summary_at": None,
        }


def save_state(
    positions: dict[int, dict[str, Any]],
    last_portfolio_summary_at: str | None = None,
) -> None:
    serial = {str(pid): p for pid, p in positions.items()}
    previous_summary = None

    if STATE_PATH.exists():
        try:
            previous = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(previous, dict):
                previous_summary = previous.get("last_portfolio_summary_at")
        except Exception:
            pass

    state = {
        "initialized": True,
        "positions": serial,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_portfolio_summary_at": (
            last_portfolio_summary_at
            if last_portfolio_summary_at is not None
            else previous_summary
        ),
    }
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def normalize_positions(snapshot: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for raw in snapshot.get("positions", []):
        if not isinstance(raw, dict):
            continue
        if raw.get("positionId") is None or raw.get("instrumentId") is None:
            continue

        pid = int(raw["positionId"])
        out[pid] = {
            "positionId": pid,
            "instrumentId": int(raw["instrumentId"]),
            "openTimestamp": raw.get("openTimestamp"),
            "openRate": raw.get("openRate"),
            "isBuy": raw.get("isBuy"),
            "leverage": raw.get("leverage"),
            "investmentPct": raw.get("investmentPct"),
            "netProfit": raw.get("netProfit"),
        }
    return out


def fnum(value: Any, digits: int = 2) -> str:
    try:
        x = float(value)
        s = f"{x:,.{digits}f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "N/D"


def euro(value: Any) -> str:
    return f"€{fnum(value, 2)}"


def position_eur(p: dict[str, Any]) -> float:
    try:
        return max(
            0.0,
            PORTFOLIO_EUR * float(p.get("investmentPct") or 0) / 100.0,
        )
    except Exception:
        return 0.0


def instrument_parts(
    iid: int,
    meta: dict[int, dict[str, Any]],
) -> tuple[str, str]:
    row = meta.get(iid, {})
    symbol = str(row.get("symbolFull") or f"#{iid}")
    name = str(row.get("instrumentDisplayName") or "")
    return symbol, name


def label(iid: int, meta: dict[int, dict[str, Any]]) -> str:
    symbol, name = instrument_parts(iid, meta)
    if name:
        return f"{symbol} — {name}"
    return symbol


def current_price(rate: dict[str, Any] | None) -> float | None:
    if not rate:
        return None
    for key in ("lastExecution", "ask", "bid"):
        if rate.get(key) is not None:
            try:
                return float(rate[key])
            except Exception:
                pass
    return None


def deviation_value(
    open_rate: Any,
    now: float | None,
    is_buy: Any,
) -> float | None:
    if now is None or open_rate in (None, 0, ""):
        return None
    try:
        d = (now / float(open_rate) - 1.0) * 100.0
        if is_buy is False:
            d *= -1
        return d
    except Exception:
        return None


def deviation(open_rate: Any, now: float | None, is_buy: Any) -> str | None:
    d = deviation_value(open_rate, now, is_buy)
    if d is None:
        return None
    return ("+" if d >= 0 else "") + fnum(d, 2) + "%"


def event_open_message(
    p: dict[str, Any],
    meta: dict[int, dict[str, Any]],
    rates: dict[int, dict[str, Any]],
) -> str:
    iid = int(p["instrumentId"])
    amount = position_eur(p)
    side = "BUY / LONG" if p.get("isBuy") is True else "SELL / SHORT"
    price = current_price(rates.get(iid))
    dev = deviation(p.get("openRate"), price, p.get("isBuy"))

    lines = [
        "🟢 <b>NUOVA OPERAZIONE THOMASPJ</b>",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"<b>{html.escape(label(iid, meta))}</b>",
        f"Operazione: <b>{side}</b>",
        "",
        f"📊 Peso posizione: <b>{fnum(p.get('investmentPct'))}%</b>",
        f"💶 Capitale replica: <b>{euro(PORTFOLIO_EUR)}</b>",
        f"🎯 Importo da replicare: <b>{euro(amount)}</b>",
        "",
        f"💵 Prezzo apertura eToro: <b>{fnum(p.get('openRate'), 4)}</b>",
        f"⚙️ Leva: <b>x{fnum(p.get('leverage'), 0)}</b>",
    ]

    if price is not None:
        lines.append(f"📍 Prezzo eToro rilevato: <b>{fnum(price, 4)}</b>")
    if dev:
        lines.append(f"📈 Scostamento: <b>{dev}</b>")

    lines += [
        "",
        f"🕐 Apertura: {html.escape(str(p.get('openTimestamp') or 'N/D'))}",
        f"ID posizione: <code>{p.get('positionId')}</code>",
    ]

    link = report_link_line()
    if link:
        lines += ["", link]

    return "\n".join(lines)


def event_close_message(
    p: dict[str, Any],
    meta: dict[int, dict[str, Any]],
    rates: dict[int, dict[str, Any]],
) -> str:
    iid = int(p["instrumentId"])
    amount = position_eur(p)
    was_long = p.get("isBuy") is True
    action = "SELL" if was_long else "BUY TO CLOSE"
    price = current_price(rates.get(iid))
    dev = deviation(p.get("openRate"), price, p.get("isBuy"))

    lines = [
        "🔴 <b>POSIZIONE THOMASPJ CHIUSA</b>",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"<b>{html.escape(label(iid, meta))}</b>",
        f"Operazione replica: <b>{action}</b>",
        "",
        f"📊 Peso precedente: <b>{fnum(p.get('investmentPct'))}%</b>",
        f"🎯 Importo da rimuovere: <b>{euro(amount)}</b>",
        "",
        f"💵 Prezzo apertura eToro: <b>{fnum(p.get('openRate'), 4)}</b>",
        f"⚙️ Leva: <b>x{fnum(p.get('leverage'), 0)}</b>",
    ]

    if price is not None:
        lines.append(
            f"📍 Prezzo mercato al rilevamento: <b>{fnum(price, 4)}</b>"
        )
    if dev:
        lines.append(f"📈 Movimento dalla sua apertura: <b>{dev}</b>")

    lines += [
        "",
        f"ID posizione: <code>{p.get('positionId')}</code>",
        "",
        "<i>Il prezzo alla chiusura è quello rilevato dal bot, "
        "non necessariamente il fill esatto di thomaspj.</i>",
    ]

    link = report_link_line()
    if link:
        lines += ["", link]

    return "\n".join(lines)


def grouped_allocations(
    positions: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}

    for p in positions.values():
        iid = int(p["instrumentId"])
        row = grouped.setdefault(
            iid,
            {"pct": 0.0, "count": 0, "long": 0, "short": 0},
        )
        try:
            row["pct"] += float(p.get("investmentPct") or 0)
        except Exception:
            pass
        row["count"] += 1

        if p.get("isBuy") is True:
            row["long"] += 1
        elif p.get("isBuy") is False:
            row["short"] += 1

    return grouped


def initial_summary(
    positions: dict[int, dict[str, Any]],
    meta: dict[int, dict[str, Any]],
) -> list[str]:
    grouped = grouped_allocations(positions)
    rows = sorted(grouped.items(), key=lambda x: x[1]["pct"], reverse=True)

    head = [
        "✅ <b>MONITOR THOMASPJ ATTIVO</b>",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"Portafoglio sorgente: <b>@{html.escape(USERNAME)}</b>",
        f"Capitale replica configurato: <b>{euro(PORTFOLIO_EUR)}</b>",
        f"Posizioni eToro rilevate: <b>{len(positions)}</b>",
        "",
        "<b>Allocazione iniziale equivalente</b>",
    ]

    messages: list[str] = []
    current = head[:]

    for iid, row in rows:
        pct = row["pct"]
        line = (
            f"• {html.escape(label(iid, meta))}: "
            f"<b>{fnum(pct)}%</b> → "
            f"<b>{euro(PORTFOLIO_EUR * pct / 100.0)}</b>"
        )
        if len("\n".join(current + [line])) > 3600:
            messages.append("\n".join(current))
            current = [
                "📊 <b>PORTAFOGLIO THOMASPJ — continua</b>",
                "",
                line,
            ]
        else:
            current.append(line)

    if current:
        current += [
            "",
            "Da ora riceverai un messaggio quando compare o scompare "
            "un <code>positionId</code> nel portafoglio pubblico eToro.",
        ]
        link = report_link_line()
        if link:
            current += ["", link]
        messages.append("\n".join(current))

    return messages


def utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def portfolio_summary_due(last_sent: str | None) -> bool:
    if not last_sent:
        return True
    try:
        dt = datetime.fromisoformat(last_sent.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - dt).total_seconds()
        return elapsed >= PORTFOLIO_SUMMARY_MINUTES * 60
    except Exception:
        return True


def portfolio_summary(
    positions: dict[int, dict[str, Any]],
    meta: dict[int, dict[str, Any]],
) -> list[str]:
    grouped = grouped_allocations(positions)
    rows = sorted(grouped.items(), key=lambda item: item[1]["pct"], reverse=True)

    total_pct = sum(row["pct"] for _, row in rows)
    allocated_eur = PORTFOLIO_EUR * total_pct / 100.0
    residual_eur = max(0.0, PORTFOLIO_EUR - allocated_eur)

    header = [
        "📊 <b>PORTAFOGLIO COMPLETO THOMASPJ</b>",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"🕐 Aggiornamento: <b>{datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}</b>",
        f"💶 Capitale replica: <b>{euro(PORTFOLIO_EUR)}</b>",
        f"📈 Totale allocato: <b>{fnum(total_pct)}%</b> → <b>{euro(allocated_eur)}</b>",
        f"💵 Quota residua teorica: <b>{euro(residual_eur)}</b>",
        f"📦 Posizioni eToro: <b>{len(positions)}</b>",
        f"🧩 Strumenti distinti: <b>{len(grouped)}</b>",
        "",
        "<b>Dettaglio allocazioni</b>",
    ]

    messages: list[str] = []
    current = header[:]

    for iid, row in rows:
        direction = (
            "LONG"
            if row["short"] == 0
            else ("SHORT" if row["long"] == 0 else "MISTO")
        )
        target_eur = PORTFOLIO_EUR * row["pct"] / 100.0
        line = (
            f"• {html.escape(label(iid, meta))}: "
            f"<b>{fnum(row['pct'])}%</b> → "
            f"<b>{euro(target_eur)}</b> · {direction}"
        )
        if row["count"] > 1:
            line += f" · {row['count']} posizioni"

        if len("\n".join(current + [line])) > 3600:
            messages.append("\n".join(current))
            current = [
                "📊 <b>PORTAFOGLIO THOMASPJ — continua</b>",
                "",
                line,
            ]
        else:
            current.append(line)

    if not rows:
        current.append("Nessuna posizione aperta restituita da eToro.")

    if current:
        current += [
            "",
            f"<i>Riepilogo automatico ogni {PORTFOLIO_SUMMARY_MINUTES} minuti circa tramite GitHub Actions.</i>",
        ]
        link = report_link_line()
        if link:
            current += ["", link]
        messages.append("\n".join(current))

    return messages


def build_report_payload(
    positions: dict[int, dict[str, Any]],
    meta: dict[int, dict[str, Any]],
    rates: dict[int, dict[str, Any]],
    new_ids: list[int] | None = None,
    closed_ids: list[int] | None = None,
) -> dict[str, Any]:
    grouped = grouped_allocations(positions)
    allocations: list[dict[str, Any]] = []

    for iid, row in sorted(
        grouped.items(),
        key=lambda item: item[1]["pct"],
        reverse=True,
    ):
        symbol, name = instrument_parts(iid, meta)
        direction = (
            "LONG"
            if row["short"] == 0
            else ("SHORT" if row["long"] == 0 else "MISTO")
        )
        allocations.append(
            {
                "instrumentId": iid,
                "symbol": symbol,
                "name": name,
                "weightPct": round(row["pct"], 6),
                "targetEur": round(PORTFOLIO_EUR * row["pct"] / 100.0, 2),
                "direction": direction,
                "positionCount": row["count"],
                "marketPrice": current_price(rates.get(iid)),
            }
        )

    detailed_positions: list[dict[str, Any]] = []
    for p in sorted(
        positions.values(),
        key=lambda x: float(x.get("investmentPct") or 0),
        reverse=True,
    ):
        iid = int(p["instrumentId"])
        symbol, name = instrument_parts(iid, meta)
        now_price = current_price(rates.get(iid))
        detailed_positions.append(
            {
                "positionId": int(p["positionId"]),
                "instrumentId": iid,
                "symbol": symbol,
                "name": name,
                "direction": "LONG" if p.get("isBuy") is True else "SHORT",
                "weightPct": float(p.get("investmentPct") or 0),
                "targetEur": round(position_eur(p), 2),
                "openRate": p.get("openRate"),
                "marketPrice": now_price,
                "deviationPct": deviation_value(
                    p.get("openRate"),
                    now_price,
                    p.get("isBuy"),
                ),
                "leverage": p.get("leverage"),
                "netProfit": p.get("netProfit"),
                "openTimestamp": p.get("openTimestamp"),
            }
        )

    total_pct = sum(row["pct"] for row in grouped.values())
    allocated_eur = PORTFOLIO_EUR * total_pct / 100.0
    residual_eur = max(0.0, PORTFOLIO_EUR - allocated_eur)

    return {
        "version": 1,
        "generatedAt": utc_iso_now(),
        "username": USERNAME,
        "portfolioEur": PORTFOLIO_EUR,
        "refresh": {
            "githubActionsMinutes": 5,
            "browserPollSeconds": 30,
        },
        "summary": {
            "positionCount": len(positions),
            "instrumentCount": len(grouped),
            "allocatedPct": round(total_pct, 6),
            "allocatedEur": round(allocated_eur, 2),
            "residualEur": round(residual_eur, 2),
        },
        "allocations": allocations,
        "positions": detailed_positions,
        "changes": {
            "newPositionIds": new_ids or [],
            "closedPositionIds": closed_ids or [],
        },
        "source": {
            "provider": "eToro Public API",
            "portfolioEndpoint": f"/user-info/people/{USERNAME}/portfolio/live",
        },
    }


def write_report(payload: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DATA_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Updated HTML report data: %s", REPORT_DATA_PATH)


def main() -> int:
    if PORTFOLIO_EUR <= 0:
        raise RuntimeError("PORTFOLIO_EUR must be > 0")

    api = Etoro()
    snapshot = api.live_portfolio(USERNAME)
    current = normalize_positions(snapshot)

    state = load_state()
    old = {
        int(pid): p
        for pid, p in state.get("positions", {}).items()
    }

    all_iids = sorted(
        {
            int(p["instrumentId"])
            for p in list(current.values()) + list(old.values())
        }
    )
    meta = api.instrument_info(all_iids) if all_iids else {}
    rates = api.market_rates(all_iids) if all_iids else {}

    if not state.get("initialized"):
        write_report(
            build_report_payload(
                current,
                meta,
                rates,
                new_ids=[],
                closed_ids=[],
            )
        )

        summary_at = None
        if SEND_INITIAL_PORTFOLIO:
            for msg in initial_summary(current, meta):
                tg_send(msg)
                time.sleep(0.3)
            summary_at = utc_iso_now()

        save_state(
            current,
            last_portfolio_summary_at=summary_at,
        )
        log.info("Initialized baseline with %d positions", len(current))
        return 0

    new_ids = sorted(set(current) - set(old))
    closed_ids = sorted(set(old) - set(current))

    if (
        old
        and len(closed_ids) >= 5
        and len(closed_ids) / max(1, len(old)) >= 0.35
    ):
        raise RuntimeError(
            f"Suspicious snapshot: {len(closed_ids)}/{len(old)} "
            "positions disappeared at once. State/report not changed."
        )

    write_report(
        build_report_payload(
            current,
            meta,
            rates,
            new_ids=new_ids,
            closed_ids=closed_ids,
        )
    )

    sent = 0

    for pid in new_ids:
        p = current[pid]
        if position_eur(p) < MIN_ALERT_EUR:
            log.info(
                "Skipping new position %s because equivalent %.2f < MIN_ALERT_EUR",
                pid,
                position_eur(p),
            )
            continue
        tg_send(event_open_message(p, meta, rates))
        sent += 1
        time.sleep(0.3)

    for pid in closed_ids:
        p = old[pid]
        if position_eur(p) < MIN_ALERT_EUR:
            log.info(
                "Skipping closed position %s because equivalent %.2f < MIN_ALERT_EUR",
                pid,
                position_eur(p),
            )
            continue
        tg_send(event_close_message(p, meta, rates))
        sent += 1
        time.sleep(0.3)

    last_summary = state.get("last_portfolio_summary_at")
    summary_at = last_summary

    if portfolio_summary_due(last_summary):
        for msg in portfolio_summary(current, meta):
            tg_send(msg)
            sent += 1
            time.sleep(0.3)
        summary_at = utc_iso_now()
        log.info("Sent complete portfolio summary")

    save_state(
        current,
        last_portfolio_summary_at=summary_at,
    )

    log.info(
        "Done: new=%d closed=%d telegram=%d report=%s",
        len(new_ids),
        len(closed_ids),
        sent,
        REPORT_DATA_PATH,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log.exception("Monitor failed: %s", exc)
        sys.exit(1)
