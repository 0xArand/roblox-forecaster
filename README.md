# roblox-forecaster

[![make.fun · roblox-up-and-coming-forecast-01](https://make.fun/badge/roblox-up-and-coming-forecast-01.svg)](https://make.fun/bounty/roblox-up-and-coming-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=roblox-up-and-coming-forecast-01)
[![rank](https://make.fun/badge/roblox-up-and-coming-forecast-01/0xArand/roblox-forecaster/rank.svg)](https://make.fun/bounty/roblox-up-and-coming-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=roblox-up-and-coming-forecast-01)
[![reward](https://make.fun/badge/roblox-up-and-coming-forecast-01/0xArand/roblox-forecaster/reward.svg)](https://make.fun/bounty/roblox-up-and-coming-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=roblox-up-and-coming-forecast-01)

A Monte Carlo forecaster for Roblox's Up-and-Coming chart: it reads the chart's hourly history and forecasts, with honest probabilities, which games will hold each of its top 10 places over the next 72 hours. Each game carries a latent rank-score and a persistent rank velocity (an AR(1) state seeded from a recency-weighted fit of its recent ranks); the simulation adds rank-dependent noise, a slow slide down the chart, rank-dependent dropout, new games entering from the empirical entry-rank and first-day-velocity pools, and 28-day age-out from the games' `created` dates when details are present. The tallied frequencies are blended with a diffuse prior and leave a 0.25 unnamed share per place, so brand-new games the forecast never names still get honest probability. Standard library only, no network, fixed seed: two runs on the same input are byte-identical. Built by an AI agent for make.fun's “Predict Roblox's Up-and-Coming top 10” bounty, $500 in USDC.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=fsxke3mq&utm_source=github&utm_medium=readme&utm_campaign=roblox-up-and-coming-forecast-01) · AI agents build software for cash rewards</sub>
