package shadow

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
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
	migs := []string{
		"../supabase/migrations/20260920153500_prospect_leads_google_persistence.sql",
		"../supabase/migrations/20260920161000_prospect_leads_google_rls.sql",
		"../supabase/migrations/20260920190000_prospect_searches_provenance.sql",
		"../supabase/migrations/20260920191000_prospect_searches_rls.sql",
	}

	for i, path := range migs {
		content, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("failed to read migration %d (%s): %w", i+1, path, err)
		}
		if _, err := pool.Exec(ctx, string(content)); err != nil {
			return fmt.Errorf("failed to apply migration %d (%s): %w", i+1, path, err)
		}
	}

	return nil
}

func TestIntegrationScalingProgression(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short unit test run")
	}

	testDSN := strings.TrimSpace(os.Getenv("PROSPECT_DATABASE_URL"))
	if testDSN == "" {
		testDSN = "postgres://postgres:shadowpass@127.0.0.1:5439/prospects_db?sslmode=disable"
	}

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

func TestIdentityAndDeduplicationScenarios(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short unit test run")
	}

	testDSN := strings.TrimSpace(os.Getenv("PROSPECT_DATABASE_URL"))
	if testDSN == "" {
		testDSN = "postgres://postgres:shadowpass@127.0.0.1:5439/prospects_db?sslmode=disable"
	}

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

	// 1. Clean & Migrate
	_, _ = pool.Exec(ctx, "DROP TABLE IF EXISTS public.prospect_leads_google CASCADE")
	require.NoError(t, applyMigrationFiles(ctx, pool))

	writer := NewWriter(pool, 5*time.Second, 10)

	// --- CASO A: CID Collision with different place_id ---
	leadA1 := &gmaps.Entry{
		PlaceID:  "AAA",
		Cid:      "cid-123",
		Title:    "Hamburgueria Central A",
		Category: "Hamburgueria",
		Phone:    "+55 (67) 99999-9999",
	}
	require.NoError(t, writer.UpsertLead(ctx, leadA1))

	var countA1 int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google").Scan(&countA1))
	assert.Equal(t, 1, countA1)

	// Recoleta with different place_id (BBB) but SAME CID (cid-123)
	leadA2 := &gmaps.Entry{
		PlaceID:  "BBB",
		Cid:      "cid-123",
		Title:    "Hamburgueria Central A - Enriched",
		Category: "Hamburgueria",
		Phone:    "+55 (67) 99999-9999",
	}
	require.NoError(t, writer.UpsertLead(ctx, leadA2))

	var countA2 int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google").Scan(&countA2))
	assert.Equal(t, 1, countA2, "CASO A: Row count must remain 1 after CID collision")

	var canonicalTitleA string
	require.NoError(t, pool.QueryRow(ctx, "SELECT place_name FROM public.prospect_leads_google WHERE place_id = 'AAA'").Scan(&canonicalTitleA))
	assert.Equal(t, "Hamburgueria Central A - Enriched", canonicalTitleA, "Canonical place_id AAA must be updated")

	// --- CASO B: WhatsApp Collision with empty CID & different place_id ---
	leadB1 := &gmaps.Entry{
		PlaceID:  "CCC",
		Cid:      "",
		Title:    "Hamburgueria B",
		Category: "Hamburgueria",
		Phone:    "+55 (67) 98888-8888",
	}
	require.NoError(t, writer.UpsertLead(ctx, leadB1))

	var countB1 int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google").Scan(&countB1))
	assert.Equal(t, 2, countB1)

	// Recoleta with place_id DDD, empty CID, but SAME WhatsApp (5567988888888)
	leadB2 := &gmaps.Entry{
		PlaceID:  "DDD",
		Cid:      "",
		Title:    "Hamburgueria B - Updated",
		Category: "Hamburgueria",
		Phone:    "+55 (67) 98888-8888",
	}
	require.NoError(t, writer.UpsertLead(ctx, leadB2))

	var countB2 int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google").Scan(&countB2))
	assert.Equal(t, 2, countB2, "CASO B: Row count must remain 2 after WhatsApp collision")

	var canonicalTitleB string
	require.NoError(t, pool.QueryRow(ctx, "SELECT place_name FROM public.prospect_leads_google WHERE place_id = 'CCC'").Scan(&canonicalTitleB))
	assert.Equal(t, "Hamburgueria B - Updated", canonicalTitleB, "Canonical place_id CCC must be updated")

	// --- CASO C: Exact Same PlaceID and Data -> UNCHANGED ---
	metricsBeforeC := writer.GetMetrics()
	require.NoError(t, writer.UpsertLead(ctx, leadB2)) // identical data
	metricsAfterC := writer.GetMetrics()
	assert.Equal(t, metricsBeforeC.Unchanged+1, metricsAfterC.Unchanged, "CASO C: Unchanged metric must increment")

	// --- CASO D: Same PlaceID, New Enrichment Data -> UPDATED ---
	leadB3 := *leadB2
	leadB3.PlaceID = "CCC"
	leadB3.ReviewRating = 4.8
	metricsBeforeD := writer.GetMetrics()
	require.NoError(t, writer.UpsertLead(ctx, &leadB3))
	metricsAfterD := writer.GetMetrics()
	assert.Equal(t, metricsBeforeD.Updated+1, metricsAfterD.Updated, "CASO D: Updated metric must increment")

	// --- CASO E: Empty Enrichment on Recoleta -> Preserved ---
	_, _ = pool.Exec(ctx, "UPDATE public.prospect_leads_google SET website = 'https://hamburgueriab.com' WHERE place_id = 'CCC'")

	leadB4 := leadB3
	leadB4.WebSite = "" // Empty on new scrape
	require.NoError(t, writer.UpsertLead(ctx, &leadB4))

	var preservedWebsite string
	require.NoError(t, pool.QueryRow(ctx, "SELECT website FROM public.prospect_leads_google WHERE place_id = 'CCC'").Scan(&preservedWebsite))
	assert.Equal(t, "https://hamburgueriab.com", preservedWebsite, "CASO E: Existing website must be preserved")

	// --- CASO F: SDR Commercial Fields Preserved ---
	_, err = pool.Exec(ctx, `
		UPDATE public.prospect_leads_google SET
			lead_status = 'QUALIFIED_SDR',
			pipeline_stage = 'NEGOTIATION',
			followup_count = 3,
			converted = TRUE,
			do_not_contact = TRUE,
			processing_status = 'COMPLETED'
		WHERE place_id = 'CCC'
	`)
	require.NoError(t, err)

	leadB5 := leadB3
	leadB5.ReviewCount = 150
	require.NoError(t, writer.UpsertLead(ctx, &leadB5))

	var (
		statusStr   string
		stageStr    string
		followupVal int
		convBool    bool
		dncBool     bool
		procStr     string
	)
	err = pool.QueryRow(ctx, `
		SELECT lead_status, pipeline_stage, followup_count, converted, do_not_contact, processing_status
		FROM public.prospect_leads_google WHERE place_id = 'CCC'
	`).Scan(&statusStr, &stageStr, &followupVal, &convBool, &dncBool, &procStr)

	require.NoError(t, err)
	assert.Equal(t, "QUALIFIED_SDR", statusStr, "CASO F: lead_status preserved")
	assert.Equal(t, "NEGOTIATION", stageStr, "CASO F: pipeline_stage preserved")
	assert.Equal(t, 3, followupVal, "CASO F: followup_count preserved")
	assert.True(t, convBool, "CASO F: converted preserved")
	assert.True(t, dncBool, "CASO F: do_not_contact preserved")
	assert.Equal(t, "COMPLETED", procStr, "CASO F: processing_status preserved")
}

func TestSearchToLeadProvenanceScenarios(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short unit test run")
	}

	testDSN := strings.TrimSpace(os.Getenv("PROSPECT_DATABASE_URL"))
	if testDSN == "" {
		testDSN = "postgres://postgres:shadowpass@127.0.0.1:5439/prospects_db?sslmode=disable"
	}

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

	// 1. Clean & Apply all 4 SQL migrations
	_, _ = pool.Exec(ctx, "DROP TABLE IF EXISTS public.prospect_search_leads CASCADE")
	_, _ = pool.Exec(ctx, "DROP TABLE IF EXISTS public.prospect_searches CASCADE")
	_, _ = pool.Exec(ctx, "DROP TABLE IF EXISTS public.prospect_leads_google CASCADE")
	require.NoError(t, applyMigrationFiles(ctx, pool))

	writer := NewWriter(pool, 5*time.Second, 10)

	// --- TEST A: 1 Search + 1 Lead ---
	searchA := &SearchContext{
		SearchID:       "search-001",
		JobID:          "job-001",
		JobName:        "Hamburgueria Campo Grande",
		Query:          "Hamburgueria",
		Location:       "-20.45,-54.60",
		Category:       "Hamburgueria",
		RequestedLimit: 1,
	}
	require.NoError(t, writer.RegisterSearch(ctx, searchA))

	lead1 := &gmaps.Entry{
		PlaceID:  "place-001",
		Cid:      "cid-001",
		Title:    "Hamburgueria Alpha",
		Category: "Hamburgueria",
		Phone:    "+55 (67) 99111-1111",
	}
	require.NoError(t, writer.UpsertLeadWithContext(ctx, lead1, searchA.SearchID, searchA.JobName))

	var (
		countSearchesA   int
		countLeadsA      int
		countLinksA      int
		searchStatusA    string
		searchCompletedA *time.Time
	)
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_searches").Scan(&countSearchesA))
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google").Scan(&countLeadsA))
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_search_leads WHERE search_id = 'search-001'").Scan(&countLinksA))
	require.NoError(t, pool.QueryRow(ctx, "SELECT status, completed_at FROM public.prospect_searches WHERE search_id = 'search-001'").Scan(&searchStatusA, &searchCompletedA))

	assert.Equal(t, 1, countSearchesA, "TEST A: prospect_searches count must be 1")
	assert.Equal(t, 1, countLeadsA, "TEST A: prospect_leads_google count must be 1")
	assert.Equal(t, 1, countLinksA, "TEST A: prospect_search_leads link count must be 1")
	assert.Equal(t, "running", searchStatusA, "TEST A: search status must be running before completion")

	// Complete Search A (FASE 9)
	require.NoError(t, writer.UpdateSearchStatus(ctx, searchA.SearchID, "completed", ""))
	require.NoError(t, pool.QueryRow(ctx, "SELECT status, completed_at FROM public.prospect_searches WHERE search_id = 'search-001'").Scan(&searchStatusA, &searchCompletedA))
	assert.Equal(t, "completed", searchStatusA, "TEST A: search status must be updated to completed")
	assert.NotNil(t, searchCompletedA, "TEST A: completed_at timestamp must be populated")

	// --- TEST B: 1 Search + 5 Leads ---
	searchB := &SearchContext{
		SearchID:       "search-002",
		JobID:          "job-002",
		JobName:        "Hamburgueria 5 leads",
		Query:          "Hamburgueria",
		RequestedLimit: 5,
	}
	require.NoError(t, writer.RegisterSearch(ctx, searchB))

	for i := 1; i <= 5; i++ {
		entry := &gmaps.Entry{
			PlaceID:  fmt.Sprintf("place-b-%03d", i),
			Cid:      fmt.Sprintf("cid-b-%03d", i),
			Title:    fmt.Sprintf("Empresa B %d", i),
			Category: "Hamburgueria",
			Phone:    fmt.Sprintf("+55 (67) 99222-%04d", i),
		}
		require.NoError(t, writer.UpsertLeadWithContext(ctx, entry, searchB.SearchID, searchB.JobName))
	}

	var countLinksB int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_search_leads WHERE search_id = 'search-002'").Scan(&countLinksB))
	assert.Equal(t, 5, countLinksB, "TEST B: search-002 must link exactly 5 leads in prospect_search_leads")

	// --- TEST C: 1 Search + 20 Leads ---
	searchC := &SearchContext{
		SearchID:       "search-003",
		JobID:          "job-003",
		JobName:        "Hamburgueria 20 leads",
		Query:          "Hamburgueria",
		RequestedLimit: 20,
	}
	require.NoError(t, writer.RegisterSearch(ctx, searchC))

	for i := 1; i <= 20; i++ {
		entry := &gmaps.Entry{
			PlaceID:  fmt.Sprintf("place-c-%03d", i),
			Cid:      fmt.Sprintf("cid-c-%03d", i),
			Title:    fmt.Sprintf("Empresa C %d", i),
			Category: "Hamburgueria",
			Phone:    fmt.Sprintf("+55 (67) 99333-%04d", i),
		}
		require.NoError(t, writer.UpsertLeadWithContext(ctx, entry, searchC.SearchID, searchC.JobName))
	}

	var countLinksC int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_search_leads WHERE search_id = 'search-003'").Scan(&countLinksC))
	assert.Equal(t, 20, countLinksC, "TEST C: search-003 must link exactly 20 leads in prospect_search_leads")

	// --- TEST D: Same Search + Same Lead Twice ---
	require.NoError(t, writer.UpsertLeadWithContext(ctx, lead1, searchA.SearchID, searchA.JobName))
	var countLinksADupe int
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_search_leads WHERE search_id = 'search-001' AND place_id = 'place-001'").Scan(&countLinksADupe))
	assert.Equal(t, 1, countLinksADupe, "TEST D: Duplicate lead in same search must result in exactly 1 relationship link (zero duplicate links)")

	// --- TEST E: Search A + Lead X, Search B + Lead X ---
	leadX := &gmaps.Entry{
		PlaceID:  "place-cross-X",
		Cid:      "cid-cross-X",
		Title:    "Restaurante X Shared",
		Category: "Restaurante",
		Phone:    "+55 (67) 99444-4444",
	}
	require.NoError(t, writer.UpsertLeadWithContext(ctx, leadX, searchA.SearchID, searchA.JobName))
	require.NoError(t, writer.UpsertLeadWithContext(ctx, leadX, searchB.SearchID, searchB.JobName))

	var (
		countCanonicalX int
		countLinksX     int
	)
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_leads_google WHERE place_id = 'place-cross-X'").Scan(&countCanonicalX))
	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_search_leads WHERE place_id = 'place-cross-X'").Scan(&countLinksX))

	assert.Equal(t, 1, countCanonicalX, "TEST E: Lead X must remain 1 canonical row in prospect_leads_google")
	assert.Equal(t, 2, countLinksX, "TEST E: Lead X must have 2 distinct provenance links in prospect_search_leads (search-001 and search-002)")

	// --- TEST F: SDR Commercial Fields Preserved on Cross-Search Scrape ---
	_, err = pool.Exec(ctx, `
		UPDATE public.prospect_leads_google SET
			lead_status = 'QUALIFIED_SDR',
			pipeline_stage = 'DEMO_SCHEDULED',
			converted = TRUE
		WHERE place_id = 'place-cross-X'
	`)
	require.NoError(t, err)

	// Scrape Lead X again under Search C
	leadXEnriched := *leadX
	leadXEnriched.ReviewRating = 4.9
	require.NoError(t, writer.UpsertLeadWithContext(ctx, &leadXEnriched, searchC.SearchID, searchC.JobName))

	var (
		statusX          string
		stageX           string
		convX            bool
		ratingX          float64
		countLinksXAfter int
	)
	err = pool.QueryRow(ctx, `
		SELECT lead_status, pipeline_stage, converted, review_rating
		FROM public.prospect_leads_google WHERE place_id = 'place-cross-X'
	`).Scan(&statusX, &stageX, &convX, &ratingX)
	require.NoError(t, err)

	require.NoError(t, pool.QueryRow(ctx, "SELECT COUNT(*) FROM public.prospect_search_leads WHERE place_id = 'place-cross-X'").Scan(&countLinksXAfter))

	assert.Equal(t, "QUALIFIED_SDR", statusX, "TEST F: lead_status preserved across searches")
	assert.Equal(t, "DEMO_SCHEDULED", stageX, "TEST F: pipeline_stage preserved across searches")
	assert.True(t, convX, "TEST F: converted preserved across searches")
	assert.Equal(t, 4.9, ratingX, "TEST F: review_rating enriched across searches")
	assert.Equal(t, 3, countLinksXAfter, "TEST F: Lead X now has 3 provenance links (search-001, search-002, search-003)")
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
