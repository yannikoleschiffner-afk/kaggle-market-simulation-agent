def agent(obs):
    """
    Pure Cropper:
    - Only buys and plants wheat continuously.
    """
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    step = obs["step"]
    
    market = []
    farmer = ["PASS"]
    
    fx, fy = me["farmer"]
    tile = me["tiles"][fy][fx]
    
    wheat_in_shed = private["shed"].get("WHEAT", 0)
    if wheat_in_shed > 0:
        market.append(["SELL", "WHEAT", wheat_in_shed])
        
    if private["seeds"].get("WHEAT", 0) == 0 and me["money"] >= 10:
        market.append(["BUY_SEED", "WHEAT", 1])
        
    if private["seeds"].get("WHEAT", 0) > 0 and tile is None:
        farmer = ["PLANT", "WHEAT"]
    elif tile and getattr(tile, "get", lambda x: None)("kind") == "PLANT":
        if tile.get("crop") == "WHEAT":
            if tile.get("yield_units", 0) > 0:
                farmer = ["HARVEST"]
            elif not tile.get("watered_today", False):
                farmer = ["WATER"]
            else:
                farmer = ["EAST"]
                
    if farmer == ["PASS"]:
        farmer = ["EAST"]
        
    return {"market": market, "farmer": farmer, "hands": []}
