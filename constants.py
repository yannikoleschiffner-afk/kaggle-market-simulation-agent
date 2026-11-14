from typing import Dict, Any

MARKET_I0 = 10000

MARKET_PARAMS = {
    'WHEAT': {'base': 25, 'I0': MARKET_I0, 'T': 400, 'below_func': 'sqrt', 'below_target': 0.8, 'above_func': 'log', 'above_target': 0.2}, 
    'CARROT': {'base': 35, 'I0': MARKET_I0, 'T': 450, 'below_func': 'hinge', 'below_target': 1.0, 'above_func': 'sqrt', 'above_target': 0.7}, 
    'TOMATO': {'base': 60, 'I0': MARKET_I0, 'T': 200, 'below_func': 'hinge', 'below_target': 0.4, 'above_func': 'sqrt', 'above_target': 0.6}, 
    'STRAWBERRY': {'base': 120, 'I0': MARKET_I0, 'T': 100, 'below_func': 'sqrt', 'below_target': 0.7, 'above_func': 'linear', 'above_target': 1.6}, 
    'MELON': {'base': 250, 'I0': MARKET_I0, 'T': 300, 'below_func': 'log', 'below_target': 0.2, 'above_func': 'sq', 'above_target': 3.6}, 
    'EGG': {'base': 50, 'I0': MARKET_I0, 'T': 332, 'below_func': 'hinge', 'below_target': 0.4, 'above_func': 'log', 'above_target': 0.2}, 
    'MILK': {'base': 160, 'I0': MARKET_I0, 'T': 122, 'below_func': 'sqrt', 'below_target': 0.6, 'above_func': 'linear', 'above_target': 1.6}, 
    'WOOL': {'base': 200, 'I0': MARKET_I0, 'T': 105, 'below_func': 'log', 'below_target': 0.2, 'above_func': 'sq', 'above_target': 3.2}, 
    'FERTILIZER': {'base': 100, 'I0': MARKET_I0, 'T': 200, 'below_func': 'linear', 'below_target': 0.4, 'above_func': 'linear', 'above_target': 0.4}
}

SHOPS = {
    'BAKERY': ['EGG', 'WHEAT'], 
    'PIZZA_SHOP': ['MILK', 'TOMATO', 'WHEAT'], 
    'BRUNCH_SPOT': ['EGG', 'WHEAT', 'STRAWBERRY'], 
    'YARN_STORE': ['WOOL'], 
    'ICE_CREAM_SHOP': ['STRAWBERRY', 'MILK', 'WHEAT'], 
    'PET_CAFE': ['CARROT'], 
    'SMOOTHIE_SHOP': ['STRAWBERRY', 'MILK'], 
    'FARMERS_MARKET': ['WHEAT', 'CARROT', 'TOMATO', 'STRAWBERRY']
}

CROPS = {
    'WHEAT': {'seed': 10, 'first_yield_day': 2, 'max_yield_day': 4, 'interval': 0, 'max_yield': 6, 'ongoing': False}, 
    'CARROT': {'seed': 20, 'first_yield_day': 2, 'max_yield_day': 3, 'interval': 0, 'max_yield': 4, 'ongoing': False}, 
    'TOMATO': {'seed': 50, 'first_yield_day': 8, 'max_yield_day': 8, 'interval': 1, 'max_yield': 4, 'ongoing': True}, 
    'STRAWBERRY': {'seed': 100, 'first_yield_day': 10, 'max_yield_day': 10, 'interval': 2, 'max_yield': 4, 'ongoing': True}, 
    'MELON': {'seed': 80, 'first_yield_day': 10, 'max_yield_day': 12, 'interval': 0, 'max_yield': 6, 'ongoing': False}
}

ANIMALS = {
    'GOOSE': {'cost': 300, 'structure': 'COOP', 'first_yield_day': 4, 'interval': 1, 'max_held': 4, 'product': 'EGG'}, 
    'COW': {'cost': 400, 'structure': 'PASTURE', 'first_yield_day': 8, 'interval': 2, 'max_held': 6, 'product': 'MILK'}, 
    'SHEEP': {'cost': 500, 'structure': 'PASTURE', 'first_yield_day': 6, 'interval': 3, 'max_held': 6, 'product': 'WOOL'}
}

# §3.6 Planting/purchase cutoff table (bank-by-day-29 constraint)
CUTOFF_DAYS = {
    'WHEAT': 25,
    'CARROT': 26,
    'MELON': 19, # 21 if fertilizer on hand
    'TOMATO': 18, # full, 21 partial
    'STRAWBERRY': 13, # full, 19 first-yield-only
    'GOOSE': 26,
    'COW': 17,
    'SHEEP': 19, # demand-conditional
}

# All tradeable resources (everything that can be in the shed and sold)
ALL_RESOURCES = ['WHEAT', 'CARROT', 'TOMATO', 'STRAWBERRY', 'MELON', 'EGG', 'MILK', 'WOOL', 'FERTILIZER']

# Squeeze manager parameters (§4.5)
SQUEEZE_PARAMS = {
    'u_arm': 1.0,         # projected u threshold to arm
    'u_disarm': 0.85,     # projected u threshold to disarm
    'u_trigger': 1.15,    # actual u threshold to start releasing
    'release_floor_frac': 0.5,  # release floor as fraction of target
    'ttl_extra_days': 2,  # extra days before forced disarm
    'min_shed_arm': 15,   # minimum shed + inbound to arm
    'max_price_walk': 0.2, # max intra-turn price walk (20%)
    'hinge_resources': ['CARROT', 'TOMATO', 'EGG'],  # squeeze-eligible
    'wheat_feed_reserve_days': 3,  # days of feed reserve for wheat
    'wheat_corner_price': 45,  # wheat corner hold price
}

# Endgame / overflow constants
ENDGAME_LIQUIDATE_DAY = 26  # day >= this → sell everything
SHED_OVERFLOW_THRESHOLD = 95  # shed projected > this → sell overflow

def get_tile(farm: Dict[str, Any], x: int, y: int):
    """Safe accessor for tiles. Corrects the x, y vs y, x confusion."""
    # tiles is accessed as tiles[y][x]
    return farm["tiles"][y][x]
