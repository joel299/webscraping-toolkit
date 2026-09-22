package webrunner

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/gosom/google-maps-scraper/shadow"
	"github.com/gosom/google-maps-scraper/web"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/stretchr/testify/require"
)

func TestDatabaseReaderListSearchesAndAPIIntegration(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping PostgreSQL integration test in short mode")
	}
	dsn := os.Getenv("PROSPECT_DATABASE_URL")
	if dsn == "" {
		t.Skip("PROSPECT_DATABASE_URL is not configured")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	pool, err := pgxpool.New(ctx, dsn)
	require.NoError(t, err)
	defer pool.Close()
	require.NoError(t, pool.Ping(ctx))

	_, err = pool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS public.prospect_searches (
			search_id TEXT PRIMARY KEY,
			job_id TEXT NOT NULL,
			job_name TEXT NOT NULL,
			query TEXT,
			location TEXT,
			category TEXT,
			requested_limit INT DEFAULT 0,
			status TEXT NOT NULL DEFAULT 'created',
			created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			completed_at TIMESTAMPTZ
		)`)
	require.NoError(t, err)
	defer func() {
		_, _ = pool.Exec(context.Background(), "DROP TABLE IF EXISTS public.prospect_searches")
	}()
	_, err = pool.Exec(ctx, "TRUNCATE TABLE public.prospect_searches CASCADE")
	require.NoError(t, err)

	writer := shadow.NewWriter(pool, time.Second, 1)
	reader := databaseReader{writer: writer}

	jobs, err := reader.ListAllJobs(ctx)
	require.NoError(t, err)
	require.Empty(t, jobs)

	base := time.Now().UTC().Add(-time.Hour)
	_, err = pool.Exec(ctx, `
		INSERT INTO public.prospect_searches
			(search_id, job_id, job_name, query, location, category, requested_limit, status, created_at, completed_at)
		VALUES
			($1, $2, $3, $4, $5, $6, $7, $8, $9, NULL),
			($10, $11, $12, $13, $14, $15, $16, $17, $18, $19),
			($20, $21, $22, $23, $24, $25, $26, $27, $28, NULL),
			($29, $30, $31, $32, $33, $34, $35, $36, $37, $38)`,
		"search-created", "job-created", "Created", "q1", "loc", "cat", 10, "created", base,
		"search-running", "job-running", "Running", "q2", "loc", "cat", 20, "running", base.Add(time.Minute), base.Add(time.Minute+time.Second),
		"search-completed", "job-completed", "Completed", "q3", "loc", "cat", 30, "completed", base.Add(2*time.Minute), base.Add(2*time.Minute+time.Second),
		"search-failed", "job-failed", "Failed", "q4", "loc", "cat", 40, "failed", base.Add(3*time.Minute), base.Add(3*time.Minute+time.Second),
	)
	require.NoError(t, err)

	jobs, err = reader.ListAllJobs(ctx)
	require.NoError(t, err)
	require.Len(t, jobs, 4)
	require.Equal(t, "job-failed", jobs[0].ID)
	require.Equal(t, web.StatusFailed, jobs[0].Status)
	require.Equal(t, web.StatusOK, jobs[1].Status)
	require.Equal(t, web.StatusWorking, jobs[2].Status)
	require.Equal(t, web.StatusPending, jobs[3].Status)

	page, err := reader.ListJobs(ctx, 2, 2)
	require.NoError(t, err)
	require.Equal(t, 2, page.TotalPages)
	require.Equal(t, 4, page.Total)
	require.Len(t, page.Jobs, 2)
	require.Equal(t, "job-running", page.Jobs[0].ID)

	svc := web.NewService(nil, t.TempDir())
	svc.SetDatabaseReader(reader)
	srv, err := web.New(svc, ":0")
	require.NoError(t, err)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/jobs", http.NoBody)
	rec := httptest.NewRecorder()
	srv.Handler().ServeHTTP(rec, req)
	require.Equal(t, http.StatusOK, rec.Code)

	var apiJobs []web.Job
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &apiJobs))
	require.Len(t, apiJobs, 4)
}
