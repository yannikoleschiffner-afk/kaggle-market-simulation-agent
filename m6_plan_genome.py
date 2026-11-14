# The evolvable day-plan genome. The m3/m4/m5 consult this; the first matching
# rule's actions override the hand-coded targets. The absent fields = the
# fall through to the existing logic, so the genomes start as the current
# strategy and drift freely from there.
#
# The rule format:
#   {'cond': {'day_lo': 0, 'day_hi': 9, 'milk_min': 2, 'yarn_min': None,
#             'money_min': None, 'enemy_sheep_min': None, 'enemy_cows_min': None,
#             'enemy_plants_min': None},
#    'act':  {'hire_delta': 5, 'cow_delta': 0, 'sheep_delta': 11, ...}}

GLOBAL_GENOME = None  # the set by the evolver before each game
LAST_FIRED = -1       # the rule index that fired last (the for the credit assignment)

COND_FIELDS = ('day_lo', 'day_hi', 'milk_min', 'yarn_min', 'money_min',
               'enemy_sheep_min', 'enemy_cows_min', 'enemy_plants_min')
# The deltas: the genome nudges the hand-coded baseline instead of the
# replacing it — the safety nets survive the bad mutations. The 'land' stays
# the absolute 0/1 flag.
ACT_FIELDS = ('hire_delta', 'cow_delta', 'sheep_delta', 'goose_delta',
              'melon_delta', 'straw_delta', 'plantable_delta', 'land',
              'water_tier_delta', 'plant_tier_delta', 'build_tier_delta',
              'harvest_tier_delta', 'care_tier_delta',
              'pace_delta', 'wool_hold_delta', 'wheat_reserve_delta')

def matches(cond, day, milk, yarn, money, enemy):
    if cond.get('day_lo') is not None and day < cond['day_lo']:
        return False
    if cond.get('day_hi') is not None and day > cond['day_hi']:
        return False
    if cond.get('milk_min') is not None and milk < cond['milk_min']:
        return False
    if cond.get('yarn_min') is not None and yarn < cond['yarn_min']:
        return False
    if cond.get('money_min') is not None and money < cond['money_min']:
        return False
    if enemy is not None:
        if cond.get('enemy_sheep_min') is not None and enemy.get('sheep', 0) < cond['enemy_sheep_min']:
            return False
        if cond.get('enemy_cows_min') is not None and enemy.get('cows', 0) < cond['enemy_cows_min']:
            return False
        if cond.get('enemy_plants_min') is not None and enemy.get('plants', 0) < cond['enemy_plants_min']:
            return False
    return True

def consult(day, milk, yarn, money, enemy=None):
    global LAST_FIRED
    g = GLOBAL_GENOME
    if not g:
        LAST_FIRED = -1
        return {}
    for i, rule in enumerate(g['rules']):
        if matches(rule.get('cond', {}), day, milk, yarn, money, enemy):
            LAST_FIRED = i
            return rule.get('act', {})
    LAST_FIRED = -1
    return {}
