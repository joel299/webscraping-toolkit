package shadow

import (
	"context"
	"encoding/json"
	"os"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/gosom/scrapemate"

	"github.com/gosom/google-maps-scraper/gmaps"
	"github.com/gosom/google-maps-scraper/log"
)

var nonDigitRegex = regexp.MustCompile(`\D+`)
var dsnPasswordRegex = regexp.MustCompile(`postgres(ql)?://([^:]+):([^@]+)@`)

// NormalizePhoneBR converts Brazilian phone numbers to 55 + DDD + number (digits only).
func NormalizePhoneBR(phone string) string {
	digits := nonDigitRegex.ReplaceAllString(phone, "")
	if digits == "" {
		return ""
	}

	if strings.HasPrefix(digits, "0") && len(digits) >= 11 {
		digits = strings.TrimPrefix(digits, "0")
	}

	if strings.HasPrefix(digits, "55") && (len(digits) == 12 || len(digits) == 13) {
		return digits
	}

	if len(digits) == 10 || len(digits) == 11 {
		return "55" + digits
	}

	return digits
}

// SanitizeDSN removes passwords from connection strings to prevent credential exposure in logs.
func SanitizeDSN(dsn string) string {
	if dsn == "" {
		return ""
	}
	return dsnPasswordRegex.ReplaceAllString(dsn, "postgres://$2:*****@")
}

// LoadDSN loads the PostgreSQL DSN securely from server-side file or environment.
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

type Metrics struct {
	Inserted  uint64 `json:"inserted"`
	Updated   uint64 `json:"updated"`
	Unchanged uint64 `json:"unchanged"`
	Failed    uint64 `json:"failed"`
}

type Writer struct {
	pool         *pgxpool.Pool
	saveInterval time.Duration
	batchSize    int
	metrics      Metrics
	mu           sync.Mutex
	disabled     bool
}

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

	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		log.Warn("shadow persistence disabled: failed to initialize pool", "dsn", SanitizeDSN(dsn), "error", err)
		return NewDisabledWriter()
	}

	if err := pool.Ping(ctx); err != nil {
		log.Warn("shadow persistence operating in shadow-fail mode: ping failed", "dsn", SanitizeDSN(dsn), "error", err)
	} else {
		log.Info("shadow persistence connected successfully", "dsn", SanitizeDSN(dsn))
		if err := initSchema(ctx, pool); err != nil {
			log.Warn("shadow persistence schema init warning", "error", err)
		}
	}

	return &Writer{
		pool:         pool,
		saveInterval: 5 * time.Second,
		batchSize:    10,
	}
}

func NewDisabledWriter() *Writer {
	return &Writer{
		disabled: true,
	}
}

func NewWriter(pool *pgxpool.Pool, saveInterval time.Duration, batchSize int) *Writer {
	return &Writer{
		pool:         pool,
		saveInterval: saveInterval,
		batchSize:    batchSize,
	}
}

func (w *Writer) GetMetrics() Metrics {
	return Metrics{
		Inserted:  atomic.LoadUint64(&w.metrics.Inserted),
		Updated:   atomic.LoadUint64(&w.metrics.Updated),
		Unchanged: atomic.LoadUint64(&w.metrics.Unchanged),
		Failed:    atomic.LoadUint64(&w.metrics.Failed),
	}
}

func initSchema(ctx context.Context, pool *pgxpool.Pool) error {
	q := `
	CREATE TABLE IF NOT EXISTS public.prospect_leads_google (
		place_id TEXT PRIMARY KEY,
		cid TEXT,
		place_name TEXT NOT NULL,
		category TEXT,
		categories JSONB,
		address TEXT,
		street TEXT,
		city TEXT,
		state TEXT,
		postal_code TEXT,
		country TEXT,
		phone TEXT,
		whatsapp TEXT,
		website TEXT,
		emails JSONB,
		email TEXT,
		review_rating NUMERIC,
		review_count INT,
		latitude DOUBLE PRECISION,
		longitude DOUBLE PRECISION,
		google_maps_link TEXT,
		job_id TEXT,
		job_name TEXT,
		created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
		updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
		
		-- Commercial / SDR State Fields (PRESERVED ON UPSERT - NEVER OVERWRITTEN BY SCRAPER)
		lead_status TEXT DEFAULT 'new',
		pipeline_stage TEXT DEFAULT 'prospect',
		followup_count INT DEFAULT 0,
		followup_at TIMESTAMPTZ,
		followup_notes TEXT,
		converted BOOLEAN DEFAULT FALSE,
		do_not_contact BOOLEAN DEFAULT FALSE,
		processing_status TEXT DEFAULT 'pending',
		sdr_owner TEXT,
		commercial_history JSONB DEFAULT '[]'::jsonb,
		appointments JSONB DEFAULT '[]'::jsonb,
		responses JSONB DEFAULT '[]'::jsonb
	);
	CREATE INDEX IF NOT EXISTS idx_prospect_leads_google_whatsapp ON public.prospect_leads_google(whatsapp);
	CREATE INDEX IF NOT EXISTS idx_prospect_leads_google_cid ON public.prospect_leads_google(cid);

	CREATE TABLE IF NOT EXISTS public.leads (
		place_id TEXT PRIMARY KEY,
		title TEXT NOT NULL,
		category TEXT,
		categories JSONB,
		address TEXT,
		street TEXT,
		city TEXT,
		state TEXT,
		postal_code TEXT,
		country TEXT,
		phone TEXT,
		phone_normalized TEXT,
		website TEXT,
		emails JSONB,
		email TEXT,
		review_rating NUMERIC,
		review_count INT,
		latitude DOUBLE PRECISION,
		longitude DOUBLE PRECISION,
		google_maps_link TEXT,
		job_id TEXT,
		job_name TEXT,
		created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
		updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

		lead_status TEXT DEFAULT 'new',
		pipeline_stage TEXT DEFAULT 'prospect',
		followup_count INT DEFAULT 0,
		followup_at TIMESTAMPTZ,
		followup_notes TEXT,
		converted BOOLEAN DEFAULT FALSE,
		do_not_contact BOOLEAN DEFAULT FALSE,
		processing_status TEXT DEFAULT 'pending',
		sdr_owner TEXT,
		commercial_history JSONB DEFAULT '[]'::jsonb,
		appointments JSONB DEFAULT '[]'::jsonb,
		responses JSONB DEFAULT '[]'::jsonb
	);
	`
	_, err := pool.Exec(ctx, q)
	return err
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

			entry, ok := result.Data.(*gmaps.Entry)
			if !ok || entry == nil || entry.Title == "" {
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
		err := w.upsertLead(saveCtx, entry)
		if err != nil {
			atomic.AddUint64(&w.metrics.Failed, 1)
			log.Warn("shadow persistence upsert failed gracefully", "place", entry.Title, "error", err)
		}
	}
}

func (w *Writer) UpsertLead(ctx context.Context, entry *gmaps.Entry) error {
	return w.upsertLead(ctx, entry)
}

func (w *Writer) upsertLead(ctx context.Context, entry *gmaps.Entry) error {
	placeID := entry.DataID
	if placeID == "" {
		placeID = entry.PlaceID
	}
	if placeID == "" {
		placeID = entry.ID
	}
	if placeID == "" {
		placeID = strings.ToLower(entry.Title + "|" + entry.Address)
	}

	phoneNorm := NormalizePhoneBR(entry.Phone)

	var emailFirst string
	if len(entry.Emails) > 0 {
		emailFirst = entry.Emails[0]
	}

	categoriesJSON, _ := json.Marshal(entry.Categories)
	emailsJSON, _ := json.Marshal(entry.Emails)

	q := `
	INSERT INTO public.prospect_leads_google (
		place_id, cid, place_name, category, categories, address, street, city, state, postal_code, country,
		phone, whatsapp, website, emails, email, review_rating, review_count,
		latitude, longitude, google_maps_link, job_id, job_name, updated_at
	) VALUES (
		$1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
		$12, $13, $14, $15, $16, $17, $18,
		$19, $20, $21, $22, $23, NOW()
	)
	ON CONFLICT (place_id) DO UPDATE SET
		cid = EXCLUDED.cid,
		place_name = EXCLUDED.place_name,
		category = EXCLUDED.category,
		categories = EXCLUDED.categories,
		address = EXCLUDED.address,
		street = EXCLUDED.street,
		city = EXCLUDED.city,
		state = EXCLUDED.state,
		postal_code = EXCLUDED.postal_code,
		country = EXCLUDED.country,
		phone = EXCLUDED.phone,
		whatsapp = EXCLUDED.whatsapp,
		website = EXCLUDED.website,
		emails = EXCLUDED.emails,
		email = EXCLUDED.email,
		review_rating = EXCLUDED.review_rating,
		review_count = EXCLUDED.review_count,
		latitude = EXCLUDED.latitude,
		longitude = EXCLUDED.longitude,
		google_maps_link = EXCLUDED.google_maps_link,
		job_id = EXCLUDED.job_id,
		job_name = EXCLUDED.job_name,
		updated_at = NOW()
	RETURNING (xmax = 0) AS is_inserted;
	`

	var isInserted bool
	err := w.pool.QueryRow(ctx, q,
		placeID,
		entry.Cid,
		entry.Title,
		entry.Category,
		categoriesJSON,
		entry.Address,
		entry.CompleteAddress.Street,
		entry.CompleteAddress.City,
		entry.CompleteAddress.State,
		entry.CompleteAddress.PostalCode,
		entry.CompleteAddress.Country,
		entry.Phone,
		phoneNorm,
		entry.WebSite,
		emailsJSON,
		emailFirst,
		entry.ReviewRating,
		entry.ReviewCount,
		entry.Latitude,
		entry.Longtitude,
		entry.Link,
		entry.ID,
		entry.Title,
	).Scan(&isInserted)

	if err != nil {
		return err
	}

	if isInserted {
		atomic.AddUint64(&w.metrics.Inserted, 1)
	} else {
		atomic.AddUint64(&w.metrics.Updated, 1)
	}

	// Dual write to legacy leads table for backward compatibility if present
	qLegacy := `
	INSERT INTO public.leads (
		place_id, title, category, categories, address, street, city, state, postal_code, country,
		phone, phone_normalized, website, emails, email, review_rating, review_count,
		latitude, longitude, google_maps_link, job_id, job_name, updated_at
	) VALUES (
		$1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
		$11, $12, $13, $14, $15, $16, $17,
		$18, $19, $20, $21, $22, NOW()
	)
	ON CONFLICT (place_id) DO UPDATE SET
		title = EXCLUDED.title,
		category = EXCLUDED.category,
		categories = EXCLUDED.categories,
		address = EXCLUDED.address,
		phone = EXCLUDED.phone,
		phone_normalized = EXCLUDED.phone_normalized,
		website = EXCLUDED.website,
		emails = EXCLUDED.emails,
		review_rating = EXCLUDED.review_rating,
		review_count = EXCLUDED.review_count,
		latitude = EXCLUDED.latitude,
		longitude = EXCLUDED.longitude,
		updated_at = NOW();
	`
	_, _ = w.pool.Exec(ctx, qLegacy,
		placeID, entry.Title, entry.Category, categoriesJSON, entry.Address,
		entry.CompleteAddress.Street, entry.CompleteAddress.City, entry.CompleteAddress.State,
		entry.CompleteAddress.PostalCode, entry.CompleteAddress.Country, entry.Phone,
		phoneNorm, entry.WebSite, emailsJSON, emailFirst, entry.ReviewRating,
		entry.ReviewCount, entry.Latitude, entry.Longtitude, entry.Link, entry.ID, entry.Title,
	)

	return nil
}
