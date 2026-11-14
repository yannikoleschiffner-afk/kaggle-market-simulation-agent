import copy
import sys
from typing import Dict, Any, List

from constants import CROPS, SHOPS, ALL_RESOURCES


def demand_drain_rate(obs: Dict[str, Any]) -> Dict[str, int]:
    """Quantify the town's daily consumption of every product.

    - Town center: +1/day for every non-fertilizer product.
    - Standard shop (2+ demands): +6/day per demanded product.
    - Single-product shop (Yarn Store, Pet Cafe): +12/day.
    """
    drain: Dict[str, int] = {r: 0 for r in ALL_RESOURCES}
    for r in ALL_RESOURCES:
        if r != "FERTILIZER":
            drain[r] += 1  # town center

    for shop in obs["town"].get("unlocked_shops", []):
        products = SHOPS.get(shop, [])
        mult = 2 if len(products) == 1 else 1
        per_day = 6 * mult
        for item in products:
            drain[item] += per_day

    return drain


def scan_enemy(obs: Dict[str, Any]) -> Dict[str, Any]:
    """Adversarial recon: aggregate the opponent's public farm state.

    The opponent's shed/inventories are hidden, but their entire grid (every
    plant and animal) is visible in obs["farms"][1 - player]["tiles"]. This
    infers their upcoming market actions:

      * crops       -> {crop: tile_count}
      * near_mature -> {crop: count of plants within 1 day of first yield}
      * animals     -> {COW/SHEEP/GOOSE: placed count}
    """
    opp = obs["farms"][1 - obs["player"]]
    day = obs["day"]
    crops: Dict[str, int] = {}
    near_mature: Dict[str, int] = {}
    animals: Dict[str, int] = {"COW": 0, "SHEEP": 0, "GOOSE": 0}

    for row in opp["tiles"]:
        for t in row:
            if not isinstance(t, dict):
                continue
            kind = t.get("kind")
            if kind == "PLANT":
                crop = t.get("crop")
                crops[crop] = crops.get(crop, 0) + 1
                age = day - t.get("planted_day", day)
                first_yield = CROPS.get(crop, {}).get("first_yield_day", 1)
                if age >= first_yield - 1:
                    near_mature[crop] = near_mature.get(crop, 0) + 1
            elif kind in ("COOP", "PASTURE"):
                a = t.get("animal")
                if a:
                    animals[a] = animals.get(a, 0) + 1

    return {"crops": crops, "near_mature": near_mature, "animals": animals}


def clone(obs: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(obs)

def step(obs: Dict[str, Any], config: Dict[str, Any], my_actions: Dict[str, Any], opp_actions: Dict[str, Any] = None) -> Dict[str, Any]:
    from kaggle_environments import make
    if opp_actions is None:
        opp_actions = {"farmer": ["PASS"]}
        
    cfg = copy.deepcopy(config) if config else {"episodeSteps": 120}
    env = make('kaggriculture', configuration=cfg)
    env.reset()
    
    p = obs["player"]
    obs_clone = copy.deepcopy(obs)
    obs_clone["player"] = 0
    obs_opp = copy.deepcopy(obs)
    obs_opp["player"] = 1
    
    env.state[0].observation = obs_clone
    env.state[1].observation = obs_opp
    
    actions = [None, None]
    actions[p] = my_actions
    actions[1 - p] = opp_actions
    
    env.step(actions)
    
    ans = env.state[p].observation
    ans["player"] = p
    return ans

def lint_actions(obs: Dict[str, Any], actions: Dict[str, Any]) -> None:
    """
    Pre-submit legality check on composed actions.
    Prints to stderr if an illegal action is detected.
    """
    player = obs["player"]
    farm = obs["farms"][player]
    tiles = farm["tiles"]
    
    def check_interaction(pos: List[int], op: str, agent_type: str):
        x, y = pos
        if not (0 <= x < 10 and 0 <= y < 10):
            print(f"[LINT ERROR] {agent_type} out of bounds at {x},{y}", file=sys.stderr)
            return
            
        tile = tiles[y][x]
        
        if op == "WATER":
            if not isinstance(tile, dict) or tile.get("kind") != "PLANT":
                print(f"[LINT ERROR] {agent_type} WATER on non-plant at {x},{y}", file=sys.stderr)
        elif op == "DIG":
            pass
        elif op == "HARVEST":
            if not isinstance(tile, dict):
                print(f"[LINT ERROR] {agent_type} HARVEST on empty tile at {x},{y}", file=sys.stderr)
            elif tile.get("kind") == "PLANT":
                if tile.get("yield_units", 0) <= 0:
                    print(f"[LINT ERROR] {agent_type} HARVEST on plant with 0 yield at {x},{y}", file=sys.stderr)
            elif "animal" in tile:
                if tile.get("yield_units", 0) <= 0:
                    print(f"[LINT ERROR] {agent_type} HARVEST on animal with 0 yield at {x},{y}", file=sys.stderr)
            else:
                print(f"[LINT ERROR] {agent_type} HARVEST on invalid tile kind at {x},{y}", file=sys.stderr)
        elif op == "FEED":
            if not isinstance(tile, dict) or "animal" not in tile:
                print(f"[LINT ERROR] {agent_type} FEED on non-animal at {x},{y}", file=sys.stderr)
        elif op == "CARE":
            if not isinstance(tile, dict) or "animal" not in tile:
                print(f"[LINT ERROR] {agent_type} CARE on non-animal at {x},{y}", file=sys.stderr)
        elif op == "COLLECT_FERTILIZER":
            if not isinstance(tile, dict) or "animal" not in tile:
                print(f"[LINT ERROR] {agent_type} COLLECT_FERTILIZER on non-animal at {x},{y}", file=sys.stderr)
        elif op == "PLANT":
            if tile is not None:
                print(f"[LINT ERROR] {agent_type} PLANT on non-empty tile at {x},{y}", file=sys.stderr)

    def simulate_agent_movement(start_pos: List[int], acts: List[str]) -> List[int]:
        pos = list(start_pos)
        for act in acts:
            if act == "NORTH": pos[1] = max(0, pos[1] - 1)
            elif act == "SOUTH": pos[1] = min(9, pos[1] + 1)
            elif act == "EAST": pos[0] = min(9, pos[0] + 1)
            elif act == "WEST": pos[0] = max(0, pos[0] - 1)
        return pos

    farmer_acts = actions.get("farmer", [])
    if farmer_acts:
        interact_op = farmer_acts[-1] if farmer_acts[-1] not in ("NORTH", "SOUTH", "EAST", "WEST", "PASS") else None
        moves = [a for a in farmer_acts if a in ("NORTH", "SOUTH", "EAST", "WEST")]
        final_pos = simulate_agent_movement(farm["farmer"], moves)
        if interact_op:
            check_interaction(final_pos, interact_op, "farmer")

    for i, hands_acts in enumerate(actions.get("hands", [])):
        if hands_acts:
            interact_op = hands_acts[-1] if hands_acts[-1] not in ("NORTH", "SOUTH", "EAST", "WEST", "PASS") else None
            moves = [a for a in hands_acts if a in ("NORTH", "SOUTH", "EAST", "WEST")]
            final_pos = simulate_agent_movement(farm["hands"][i], moves)
            if interact_op:
                check_interaction(final_pos, interact_op, f"hand_{i}")
