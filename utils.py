import re
from typing import List, Dict, Any

def slug(s: str) -> str:
    if not isinstance(s, str):
        return ""
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()

def uniq(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out

def print_json(title: str, obj: Any):
    import json
    try:
        print(f"{title}\n{json.dumps(obj, indent=2)}")
    except Exception:
        print(title, obj)

def stops_param_for_fare(stops: List[Dict[str, float]] | None) -> str | None:
    if not stops:
        return None
    # fare/all expects a JSON string for stops (from your logs)
    import json
    return json.dumps([{"lat": s["lat"], "lng": s["lng"]} for s in stops])

def strip_asterisks(text: str) -> str:
    """
    Output guardrail: Strip all asterisks (*) from assistant output.
    This ensures clean text output without markdown formatting characters.
    """
    if not isinstance(text, str):
        return text
    return text.replace("*", "")
