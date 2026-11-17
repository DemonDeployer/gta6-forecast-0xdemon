# GTA VI Twitch launch-day forecaster

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/DemonDeployer/gta6-forecast-0xdemon/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/DemonDeployer/gta6-forecast-0xdemon/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day (19 November 2026, UTC), given only the first hour's
viewer count. Entry for the
[make.fun bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01).

## How it works

`main.py` (Python 3.13, standard library only, offline, deterministic) reads
one case file per run and writes five quantiles (5%, 25%, 50%, 75%, 95%) of
the viewer count for each of hours 2–24.

The forecast is anchored on the case's own hour-1 print, scaled by a
launch-day shape learned at runtime from the case's `comparables` — past big
game launches, aligned by their release-day UTC hour:

- **Median curve:** for each hour, the median across past launches of the
  ratio `viewers(hour) / viewers(hour 1)`, computed on the log scale so a
  few runaway hits cannot drag the curve. The typical shape dips in the
  early hours, then climbs steeply as the US unlocks and evening arrives,
  peaking around hours 19–20 at roughly 2.4× the first hour.
- **Spread:** the cross-launch disagreement of those log-ratios in each
  hour, measured with a median absolute deviation (robust to outlier
  launches), floored and capped so the forecast never claims false
  precision nor spreads without bound. Quantiles use the standard normal
  multipliers (−1.645, −0.674, 0, 0.674, 1.645) on the log scale.
- **Fallback:** if a case carries too few usable past launches, the shape
  stays flat at the hour-1 print with a spread growing like the square
  root of the hours elapsed.

Quantiles are clamped to (0, 1e9], kept non-decreasing, and rounded to two
decimals (half up).

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` in the input directory and writes one `*.out` per case.

## Validation

Scored locally by leave-one-out over the practice kit's 38 comparable
launches: each launch's release day is treated as a pseudo-case (its hour-1
print known, hours 2–24 forecast from the other launches, the pre-release
GTA VI category entry excluded) and scored by mean pinball loss on the log
scale, the contest's own metric. Over 37 pseudo-cases (4,255 scored items)
the shipped program scores **0.399**, against **0.930** for the house
persistence baseline on the same pseudo-cases. All four practice cases
produce valid output files in the exact required shape, deterministically
(two runs byte-identical), in ~0.25 s for all four cases.

<sub>Entered on [make.fun](https://make.fun/?ref=qamf9tkx&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
