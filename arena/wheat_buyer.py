def agent(obs):
    """
    Wheat Buyer:
    - Buys wheat on the market every turn if it has money.
    """
    player = obs["player"]
    me = obs["farms"][player]
    
    market = []
    
    # Very crude approximation: if we have roughly enough money for 1 wheat
    if me["money"] > 30:
        market.append(["BUY_PRODUCT", "WHEAT", 1])
        
    return {"market": market, "farmer": ["PASS"], "hands": []}
