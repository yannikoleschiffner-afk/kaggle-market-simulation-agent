from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

@dataclass
class TurnIntents:
    """Explicit coupling between M4 and M5."""
    next_turn_seed_needs: Dict[str, int] = field(default_factory=dict)
    dump_day_mule_run_completions: Dict[str, int] = field(default_factory=dict)
