package shadow

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/gosom/scrapemate"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/gosom/google-maps-scraper/gmaps"
)

func TestIntegrationShadowPersistence(t *testing.T) {
	testDSN := "postgres://postgres:shadowpass@127.0.0.1:5439/prospects_db?sslmode=disable"

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	config, err := pgxpool.ParseConfig(testDSN)
	if err != nil {
		t.Skip("Skipping integration test: PostgreSQL container not reachable")
		return
	}

	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil || pool.Ping(ctx) != nil {
		t.Skip("Skipping integration test: PostgreSQL container ping failed")
		return
	}
	defer pool.Close()

	// 1. Create secret file
	tmpDir := t.TempDir()
	secretPath := filepath.Join(tmpDir, "prospect_database_url")
	require.NoError(t, os.WriteFile(secretPath, []byte(testDSN+"\n"), 0600))
	t.Setenv("PROSPECT_DATABASE_URL_FILE", secretPath)

	// 2. Initialize Shadow Writer
	rawWriter := NewWriterFromEnv()
	writer, ok := rawWriter.(*Writer)
	require.True(t, ok)
	require.False(t, writer.disabled)

	// Clean tables if exist
	_, _ = pool.Exec(ctx, "DROP TABLE IF EXISTS public.prospect_leads_google")
	_, _ = pool.Exec(ctx, "DROP TABLE IF EXISTS public.leads")
	require.NoError(t, initSchema(ctx, pool))

	// 3. Test New Lead Insert (INSERTED)
	entry1 := &gmaps.Entry{
		ID:          "lead-001",
		DataID:      "data-001",
		Cid:         "123456789",
		Title:       "Hamburgueria Búfalo Beef",
		Category:    "Hamburgueria",
		Categories:  []string{"Hamburgueria", "Restaurante"},
		Address:     "Av. Afonso Pena, 1000 - Campo Grande, MS",
		Phone:       "+55 (67) 99999-8888",
		WebSite:     "https://bufalobeef.com.br",
		Emails:      []string{"contato@bufalobeef.com.br"},
		ReviewRating: 4.8,
		ReviewCount: 150,
		Latitude:    -20.4500,
		Longtitude:  -54.6000,
		Link:        "https://maps.google.com/?cid=123456789",
	}

	ch := make(chan scrapemate.Result, 1)
	ch <- scrapemate.Result{Data: entry1}
	close(ch)

	require.NoError(t, writer.Run(ctx, ch))

	m1 := writer.GetMetrics()
	assert.Equal(t, uint64(1), m1.Inserted, "First write must increment Inserted metric")
	assert.Equal(t, uint64(0), m1.Updated)

	// Verify phone normalization and saved values in public.prospect_leads_google
	var (
		savedWhatsapp    string
		savedPlaceName   string
		savedCid         string
		savedLeadStatus  string
		savedPipeline    string
		savedConverted   bool
		savedDoNotContact bool
	)

	err = pool.QueryRow(ctx, `
		SELECT whatsapp, place_name, cid, lead_status, pipeline_stage, converted, do_not_contact
		FROM public.prospect_leads_google WHERE place_id = $1
	`, "data-001").Scan(&savedWhatsapp, &savedPlaceName, &savedCid, &savedLeadStatus, &savedPipeline, &savedConverted, &savedDoNotContact)

	require.NoError(t, err)
	assert.Equal(t, "5567999998888", savedWhatsapp, "WhatsApp must be normalized to 55+DDD+Number")
	assert.Equal(t, "Hamburgueria Búfalo Beef", savedPlaceName)
	assert.Equal(t, "123456789", savedCid)
	assert.Equal(t, "new", savedLeadStatus)
	assert.Equal(t, "prospect", savedPipeline)
	assert.False(t, savedConverted)
	assert.False(t, savedDoNotContact)

	// 4. Update Commercial SDR State in PostgreSQL directly (Simulate SDR team work)
	_, err = pool.Exec(ctx, `
		UPDATE public.prospect_leads_google SET
			lead_status = 'QUALIFIED_SDR',
			pipeline_stage = 'NEGOTIATION',
			followup_count = 3,
			converted = TRUE,
			do_not_contact = TRUE
		WHERE place_id = $1
	`, "data-001")
	require.NoError(t, err)

	// 5. Test Existing Lead Rescrape (UPSERT - UPDATED)
	entry1Updated := &gmaps.Entry{
		ID:          "lead-001",
		DataID:      "data-001",
		Cid:         "123456789",
		Title:       "Hamburgueria Búfalo Beef Premium", // Title updated by scraper
		Category:    "Hamburgueria Gourmet",
		Categories:  []string{"Hamburgueria Gourmet"},
		Address:     "Av. Afonso Pena, 1000 - Campo Grande, MS",
		Phone:       "(67) 99999-8888",
		WebSite:     "https://bufalobeef.com.br",
		Emails:      []string{"contato@bufalobeef.com.br", "sac@bufalobeef.com.br"},
		ReviewRating: 4.9, // Rating updated
		ReviewCount: 180, // Review count updated
		Latitude:    -20.4500,
		Longtitude:  -54.6000,
		Link:        "https://maps.google.com/?cid=123456789",
	}

	ch2 := make(chan scrapemate.Result, 1)
	ch2 <- scrapemate.Result{Data: entry1Updated}
	close(ch2)

	require.NoError(t, writer.Run(ctx, ch2))

	m2 := writer.GetMetrics()
	assert.Equal(t, uint64(1), m2.Inserted)
	assert.Equal(t, uint64(1), m2.Updated, "Second write of same lead must increment Updated metric")

	// 6. Verify Commercial State Preservation (MUST NOT BE OVERWRITTEN)
	var (
		checkPlaceName   string
		checkRating      float64
		checkLeadStatus  string
		checkPipeline    string
		checkFollowup    int
		checkConverted   bool
		checkDoNotContact bool
	)

	err = pool.QueryRow(ctx, `
		SELECT place_name, review_rating, lead_status, pipeline_stage, followup_count, converted, do_not_contact
		FROM public.prospect_leads_google WHERE place_id = $1
	`, "data-001").Scan(&checkPlaceName, &checkRating, &checkLeadStatus, &checkPipeline, &checkFollowup, &checkConverted, &checkDoNotContact)

	require.NoError(t, err)
	// Scraped enrichment fields updated:
	assert.Equal(t, "Hamburgueria Búfalo Beef Premium", checkPlaceName)
	assert.Equal(t, 4.9, checkRating)

	// Commercial SDR fields PRESERVED:
	assert.Equal(t, "QUALIFIED_SDR", checkLeadStatus, "lead_status must NOT be overwritten by scraper")
	assert.Equal(t, "NEGOTIATION", checkPipeline, "pipeline_stage must NOT be overwritten by scraper")
	assert.Equal(t, 3, checkFollowup, "followup_count must NOT be overwritten by scraper")
	assert.True(t, checkConverted, "converted must NOT be overwritten by scraper")
	assert.True(t, checkDoNotContact, "do_not_contact must NOT be overwritten by scraper")
}

func TestShadowFallbackMode(t *testing.T) {
	// Point DSN to non-existent port
	badDSN := "postgres://postgres:badpass@127.0.0.1:59999/prospects_db?sslmode=disable"
	t.Setenv("PROSPECT_DATABASE_URL", badDSN)

	writer := NewWriterFromEnv()
	require.NotNil(t, writer)

	// Run job results through shadow writer in fallback mode
	ch := make(chan scrapemate.Result, 1)
	ch <- scrapemate.Result{Data: &gmaps.Entry{Title: "Test Lead Offline", Phone: "67999999999"}}
	close(ch)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	// Must complete cleanly without returning error to scrapemate
	err := writer.Run(ctx, ch)
	assert.NoError(t, err, "Shadow writer in fallback mode must not fail or crash scrapemate pipeline")
}
