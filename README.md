# gta6-twitch-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/diki965/gta6-twitch-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/diki965/gta6-twitch-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecast GTA VI's launch-day Twitch viewers hour by hour: `main.py` (Python 3.13, standard library only) reads each case in `$MAKEFUN_INPUT_DIR` (else `/input/`) and writes `/output/<id>.out` — five quantiles of Twitch viewers for each of hours 2–24 of the release day, from the hour-1 print and the case's comparable launches. Entry for the [make.fun bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01) "Forecast GTA VI's launch-day Twitch viewers hour by hour".

## Run it

```sh
python3 main.py
```

`main.py` (Python 3.13, standard library only) reads each case in
`$MAKEFUN_INPUT_DIR` (else `/input/`) and writes `/output/<id>.out`:
five quantiles of Twitch viewers for each of hours 2–24 of the
release day, from the hour-1 print and the case's comparable launches.

## Approach

Past big launches are the whole signal. For every comparable launch
the program builds its release-day curve (hourly viewers, hours 1–24)
and, for each hour `h`, regresses the log-ratio `ln(viewers_h /
viewers_1)` on the launch's log hour-1 size. Two facts in those curves
drive the design:

1. **A common day shape, in UTC hours.** Lined up by UTC hour,
   launch days dip in the small hours, climb to a peak around hours
   19–21 (US evening), then fall. The shape is cleanest for launches
   that unlocked at local midnight, rolling timezone by timezone —
   which is how GTA VI and all four practice launches unlock.
2. **Bigger hour 1 ⇒ flatter day.** The fitted slope on log hour-1
   size runs from ≈ 0 at hour 2 to ≈ −0.9 at hours 19–21. A launch
   already at 300k viewers at 00:00 UTC has most regions awake and
   watching; one at 25k still has its whole day ahead of it. So the
   forecast is a per-hour regression on log hour-1 size, not one
   pooled median curve.

**Training pool.** Only comparables that look like the target: a
rolling local-midnight unlock, or console-only platforms (no PC).
Simultaneous global unlocks and PC-first launches have a different
hour 1 (often a pre-unlock trickle) and poison the fit. On
leave-one-out tests over the 37 comparable launch curves, the
restricted pool (14 launches) beat training on all 37 by a wide
margin; weighting the others in instead of excluding them was worse
still.

**Spread.** Each hour's residual standard deviation from its
regression, used as a normal log-spread (scale 1.0, untuned). That
gives honest quantiles — 0.891 coverage at 90% on the practice cases
— instead of the house baseline's fixed `0.15·sqrt(h−1)` widening.

**v2: the clamp is extended, the ratio floor is gone.** This is the
second entry; v1 is the previous commit. GTA VI's hour-1 print will
almost certainly sit far above the largest comparable (387k), and
v1's hard clamp to the pool's log-range would freeze the forecast at
the biggest launch's fitted position, over-forecasting the peak (at a
synthetic hour-1 print of 1,000,000 v1 puts the hour-20 median at
1.46× hour 1; the pool's two biggest launches actually peaked at
1.16× and 1.34×). So v2 clamps log hour-1 size to the pool's range
extended by half the pool's log-range on each side (fitted position
capped at pool-max + ~2.05 log units, ≈ 3.0M viewers) and drops the
fitted-ratio floor, which was inert in-range and cost 0.0012 under
extrapolation. On a leave-out-the-3-largest-launches test the
extension cuts the loss from 0.2890 to 0.2555 (−11.6%); in-range it
costs nothing (practice cases identical, leave-one-out 0.2453 vs
0.2460).

**Things tried that did not help.** A plain median log-ratio curve
across all comparables; empirical per-hour quantiles of the ratios;
weighting comparables by closeness of hour-1 size; adding the
pre-release history jump (`ln(p1 / pre-midnight mean)`) as a second
regressor; kernel weighting by log hour-1 distance; nearest-neighbour
empirical quantiles; ensembles with the pooled median curve; recency
weighting; a rolling-only pool (won the 4 practice cases but lost
leave-one-out badly); Student-t and empirical residual shapes;
per-hour spread tuning; asymmetric spreads; dropping the outlier
launch (Resident Evil Requiem) — all worse on leave-one-out tests
and/or the practice cases, or within noise, so none of them is in
the program. Smoothing the fitted curve across hours changed
nothing.

**Guardrails.** Log hour-1 size is clamped to the pool's range
extended by half that range on each side (see above), so an hour-1
print far outside past launches still gets a bounded, sane forecast.
Any unexpected input anywhere falls back to the house persistence
forecast, and every output row is clamped to (0, 1e9] and
non-decreasing and re-checked before writing, so the program cannot
emit an invalid forecast file. It is fully deterministic (no
randomness, no time or dict-order dependence) and runs in ~0.05 s
per case.

## Practice results

`grade-local` cannot grade this kit locally — it reports *"its scorer
and reference data are not published in the kit, so it is graded on
the server only"* — so the practice answers were reconstructed from
the public source the kit names (SullyGnome hourly averages, per
`input/NOTICE.txt`), cross-validated against each case file's own
`history_hourly` tail, which matches the fetched values exactly at
every overlapping hour. That reconstruction is confirmed correct by
the baseline: the house starter scored on it gives loss **0.387**,
typical miss **82.7%**, coverage **0.783** — the competition's stated
**0.387 / 82.8% / 0.783**.

| case | launch | baseline loss | v1 | v2 (this entry) |
|------|--------|---------------|----|-----------------|
| p00 | Marvel's Wolverine | 0.7437 | 0.2588 | 0.2588 |
| p01 | Red Dead Redemption 2 | 0.2868 | 0.1430 | 0.1430 |
| p02 | God of War Ragnarök | 0.2146 | 0.1268 | 0.1268 |
| p03 | Marvel's Spider-Man 2 | 0.3033 | 0.1986 | 0.1986 |
| **pooled** | | **0.3871** | **0.1818** | **0.1818** |

Pooled: **loss 0.1818** (vs 0.3871 baseline, −53%), typical miss
**29.3%** (vs 82.7%), 90% coverage **0.891** (vs 0.783), all 4 cases
valid, ~0.17 s for all 4 cases. Leave-one-out over the comparable
launches (rolling-midnight test set) agrees: baseline 0.3925 vs this
model 0.279. The practice outputs are byte-identical to v1's — the
v2 change only acts when the hour-1 print leaves the pool's range,
which no practice case does. Where v2 differs is the regime the
final lives in: leave-out-the-3-largest-launches, loss **0.2555**
vs v1's **0.2890**.

The hardest case is p00 (Wolverine, peak 9.1× its hour-1 print —
hour 1 is a midday trough in NZ/Australia); the spread, not the
median, is what covers such launches, which is why the spread is
kept at its honest fitted value rather than tuned down.

---

<sub>Entered on [make.fun](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
