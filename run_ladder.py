from kaggle_environments import make
import json
import importlib

def run_match(agent1, agent2, seed):
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    env.run([agent1, agent2])
    
    final_state = env.steps[-1]
    bank1 = final_state[0].reward
    bank2 = final_state[1].reward
    
    if bank1 > bank2:
        return 1, bank1 - bank2
    elif bank1 < bank2:
        return -1, bank1 - bank2
    return 0, 0

def run_ladder():
    opponents = [
        "starter", 
        "random", 
        "pass", 
        "arena/naive_melon_dumper.py", 
        "arena/fertilizer_crasher.py", 
        "arena/pure_cropper.py", 
        "arena/wheat_buyer.py"
    ]
    seeds = [42, 43, 44, 45, 46, 47, 48, 49, 50, 51]
    
    our_agent = "main.py"
    
    print(f"Running ladder against {len(opponents)} opponents over {len(seeds)} seeds...")
    
    for opp in opponents:
        wins = 0
        losses = 0
        ties = 0
        total_delta = 0
        
        for seed in seeds:
            try:
                res, delta = run_match(our_agent, opp, seed)
                if res == 1: wins += 1
                elif res == -1: losses += 1
                else: ties += 1
                total_delta += delta
            except Exception as e:
                print(f"Error in match {our_agent} vs {opp} (seed {seed}): {e}")
                
        print(f"vs {opp:25s}: {wins}W - {losses}L - {ties}T (Avg Delta: {total_delta/len(seeds):.1f})")

if __name__ == "__main__":
    run_ladder()
