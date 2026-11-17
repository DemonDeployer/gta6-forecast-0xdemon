"""Launch-day Twitch viewer forecaster for gta6-twitch-ccu-forecast-01.

Idea in one paragraph: an hour's viewer count is forecast as the case's own
hour-1 print scaled by a typical launch-day shape.  The shape comes from the
case itself: for every past launch bundled in the case, take the ratio of that
launch's viewers in hour h to its viewers in hour 1.  Past launches are not
all equally informative about a new launch, though: a launch that opened to a
similar-sized first hour behaves far more like the new game than one that
opened a hundred times smaller, so each past launch is weighted by how close
its own hour-1 count sits to this case's hour-1 print (a Gaussian weight on
the log scale).  The centre for an hour is the average of the weighted mean
and the weighted median of the log-ratios, so one runaway launch cannot drag
the curve.  The spread around that centre also comes from the launches: the
weighted spread of the log-ratios in that hour, measured with a median
absolute deviation, which stays honest when a couple of launches behave
nothing like the rest.  Quantiles are then the usual normal multipliers on
the log scale.  When a case carries too few usable past launches, the shape
falls back to staying flat at the hour-1 print with a spread that grows like
the square root of the hours elapsed.

Everything here is standard library only, deterministic, and offline: no
randomness, no clock, no network.  The same input bytes always produce the
same output bytes.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

IN_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# Normal quantiles for the five scored levels, in level order.
Z_SCORES = (-1.6448536269514722, -0.6744897501960817, 0.0,
            0.6744897501960817, 1.6448536269514722)

FIRST_HOUR = 1
LAST_HOUR = 24
MIN_LAUNCHES = 8          # need at least this many past launches per hour
KERNEL_SCALE = 2.0        # log-distance scale for size-similarity weights
MIN_EFFECTIVE = 4.0       # below this, pull the centre toward all launches
SIGMA_FLOOR = 0.20        # never claim more precision than this (log units)
SIGMA_CAP = 1.50          # never spread wider than this (log units)
FALLBACK_SIGMA = 0.15     # flat-shape spread grows with sqrt(hours elapsed)
MAX_VIEWERS = 1_000_000_000.0


def _parse_time(text):
    """ISO-8601 timestamp -> aware datetime, tolerating a trailing Z."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _weighted_mean(values, weights):
    total = sum(weights)
    return sum(w * v for w, v in zip(weights, values)) / total


def _weighted_median(values, weights):
    order = sorted(range(len(values)), key=lambda i: values[i])
    half = sum(weights) / 2.0
    running = 0.0
    for i in order:
        running += weights[i]
        if running >= half:
            return values[i]
    return values[order[-1]]


def _weighted_mad_sigma(values, weights, centre):
    """Robust spread: 1.4826 * weighted median absolute deviation."""
    deviations = [abs(v - centre) for v in values]
    return 1.4826 * _weighted_median(deviations, weights)


def _effective_n(weights):
    """(sum w)^2 / sum w^2: how many launches the weights really rest on."""
    return sum(weights) ** 2 / sum(w * w for w in weights)


def _size_weights(log_firsts, log_p1):
    """Gaussian weights: 1 for a launch that opened at this case's size,
    fading as its hour-1 count moves away on the log scale."""
    return [math.exp(-((lf - log_p1) / KERNEL_SCALE) ** 2)
            for lf in log_firsts]


def _log_ratios(case):
    """Past launches as (log hour-1 viewers, {hour: log-ratio}) pairs.

    A launch contributes to an hour only when both its hour-1 and that
    hour's counts are present and positive; launches whose release day is
    not fully covered simply contribute to fewer hours.
    """
    launches = []
    for launch in case.get("comparables") or []:
        hourly = launch.get("hourly") or []
        if not hourly:
            continue
        try:
            day_start = _parse_time(launch["day_start"])
        except (KeyError, TypeError, ValueError):
            continue
        day = {}
        for point in hourly:
            try:
                when = _parse_time(point["from"])
                viewers = point["viewers"]
            except (KeyError, TypeError, ValueError):
                continue
            if not isinstance(viewers, (int, float)) or viewers <= 0:
                continue
            hour = _hour_of(when, day_start)
            if hour is not None and hour not in day:
                day[hour] = float(viewers)
        first = day.get(FIRST_HOUR)
        if not first:
            continue
        log_first = math.log(first)
        ratios = {h: math.log(v) - log_first
                  for h, v in day.items() if h != FIRST_HOUR}
        launches.append((log_first, ratios))
    return launches


def _forecast_hours(case, p1):
    """Median log-ratio and robust spread per hour, from the past launches."""
    launches = _log_ratios(case)
    log_p1 = math.log(p1)
    curve = {}
    for hour in range(FIRST_HOUR + 1, LAST_HOUR + 1):
        pairs = [(lf, ratios[hour]) for lf, ratios in launches
                 if hour in ratios]
        if len(pairs) >= MIN_LAUNCHES:
            log_firsts = [lf for lf, _ in pairs]
            samples = [r for _, r in pairs]
            weights = _size_weights(log_firsts, log_p1)
            centre = 0.5 * (_weighted_mean(samples, weights)
                            + _weighted_median(samples, weights))
            # If the weights rest on very few launches (this case opened
            # far outside the past launches' sizes), pull the centre back
            # toward the plain median over all of them.
            ess = _effective_n(weights)
            if ess < MIN_EFFECTIVE:
                blend = ess / MIN_EFFECTIVE
                centre = (blend * centre
                          + (1.0 - blend) * _median(samples))
            spread = _weighted_mad_sigma(samples, weights, centre)
            spread = min(max(spread, SIGMA_FLOOR), SIGMA_CAP)
        else:
            centre = 0.0
            spread = FALLBACK_SIGMA * math.sqrt(hour - FIRST_HOUR)
        curve[hour] = (centre, spread)
    return curve


def _round_half_up_2dp(value):
    """Round to 2 decimals, halves away from zero, as a JSON number."""
    scaled = value * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    out = whole / 100.0
    return int(out) if float(out).is_integer() else out


def _hour_of(point_time, day_start):
    """Which release-day hour (1..24) a timestamp falls in, else None."""
    delta = point_time - day_start
    hour = int(delta.total_seconds() // 3600) + 1
    return hour if 1 <= hour <= LAST_HOUR else None


def _quantile_row(p1, centre, spread):
    """Five quantiles for one hour: median ratio times lognormal spread."""
    raw = []
    for z in Z_SCORES:
        value = p1 * math.exp(centre + z * spread)
        value = min(max(value, 0.01), MAX_VIEWERS)
        raw.append(_round_half_up_2dp(value))
    # Rounding can only move a value by a cent, so a running max restores
    # the required non-decreasing order without changing any value much.
    row = []
    floor = 0.0
    for value in raw:
        value = max(value, floor)
        row.append(value)
        floor = value
    return row


def forecast_case(case):
    """Forecast hours 2..24 of one case, in the contest's output shape."""
    known = case.get("known") or []
    first = next((k for k in known if k.get("hour") == FIRST_HOUR), None)
    if first is None:
        raise ValueError("case has no hour-1 print")
    p1 = float(first["viewers"])
    if not math.isfinite(p1) or p1 < 1:
        p1 = 1.0
    curve = _forecast_hours(case, p1)
    hours = []
    for row in case.get("forecast") or []:
        hour = row["hour"]
        centre, spread = curve[hour]
        hours.append({"hour": hour, "q": _quantile_row(p1, centre, spread)})
    hours.sort(key=lambda r: r["hour"])
    return {"hours": hours}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(IN_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_case(case)
        target = OUT_DIR / (path.stem + ".out")
        target.write_text(
            json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
