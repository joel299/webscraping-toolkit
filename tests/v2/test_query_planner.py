from packages.planner import build_queries

def test_planner_is_domain_agnostic():
    assert all('hamburgueria' not in q.lower() for q in build_queries('clinica','Campo Grande','MS').queries)
    assert all('clinica' not in q.lower() for q in build_queries('lanchonete','Campo Grande','MS').queries)

def test_planner_has_neutral_variations():
    p=build_queries('clinica','Campo Grande','MS')
    assert len(p.queries)==2 and p.queries[0]!=p.queries[1]
