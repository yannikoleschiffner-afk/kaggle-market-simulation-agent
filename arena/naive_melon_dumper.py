def agent(obs):
    """
    Naive Melon Dumper: 
    - Day 0: Buys MELON seeds and plants them.
    - Water them every day.
    - Harvest when yield_units > 0.
    - Sells all melons immediately.
    """
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    step = obs["step"]
    
    market = []
    farmer = ["PASS"]
    
    fx, fy = me["farmer"]
    tile = me["tiles"][fy][fx]
    
    melons_in_shed = private["shed"].get("MELON", 0)
    if melons_in_shed > 0:
        market.append(["SELL", "MELON", melons_in_shed])
        
    if step == 0:
        market.append(["BUY_SEED", "MELON", 15])
        
    # Simple state machine for the farmer
    if private["seeds"].get("MELON", 0) > 0 and tile is None:
        farmer = ["PLANT", "MELON"]
    elif tile and getattr(tile, "get", lambda x: None)("kind") == "PLANT":
        if tile.get("crop") == "MELON":
            if tile.get("yield_units", 0) > 0:
                farmer = ["HARVEST"]
            elif not tile.get("watered_today", False):
                farmer = ["WATER"]
                
    # Basic movement to find empty tile (dummy logic for archetype)
    if farmer == ["PASS"] and tile is not None and private["seeds"].get("MELON", 0) > 0:
        farmer = ["EAST"] # naive movement
        
    return {"market": market, "farmer": farmer, "hands": []}
