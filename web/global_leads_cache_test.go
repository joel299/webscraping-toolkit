package web

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"sync"
	"testing"
	"time"
)

type cacheEntry struct {
	value []byte
	ttl   time.Duration
}

type fakeGlobalLeadsCache struct {
	mu          sync.Mutex
	entries     map[string]cacheEntry
	getErr      error
	setErr      error
	deleteErr   error
	getCalls    int
	setCalls    int
	deleteCalls int
}

func newFakeGlobalLeadsCache() *fakeGlobalLeadsCache {
	return &fakeGlobalLeadsCache{entries: make(map[string]cacheEntry)}
}

func (c *fakeGlobalLeadsCache) Get(_ context.Context, key string) ([]byte, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.getCalls++
	if c.getErr != nil {
		return nil, c.getErr
	}
	entry, ok := c.entries[key]
	if !ok {
		return nil, errGlobalLeadsCacheMiss
	}
	return append([]byte(nil), entry.value...), nil
}

func (c *fakeGlobalLeadsCache) Set(_ context.Context, key string, value []byte, ttl time.Duration) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.setCalls++
	if c.setErr != nil {
		return c.setErr
	}
	c.entries[key] = cacheEntry{value: append([]byte(nil), value...), ttl: ttl}
	return nil
}

func (c *fakeGlobalLeadsCache) Delete(_ context.Context, key string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.deleteCalls++
	if c.deleteErr != nil {
		return c.deleteErr
	}
	delete(c.entries, key)
	return nil
}

type countingGlobalLeadsReader struct {
	page  GlobalLeadsPage
	err   error
	calls int
}

func (r *countingGlobalLeadsReader) ListAllJobs(context.Context) ([]Job, error) { return nil, nil }
func (r *countingGlobalLeadsReader) ListJobs(context.Context, int, int) (JobPage, error) {
	return JobPage{}, nil
}
func (r *countingGlobalLeadsReader) ListGlobalLeads(context.Context, int, int) (GlobalLeadsPage, error) {
	r.calls++
	if r.err != nil {
		return GlobalLeadsPage{}, r.err
	}
	return r.page, nil
}
func (r *countingGlobalLeadsReader) GetJob(context.Context, string) (Job, error) { return Job{}, nil }
func (r *countingGlobalLeadsReader) GetPlaces(context.Context, string) ([]Place, error) {
	return nil, nil
}
func (r *countingGlobalLeadsReader) ExportCSV(context.Context, string, string) error { return nil }

func testGlobalLeadsService(t *testing.T) (*Service, *countingGlobalLeadsReader, *fakeGlobalLeadsCache) {
	t.Helper()
	t.Setenv("PROSPECT_READ_MODE", "database")
	t.Setenv("PROSPECT_CACHE_ENABLED", "true")
	reader := &countingGlobalLeadsReader{page: GlobalLeadsPage{
		Items:  []Place{{PlaceID: "lead-1", Title: "Alpha"}},
		Total:  1,
		Limit:  10,
		Offset: 0,
	}}
	cache := newFakeGlobalLeadsCache()
	svc := NewService(nil, t.TempDir())
	svc.SetDatabaseReader(reader)
	svc.SetGlobalLeadsCache(cache)
	return svc, reader, cache
}

func TestGlobalLeadsCacheDisabledBypassesRedis(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "database")
	t.Setenv("PROSPECT_CACHE_ENABLED", "false")
	reader := &countingGlobalLeadsReader{page: GlobalLeadsPage{Items: []Place{{PlaceID: "lead-1"}}}}
	cache := newFakeGlobalLeadsCache()
	svc := NewService(nil, t.TempDir())
	svc.SetDatabaseReader(reader)
	svc.SetGlobalLeadsCache(cache)

	if _, err := svc.ListGlobalLeads(context.Background(), 10, 0); err != nil {
		t.Fatalf("ListGlobalLeads: %v", err)
	}
	if reader.calls != 1 || cache.getCalls != 0 || cache.setCalls != 0 {
		t.Fatalf("disabled cache calls: reader=%d get=%d set=%d", reader.calls, cache.getCalls, cache.setCalls)
	}
	if svc.GlobalLeadsCacheStats().Bypass != 1 {
		t.Fatalf("expected one cache bypass, got %+v", svc.GlobalLeadsCacheStats())
	}
}

func TestGlobalLeadsCacheMissThenHitPreservesPayload(t *testing.T) {
	svc, reader, cache := testGlobalLeadsService(t)
	want, err := svc.ListGlobalLeads(context.Background(), 10, 0)
	if err != nil {
		t.Fatalf("miss: %v", err)
	}
	hit, err := svc.ListGlobalLeads(context.Background(), 10, 0)
	if err != nil {
		t.Fatalf("hit: %v", err)
	}
	if got, wantJSON := mustJSON(t, hit), mustJSON(t, want); string(got) != string(wantJSON) {
		t.Fatalf("cached payload changed: got=%s want=%s", got, wantJSON)
	}
	if reader.calls != 1 || cache.getCalls != 2 || cache.setCalls != 1 {
		t.Fatalf("miss/hit calls: reader=%d get=%d set=%d", reader.calls, cache.getCalls, cache.setCalls)
	}
	stats := svc.GlobalLeadsCacheStats()
	if stats.Miss != 1 || stats.Hit != 1 || stats.Errors != 0 {
		t.Fatalf("unexpected cache stats: %+v", stats)
	}
	if cache.entries[globalLeadsCacheKey(10, 0)].ttl != globalLeadsCacheTTL {
		t.Fatalf("TTL=%s, want %s", cache.entries[globalLeadsCacheKey(10, 0)].ttl, globalLeadsCacheTTL)
	}
}

func TestGlobalLeadsCacheKeyVariesByPagination(t *testing.T) {
	svc, reader, cache := testGlobalLeadsService(t)
	reader.page = GlobalLeadsPage{Items: []Place{{PlaceID: "page-0"}}, Limit: 1, Offset: 0}
	if _, err := svc.ListGlobalLeads(context.Background(), 1, 0); err != nil {
		t.Fatal(err)
	}
	reader.page = GlobalLeadsPage{Items: []Place{{PlaceID: "page-1"}}, Limit: 1, Offset: 1}
	if _, err := svc.ListGlobalLeads(context.Background(), 1, 1); err != nil {
		t.Fatal(err)
	}
	if len(cache.entries) != 2 || reader.calls != 2 {
		t.Fatalf("pagination keys did not isolate pages: keys=%d reader_calls=%d", len(cache.entries), reader.calls)
	}
}

func TestGlobalLeadsCacheTTLAndInvalidation(t *testing.T) {
	svc, reader, cache := testGlobalLeadsService(t)
	if _, err := svc.ListGlobalLeads(context.Background(), 10, 0); err != nil {
		t.Fatal(err)
	}
	key := globalLeadsCacheKey(10, 0)
	if cache.entries[key].ttl != 45*time.Second {
		t.Fatalf("unexpected cache TTL: %s", cache.entries[key].ttl)
	}
	svc.InvalidateGlobalLeadsCache(context.Background())
	if _, ok := cache.entries[key]; ok {
		t.Fatal("cache entry survived invalidation")
	}
	if _, err := svc.ListGlobalLeads(context.Background(), 10, 0); err != nil {
		t.Fatal(err)
	}
	if reader.calls != 2 || svc.GlobalLeadsCacheStats().Invalidated != 1 {
		t.Fatalf("invalidation was not observed: calls=%d stats=%+v", reader.calls, svc.GlobalLeadsCacheStats())
	}
}

func TestGlobalLeadsCacheUnavailableFallsBackToPostgres(t *testing.T) {
	svc, reader, cache := testGlobalLeadsService(t)
	cache.getErr = errors.New("connection refused")
	if _, err := svc.ListGlobalLeads(context.Background(), 10, 0); err != nil {
		t.Fatalf("fallback: %v", err)
	}
	if reader.calls != 1 || svc.GlobalLeadsCacheStats().Errors != 1 || svc.GlobalLeadsCacheStats().Fallback != 1 {
		t.Fatalf("fallback did not use PostgreSQL: calls=%d stats=%+v", reader.calls, svc.GlobalLeadsCacheStats())
	}
}

func TestGlobalLeadsCacheMalformedValueFallsBackSafely(t *testing.T) {
	svc, reader, cache := testGlobalLeadsService(t)
	cache.entries[globalLeadsCacheKey(10, 0)] = cacheEntry{value: []byte("not-json")}
	if _, err := svc.ListGlobalLeads(context.Background(), 10, 0); err != nil {
		t.Fatalf("malformed fallback: %v", err)
	}
	if reader.calls != 1 || cache.deleteCalls != 1 || svc.GlobalLeadsCacheStats().Errors != 1 || svc.GlobalLeadsCacheStats().Fallback != 1 {
		t.Fatalf("malformed value handling: reader=%d deletes=%d stats=%+v", reader.calls, cache.deleteCalls, svc.GlobalLeadsCacheStats())
	}
}

func TestGlobalLeadsCacheHitSurvivesPostgresFailure(t *testing.T) {
	svc, reader, _ := testGlobalLeadsService(t)
	if _, err := svc.ListGlobalLeads(context.Background(), 10, 0); err != nil {
		t.Fatal(err)
	}
	reader.err = errors.New("postgres unavailable")
	if _, err := svc.ListGlobalLeads(context.Background(), 10, 0); err != nil {
		t.Fatalf("cache hit should not require PostgreSQL: %v", err)
	}
	if reader.calls != 1 {
		t.Fatalf("PostgreSQL was called on cache hit: %d", reader.calls)
	}
}

func TestRedisGlobalLeadsCacheIntegration(t *testing.T) {
	if os.Getenv("PROSPECT_REDIS_INTEGRATION") != "1" {
		t.Skip("set PROSPECT_REDIS_INTEGRATION=1 to run against local Redis")
	}
	cache, err := NewRedisGlobalLeadsCache(context.Background(), "redis://127.0.0.1:6379/0")
	if err != nil {
		t.Fatalf("connect Redis: %v", err)
	}
	defer cache.Close()
	key := "gru95:test:global-leads"
	defer cache.Delete(context.Background(), key)
	if err := cache.Set(context.Background(), key, []byte(`{"items":[]}`), time.Second); err != nil {
		t.Fatalf("set Redis: %v", err)
	}
	value, err := cache.Get(context.Background(), key)
	if err != nil || string(value) != `{"items":[]}` {
		t.Fatalf("get Redis: value=%s err=%v", value, err)
	}
}

func mustJSON(t *testing.T, value GlobalLeadsPage) []byte {
	t.Helper()
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return encoded
}
