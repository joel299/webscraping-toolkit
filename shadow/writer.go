package shadow

import (
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"os"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gosom/scrapemate"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/gosom/google-maps-scraper/gmaps"
	"github.com/gosom/google-maps-scraper/log"
)

var dsnPasswordRegex = regexp.MustCompile(`postgres(ql)?://([^:]+):([^@]+)@`)

// SanitizeDSN removes passwords from connection strings to prevent credential exposure in logs.
func SanitizeDSN(dsn string) string {
	if dsn == "" {
		return ""
	}
	return dsnPasswordRegex.ReplaceAllString(dsn, "postgres://$2:*****@")
}

// LoadDSN loads the PostgreSQL DSN securely from server-side secret file or environment.
func LoadDSN() string {
	filePath := os.Getenv("PROSPECT_DATABASE_URL_FILE")
	if filePath == "" {
		filePath = "/run/secrets/prospect_database_url"
	}

	if data, err := os.ReadFile(filePath); err == nil {
		dsn := strings.TrimRight(string(data), "\r\n")
		dsn = strings.TrimSpace(dsn)
		if dsn != "" {
			return dsn
		}
	}

	if dsn := strings.TrimSpace(os.Getenv("PROSPECT_DATABASE_URL")); dsn != "" {
		return dsn
	}

	return ""
}

type SearchContext struct {
	SearchID       string `json:"search_id"`
	JobID          string `json:"job_id"`
	JobName        string `json:"job_name"`
	Query          string `json:"query"`
	Location       string `json:"location"`
	Category       string `json:"category"`
	RequestedLimit int    `json:"requested_limit"`
	Status         string `json:"status"`
}

type Metrics struct {
	Inserted                 uint64 `json:"inserted"`
	Updated                  uint64 `json:"updated"`
	Unchanged                uint64 `json:"unchanged"`
	Failed                   uint64 `json:"failed"`
	SearchesCreated          uint64 `json:"searches_created"`
	SearchesUpdated          uint64 `json:"searches_updated"`
	SearchLeadLinksInserted  uint64 `json:"search_lead_links_inserted"`
	SearchLeadLinksUnchanged uint64 `json:"search_lead_links_unchanged"`
	ProvenanceFailed         uint64 `json:"provenance_failed"`
	ProvenanceDegraded       bool   `json:"provenance_degraded"`
}

type Writer struct {
	pool         *pgxpool.Pool
	saveInterval time.Duration
	batchSize    int
	metrics      Metrics
	mu           sync.Mutex
	disabled     bool
	mapper       *ProspectLeadMapper
	validator    *ProspectLeadValidator
	jobID        string
	jobName      string
	provenanceDegraded uint32
}

type UpsertOutcome string

const (
	OutcomeInserted  UpsertOutcome = "inserted"
	OutcomeUpdated   UpsertOutcome = "updated"
	OutcomeUnchanged UpsertOutcome = "unchanged"
)

type UpsertLeadResult struct {
	CanonicalPlaceID string
	Outcome          UpsertOutcome
}

// SetJobContext sets the search/job provenance context for results written by this Writer instance.
func (w *Writer) SetJobContext(jobID, jobName string) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.jobID = jobID
	w.jobName = jobName
}

// NewWriterFromEnv initializes the persistence writer using environment credentials.
func NewWriterFromEnv() scrapemate.ResultWriter {
	dsn := LoadDSN()
	if dsn == "" {
		log.Info("shadow persistence disabled: no DSN configured in file or env")
		return NewDisabledWriter()
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	config, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		log.Warn("shadow persistence disabled: invalid DSN format", "dsn", SanitizeDSN(dsn))
		return NewDisabledWriter()
	}

	config.MaxConns = 10
	config.MinConns = 2
	config.MaxConnIdleTime = 5 * time.Minute

	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		log.Warn("shadow persistence disabled: failed to initialize pool", "dsn", SanitizeDSN(dsn), "error_class", ProvenanceErrorClass(err))
		return NewDisabledWriter()
	}

	if err := pool.Ping(ctx); err != nil {
		log.Warn("shadow persistence operating in shadow-fail mode: ping failed", "dsn", SanitizeDSN(dsn), "error_class", ProvenanceErrorClass(err))
		return &Writer{
			pool:         pool,
			saveInterval: 5 * time.Second,
			batchSize:    10,
			mapper:       NewProspectLeadMapper(),
			validator:    NewProspectLeadValidator(),
			disabled:     false,
		}
	}

	log.Info("shadow persistence connected successfully", "dsn", SanitizeDSN(dsn))
	if err := ValidateSchema(ctx, pool); err != nil {
		log.Warn("shadow persistence schema validation warning: table missing or unreadable; shadow writer entering shadow-fail mode", "error_class", ProvenanceErrorClass(err))
	}

	return &Writer{
		pool:         pool,
		saveInterval: 5 * time.Second,
		batchSize:    10,
		mapper:       NewProspectLeadMapper(),
		validator:    NewProspectLeadValidator(),
	}
}

// ValidateSchema verifies that public.prospect_leads_google exists without performing runtime DDL (GATE 4).
func ValidateSchema(ctx context.Context, pool *pgxpool.Pool) error {
	if pool == nil {
		return nil
	}
	_, err := pool.Exec(ctx, "SELECT 1 FROM public.prospect_leads_google LIMIT 0")
	return err
}

func NewDisabledWriter() *Writer {
	return &Writer{
		disabled:  true,
		mapper:    NewProspectLeadMapper(),
		validator: NewProspectLeadValidator(),
	}
}

func NewWriter(pool *pgxpool.Pool, saveInterval time.Duration, batchSize int) *Writer {
	return &Writer{
		pool:         pool,
		saveInterval: saveInterval,
		batchSize:    batchSize,
		mapper:       NewProspectLeadMapper(),
		validator:    NewProspectLeadValidator(),
	}
}

func (w *Writer) GetMetrics() Metrics {
	return Metrics{
		Inserted:                 atomic.LoadUint64(&w.metrics.Inserted),
		Updated:                  atomic.LoadUint64(&w.metrics.Updated),
		Unchanged:                atomic.LoadUint64(&w.metrics.Unchanged),
		Failed:                   atomic.LoadUint64(&w.metrics.Failed),
		SearchesCreated:          atomic.LoadUint64(&w.metrics.SearchesCreated),
		SearchesUpdated:          atomic.LoadUint64(&w.metrics.SearchesUpdated),
		SearchLeadLinksInserted:  atomic.LoadUint64(&w.metrics.SearchLeadLinksInserted),
		SearchLeadLinksUnchanged: atomic.LoadUint64(&w.metrics.SearchLeadLinksUnchanged),
		ProvenanceFailed:         atomic.LoadUint64(&w.metrics.ProvenanceFailed),
		ProvenanceDegraded:       atomic.LoadUint32(&w.provenanceDegraded) == 1,
	}
}

// ProvenanceErrorClass returns a safe, low-cardinality classification for persistence errors.
// It deliberately does not expose database error text, DSNs, or user data in logs.
func ProvenanceErrorClass(err error) string {
	if err == nil {
		return "none"
	}
	if errors.Is(err, context.Canceled) {
		return "context_canceled"
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return "context_deadline_exceeded"
	}
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		return "postgres_" + pgErr.Code
	}
	return "database_error"
}

func (w *Writer) markProvenanceFailure(operation string, err error) {
	atomic.AddUint64(&w.metrics.ProvenanceFailed, 1)
	atomic.StoreUint32(&w.provenanceDegraded, 1)
	log.Warn("shadow provenance operation failed", "operation", operation, "error_class", ProvenanceErrorClass(err))
}

// RegisterSearch registers or updates a search in public.prospect_searches (GATE 7 & GATE 8)
func (w *Writer) RegisterSearch(ctx context.Context, s *SearchContext) error {
	if s == nil || w.pool == nil || w.disabled {
		return nil
	}

	status := strings.ToLower(strings.TrimSpace(s.Status))
	if status == "" {
		status = "running"
	}

	validStatuses := map[string]bool{
		"created":   true,
		"running":   true,
		"completed": true,
		"failed":    true,
	}

	if !validStatuses[status] {
		err := fmt.Errorf("invalid search status: %s", status)
		w.markProvenanceFailure("register_search", err)
		return err
	}

	q := `
	INSERT INTO public.prospect_searches (
		search_id, job_id, job_name, query, location, category, requested_limit, status, started_at, updated_at
	) VALUES (
		$1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW()
	)
	ON CONFLICT (search_id) DO UPDATE SET
		job_id = EXCLUDED.job_id,
		job_name = EXCLUDED.job_name,
		query = EXCLUDED.query,
		location = EXCLUDED.location,
		category = EXCLUDED.category,
		requested_limit = EXCLUDED.requested_limit,
		status = EXCLUDED.status,
		updated_at = NOW()
	RETURNING (xmax::text = '0') AS is_insert;
	`

	var isInsert bool
	err := w.pool.QueryRow(ctx, q,
		s.SearchID,
		s.JobID,
		s.JobName,
		s.Query,
		s.Location,
		s.Category,
		s.RequestedLimit,
		status,
	).Scan(&isInsert)

	if err != nil {
		w.markProvenanceFailure("register_search", err)
		return err
	}

	if isInsert {
		atomic.AddUint64(&w.metrics.SearchesCreated, 1)
	} else {
		atomic.AddUint64(&w.metrics.SearchesUpdated, 1)
	}
	return nil
}

// UpdateSearchStatus updates status and completion time in public.prospect_searches (GATE 7)
func (w *Writer) UpdateSearchStatus(ctx context.Context, searchID, status, errMsg string) error {
	if searchID == "" || w.pool == nil || w.disabled {
		return nil
	}

	status = strings.ToLower(strings.TrimSpace(status))
	validStatuses := map[string]bool{
		"created":   true,
		"running":   true,
		"completed": true,
		"failed":    true,
	}

	if !validStatuses[status] {
		err := fmt.Errorf("invalid search status: %s", status)
		w.markProvenanceFailure("update_search_status", err)
		return err
	}

	var completedAt *time.Time
	if status == "completed" || status == "failed" {
		now := time.Now().UTC()
		completedAt = &now
	}

	q := `
	UPDATE public.prospect_searches SET
		status = $2,
		error_message = NULLIF($3, ''),
		completed_at = COALESCE($4, completed_at),
		updated_at = NOW()
	WHERE search_id = $1
	`

	_, err := w.pool.Exec(ctx, q, searchID, status, errMsg, completedAt)
	if err != nil {
		w.markProvenanceFailure("update_search_status", err)
		return err
	}

	return nil
}

// LinkLeadToSearch connects a canonical lead to a search request in public.prospect_search_leads (FASE 7)
func (w *Writer) LinkLeadToSearch(ctx context.Context, searchID, placeID string, resultOrder int) error {
	if searchID == "" || placeID == "" || w.pool == nil || w.disabled {
		return nil
	}

	q := `
	INSERT INTO public.prospect_search_leads (
		search_id, place_id, result_order, discovered_at, created_at
	) VALUES (
		$1, $2, $3, NOW(), NOW()
	)
	ON CONFLICT (search_id, place_id) DO NOTHING
	RETURNING (xmax::text = '0') AS is_inserted;
	`

	var isInserted bool
	err := w.pool.QueryRow(ctx, q, searchID, placeID, resultOrder).Scan(&isInserted)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			atomic.AddUint64(&w.metrics.SearchLeadLinksUnchanged, 1)
			return nil
		}
		w.markProvenanceFailure("link_lead_to_search", err)
		return err
	}

	if isInserted {
		atomic.AddUint64(&w.metrics.SearchLeadLinksInserted, 1)
	} else {
		atomic.AddUint64(&w.metrics.SearchLeadLinksUnchanged, 1)
	}

	return nil
}

func (w *Writer) Run(ctx context.Context, in <-chan scrapemate.Result) error {
	if w.disabled {
		for range in {
			// Consume channel silently
		}
		return nil
	}

	batch := make([]*gmaps.Entry, 0, w.batchSize)
	ticker := time.NewTicker(w.saveInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			w.flushBatch(context.Background(), batch)
			return nil
		case <-ticker.C:
			if len(batch) > 0 {
				w.flushBatch(ctx, batch)
				batch = batch[:0]
			}
		case result, ok := <-in:
			if !ok {
				if len(batch) > 0 {
					w.flushBatch(ctx, batch)
				}
				return nil
			}

			var entry *gmaps.Entry
			switch v := result.Data.(type) {
			case *gmaps.Entry:
				entry = v
			case gmaps.Entry:
				entry = &v
			}

			if entry == nil || entry.Title == "" {
				continue
			}

			batch = append(batch, entry)
			if len(batch) >= w.batchSize {
				w.flushBatch(ctx, batch)
				batch = batch[:0]
			}
		}
	}
}

func (w *Writer) flushBatch(ctx context.Context, entries []*gmaps.Entry) {
	if len(entries) == 0 || w.pool == nil {
		return
	}

	saveCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	for _, entry := range entries {
		res, err := w.upsertLeadWithContext(saveCtx, entry, "", "")
		_ = res
		if err != nil {
			atomic.AddUint64(&w.metrics.Failed, 1)
			log.Warn("shadow persistence upsert failed gracefully", "operation", "upsert_lead", "error_class", ProvenanceErrorClass(err))
		}
	}
}

// ResolveIdentity resolves an existing record in public.prospect_leads_google in strict priority (PASSO 2):
// 1. place_id
// 2. cid (if non-empty)
// 3. whatsapp (if non-empty)
func (w *Writer) ResolveIdentity(ctx context.Context, lead *ProspectLead) (string, error) {
	if lead == nil || w.pool == nil {
		return "", nil
	}

	// 1. Lookup by place_id
	if lead.PlaceID != "" {
		var existingID string
		err := w.pool.QueryRow(ctx, "SELECT place_id FROM public.prospect_leads_google WHERE place_id = $1", lead.PlaceID).Scan(&existingID)
		if err == nil && existingID != "" {
			return existingID, nil
		}
	}

	// 2. Lookup by cid
	if lead.Cid != "" {
		var existingID string
		err := w.pool.QueryRow(ctx, "SELECT place_id FROM public.prospect_leads_google WHERE cid = $1", lead.Cid).Scan(&existingID)
		if err == nil && existingID != "" {
			return existingID, nil
		}
	}

	// 3. Lookup by whatsapp
	if lead.Whatsapp != "" {
		var existingID string
		err := w.pool.QueryRow(ctx, "SELECT place_id FROM public.prospect_leads_google WHERE whatsapp = $1", lead.Whatsapp).Scan(&existingID)
		if err == nil && existingID != "" {
			return existingID, nil
		}
	}

	return "", nil
}

func (w *Writer) updateExistingLead(ctx context.Context, canonicalPlaceID string, lead *ProspectLead) error {
	q := `
	WITH old_row AS (
		SELECT place_id, cid, place_name, category, categories, address, phone, whatsapp, website, review_rating, review_count
		FROM public.prospect_leads_google
		WHERE place_id = $1::text
	),
	updated AS (
		UPDATE public.prospect_leads_google AS target SET
			cid = CASE WHEN $2::text IS NOT NULL AND $2::text != '' THEN $2::text ELSE target.cid END,
			place_name = $3::text,
			category = $4::text,
			categories = $5::jsonb,
			address = CASE WHEN $6::text IS NOT NULL AND $6::text != '' THEN $6::text ELSE target.address END,
			street = CASE WHEN $7::text IS NOT NULL AND $7::text != '' THEN $7::text ELSE target.street END,
			city = CASE WHEN $8::text IS NOT NULL AND $8::text != '' THEN $8::text ELSE target.city END,
			state = CASE WHEN $9::text IS NOT NULL AND $9::text != '' THEN $9::text ELSE target.state END,
			postal_code = CASE WHEN $10::text IS NOT NULL AND $10::text != '' THEN $10::text ELSE target.postal_code END,
			country = CASE WHEN $11::text IS NOT NULL AND $11::text != '' THEN $11::text ELSE target.country END,
			phone = CASE WHEN $12::text IS NOT NULL AND $12::text != '' THEN $12::text ELSE target.phone END,
			whatsapp = CASE WHEN $13::text IS NOT NULL AND $13::text != '' THEN $13::text ELSE target.whatsapp END,
			website = CASE WHEN $14::text IS NOT NULL AND $14::text != '' THEN $14::text ELSE target.website END,
			emails = CASE WHEN $15::jsonb IS NOT NULL AND $15::jsonb != '[]'::jsonb AND $15::jsonb != 'null'::jsonb THEN $15::jsonb ELSE target.emails END,
			email = CASE WHEN $16::text IS NOT NULL AND $16::text != '' THEN $16::text ELSE target.email END,
			review_rating = $17::numeric,
			review_count = $18::int,
			latitude = $19::double precision,
			longitude = $20::double precision,
			google_maps_link = CASE WHEN $21::text IS NOT NULL AND $21::text != '' THEN $21::text ELSE target.google_maps_link END,
			job_id = COALESCE(NULLIF($22::text, ''), target.job_id),
			job_name = COALESCE(NULLIF($23::text, ''), target.job_name),
			updated_at = NOW()
		WHERE target.place_id = $1::text
		RETURNING 1
	)
	SELECT 
		(
			(old.cid IS DISTINCT FROM $2::text AND $2::text != '') OR
			old.place_name IS DISTINCT FROM $3::text OR
			old.category IS DISTINCT FROM $4::text OR
			old.categories IS DISTINCT FROM $5::jsonb OR
			(NULLIF($6::text, '') IS NOT NULL AND old.address IS DISTINCT FROM $6::text) OR
			(NULLIF($12::text, '') IS NOT NULL AND old.phone IS DISTINCT FROM $12::text) OR
			(NULLIF($13::text, '') IS NOT NULL AND old.whatsapp IS DISTINCT FROM $13::text) OR
			(NULLIF($14::text, '') IS NOT NULL AND old.website IS DISTINCT FROM $14::text) OR
			old.review_rating IS DISTINCT FROM $17::numeric OR
			old.review_count IS DISTINCT FROM $18::int
		) AS is_modified
	FROM old_row old;
	`

	var isModified bool
	err := w.pool.QueryRow(ctx, q,
		canonicalPlaceID,
		lead.Cid,
		lead.PlaceName,
		lead.Category,
		lead.CategoriesJSON,
		lead.Address,
		lead.Street,
		lead.City,
		lead.State,
		lead.PostalCode,
		lead.Country,
		lead.Phone,
		lead.Whatsapp,
		lead.Website,
		lead.EmailsJSON,
		lead.Email,
		lead.ReviewRating,
		lead.ReviewCount,
		lead.Latitude,
		lead.Longitude,
		lead.GoogleMapsLink,
		lead.JobID,
		lead.JobName,
	).Scan(&isModified)

	if err != nil {
		return err
	}

	if isModified {
		atomic.AddUint64(&w.metrics.Updated, 1)
	} else {
		atomic.AddUint64(&w.metrics.Unchanged, 1)
	}

	return nil
}

func (w *Writer) insertLead(ctx context.Context, lead *ProspectLead) (string, error) {
	q := `
	INSERT INTO public.prospect_leads_google (
		place_id, cid, place_name, category, categories, address, street, city, state, postal_code, country,
		phone, whatsapp, website, emails, email, review_rating, review_count,
		latitude, longitude, google_maps_link, job_id, job_name, updated_at
	) VALUES (
		$1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11,
		$12, $13, $14, $15::jsonb, $16, $17, $18,
		$19, $20, $21, NULLIF($22, ''), NULLIF($23, ''), NOW()
	)
	`
	_, err := w.pool.Exec(ctx, q,
		lead.PlaceID,
		lead.Cid,
		lead.PlaceName,
		lead.Category,
		lead.CategoriesJSON,
		lead.Address,
		lead.Street,
		lead.City,
		lead.State,
		lead.PostalCode,
		lead.Country,
		lead.Phone,
		lead.Whatsapp,
		lead.Website,
		lead.EmailsJSON,
		lead.Email,
		lead.ReviewRating,
		lead.ReviewCount,
		lead.Latitude,
		lead.Longitude,
		lead.GoogleMapsLink,
		lead.JobID,
		lead.JobName,
	)

	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "23505" {
			// Concurrency / unique violation recovery (GATE 3):
			// Locate existing canonical record and update it instead of failing
			existingID, resErr := w.ResolveIdentity(ctx, lead)
			if resErr == nil && existingID != "" {
				updateErr := w.updateExistingLead(ctx, existingID, lead)
				return existingID, updateErr
			}
		}
		return lead.PlaceID, err
	}

	atomic.AddUint64(&w.metrics.Inserted, 1)
	return lead.PlaceID, nil
}

func (w *Writer) UpsertLead(ctx context.Context, entry *gmaps.Entry) error {
	_, err := w.upsertLeadWithContext(ctx, entry, "", "")
	return err
}

func (w *Writer) UpsertLeadWithContext(ctx context.Context, entry *gmaps.Entry, jobID, jobName string) (*UpsertLeadResult, error) {
	return w.upsertLeadWithContext(ctx, entry, jobID, jobName)
}

func (w *Writer) upsertLead(ctx context.Context, entry *gmaps.Entry) (*UpsertLeadResult, error) {
	return w.upsertLeadWithContext(ctx, entry, "", "")
}

func (w *Writer) upsertLeadWithContext(ctx context.Context, entry *gmaps.Entry, jobID, jobName string) (*UpsertLeadResult, error) {
	if entry == nil {
		return nil, nil
	}

	w.mu.Lock()
	if jobID == "" {
		jobID = w.jobID
	}
	if jobName == "" {
		jobName = w.jobName
	}
	w.mu.Unlock()

	lead := w.mapper.MapToProspectLead(entry, jobID, jobName)
	if err := w.validator.Validate(lead); err != nil {
		return nil, err
	}

	// 1. Resolve identity across place_id, cid, and whatsapp
	existingID, err := w.ResolveIdentity(ctx, lead)
	if err != nil {
		atomic.AddUint64(&w.metrics.Failed, 1)
		return nil, err
	}

	var canonicalPlaceID string
	var outcome UpsertOutcome

	if existingID != "" {
		// Existing canonical lead found: UPDATE without mutating place_id or SDR fields
		canonicalPlaceID = existingID
		err = w.updateExistingLead(ctx, canonicalPlaceID, lead)
		outcome = OutcomeUpdated
	} else {
		// Fresh lead: INSERT (recovers to update if race condition occurs on CID/WhatsApp)
		canonicalPlaceID, err = w.insertLead(ctx, lead)
		if canonicalPlaceID != lead.PlaceID {
			outcome = OutcomeUpdated
		} else {
			outcome = OutcomeInserted
		}
	}

	if err != nil {
		atomic.AddUint64(&w.metrics.Failed, 1)
		return nil, err
	}

	// 2. Link lead to search using CANONICAL place ID ONLY (GATE 3 Fix)
	if lead.JobID != "" && canonicalPlaceID != "" {
		if linkErr := w.LinkLeadToSearch(ctx, lead.JobID, canonicalPlaceID, 0); linkErr != nil {
			log.Warn("shadow provenance link failed; continuing lead persistence", "operation", "link_lead_to_search")
		}
	}

	return &UpsertLeadResult{
		CanonicalPlaceID: canonicalPlaceID,
		Outcome:          outcome,
	}, nil
}

// FindCompletedSearch searches for an existing completed search matching query and optional location.
func (w *Writer) FindCompletedSearch(ctx context.Context, query string, location string) (*SearchContext, error) {
	if w.disabled || w.pool == nil {
		return nil, errors.New("writer disabled or uninitialized")
	}

	query = strings.TrimSpace(query)
	location = strings.TrimSpace(location)
	if query == "" {
		return nil, errors.New("query is required")
	}

	sql := `
		SELECT search_id, job_id, COALESCE(query, ''), COALESCE(location, ''), COALESCE(category, ''), requested_limit
		FROM public.prospect_searches
		WHERE status = 'completed'
		  AND LOWER(TRIM(query)) = LOWER($1)
		  AND ($2 = '' OR LOWER(TRIM(location)) = LOWER($2))
		ORDER BY completed_at DESC NULLS LAST, created_at DESC
		LIMIT 1
	`

	var s SearchContext
	err := w.pool.QueryRow(ctx, sql, query, location).Scan(
		&s.SearchID,
		&s.JobID,
		&s.Query,
		&s.Location,
		&s.Category,
		&s.RequestedLimit,
	)
	if err != nil {
		return nil, err
	}
	return &s, nil
}

// FetchLeadsForSearch retrieves the canonical leads linked to a specific search_id.
func (w *Writer) FetchLeadsForSearch(ctx context.Context, searchID string, limit int) ([]*ProspectLead, error) {
	if w.disabled || w.pool == nil {
		return nil, errors.New("writer disabled or uninitialized")
	}

	if limit <= 0 {
		limit = 1000
	}

	sql := `
		SELECT 
			g.place_id, COALESCE(g.cid, ''), g.place_name, COALESCE(g.category, ''),
			COALESCE(g.address, ''), COALESCE(g.street, ''), COALESCE(g.city, ''),
			COALESCE(g.state, ''), COALESCE(g.postal_code, ''), COALESCE(g.country, ''),
			COALESCE(g.phone, ''), COALESCE(g.whatsapp, ''), COALESCE(g.website, ''),
			COALESCE(g.email, ''), g.review_rating, g.review_count,
			g.latitude, g.longitude, COALESCE(g.google_maps_link, '')
		FROM public.prospect_search_leads sl
		JOIN public.prospect_leads_google g ON sl.place_id = g.place_id
		WHERE sl.search_id = $1
		ORDER BY sl.result_order ASC, sl.discovered_at ASC, sl.created_at ASC
		LIMIT $2
	`

	rows, err := w.pool.Query(ctx, sql, searchID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var leads []*ProspectLead
	for rows.Next() {
		var l ProspectLead
		err := rows.Scan(
			&l.PlaceID, &l.Cid, &l.PlaceName, &l.Category,
			&l.Address, &l.Street, &l.City,
			&l.State, &l.PostalCode, &l.Country,
			&l.Phone, &l.Whatsapp, &l.Website,
			&l.Email, &l.ReviewRating, &l.ReviewCount,
			&l.Latitude, &l.Longitude, &l.GoogleMapsLink,
		)
		if err != nil {
			return nil, err
		}
		leads = append(leads, &l)
	}

	if err := rows.Err(); err != nil {
		return nil, err
	}

	return leads, nil
}

// WriteLeadsToCSVFile exports a slice of ProspectLeads to a standard CSV file matching gmaps.Entry header specs.
func (w *Writer) WriteLeadsToCSVFile(leads []*ProspectLead, filePath string) error {
	f, err := os.Create(filePath)
	if err != nil {
		return err
	}
	defer f.Close()

	cw := csv.NewWriter(f)
	defer cw.Flush()

	header := (&gmaps.Entry{}).CsvHeaders()
	if err := cw.Write(header); err != nil {
		return err
	}

	for _, lead := range leads {
		entry := &gmaps.Entry{
			Title:        lead.PlaceName,
			Category:     lead.Category,
			Address:      lead.Address,
			WebSite:      lead.Website,
			Phone:        lead.Phone,
			ReviewCount:  lead.ReviewCount,
			ReviewRating: lead.ReviewRating,
			Latitude:     lead.Latitude,
			Longtitude:   lead.Longitude,
			Cid:          lead.Cid,
			Link:         lead.GoogleMapsLink,
		}
		if err := cw.Write(entry.CsvRow()); err != nil {
			return err
		}
	}
	return nil
}
