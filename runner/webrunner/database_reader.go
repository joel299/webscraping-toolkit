package webrunner

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gosom/google-maps-scraper/shadow"
	"github.com/gosom/google-maps-scraper/web"
)

// databaseReader adapts the persisted provenance model to the existing web
// contracts. It is read-only; writes continue to use the current job runner.
type databaseReader struct {
	writer *shadow.Writer
}

var errDatabaseRead = errors.New("database read failed")

func (r databaseReader) ListAllJobs(ctx context.Context) ([]web.Job, error) {
	_, total, err := r.writer.ListSearches(ctx, 0, 1)
	if err != nil {
		return nil, errDatabaseRead
	}
	if total == 0 {
		return []web.Job{}, nil
	}
	searches, _, err := r.writer.ListSearches(ctx, 0, total)
	if err != nil {
		return nil, errDatabaseRead
	}
	jobs := make([]web.Job, 0, len(searches))
	for _, search := range searches {
		jobs = append(jobs, searchToJob(search))
	}
	return jobs, nil
}

func (r databaseReader) ListJobs(ctx context.Context, page, limit int) (web.JobPage, error) {
	if page < 1 {
		page = 1
	}
	if limit < 1 {
		limit = 20
	}
	_, total, err := r.writer.ListSearches(ctx, 0, 1)
	if err != nil {
		return web.JobPage{}, errDatabaseRead
	}

	totalPages := (total + limit - 1) / limit
	if totalPages == 0 {
		totalPages = 1
	}
	if page > totalPages {
		page = totalPages
	}
	searches, _, err := r.writer.ListSearches(ctx, (page-1)*limit, limit)
	if err != nil {
		return web.JobPage{}, errDatabaseRead
	}
	jobs := make([]web.Job, 0, len(searches))
	for _, search := range searches {
		jobs = append(jobs, searchToJob(search))
	}
	return web.JobPage{
		Jobs: jobs, CurrentPage: page, TotalPages: totalPages, Total: total,
		HasPrev: page > 1, HasNext: page < totalPages,
		PrevPage: page - 1, NextPage: page + 1, HasPages: totalPages > 1,
	}, nil
}

func (r databaseReader) GetJob(ctx context.Context, id string) (web.Job, error) {
	search, err := r.writer.GetSearch(ctx, id)
	if err != nil {
		return web.Job{}, errDatabaseRead
	}
	return searchToJob(*search), nil
}

func (r databaseReader) GetPlaces(ctx context.Context, id string) ([]web.Place, error) {
	leads, err := r.writer.FetchLeadsForSearchPage(ctx, id, 0, 0)
	if err != nil {
		return nil, errDatabaseRead
	}
	places := make([]web.Place, 0, len(leads))
	for _, lead := range leads {
		places = append(places, leadToPlace(lead))
	}
	return places, nil
}

func (r databaseReader) ExportCSV(ctx context.Context, id, path string) error {
	leads, err := r.writer.FetchLeadsForSearchPage(ctx, id, 0, 0)
	if err != nil {
		return errDatabaseRead
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return r.writer.WriteLeadsToCSVFile(leads, path)
}

func searchToJob(search shadow.SearchContext) web.Job {
	status := web.StatusFailed
	switch strings.ToLower(search.Status) {
	case "created", "pending":
		status = web.StatusPending
	case "running", "working":
		status = web.StatusWorking
	case "completed", "ok":
		status = web.StatusOK
	}
	createdAt := search.CreatedAt
	if createdAt.IsZero() {
		createdAt = time.Now().UTC()
	}
	lat, lon := splitLocation(search.Location)
	depth := search.RequestedLimit
	if depth <= 0 {
		depth = 1
	}
	return web.Job{
		ID: search.SearchID, Name: search.JobName, Date: createdAt, Status: status,
		Data: web.JobData{
			Keywords: []string{search.Query}, Lang: "pt", Lat: lat, Lon: lon,
			Depth: depth, MaxTime: 15 * time.Minute, Zoom: 15,
		},
	}
}

func splitLocation(location string) (string, string) {
	parts := strings.SplitN(location, ",", 2)
	if len(parts) != 2 {
		return "", ""
	}
	return strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1])
}

func leadToPlace(lead *shadow.ProspectLead) web.Place {
	return web.Place{
		Title: lead.PlaceName, Address: lead.Address, Latitude: lead.Latitude,
		Longitude: lead.Longitude, Link: lead.GoogleMapsLink, Category: lead.Category,
		Phone: lead.Phone, Website: lead.Website, ReviewRating: lead.ReviewRating,
		ReviewCount: lead.ReviewCount, Emails: append([]string(nil), lead.Emails...),
	}
}

var _ web.DatabaseReader = databaseReader{}
