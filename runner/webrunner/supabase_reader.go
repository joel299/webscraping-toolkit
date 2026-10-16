package webrunner

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/gosom/google-maps-scraper/gmaps"
	"github.com/gosom/google-maps-scraper/internal/supabaseapi"
	"github.com/gosom/google-maps-scraper/shadow"
	"github.com/gosom/google-maps-scraper/web"
)

type supabaseDatabaseReader struct{ client *supabaseapi.Client }

func (r supabaseDatabaseReader) ListAllJobs(ctx context.Context) ([]web.Job, error) {
	var all []shadow.SearchContext
	for offset := 0; ; offset += 1000 {
		rows, _, err := r.listSearches(ctx, offset, 1000, false)
		if err != nil {
			return nil, err
		}
		all = append(all, rows...)
		if len(rows) < 1000 {
			break
		}
	}
	jobs := make([]web.Job, 0, len(all))
	for _, row := range all {
		jobs = append(jobs, searchToJob(row))
	}
	return jobs, nil
}

func (r supabaseDatabaseReader) ListJobs(ctx context.Context, page, limit int) (web.JobPage, error) {
	if page < 1 {
		page = 1
	}
	if limit < 1 {
		limit = 20
	}
	rows, total, err := r.listSearches(ctx, (page-1)*limit, limit, true)
	if err != nil {
		return web.JobPage{}, err
	}
	totalPages := (total + limit - 1) / limit
	if totalPages == 0 {
		totalPages = 1
	}
	if page > totalPages {
		page = totalPages
	}
	jobs := make([]web.Job, 0, len(rows))
	for _, row := range rows {
		jobs = append(jobs, searchToJob(row))
	}
	return web.JobPage{Jobs: jobs, CurrentPage: page, TotalPages: totalPages, Total: total, HasPrev: page > 1, HasNext: page < totalPages, PrevPage: page - 1, NextPage: page + 1, HasPages: totalPages > 1}, nil
}

func (r supabaseDatabaseReader) listSearches(ctx context.Context, offset, limit int, count bool) ([]shadow.SearchContext, int, error) {
	query := fmt.Sprintf("select=search_id,job_id,job_name,query,location,category,requested_limit,status,created_at,completed_at&order=created_at.desc,search_id.desc&limit=%d&offset=%d", limit, offset)
	prefer := ""
	if count {
		prefer = "count=exact"
	}
	data, headers, err := r.client.Do(ctx, http.MethodGet, "prospect_searches", query, nil, prefer)
	if err != nil {
		return nil, 0, err
	}
	var rows []shadow.SearchContext
	if err = json.Unmarshal(data, &rows); err != nil {
		return nil, 0, err
	}
	total := 0
	if count {
		if cr := headers.Get("Content-Range"); cr != "" {
			parts := strings.SplitN(cr, "/", 2)
			if len(parts) == 2 {
				total, _ = strconv.Atoi(parts[1])
			}
		}
	}
	if !count {
		total = len(rows)
	}
	return rows, total, nil
}

func (r supabaseDatabaseReader) GetJob(ctx context.Context, id string) (web.Job, error) {
	data, _, err := r.client.Do(ctx, http.MethodGet, "prospect_searches", "select=search_id,job_id,job_name,query,location,category,requested_limit,status,created_at,completed_at&search_id=eq."+supabaseapi.EscapeFilter(id)+"&limit=1", nil, "")
	if err != nil {
		return web.Job{}, err
	}
	var rows []shadow.SearchContext
	if err = json.Unmarshal(data, &rows); err != nil {
		return web.Job{}, err
	}
	if len(rows) == 0 {
		return web.Job{}, fmt.Errorf("search not found")
	}
	return searchToJob(rows[0]), nil
}

type relation struct {
	SearchID    string `json:"search_id"`
	PlaceID     string `json:"place_id"`
	ResultOrder int    `json:"result_order"`
}
type remoteLead struct {
	PlaceID        string   `json:"place_id"`
	Cid            string   `json:"cid"`
	PlaceName      string   `json:"place_name"`
	Category       string   `json:"category"`
	Address        string   `json:"address"`
	Phone          string   `json:"phone"`
	Website        string   `json:"website"`
	Emails         []string `json:"emails"`
	Email          string   `json:"email"`
	ReviewRating   float64  `json:"review_rating"`
	ReviewCount    int      `json:"review_count"`
	Latitude       float64  `json:"latitude"`
	Longitude      float64  `json:"longitude"`
	GoogleMapsLink string   `json:"google_maps_link"`
}

func (r supabaseDatabaseReader) GetPlaces(ctx context.Context, id string) ([]web.Place, error) {
	links, err := r.links(ctx, "search_id=eq."+supabaseapi.EscapeFilter(id))
	if err != nil {
		return nil, err
	}
	leads, err := r.fetchLeads(ctx, links)
	if err != nil {
		return nil, err
	}
	places := make([]web.Place, 0, len(leads))
	for _, lead := range leads {
		places = append(places, remoteLeadToPlace(lead, id, ""))
	}
	return places, nil
}

func (r supabaseDatabaseReader) links(ctx context.Context, filter string) ([]relation, error) {
	var all []relation
	for offset := 0; ; offset += 1000 {
		query := "select=search_id,place_id,result_order"
		if filter != "" {
			query += "&" + filter
		}
		query += fmt.Sprintf("&order=result_order.asc,discovered_at.asc,created_at.asc&limit=1000&offset=%d", offset)
		data, _, err := r.client.Do(ctx, http.MethodGet, "prospect_search_leads", query, nil, "")
		if err != nil {
			return nil, err
		}
		var page []relation
		if err = json.Unmarshal(data, &page); err != nil {
			return nil, err
		}
		all = append(all, page...)
		if len(page) < 1000 {
			break
		}
	}
	return all, nil
}

func (r supabaseDatabaseReader) fetchLeads(ctx context.Context, links []relation) ([]remoteLead, error) {
	if len(links) == 0 {
		return []remoteLead{}, nil
	}
	byID := make(map[string]remoteLead, len(links))
	ids := make([]string, 0, len(links))
	for _, link := range links {
		if _, ok := byID[link.PlaceID]; !ok {
			ids = append(ids, link.PlaceID)
		}
	}
	for start := 0; start < len(ids); start += 100 {
		end := min(start+100, len(ids))
		quoted := make([]string, 0, end-start)
		for _, id := range ids[start:end] {
			quoted = append(quoted, `"`+strings.ReplaceAll(id, `"`, `\"`)+`"`)
		}
		query := "select=place_id,cid,place_name,category,address,phone,website,emails,email,review_rating,review_count,latitude,longitude,google_maps_link&place_id=in.(" + strings.Join(quoted, ",") + ")"
		data, _, err := r.client.Do(ctx, http.MethodGet, "prospect_leads_google", query, nil, "")
		if err != nil {
			return nil, err
		}
		var page []remoteLead
		if err = json.Unmarshal(data, &page); err != nil {
			return nil, err
		}
		for _, lead := range page {
			byID[lead.PlaceID] = lead
		}
	}
	ordered := make([]remoteLead, 0, len(links))
	for _, link := range links {
		lead, ok := byID[link.PlaceID]
		if !ok {
			return nil, fmt.Errorf("Supabase search relation references missing lead")
		}
		ordered = append(ordered, lead)
	}
	return ordered, nil
}

func remoteLeadToPlace(l remoteLead, jobID, jobName string) web.Place {
	emails := append([]string(nil), l.Emails...)
	if len(emails) == 0 && l.Email != "" {
		emails = []string{l.Email}
	}
	return web.Place{PlaceID: l.PlaceID, JobID: jobID, JobName: jobName, Title: l.PlaceName, Address: l.Address, Latitude: l.Latitude, Longitude: l.Longitude, Link: l.GoogleMapsLink, Category: l.Category, Phone: l.Phone, Website: l.Website, ReviewRating: l.ReviewRating, ReviewCount: l.ReviewCount, Emails: emails}
}

func (r supabaseDatabaseReader) ListGlobalLeads(ctx context.Context, limit, offset int) (web.GlobalLeadsPage, error) {
	if limit < 1 {
		limit = 100
	}
	if offset < 0 {
		offset = 0
	}
	query := fmt.Sprintf("select=place_id,cid,place_name,category,address,phone,website,emails,email,review_rating,review_count,latitude,longitude,google_maps_link&order=place_name.asc,place_id.asc&limit=%d&offset=%d", limit, offset)
	data, headers, err := r.client.Do(ctx, http.MethodGet, "prospect_leads_google", query, nil, "count=exact")
	if err != nil {
		return web.GlobalLeadsPage{}, err
	}
	var leads []remoteLead
	if err = json.Unmarshal(data, &leads); err != nil {
		return web.GlobalLeadsPage{}, err
	}
	total := contentRangeTotal(headers.Get("Content-Range"), len(leads))
	if len(leads) == 0 {
		return web.GlobalLeadsPage{Items: []web.Place{}, Total: total, Limit: limit, Offset: offset}, nil
	}
	ids := make([]string, 0, len(leads))
	for _, lead := range leads {
		ids = append(ids, lead.PlaceID)
	}
	links, err := r.linksForPlaceIDs(ctx, ids)
	if err != nil {
		return web.GlobalLeadsPage{}, err
	}
	firstSearchByPlace := make(map[string]string, len(ids))
	for _, link := range links {
		if _, ok := firstSearchByPlace[link.PlaceID]; !ok {
			firstSearchByPlace[link.PlaceID] = link.SearchID
		}
	}
	jobNames := map[string]string{}
	searches, _, err := r.listSearches(ctx, 0, 10000, false)
	if err != nil {
		return web.GlobalLeadsPage{}, err
	}
	for _, s := range searches {
		jobNames[s.SearchID] = s.JobName
	}
	items := make([]web.Place, 0, len(leads))
	for _, lead := range leads {
		searchID := firstSearchByPlace[lead.PlaceID]
		items = append(items, remoteLeadToPlace(lead, searchID, jobNames[searchID]))
	}
	return web.GlobalLeadsPage{Items: items, Total: total, Limit: limit, Offset: offset}, nil
}

func contentRangeTotal(value string, fallback int) int {
	parts := strings.SplitN(value, "/", 2)
	if len(parts) != 2 || parts[1] == "*" {
		return fallback
	}
	total, err := strconv.Atoi(parts[1])
	if err != nil || total < 0 {
		return fallback
	}
	return total
}

func (r supabaseDatabaseReader) linksForPlaceIDs(ctx context.Context, ids []string) ([]relation, error) {
	if len(ids) == 0 {
		return []relation{}, nil
	}
	var all []relation
	for start := 0; start < len(ids); start += 100 {
		end := min(start+100, len(ids))
		quoted := make([]string, 0, end-start)
		for _, id := range ids[start:end] {
			// QueryEscape protects PostgREST's quoted IN-list values, including
			// punctuation that may appear in upstream place identifiers.
			quoted = append(quoted, "%22"+url.QueryEscape(id)+"%22")
		}
		filter := "place_id=in.(" + strings.Join(quoted, ",") + ")"
		for offset := 0; ; offset += 1000 {
			query := "select=search_id,place_id,result_order&" + filter + fmt.Sprintf("&order=result_order.asc,discovered_at.asc,created_at.asc&limit=1000&offset=%d", offset)
			data, _, err := r.client.Do(ctx, http.MethodGet, "prospect_search_leads", query, nil, "")
			if err != nil {
				return nil, err
			}
			var page []relation
			if err = json.Unmarshal(data, &page); err != nil {
				return nil, err
			}
			all = append(all, page...)
			if len(page) < 1000 {
				break
			}
		}
	}
	return all, nil
}

func (r supabaseDatabaseReader) ExportCSV(ctx context.Context, id, path string) error {
	places, err := r.GetPlaces(ctx, id)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	cw := csv.NewWriter(f)
	defer cw.Flush()
	if err = cw.Write((&gmaps.Entry{}).CsvHeaders()); err != nil {
		return err
	}
	for _, p := range places {
		e := &gmaps.Entry{Title: p.Title, Category: p.Category, Address: p.Address, Phone: p.Phone, WebSite: p.Website, ReviewRating: p.ReviewRating, ReviewCount: p.ReviewCount, Latitude: p.Latitude, Longtitude: p.Longitude, Link: p.Link}
		if err = cw.Write(e.CsvRow()); err != nil {
			return err
		}
	}
	return cw.Error()
}

var _ web.DatabaseReader = supabaseDatabaseReader{}
