package web

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

type fakeDatabaseReader struct {
	page  JobPage
	job   Job
	place []Place
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
