from typing import Dict, Any, List, Set
import math

from turn_intents import TurnIntents
from m1_state_core import scan_enemy
from constants import (
    MARKET_I0, MARKET_PARAMS, ALL_RESOURCES,
    ENDGAME_LIQUIDATE_DAY, SHED_OVERFLOW_THRESHOLD,
    SQUEEZE_PARAMS, CROPS
)

# ── Tunable knobs (the evolve.py search space) ───────────────────────────────
PACE_DIV = 4.0           # the sell pacing: the drain / this per turn
WOOL_HOLD = 150          # the wool hold below this price (the d<25)
WHEAT_RESERVE_MULT = 2.0 # the feed reserve = the mouths * this
_BASE_KNOBS = {'PACE_DIV': PACE_DIV, 'WOOL_HOLD': WOOL_HOLD,
               'WHEAT_RESERVE_MULT': WHEAT_RESERVE_MULT}
try:
    from m6_plan_genome import consult as _genome_consult
    _HAS_GENOME = True
except ImportError:
    _genome_consult = None
    _HAS_GENOME = False

class MicroTrader:
    def __init__(self, adversarial=False):
        # Squeeze state machine per resource: DORMANT / ARMED / RELEASING / EXHAUSTED
        self.squeeze_state = {r: 'DORMANT' for r in SQUEEZE_PARAMS['hinge_resources']}
        self.squeeze_armed_day = {}
        self.squeeze_projected_peak_day = {}
        self.adversarial = adversarial
        self.trade_day = -1
        self.bought_cow = 0
        self.bought_sheep = 0
        self.bought_goose = 0
        self.bought_land = False

    def compose_orders(self, obs: Dict[str, Any], shadow_market: Any, duals: Dict[str, float], intents: TurnIntents, hires_needed: int, decisions: Dict[str, Any]) -> List[List[Any]]:
        global PACE_DIV, WOOL_HOLD, WHEAT_RESERVE_MULT
        # The genome sell-side deltas: always recompute from the bases (the the
        # no-leak pattern), applied per call.
        if _HAS_GENOME:
            g = _genome_consult(obs["day"], 0, 0, obs["farms"][obs["player"]]["money"])
            PACE_DIV = max(1.5, min(8.0, _BASE_KNOBS['PACE_DIV'] + g.get('pace_delta', 0)))
            WOOL_HOLD = max(40, min(280, _BASE_KNOBS['WOOL_HOLD'] + g.get('wool_hold_delta', 0)))
            WHEAT_RESERVE_MULT = max(0.5, min(4.0, _BASE_KNOBS['WHEAT_RESERVE_MULT'] + g.get('wheat_reserve_delta', 0)))
        # The RL's found insight: the mixed milk+yarn draws want the longer
        # wool holds (the the kid19_g34's consistent +55-58 delta) — the the
        # dual demand absorbs the bigger stock without the floor crash.
        if _HAS_GENOME:
            shops = obs['town']['unlocked_shops']
            milk_n = sum(1 for s in shops if s in ('PIZZA_SHOP', 'ICE_CREAM_SHOP', 'SMOOTHIE_SHOP'))
            yarn_n = sum(1 for s in shops if s == 'YARN_STORE')
            if milk_n >= 2 and yarn_n >= 2:
                WOOL_HOLD = max(40, min(280, WOOL_HOLD + 55))
        orders = []
        private_shed = obs["private"]["shed"]
        day = obs["day"]
        cash = obs["farms"][obs["player"]]["money"]
        # Projected cash through the queue: the sells land first and fund the buys.
        proj_cash = cash

        # Track which resources have been claimed by a handler this turn
        claimed: Set[str] = set()

        # =====================================================================
        # Phase 0: ENDGAME LIQUIDATOR (day >= 28)
        # =====================================================================
        if day >= ENDGAME_LIQUIDATE_DAY:
            # Note: the animal SELL orders are invalid (the animals aren't in
            # the market's PRODUCTS), so only the tradeable resources sell.
            # The front-running ladder (the expert): the smooth drain from
            # the d26 beats the joint d28 dump into the crashed market.
            if day == 26:
                frac = 3
            elif day == 27:
                frac = 2
            elif day == 28:
                frac = 2
            else:
                frac = 1
            for resource in ALL_RESOURCES:
                held = private_shed.get(resource, 0)
                if held > 0 and len(orders) < 10:
                    qty = held if frac == 1 else max(0, (held // frac) + (1 if day >= 29 else 0))
                    if qty > 0:
                        orders.append(["SELL", resource, qty])
                        claimed.add(resource)
            # Keep hiring the hands: the final harvests + the pocket dumps still
            # need the workers (the env fires everyone at midnight).
            hires_target = decisions.get("hires", 0)
            total_hands = len(obs["farms"][obs["player"]]["hands"])
            while total_hands < hires_target and len(orders) < 10:
                orders.append(["HIRE"])
                total_hands += 1
            return orders[:10]

        # =====================================================================
        # Phase 1: SELL-TO-FUND — continuous product dumps (winner pattern).
        # Demand-aware: hold when the town has no shops for the resource (the
        # dump would crash the price; the goods don't spoil in the shed).
        # =====================================================================
        from m1_state_core import demand_drain_rate
        drain_map = demand_drain_rate(obs)
        enemy = scan_enemy(obs)
        enemy_sheep = enemy.get("animals", {}).get("SHEEP", 0)
        for resource in ["MILK", "WOOL", "EGG"]:
            held = private_shed.get(resource, 0)
            if held <= 0:
                continue
            demand_ok = drain_map.get(resource, 1) >= 7
            # The wool hold below $150 (the no-spoil good). Dumping into a
            # crashed market locks in the floor; the drain recovers it by the
            # endgame.
            price = obs["market"]["prices"].get(resource, 0)
            # The preemptive defection: a big enemy flock means their wool is
            # coming — sell ours FIRST into the still-pristine market instead
            # of holding into the joint endgame dump (the Prisoner's Dilemma:
            # the defector captures the premium tier, the holder gets the $1
            # floor).
            enemy_flock = resource == "WOOL" and enemy_sheep >= 8 and 10 <= day < 25
            if resource == "WOOL" and price < WOOL_HOLD and day < 25 and not enemy_flock:
                claimed.add(resource)
                continue
            if (demand_ok or day >= 26 or enemy_flock) and len(orders) < 10:
                # The paced sell (the expert's +$21.5k): the AMM re-prices
                # per unit, so the full dumps crash the glut curve. Sell the
                # ~the town consumption per tick (the drain/4 turns) — the
                # shed drains at the production rate, the price stays on the
                # scarcity side. The endgame/dump states sell out.
                if day >= 26 or enemy_flock:
                    qty = held
                else:
                    qty = min(held, max(2, int(math.ceil(drain_map.get(resource, 6) / PACE_DIV))))
                orders.append(["SELL", resource, qty])
                claimed.add(resource)

        # =====================================================================
        # Phase 1.5: Melon dump timing (day 8-13 as they mature)
        # =====================================================================
        if day in [8, 9, 10, 11, 12, 13] and "MELON" not in claimed:
            shed_melons = private_shed.get("MELON", 0)
            if shed_melons > 0 and len(orders) < 10:
                orders.append(["SELL", "MELON", shed_melons])
                claimed.add("MELON")

        # =====================================================================
        # Phase 2: PACING CONTROLLER (premium goods)
        # =====================================================================
        kappa = 0.25
        for resource in ["STRAWBERRY", "MELON"]:
            if resource in claimed:
                continue
            my_shed = private_shed.get(resource, 0)
            if my_shed <= 0:
                continue
            inv = obs["market"]["inventory"].get(resource, MARKET_I0)
            diff = MARKET_I0 - inv
            # The crash guard: when the shared market is glutted (both players
            # flood the same harvest), hold rather than lock in the floor.
            price = obs["market"]["prices"].get(resource, 999)
            if resource == "STRAWBERRY" and price < 80 and day < 25 and my_shed < 60:
                claimed.add(resource)
                continue
            sell_caps = {"STRAWBERRY": 8, "MELON": 15}
            max_sell = sell_caps.get(resource, 5)
            drain = min(max_sell, 5.0)
            q = drain + kappa * diff
            q_int = int(round(max(1, q)))
            q_int = min(q_int, my_shed, max_sell)
            if q_int > 0 and len(orders) < 10:
                orders.append(["SELL", resource, q_int])
                claimed.add(resource)

        # =====================================================================
        # Phase 2.5: the staples (the carrot/tomato). They sell AFTER the
        # premium goods (the sequential clearing), but they MUST sell — the
        # shed-held carrots/tomatoes were the unrealized endgame revenue.
        # =====================================================================
        for resource in ["CARROT", "TOMATO"]:
            if resource in claimed:
                continue
            held = private_shed.get(resource, 0)
            if held <= 0:
                continue
            demand_ok = drain_map.get(resource, 1) >= 7
            # Only the backlogs clear mid-game (the small holdings aren't worth
            # the order slots that the herd buys + the premium sells need).
            if held > 15 and (demand_ok or day >= 26) and len(orders) < 10:
                orders.append(["SELL", resource, min(held, 10)])
                claimed.add(resource)

        # =====================================================================
        # Phase 3: FERTILIZER — sell the excess over the field reserve.
        # =====================================================================
        if "FERTILIZER" not in claimed:
            fert_held = private_shed.get("FERTILIZER", 0)
            reserve = 15 if day < 26 else 0
            excess = max(0, fert_held - reserve)
            if excess > 0 and len(orders) < 10:
                orders.append(["SELL", "FERTILIZER", excess])
                claimed.add("FERTILIZER")

        # =====================================================================
        # Phase 4: WHEAT — feed reserve + arbitrage (buy cheap, sell dear).
        # =====================================================================
        if "WHEAT" not in claimed:
            wheat_held = private_shed.get("WHEAT", 0)
            wheat_price = obs["market"]["prices"].get("WHEAT", 25)
            total_shed = sum(private_shed.get(r, 0) for r in ALL_RESOURCES)

            # Daily feed need (field animals + shed animals awaiting placement)
            daily_feed_need = 0
            for row in obs["farms"][obs["player"]]["tiles"]:
                for t in row:
                    if isinstance(t, dict) and t.get("animal"):
                        daily_feed_need += 1
            daily_feed_need += private_shed.get("COW", 0) + private_shed.get("SHEEP", 0) + private_shed.get("GOOSE", 0)
            feed_reserve = daily_feed_need * 2

            # The sell when the shed clears the 2-day feed buffer AND the price
            # is decent — the harvest surplus must not sit until the endgame
            # dump (the grown wheat is the ~$30-45 cash, not just the feed).
            if wheat_held > feed_reserve + 6 and wheat_price >= 25 and day < 27:
                excess = wheat_held - feed_reserve - 3
                if excess > 0 and len(orders) < 10:
                    orders.append(["SELL", "WHEAT", excess])
                claimed.add("WHEAT")
            elif wheat_held > feed_reserve + 40:
                excess = wheat_held - feed_reserve
                if len(orders) < 10:
                    orders.append(["SELL", "WHEAT", excess])
                claimed.add("WHEAT")
            else:
                claimed.add("WHEAT")  # hold for the feed reserve

        # =====================================================================
        # Phase 5: BUYS funded by the queue's sell proceeds (any hour).
        # The m3 sets the daily plan; the m5 executes the moment cash appears.
        # =====================================================================
        def cash_after(amount):
            nonlocal proj_cash
            proj_cash -= amount

        if self.trade_day != day:
            self.trade_day = day
            self.bought_cow = 0
            self.bought_sheep = 0
            self.bought_goose = 0
            self.bought_land = False

        # Seeds first — cheap and the growth engine.
        seed_prices = {"MELON": 80, "WHEAT": 10, "STRAWBERRY": 100, "CARROT": 30, "TOMATO": 50}
        for crop, qty in intents.next_turn_seed_needs.items():
            already_have = obs["private"]["seeds"].get(crop, 0)
            need = max(0, qty - already_have)
            price = seed_prices.get(crop, 50)
            if price >= 50:
                budget = min(2500, max(0, proj_cash - 100))
                affordable = max(0, budget // max(price, 1))
                need = min(need, affordable)
            if need > 0 and len(orders) < 10:
                orders.append(["BUY_SEED", crop, need])
                cash_after(need * price)

        # The animals: the m3's daily plan, bought the moment the cash appears.
        # The early-game cash floor: the animal buys must leave the day's
        # mandatory budget (the hires + the watering + the feed) intact — the
        # d4 bankruptcies (the 99646243/99643963) come from the buys eating it.
        day_reserve = 150 if obs["day"] <= 6 else 50
        plan_animal = decisions.get("buy_animal", {})
        want_cow = max(0, plan_animal.get("COW", 0) - self.bought_cow)
        want_sheep = max(0, plan_animal.get("SHEEP", 0) - self.bought_sheep)
        want_goose = max(0, plan_animal.get("GOOSE", 0) - self.bought_goose)
        if len(orders) < 10:
            if want_cow > 0 and proj_cash >= 400 + day_reserve:
                qty = min(want_cow, 2)
                orders.append(["BUY_ANIMAL", "COW", qty])
                cash_after(qty * 400)
                self.bought_cow += qty
            if want_sheep > 0 and proj_cash >= 500 + day_reserve:
                qty = min(want_sheep, 2)
                orders.append(["BUY_ANIMAL", "SHEEP", qty])
                cash_after(qty * 500)
                self.bought_sheep += qty

        if len(orders) < 10:
            # Wheat feed reserve top-up — covers the d0-3 window before the
            # grown wheat harvests mature. Count the mouths + the planned buys.
            daily_feed_need = 0
            for row in obs["farms"][obs["player"]]["tiles"]:
                for t in row:
                    if isinstance(t, dict) and t.get("animal"):
                        daily_feed_need += 1
            daily_feed_need += private_shed.get("COW", 0) + private_shed.get("SHEEP", 0) + private_shed.get("GOOSE", 0)
            daily_feed_need += self.bought_cow + self.bought_sheep
            wheat_held = private_shed.get("WHEAT", 0)
            for inv in obs.get("private", {}).get("inventories", []):
                wheat_held += inv.get("WHEAT", 0)
            wheat_price = obs["market"]["prices"].get("WHEAT", 25)
            reserve_goal = daily_feed_need * WHEAT_RESERVE_MULT
            if daily_feed_need > 0 and wheat_held < reserve_goal:
                need = min(20, reserve_goal + 6 - wheat_held)
                affordable = max(0, (proj_cash - 200) // max(1, wheat_price))
                need = min(need, affordable)
                cost = need * wheat_price
                if need > 0 and len(orders) < 10:
                    orders.append(["BUY_PRODUCT", "WHEAT", need])
                    cash_after(cost)

        # The goose hedge LAST: the feed wheat must be secured first (a goose
        # starving the day-0 herd costs far more than the egg EV).
        if want_goose > 0 and proj_cash >= 300 + day_reserve and len(orders) < 10:
            qty = min(want_goose, 2)
            orders.append(["BUY_ANIMAL", "GOOSE", qty])
            cash_after(qty * 300)
            self.bought_goose += qty

        # The land: once per unlock. Real prices: [1000, 2000, 4000].
        if decisions.get("buy_land", 0) and not self.bought_land and len(orders) < 10:
            n_extra = len(obs["farms"][obs["player"]]["unlocked_quadrants"]) - 1
            land_cost = [1000, 2000, 4000][min(2, max(0, n_extra))]
            if proj_cash >= land_cost + 100:
                orders.append(["BUY_LAND"])
                cash_after(land_cost)
                self.bought_land = True

        # Fertilizer floor-sniping: REMOVED. The fertilizer has no town drain,
        # so a crashed price never recovers — buying the dips just feeds the
        # Phase-3 sell-back wash (measured: ~1125 units churned for ~0 net in
        # the mirror games while burning the order slots + the shed space).

        # Hires last (the fib burn must not starve the growth buys)
        hires_target = decisions.get("hires", 0)
        total_hands = len(obs["farms"][obs["player"]]["hands"])
        while total_hands < hires_target and len(orders) < 10 and proj_cash > 0:
            orders.append(["HIRE"])
            total_hands += 1

        # =====================================================================
        # Phase 6: SHED OVERFLOW safety net
        # =====================================================================
        total_shed = sum(private_shed.get(r, 0) for r in ALL_RESOURCES)
        if total_shed > SHED_OVERFLOW_THRESHOLD and len(orders) < 10:
            overflow = total_shed - SHED_OVERFLOW_THRESHOLD
            resource_by_price = []
            for r in ALL_RESOURCES:
                held = private_shed.get(r, 0)
                if held > 0:
                    resource_by_price.append((obs["market"]["prices"].get(r, 1), r, held))
            resource_by_price.sort()
            for price, r, held in resource_by_price:
                if overflow <= 0:
                    break
                sell_qty = min(held, overflow)
                if sell_qty > 0 and len(orders) < 10:
                    orders.append(["SELL", r, sell_qty])
                    claimed.add(r)
                    overflow -= sell_qty

        # =====================================================================
        # Phase 7: DEFAULT-SELL (safety net — the un-brickable fallback)
        # =====================================================================
        for resource in ALL_RESOURCES:
            if resource in claimed:
                continue
            held = private_shed.get(resource, 0)
            if resource == "WHEAT":
                daily_feed_need = sum(
                    1 for row in obs["farms"][obs["player"]]["tiles"]
                    for t in row if isinstance(t, dict) and t.get("animal"))
                sellable = max(0, held - daily_feed_need * 2)
            else:
                sellable = held
            if sellable > 0 and len(orders) < 10:
                orders.append(["SELL", resource, sellable])
                claimed.add(resource)

        return orders[:10]
