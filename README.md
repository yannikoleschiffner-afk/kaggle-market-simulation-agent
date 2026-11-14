# AI Agent for a Kaggle Market Simulation (Kaggriculture)

An autonomous agent for **Kaggriculture**, a Kaggle simulation competition (2026). Two players run competing farms for a 30-day season (720 turns), each with a farmer and hireable farm hands. They plant crops, raise animals and sell into a shared market whose prices react to supply and to the shops that unlock in town. The richest farm at the end wins.

**Result:** top 100 of 10,000+ participants in the final ranking (September 2026).

The game is hard for a simple bot: prices fall as both players sell, animals die if they are not fed, crops turn to weeds if they are not watered, hands cost a growing (Fibonacci) daily wage, and the shop draw changes which products are worth producing.

## Architecture

The agent separates *what to produce* from *who does it* and *when to sell*:

| Module | Role |
|---|---|
| `m1_state_core.py` | Exact re-implementation of the game's state transition. It is used to look ahead, read the opponent's position and lint actions before submitting them. It is fuzz-tested against the official environment (`tests/test_m1_twin.py`). |
| `m2_shadow_market.py` | Model of the market's price curves and of town demand. It gives marginal prices for selling *n* units and warns when the opponent is dumping. |
| `m3_macro_lp.py` | Daily strategic planner: herd sizes, crop mix, hires and land purchases, conditioned on the shop draw and the opponent's farm. |
| `m4_dispatcher.py` | Multi-agent task dispatcher that assigns watering, planting, harvesting, feeding and building tasks to the farmer and hands by priority tier and distance. |
| `m5_micro_trader.py` | Sell-side execution: paces sales against the price curve, holds stock for demand, liquidates in the endgame, and runs a squeeze state machine for scarce products. |
| `m6_plan_genome.py` | An evolvable rule genome that nudges the planner's parameters. It was tuned with an evolutionary search over self-play and replays. |
| `main.py` | Kaggle entry point that wires the modules together each turn. |
| `arena/` | Scripted sparring opponents (melon dumper, fertiliser crasher, pure cropper, wheat buyer) |
| `run_ladder.py` | Ladder: plays the agent against built-in and arena opponents over fixed seeds |

## Results

Local ladder (`python run_ladder.py`, 10 seeds per opponent):

| Opponent | Record | Avg. money margin |
|---|---|---|
| Kaggle `starter` | 10–0 | +118,050 |
| `random` | 10–0 | +120,341 |
| `pass` | 10–0 | +112,030 |
| `naive_melon_dumper` | 10–0 | +119,786 |
| `fertilizer_crasher` | 10–0 | +120,086 |
| `pure_cropper` | 10–0 | +118,606 |
| `wheat_buyer` | 10–0 | +110,436 |

On the live Kaggle leaderboard I used replays of losses against strong opponents to find and fix weaknesses.

## Running

```bash
pip install kaggle-environments pytest
python run_ladder.py          # ladder against all opponents
pytest tests                  # engine spec + fuzzing against the official environment
```

Single game:

```python
from kaggle_environments import make
env = make("kaggriculture", debug=True)
env.run(["main.py", "arena/pure_cropper.py"])
print([s.reward for s in env.steps[-1]])
```

## Stack

Python · kaggle-environments · simulation and fuzz testing · evolutionary parameter search
