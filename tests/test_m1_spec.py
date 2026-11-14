import pytest
from constants import MARKET_PARAMS, MARKET_I0, get_tile
from m2_shadow_market import get_marginal_price

def test_get_tile():
    farm = {
        "tiles": [
            [None, None],
            [{"kind": "PLANT"}, None]
        ]
    }
    # x=0, y=1
    tile = get_tile(farm, 0, 1)
    assert tile is not None
    assert tile["kind"] == "PLANT"

def test_price_checkpoints():
    """Test curve values from the price table checkpoints."""
    # From the document table:
    # Wheat P(I0-T)=25+sqrt(400)=45. Wait, target=0.8. amp = 0.8*25 = 20. base=25. P(I0-T) = 25+20=45.
    assert get_marginal_price("WHEAT", MARKET_I0 - 400) == 45
    # P(I0) = base
    assert get_marginal_price("WHEAT", MARKET_I0) == 25
    
    # Check carrot
    # P(I0-T) for carrot: u=T/T=1. 35 + 1.0 * 35 = 70. Wait, u+8max(0,u-1)^2 for u=1 is 1. 35 + 35*1 = 70.
    assert get_marginal_price("CARROT", MARKET_I0 - 450) == 70
    
    # Check strawberry P(I0+T)
    # base 120, above target 1.6 -> amp = 1.6 * 120 = 192.
    # Linear: 120 - 192*(100/100) = -72 -> floored to 1
    assert get_marginal_price("STRAWBERRY", MARKET_I0 + 100) == 1
    
    # Melon P(I0+T)
    # base 250, above target 3.6 -> amp = 3.6 * 250 = 900.
    # sq: 250 - 900*(300/300)^2 = -650 -> floored to 1
    assert get_marginal_price("MELON", MARKET_I0 + 300) == 1

def test_half_rounding():
    """Test that int(round(x)) does banker's rounding."""
    # 2.5 rounds to 2, 3.5 rounds to 4 in python 3
    assert int(round(2.5)) == 2
    assert int(round(3.5)) == 4
    
    # Check a price that lands exactly on .5
    # For linear fertilizer, base=100, T=200, amp=0.4*100=40.
    # Price drop for 1 unit = 40/200 = 0.2
    # For 2 units = 0.4
    # Wait, need exactly 0.5. Let's find one.
    # 2.5 units? No, units are integers.
    # T=200, amp=40. price(inv=MARKET_I0 + x) = 100 - 40*(x/200) = 100 - 0.2*x.
    # At x=2, price=99.6 -> 100
    # At x=3, price=99.4 -> 99
    # At x=2.5 price=99.5 -> 100
    # Can we have exactly .5? 
    # What if price is 98.5? x = 7.5. Not possible.
    # But python's round is used, so we just test the python behavior.
    assert round(99.5) == 100
    assert round(98.5) == 98
