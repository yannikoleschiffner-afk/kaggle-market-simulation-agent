def agent(obs):
    """
    Fertilizer Crasher:
    - Buys geese, places them in coops.
    - Collects fertilizer and sells it all to crash the market.
    """
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    step = obs["step"]
    
    market = []
    farmer = ["PASS"]
    
    fx, fy = me["farmer"]
    tile = me["tiles"][fy][fx]
    
    fert_in_shed = private["shed"].get("FERTILIZER", 0)
    if fert_in_shed > 0:
        market.append(["SELL", "FERTILIZER", fert_in_shed])
        
    if step == 0:
        market.append(["BUY_ANIMAL", "GOOSE", 5])
        
    # Logic to build coops and place geese
    # For simplicity, move east and build if empty
    geese = private["shed"].get("GOOSE", 0)
    
    if geese > 0 and tile is None:
        farmer = ["BUILD_COOP"]
    elif geese > 0 and tile and getattr(tile, "get", lambda x: None)("kind") == "COOP" and not tile.get("animal"):
        farmer = ["PLACE", "GOOSE"]
    elif tile and getattr(tile, "get", lambda x: None)("kind") == "COOP" and tile.get("animal") == "GOOSE":
        if tile.get("fertilizer_available", False):
            farmer = ["COLLECT_FERTILIZER"]
        else:
            # Move east to find next
            farmer = ["EAST"]
    else:
        if geese > 0:
            farmer = ["EAST"]
            
    return {"market": market, "farmer": farmer, "hands": []}
