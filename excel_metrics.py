from __future__ import annotations

import csv
import io
import json
import math
import os
import statistics
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import requests

API_BASE = "https://public-api.etoro.com/api/v1"
PERIODS = ("Year to date", "Last Year", "Last 2 Years", "Last 3 Years", "Last 5 Years", "All Time")
TRADING_DAYS = 252.0


def _num(value: Any) -> float | None:
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    s = str(value).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%b %Y", "%B %Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _headers() -> dict[str, str]:
    api_key = os.getenv("ETORO_API_KEY", "").strip()
    user_key = os.getenv("ETORO_USER_KEY", "").strip()
    if not api_key or not user_key:
        raise RuntimeError("Missing ETORO_API_KEY or ETORO_USER_KEY")
    return {
        "x-api-key": api_key,
        "x-user-key": user_key,
        "x-request-id": str(uuid.uuid4()),
        "Accept": "application/json",
        "User-Agent": "dario-investimenti-etoro-bot/1.0",
    }


def _get_json(url: str, *, params: dict[str, Any] | None = None, timeout: int = 40) -> Any:
    headers = _headers()
    response = requests.get(url, headers=headers, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _guess_start(data: dict[str, Any]) -> date:
    candidates: list[date] = []
    perf = data.get("performance")
    if isinstance(perf, dict):
        labels = perf.get("labels")
        if isinstance(labels, list):
            for item in labels:
                dt = _date(item)
                if dt is not None:
                    candidates.append(dt)
    # Add a small cushion so the benchmark has the previous close needed to
    # calculate the first daily return of the strategy period.
    if candidates:
        return min(candidates) - timedelta(days=14)
    return date(2010, 1, 1)


def fetch_strategy_daily(username: str, start: date, end: date) -> dict[date, float]:
    """eToro daily user gains as decimal daily returns (0.14 -> 0.0014)."""
    url = f"{API_BASE}/user-info/people/{username}/daily-gain"
    payload = _get_json(
        url,
        params={"minDate": start.isoformat(), "maxDate": end.isoformat(), "type": "Daily"},
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected eToro daily-gain response: {type(payload).__name__}")

    result: dict[date, float] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        dt = _date(row.get("timestamp"))
        gain = _num(row.get("gain"))
        if dt is None or gain is None:
            continue
        result[dt] = gain / 100.0
    if len(result) < 3:
        raise RuntimeError(f"eToro daily-gain returned too few observations ({len(result)})")
    return result


def _benchmark_yahoo(start: date, end: date) -> dict[date, float]:
    """Daily S&P 500 returns from Yahoo's public chart feed (^GSPC)."""
    # period2 is exclusive in the chart endpoint.
    p1 = int(datetime.combine(start - timedelta(days=10), datetime.min.time(), tzinfo=timezone.utc).timestamp())
    p2 = int(datetime.combine(end + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc).timestamp())
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC"
    params = {
        "period1": p1,
        "period2": p2,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "Mozilla/5.0 dario-investimenti-etoro-bot/1.0"},
        timeout=40,
    )
    response.raise_for_status()
    payload = response.json()
    chart = (payload.get("chart") or {}).get("result") or []
    if not chart:
        raise RuntimeError("Yahoo S&P 500 response has no chart result")
    item = chart[0]
    timestamps = item.get("timestamp") or []
    indicators = item.get("indicators") or {}
    adj = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
    closes = adj
    if not closes or len(closes) != len(timestamps):
        closes = (indicators.get("quote") or [{}])[0].get("close") or []
    if len(closes) != len(timestamps):
        raise RuntimeError("Yahoo S&P 500 timestamps/prices length mismatch")

    prices: list[tuple[date, float]] = []
    for ts, close in zip(timestamps, closes):
        value = _num(close)
        if value is None or value <= 0:
            continue
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
        prices.append((dt, value))
    prices.sort()
    if len(prices) < 3:
        raise RuntimeError("Yahoo S&P 500 returned too few daily prices")

    result: dict[date, float] = {}
    prev: float | None = None
    prev_date: date | None = None
    for dt, value in prices:
        if prev is not None and prev > 0:
            # Do not create a synthetic return across a suspiciously large data gap.
            if prev_date is None or (dt - prev_date).days <= 10:
                result[dt] = value / prev - 1.0
        prev = value
        prev_date = dt
    return result


def _benchmark_stooq(start: date, end: date) -> dict[date, float]:
    """Fallback daily S&P 500 closes from Stooq."""
    url = "https://stooq.com/q/d/l/"
    params = {
        "s": "^spx",
        "i": "d",
        "d1": (start - timedelta(days=10)).strftime("%Y%m%d"),
        "d2": (end + timedelta(days=2)).strftime("%Y%m%d"),
    }
    response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=40)
    response.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(response.text)))
    prices: list[tuple[date, float]] = []
    for row in rows:
        dt = _date(row.get("Date"))
        close = _num(row.get("Close"))
        if dt is not None and close is not None and close > 0:
            prices.append((dt, close))
    prices.sort()
    if len(prices) < 3:
        raise RuntimeError("Stooq S&P 500 returned too few daily prices")
    result: dict[date, float] = {}
    prev: float | None = None
    prev_date: date | None = None
    for dt, value in prices:
        if prev is not None and prev > 0 and (prev_date is None or (dt - prev_date).days <= 10):
            result[dt] = value / prev - 1.0
        prev = value
        prev_date = dt
    return result


def fetch_benchmark_daily(start: date, end: date) -> tuple[dict[date, float], str]:
    errors: list[str] = []
    for name, fn in (("Yahoo ^GSPC daily", _benchmark_yahoo), ("Stooq ^SPX daily", _benchmark_stooq)):
        try:
            values = fn(start, end)
            if len(values) >= 3:
                return values, name
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("Unable to retrieve daily S&P 500 benchmark. " + " | ".join(errors))


def _sample_std(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else 0.0


def _covariance_p(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    aa = a[:n]
    bb = b[:n]
    ma = statistics.fmean(aa)
    mb = statistics.fmean(bb)
    return sum((x - ma) * (y - mb) for x, y in zip(aa, bb)) / n


def _variance_p(values: list[float]) -> float:
    if not values:
        return 0.0
    m = statistics.fmean(values)
    return sum((x - m) ** 2 for x in values) / len(values)


def _compound(returns: Iterable[float]) -> float:
    value = 1.0
    for r in returns:
        value *= 1.0 + r
    return value


def _cagr(returns: list[float]) -> float:
    # Exact workbook logic: years = COUNT(daily returns) / 252;
    # CAGR = (Pt/P0)^(1/years)-1.
    n = len(returns)
    if n <= 0:
        return 0.0
    terminal = _compound(returns)
    if terminal <= 0:
        return 0.0
    years = n / TRADING_DAYS
    return terminal ** (1.0 / years) - 1.0


def _max_drawdown(returns: list[float]) -> float:
    # Equivalent to the workbook's cumulative-equity / peak / drawdown sheets.
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, 1.0 - equity / peak)
    return mdd


def _estimated_score(metrics: dict[str, float]) -> float:
    """Display-only score. The uploaded workbook does not define BullAware's Score formula."""
    sharpe = max(0.0, min(10.0, metrics.get("sharpe", 0.0) / 2.0 * 10.0))
    sortino = max(0.0, min(10.0, metrics.get("sortino", 0.0) / 3.0 * 10.0))
    omega = max(0.0, min(10.0, (metrics.get("omega", 1.0) - 0.5) / 1.5 * 10.0))
    info = max(0.0, min(10.0, (metrics.get("information", 0.0) + 0.5) / 1.5 * 10.0))
    calmar = max(0.0, min(10.0, metrics.get("calmar", 0.0) / 2.0 * 10.0))
    return round(statistics.fmean([sharpe, sortino, omega, info, calmar]), 1)


def excel_metrics(strategy_returns: list[float], benchmark_returns: list[float], risk_free_annual: float = 0.0) -> dict[str, float]:
    """Replicate the formulas in analisi.xlsx / sheet 'Metric calculation'."""
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 3:
        return {k: 0.0 for k in ("score", "beta", "sharpe", "sortino", "jensen", "omega", "treynor", "information", "calmar")}

    rs = [float(x) for x in strategy_returns[:n]]
    rb = [float(x) for x in benchmark_returns[:n]]
    rf_y = float(risk_free_annual)
    rf_d = (1.0 + rf_y) ** (1.0 / TRADING_DAYS) - 1.0

    # Sharpe: workbook C82:C87. STDEV is sample standard deviation.
    excess = [r - rf_d for r in rs]
    mean_excess = statistics.fmean(excess)
    sd_excess = _sample_std(excess)
    sharpe = mean_excess / sd_excess * math.sqrt(TRADING_DAYS) if sd_excess > 0 else 0.0

    # Sortino: workbook AS87:AS91. Denominator divides squared downside
    # deviations by COUNT(all returns), not just the number of negative days.
    downside = math.sqrt(sum((r - rf_d) ** 2 if r < rf_d else 0.0 for r in rs) / len(rs))
    sortino = (statistics.fmean(rs) - rf_d) / downside * math.sqrt(TRADING_DAYS) if downside > 0 else 0.0

    # Omega: workbook BG80:BG83.
    omega_num = sum((r - rf_d) for r in rs if r > rf_d)
    omega_den = sum((rf_d - r) for r in rs if r < rf_d)
    omega = omega_num / omega_den if omega_den > 0 else (10.0 if omega_num > 0 else 0.0)

    # Beta: workbook B466:B468 uses population covariance / population variance.
    var_b = _variance_p(rb)
    beta = _covariance_p(rs, rb) / var_b if var_b > 0 else 0.0

    # CAGR: workbook Q38:Q42 and Q26:Q30 uses n = COUNT / 252.
    cagr_s = _cagr(rs)
    cagr_b = _cagr(rb)

    # Jensen: workbook Q465:Q469.
    jensen_decimal = cagr_s - (rf_y + beta * (cagr_b - rf_y))

    # Treynor: workbook AS466:AS470.
    treynor = (cagr_s - rf_y) / beta if abs(beta) > 1e-15 else 0.0

    # Information Ratio: workbook BG149:BG152. Active returns are matched by date;
    # STDEV is sample and then annualized by sqrt(252).
    active = [s - b for s, b in zip(rs, rb)]
    active_sd = _sample_std(active)
    information = statistics.fmean(active) / active_sd * math.sqrt(TRADING_DAYS) if active_sd > 0 else 0.0

    # Calmar: workbook AE184:AE186 = strategy CAGR / strategy max drawdown.
    mdd = _max_drawdown(rs)
    calmar = cagr_s / mdd if mdd > 0 else 0.0

    result = {
        "beta": beta,
        "sharpe": sharpe,
        "sortino": sortino,
        # HTML/BullAware displays Jensen's alpha as percentage points.
        "jensen": jensen_decimal * 100.0,
        "omega": omega,
        "treynor": treynor,
        "information": information,
        "calmar": calmar,
        "strategyCagr": cagr_s,
        "benchmarkCagr": cagr_b,
        "maxDrawdown": mdd,
        "observations": float(n),
        "riskFreeAnnual": rf_y,
        "riskFreeDaily": rf_d,
    }
    result["score"] = _estimated_score(result)
    return {k: (round(v, 10) if math.isfinite(v) else 0.0) for k, v in result.items()}


def _period_start(label: str, end: date) -> date | None:
    if label == "Year to date":
        return date(end.year, 1, 1)
    years = {"Last Year": 1, "Last 2 Years": 2, "Last 3 Years": 3, "Last 5 Years": 5}.get(label)
    if years is None:
        return None
    try:
        return end.replace(year=end.year - years)
    except ValueError:
        return end.replace(year=end.year - years, month=2, day=28)


def _period_rows(pairs: list[tuple[date, float, float]], label: str) -> list[tuple[date, float, float]]:
    if not pairs or label == "All Time":
        return pairs[:]
    start = _period_start(label, pairs[-1][0])
    if start is None:
        return pairs[:]
    return [row for row in pairs if row[0] >= start]


def period_metrics(data: dict[str, Any]) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    username = os.getenv("ETORO_USERNAME", "thomaspj").strip() or "thomaspj"
    risk_free = float(os.getenv("RISK_FREE_ANNUAL", "0") or 0.0)
    end = datetime.now(timezone.utc).date()
    start = _guess_start(data)

    strategy = fetch_strategy_daily(username, start, end)
    benchmark, benchmark_source = fetch_benchmark_daily(start, end)

    # The workbook compares strategy and benchmark on the same market-day calendar.
    # Intersecting the dates also removes weekend/holiday zero rows returned by some
    # daily-performance feeds.
    common = sorted(set(strategy).intersection(benchmark))
    pairs = [(dt, strategy[dt], benchmark[dt]) for dt in common]
    if len(pairs) < 3:
        raise RuntimeError(
            f"Too few common strategy/S&P500 daily observations: strategy={len(strategy)}, "
            f"benchmark={len(benchmark)}, common={len(pairs)}"
        )

    result: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for label in PERIODS:
        rows = _period_rows(pairs, label)
        counts[label] = len(rows)
        if len(rows) < 3:
            result[label] = {k: 0.0 for k in ("score", "beta", "sharpe", "sortino", "jensen", "omega", "treynor", "information", "calmar")}
            continue
        result[label] = excel_metrics(
            [row[1] for row in rows],
            [row[2] for row in rows],
            risk_free,
        )

    meta = {
        "formulaSource": "analisi.xlsx / Metric calculation",
        "strategySource": "eToro /user-info/people/{username}/daily-gain (Daily)",
        "benchmarkSource": benchmark_source,
        "benchmark": "S&P 500 (^GSPC)",
        "riskFreeAnnual": risk_free,
        "periodsPerYear": 252,
        "commonStart": pairs[0][0].isoformat(),
        "commonEnd": pairs[-1][0].isoformat(),
        "commonObservations": len(pairs),
        "observationsByPeriod": counts,
    }
    print("Excel-formula performance metrics:", json.dumps(result, ensure_ascii=False, sort_keys=True))
    print("Excel-formula metrics metadata:", json.dumps(meta, ensure_ascii=False, sort_keys=True))
    return result, meta
