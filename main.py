"""Forecast a launch day's hourly Twitch viewers from its first hour.

Approach: launch-day curves from past big releases (the case's
`comparables`) are the whole signal.  For each past launch I take the
log-ratio of each later hour's viewers to that launch's hour-1 print,
and regress that ratio on the launch's (log) hour-1 size.  Two facts
from those curves drive the design:

* A launch's day has a strong common shape once you line launches up
  by UTC hour: a dip in the small hours, then a climb to a peak around
  hours 19-21 as the US evening arrives, then a fall.  The shape is
  clearest among launches that unlocked at local midnight (rolling),
  which is how the practice launches and GTA VI unlock.
* The bigger hour 1 is, the flatter the rest of the day: the fitted
  slope on log hour-1 size runs from about 0 at hour 2 to about -0.9
  at hours 19-21.  A launch that already has 300k viewers at 00:00 UTC
  has most regions awake and watching; one with 25k still has its
  whole day ahead of it.  So the forecast is a per-hour regression on
  log hour-1 size, not a single pooled median curve.

Training pool: comparables whose unlock rolled at local midnight, or
whose platforms are console-only (no PC).  Simultaneous global
unlocks and PC-first launches have a different hour-1 (often a
pre-unlock trickle) and their curves would poison the fit; on
leave-one-out tests over the comparable launches, the restricted pool
beat training on all of them by a wide margin.

Spread: the residual standard deviation of each hour's regression,
used as a normal log-spread.  That gives honest quantiles (about 0.89
coverage at 90% on the practice cases) rather than the baseline's
fixed 0.15*sqrt(h-1) widening.

Safety: the fitted log-ratio is floored at the lowest ratio that hour
ever showed in the pool, and log hour-1 size is clamped to the pool's
range, so an hour-1 print far outside past launches (GTA VI may be
one) cannot extrapolate the curve to nonsense.  Anything unexpected
anywhere falls back to the house persistence forecast, and every
output row is clamped and re-checked before it is written, so the
program can never emit an invalid forecast file.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z_SCORES = [-1.645, -0.674, 0.0, 0.674, 1.645]
HOURS = list(range(2, 25))

# Fixed widening of the house persistence forecast, used only as a
# fallback when the comparable curves cannot be used at all.
FALLBACK_SIGMA = 0.15

# How much of each hour's residual log spread the quantiles use.  Kept
# at 1.0, the untuned honest value: scaling it to 0.9 scored a hair
# better on the practice cases (0.179 vs 0.182) and on leave-one-out
# tests, but the gap is inside noise and 1.0 keeps the 90% coverage
# closest to 0.9 (0.891 on practice), which is what the final's single
# case needs if GTA VI behaves like an outlier launch.
SPREAD_SCALE = 1.0


def _parse_time(text):
    """ISO-8601 timestamp to an aware datetime; None when unparsable."""
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _round2(value):
    """Round to 2 decimals, half up, returning an int for whole numbers."""
    scaled = value * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    out = whole / 100.0
    return int(out) if float(out).is_integer() else out


def _clamp_row(values):
    """Force a row of five quantiles into (0, 1e9] and non-decreasing."""
    fixed = []
    prev = 0.0
    for value in values:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            value = prev if prev > 0 else 1.0
        value = min(max(float(value), 1.0), 1e9)
        if value < prev:
            value = prev
        fixed.append(_round2(value))
        prev = fixed[-1]
    return fixed


def _fallback_rows(p1):
    """House persistence forecast: every hour stays at the hour-1 print."""
    rows = {}
    for hour in HOURS:
        spread = FALLBACK_SIGMA * math.sqrt(hour - 1)
        rows[hour] = _clamp_row(
            [p1 * math.exp(z * spread) for z in Z_SCORES]
        )
    return rows


def _release_day_curve(comparable):
    """{hour 1..24: viewers} for a comparable's release day, or {}.

    A point counts only when it lands on one of the 24 whole hours of
    the comparable's release day and its viewer count is positive.
    """
    day_start = _parse_time(comparable.get("day_start"))
    if day_start is None:
        return {}
    curve = {}
    for point in comparable.get("hourly") or []:
        if not isinstance(point, dict):
            continue
        viewers = point.get("viewers")
        if not isinstance(viewers, (int, float)) or viewers <= 0:
            continue
        when = _parse_time(point.get("from"))
        if when is None:
            continue
        hour = int((when - day_start).total_seconds() // 3600) + 1
        if 1 <= hour <= 24:
            curve[hour] = float(viewers)
    return curve


def _is_similar(comparable):
    """True for launches shaped like a rolling-midnight console launch.

    Rolling local-midnight unlocks share the UTC-day shape this contest
    scores (GTA VI and every practice launch unlock that way); console
    only launches share the audience that watches at console hours.
    A launch counts when it matches either test.
    """
    unlock = str(comparable.get("unlock") or "").lower()
    rolling = ("midnight local" in unlock or "rolling" in unlock) and (
        "simultaneous" not in unlock and "single global" not in unlock
    )
    platforms = str(comparable.get("platforms") or "").lower()
    console_only = "pc" not in platforms
    return rolling or console_only


def _fit_hour(curves, hour, log_p1):
    """Fit log-ratio at one hour against log hour-1 size.

    Returns (median log-ratio, residual log sd) for this hour, or None
    when too few curves carry the hour.
    """
    xs = []
    ys = []
    for curve in curves:
        if hour in curve and 1 in curve:
            xs.append(math.log(curve[1]))
            ys.append(math.log(curve[hour] / curve[1]))
    if len(xs) < 5:
        return None
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    slope = 0.0
    if denom > 0:
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    intercept = mean_y - slope * mean_x
    clamped = min(max(log_p1, min(xs)), max(xs))
    median = intercept + slope * clamped
    floor = min(ys)
    if median < floor:
        median = floor
    if n > 2:
        resid_sq = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
        sd = math.sqrt(resid_sq / (n - 2))
    else:
        sd = 0.15
    if sd <= 0:
        sd = 0.15
    return median, sd


def _model_rows(case, p1):
    """Forecast rows from the comparable launch curves."""
    curves = []
    for comparable in case.get("comparables") or []:
        if not isinstance(comparable, dict):
            continue
        curve = _release_day_curve(comparable)
        if 1 in curve and sum(1 for h in HOURS if h in curve) >= 20:
            curves.append((comparable, curve))
    if len(curves) < 3:
        return None
    similar = [curve for comparable, curve in curves if _is_similar(comparable)]
    pool = similar if len(similar) >= 5 else [curve for _, curve in curves]
    if len(pool) < 5:
        return None
    log_p1 = math.log(p1)
    rows = {}
    for hour in HOURS:
        fit = _fit_hour(pool, hour, log_p1)
        if fit is None:
            return None
        median, sd = fit
        rows[hour] = _clamp_row(
            [p1 * math.exp(median + z * sd * SPREAD_SCALE) for z in Z_SCORES]
        )
    return rows


def _hour1_print(case):
    """Hour-1 viewers from the case's known rows, at least 1."""
    for row in case.get("known") or []:
        if isinstance(row, dict) and row.get("hour") == 1:
            viewers = row.get("viewers")
            if isinstance(viewers, (int, float)) and viewers > 0:
                return float(viewers)
    known = case.get("known") or []
    if known and isinstance(known[0], dict):
        viewers = known[0].get("viewers")
        if isinstance(viewers, (int, float)) and viewers > 0:
            return float(viewers)
    return 1.0


def forecast_case(case):
    """One case's forecast dict, always valid, model or fallback."""
    p1 = _hour1_print(case)
    try:
        rows = _model_rows(case, p1)
    except Exception:
        rows = None
    if rows is None:
        rows = _fallback_rows(p1)
    wanted = []
    for row in case.get("forecast") or []:
        if isinstance(row, dict) and isinstance(row.get("hour"), int):
            wanted.append(row["hour"])
    wanted = [h for h in wanted if 2 <= h <= 24]
    if len(wanted) != 23 or sorted(wanted) != HOURS:
        wanted = list(HOURS)
    hours = []
    for hour in wanted:
        quantiles = rows.get(hour)
        if quantiles is None or len(quantiles) != 5:
            quantiles = _fallback_rows(p1)[hour]
        hours.append({"hour": hour, "q": _clamp_row(quantiles)})
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            forecast = forecast_case(case)
        except Exception:
            forecast = {
                "hours": [
                    {"hour": hour, "q": [1.0, 1.0, 1.0, 1.0, 1.0]}
                    for hour in HOURS
                ]
            }
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
