// migrate_sqlite_to_supabase copies a preserved local web data snapshot to the
// configured Supabase REST API. It is dry-run by default; pass -execute to write.
package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/gosom/google-maps-scraper/gmaps"
	"github.com/gosom/google-maps-scraper/shadow"
	"github.com/gosom/google-maps-scraper/web"
	websqlite "github.com/gosom/google-maps-scraper/web/sqlite"
)

type client struct {
	baseURL string
	key     string
	http    *http.Client
}

type leadPayload map[string]any

type migration struct {
	jobs       []web.Job
	leads      map[string]leadPayload
	links      []map[string]any
	leadCount  int
	jobCount   int
	rowCount   int
	client     *client
	execute    bool
	searches   []map[string]any
	searchKeys map[string]struct{}
}

func main() {
	dataDir := flag.String("data-dir", "recovery-backups/supabase-migration-20261016/data", "directory containing jobs.db and per-job CSV files")
	execute := flag.Bool("execute", false, "write records to Supabase; default only validates and reports counts")
	flag.Parse()

	if err := run(*dataDir, *execute); err != nil {
		fmt.Fprintln(os.Stderr, "migration stopped:", err)
		os.Exit(1)
	}
}

func run(dataDir string, execute bool) error {
	root, err := filepath.Abs(dataDir)
	if err != nil {
		return err
	}
	jobsPath := filepath.Join(root, "jobs.db")
	if _, err := os.Stat(jobsPath); err != nil {
		return fmt.Errorf("snapshot jobs.db: %w", err)
	}
	env, err := readEnv(filepath.Join(".env"))
	if err != nil {
		return err
	}
	baseURL := strings.TrimRight(env["SUPABASE_URL"], "/")
	key := strings.TrimSpace(env["SUPABASE_SERVICE_ROLE_KEY"])
	if baseURL == "" || key == "" {
		return errors.New("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required in .env")
	}
	if !strings.HasPrefix(baseURL, "https://") {
		return errors.New("SUPABASE_URL must use HTTPS")
	}
	if !(strings.HasPrefix(key, "eyJ") || strings.HasPrefix(key, "sb_secret_")) {
		return errors.New("configured key is not a recognized Supabase secret key")
	}
	c := &client{baseURL: baseURL, key: key, http: &http.Client{Timeout: 60 * time.Second}}

	repo, err := websqlite.New(jobsPath)
	if err != nil {
		return fmt.Errorf("open preserved SQLite snapshot: %w", err)
	}
	defer repo.(interface{ Close() error }).Close()
	jobs, err := repo.Select(context.Background(), web.SelectParams{Limit: 100000})
	if err != nil {
		return fmt.Errorf("read SQLite jobs: %w", err)
	}
	sort.Slice(jobs, func(i, j int) bool { return jobs[i].Date.Before(jobs[j].Date) })

	m := &migration{jobs: jobs, jobCount: len(jobs), client: c, execute: execute, leads: map[string]leadPayload{}, searchKeys: map[string]struct{}{}}
	mapper := shadow.NewProspectLeadMapper()
	canonical := map[string]string{}
	cidCanonical := map[string]string{}
	phoneAddressCanonical := map[string]string{}
	phoneAddresses := map[string]map[string]struct{}{}
	if execute {
		rows, err := c.existingLeads()
		if err != nil {
			return fmt.Errorf("read target lead identities: %w", err)
		}
		for _, row := range rows {
			id := str(row["place_id"])
			if id == "" {
				continue
			}
			canonical[id] = id
			if cid := str(row["cid"]); cid != "" {
				cidCanonical[cid] = id
			}
			phone := str(row["whatsapp"])
			if phone == "" {
				phone = mapperPhone(mapper, str(row["phone"]))
			}
			addr := norm(str(row["address"]))
			if phone != "" && addr != "" {
				phoneAddressCanonical[phone+"|"+addr] = id
				if phoneAddresses[phone] == nil {
					phoneAddresses[phone] = map[string]struct{}{}
				}
				phoneAddresses[phone][addr] = struct{}{}
			}
		}
	}
	linkSet := map[string]struct{}{}

	for _, job := range jobs {
		search := makeSearch(job)
		m.searches = append(m.searches, search)
		m.searchKeys[job.ID] = struct{}{}
		csvPath := filepath.Join(root, filepath.Base(job.ID)+".csv")
		f, err := os.Open(csvPath)
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return fmt.Errorf("open result CSV for job %s: %w", job.ID, err)
		}
		rows, err := parseCSV(f, job, mapper, canonical, cidCanonical, phoneAddressCanonical, phoneAddresses, m.leads)
		closeErr := f.Close()
		if err != nil {
			return fmt.Errorf("parse result CSV for job %s: %w", job.ID, err)
		}
		if closeErr != nil {
			return closeErr
		}
		m.rowCount += rows
		for i := 0; i < rows; i++ {
			// Result order is represented by the CSV's stable row sequence.
			// The relation is deduped by search/place pair below.
		}
		// Build provenance from rows a second time using the same parser's link list.
		file, err := os.Open(csvPath)
		if err != nil {
			return err
		}
		links, err := parseLinks(file, job, mapper, canonical, cidCanonical, phoneAddressCanonical, phoneAddresses)
		_ = file.Close()
		if err != nil {
			return fmt.Errorf("build provenance for job %s: %w", job.ID, err)
		}
		for _, link := range links {
			key := str(link["search_id"]) + "|" + str(link["place_id"])
			if _, ok := linkSet[key]; ok {
				continue
			}
			linkSet[key] = struct{}{}
			m.links = append(m.links, link)
		}
	}
	m.leadCount = len(m.leads)

	fmt.Printf("Snapshot review: jobs=%d, CSV rows=%d, unique lead identities=%d, provenance links=%d\n", m.jobCount, m.rowCount, m.leadCount, len(m.links))
	if !execute {
		fmt.Println("Dry-run only. No Supabase records were changed. Run again with -execute to import idempotently.")
		return nil
	}

	ctx := context.Background()
	if err := c.upsertBatch(ctx, "prospect_searches", "search_id", m.searches); err != nil {
		return fmt.Errorf("upsert searches: %w", err)
	}
	leadRows := make([]map[string]any, 0, len(m.leads))
	for _, row := range m.leads {
		leadRows = append(leadRows, row)
	}
	sort.Slice(leadRows, func(i, j int) bool { return str(leadRows[i]["place_id"]) < str(leadRows[j]["place_id"]) })
	if err := c.upsertBatch(ctx, "prospect_leads_google", "place_id", leadRows); err != nil {
		return fmt.Errorf("upsert leads: %w", err)
	}
	if err := c.upsertBatch(ctx, "prospect_search_leads", "search_id,place_id", m.links); err != nil {
		return fmt.Errorf("upsert provenance links: %w", err)
	}

	searchN, err := c.count("prospect_searches", "search_id")
	if err != nil {
		return err
	}
	leadN, err := c.count("prospect_leads_google", "place_id")
	if err != nil {
		return err
	}
	linkN, err := c.count("prospect_search_leads", "search_id")
	if err != nil {
		return err
	}
	fmt.Printf("Supabase counts verified: prospect_searches=%d, prospect_leads_google=%d, prospect_search_leads=%d\n", searchN, leadN, linkN)
	return nil
}

func readEnv(path string) (map[string]string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", path, err)
	}
	values := map[string]string{}
	for _, line := range strings.Split(string(b), "\n") {
		line = strings.TrimSpace(strings.TrimSuffix(line, "\r"))
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		values[strings.TrimSpace(k)] = strings.Trim(strings.TrimSpace(v), "\"'")
	}
	return values, nil
}

func makeSearch(job web.Job) map[string]any {
	status := map[string]string{"pending": "created", "working": "running", "ok": "completed", "failed": "failed"}[strings.ToLower(job.Status)]
	if status == "" {
		status = "created"
	}
	location := strings.TrimSpace(strings.Join([]string{job.Data.City, job.Data.State}, ", "))
	if location == "," {
		location = ""
	}
	query := strings.Join(job.Data.Keywords, ", ")
	limit := job.Data.Depth
	if limit < 0 {
		limit = 0
	}
	row := map[string]any{"search_id": job.ID, "job_id": job.ID, "job_name": job.Name, "query": query, "location": location, "category": job.Data.Category, "requested_limit": limit, "status": status, "created_at": job.Date.UTC().Format(time.RFC3339Nano), "updated_at": job.Date.UTC().Format(time.RFC3339Nano)}
	if status == "running" || status == "completed" || status == "failed" {
		row["started_at"] = job.Date.UTC().Format(time.RFC3339Nano)
	}
	if status == "completed" || status == "failed" {
		row["completed_at"] = job.Date.UTC().Format(time.RFC3339Nano)
	}
	return row
}

func parseCSV(r io.Reader, job web.Job, mapper *shadow.ProspectLeadMapper, canonical, cidCanonical, phoneAddressCanonical map[string]string, phoneAddresses map[string]map[string]struct{}, leads map[string]leadPayload) (int, error) {
	reader := csv.NewReader(r)
	reader.FieldsPerRecord = -1
	header, err := reader.Read()
	if err != nil {
		if err == io.EOF {
			return 0, nil
		}
		return 0, err
	}
	cols := map[string]int{}
	for i, h := range header {
		cols[strings.ToLower(strings.TrimSpace(h))] = i
	}
	get := func(row []string, name string) string {
		i, ok := cols[name]
		if !ok || i >= len(row) {
			return ""
		}
		return strings.TrimSpace(row[i])
	}
	count := 0
	for {
		row, err := reader.Read()
		if err == io.EOF {
			return count, nil
		}
		if err != nil {
			return count, err
		}
		entry := entryFromCSV(row, get)
		if entry.Title == "" {
			continue
		}
		lead := mapper.MapToProspectLead(&entry, job.ID, job.Name)
		if lead == nil || lead.PlaceID == "" {
			continue
		}
		count++
		id := lead.PlaceID
		if existing := canonical[id]; existing != "" {
			id = existing
		}
		if lead.Cid != "" {
			if existing := cidCanonical[lead.Cid]; existing != "" {
				id = existing
			}
		}
		addr := norm(lead.Address)
		if lead.Whatsapp != "" && addr != "" {
			if existing := phoneAddressCanonical[lead.Whatsapp+"|"+addr]; existing != "" {
				id = existing
			}
		}
		canonical[lead.PlaceID] = id
		if lead.Cid != "" {
			cidCanonical[lead.Cid] = id
		}
		phone := lead.Whatsapp
		if phone != "" && addr != "" {
			phoneAddressCanonical[phone+"|"+addr] = id
			if phoneAddresses[phone] == nil {
				phoneAddresses[phone] = map[string]struct{}{}
			}
			phoneAddresses[phone][addr] = struct{}{}
		}
		payload := toPayload(lead, id)
		// A globally unique WhatsApp index is stricter than our identity rule
		// (phone plus address). Keep the phone field but omit whatsapp when that
		// number already belongs to a different address.
		if phone != "" && addr != "" && len(phoneAddresses[phone]) > 1 {
			delete(payload, "whatsapp")
		}
		if prior := leads[id]; prior != nil {
			for k, v := range payload {
				prior[k] = v
			}
		} else {
			leads[id] = payload
		}
	}
}

func parseLinks(r io.Reader, job web.Job, mapper *shadow.ProspectLeadMapper, canonical, cidCanonical, phoneAddressCanonical map[string]string, phoneAddresses map[string]map[string]struct{}) ([]map[string]any, error) {
	reader := csv.NewReader(r)
	reader.FieldsPerRecord = -1
	header, err := reader.Read()
	if err != nil {
		if err == io.EOF {
			return nil, nil
		}
		return nil, err
	}
	cols := map[string]int{}
	for i, h := range header {
		cols[strings.ToLower(strings.TrimSpace(h))] = i
	}
	get := func(row []string, name string) string {
		i, ok := cols[name]
		if !ok || i >= len(row) {
			return ""
		}
		return strings.TrimSpace(row[i])
	}
	var links []map[string]any
	order := 0
	for {
		row, err := reader.Read()
		if err == io.EOF {
			return links, nil
		}
		if err != nil {
			return nil, err
		}
		entry := entryFromCSV(row, get)
		if entry.Title == "" {
			continue
		}
		l := mapper.MapToProspectLead(&entry, job.ID, job.Name)
		if l == nil {
			continue
		}
		id := canonical[l.PlaceID]
		if id == "" {
			id = l.PlaceID
		}
		if l.Cid != "" && cidCanonical[l.Cid] != "" {
			id = cidCanonical[l.Cid]
		}
		addr := norm(l.Address)
		if l.Whatsapp != "" && addr != "" && phoneAddressCanonical[l.Whatsapp+"|"+addr] != "" {
			id = phoneAddressCanonical[l.Whatsapp+"|"+addr]
		}
		if id == "" {
			continue
		}
		links = append(links, map[string]any{"search_id": job.ID, "place_id": id, "result_order": order, "discovered_at": job.Date.UTC().Format(time.RFC3339Nano), "created_at": job.Date.UTC().Format(time.RFC3339Nano)})
		order++
	}
}

func entryFromCSV(row []string, get func([]string, string) string) gmaps.Entry {
	var e gmaps.Entry
	e.ID = get(row, "input_id")
	e.Link = get(row, "link")
	e.Title = get(row, "title")
	e.Category = get(row, "category")
	e.Address = get(row, "address")
	e.WebSite = get(row, "website")
	e.Phone = get(row, "phone")
	e.Cid = get(row, "cid")
	e.DataID = get(row, "data_id")
	e.PlaceID = get(row, "place_id")
	e.ReviewCount = parseInt(get(row, "review_count"))
	e.ReviewRating = parseFloat(get(row, "review_rating"))
	e.Latitude = parseFloat(get(row, "latitude"))
	e.Longtitude = parseFloat(get(row, "longitude"))
	if e.Category != "" {
		e.Categories = []string{e.Category}
	}
	e.Emails = splitList(get(row, "emails"))
	_ = json.Unmarshal([]byte(get(row, "complete_address")), &e.CompleteAddress)
	return e
}

func toPayload(p *shadow.ProspectLead, id string) leadPayload {
	row := leadPayload{"place_id": id, "place_name": p.PlaceName, "job_id": p.JobID, "job_name": p.JobName}
	put := func(k string, v any, empty bool) {
		if !empty {
			row[k] = v
		}
	}
	put("cid", p.Cid, p.Cid == "")
	put("category", p.Category, p.Category == "")
	put("categories", p.Categories, len(p.Categories) == 0)
	put("address", p.Address, p.Address == "")
	put("street", p.Street, p.Street == "")
	put("city", p.City, p.City == "")
	put("state", p.State, p.State == "")
	put("postal_code", p.PostalCode, p.PostalCode == "")
	put("country", p.Country, p.Country == "")
	put("phone", p.Phone, p.Phone == "")
	put("whatsapp", p.Whatsapp, p.Whatsapp == "")
	put("website", p.Website, p.Website == "")
	put("emails", p.Emails, len(p.Emails) == 0)
	put("email", p.Email, p.Email == "")
	put("review_rating", p.ReviewRating, p.ReviewRating == 0)
	put("review_count", p.ReviewCount, p.ReviewCount == 0)
	put("latitude", p.Latitude, p.Latitude == 0)
	put("longitude", p.Longitude, p.Longitude == 0)
	put("google_maps_link", p.GoogleMapsLink, p.GoogleMapsLink == "")
	return row
}

func (c *client) request(ctx context.Context, method, path string, body any, extra http.Header) (*http.Response, error) {
	var reader io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		reader = strings.NewReader(string(b))
	}
	u := c.baseURL + path
	req, err := http.NewRequestWithContext(ctx, method, u, reader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("apikey", c.key)
	req.Header.Set("Accept", "application/json")
	if strings.HasPrefix(c.key, "eyJ") {
		req.Header.Set("Authorization", "Bearer "+c.key)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, vs := range extra {
		for _, v := range vs {
			req.Header.Add(k, v)
		}
	}
	return c.http.Do(req)
}

func (c *client) existingLeads() ([]map[string]any, error) {
	var all []map[string]any
	var total int
	for start := 0; start < total || start == 0; start += 1000 {
		extra := http.Header{
			"Range":      []string{fmt.Sprintf("%d-%d", start, start+999)},
			"Range-Unit": []string{"items"},
			"Prefer":     []string{"count=exact"},
		}
		resp, err := c.request(context.Background(), http.MethodGet, "/rest/v1/prospect_leads_google?select=place_id,cid,whatsapp,address,phone&order=place_id.asc", nil, extra)
		if err != nil {
			return nil, err
		}
		b, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if resp.StatusCode == http.StatusRequestedRangeNotSatisfiable && start >= total {
			return all, nil
		}
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return nil, fmt.Errorf("target identity query HTTP %d: %s", resp.StatusCode, short(b))
		}
		if start == 0 {
			contentRange := resp.Header.Get("Content-Range")
			if i := strings.LastIndex(contentRange, "/"); i >= 0 {
				total, _ = strconv.Atoi(contentRange[i+1:])
			}
		}
		var page []map[string]any
		if err := json.Unmarshal(b, &page); err != nil {
			return nil, err
		}
		all = append(all, page...)
		if len(page) < 1000 || total == 0 {
			return all, nil
		}
	}
	return all, nil
}

func (c *client) upsertBatch(ctx context.Context, table, conflict string, rows []map[string]any) error {
	// PostgREST requires identical JSON keys on every object in a bulk insert.
	groups := map[string][]map[string]any{}
	for _, row := range rows {
		keys := make([]string, 0, len(row))
		for key := range row {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		signature := strings.Join(keys, "\x00")
		groups[signature] = append(groups[signature], row)
	}
	signatures := make([]string, 0, len(groups))
	for signature := range groups {
		signatures = append(signatures, signature)
	}
	sort.Strings(signatures)
	batchNumber := 0
	for _, signature := range signatures {
		group := groups[signature]
		for start := 0; start < len(group); start += 100 {
			end := start + 100
			if end > len(group) {
				end = len(group)
			}
			path := "/rest/v1/" + table + "?on_conflict=" + url.QueryEscape(conflict)
			extra := http.Header{"Prefer": []string{"resolution=merge-duplicates,return=minimal"}}
			resp, err := c.request(ctx, http.MethodPost, path, group[start:end], extra)
			if err != nil {
				return err
			}
			b, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			if resp.StatusCode < 200 || resp.StatusCode >= 300 {
				return fmt.Errorf("%s batch %d HTTP %d: %s", table, batchNumber, resp.StatusCode, short(b))
			}
			batchNumber++
		}
	}
	return nil
}

func (c *client) count(table, field string) (int, error) {
	extra := http.Header{"Prefer": []string{"count=exact"}}
	path := "/rest/v1/" + table + "?select=" + url.QueryEscape(field) + "&limit=1"
	resp, err := c.request(context.Background(), http.MethodGet, path, nil, extra)
	if err != nil {
		return 0, err
	}
	b, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return 0, fmt.Errorf("count %s HTTP %d: %s", table, resp.StatusCode, short(b))
	}
	contentRange := resp.Header.Get("Content-Range")
	if i := strings.LastIndex(contentRange, "/"); i >= 0 {
		n, err := strconv.Atoi(contentRange[i+1:])
		if err == nil {
			return n, nil
		}
	}
	return 0, fmt.Errorf("count %s missing exact Content-Range", table)
}

func (c *client) existingLeadsUnused() {}
func mapperPhone(mapper *shadow.ProspectLeadMapper, phone string) string {
	_ = mapper
	return digits(phone)
}
func digits(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r >= '0' && r <= '9' {
			b.WriteRune(r)
		}
	}
	return b.String()
}
func norm(s string) string {
	return strings.Join(strings.Fields(strings.ToLower(strings.TrimSpace(s))), " ")
}
func splitList(s string) []string {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	parts := strings.Split(s, ",")
	var out []string
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}
func parseInt(s string) int       { n, _ := strconv.Atoi(strings.TrimSpace(s)); return n }
func parseFloat(s string) float64 { n, _ := strconv.ParseFloat(strings.TrimSpace(s), 64); return n }
func str(v any) string            { s, _ := v.(string); return s }
func short(b []byte) string {
	s := strings.TrimSpace(string(b))
	if len(s) > 500 {
		s = s[:500]
	}
	return s
}
