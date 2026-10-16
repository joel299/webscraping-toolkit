package web

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
	"time"
	"unicode"

	"github.com/redis/go-redis/v9"
	"golang.org/x/text/unicode/norm"
)

const (
	globalLeadsCacheVersion = "v1"
	globalLeadsCacheTTL     = 45 * time.Second
)

var errGlobalLeadsCacheMiss = errors.New("global leads cache miss")

// GlobalLeadsCache is the small cache contract used by the global leads read path.
// Implementations must treat errors as advisory: PostgreSQL remains authoritative.
type GlobalLeadsCache interface {
	Get(context.Context, string) ([]byte, error)
	Set(context.Context, string, []byte, time.Duration) error
	Delete(context.Context, string) error
}

type globalLeadsCacheCloser interface {
	GlobalLeadsCache
	Close() error
}

type RedisGlobalLeadsCache struct {
	client *redis.Client
}

// NewRedisGlobalLeadsCache connects to the configured local Redis instance.
func NewRedisGlobalLeadsCache(ctx context.Context, address string) (*RedisGlobalLeadsCache, error) {
	if strings.TrimSpace(address) == "" {
		address = "redis://127.0.0.1:6379/0"
	}
	options, err := redis.ParseURL(address)
	if err != nil {
		return nil, fmt.Errorf("parse redis url: %w", err)
	}
	client := redis.NewClient(options)
	if err := client.Ping(ctx).Err(); err != nil {
		_ = client.Close()
		return nil, fmt.Errorf("ping redis: %w", err)
	}
	return &RedisGlobalLeadsCache{client: client}, nil
}

func (c *RedisGlobalLeadsCache) Get(ctx context.Context, key string) ([]byte, error) {
	value, err := c.client.Get(ctx, key).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, errGlobalLeadsCacheMiss
	}
	return value, err
}

func (c *RedisGlobalLeadsCache) Set(ctx context.Context, key string, value []byte, ttl time.Duration) error {
	return c.client.Set(ctx, key, value, ttl).Err()
}

func (c *RedisGlobalLeadsCache) Delete(ctx context.Context, key string) error {
	return c.client.Del(ctx, key).Err()
}

func (c *RedisGlobalLeadsCache) Close() error {
	if c == nil || c.client == nil {
		return nil
	}
	return c.client.Close()
}

type globalLeadsCacheMetrics struct {
	hit         atomic.Uint64
	miss        atomic.Uint64
	errorCount  atomic.Uint64
	bypass      atomic.Uint64
	fallback    atomic.Uint64
	invalidated atomic.Uint64
}

// GlobalLeadsCacheStats is a snapshot of sanitized cache observability counters.
type GlobalLeadsCacheStats struct {
	Hit         uint64
	Miss        uint64
	Errors      uint64
	Bypass      uint64
	Fallback    uint64
	Invalidated uint64
}

func (m *globalLeadsCacheMetrics) snapshot() GlobalLeadsCacheStats {
	return GlobalLeadsCacheStats{
		Hit:         m.hit.Load(),
		Miss:        m.miss.Load(),
		Errors:      m.errorCount.Load(),
		Bypass:      m.bypass.Load(),
		Fallback:    m.fallback.Load(),
		Invalidated: m.invalidated.Load(),
	}
}

func globalLeadsCacheEnabled() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("PROSPECT_CACHE_ENABLED"))) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

func globalLeadsCacheKey(limit, offset int) string {
	return "prospect:global_leads:" + globalLeadsCacheVersion + ":" + strconv.Itoa(limit) + ":" + strconv.Itoa(offset)
}

func (s *Service) ListGlobalLeads(ctx context.Context, limit, offset int) (GlobalLeadsPage, error) {
	if !databaseReadMode() {
		return s.listLocalGlobalLeads(ctx, limit, offset)
	}
	if s.database == nil {
		return GlobalLeadsPage{}, fmt.Errorf("database read mode is unavailable")
	}

	if !globalLeadsCacheEnabled() || s.globalLeadsCache == nil {
		s.globalLeadsMetrics.bypass.Add(1)
		log.Printf("CACHE_BYPASS endpoint=global_leads reason=disabled_or_unconfigured")
		return s.database.ListGlobalLeads(ctx, limit, offset)
	}

	key := globalLeadsCacheKey(limit, offset)
	encoded, err := s.globalLeadsCache.Get(ctx, key)
	if err == nil {
		var page GlobalLeadsPage
		if unmarshalErr := json.Unmarshal(encoded, &page); unmarshalErr == nil {
			s.globalLeadsMetrics.hit.Add(1)
			log.Printf("CACHE_HIT endpoint=global_leads")
			return page, nil
		}
		s.globalLeadsMetrics.errorCount.Add(1)
		s.globalLeadsMetrics.fallback.Add(1)
		log.Printf("CACHE_ERROR endpoint=global_leads reason=malformed_payload")
		_ = s.globalLeadsCache.Delete(ctx, key)
	} else if errors.Is(err, errGlobalLeadsCacheMiss) {
		s.globalLeadsMetrics.miss.Add(1)
		log.Printf("CACHE_MISS endpoint=global_leads")
	} else {
		s.globalLeadsMetrics.errorCount.Add(1)
		s.globalLeadsMetrics.fallback.Add(1)
		log.Printf("CACHE_ERROR endpoint=global_leads reason=read_failure")
	}

	page, err := s.database.ListGlobalLeads(ctx, limit, offset)
	if err != nil {
		return GlobalLeadsPage{}, err
	}
	encoded, err = json.Marshal(page)
	if err != nil {
		return page, err
	}
	if err := s.globalLeadsCache.Set(ctx, key, encoded, globalLeadsCacheTTL); err != nil {
		s.globalLeadsMetrics.errorCount.Add(1)
		log.Printf("CACHE_ERROR endpoint=global_leads reason=write_failure")
	} else {
		s.globalLeadsCacheMu.Lock()
		s.globalLeadsCacheKeys[key] = struct{}{}
		s.globalLeadsCacheMu.Unlock()
	}
	return page, nil
}

func (s *Service) listLocalGlobalLeads(ctx context.Context, limit, offset int) (GlobalLeadsPage, error) {
	if limit < 1 {
		limit = 100
	}
	if limit > 500 {
		limit = 500
	}
	if offset < 0 {
		return GlobalLeadsPage{}, fmt.Errorf("invalid offset")
	}

	jobs, err := s.repo.Select(ctx, SelectParams{})
	if err != nil {
		return GlobalLeadsPage{}, fmt.Errorf("list local searches: %w", err)
	}

	items := make([]Place, 0)
	seen := make(map[string]struct{})
	for _, job := range jobs {
		if job.Status != StatusOK {
			continue
		}

		places, err := s.GetPlaces(ctx, job.ID)
		if errors.Is(err, ErrPlacesNotFound) {
			continue
		}
		if err != nil {
			return GlobalLeadsPage{}, fmt.Errorf("read local results for search %s: %w", job.ID, err)
		}

		for _, place := range places {
			keys := localPlaceKeys(place)
			duplicate := false
			for _, key := range keys {
				if _, ok := seen[key]; ok {
					duplicate = true
					break
				}
			}
			if duplicate {
				for _, key := range keys {
					seen[key] = struct{}{}
				}
				continue
			}
			for _, key := range keys {
				seen[key] = struct{}{}
			}
			place.JobID = job.ID
			place.JobName = job.Name
			items = append(items, place)
		}
	}

	total := len(items)
	if offset >= total {
		items = []Place{}
	} else {
		end := offset + limit
		if end > total {
			end = total
		}
		items = items[offset:end]
	}

	return GlobalLeadsPage{Items: items, Total: total, Limit: limit, Offset: offset}, nil
}

// localPlaceKeys returns stable identity aliases for one business. A matching
// normalized phone and address is the primary cross-search identity; the Maps
// place ID also joins records when one search omitted or changed contact data.
func localPlaceKeys(place Place) []string {
	keys := make([]string, 0, 2)
	phone := normalizePhone(place.Phone)
	address := normalizeBusinessAddress(place.Title, place.Address)
	if phone != "" && address != "" {
		keys = append(keys, "phone-address:"+phone+"|"+address)
	}
	if placeID := normalizeIdentityText(place.PlaceID); placeID != "" {
		keys = append(keys, "place-id:"+placeID)
	}
	if len(keys) > 0 {
		return keys
	}
	if link := strings.TrimSpace(strings.SplitN(place.Link, "?", 2)[0]); link != "" {
		return []string{"link:" + strings.ToLower(link)}
	}
	return []string{"name-address:" + normalizeIdentityText(place.Title) + "|" + normalizeIdentityText(place.Address)}
}

func normalizePhone(phone string) string {
	var digits strings.Builder
	for _, r := range phone {
		if unicode.IsDigit(r) {
			digits.WriteRune(r)
		}
	}
	value := digits.String()
	// Google results sometimes include Brazil's country code and sometimes do not.
	if strings.HasPrefix(value, "55") && (len(value) == 12 || len(value) == 13) {
		value = value[2:]
	}
	return value
}

func normalizeBusinessAddress(title, address string) string {
	value := normalizeIdentityText(address)
	name := normalizeIdentityText(title)
	// Some Google records prefix the address with the business name. Remove
	// that prefix so it matches the same street address without the name.
	if name != "" && strings.HasPrefix(value, name) {
		value = strings.TrimPrefix(value, name)
	}
	return value
}

func normalizeIdentityText(value string) string {
	value = strings.ToLower(norm.NFD.String(strings.TrimSpace(value)))
	var normalized strings.Builder
	for _, r := range value {
		if unicode.Is(unicode.Mn, r) {
			continue
		}
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			normalized.WriteRune(r)
		}
	}
	return normalized.String()
}

// SetGlobalLeadsCache enables the injectable cache used by the global leads read path.
func (s *Service) SetGlobalLeadsCache(cache GlobalLeadsCache) {
	s.globalLeadsCache = cache
}

// GlobalLeadsCacheStats returns sanitized counters for the cache read path.
func (s *Service) GlobalLeadsCacheStats() GlobalLeadsCacheStats {
	return s.globalLeadsMetrics.snapshot()
}

// InvalidateGlobalLeadsCache removes the requested global leads namespace.
// The current bounded read path has a single namespace; deleting known keys is
// avoided so invalidation remains safe as pagination variants are added.
func (s *Service) InvalidateGlobalLeadsCache(ctx context.Context) {
	if !globalLeadsCacheEnabled() || s.globalLeadsCache == nil {
		return
	}
	// The service tracks keys populated during this process and invalidates them
	// explicitly; this avoids Redis KEYS/SCAN on a production-sized database.
	s.globalLeadsCacheMu.Lock()
	keys := make([]string, 0, len(s.globalLeadsCacheKeys))
	for key := range s.globalLeadsCacheKeys {
		keys = append(keys, key)
	}
	s.globalLeadsCacheKeys = make(map[string]struct{})
	s.globalLeadsCacheMu.Unlock()
	for _, key := range keys {
		if err := s.globalLeadsCache.Delete(ctx, key); err != nil {
			log.Printf("CACHE_ERROR endpoint=global_leads reason=invalidation_failure")
			continue
		}
		s.globalLeadsMetrics.invalidated.Add(1)
	}
}
