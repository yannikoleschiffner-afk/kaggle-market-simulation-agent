from typing import Dict, Any
from m1_state_core import scan_enemy, demand_drain_rate
from m6_plan_genome import consult as genome_consult

FIB_SEQ = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377]

# ── Herd targets ────────────────────────────────────────────────────────────
# Winner replay (136k): 7 cows + 13 sheep, bought from day 0, scaled by day 11.
# We scale against the shop draw: wool only pays with Yarn Stores, milk pays
# almost always (Pizza/IceCream/Smoothie are common draws).
HERD_COWS_MAX = 7
HERD_SHEEP_BY_YARN = {0: 0, 1: 5, 2: 11, 3: 15, 4: 18}

DAY0_COWS = 2            # the pre-reveal bet — the d3 draw decides the ramp (the 99646243 lesson: the full 3 on a no-milk draw = the d4 bankruptcy)
DAY0_SHEEP = 2

# ── Tunable knobs (the evolve.py search space) ───────────────────────────────
COW_BASE = 4            # the cow target baseline from the d6 gate (the 3 was under-committing: the new losses had the opponents at the 8-9 cows vs our 5 on the milk draws)
COW_PER_MILK = 3.0      # the cow target per the milk shop (the the 2.5 left the milk draws under-herded)
COW_PREGATE = 3         # the cow cap before the d6 gate
STRAW_RATE = 5          # the strawberries/day
MELON_TOTAL = 16        # the total melon plants (the the winners' d10 harvest spike: the 2.8x the cash gap)
HIRE_D0 = 5             # the max hires on the d0-1 (the the wheat rush funds the extra hand)
CAP_PLANTS = 60         # the plantable cap
WHEAT_TARGET_MULT = 1.0 # the wheat target = max(6, mouths * this)

def _daily_hire_cost(num_hands):
    return sum(FIB_SEQ[i] for i in range(num_hands))

class SolverBackend:
    pass

class ScipyMacroLP(SolverBackend):
    def __init__(self, adversarial=False):
        self.prev_solution = None
        self.adversarial = adversarial

    def solve(self, state: Dict[str, Any], horizon_days: int):
        day = state["day"]
        me = state["farms"][state["player"]]
        money = me["money"]
        unlocked = len(me.get("unlocked_quadrants", ["NW"]))

        num_cows = 0; num_sheep = 0; num_geese = 0; num_animals = 0; num_plants = 0
        num_wheat_planted = 0; num_straw_planted = 0; num_melon_planted = 0
        num_carrot_planted = 0
        for row in me["tiles"]:
            for t in row:
                if isinstance(t, dict):
                    if t.get("animal") == "COW": num_cows += 1; num_animals += 1
                    elif t.get("animal") == "SHEEP": num_sheep += 1; num_animals += 1
                    elif t.get("animal") == "GOOSE": num_geese += 1; num_animals += 1
                    elif t.get("animal"): num_animals += 1
                    elif t.get("kind") == "PLANT":
                        num_plants += 1
                        c = t.get("crop")
                        if c == "WHEAT": num_wheat_planted += 1
                        elif c == "STRAWBERRY": num_straw_planted += 1
                        elif c == "MELON": num_melon_planted += 1
                        elif c == "CARROT": num_carrot_planted += 1

        cows_in_shed = state.get("private", {}).get("shed", {}).get("COW", 0)
        sheep_in_shed = state.get("private", {}).get("shed", {}).get("SHEEP", 0)
        geese_in_shed = state.get("private", {}).get("shed", {}).get("GOOSE", 0)
        total_cows = num_cows + cows_in_shed
        total_sheep = num_sheep + sheep_in_shed
        total_geese = num_geese + geese_in_shed

        # ── Shop draw ──
        shops = state.get("town", {}).get("unlocked_shops", [])
        drain = demand_drain_rate(state)
        yarn = sum(1 for s in shops if s == "YARN_STORE")
        milk_shops = sum(1 for s in shops if s in ("PIZZA_SHOP", "ICE_CREAM_SHOP", "SMOOTHIE_SHOP"))
        pet_cafes = sum(1 for s in shops if s == "PET_CAFE")
        # The cows pay with the milk demand. The expert's delayed step-ramp:
        # the baseline 3 through the d5 (the liquidity phase — the 5+ cows
        # crash the milk floor on the milk-less draws), then the d6 gate:
        # the +3 per the visible milk shop, the confirmed-milkless collapse.
        # The +1-tuning won the suite but the -14k Pratik regression was the
        # early 5-cow baseline buying into the no-demand market.
        if day <= 5:
            # The pre-gate cows only if the d3 reveal shows milk demand;
            # on the no-milk draws the d0 insurance cow is the ceiling.
            cows_target = COW_PREGATE if milk_shops >= 1 else 1
        elif milk_shops == 0 and day >= 9:
            cows_target = 2
        else:
            cows_target = min(13, COW_BASE + COW_PER_MILK * milk_shops)
        if milk_shops == 0 and day >= 9:
            cows_target = 2
        sheep_target = HERD_SHEEP_BY_YARN.get(min(yarn, 4), 0)
        # The competitive response: the wool demand is shared. The joint flock
        # must stay below the drain capacity — but the drain scales with the
        # yarn count, so the reduction is only correct for the 0-2 yarn draws.
        # On the 3-yarn draws (the drain 37/day) the full 13 sheep each still
        # sells at the premium (the winner's $72k wool games).
        enemy = scan_enemy(state)
        enemy_sheep = enemy.get("animals", {}).get("SHEEP", 0)
        if enemy_sheep >= 5 and yarn <= 2:
            sheep_target = max(2, sheep_target - (enemy_sheep - 5))
        # The enemy cow reaction: the shared milk floor. When the opponent's
        # already flooding the milk, our cows buy into the crash — the trim.
        enemy_cows = enemy.get("animals", {}).get("COW", 0)
        if enemy_cows >= 7:
            cows_target = max(2, cows_target - 2)
        bakeries = sum(1 for s in shops if s == "BAKERY")
        brunches = sum(1 for s in shops if s == "BRUNCH_SPOT")
        # The egg demand = the bakeries + the brunch spots (the the rulebook's
        # SHOPS table). The 1+1 combos were getting zero geese (the the 3/5 of
        # the new losses) — the egg shops count together now.
        egg_shops = bakeries + brunches
        geese_target = min(8, egg_shops * 3) if egg_shops >= 2 else 0

        # ── The plan genome override (the evolve_plans search) — the delta
        # semantics: the nudges on top of the hand-coded targets, the clamped.
        # The enemy state feeds the reactive conditions.
        genome = genome_consult(day, milk_shops, yarn, money, {
            'sheep': enemy.get('animals', {}).get('SHEEP', 0),
            'cows': enemy.get('animals', {}).get('COW', 0),
            'plants': enemy.get('plants', 0),
        })
        if genome:
            cows_target = max(0, min(14, cows_target + genome.get('cow_delta', 0)))
            sheep_target = max(0, min(20, sheep_target + genome.get('sheep_delta', 0)))
            geese_target = max(0, min(8, geese_target + genome.get('goose_delta', 0)))

        # ── Animals: the daily buy plan (up to 2 per type). The m5 executes the
        # buys the moment the cash appears (the sell-to-fund flow). ──
        buy_animal = {}
        cow_ok = day <= 17
        sheep_ok = day <= 21
        goose_ok = day <= 12
        if cow_ok and total_cows < cows_target:
            cap = 5 if milk_shops >= 4 else (4 if milk_shops >= 3 else 3)
            want = min(cap, cows_target - total_cows)
            buy_animal["COW"] = want
        if sheep_ok and total_sheep < sheep_target:
            cap = 3 if yarn >= 2 else 2
            buy_animal["SHEEP"] = min(cap, sheep_target - total_sheep)
        if goose_ok and total_geese < geese_target:
            buy_animal["GOOSE"] = min(2, geese_target - total_geese)
        # Day 0: the fixed opening herd (the winner's exact bet).
        if day == 0:
            buy_animal["COW"] = min(3, max(0, DAY0_COWS - total_cows))
            buy_animal["SHEEP"] = min(2, max(0, DAY0_SHEEP - total_sheep))

        # ── Land (the m5 buys when the cash allows; day-gated here) ──
        # Real prices: LAND_PRICES = [1000, 2000, 4000]. The top bots never buy
        # the 4th quadrant — the 75-tile field is the waterable capacity, and
        # over-expansion is what kills the far plants.
        buy_land = 0
        if unlocked == 1 and day >= 2:
            buy_land = 1
        elif unlocked == 2 and day >= 5:
            buy_land = 1
        if genome and 'land' in genome:
            buy_land = genome['land']

        # ── Labor ramp: 4 → 12 by day ~11 (fib burn must stay fundable) ──
        mouths = num_animals + cows_in_shed + sheep_in_shed + geese_in_shed
        max_hires_by_day = 12
        if day <= 1: max_hires_by_day = HIRE_D0
        elif day <= 3: max_hires_by_day = 6
        elif day <= 5: max_hires_by_day = 8
        elif day <= 7: max_hires_by_day = 9
        elif day <= 9: max_hires_by_day = 10
        elif day <= 11: max_hires_by_day = 11
        if genome and 'hire_delta' in genome:
            max_hires_by_day = min(12, max(2, max_hires_by_day + genome['hire_delta']))

        wheat_seed_cost = 10
        mandatory_daily_seed_cost = max(0, mouths) * wheat_seed_cost
        hires = 0
        for h in range(1, max_hires_by_day + 1):
            daily_burn = _daily_hire_cost(h) + mandatory_daily_seed_cost
            if money >= (daily_burn * 2) + 300:
                hires = h
            else:
                break
        if hires < min(4, max_hires_by_day) and money >= 50:
            hires = min(4, max_hires_by_day)
        # The env fires every hand at midnight, so the daily hire count must be
        # monotonic — a money dip must never shrink the workforce (the wage for
        # the existing hands is already committed).
        prev = getattr(self, "prev_hires", 0)
        if day < 28:
            hires = max(hires, prev)
        self.prev_hires = hires

        # ── Wheat feed reserve: 3 days of feed, at the live market price ──
        # (The m5 recomputes this per turn with the live shed state; this
        #  decision slot is kept for interface compatibility but left empty.)
        buy_wheat = 0

        # ── Planting ──
        total_tiles = (unlocked * 25) - 4
        if genome:
            melon_total = max(2, min(24, MELON_TOTAL + genome.get('melon_delta', 0)))
            straw_rate = max(0, min(12, STRAW_RATE + genome.get('straw_delta', 0)))
        else:
            melon_total = MELON_TOTAL
            straw_rate = STRAW_RATE
        # Reserve only the CURRENT herd + a small pipeline headroom; the fields
        # fill the rest. The late game (the d20+): the herd's done growing, the
        # reserve drops to zero and the wheat flood takes the full board.
        if day >= 20:
            reserved_for_animals = 0
        else:
            reserved_for_animals = min(14, total_cows + total_sheep + 3)
        plantable = max(0, total_tiles - reserved_for_animals - num_animals - num_plants)
        # The waterable cap: ~40 tiles is what the 12-worker crew can water
        # daily. Over-planting beyond it is how the far tiles starve and die.
        plantable = min(plantable, max(0, CAP_PLANTS - num_plants))
        # The genome's direct field-density lever: the full-freedom knob that
        # lets the evolution push toward the full 75-tile utilization (the the
        # top bots fill the every purchased tile) paired with the hire_delta.
        if genome and 'plantable_delta' in genome:
            plantable = max(0, plantable + genome['plantable_delta'])

        plant = {}
        if plantable > 0:
            if day <= 1:
                # The wheat rush opening: the 2-day wheat pays the d2-3 and
                # compounds into the herd + the fields (the the winners' d14
                # cash lead). The melons follow the d4-6 batch.
                melon_goal = max(0, 5 - num_melon_planted)
                wheat_goal = max(0, 18 - num_wheat_planted)
                melon_take = min(plantable, melon_goal)
                wheat_take = min(plantable - melon_take, wheat_goal)
                if melon_take > 0:
                    plant["MELON"] = melon_take
                if wheat_take > 0:
                    plant["WHEAT"] = wheat_take
            elif day <= 9:
                # Strawberries (the ongoing crop engine) + wheat feed.
                # The wheat surplus engine (the 101471086 lesson): the top bots
                # export the wheat daily (the the d8: the 15 wheat sold) while we
                # import it just to feed. The +6 surplus per cycle funds the d8-14
                # cash gap.
                wheat_target_total = max(12, mouths + 6)
                wheat_need = max(0, min(plantable - 3, wheat_target_total - num_wheat_planted))
                straw_need = max(0, plantable - wheat_need)
                # The carrots: the 2-day fast cash for the strong Pet Cafe
                # draws (2+ shops). Taken from the wheat share when it exists,
                # else from the strawberries.
                if pet_cafes >= 1 and day >= 8:
                    carrot_take = min(wheat_need if wheat_need > 0 else straw_need, 6)
                    if wheat_need > 0:
                        wheat_need -= carrot_take
                    else:
                        straw_need -= carrot_take
                    if carrot_take > 0:
                        plant["CARROT"] = carrot_take
                if straw_need > 0:
                    plant["STRAWBERRY"] = straw_need
                if wheat_need > 0:
                    plant["WHEAT"] = wheat_need
                # Second melon batch (the winner's d6-8 melons): the mid-game cash.
                if 5 <= day <= 7 and num_melon_planted < melon_total:
                    melon_extra = min(plantable, melon_total - num_melon_planted, 4)
                    if melon_extra > 0:
                        plant["MELON"] = melon_extra
                # The third melon batch (the live meta: the ~60-72 units at
                # the ~$230 — the ~2-3/day paced into the town drain keeps
                # the price; the +$8-11k per the game).
                if 9 <= day <= 14 and num_melon_planted < melon_total:
                    melon_extra = min(plantable, 20 - num_melon_planted, 2)
                    if melon_extra > 0:
                        plant["MELON"] = melon_extra
            elif day <= 25:
                # Wheat-dominant phase riding the town drain; strawberries while
                # they still pay (the d13-19 plants yield 1-2 productions, still
                # ~2-3x the wheat per the tile).
                if day <= 12:
                    # The d10-12 push: the strawberries planted here still reach
                    # the 2 productions (the the ~$120/tile) — the field must
                    # not idle at the 5/day crawl.
                    straw_take = min(plantable, max(int(straw_rate), 8))
                elif day <= 16:
                    # The expert's stop-day: the strawberries need the 10 days
                    # to the first yield — the d17+ plants never reach the
                    # second production. The wheat takes the tiles instead.
                    straw_take = min(plantable, int(straw_rate))
                else:
                    straw_take = 0
                plant["STRAWBERRY"] = straw_take
                wheat_take = plantable - straw_take
                if pet_cafes >= 1 and 8 <= day <= 20:
                    carrot_take = min(wheat_take, 4)
                    wheat_take -= carrot_take
                    if carrot_take > 0:
                        plant["CARROT"] = carrot_take
                plant["WHEAT"] = wheat_take
            else:
                plant["WHEAT"] = plantable

        plant = {k: v for k, v in plant.items() if v > 0}

        decisions = {
            "plant": plant,
            "buy_animal": buy_animal,
            "buy_wheat": buy_wheat,
            "hires": hires,
            "buy_land": buy_land
        }
        self.prev_solution = decisions
        return decisions, 5.0, 8.0, 1.0, {}

def get_planner(adversarial=False):
    return ScipyMacroLP(adversarial=adversarial)
