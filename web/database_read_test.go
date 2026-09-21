package web

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

type fakeDatabaseReader struct {
	page  JobPage
	job   Job
	place []Place
}

func (f fakeDatabaseReader) ListAllJobs(context.Context) ([]Job, error) {
	return f.page.Jobs, nil
}

func (f fakeDatabaseReader) ListJobs(context.Context, int, int) (JobPage, error) {
	return f.page, nil
}

func (f fakeDatabaseReader) GetJob(context.Context, string) (Job, error) {
	return f.job, nil
}

func (f fakeDatabaseReader) GetPlaces(context.Context, string) ([]Place, error) {
	return f.place, nil
}

func (f fakeDatabaseReader) ExportCSV(_ context.Context, _ string, path string) error {
	return os.WriteFile(path, []byte("database,csv\n"), 0o600)
}

func TestDatabaseReadModeRoutesExistingContracts(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "database")
	dir := t.TempDir()
	reader := fakeDatabaseReader{
		page:  JobPage{Jobs: []Job{{ID: "search-1", Status: StatusOK}}},
		job:   Job{ID: "search-1", Status: StatusOK},
		place: []Place{{Title: "No coordinates", Address: "DB", Latitude: 0, Longitude: 0}},
	}
	svc := NewService(nil, dir)
	svc.SetDatabaseReader(reader)

	page, err := svc.ListJobs(context.Background(), 1, 20)
	if err != nil || len(page.Jobs) != 1 || page.Jobs[0].ID != "search-1" {
		t.Fatalf("database list = %+v, err=%v", page, err)
	}
	job, err := svc.Get(context.Background(), "search-1")
	if err != nil || job.ID != "search-1" {
		t.Fatalf("database get = %+v, err=%v", job, err)
	}
	places, err := svc.GetPlaces(context.Background(), "search-1")
	if err != nil || len(places) != 1 || places[0].Title != "No coordinates" {
		t.Fatalf("database places = %+v, err=%v", places, err)
	}
	path, err := svc.GetCSV(context.Background(), "search-1")
	if err != nil {
		t.Fatalf("database csv: %v", err)
	}
	if filepath.Base(path) != "search-1.csv" {
		t.Fatalf("database csv path = %q", path)
	}
}

func TestDatabaseReadModeDoesNotSilentlyFallBack(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "database")
	svc := NewService(nil, t.TempDir())
	if _, err := svc.ListJobs(context.Background(), 1, 20); err == nil {
		t.Fatal("expected unavailable database read mode error")
	}
	if _, err := svc.GetPlaces(context.Background(), "search-1"); err == nil {
		t.Fatal("expected unavailable database read mode error for places")
	}
}

func TestAPIGetJobsUsesDatabaseReaderInDatabaseMode(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "database")
	databaseJobs := []Job{{ID: "search-db-1"}, {ID: "search-db-2"}}
	repo := &mockJobRepo{jobs: []Job{{ID: "sqlite-only"}}}
	svc := NewService(repo, t.TempDir())
	svc.SetDatabaseReader(fakeDatabaseReader{page: JobPage{Jobs: databaseJobs}})
	srv, err := New(svc, ":0")
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/v1/jobs", http.NoBody)
	rec := httptest.NewRecorder()
	srv.srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}

	var jobs []Job
	if err := json.Unmarshal(rec.Body.Bytes(), &jobs); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(jobs) != 2 || jobs[0].ID != "search-db-1" || jobs[1].ID != "search-db-2" {
		t.Fatalf("database jobs = %+v", jobs)
	}
}

func TestAPIGetJobsUsesSQLiteInCurrentMode(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "current")
	repoJobs := []Job{{ID: "sqlite-job"}}
	repo := &mockJobRepo{jobs: repoJobs}
	svc := NewService(repo, t.TempDir())
	svc.SetDatabaseReader(fakeDatabaseReader{page: JobPage{Jobs: []Job{{ID: "database-only"}}}})
	srv, err := New(svc, ":0")
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/v1/jobs", http.NoBody)
	rec := httptest.NewRecorder()
	srv.srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}

	var jobs []Job
	if err := json.Unmarshal(rec.Body.Bytes(), &jobs); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if len(jobs) != 1 || jobs[0].ID != "sqlite-job" {
		t.Fatalf("current-mode jobs = %+v", jobs)
	}
}
