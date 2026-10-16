package shadow

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gosom/google-maps-scraper/gmaps"
	"github.com/gosom/google-maps-scraper/internal/supabaseapi"
	"github.com/gosom/google-maps-scraper/log"
	"github.com/gosom/scrapemate"
)

// SupabaseWriter persists scraped lead data and search provenance through the
// Supabase REST API. It intentionally does not open a PostgreSQL connection.
type SupabaseWriter struct {
	client         *supabaseapi.Client
	mapper         *ProspectLeadMapper
	validator      *ProspectLeadValidator
	mu             sync.RWMutex
	jobID, jobName string
	metrics        Metrics
	closed         atomic.Bool
}

func NewSupabaseWriterFromEnv() (*SupabaseWriter, error) {
	client, err := supabaseapi.NewFromEnv()
	if err != nil {
		return nil, err
	}
	w := &SupabaseWriter{client: client, mapper: NewProspectLeadMapper(), validator: NewProspectLeadValidator()}
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	if _, _, err := client.Do(ctx, http.MethodGet, "prospect_searches", "select=search_id&limit=1", nil, ""); err != nil {
		return nil, fmt.Errorf("Supabase connectivity/schema check failed: %w", err)
	}
	if _, _, err := client.Do(ctx, http.MethodGet, "prospect_leads_google", "select=place_id&limit=1", nil, ""); err != nil {
		return nil, fmt.Errorf("Supabase leads table check failed: %w", err)
	}
	if _, _, err := client.Do(ctx, http.MethodGet, "prospect_search_leads", "select=search_id&limit=1", nil, ""); err != nil {
		return nil, fmt.Errorf("Supabase provenance table check failed: %w", err)
	}
	return w, nil
}

func (w *SupabaseWriter) Close() error {
	if w != nil {
		w.closed.Store(true)
	}
	return nil
}
func (w *SupabaseWriter) ensureOpen() error {
	if w == nil || w.closed.Load() {
		return ErrWriterClosed
	}
	return nil
}
func (w *SupabaseWriter) SetJobContext(jobID, jobName string) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.jobID, w.jobName = jobID, jobName
}

func (w *SupabaseWriter) RegisterSearch(ctx context.Context, s *SearchContext) error {
	if err := w.ensureOpen(); err != nil {
		return err
	}
	if s == nil {
		return errors.New("search context is required")
	}
	status := strings.ToLower(strings.TrimSpace(s.Status))
	if status == "" {
		status = "running"
	}
	if !validSearchStatus(status) {
		return fmt.Errorf("invalid search status: %s", status)
	}
	now := time.Now().UTC()
	row := map[string]any{"search_id": s.SearchID, "job_id": s.JobID, "job_name": s.JobName, "query": s.Query, "location": s.Location, "category": s.Category, "requested_limit": s.RequestedLimit, "status": status, "updated_at": now}
	if status == "created" || status == "running" {
		row["started_at"] = now
	}
	_, _, err := w.client.Do(ctx, http.MethodPost, "prospect_searches", "on_conflict=search_id", row, "resolution=merge-duplicates,return=minimal")
	if err != nil {
		w.markFailure("register_search", err)
		return err
	}
	return nil
}

func validSearchStatus(status string) bool {
	return status == "created" || status == "running" || status == "completed" || status == "failed"
}

func (w *SupabaseWriter) UpdateSearchStatus(ctx context.Context, searchID, status, errMsg string) error {
	if err := w.ensureOpen(); err != nil {
		return err
	}
	status = strings.ToLower(strings.TrimSpace(status))
	if !validSearchStatus(status) {
		return fmt.Errorf("invalid search status: %s", status)
	}
	row := map[string]any{"status": status, "error_message": nil, "updated_at": time.Now().UTC()}
	if errMsg != "" {
		row["error_message"] = errMsg
	}
	if status == "completed" || status == "failed" {
		row["completed_at"] = time.Now().UTC()
	}
	_, _, err := w.client.Do(ctx, http.MethodPatch, "prospect_searches", "search_id=eq."+supabaseapi.EscapeFilter(searchID), row, "return=minimal")
	if err != nil {
		w.markFailure("update_search_status", err)
	}
	return err
}

func (w *SupabaseWriter) LinkLeadToSearch(ctx context.Context, searchID, placeID string, resultOrder int) error {
	if err := w.ensureOpen(); err != nil {
		return err
	}
	row := map[string]any{"search_id": searchID, "place_id": placeID, "result_order": resultOrder, "discovered_at": time.Now().UTC()}
	_, _, err := w.client.Do(ctx, http.MethodPost, "prospect_search_leads", "on_conflict=search_id,place_id", row, "resolution=ignore-duplicates,return=minimal")
	if err != nil {
		w.markFailure("link_lead_to_search", err)
	}
	return err
}

func (w *SupabaseWriter) FindCompletedSearch(ctx context.Context, query, location string) (*SearchContext, error) {
	query = strings.TrimSpace(query)
	if query == "" {
		return nil, errors.New("query is required")
	}
	filter := "select=search_id,job_id,job_name,query,location,category,requested_limit,status,created_at,completed_at&status=eq.completed&query=ilike." + supabaseapi.EscapeFilter(query) + "&order=completed_at.desc.nullslast,created_at.desc&limit=1"
	if strings.TrimSpace(location) != "" {
		filter += "&location=ilike." + supabaseapi.EscapeFilter(strings.TrimSpace(location))
	}
	data, _, err := w.client.Do(ctx, http.MethodGet, "prospect_searches", filter, nil, "")
	if err != nil {
		return nil, err
	}
	var results []SearchContext
	if err := json.Unmarshal(data, &results); err != nil {
		return nil, err
	}
	if len(results) == 0 {
		return nil, nil
	}
	return &results[0], nil
}

func (w *SupabaseWriter) FetchLeadsForSearch(ctx context.Context, searchID string, limit int) ([]*ProspectLead, error) {
	leads, err := w.FetchLeadsForSearchPage(ctx, searchID, limit, 0)
	return leads, err
}

func (w *SupabaseWriter) FetchLeadsForSearchPage(ctx context.Context, searchID string, limit, offset int) ([]*ProspectLead, error) {
	query := "select=place_id,result_order&search_id=eq." + supabaseapi.EscapeFilter(searchID) + "&order=result_order.asc,discovered_at.asc,created_at.asc"
	if limit > 0 {
		query += fmt.Sprintf("&limit=%d&offset=%d", limit, maxInt(offset, 0))
	}
	data, _, err := w.client.Do(ctx, http.MethodGet, "prospect_search_leads", query, nil, "")
	if err != nil {
		return nil, err
	}
	var links []struct {
		PlaceID     string `json:"place_id"`
		ResultOrder int    `json:"result_order"`
	}
	if err := json.Unmarshal(data, &links); err != nil {
		return nil, err
	}
	if len(links) == 0 {
		return []*ProspectLead{}, nil
	}
	ids := make([]string, 0, len(links))
	for _, link := range links {
		ids = append(ids, `"`+strings.ReplaceAll(link.PlaceID, `"`, `\"`)+`"`)
	}
	leadQuery := "select=place_id,cid,place_name,category,categories,address,street,city,state,postal_code,country,phone,whatsapp,website,emails,email,review_rating,review_count,latitude,longitude,google_maps_link&place_id=in.(" + strings.Join(ids, ",") + ")"
	leadData, _, err := w.client.Do(ctx, http.MethodGet, "prospect_leads_google", leadQuery, nil, "")
	if err != nil {
		return nil, err
	}
	var rows []ProspectLead
	if err := json.Unmarshal(leadData, &rows); err != nil {
		return nil, err
	}
	byID := make(map[string]*ProspectLead, len(rows))
	for i := range rows {
		rows[i].JobID = searchID
		byID[rows[i].PlaceID] = &rows[i]
	}
	ordered := make([]*ProspectLead, 0, len(links))
	for _, link := range links {
		if lead := byID[link.PlaceID]; lead != nil {
			ordered = append(ordered, lead)
		}
	}
	if len(ordered) != len(links) {
		return nil, errors.New("Supabase search has provenance links without leads")
	}
	return ordered, nil
}

func (w *SupabaseWriter) Run(ctx context.Context, in <-chan scrapemate.Result) error {
	if err := w.ensureOpen(); err != nil {
		return err
	}
	var firstErr error
	for result := range in {
		var entry *gmaps.Entry
		switch v := result.Data.(type) {
		case *gmaps.Entry:
			entry = v
		case gmaps.Entry:
			entry = &v
		}
		if entry == nil || strings.TrimSpace(entry.Title) == "" {
			continue
		}
		w.mu.RLock()
		jobID, jobName := w.jobID, w.jobName
		w.mu.RUnlock()
		if err := w.upsertEntry(ctx, entry, jobID, jobName); err != nil {
			w.markFailure("upsert_lead", err)
			if firstErr == nil {
				firstErr = err
			}
		}
	}
	return firstErr
}

func (w *SupabaseWriter) upsertEntry(ctx context.Context, entry *gmaps.Entry, jobID, jobName string) error {
	lead := w.mapper.MapToProspectLead(entry, jobID, jobName)
	if err := w.validator.Validate(lead); err != nil {
		return err
	}
	// Resolve existing canonical rows by stable identity before the primary-key
	// upsert. This also avoids unique cid/WhatsApp conflicts on legacy records.
	canonical := ""
	for _, pair := range [][2]string{{"place_id", lead.PlaceID}, {"cid", lead.Cid}, {"whatsapp", lead.Whatsapp}} {
		if pair[1] == "" {
			continue
		}
		data, _, err := w.client.Do(ctx, http.MethodGet, "prospect_leads_google", "select=place_id&"+pair[0]+"=eq."+supabaseapi.EscapeFilter(pair[1])+"&limit=1", nil, "")
		if err != nil {
			return err
		}
		var found []struct {
			PlaceID string `json:"place_id"`
		}
		if err := json.Unmarshal(data, &found); err != nil {
			return err
		}
		if len(found) > 0 {
			canonical = found[0].PlaceID
			break
		}
	}
	if canonical == "" {
		canonical = lead.PlaceID
	}
	row := map[string]any{
		"id": canonical, "place_id": canonical, "cid": emptyNil(lead.Cid), "place_name": lead.PlaceName, "category": lead.Category,
		"categories": lead.Categories, "address": emptyNil(lead.Address), "street": emptyNil(lead.Street), "city": emptyNil(lead.City),
		"state": emptyNil(lead.State), "postal_code": emptyNil(lead.PostalCode), "country": emptyNil(lead.Country), "phone": emptyNil(lead.Phone),
		"whatsapp": emptyNil(lead.Whatsapp), "website": emptyNil(lead.Website), "emails": lead.Emails, "email": emptyNil(lead.Email),
		"review_rating": lead.ReviewRating, "review_count": lead.ReviewCount, "latitude": lead.Latitude, "longitude": lead.Longitude,
		"google_maps_link": emptyNil(lead.GoogleMapsLink), "job_id": emptyNil(jobID), "job_name": emptyNil(jobName), "updated_at": time.Now().UTC(),
	}
	_, _, err := w.client.Do(ctx, http.MethodPost, "prospect_leads_google", "on_conflict=place_id", row, "resolution=merge-duplicates,return=minimal")
	if err != nil {
		return err
	}
	if jobID != "" {
		return w.LinkLeadToSearch(ctx, jobID, canonical, 0)
	}
	return nil
}

func emptyNil(value string) any {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return value
}
func (w *SupabaseWriter) markFailure(operation string, err error) {
	atomic.AddUint64(&w.metrics.Failed, 1)
	log.Warn("Supabase persistence operation failed", "operation", operation, "error_class", "rest_error")
	_ = err
}

// WriteLeadsToCSVFile keeps the existing DB-first cache export contract.
func (w *SupabaseWriter) WriteLeadsToCSVFile(leads []*ProspectLead, filePath string) error {
	f, err := os.Create(filePath)
	if err != nil {
		return err
	}
	defer f.Close()
	cw := csv.NewWriter(f)
	defer cw.Flush()
	if err := cw.Write((&gmaps.Entry{}).CsvHeaders()); err != nil {
		return err
	}
	for _, lead := range leads {
		entry := &gmaps.Entry{Title: lead.PlaceName, Category: lead.Category, Address: lead.Address, WebSite: lead.Website, Phone: lead.Phone, ReviewCount: lead.ReviewCount, ReviewRating: lead.ReviewRating, Latitude: lead.Latitude, Longtitude: lead.Longitude, Cid: lead.Cid, Link: lead.GoogleMapsLink}
		if err := cw.Write(entry.CsvRow()); err != nil {
			return err
		}
	}
	return cw.Error()
}
