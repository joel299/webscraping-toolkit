package webrunner

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/gosom/google-maps-scraper/internal/supabaseapi"
	"github.com/gosom/google-maps-scraper/web"
)

// supabaseJobRepository preserves the durable local queue needed to resume
// work after a container restart, while making Supabase the active search/job
// record and lead database. Every create/status transition is mirrored via
// PostgREST before the operation is reported successful.
type supabaseJobRepository struct {
	local  web.JobRepository
	client *supabaseapi.Client
}

func (r *supabaseJobRepository) Close() error {
	if closer, ok := r.local.(interface{ Close() error }); ok {
		return closer.Close()
	}
	return nil
}
func (r *supabaseJobRepository) Get(ctx context.Context, id string) (web.Job, error) {
	return r.local.Get(ctx, id)
}
func (r *supabaseJobRepository) Select(ctx context.Context, p web.SelectParams) ([]web.Job, error) {
	return r.local.Select(ctx, p)
}
func (r *supabaseJobRepository) Delete(ctx context.Context, id string) error {
	return r.local.Delete(ctx, id)
}
func (r *supabaseJobRepository) ClaimPending(ctx context.Context) (*web.Job, error) {
	claimer, ok := r.local.(web.JobClaimer)
	if !ok {
		return nil, fmt.Errorf("local job queue does not support atomic claims")
	}
	job, err := claimer.ClaimPending(ctx)
	if err != nil {
		return nil, err
	}
	if err := r.syncSearch(ctx, job); err != nil {
		job.Status = web.StatusPending
		_ = r.local.Update(ctx, job)
		return nil, fmt.Errorf("sync claimed job to Supabase: %w", err)
	}
	return job, nil
}
func (r *supabaseJobRepository) RecoverWorking(ctx context.Context) (int64, error) {
	recoverer, ok := r.local.(interface {
		RecoverWorking(context.Context) (int64, error)
	})
	if !ok {
		return 0, nil
	}
	n, err := recoverer.RecoverWorking(ctx)
	if err != nil {
		return n, err
	}
	if n > 0 {
		pending, selectErr := r.local.Select(ctx, web.SelectParams{Status: web.StatusPending})
		if selectErr != nil {
			return n, selectErr
		}
		for i := range pending {
			if syncErr := r.syncSearch(ctx, &pending[i]); syncErr != nil {
				return n, fmt.Errorf("sync recovered job to Supabase: %w", syncErr)
			}
		}
	}
	return n, nil
}
func (r *supabaseJobRepository) Count(ctx context.Context, p web.SelectParams) (int, error) {
	if counter, ok := r.local.(interface {
		Count(context.Context, web.SelectParams) (int, error)
	}); ok {
		return counter.Count(ctx, p)
	}
	jobs, err := r.local.Select(ctx, p)
	return len(jobs), err
}
func (r *supabaseJobRepository) CreateFirstCredential(ctx context.Context, email, password string) error {
	store, ok := r.local.(web.CredentialStore)
	if !ok {
		return fmt.Errorf("local credential store is unavailable")
	}
	return store.CreateFirstCredential(ctx, email, password)
}
func (r *supabaseJobRepository) PasswordHash(ctx context.Context, email string) (string, error) {
	store, ok := r.local.(web.CredentialStore)
	if !ok {
		return "", fmt.Errorf("local credential store is unavailable")
	}
	return store.PasswordHash(ctx, email)
}
func (r *supabaseJobRepository) CreateOrReuseSearch(ctx context.Context, job *web.Job, key string, now time.Time, ttl time.Duration, force bool) (web.Job, bool, bool, error) {
	cache, ok := r.local.(web.SearchCacheRepository)
	if !ok {
		return web.Job{}, false, false, fmt.Errorf("local search cache is unavailable")
	}
	result, reused, fresh, err := cache.CreateOrReuseSearch(ctx, job, key, now, ttl, force)
	if err != nil {
		return web.Job{}, false, false, err
	}
	if err := r.syncSearch(ctx, &result); err != nil {
		return web.Job{}, false, false, fmt.Errorf("save job in Supabase: %w", err)
	}
	return result, reused, fresh, nil
}

func (r *supabaseJobRepository) Create(ctx context.Context, job *web.Job) error {
	if err := r.local.Create(ctx, job); err != nil {
		return err
	}
	if err := r.syncSearch(ctx, job); err != nil {
		_ = r.local.Delete(ctx, job.ID)
		return fmt.Errorf("save job in Supabase: %w", err)
	}
	return nil
}

func (r *supabaseJobRepository) Update(ctx context.Context, job *web.Job) error {
	if err := r.syncSearch(ctx, job); err != nil {
		return fmt.Errorf("update job in Supabase: %w", err)
	}
	return r.local.Update(ctx, job)
}

func (r *supabaseJobRepository) syncSearch(ctx context.Context, job *web.Job) error {
	if job == nil {
		return fmt.Errorf("job is nil")
	}
	status := map[string]string{web.StatusPending: "created", web.StatusWorking: "running", web.StatusOK: "completed", web.StatusFailed: "failed"}[strings.ToLower(job.Status)]
	if status == "" {
		return fmt.Errorf("unsupported job status %q", job.Status)
	}
	query := strings.Join(job.Data.Keywords, ", ")
	location := job.Data.GeoCoordinates()
	if job.Data.City != "" {
		location = strings.TrimSpace(strings.Join([]string{job.Data.City, job.Data.State}, ", "))
	}
	row := map[string]any{
		"search_id": job.ID, "job_id": job.ID, "job_name": job.Name, "query": query, "location": location,
		"category": job.Data.Category, "requested_limit": job.Data.Depth, "status": status, "updated_at": time.Now().UTC(),
	}
	if !job.Date.IsZero() {
		row["created_at"] = job.Date.UTC()
	}
	if status == "running" {
		row["started_at"] = time.Now().UTC()
	}
	if status == "completed" || status == "failed" {
		row["completed_at"] = time.Now().UTC()
	}
	_, _, err := r.client.Do(ctx, http.MethodPost, "prospect_searches", "on_conflict=search_id", row, "resolution=merge-duplicates,return=minimal")
	return err
}

// Ensure JSON is exercised here to catch unsupported job data types before
// any queue entry is committed to the local worker.
func marshalJobData(job *web.Job) ([]byte, error) { return json.Marshal(job.Data) }

var _ web.JobRepository = (*supabaseJobRepository)(nil)
var _ web.CredentialStore = (*supabaseJobRepository)(nil)
var _ web.SearchCacheRepository = (*supabaseJobRepository)(nil)
var _ web.JobClaimer = (*supabaseJobRepository)(nil)
