from dataclasses import dataclass

@dataclass(frozen=True)
class QueryPlan:
    requested_category: str
    queries: tuple[str, ...]
    cells: tuple[str, ...]

def build_queries(category: str, city: str, state: str, worker_count: int = 2) -> QueryPlan:
    base = f"{category.strip()} {city.strip()} {state.strip()}".strip()
    # Neutral geographic variations; never inject another business domain.
    zones = ("setor norte", "setor sul", "setor leste", "setor oeste")
    n = max(1, min(worker_count, len(zones)))
    return QueryPlan(category.strip(), tuple(f"{base} {zones[i]}" for i in range(n)), zones[:n])
