"""gta6-twitch-ccu-forecast-01 entry: an empirical launch-day forecaster.

Idea: the case file carries dozens of past big game launches (comparables),
each with hourly Twitch viewers from 14 days before its release day to 3 days
after. A launch day has a characteristic shape once it is scaled by its own
first hour: a morning climb as the big regions unlock, a long peak, a slow
overnight decay. This program reads that shape off the comparables directly:
for every hour h of the day it pools log(viewers_h / viewers_1) over the
comparables, weighting each one by how close its own hour-1 audience is to
this case's (a launch that opened to a similar crowd moves like this one;
one a hundred times smaller does not), and takes the five scored quantiles
of that weighted pool as the forecast's shape for hour h, anchored on this
case's hour-1 print. Leave-one-out scoring over the comparables themselves
put the best weight width at 0.8 log units and the weighted pool well ahead
of both the flat pool and the persistence baseline. No randomness: the same
case always writes the same forecast, byte for byte.

Runs as `python3 -P -s /bot/main.py` (Python 3.13, standard library only, no
network): reads every <id>.in in $MAKEFUN_INPUT_DIR (else /input) and writes
<id>.out to $MAKEFUN_OUTPUT_DIR (else /output) in the contest's exact shape.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Fallback spread (the house baseline's) for an hour the comparables cannot
# speak about: quantiles of the standard normal at the scored levels.
Z = [-1.645, -0.674, 0, 0.674, 1.645]
SIGMA = 0.15


def parse_ts(text: str) -> float:
    """ISO 8601 UTC timestamp to epoch seconds."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def day_series(comp: dict) -> dict:
    """A comparable's release-day hourly viewers, keyed by hour 1..24."""
    try:
        start = parse_ts(comp["day_start"])
    except (KeyError, TypeError, ValueError):
        return {}
    series = {}
    for point in comp.get("hourly") or []:
        viewers = point.get("viewers")
        if viewers is None:
            continue
        try:
            idx = int((parse_ts(point["from"]) - start) // 3600) + 1
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= idx <= 24:
            series[idx] = max(1.0, float(viewers))
    return series


def quantile(sorted_vals: list, tau: float) -> float:
    """The tau quantile of a sorted list, linear interpolation (type 7)."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = tau * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] * (1 - (pos - lo)) + sorted_vals[hi] * (pos - lo)


# Width of the scale-similarity weight, in log units of hour-1 viewers:
# a comparable whose first hour drew e^0.8 (about 2.2x) more or fewer viewers
# than this case counts e^-1 (about 0.37) as much. Tuned by leave-one-out
# scoring over the comparables in the practice cases.
WEIGHT_WIDTH = 0.8


def weighted_quantile(pairs: list, tau: float) -> float:
    """The tau quantile of (value, weight) pairs, linear on cumulative weight."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return pairs[len(pairs) // 2][0]
    target = tau * total
    acc = 0.0
    for i, (value, weight) in enumerate(pairs):
        acc += weight
        if acc >= target:
            if i == 0:
                return value
            prev_value = pairs[i - 1][0]
            frac = (target - (acc - weight)) / weight if weight > 0 else 0.0
            return prev_value + (value - prev_value) * frac
    return pairs[-1][0]


def forecast_case(case: dict) -> dict:
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError("case has no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))

    # Pool the log ratio of every later hour to hour 1 over all comparables,
    # each weighted by the closeness of its own hour 1 to this case's.
    pool = {h: [] for h in range(2, 25)}
    log_p1 = math.log(p1)
    for comp in case.get("comparables") or []:
        series = day_series(comp)
        if 1 not in series:
            continue
        base = series[1]
        weight = math.exp(-abs(math.log(base) - log_p1) / WEIGHT_WIDTH)
        for h in range(2, 25):
            if h in series:
                pool[h].append((math.log(series[h] / base), weight))

    hours = []
    for row in case["forecast"]:
        h = row["hour"]
        pairs = pool.get(h, [])
        if len(pairs) >= 5:
            qs = [p1 * math.exp(weighted_quantile(pairs, tau)) for tau in LEVELS]
        else:
            qs = [p1 * math.exp(z * SIGMA * math.sqrt(h - 1)) for z in Z]
        qs = [max(1e-6, q) for q in qs]
        for i in range(1, 5):
            qs[i] = max(qs[i], qs[i - 1])
        hours.append({"hour": h, "q": [round(q, 2) for q in qs]})
    return {"hours": hours}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        out = json.dumps(forecast, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
