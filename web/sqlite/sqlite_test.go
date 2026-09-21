//nolint:testpackage // tests the private SQLite repository and schema directly
package sqlite

import (
	"context"
	"errors"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gosom/google-maps-scraper/web"
)

func newTestRepo(t *testing.T) *repo {
	t.Helper()

	db, err := initDatabase(":memory:")
	if err != nil {
		t.Fatalf("initDatabase: %v", err)
	}

	t.Cleanup(func() {
		if err := db.Close(); err != nil {
			t.Errorf("close database: %v", err)
		}
	})

	return &repo{db: db}
}

func createTestJob(t *testing.T, repo *repo, id string, date time.Time) {
	t.Helper()

	job := web.Job{ID: id, Name: id, Date: date, Status: web.StatusPending}
	if err := repo.Create(context.Background(), &job); err != nil {
		t.Fatalf("Create(%q): %v", id, err)
	}
}

func newFileRepo(t *testing.T, path string) *repo {
	t.Helper()

	db, err := initDatabase(path)
	if err != nil {
		t.Fatalf("initDatabase(%q): %v", path, err)
	}
	t.Cleanup(func() {
		if err := db.Close(); err != nil {
			t.Errorf("close database: %v", err)
		}
	})
	return &repo{db: db}
}

func TestClaimPendingConcurrentConnectionsClaimsOneJob(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "jobs.db")
	writer := newFileRepo(t, dbPath)
	claimer := newFileRepo(t, dbPath)
	createTestJob(t, writer, "only-job", time.Unix(1, 0))

	start := make(chan struct{})
	results := make(chan struct {
		job *web.Job
		err error
	}, 2)
	var ready sync.WaitGroup
	ready.Add(2)
	claim := func(repo *repo) {
		ready.Done()
		<-start
		job, err := repo.ClaimPending(context.Background())
		results <- struct {
			job *web.Job
			err error
		}{job: job, err: err}
	}
	go claim(writer)
	go claim(claimer)
	ready.Wait()
	close(start)

	claimed := 0
	noJob := 0
	for range 2 {
		result := <-results
		if result.job != nil {
			claimed++
			if result.job.ID != "only-job" || result.job.Status != web.StatusWorking {
				t.Fatalf("unexpected claim: %+v", result.job)
			}
		}
		if errors.Is(result.err, web.ErrNoJobAvailable) {
			noJob++
		} else if result.job == nil && result.err != nil {
			t.Fatalf("claim failed: %v", result.err)
		}
	}
	if claimed != 1 || noJob != 1 {
		t.Fatalf("claimed=%d no_job=%d, want one of each", claimed, noJob)
	}

	job, err := writer.Get(context.Background(), "only-job")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if job.Status != web.StatusWorking {
		t.Fatalf("status=%q, want %q", job.Status, web.StatusWorking)
	}
}

func TestClaimPendingConcurrentWorkersClaimUniqueJobs(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "jobs.db")
	workerA := newFileRepo(t, dbPath)
	workerB := newFileRepo(t, dbPath)
	for i, id := range []string{"job-a", "job-b", "job-c"} {
		createTestJob(t, workerA, id, time.Unix(int64(i+1), 0))
	}

	start := make(chan struct{})
	results := make(chan *web.Job, 2)
	var ready sync.WaitGroup
	ready.Add(2)
	claim := func(repo *repo) {
		ready.Done()
		<-start
		job, err := repo.ClaimPending(context.Background())
		if err != nil {
			t.Errorf("claim: %v", err)
			return
		}
		results <- job
	}
	go claim(workerA)
	go claim(workerB)
	ready.Wait()
	close(start)

	seen := make(map[string]bool)
	for range 2 {
		job := <-results
		if seen[job.ID] {
			t.Fatalf("duplicate claim for %q", job.ID)
		}
		seen[job.ID] = true
	}
	if len(seen) != 2 {
		t.Fatalf("claimed %d unique jobs, want 2", len(seen))
	}
}

func TestClaimPendingSingleProcessLifecycle(t *testing.T) {
	repo := newTestRepo(t)
	createTestJob(t, repo, "single-job", time.Unix(1, 0))

	job, err := repo.ClaimPending(context.Background())
	if err != nil {
		t.Fatalf("ClaimPending: %v", err)
	}
	if job.Status != web.StatusWorking {
		t.Fatalf("status=%q, want %q", job.Status, web.StatusWorking)
	}

	job.Status = web.StatusOK
	if err := repo.Update(context.Background(), job); err != nil {
		t.Fatalf("Update: %v", err)
	}
	if _, err := repo.ClaimPending(context.Background()); !errors.Is(err, web.ErrNoJobAvailable) {
		t.Fatalf("second claim error=%v, want ErrNoJobAvailable", err)
	}
}

func TestSelectSupportsOffsetWithoutLimit(t *testing.T) {
	repo := newTestRepo(t)

	createTestJob(t, repo, "a", time.Unix(1, 0))
	createTestJob(t, repo, "b", time.Unix(2, 0))
	createTestJob(t, repo, "c", time.Unix(3, 0))

	jobs, err := repo.Select(context.Background(), web.SelectParams{Offset: 1})
	if err != nil {
		t.Fatalf("Select: %v", err)
	}

	if len(jobs) != 2 || jobs[0].ID != "b" || jobs[1].ID != "a" {
		t.Fatalf("unexpected jobs: %+v", jobs)
	}
}

func TestSelectOrdersSameSecondJobsByID(t *testing.T) {
	repo := newTestRepo(t)
	createdAt := time.Unix(1, 0)

	createTestJob(t, repo, "b", createdAt)
	createTestJob(t, repo, "c", createdAt)
	createTestJob(t, repo, "a", createdAt)

	jobs, err := repo.Select(context.Background(), web.SelectParams{})
	if err != nil {
		t.Fatalf("Select: %v", err)
	}

	want := []string{"c", "b", "a"}
	for i := range want {
		if jobs[i].ID != want[i] {
			t.Fatalf("job %d: got %q, want %q", i, jobs[i].ID, want[i])
		}
	}
}

func TestSchemaIndexesJobPaginationOrder(t *testing.T) {
	repo := newTestRepo(t)

	var statement string

	err := repo.db.QueryRowContext(
		context.Background(),
		`SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'idx_jobs_created_at_id'`,
	).Scan(&statement)
	if err != nil {
		t.Fatalf("query pagination index: %v", err)
	}

	want := strings.Fields("CREATE INDEX idx_jobs_created_at_id ON jobs (created_at DESC, id DESC)")
	if strings.Join(strings.Fields(statement), " ") != strings.Join(want, " ") {
		t.Fatalf("unexpected index: %q", statement)
	}
}
