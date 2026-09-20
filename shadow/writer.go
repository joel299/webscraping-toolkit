package shadow

import (
	"context"
	"fmt"
	"os"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gosom/scrapemate"
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
	mapper       *ProspectLeadMapper
	validator    *ProspectLeadValidator
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

	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		log.Warn("shadow persistence disabled: failed to initialize pool", "dsn", SanitizeDSN(dsn), "error", err)
		return NewDisabledWriter()
	}

	if err := pool.Ping(ctx); err != nil {
		log.Warn("shadow persistence operating in shadow-fail mode: ping failed", "dsn", SanitizeDSN(dsn), "error", err)
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
		log.Warn("shadow persistence schema validation warning: table missing or unreadable; shadow writer entering shadow-fail mode", "error", err)
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
		Inserted:  atomic.LoadUint64(&w.metrics.Inserted),
		Updated:   atomic.LoadUint64(&w.metrics.Updated),
		Unchanged: atomic.LoadUint64(&w.metrics.Unchanged),
		Failed:    atomic.LoadUint64(&w.metrics.Failed),
	}
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
		err := w.upsertLead(saveCtx, entry)
		if err != nil {
			atomic.AddUint64(&w.metrics.Failed, 1)
			log.Warn("shadow persistence upsert failed gracefully", "place", entry.Title, "error", err)
			fmt.Printf("SHADOW_UPSERT_ERROR: place=%s err=%v\n", entry.Title, err)
		}
	}
}

func (w *Writer) UpsertLead(ctx context.Context, entry *gmaps.Entry) error {
	return w.upsertLead(ctx, entry)
}

func (w *Writer) upsertLead(ctx context.Context, entry *gmaps.Entry) error {
	if entry == nil {
		return nil
	}

	lead := w.mapper.MapToProspectLead(entry, "", "")
	if err := w.validator.Validate(lead); err != nil {
		return err
	}

	// SQL non-destructive UPSERT with exact metrics tracking (GATE 8 & GATE 9)
	q := `
	INSERT INTO public.prospect_leads_google AS target (
		place_id, cid, place_name, category, categories, address, street, city, state, postal_code, country,
		phone, whatsapp, website, emails, email, review_rating, review_count,
		latitude, longitude, google_maps_link, job_id, job_name, updated_at
	) VALUES (
		$1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11,
		$12, $13, $14, $15::jsonb, $16, $17, $18,
		$19, $20, $21, NULLIF($22, ''), NULLIF($23, ''), NOW()
	)
	ON CONFLICT (place_id) DO UPDATE SET
		cid = CASE WHEN EXCLUDED.cid IS NOT NULL AND EXCLUDED.cid != '' THEN EXCLUDED.cid ELSE target.cid END,
		place_name = EXCLUDED.place_name,
		category = EXCLUDED.category,
		categories = EXCLUDED.categories,
		address = CASE WHEN EXCLUDED.address IS NOT NULL AND EXCLUDED.address != '' THEN EXCLUDED.address ELSE target.address END,
		street = EXCLUDED.street,
		city = EXCLUDED.city,
		state = EXCLUDED.state,
		postal_code = EXCLUDED.postal_code,
		country = EXCLUDED.country,
		phone = CASE WHEN EXCLUDED.phone IS NOT NULL AND EXCLUDED.phone != '' THEN EXCLUDED.phone ELSE target.phone END,
		whatsapp = CASE WHEN EXCLUDED.whatsapp IS NOT NULL AND EXCLUDED.whatsapp != '' THEN EXCLUDED.whatsapp ELSE target.whatsapp END,
		website = CASE WHEN EXCLUDED.website IS NOT NULL AND EXCLUDED.website != '' THEN EXCLUDED.website ELSE target.website END,
		emails = CASE WHEN EXCLUDED.emails IS NOT NULL AND EXCLUDED.emails != '[]'::jsonb AND EXCLUDED.emails != 'null'::jsonb THEN EXCLUDED.emails ELSE target.emails END,
		email = CASE WHEN EXCLUDED.email IS NOT NULL AND EXCLUDED.email != '' THEN EXCLUDED.email ELSE target.email END,
		review_rating = EXCLUDED.review_rating,
		review_count = EXCLUDED.review_count,
		latitude = EXCLUDED.latitude,
		longitude = EXCLUDED.longitude,
		google_maps_link = CASE WHEN EXCLUDED.google_maps_link IS NOT NULL AND EXCLUDED.google_maps_link != '' THEN EXCLUDED.google_maps_link ELSE target.google_maps_link END,
		job_id = COALESCE(NULLIF(EXCLUDED.job_id, ''), target.job_id),
		job_name = COALESCE(NULLIF(EXCLUDED.job_name, ''), target.job_name),
		updated_at = NOW()
	RETURNING 
		(xmax::text = '0') AS is_inserted,
		(
			target.place_name IS DISTINCT FROM EXCLUDED.place_name OR
			target.category IS DISTINCT FROM EXCLUDED.category OR
			target.categories IS DISTINCT FROM EXCLUDED.categories OR
			(EXCLUDED.address IS NOT NULL AND EXCLUDED.address != '' AND target.address IS DISTINCT FROM EXCLUDED.address) OR
			(EXCLUDED.phone IS NOT NULL AND EXCLUDED.phone != '' AND target.phone IS DISTINCT FROM EXCLUDED.phone) OR
			(EXCLUDED.whatsapp IS NOT NULL AND EXCLUDED.whatsapp != '' AND target.whatsapp IS DISTINCT FROM EXCLUDED.whatsapp) OR
			(EXCLUDED.website IS NOT NULL AND EXCLUDED.website != '' AND target.website IS DISTINCT FROM EXCLUDED.website) OR
			target.review_rating IS DISTINCT FROM EXCLUDED.review_rating OR
			target.review_count IS DISTINCT FROM EXCLUDED.review_count
		) AS is_modified;
	`

	var isInserted, isModified bool
	err := w.pool.QueryRow(ctx, q,
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
	).Scan(&isInserted, &isModified)

	if err != nil {
		return err
	}

	if isInserted {
		atomic.AddUint64(&w.metrics.Inserted, 1)
	} else if isModified {
		atomic.AddUint64(&w.metrics.Updated, 1)
	} else {
		atomic.AddUint64(&w.metrics.Unchanged, 1)
	}

	return nil
}
