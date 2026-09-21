package web

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
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

func (f fakeDatabaseReader) ListGlobalLeads(_ context.Context, limit, offset int) (GlobalLeadsPage, error) {
	start := offset
	if start > len(f.place) {
		start = len(f.place)
	}
	end := start + limit
	if end > len(f.place) {
		end = len(f.place)
	}
	return GlobalLeadsPage{Items: f.place[start:end], Total: len(f.place), Limit: limit, Offset: offset}, nil
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

func TestAPIGlobalLeadsUsesAggregatedDatabaseReadModel(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "database")
	repo := &mockJobRepo{}
	reader := fakeDatabaseReader{place: []Place{
		{PlaceID: "place-1", Title: "Alpha", JobID: "search-1", JobName: "Busca A"},
		{PlaceID: "place-2", Title: "Beta", JobID: "search-2", JobName: "Busca B"},
	}}
	srv, err := New(NewService(repo, t.TempDir()), ":0")
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	srv.svc.SetDatabaseReader(reader)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/leads?limit=1&offset=1", http.NoBody)
	rec := httptest.NewRecorder()
	srv.srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}

	var page GlobalLeadsPage
	if err := json.Unmarshal(rec.Body.Bytes(), &page); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if page.Total != 2 || page.Limit != 1 || page.Offset != 1 || len(page.Items) != 1 || page.Items[0].JobID != "search-2" {
		t.Fatalf("global leads page = %+v", page)
	}
}

type failingGlobalReader struct{ fakeDatabaseReader }

func (failingGlobalReader) ListGlobalLeads(context.Context, int, int) (GlobalLeadsPage, error) {
	return GlobalLeadsPage{}, errors.New("database credentials must not be exposed")
}

func TestAPIGlobalLeadsSanitizesDatabaseErrors(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "database")
	srv, err := New(NewService(&mockJobRepo{}, t.TempDir()), ":0")
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	srv.svc.SetDatabaseReader(failingGlobalReader{})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/leads", http.NoBody)
	rec := httptest.NewRecorder()
	srv.srv.Handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("expected 500, got %d", rec.Code)
	}
	if strings.Contains(rec.Body.String(), "credentials") {
		t.Fatalf("response exposed database error: %s", rec.Body.String())
	}
}
