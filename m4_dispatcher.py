from typing import Dict, Any, List, Tuple, Set
from turn_intents import TurnIntents
from constants import CROPS, ANIMALS
try:
    from m6_plan_genome import consult as genome_consult
    _HAS_GENOME = True
except ImportError:
    genome_consult = None
    _HAS_GENOME = False

def manhattan(p1: Tuple[int, int], p2: Tuple[int, int]) -> int:
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

# ═══════════════════════════════════════════════════════════════════════════
# STRICT TIERED PRIORITIES — no distance can cross tiers
# ═══════════════════════════════════════════════════════════════════════════
TIER_FEED             = 100   # Tier 1: Survival — animals escape if unfed 2 days
TIER_CRITICAL_WATER   = 95    # Tier 1: Plants become weeds if unwatered 2 days
TIER_COLLECT_FERT     = 91    # Tier 2: Daily fertilizer ($100/animal, lost if uncollected)
TIER_WATER            = 84    # Tier 3: Routine watering — must outrank the harvests
TIER_WATER_SKIP       = 72    # Tier 4: Survival-only watering (the non-bonus /
                              # non-production days) — filler work; the yield
                              # never suffers (the expert's intermittent
                              # watering: the half the field every other day).
TIER_HARVEST_ANIMAL   = 82    # Tier 3: Milk/wool/egg extraction
TIER_HARVEST          = 80    # Tier 3: Crop extraction
TIER_BUILD            = 80    # Tier 3: Build structures — the shed-animals wait
                              # on the build; ties the harvest. The measured:
                              # the live games +46k/+38k with the 80 (the
                              # placements stall at the 78-79).
TIER_PLACE_ANIMAL     = 80    # Tier 3: Place animals into structures
TIER_FERTILIZE        = 83    # Tier 4: Yield doubler (production-timed)
TIER_PLANT            = 70    # Tier 5: Growth — instantiate new seeds
# The early-game plant priority (the d0-6 only): the winner executes the
# 13 plant + 13 water lockstep on the d0 (the distill data); our 70-tier
# plantings get squeezed out by the feeds/builds. The high tier early, the
# 70 after the d6 (the global boost crashed the mid-game harvests before).
TIER_PLANT_EARLY      = 79
TIER_CARE             = 90    # Tier 2.5: +1 yield on the next production (the
                              # ~$67/action for the sheep) — above the water,
                              # below the collect (the ~$100/day). The winner's
                              # wool volume (the 304 vs our 139) is the care
                              # uptime.
TIER_CLEAR_WEED       = 65    # Tier 6: Weed removal

# The genome-adjustable tiers: the deltas (the the m6 rule actions) shift
# these around the saved bases — the evolution can re-balance the worker
# allocation (the the "is the dispatch suboptimal" question) without the
# touching the structural tiers (the the feed/critical/survival ones).
_BASE_TIERS = {
    'water': TIER_WATER, 'water_skip': TIER_WATER_SKIP,
    'plant': TIER_PLANT, 'plant_early': TIER_PLANT_EARLY,
    'build': TIER_BUILD, 'harvest': TIER_HARVEST, 'care': TIER_CARE,
}
_TIER_DELTA_KEYS = ('water_tier_delta', 'plant_tier_delta',
                    'build_tier_delta', 'harvest_tier_delta', 'care_tier_delta')

SHED_TILES = [(4, 4), (5, 4), (4, 5), (5, 5)]
SHED_SET = set(SHED_TILES)

# Products the workers should deposit into the shed for sale.
PRODUCT_ITEMS = ["MILK", "WOOL", "EGG", "STRAWBERRY", "MELON", "CARROT", "TOMATO"]

# ═══════════════════════════════════════════════════════════════════════════
# SECTOR DEFINITIONS (field work home quadrants)
# ═══════════════════════════════════════════════════════════════════════════
def get_sector(x, y):
    if x < 5 and y < 5: return "NW"
    if x >= 5 and y < 5: return "NE"
    if x < 5 and y >= 5: return "SW"
    return "SE"

# The load-aware sector assignment (the forensics fix): the workers quota'd by
# the planted-field load per quadrant, the min-2 floor, the incremental hires.
LOAD_AWARE_SECTORS = True
# The sector-route following (the load-balanced nearest-neighbour partition).
ROUTES_ON = True

def pos_in_sector(x, y, sector):
    if sector == "NW": return x <= 4 and y <= 4
    if sector == "NE": return x >= 5 and y <= 4
    if sector == "SW": return x <= 4 and y >= 5
    if sector == "SE": return x >= 5 and y >= 5
    return False

def _sector_tile_list(sector):
    """The row-major snake path through the quadrant (the continuous sweep)."""
    if sector == "NW":
        ys, xs = range(5), range(5)
    elif sector == "NE":
        ys, xs = range(5), range(5, 10)
    elif sector == "SW":
        ys, xs = range(5, 10), range(5)
    else:
        ys, xs = range(5, 10), range(5, 10)
    tiles = []
    for j, y in enumerate(ys):
        row = list(xs)
        if j % 2 == 1:
            row = row[::-1]
        for x in row:
            tiles.append((x, y))
    return tiles

SECTOR_TILE_LISTS = {s: _sector_tile_list(s) for s in ("NW", "NE", "SW", "SE")}

# Animal maintenance ops — the lease system handles these.
ANIMAL_MAINT_OPS = {"FEED", "CARE", "COLLECT_FERTILIZER", "HARVEST_ANIMAL"}

class MultiAgentDispatcher:
    def __init__(self):
        self.plant_queue = []
        self.unassigned_tasks = 0
        self.worker_sectors = {}  # worker_idx -> home quadrant
        self.worker_animal = {}   # worker_idx -> leased animal tile (persistent visit)
        self.worker_task = {}     # worker_idx -> (op, pos) multi-turn task lease
        self.last_water_step = {} # tile -> step of the last watering (round-robin)
        self.sweep_pos = {}       # worker_idx -> the current sweep tile
        self.worker_route = {}    # worker_idx -> [pos, pos, ...] local task chain
        self.routes = {}          # worker_idx -> [pos, ...] the midnight route
        self.route_idx = {}       # worker_idx -> the position in the route
        self.pass_reasons = []    # debug: (day, hour, task_or_None, n_tasks) per PASS
        self.cross_lease = {}     # worker_idx -> (op, pos) committed cross-sector task
        self.quota_log = []       # debug: (day, tuple(sorted(quotas)))
        self.sector_load = {}     # quadrant -> the stored field load (for the mid-day fills)

    def _formulate_routes(self, agents, tasks, unlocked):
        """The midnight route solver: partition each sector's field tiles among
        its workers as the contiguous nearest-neighbour paths (the critical
        tiles first)."""
        by_sector = {}
        for i, pos in enumerate(agents):
            role = self.worker_sectors.get(i, "NW")
            by_sector.setdefault(role, []).append((i, tuple(pos)))
        for role, workers in by_sector.items():
            tiles = {}
            for t in tasks:
                pos = t.get("pos")
                if pos is None:
                    continue
                tx, ty = pos
                if not pos_in_sector(tx, ty, role):
                    continue
                if t["op"] in ANIMAL_MAINT_OPS:
                    continue
                if t["op"] == "PLANT" and t.get("crop") is None:
                    continue
                if pos not in tiles:
                    tiles[pos] = t["priority"]
                elif t["priority"] > tiles[pos]:
                    tiles[pos] = t["priority"]
            ordered = sorted(tiles.keys(), key=lambda p: -tiles[p])
            routes = {w: [] for w, _ in workers}
            for tile in ordered:
                best_w = None
                best_cost = float('inf')
                for w, start in workers:
                    route = routes[w]
                    anchor = route[-1] if route else start
                    cost = manhattan(anchor, tile) + 2 * len(route)
                    if cost < best_cost:
                        best_cost = cost
                        best_w = w
                if best_w is not None:
                    routes[best_w].append(tile)
            for w, start in workers:
                route = list(routes[w])
                ordered_route = []
                cur = start
                while route:
                    nxt = min(route, key=lambda t: manhattan(cur, t))
                    ordered_route.append(nxt)
                    route.remove(nxt)
                    cur = nxt
                self.routes[w] = ordered_route
                self.route_idx[w] = 0

    def _is_shed_adjacent(self, pos):
        # The env only accepts PICKUP/DROP on the four exact shed tiles, not
        # the ring around them — the manhattan<=1 version had the workers
        # stuck in the failing pickup loops (the 40+ pickups/day).
        return pos in SHED_SET

    def is_unlocked(self, x, y, unlocked):
        if x < 5 and y < 5: return True
        if x >= 5 and y < 5: return "NE" in unlocked
        if x < 5 and y >= 5: return "SW" in unlocked
        return "SE" in unlocked

    def _move_towards(self, a_pos, target):
        if isinstance(target, set):
            best = min(target, key=lambda t: manhattan(a_pos, t))
        else:
            best = target
        dx = best[0] - a_pos[0]
        dy = best[1] - a_pos[1]
        if abs(dx) >= abs(dy):
            return ["EAST"] if dx > 0 else ["WEST"] if dx < 0 else ["PASS"]
        else:
            return ["SOUTH"] if dy > 0 else ["NORTH"] if dy < 0 else ["PASS"]

    def _assign_sectors_plain(self, agents, unlocked_quads, load=None):
        """Every agent gets a home quadrant; animal work floats above sectors.
        The quotas follow the field load per quadrant (the stranded-task
        forensics: the even split idles the workers in the light sectors while
        the loaded sectors overflow); the min-1 floor keeps the coverage."""
        self.worker_sectors = {}
        quads = list(unlocked_quads)
        if not quads:
            quads = ["NW"]
        n = len(agents)
        if load is not None:
            total = sum(load.values())
            floor = max(1, min(2, n // len(quads)))
            if total > 0:
                raw = {q: n * load[q] / total for q in quads}
                quotas = {q: max(floor, int(raw[q])) for q in quads}
                leftover = n - sum(quotas.values())
                if leftover < 0:
                    # The floor overran the headcount: trim the lightest first.
                    while leftover < 0:
                        q_min = min(quads, key=lambda q: raw[q])
                        if quotas[q_min] > floor:
                            quotas[q_min] -= 1
                            leftover += 1
                        else:
                            quotas[quads[0]] -= 1
                            leftover += 1
                else:
                    for q in sorted(quads, key=lambda q: -(raw[q] - int(raw[q]))):
                        if leftover <= 0:
                            break
                        quotas[q] += 1
                        leftover -= 1
            else:
                quotas = self._even_quotas(n, quads)
        else:
            quotas = self._even_quotas(n, quads)
        unassigned = list(range(len(agents)))
        for q in quads:
            while quotas[q] > 0 and unassigned:
                best = min(unassigned, key=lambda h: self._dist_to_quad_center(agents[h], q))
                self.worker_sectors[best] = q
                unassigned.remove(best)
                quotas[q] -= 1

    @staticmethod
    def _even_quotas(n, quads):
        base = n // len(quads)
        quotas = {q: base for q in quads}
        extra = n - base * len(quads)
        for k in range(extra):
            quotas[quads[k]] += 1
        return quotas

    def _dist_to_quad_center(self, pos, quad):
        centers = {"NW": (2, 2), "NE": (7, 2), "SW": (2, 7), "SE": (7, 7)}
        c = centers.get(quad, (5, 5))
        return manhattan(pos, c)

    def generate_tasks(self, obs, decisions):
        global TIER_WATER, TIER_WATER_SKIP, TIER_PLANT, TIER_PLANT_EARLY
        global TIER_BUILD, TIER_HARVEST, TIER_CARE
        farm = obs["farms"][obs["player"]]
        unlocked = farm.get("unlocked_quadrants", ["NW"])
        tiles = farm["tiles"]

        # The genome tier deltas: the re-balance the worker allocation each
        # call. ALWAYS recompute from the bases (the the no-genome call resets
        # to them) — otherwise the mutated tiers leak into the next game in
        # the same worker process.
        enemy_info = {'sheep': 0, 'cows': 0, 'plants': 0}
        for y in range(10):
            for x in range(10):
                t = obs['farms'][1 - obs['player']]['tiles'][y][x]
                if isinstance(t, dict):
                    if t.get('kind') == 'PLANT':
                        enemy_info['plants'] += 1
                    elif t.get('animal'):
                        if t['animal'] == 'SHEEP':
                            enemy_info['sheep'] += 1
                        elif t['animal'] == 'COW':
                            enemy_info['cows'] += 1
        g = genome_consult(obs["day"], 0, 0, farm["money"], enemy_info) if _HAS_GENOME else {}
        TIER_WATER = max(60, min(99, _BASE_TIERS['water'] + g.get('water_tier_delta', 0)))
        TIER_WATER_SKIP = max(50, min(90, _BASE_TIERS['water_skip'] + g.get('water_tier_delta', 0)))
        TIER_PLANT = max(50, min(90, _BASE_TIERS['plant'] + g.get('plant_tier_delta', 0)))
        TIER_PLANT_EARLY = max(55, min(95, _BASE_TIERS['plant_early'] + g.get('plant_tier_delta', 0)))
        TIER_BUILD = max(55, min(95, _BASE_TIERS['build'] + g.get('build_tier_delta', 0)))
        TIER_HARVEST = max(55, min(95, _BASE_TIERS['harvest'] + g.get('harvest_tier_delta', 0)))
        TIER_CARE = max(60, min(99, _BASE_TIERS['care'] + g.get('care_tier_delta', 0)))

        tasks = []
        intents = TurnIntents()

        # Refill plant queue: at hour 0, and also when empty (instant replanting)
        if obs["hour"] == 0 or len(self.plant_queue) == 0:
            for c, qty in decisions.get("plant", {}).items():
                already = self.plant_queue.count(c)
                needed = max(0, qty - already)
                self.plant_queue.extend([c] * needed)

        # ── Scan tiles ──
        empty_tiles = []
        invs = obs.get("private", {}).get("inventories", [])
        system_wheat = obs["private"]["shed"].get("WHEAT", 0) + sum(inv.get("WHEAT", 0) for inv in invs)
        system_fert = obs["private"]["shed"].get("FERTILIZER", 0) + sum(inv.get("FERTILIZER", 0) for inv in invs)
        system_animals = {
            "COW": obs["private"]["shed"].get("COW", 0) + sum(inv.get("COW", 0) for inv in invs),
            "SHEEP": obs["private"]["shed"].get("SHEEP", 0) + sum(inv.get("SHEEP", 0) for inv in invs),
            "GOOSE": obs["private"]["shed"].get("GOOSE", 0) + sum(inv.get("GOOSE", 0) for inv in invs),
        }

        for y in range(10):
            for x in range(10):
                if not self.is_unlocked(x, y, unlocked):
                    continue
                tile = tiles[y][x]
                if tile is None:
                    empty_tiles.append((x, y))
                elif isinstance(tile, dict):
                    kind = tile.get("kind")

                    if kind == "PLANT":
                        crop = tile.get("crop")
                        c_data = CROPS.get(crop, {})
                        max_yield_day = c_data.get("max_yield_day", 1)
                        planted_day = tile.get("planted_day", obs["day"])
                        age_days = obs["day"] - planted_day
                        current_yield = tile.get("yield_units", 0)
                        max_possible_yield = c_data.get("max_yield", 1)
                        is_watered = tile.get("watered_today", False)

                        hit_max = current_yield >= max_possible_yield
                        mature = age_days >= max_yield_day and current_yield > 0
                        endgame_dump = obs["day"] >= 29 and current_yield > 0
                        # Harvest if sitting past max yield day (don't let crops rot)
                        overripe = age_days >= max_yield_day + 2 and current_yield > 0

                        if hit_max or mature or endgame_dump or overripe:
                            tasks.append({"op": "HARVEST", "pos": (x, y), "priority": TIER_HARVEST})
                        elif not is_watered:
                            # Check if this is CRITICAL (unwatered yesterday too).
                            # The evening sweep: the dying tiles get the near-top
                            # priority once the morning animal wave is done.
                            consecutive = tile.get("consecutive_unwatered", 0)
                            if consecutive >= 1:
                                prio = TIER_CRITICAL_WATER + (4 if obs["hour"] >= 15 else 0)
                            else:
                                # The intermittent watering (the expert's density
                                # unlock): the yield only responds to water in
                                # specific windows — the one-time crops in
                                # [(max_yield_day+1)//2, max_yield_day], the
                                # ongoing crops on their production days. The
                                # other days the water is the pure survival —
                                # it drops below the harvests and the plants.
                                ongoing = c_data.get("ongoing", False)
                                if ongoing:
                                    prod = (age_days + 1 - c_data["first_yield_day"])
                                    if (prod >= 0
                                            and prod % c_data.get("interval", 1) == 0):
                                        prio = TIER_WATER
                                    else:
                                        prio = TIER_WATER_SKIP
                                else:
                                    window_start = (c_data["max_yield_day"] + 1) // 2
                                    if window_start <= age_days <= c_data["max_yield_day"]:
                                        prio = TIER_WATER
                                    else:
                                        prio = TIER_WATER_SKIP
                            tasks.append({"op": "WATER", "pos": (x, y), "priority": prio})
                        elif (c_data.get("ongoing", False)
                              and tile.get("fertilized_until_day", -1) < obs["day"]
                              and age_days >= c_data.get("first_yield_day", 10) - 4
                              and system_fert > 0):
                            # Production-timed fertilize: doubles the yield (2 vs 1)
                            # on the upcoming scheduled productions. Re-applied
                            # every ~3 days from 4 days before the first yield.
                            tasks.append({"op": "FERTILIZE", "pos": (x, y), "priority": TIER_FERTILIZE})
                            system_fert -= 1

                    elif kind == "COOP":
                        if tile.get("animal"):
                            if tile.get("yield_units", 0) > 0:
                                tasks.append({"op": "HARVEST_ANIMAL", "pos": (x, y), "priority": TIER_HARVEST_ANIMAL})
                            if not tile.get("fed_today", False) and system_wheat > 0:
                                danger = tile.get("consecutive_unfed", 0) >= 1
                                prio = TIER_FEED + (30 if danger else 0)
                                tasks.append({"op": "FEED", "pos": (x, y), "priority": prio})
                                system_wheat -= 1
                            if tile.get("fertilizer_available"):
                                tasks.append({"op": "COLLECT_FERTILIZER", "pos": (x, y), "priority": TIER_COLLECT_FERT})
                            if not tile.get("cared_today", False) and tile.get("fed_today", False):
                                # CARE only if already fed today (expert: unfed care = wasted action)
                                tasks.append({"op": "CARE", "pos": (x, y), "priority": TIER_CARE})
                        else:
                            if system_animals["GOOSE"] > 0:
                                prio = TIER_PLACE_ANIMAL + (10 if system_animals["GOOSE"] >= 3 else 0)
                                tasks.append({"op": "PLACE_ANIMAL", "animal": "GOOSE", "pos": (x, y), "priority": prio})
                                system_animals["GOOSE"] -= 1

                    elif kind == "PASTURE":
                        if tile.get("animal"):
                            if tile.get("yield_units", 0) > 0:
                                tasks.append({"op": "HARVEST_ANIMAL", "pos": (x, y), "priority": TIER_HARVEST_ANIMAL})
                            if not tile.get("fed_today", False) and system_wheat > 0:
                                danger = tile.get("consecutive_unfed", 0) >= 1
                                prio = TIER_FEED + (30 if danger else 0)
                                tasks.append({"op": "FEED", "pos": (x, y), "priority": prio})
                                system_wheat -= 1
                            if tile.get("fertilizer_available"):
                                tasks.append({"op": "COLLECT_FERTILIZER", "pos": (x, y), "priority": TIER_COLLECT_FERT})
                            if not tile.get("cared_today", False) and tile.get("fed_today", False):
                                tasks.append({"op": "CARE", "pos": (x, y), "priority": TIER_CARE})
                        else:
                            if system_animals["COW"] > 0:
                                prio = TIER_PLACE_ANIMAL + (10 if system_animals["COW"] >= 3 else 0)
                                tasks.append({"op": "PLACE_ANIMAL", "animal": "COW", "pos": (x, y), "priority": prio})
                                system_animals["COW"] -= 1
                            elif system_animals["SHEEP"] > 0:
                                prio = TIER_PLACE_ANIMAL + (10 if system_animals["SHEEP"] >= 3 else 0)
                                tasks.append({"op": "PLACE_ANIMAL", "animal": "SHEEP", "pos": (x, y), "priority": prio})
                                system_animals["SHEEP"] -= 1

                    elif kind == "WEED":
                        tasks.append({"op": "CLEAR", "pos": (x, y), "priority": TIER_CLEAR_WEED})

        # ── Build structures: pastures shed-adjacent, coops on shed ring ──
        needed_pastures = system_animals["COW"] + system_animals["SHEEP"]
        needed_coops = system_animals["GOOSE"]

        # Sort empty tiles by distance to shed to place structures near shed
        empty_tiles.sort(key=lambda p: min(manhattan(p, s) for s in SHED_TILES))

        for pos in empty_tiles[:]:
            if needed_pastures > 0:
                tasks.append({"op": "BUILD_PASTURE", "pos": pos, "priority": TIER_BUILD})
                needed_pastures -= 1
                empty_tiles.remove(pos)
            else:
                break

        for pos in empty_tiles[:]:
            if needed_coops > 0:
                tasks.append({"op": "BUILD_COOP", "pos": pos, "priority": TIER_BUILD})
                needed_coops -= 1
                empty_tiles.remove(pos)
            else:
                break

        # ── Plant tasks on remaining empty tiles ──
        plant_candidates = list(empty_tiles)
        plant_candidates.sort(key=lambda p: manhattan(p, (5, 5)))

        temp_queue = list(self.plant_queue)
        for pos in plant_candidates:
            if not temp_queue:
                break
            crop = temp_queue.pop(0)
            tasks.append({"op": "PLANT", "crop": crop, "pos": pos,
                          "priority": (TIER_PLANT_EARLY if obs["day"] <= 6 else TIER_PLANT)})
            intents.next_turn_seed_needs[crop] = intents.next_turn_seed_needs.get(crop, 0) + 1

        return sorted(tasks, key=lambda t: t["priority"], reverse=True), intents

    def dispatch(self, obs, duals, decisions):
        tasks, intents = self.generate_tasks(obs, decisions)
        farm = obs["farms"][obs["player"]]
        farmer_pos = tuple(farm["farmer"])
        hands_pos = [tuple(h) for h in farm.get("hands", [])]
        agents = [farmer_pos] + hands_pos

        unlocked = farm.get("unlocked_quadrants", ["NW"])
        if LOAD_AWARE_SECTORS and (obs.get("hour", 0) == 0 or not self.worker_sectors \
                or set(self.worker_sectors.values()) != set(unlocked)):
            # The load = the PLANTED field tiles per quadrant (the stable
            # day-scale load; the current-turn tasks are the hour-scale and
            # made the assignment thrash / strand the fresh plantings).
            field_load = {q: 0 for q in unlocked}
            for y in range(10):
                for x in range(10):
                    t = farm["tiles"][y][x]
                    if isinstance(t, dict) and (t.get("ongoing") or t.get("crop")):
                        for q in unlocked:
                            if pos_in_sector(x, y, q):
                                field_load[q] += 1
                                break
            # The NW hosts the shed (the pickups/drops for every worker) — a
            # small fixed load on top of the field tiles.
            field_load["NW"] = field_load.get("NW", 0) + 1
            self.sector_load = dict(field_load)
            self._assign_sectors_plain(agents, unlocked, field_load)
            self.quota_log.append((obs["day"],
                                   tuple(sorted((q, list(self.worker_sectors.values()).count(q)) for q in unlocked))))
        elif not LOAD_AWARE_SECTORS:
            # The legacy every-turn even split (the baseline for the A/B).
            self._assign_sectors_plain(agents, unlocked)
        else:
            # The mid-day hires: assign the new workers to the least-staffed
            # sector (the incremental — no reshuffling; the load-proportional
            # fills measured worse on the contested games).
            for wi in range(len(agents)):
                if wi not in self.worker_sectors:
                    self.worker_sectors[wi] = min(
                        unlocked, key=lambda q: list(self.worker_sectors.values()).count(q))

        local_seeds = dict(obs.get("private", {}).get("seeds", {}))
        shed_wheat = obs.get("private", {}).get("shed", {}).get("WHEAT", 0)
        unfed_count = sum(1 for t in tasks if t["op"] == "FEED")
        day = obs["day"]
        hour = obs["hour"]

        if ROUTES_ON:
            self._formulate_routes(agents, tasks, unlocked)

        survival_match = {}

        # ── Group the animal maintenance tasks by tile ──
        animal_needs: Dict[Tuple[int, int], List[Tuple[int, Dict]]] = {}
        for t_idx, t in enumerate(tasks):
            if t["op"] in ANIMAL_MAINT_OPS:
                animal_needs.setdefault(t["pos"], []).append((t_idx, t))

        # Drop stale leases for animals that no longer exist
        live_tiles = set(animal_needs.keys())
        for wi in list(self.worker_animal.keys()):
            if self.worker_animal[wi] not in live_tiles and self.worker_animal[wi] is not None:
                # Keep the lease only if the animal exists at all (tasks may be
                # momentarily empty mid-day); drop if the tile itself is gone.
                pass

        assigned: Set[int] = set()          # task indices claimed this turn
        claimed_animals: Set[Tuple] = set()  # animal tiles claimed this turn
        actions = []

        for i, a_pos in enumerate(agents):
            invs = obs.get("private", {}).get("inventories", [])
            inv = invs[i] if i < len(invs) else {}
            role = self.worker_sectors.get(i, "NW")
            carried_wheat = inv.get("WHEAT", 0)
            carried_products = sum(inv.get(r, 0) for r in PRODUCT_ITEMS)
            dist_to_shed = min(manhattan(a_pos, s) for s in SHED_TILES)
            at_shed_ring = a_pos in SHED_SET or self._is_shed_adjacent(a_pos)
            leased = self.worker_animal.get(i) is not None

            # ── Inventory management ──
            # The env auto-drops the inventories at midnight; the m5 sells the
            # shed goods the next morning. Only the FINAL day needs the manual
            # dump (so the day-29 sells can move the goods before the end).
            if day >= 29 and (carried_wheat > 0 or carried_products > 0):
                if at_shed_ring:
                    actions.append(["DROP", "WHEAT", carried_wheat] if carried_wheat > 0 else ["DROP", "MILK", 1])
                else:
                    actions.append(self._move_towards(a_pos, SHED_SET))
                continue

            best_task = None
            best_task_idx = None
            best_cost = float('inf')

            # 0. Multi-turn task lease (placements/builds/fertilize/cross-sector
            # sweeps): finish what we started — without this, the pickup+walk
            # tasks get re-claimed by a new worker every turn (the pickups
            # thrash).
            tlease = self.worker_task.get(i)
            if tlease is not None:
                t_op, t_pos = tlease
                found = None
                for t_idx, t in enumerate(tasks):
                    if t_idx in assigned:
                        continue
                    if t["op"] == t_op and t.get("pos") == t_pos:
                        found = (t_idx, t)
                        break
                if found is not None:
                    t_idx, t = found
                    best_task = t
                    best_task_idx = t_idx
                    best_cost = -t["priority"] * 1000
                else:
                    self.worker_task[i] = None
                    best_cost = float('inf')

            # 1. Affinity: finish the animal visit already in progress.
            aff = self.worker_animal.get(i)
            if best_task is None and aff is not None:
                for t_idx, t in animal_needs.get(aff, []):
                    if t_idx in assigned:
                        continue
                    if t["op"] == "FEED" and inv.get("WHEAT", 0) == 0 and shed_wheat == 0:
                        continue
                    cost = -t["priority"]
                    if cost < best_cost:
                        best_cost = cost
                        best_task = t
                        best_task_idx = t_idx
            if best_task is None:
                    self.worker_animal[i] = None
                    best_cost = float('inf')

            # 2. Claim: pick up a new animal visit (one animal per worker).
            if best_task is None:
                candidates = []
                for tile, tlist in animal_needs.items():
                    if tile in claimed_animals:
                        continue
                    if tile in self.worker_animal.values():
                        continue
                    best_p = 0
                    has_feed = False
                    for t_idx, t in tlist:
                        if t["op"] == "FEED" and inv.get("WHEAT", 0) == 0 and shed_wheat == 0:
                            continue
                        if t["priority"] > best_p:
                            best_p = t["priority"]
                        if t["op"] == "FEED":
                            has_feed = True
                    if best_p == 0:
                        continue
                    d = manhattan(a_pos, tile)
                    # FEED needs win ties; danger FEEDs (130) outrank everything.
                    cost = -(best_p * 1000) + d
                    # The escape-deadline triage: a danger feed this worker
                    # cannot reach (the shed pickup + the walk + the feed)
                    # before the midnight is doomed — the walk saves nothing.
                    if (has_feed and best_p >= TIER_FEED + 30
                            and dist_to_shed + d + 2 > (24 - hour)):
                        cost += 15000
                    candidates.append((cost, tile, has_feed, best_p))
                if candidates:
                    candidates.sort(key=lambda c: (c[0], -c[2]))
                    _, tile, _, _ = candidates[0]
                    claimed_animals.add(tile)
                    for t_idx, t in animal_needs[tile]:
                        if t_idx in assigned:
                            continue
                        if t["op"] == "FEED" and inv.get("WHEAT", 0) == 0 and shed_wheat == 0:
                            continue
                        cost = -t["priority"]
                        if cost < best_cost:
                            best_cost = cost
                            best_task = t
                            best_task_idx = t_idx

            # 3. Field work in the home sector: the sector-route following.
            # The route is the load-balanced nearest-neighbour partition of
            # the sector's tiles (the formulate), so each worker's the
            # assigned the contiguous sub-path — the no fighting over the
            # same tiles and the no cross-sector hops. The expert's rigid
            # cluster partition: the route advances past the dead/claimed
            # tiles each turn with NO greedy escape (the escape was the
            # residual cross-cluster pollution).
            if best_task is None:
                route = self.routes.get(i, []) if ROUTES_ON else []
                ri = self.route_idx.get(i, 0)
                while ri < len(route):
                    pos = route[ri]
                    if manhattan(a_pos, pos) > 4:
                        break
                    found = None
                    for t_idx, t in enumerate(tasks):
                        if t_idx in assigned:
                            continue
                        if t.get("pos") != pos:
                            continue
                        if t["op"] == "PLANT" and local_seeds.get(t.get("crop", ""), 0) == 0:
                            continue
                        if t["op"] == "FERTILIZE" and inv.get("FERTILIZER", 0) == 0:
                            continue
                        if found is None or t["priority"] > found[1]["priority"]:
                            found = (t_idx, t)
                    if found is not None:
                        best_task = found[1]
                        best_task_idx = found[0]
                        break
                    ri += 1
                self.route_idx[i] = ri
            if best_task is None:
                for t_idx, t in enumerate(tasks):
                    if t_idx in assigned:
                        continue
                    tx, ty = t.get("pos", a_pos)
                    in_sector = pos_in_sector(tx, ty, role)
                    near_shed = self._is_shed_adjacent((tx, ty)) or (tx, ty) in SHED_SET
                    build_op = t["op"] in {"BUILD_PASTURE", "BUILD_COOP", "PLACE_ANIMAL"}
                    if t["op"] == "PLANT" and local_seeds.get(t.get("crop", ""), 0) == 0:
                        continue
                    # The pocket-flow: the fert-less workers skip the FERTILIZE
                    # (no shed round-trips); the carriers apply their pocket
                    # fert directly (the advisor's one-stage pipeline).
                    if t["op"] == "FERTILIZE" and inv.get("FERTILIZER", 0) == 0:
                        continue
                    if not in_sector and not (near_shed and build_op):
                        continue
                    dist = manhattan(a_pos, (tx, ty))
                    cost = -(t["priority"] * 1000) + dist
                    # The deadline-aware triage: a critical tile this worker
                    # cannot reach before the midnight is already doomed — the
                    # walk saves nothing, so it drops below the ordinary work.
                    # (The advisor's slack test: the reachable criticals win;
                    # the doomed ones stop stealing the workers' days.)
                    if (t["op"] == "WATER" and t["priority"] >= TIER_CRITICAL_WATER
                            and dist + 1 > (24 - hour)):
                        cost += 15000
                    if cost < best_cost:
                        best_cost = cost
                        best_task = t
                        best_task_idx = t_idx

            if best_task is None:
                self.pass_reasons.append((obs["day"], obs["hour"], None, len(tasks),
                                          tuple(sorted(set(t["op"] for t in tasks)))))
                actions.append(["PASS"])
                continue

            assigned.add(best_task_idx)
            t = best_task
            if t["op"] in ANIMAL_MAINT_OPS:
                self.worker_animal[i] = t["pos"]
                self.worker_task[i] = None
            elif t["op"] in {"PLACE_ANIMAL", "BUILD_PASTURE", "BUILD_COOP", "FERTILIZE"}:
                self.worker_task[i] = (t["op"], t["pos"])
                self.worker_animal[i] = None
            else:
                self.worker_animal[i] = None
                self.worker_task[i] = None

            action = None
            if t["op"] == "FEED" and inv.get("WHEAT", 0) == 0:
                if at_shed_ring:
                    action = ["PICKUP", "WHEAT", 2]
                else:
                    action = self._move_towards(a_pos, SHED_SET)
            elif t["op"] == "FERTILIZE" and inv.get("FERTILIZER", 0) == 0:
                if at_shed_ring:
                    action = ["PICKUP", "FERTILIZER", 2]
                else:
                    action = self._move_towards(a_pos, SHED_SET)
            elif t["op"] == "PLACE_ANIMAL" and inv.get(t.get("animal", ""), 0) == 0:
                if at_shed_ring:
                    action = ["PICKUP", t["animal"], 1]
                else:
                    action = self._move_towards(a_pos, SHED_SET)
            elif a_pos == t["pos"]:
                op = t["op"]
                if op == "WATER":
                    action = ["WATER"]
                    self.last_water_step[t["pos"]] = obs["step"]
                elif op == "HARVEST": action = ["HARVEST"]
                elif op == "HARVEST_ANIMAL": action = ["HARVEST"]
                elif op == "CARE": action = ["CARE"]
                elif op == "COLLECT_FERTILIZER": action = ["COLLECT_FERTILIZER"]
                elif op == "FEED": action = ["FEED"]
                elif op == "CLEAR": action = ["DIG"]
                elif op == "PLACE_ANIMAL": action = ["PLACE", t["animal"]]
                elif op == "BUILD_PASTURE": action = ["BUILD_PASTURE"]
                elif op == "BUILD_COOP": action = ["BUILD_COOP"]
                elif op == "PLANT":
                    crop = t["crop"]
                    if local_seeds.get(crop, 0) > 0:
                        action = ["PLANT", crop]
                        local_seeds[crop] -= 1
                    else:
                        action = ["PASS"]
                elif op == "FERTILIZE": action = ["FERTILIZE"]
                else: action = [op]
            else:
                action = self._move_towards(a_pos, t["pos"])

            if not action:
                action = ["PASS"]
                self.pass_reasons.append((obs["day"], obs["hour"], best_task, len(tasks)))
            actions.append(action)

        farmer_action = actions[0] if actions else ["PASS"]
        hand_actions = actions[1:] if len(actions) > 1 else []

        if farmer_action and farmer_action[0] == "PLANT":
            if self.plant_queue: self.plant_queue.pop(0)
        for ha in hand_actions:
            if ha and ha[0] == "PLANT":
                if self.plant_queue: self.plant_queue.pop(0)

        self.unassigned_tasks = len(tasks) - len(assigned)
        return farmer_action, hand_actions, intents
