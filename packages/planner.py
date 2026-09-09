from dataclasses import dataclass

@dataclass(frozen=True)
class QueryPlan:
    requested_category: str
    queries: tuple[str, ...]
    cells: tuple[str, ...]

def build_queries(category: str, city: str, state: str, worker_count: int = 2) -> QueryPlan:
    base = f"{category.strip()} {city.strip()} {state.strip()}".strip()
    # Preserve exact intent for worker A; worker B receives a distinct neutral shard.
    zones = ("base", "setor norte", "setor sul", "setor leste", "setor oeste")
    n = max(1, min(worker_count, len(zones)))
    queries = (base,) + tuple(f"{base} {z}" for z in zones[1:n])
    return QueryPlan(category.strip(), queries, zones[:n])
