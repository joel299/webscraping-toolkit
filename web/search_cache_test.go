package web

import "testing"

func TestSearchCacheKeyNormalizesStructuredCategoryAndLocation(t *testing.T) {
	first := JobData{
		Keywords: []string{"farmácias em Água Clara, MS"},
		Category: "Farmácia", City: "Água Clara", State: "MS",
		Lang: "pt", Depth: 1,
	}
	second := JobData{
		Keywords: []string{"FARMACIA + AGUA CLARA + MS"},
		Lang:     "PT", Depth: 1,
	}

	firstKey, err := SearchCacheKey(first)
	if err != nil {
		t.Fatalf("SearchCacheKey(first): %v", err)
	}
	secondKey, err := SearchCacheKey(second)
	if err != nil {
		t.Fatalf("SearchCacheKey(second): %v", err)
	}
	if firstKey != secondKey {
		t.Fatalf("equivalent searches produced different keys: %s != %s", firstKey, secondKey)
	}

	second.Depth++
	thirdKey, err := SearchCacheKey(second)
	if err != nil {
		t.Fatalf("SearchCacheKey(third): %v", err)
	}
	if firstKey == thirdKey {
		t.Fatal("different search depth should produce a different cache key")
	}
}
