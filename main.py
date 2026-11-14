import time
import sys
import os
from typing import Dict, Any

from m1_state_core import lint_actions
from m2_shadow_market import ShadowMarket
from m3_macro_lp import get_planner
from m4_dispatcher import MultiAgentDispatcher
from m5_micro_trader import MicroTrader

class AgentContext:
    def __init__(self, adversarial=False):
        self.shadow = ShadowMarket()
        self.planner = get_planner(adversarial=adversarial)
        self.dispatcher = MultiAgentDispatcher()
        self.trader = MicroTrader(adversarial=adversarial)
        
        self.lam = 5.0
        self.mu = 8.0
        self.rho = 1.3
        self.duals = {}
        
        # 1D timing stats
        self.t_m1 = 0.0
        self.t_m2 = 0.0
        self.t_m3 = 0.0
        self.t_m4 = 0.0

ctx = AgentContext()

def _step(obs: Dict[str, Any], c: "AgentContext") -> Dict[str, Any]:
    t_start = time.time()
    
    c.t_m1 = time.time() - t_start
    
    t2_start = time.time()
    # M2 Update
    c.shadow.update_from_obs(obs, obs, {})
    c.t_m2 = time.time() - t2_start
    
    t3_start = time.time()
    # M3 Macro Planner (daily at hour 0 or on shock)
    if obs["hour"] == 0:
        _, c.lam, c.mu, c.rho, c.duals = c.planner.solve(obs, horizon_days=30 - obs["day"])
    c.t_m3 = time.time() - t3_start
    
    t4_start = time.time()
    # M4 Dispatcher
    decisions = c.planner.prev_solution if c.planner.prev_solution else {"plant": {}, "buy_animal": {}, "hires": 0}
    farmer_action, hand_actions, intents = c.dispatcher.dispatch(obs, c.duals, decisions)
    c.t_m4 = time.time() - t4_start
    
    t5_start = time.time()
    # M5 Micro Trader
    obs["unassigned_tasks"] = c.dispatcher.unassigned_tasks
    market_orders = c.trader.compose_orders(obs, c.shadow, c.duals, intents, 0, decisions)
    
    actions = {
        "farmer": farmer_action,
        "hands": hand_actions,
        "market": market_orders
    }
    
    # Lint
    lint_actions(obs, actions)
    
    return actions

def agent(obs: Dict[str, Any], config: Dict[str, Any] = None) -> Dict[str, Any]:
    global ctx
    return _step(obs, ctx)
