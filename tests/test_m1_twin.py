import os
import random
import copy
import pytest
import kaggle_environments

from m1_state_core import step

def get_random_action(obs):
    acts = ["NORTH", "SOUTH", "EAST", "WEST", "WATER", "HARVEST", "PASS"]
    
    return {
        "farmer": [random.choice(acts)],
        "market": []
    }

@pytest.mark.skipif(os.environ.get("TWIN_AVAILABLE", "true").lower() == "false", reason="Skipping full twin fuzzing")
def test_twin_fuzzing():
    # We will do a mini version for 5 seeds to keep test time low, 
    # but theoretically we can do 500.
    for seed in range(42, 47):
        env = kaggle_environments.make('kaggriculture', configuration={'episodeSteps': 50, 'seed': seed})
        env.reset()
        
        while not env.done:
            obs = env.state[0].observation
            
            a1 = get_random_action(obs)
            a2 = get_random_action(obs)
            
            actions = [a1, a2]
            
            # Run M1 Step
            m1_next_obs = step(obs, {'episodeSteps': 50, 'seed': seed}, a1, a2)
            
            # Run Engine Step
            env.step(actions)
            engine_next_obs = env.state[0].observation
            
            # Compare state
            assert m1_next_obs["farms"] == engine_next_obs["farms"]
            assert m1_next_obs["private"]["shed"] == engine_next_obs["private"]["shed"]
            assert m1_next_obs["market"]["inventory"] == engine_next_obs["market"]["inventory"]
