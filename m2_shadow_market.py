import math
from typing import Dict, List, Any, Tuple
from constants import MARKET_PARAMS, MARKET_I0, SHOPS, CROPS, ANIMALS

def _shape(func_name: str, x: float, T: float) -> float:
    if func_name == "linear":
        return x / T
    elif func_name == "sq":
        return (x / T) ** 2
    elif func_name == "sqrt":
        return math.sqrt(x / T) if x >= 0 else 0.0
    elif func_name == "log":
        return math.log1p(x) / math.log1p(T) if x >= 0 else 0.0
    elif func_name == "hinge":
        u = x / T
        if u <= 1:
            return u
        return u + 8 * (u - 1) ** 2
    return x / T

def get_marginal_price(item: str, inventory: int) -> int:
    p = MARKET_PARAMS[item]
    base = p["base"]
    I0 = p["I0"]
    T = p["T"]
    
    if inventory < I0:
        f = p["below_func"]
        amp = p["below_target"] * base / _shape(f, T, T)
        price = base + amp * _shape(f, I0 - inventory, T)
    else:
        f = p["above_func"]
        amp = p["above_target"] * base / _shape(f, T, T)
        price = base - amp * _shape(f, inventory - I0, T)
        
    return max(1, int(round(price)))

class ShadowMarket:
    def __init__(self):
        # Tracking [lo, hi] for opponent shed
        self.opp_shed_bounds: Dict[str, List[int]] = {k: [0, 0] for k in MARKET_PARAMS}
        self.town_unlocked_shops = []
        self.opp_money = 3000
        self.market_inventory = {k: MARKET_I0 for k in MARKET_PARAMS}
        
    def _estimate_town_drain(self, resource: str, prev_step: int, cur_step: int, unlocked_shops: List[str]) -> int:
        drain = 0
        # Town center drains 1 every 24 turns
        for step in range(prev_step + 1, cur_step + 1):
            if step > 0 and step % 24 == 0:
                drain += 1
            # Shops drain every 4 turns
            if step > 0 and step % 4 == 0:
                for shop in unlocked_shops:
                    if resource in SHOPS[shop]:
                        drain += 1
        return drain

    def update_from_obs(self, obs: Dict[str, Any], prev_obs: Dict[str, Any], my_actions: Dict[str, Any]):
        if not prev_obs:
            self.opp_money = obs["farms"][1 - obs["player"]]["money"]
            self.market_inventory = dict(obs["market"]["inventory"])
            self.town_unlocked_shops = list(obs["town"]["unlocked_shops"])
            return

        player = obs["player"]
        opp = 1 - player
        
        # Track town shops
        self.town_unlocked_shops = list(obs["town"]["unlocked_shops"])
        
        # We need to know my actual sales.
        # This can be read from my_actions "market" list (assuming they didn't fail)
        my_net_r = {k: 0 for k in MARKET_PARAMS}
        my_buys_cost = 0
        
        # Check actual my market actions executed successfully 
        # (For robustness, should read from my private inventory and money, but approximate via actions first)
        market_orders = my_actions.get("market", [])
        for order in market_orders:
            op = order[0]
            if op == "SELL":
                item = order[1]
                qty = order[2]
                my_net_r[item] -= qty
            elif op == "BUY_PRODUCT":
                item = order[1]
                qty = order[2]
                my_net_r[item] += qty
                my_buys_cost += get_marginal_price(item, prev_obs["market"]["inventory"][item]) * qty # crude
            elif op == "BUY_SEED":
                crop = order[1]
                qty = order[2]
                my_buys_cost += CROPS[crop]["seed"] * qty
            elif op == "BUY_ANIMAL":
                animal = order[1]
                qty = order[2]
                my_buys_cost += ANIMALS[animal]["cost"] * qty
                
        # Flow Conservation
        opp_sells_volume = 0
        opp_sells_revenue = 0
        
        for resource in MARKET_PARAMS:
            town_drain = self._estimate_town_drain(resource, prev_obs["step"], obs["step"], self.town_unlocked_shops)
            inv_now = obs["market"]["inventory"][resource]
            inv_prev = prev_obs["market"]["inventory"][resource]
            
            delta_inv = inv_now - inv_prev
            
            # delta_inv = my_net + opp_net - town_drain
            # opp_net = delta_inv - my_net + town_drain
            opp_net = delta_inv - my_net_r[resource] + town_drain
            
            if opp_net < 0: # opp sold
                sold_qty = -opp_net
                self.opp_shed_bounds[resource][1] -= sold_qty
                self.opp_shed_bounds[resource][0] -= sold_qty
                self.opp_shed_bounds[resource][0] = max(0, self.opp_shed_bounds[resource][0])
                
                # Approximate revenue (assume they sold all at once for simplicity, or sum marginal prices)
                # Actual Kaggle engine prices one by one.
                inv_temp = inv_prev
                # subtract my net first if my sell happened before theirs?
                # We assume interleaved or just average price.
                avg_price = get_marginal_price(resource, inv_prev)
                opp_sells_revenue += sold_qty * avg_price
            
        # Money ledger check
        opp_money_now = obs["farms"][opp]["money"]
        opp_money_delta = opp_money_now - self.opp_money
        
        # If opp_money_delta > opp_sells_revenue, they might have sold at floor where inventory didn't move!
        if opp_money_delta > opp_sells_revenue:
            unaccounted_revenue = opp_money_delta - opp_sells_revenue
            # We can't know exactly which resource, but floor sells are $1.
            # So unaccounted_revenue = unaccounted_units.
            # We widen the lower bound to 0 (we know they dumped something).
            for k in self.opp_shed_bounds:
                self.opp_shed_bounds[k][0] = 0
                
        # Track opp harvests (yield_units transitions) to increase bounds
        # Compare tiles from prev_obs to obs
        prev_tiles = prev_obs["farms"][opp]["tiles"]
        curr_tiles = obs["farms"][opp]["tiles"]
        
        for y in range(10):
            for x in range(10):
                ptile = prev_tiles[y][x]
                ctile = curr_tiles[y][x]
                if ptile and getattr(ptile, "get", lambda x: None)("kind") == "PLANT":
                    if ctile is None or (getattr(ctile, "get", lambda x: None)("kind") == "PLANT" and ctile.get("yield_units", 0) < ptile.get("yield_units", 0)):
                        # Harvest occurred
                        crop = ptile["crop"]
                        diff = ptile.get("yield_units", 0) - (ctile.get("yield_units", 0) if ctile and ctile.get("crop") == crop else 0)
                        if diff > 0:
                            self.opp_shed_bounds[crop][0] += diff
                            self.opp_shed_bounds[crop][1] += diff
                # Similarly for animals (products and fertilizer)
        
        self.opp_money = opp_money_now
        self.market_inventory = dict(obs["market"]["inventory"])

    def project_prices(self, t_now: int, horizon: int, own_sales_plan: Dict[int, Dict[str, int]]) -> Dict[int, Dict[str, int]]:
        proj = {}
        for d in range(horizon):
            step = t_now + d * 24
            proj[step] = {}
            for resource in MARKET_PARAMS:
                drain = self._estimate_town_drain(resource, t_now, step, self.town_unlocked_shops)
                my_planned = sum(own_sales_plan.get(t, {}).get(resource, 0) for t in range(t_now, step + 1))
                
                # Assume opp dumps upper bound at random or spreads it
                # For simplicity, we assume they hold until their dump alarm, but we just use current bounds
                opp_held = self.opp_shed_bounds[resource][1]
                
                projected_inv = self.market_inventory[resource] + my_planned + opp_held - drain
                proj[step][resource] = get_marginal_price(resource, projected_inv)
                
        return proj
        
    def get_dump_alarm(self, obs: Dict[str, Any]) -> Dict[str, int]:
        alarms = {}
        opp = 1 - obs["player"]
        tiles = obs["farms"][opp]["tiles"]
        
        # Look for melons
        for y in range(10):
            for x in range(10):
                tile = tiles[y][x]
                if tile and getattr(tile, "get", lambda x: None)("kind") == "PLANT" and tile["crop"] == "MELON":
                    age = obs["day"] - tile["planted_day"]
                    # If fertilized, matures at 8. Otherwise 10.
                    # We can see if it's fertilized: fertilized_until_day
                    maturation_age = 10
                    # if they've been watering and fertilizing...
                    turns_left = max(0, (maturation_age - age) * 24 - obs["hour"])
                    if "MELON" not in alarms or turns_left < alarms["MELON"]:
                        alarms["MELON"] = turns_left
        return alarms
