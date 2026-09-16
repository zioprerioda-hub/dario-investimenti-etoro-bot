from __future__ import annotations

import html
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

TELEGRAM_BASE = "https://api.telegram.org"
REPORT_JSON_PATH = Path(os.getenv("REPORT_JSON_PATH", "docs/report.json"))
REPORT_STATE_PATH = Path(os.getenv("REPORT_STATE_PATH", "html_report_state.json"))
REPORT_INTERVAL_MINUTES = max(
    1,
    int(
        os.getenv(
            "HTML_REPORT_MINUTES",
            os.getenv("PORTFOLIO_SUMMARY_MINUTES", "10"),
        )
    ),
)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "25"))


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


TELEGRAM_BOT_TOKEN = required_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = required_env("TELEGRAM_CHAT_ID")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Missing report data file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Invalid report JSON")
    return data


def load_state() -> dict[str, Any]:
    if not REPORT_STATE_PATH.exists():
        return {"last_sent_at": None, "last_generated_at": None}
    try:
        data = json.loads(REPORT_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"last_sent_at": None, "last_generated_at": None}


def save_state(generated_at: str | None) -> None:
    payload = {
        "last_sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_generated_at": generated_at,
    }
    REPORT_STATE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def due(last_sent_at: str | None) -> bool:
    if not last_sent_at:
        return True
    try:
        dt = datetime.fromisoformat(last_sent_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (
            datetime.now(timezone.utc) - dt
        ).total_seconds() >= REPORT_INTERVAL_MINUTES * 60
    except Exception:
        return True


def n(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"


def eur(value: Any) -> str:
    return f"€{n(value, 2)}"


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else "—"))


def signed(value: Any, suffix: str = "%") -> str:
    try:
        x = float(value)
        return ("+" if x >= 0 else "") + n(x, 2) + suffix
    except Exception:
        return "—"


def parse_stamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def build_html(data: dict[str, Any]) -> str:
    username = str(data.get("username") or "thomaspj")
    generated_at = data.get("generatedAt")
    stamp = parse_stamp(generated_at)
    stamp_text = stamp.astimezone().strftime("%d/%m/%Y %H:%M")
    summary = data.get("summary") or {}
    allocations = data.get("allocations") or []
    positions = data.get("positions") or []
    changes = data.get("changes") or {}
    portfolio_eur = data.get("portfolioEur", 0)

    allocation_rows = []
    max_pct = max([float(x.get("weightPct") or 0) for x in allocations] or [1.0])
    for row in allocations:
        pct = float(row.get("weightPct") or 0)
        width = max(1.0, pct / max_pct * 100.0)
        allocation_rows.append(
            f"""
            <div class="allocation-row">
              <div class="allocation-name"><b>{esc(row.get('symbol'))}</b><span>{esc(row.get('name'))}</span></div>
              <div class="allocation-track"><div class="allocation-fill" style="width:{width:.2f}%"></div></div>
              <div class="allocation-value">{n(pct)}% · {eur(row.get('targetEur'))}</div>
            </div>
            """
        )

    position_rows = []
    for p in positions:
        dev = p.get("deviationPct")
        pnl = p.get("netProfit")
        try:
            dev_cls = "pos" if float(dev) >= 0 else "neg"
        except Exception:
            dev_cls = "muted"
        try:
            pnl_cls = "pos" if float(pnl) >= 0 else "neg"
        except Exception:
            pnl_cls = "muted"
        direction = str(p.get("direction") or "—")
        dir_cls = "long" if direction == "LONG" else "short"
        opened = p.get("openTimestamp")
        if opened:
            try:
                opened = parse_stamp(str(opened)).astimezone().strftime("%d/%m/%Y %H:%M")
            except Exception:
                pass
        position_rows.append(
            f"""
            <tr>
              <td><div class="instrument"><b>{esc(p.get('symbol'))}</b><span>{esc(p.get('name'))}</span></div></td>
              <td><span class="pill {dir_cls}">{esc(direction)}</span></td>
              <td>{n(p.get('weightPct'))}%</td>
              <td><b>{eur(p.get('targetEur'))}</b></td>
              <td>{n(p.get('openRate'),4)}</td>
              <td>{n(p.get('marketPrice'),4)}</td>
              <td class="{dev_cls}">{signed(dev)}</td>
              <td>x{n(p.get('leverage'),0)}</td>
              <td class="{pnl_cls}">{signed(pnl)}</td>
              <td>{esc(opened)}</td>
              <td><code>{esc(p.get('positionId'))}</code></td>
            </tr>
            """
        )

    if not allocation_rows:
        allocation_rows.append('<div class="empty">Nessuna allocazione disponibile.</div>')
    if not position_rows:
        position_rows.append('<tr><td colspan="11" class="empty">Nessuna posizione aperta.</td></tr>')

    new_count = len(changes.get("newPositionIds") or [])
    closed_count = len(changes.get("closedPositionIds") or [])

    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(username)} · eToro Mirror Report</title>
<style>
:root{{--bg:#0d1625;--panel:#1a2535;--panel2:#111b2a;--line:#334155;--text:#f7f8fb;--muted:#9ca8ba;--green:#18c54d;--red:#ff4c55;--blue:#249cf0;--amber:#f4b63d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif}}.wrap{{max-width:1500px;margin:auto;padding:22px}}.hero{{border:1px solid var(--line);background:var(--panel);border-radius:18px;padding:24px;display:flex;justify-content:space-between;gap:20px;align-items:center}}.hero h1{{margin:5px 0 0;font-size:36px}}.hero p{{margin:7px 0 0;color:var(--muted)}}.badge{{display:inline-flex;align-items:center;gap:8px;background:#153b28;color:#83f0a6;border:1px solid #25683f;padding:8px 12px;border-radius:999px;font-weight:800;font-size:13px}}.dot{{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green)}}.hero-meta{{text-align:right;color:var(--muted);font-size:13px}}.hero-meta b{{color:#fff}}.tabs{{margin:24px auto;border:1px solid #414957;border-radius:15px;padding:6px;display:flex;gap:5px;width:max-content;max-width:100%;overflow:auto}}.tabs button{{background:transparent;border:0;color:#adb5c3;padding:10px 18px;border-radius:11px;font-size:16px;cursor:pointer}}.tabs button.active{{background:#0dc32f;color:#fff}}.panel{{display:none}}.panel.active{{display:block}}.cards{{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:14px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px}}.label{{color:var(--muted);font-size:13px}}.value{{font-size:27px;font-weight:800;margin-top:8px}}.grid{{display:grid;grid-template-columns:1.15fr .85fr;gap:16px;margin-top:16px}}.section{{background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden}}.section h2{{margin:0;padding:18px 20px;border-bottom:1px solid var(--line);font-size:18px}}.allocations{{padding:18px}}.allocation-row{{display:grid;grid-template-columns:minmax(160px,1.5fr) 3fr auto;align-items:center;gap:12px;margin:13px 0}}.allocation-name{{display:flex;flex-direction:column;gap:2px;min-width:0}}.allocation-name span{{color:var(--muted);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.allocation-track{{height:10px;border-radius:999px;background:#283649;overflow:hidden}}.allocation-fill{{height:100%;background:linear-gradient(90deg,#169e3b,#36db68);border-radius:999px}}.allocation-value{{font-variant-numeric:tabular-nums;white-space:nowrap}}.facts{{padding:18px;display:grid;gap:12px}}.fact{{display:flex;justify-content:space-between;gap:16px;padding-bottom:10px;border-bottom:1px solid #2c394b}}.fact span:first-child{{color:var(--muted)}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:1180px}}th,td{{padding:13px 14px;border-bottom:1px solid #2c394b;text-align:left;white-space:nowrap}}th{{background:#182334;color:#aab4c4;font-size:11px;text-transform:uppercase;letter-spacing:.05em;position:sticky;top:0}}td{{font-size:14px}}.instrument{{display:flex;flex-direction:column}}.instrument span{{color:var(--muted);font-size:12px}}.pill{{display:inline-block;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:800}}.pill.long{{background:#153b28;color:#7df0a4}}.pill.short{{background:#4b1f25;color:#ff9da5}}.pos{{color:var(--green);font-weight:700}}.neg{{color:var(--red);font-weight:700}}.muted{{color:var(--muted)}}code{{color:#cbd7e6}}.empty{{padding:24px;color:var(--muted);text-align:center}}footer{{color:var(--muted);font-size:12px;padding:26px 2px;line-height:1.5}}@media(max-width:1050px){{.cards{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}.hero{{align-items:flex-start;flex-direction:column}}.hero-meta{{text-align:left}}}}@media(max-width:620px){{.wrap{{padding:12px}}.cards{{grid-template-columns:1fr}}.hero h1{{font-size:29px}}.tabs{{width:100%}}.tabs button{{flex:1}}.allocation-row{{grid-template-columns:1fr auto}}.allocation-track{{grid-column:1/-1}}}}
</style>
</head>
<body>
<div class="wrap">
<header class="hero">
  <div><div class="badge"><span class="dot"></span> ETORO SNAPSHOT</div><h1>{esc(username)}</h1><p>Report privato del portafoglio pubblico · replica proporzionale su {eur(portfolio_eur)}</p></div>
  <div class="hero-meta"><div>Aggiornato: <b>{esc(stamp_text)}</b></div><div>Nuove posizioni: <b>{new_count}</b> · Chiuse: <b>{closed_count}</b></div></div>
</header>
<nav class="tabs"><button class="active" data-tab="overview">Overview</button><button data-tab="positions">Positions</button></nav>
<section id="overview" class="panel active">
  <div class="cards">
    <article class="card"><div class="label">Capitale replica</div><div class="value">{eur(portfolio_eur)}</div></article>
    <article class="card"><div class="label">Allocato</div><div class="value">{n(summary.get('allocatedPct'))}%</div></article>
    <article class="card"><div class="label">Valore allocato</div><div class="value">{eur(summary.get('allocatedEur'))}</div></article>
    <article class="card"><div class="label">Residuo teorico</div><div class="value">{eur(summary.get('residualEur'))}</div></article>
    <article class="card"><div class="label">Posizioni aperte</div><div class="value">{esc(summary.get('positionCount'))}</div></article>
  </div>
  <div class="grid">
    <article class="section"><h2>Allocazione per strumento</h2><div class="allocations">{''.join(allocation_rows)}</div></article>
    <article class="section"><h2>Dettagli snapshot</h2><div class="facts">
      <div class="fact"><span>Utente eToro</span><b>@{esc(username)}</b></div>
      <div class="fact"><span>Strumenti distinti</span><b>{esc(summary.get('instrumentCount'))}</b></div>
      <div class="fact"><span>Posizioni</span><b>{esc(summary.get('positionCount'))}</b></div>
      <div class="fact"><span>Nuove ultimo controllo</span><b>{new_count}</b></div>
      <div class="fact"><span>Chiuse ultimo controllo</span><b>{closed_count}</b></div>
      <div class="fact"><span>Fonte</span><b>eToro Public API</b></div>
    </div></article>
  </div>
</section>
<section id="positions" class="panel"><article class="section"><h2>Posizioni correnti eToro</h2><div class="table-wrap"><table><thead><tr><th>Strumento</th><th>Direzione</th><th>Peso</th><th>Replica €</th><th>Open rate</th><th>Prezzo attuale</th><th>Scostamento</th><th>Leva</th><th>P/L eToro</th><th>Apertura</th><th>Position ID</th></tr></thead><tbody>{''.join(position_rows)}</tbody></table></div></article></section>
<footer>Questo file è uno snapshot generato automaticamente dal bot. Non contiene API key né token. I valori restano quelli del momento di generazione; al successivo invio Telegram riceverai un nuovo file aggiornato.</footer>
</div>
<script>document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id===b.dataset.tab));}});</script>
</body></html>"""


def send_document(path: Path, caption: str) -> None:
    url = f"{TELEGRAM_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    with path.open("rb") as fh:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML",
            },
            files={"document": (path.name, fh, "text/html")},
            timeout=REQUEST_TIMEOUT,
        )
    response.raise_for_status()


def main() -> int:
    state = load_state()
    if not due(state.get("last_sent_at")):
        print("HTML report not due yet")
        return 0

    data = load_json(REPORT_JSON_PATH)
    generated_at = data.get("generatedAt")
    if not generated_at:
        print("Report JSON has no generatedAt yet; skip HTML send")
        return 0

    content = build_html(data)
    stamp = parse_stamp(str(generated_at))
    file_name = f"Report_{data.get('username') or 'thomaspj'}_{stamp.strftime('%Y-%m-%d_%H-%M')}.html"

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / file_name
        path.write_text(content, encoding="utf-8")
        caption = (
            f"📊 <b>REPORT HTML {esc(str(data.get('username') or 'thomaspj')).upper()}</b>\n"
            f"Snapshot eToro: <b>{stamp.astimezone().strftime('%d/%m/%Y %H:%M')}</b>\n"
            f"Apri il file nel browser per vedere Overview e Positions."
        )
        send_document(path, caption)

    save_state(str(generated_at))
    print(f"HTML report sent: {file_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
