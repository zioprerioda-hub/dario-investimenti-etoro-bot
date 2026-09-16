from __future__ import annotations

import json
import math
import statistics
from datetime import datetime
from typing import Any

import run_report_fixed as base

PERIODS = ("Year to date", "Last Year", "Last 2 Years", "Last 3 Years", "Last 5 Years", "All Time")


def _finite(x: Any) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    for fmt in ("%b %Y", "%B %Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%b %d %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _performance_series(data: dict[str, Any]) -> list[tuple[datetime, float, float]]:
    perf = data.get("performance")
    if not isinstance(perf, dict):
        return []
    labels = perf.get("labels")
    if not isinstance(labels, list) or len(labels) < 3:
        return []

    arrays: list[tuple[str, list[Any]]] = []
    for key, value in perf.items():
        if key == "labels" or not isinstance(value, list) or len(value) != len(labels):
            continue
        if sum(_finite(v) is not None for v in value) >= max(3, len(labels) // 2):
            arrays.append((str(key), value))
    if not arrays:
        return []

    benchmark = None
    for key, arr in arrays:
        lk = key.lower()
        if any(token in lk for token in ("sp500", "s&p", "benchmark", "spy")):
            benchmark = arr
            break

    portfolio = None
    user = str((data.get("profile") or {}).get("username") or "").lower()
    for wanted in (user, "thomaspj", "jeppe", "strategy", "portfolio", "user", "equity"):
        if not wanted:
            continue
        for key, arr in arrays:
            if arr is benchmark:
                continue
            if wanted in key.lower():
                portfolio = arr
                break
        if portfolio is not None:
            break
    if portfolio is None:
        portfolio = next((arr for _, arr in arrays if arr is not benchmark), None)
    if portfolio is None:
        return []
    if benchmark is None:
        benchmark = [0.0] * len(labels)

    rows: list[tuple[datetime, float, float]] = []
    for lab, p, b in zip(labels, portfolio, benchmark):
        dt = _parse_date(lab)
        pv = _finite(p)
        bv = _finite(b)
        if dt is not None and pv is not None and bv is not None:
            rows.append((dt, pv, bv))
    rows.sort(key=lambda x: x[0])
    return rows


def _period_start(label: str, end: datetime) -> datetime | None:
    if label == "Year to date":
        return datetime(end.year, 1, 1)
    years = {"Last Year": 1, "Last 2 Years": 2, "Last 3 Years": 3, "Last 5 Years": 5}.get(label)
    if years is None:
        return None
    try:
        return end.replace(year=end.year - years)
    except ValueError:
        return end.replace(month=2, day=28, year=end.year - years)


def _slice_with_anchor(rows: list[tuple[datetime, float, float]], label: str) -> list[tuple[datetime, float, float]]:
    if not rows or label == "All Time":
        return rows[:]
    start = _period_start(label, rows[-1][0])
    if start is None:
        return rows[:]
    idx = next((i for i, row in enumerate(rows) if row[0] >= start), len(rows) - 1)
    return rows[max(0, idx - 1):]


def _sample_std(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else 0.0


def _cov_pop(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    aa, bb = a[:n], b[:n]
    ma, mb = statistics.fmean(aa), statistics.fmean(bb)
    return sum((x - ma) * (y - mb) for x, y in zip(aa, bb)) / n


def _var_pop(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = statistics.fmean(values)
    return sum((x - mean) ** 2 for x in values) / len(values)


def _max_drawdown(equity: list[float]) -> float:
    peak = -math.inf
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def _infer_periods_per_year(dates: list[datetime]) -> float:
    deltas = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
    if not deltas:
        return 12.0
    med = statistics.median(deltas)
    if med <= 3:
        return 252.0
    return max(1.0, min(252.0, 365.25 / med))


def _score(metrics: dict[str, float]) -> float:
    sharpe = max(0.0, min(10.0, metrics.get("sharpe", 0.0) / 2.0 * 10.0))
    sortino = max(0.0, min(10.0, metrics.get("sortino", 0.0) / 3.0 * 10.0))
    omega = max(0.0, min(10.0, (metrics.get("omega", 1.0) - 0.5) / 1.5 * 10.0))
    info = max(0.0, min(10.0, (metrics.get("information", 0.0) + 0.5) / 1.5 * 10.0))
    calmar = max(0.0, min(10.0, metrics.get("calmar", 0.0) / 2.0 * 10.0))
    return round(statistics.fmean([sharpe, sortino, omega, info, calmar]), 1)


def _metrics_for(rows: list[tuple[datetime, float, float]]) -> dict[str, float]:
    zero = {"score": 0.0, "beta": 0.0, "sharpe": 0.0, "sortino": 0.0, "jensen": 0.0, "omega": 0.0, "treynor": 0.0, "information": 0.0, "calmar": 0.0}
    if len(rows) < 3:
        return zero

    peq = [1.0 + row[1] / 100.0 for row in rows]
    beq = [1.0 + row[2] / 100.0 for row in rows]
    if any(x <= 0 for x in peq) or any(x <= 0 for x in beq):
        return zero

    r = [peq[i] / peq[i - 1] - 1.0 for i in range(1, len(peq))]
    b = [beq[i] / beq[i - 1] - 1.0 for i in range(1, len(beq))]
    dates = [row[0] for row in rows]
    ppy = _infer_periods_per_year(dates)
    mu = statistics.fmean(r)
    sd = _sample_std(r)
    downside = math.sqrt(sum(min(x, 0.0) ** 2 for x in r) / len(r)) if r else 0.0
    sharpe = mu / sd * math.sqrt(ppy) if sd > 0 else 0.0
    sortino = mu / downside * math.sqrt(ppy) if downside > 0 else 0.0

    var_b = _var_pop(b)
    beta = _cov_pop(r, b) / var_b if var_b > 0 else 0.0
    elapsed_days = max(1, (rows[-1][0] - rows[0][0]).days)
    years = max(elapsed_days / 365.25, 1.0 / ppy)
    ann_r = (peq[-1] / peq[0]) ** (1.0 / years) - 1.0
    ann_b = (beq[-1] / beq[0]) ** (1.0 / years) - 1.0
    jensen = ann_r - beta * ann_b

    pos = sum(max(x, 0.0) for x in r)
    neg = abs(sum(min(x, 0.0) for x in r))
    omega = pos / neg if neg > 0 else (10.0 if pos > 0 else 0.0)
    treynor = ann_r / beta if abs(beta) > 1e-12 else 0.0
    active = [x - y for x, y in zip(r, b)]
    active_sd = _sample_std(active)
    information = statistics.fmean(active) / active_sd * math.sqrt(ppy) if active_sd > 0 else 0.0
    mdd = abs(_max_drawdown(peq))
    calmar = ann_r / mdd if mdd > 0 else 0.0

    result = {"beta": beta, "sharpe": sharpe, "sortino": sortino, "jensen": jensen * 100.0, "omega": omega, "treynor": treynor, "information": information, "calmar": calmar}
    result["score"] = _score(result)
    return {k: (round(v, 6) if math.isfinite(v) else 0.0) for k, v in result.items()}


def _period_metrics(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    rows = _performance_series(data)
    if len(rows) < 3:
        return {"All Time": dict(data.get("performanceMetrics") or {})}
    return {label: _metrics_for(_slice_with_anchor(rows, label)) for label in PERIODS}


PERFORMANCE_JS = r'''
<script id="performance-range-fix-v2">
(() => {
  const PERIODS = ['Year to date','Last Year','Last 2 Years','Last 3 Years','Last 5 Years','All Time'];
  const select = document.querySelector('.ov-select[aria-label="Time period"]');
  const label = document.getElementById('metricPeriodLabel');
  const grid = document.getElementById('performanceMetricGrid');
  const score = document.getElementById('metricScorePill');
  if (!select || !label || !grid || typeof D === 'undefined') return;
  document.querySelectorAll('.pm-range-menu-fixed').forEach(el => el.remove());
  const menu = document.createElement('div');
  menu.className = 'pm-range-menu-fixed';
  PERIODS.forEach(name => {
    const b = document.createElement('button'); b.type = 'button'; b.dataset.period = name;
    b.innerHTML = `<span>${name}</span><b>${name === 'All Time' ? '✓' : ''}</b>`; menu.appendChild(b);
  });
  const custom = document.createElement('button'); custom.type = 'button'; custom.disabled = true; custom.className = 'disabled';
  custom.innerHTML = '<span>🔒&nbsp; Custom</span><b></b>'; menu.appendChild(custom);
  select.parentElement.style.position = 'relative'; select.parentElement.appendChild(menu);
  const prettyLocal = (n,d=2) => Number(n ?? 0).toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:d});
  const defsFor = pm => [
    {label:'Beta',value:pm.beta,min:0,t1:.8,t2:1.2,max:2,dec:2},
    {label:'Sharpe Ratio',value:pm.sharpe,min:0,t1:.5,t2:1,max:2,dec:2},
    {label:'Sortino Ratio',value:pm.sortino,min:0,t1:1,t2:2,max:3,dec:2},
    {label:"Jensen's Alpha",value:pm.jensen,min:-2,t1:0,t2:2,max:15,dec:1},
    {label:'Omega Ratio',value:pm.omega,min:0,t1:1,t2:1.5,max:3,dec:2},
    {label:'Treynor Ratio',value:pm.treynor,min:-2,t1:0,t2:1.25,max:3,dec:2},
    {label:'Information Ratio',value:pm.information,min:-1,t1:0,t2:.6,max:1,dec:2},
    {label:'Calmar Ratio',value:pm.calmar,min:-1,t1:0,t2:.6,max:2,dec:2}
  ];
  const card = m => { const val=Number(m.value||0), span=(m.max-m.min)||1, pos=Math.max(0,Math.min(100,((val-m.min)/span)*100)); const s1=((m.t1-m.min)/span)*100,s2=((m.t2-m.t1)/span)*100,s3=((m.max-m.t2)/span)*100; return `<article class="pm-card"><div class="pm-card-head"><div class="pm-title">${m.label} <span class="pm-info">ⓘ</span></div><div class="pm-link">↗</div></div><div class="pm-value">${prettyLocal(val,m.dec)}</div><div class="pm-meter"><div class="pm-track"><span class="pm-seg red" style="width:${s1}%"></span><span class="pm-seg amber" style="width:${s2}%"></span><span class="pm-seg green" style="width:${s3}%"></span><div class="pm-marker" style="left:${pos}%"><span class="pm-badge">${prettyLocal(val,m.dec)}</span><i></i></div></div><div class="pm-ticks"><span>${prettyLocal(m.min,2)}</span><span>${prettyLocal(m.t1,2)}</span><span>${prettyLocal(m.t2,2)}</span><span>${prettyLocal(m.max,2)}</span></div></div></article>`; };
  function renderPeriod(name){ const pm=(D.performanceMetricsByPeriod||{})[name]||D.performanceMetrics||{}; label.textContent=name; score.textContent=`Score: ${prettyLocal(pm.score||0,1)}/10`; grid.innerHTML=defsFor(pm).map(card).join(''); menu.querySelectorAll('button[data-period]').forEach(b=>{b.classList.toggle('active',b.dataset.period===name);b.querySelector('b').textContent=b.dataset.period===name?'✓':''}); menu.classList.remove('open'); }
  select.addEventListener('click', e=>{e.preventDefault();e.stopImmediatePropagation();menu.classList.toggle('open')}, true);
  menu.addEventListener('click', e=>{const b=e.target.closest('button[data-period]');if(!b)return;e.preventDefault();e.stopPropagation();renderPeriod(b.dataset.period)});
  document.addEventListener('click', e=>{if(!select.contains(e.target)&&!menu.contains(e.target))menu.classList.remove('open')});
  renderPeriod('All Time');
})();
</script>
'''

PERFORMANCE_CSS = r'''
<style id="performance-range-style-v2">
.ov-head{overflow:visible!important}.pm-range-menu-fixed{display:none;position:absolute;right:0;top:calc(100% + 6px);width:190px;padding:6px;background:#17191d;border:1px solid #2c3440;border-radius:12px;box-shadow:0 14px 36px #0008;z-index:99999}.pm-range-menu-fixed.open{display:block}.pm-range-menu-fixed button{width:100%;height:38px;padding:0 10px;border:0;border-radius:8px;background:transparent;color:#9da9bc;display:flex;align-items:center;justify-content:space-between;font:600 14px/1.1 inherit;text-align:left;cursor:pointer}.pm-range-menu-fixed button:hover,.pm-range-menu-fixed button.active{background:#232831;color:#fff}.pm-range-menu-fixed button.active{outline:1px solid #238cff}.pm-range-menu-fixed button.disabled{opacity:.45;cursor:not-allowed}.pm-range-menu-fixed button b{font-size:14px;color:#fff}.ov-select{position:relative;z-index:100000}
</style>
'''


def _enhanced_fix_html(raw_html: bytes) -> tuple[bytes, int]:
    deduped, removed = base._fix_html(raw_html)
    text = deduped.decode("utf-8")
    start, end, data = base._extract_const_d(text)
    if isinstance(data, dict):
        data["performanceMetricsByPeriod"] = _period_metrics(data)
        data["riskFreeAnnual"] = 0.0
    compact = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    text = text[:start] + compact + text[end:]
    text = text.replace("</head>", PERFORMANCE_CSS + '\n<meta name="performance-ranges" content="ytd-1y-2y-3y-5y-alltime-rf0">\n</head>', 1)
    text = text.replace("</body>", PERFORMANCE_JS + "\n</body>", 1)
    return text.encode("utf-8"), removed


def main() -> int:
    base._fix_html = _enhanced_fix_html
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
