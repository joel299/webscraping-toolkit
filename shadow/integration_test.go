package shadow

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/gosom/scrapemate"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/gosom/google-maps-scraper/gmaps"
)

// applyMigrationFiles executes real versioned SQL migrations (GATE 3).
func applyMigrationFiles(ctx context.Context, pool *pgxpool.Pool) error {
	mig1 := "../supabase/migrations/20260920153500_prospect_leads_google_persistence.sql"
	mig2 := "../supabase/migrations/20260920161000_prospect_leads_google_rls.sql"

	content1, err := os.ReadFile(mig1)
	if err != nil {
		return fmt.Errorf("failed to read migration 1: %w", err)
	}

	content2, err := os.ReadFile(mig2)
	if err != nil {
		return fmt.Errorf("failed to read migration 2: %w", err)
	}

	if _, err := pool.Exec(ctx, string(content1)); err != nil {
		return fmt.Errorf("failed to apply migration 1: %w", err)
	}

	if _, err := pool.Exec(ctx, string(content2)); err != nil {
		return fmt.Errorf("failed to apply migration 2: %w", err)
	}

	return nil
}

func TestIntegrationScalingProgression(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short unit test run")
	}

	testDSN := "postgres://postgres:shadowpass@127.0.0.1:5439/prospects_db?sslmode=disable"

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
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

	// 1. Secret File Setup
	tmpDir := t.TempDir()
	secretPath := filepath.Join(tmpDir, "prospect_database_url")
	require.NoError(t, os.WriteFile(secretPath, []byte(testDSN+"\n"), 0600))
	t.Setenv("PROSPECT_DATABASE_URL_FILE", secretPath)

	// 2. Clean database & Apply real migration files (GATE 3)
	_, _ = pool.Exec(ctx, "DROP TABLE IF EXISTS public.prospect_leads_google CASCADE")
	_, _ = pool.Exec(ctx, "DROP TABLE IF EXISTS public.leads CASCADE")
	require.NoError(t, applyMigrationFiles(ctx, pool))

	// 3. Initialize Shadow Writer
	rawWriter := NewWriterFromEnv()
	writer, ok := rawWriter.(*Writer)
	require.True(t, ok)
	require.False(t, writer.disabled)

	// Build 20 distinct entries
	var dataset []*gmaps.Entry
	for i := 1; i <= 20; i++ {
		entry := &gmaps.Entry{
			ID:           fmt.Sprintf("lead-%03d", i),
			DataID:       fmt.Sprintf("data-%03d", i),
			Cid:          fmt.Sprintf("cid-%03d", i),
			Title:        fmt.Sprintf("Empresa Teste Comercial %03d", i),
			Category:     "Hamburgueria",
			Categories:   []string{"Hamburgueria", "Restaurante"},
			Address:      fmt.Sprintf("Rua Afonso Pena, %d - Campo Grande, MS", i*10),
			Phone:        fmt.Sprintf("+55 (67) 99000-%04d", i),
			WebSite:      fmt.Sprintf("https://empresa%03d.com.br", i),
			Emails:       []string{fmt.Sprintf("contato@empresa%03d.com.br", i)},
			ReviewRating: 4.5 + float64(i%5)*0.1,
			ReviewCount:  50 + i*5,
			Latitude:     -20.4500 + float64(i)*0.001,
			Longtitude:   -54.6000 + float64(i)*0.001,
			Link:         fmt.Sprintf("https://maps.google.com/?cid=cid-%03d", i),
		}
		dataset = append(dataset, entry)
	}

	// --- TEST 1: PERSIST 1 LEAD ---
	ch1 := make(chan scrapemate.Result, 1)
	ch1 <- scrapemate.Result{Data: dataset[0]}
	close(ch1)

	require.NoError(t, writer.Run(ctx, ch1))

	var count1 int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google").Scan(&count1))
	assert.Equal(t, 1, count1, "Count must be 1 after Test 1")

	var savedPhoneNorm string
	require.NoError(t, pool.QueryRow(ctx, "SELECT whatsapp FROM public.prospect_leads_google WHERE place_id = $1", "data-001").Scan(&savedPhoneNorm))
	assert.Equal(t, "5567990000001", savedPhoneNorm, "Phone BR must be normalized to 5567990000001")

	// --- TEST 2: RE-RUN SAME LEAD (UPSERT & COMMERCIAL PRESERVATION) ---
	_, err = pool.Exec(ctx, `
		UPDATE public.prospect_leads_google SET
			lead_status = 'QUALIFIED_SDR',
			pipeline_stage = 'NEGOTIATION',
			followup_count = 5,
			converted = TRUE,
			do_not_contact = TRUE
		WHERE place_id = $1
	`, "data-001")
	require.NoError(t, err)

	updatedEntry1 := *dataset[0]
	updatedEntry1.Title = "Empresa Teste Comercial 001 - Premium"
	updatedEntry1.ReviewRating = 4.9

	ch2 := make(chan scrapemate.Result, 1)
	ch2 <- scrapemate.Result{Data: &updatedEntry1}
	close(ch2)

	require.NoError(t, writer.Run(ctx, ch2))

	var count2 int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google").Scan(&count2))
	assert.Equal(t, 1, count2, "Count must remain 1 (zero duplicates created)")

	var (
		checkTitle        string
		checkRating       float64
		checkLeadStatus   string
		checkPipeline     string
		checkFollowup     int
		checkConverted    bool
		checkDoNotContact bool
	)
	err = pool.QueryRow(ctx, `
		SELECT place_name, review_rating, lead_status, pipeline_stage, followup_count, converted, do_not_contact
		FROM public.prospect_leads_google WHERE place_id = $1
	`, "data-001").Scan(&checkTitle, &checkRating, &checkLeadStatus, &checkPipeline, &checkFollowup, &checkConverted, &checkDoNotContact)

	require.NoError(t, err)
	assert.Equal(t, "Empresa Teste Comercial 001 - Premium", checkTitle)
	assert.Equal(t, 4.9, checkRating)
	assert.Equal(t, "QUALIFIED_SDR", checkLeadStatus, "lead_status must be preserved")
	assert.Equal(t, "NEGOTIATION", checkPipeline, "pipeline_stage must be preserved")
	assert.Equal(t, 5, checkFollowup, "followup_count must be preserved")
	assert.True(t, checkConverted, "converted must be preserved")
	assert.True(t, checkDoNotContact, "do_not_contact must be preserved")

	// --- TEST 2B: NON-DESTRUCTIVE ENRICHMENT PRESERVATION (GATE 8) ---
	emptyReScrape := *dataset[0]
	emptyReScrape.Title = "Empresa Teste Comercial 001 - Premium"
	emptyReScrape.ReviewRating = 4.9
	emptyReScrape.WebSite = "" // Empty on new scrape
	emptyReScrape.Phone = ""   // Empty on new scrape
	emptyReScrape.Address = "" // Empty on new scrape

	ch2b := make(chan scrapemate.Result, 1)
	ch2b <- scrapemate.Result{Data: &emptyReScrape}
	close(ch2b)

	require.NoError(t, writer.Run(ctx, ch2b))

	var (
		preservedWebsite  string
		preservedWhatsapp string
		preservedAddress  string
	)
	err = pool.QueryRow(ctx, `
		SELECT website, whatsapp, address
		FROM public.prospect_leads_google WHERE place_id = $1
	`, "data-001").Scan(&preservedWebsite, &preservedWhatsapp, &preservedAddress)

	require.NoError(t, err)
	assert.Equal(t, "https://empresa001.com.br", preservedWebsite, "Existing website must be preserved when new scrape is empty")
	assert.Equal(t, "5567990000001", preservedWhatsapp, "Existing whatsapp must be preserved when new scrape is empty")
	assert.Contains(t, preservedAddress, "Rua Afonso Pena, 10", "Existing address must be preserved when new scrape is empty")

	// --- TEST 2C: UNCHANGED METRICS INCREMENT (GATE 9) ---
	metricsBefore := writer.GetMetrics()
	ch2c := make(chan scrapemate.Result, 1)
	ch2c <- scrapemate.Result{Data: &emptyReScrape} // Exact same data again
	close(ch2c)

	require.NoError(t, writer.Run(ctx, ch2c))
	metricsAfter := writer.GetMetrics()

	assert.Equal(t, metricsBefore.Unchanged+1, metricsAfter.Unchanged, "Unchanged metric must increment when identical lead is re-scraped")

	// --- TEST 3: 5 LEADS ---
	ch3 := make(chan scrapemate.Result, 4)
	for i := 1; i < 5; i++ {
		ch3 <- scrapemate.Result{Data: dataset[i]}
	}
	close(ch3)

	require.NoError(t, writer.Run(ctx, ch3))

	var count3 int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google").Scan(&count3))
	assert.Equal(t, 5, count3, "Count must be 5 after Test 3")

	// --- TEST 4: 20 LEADS ---
	ch4 := make(chan scrapemate.Result, 15)
	for i := 5; i < 20; i++ {
		ch4 <- scrapemate.Result{Data: dataset[i]}
	}
	close(ch4)

	require.NoError(t, writer.Run(ctx, ch4))

	var count4 int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google").Scan(&count4))
	assert.Equal(t, 20, count4, "Total count must be 20 after Test 4")

	var normPhoneCount int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google WHERE whatsapp LIKE '556799000%'").Scan(&normPhoneCount))
	assert.Equal(t, 20, normPhoneCount, "All 20 phone numbers must be normalized to 55+DDD+Number")
}

func TestShadowFallbackMode(t *testing.T) {
	badDSN := "postgres://postgres:badpass@127.0.0.1:59999/prospects_db?sslmode=disable"
	t.Setenv("PROSPECT_DATABASE_URL", badDSN)

	writer := NewWriterFromEnv()
	require.NotNil(t, writer)

	ch := make(chan scrapemate.Result, 1)
	ch <- scrapemate.Result{Data: &gmaps.Entry{Title: "Test Lead Offline", Phone: "67999999999"}}
	close(ch)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	err := writer.Run(ctx, ch)
	assert.NoError(t, err, "Shadow writer in fallback mode must not fail or crash scrapemate pipeline")
}
