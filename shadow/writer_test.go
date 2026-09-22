package shadow

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/gosom/google-maps-scraper/gmaps"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNormalizePhoneBR(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected string
	}{
		{
			name:     "Formatted BR mobile with country code",
			input:    "+55 (67) 99999-9999",
			expected: "5567999999999",
		},
		{
			name:     "Formatted BR mobile without country code",
			input:    "(67) 99999-9999",
			expected: "5567999999999",
		},
		{
			name:     "BR mobile with leading zero",
			input:    "067 99999-9999",
			expected: "5567999999999",
		},
		{
			name:     "BR landline without country code",
			input:    "(67) 3321-1234",
			expected: "556733211234",
		},
		{
			name:     "Already normalized",
			input:    "5567999999999",
			expected: "5567999999999",
		},
		{
			name:     "Empty input",
			input:    "",
			expected: "",
		},
		{
			name:     "Invalid phone text",
			input:    "No Phone",
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := NormalizePhoneBR(tt.input)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestSanitizeDSN(t *testing.T) {
	rawDSN := "postgres://postgres.user:SecretPassword123!@aws-0-sa-east-1.pooler.supabase.com:6543/postgres"
	sanitized := SanitizeDSN(rawDSN)
	assert.NotContains(t, sanitized, "SecretPassword123!")
	assert.Contains(t, sanitized, "*****@aws-0-sa-east-1.pooler.supabase.com:6543/postgres")
}

func TestProvenanceErrorClass(t *testing.T) {
	t.Run("context canceled", func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		assert.Equal(t, "context_canceled", ProvenanceErrorClass(ctx.Err()))
	})

	t.Run("deadline exceeded", func(t *testing.T) {
		ctx, cancel := context.WithDeadline(context.Background(), time.Unix(0, 0))
		defer cancel()
		assert.Equal(t, "context_deadline_exceeded", ProvenanceErrorClass(ctx.Err()))
	})

	t.Run("postgres error is classified without message", func(t *testing.T) {
		err := &pgconn.PgError{Code: "23503", Message: "sensitive database detail"}
		classified := ProvenanceErrorClass(err)
		assert.Equal(t, "postgres_23503", classified)
		assert.NotContains(t, classified, "sensitive database detail")
	})
}

func TestRetryableDatabaseReadError(t *testing.T) {
	assert.True(t, retryableDatabaseReadError(&pgconn.PgError{Code: "08006"}))
	assert.True(t, retryableDatabaseReadError(&pgconn.PgError{Code: "57P01"}))
	assert.False(t, retryableDatabaseReadError(&pgconn.PgError{Code: "42703"}))
	assert.False(t, retryableDatabaseReadError(context.Canceled))
	assert.False(t, retryableDatabaseReadError(context.DeadlineExceeded))
}

func TestLoadDSN(t *testing.T) {
	tmpDir := t.TempDir()
	secretFile := filepath.Join(tmpDir, "prospect_database_url")
	expectedDSN := "postgres://user:pass@localhost:5432/testdb"

	err := os.WriteFile(secretFile, []byte(expectedDSN+"\n"), 0600)
	require.NoError(t, err)

	t.Setenv("PROSPECT_DATABASE_URL_FILE", secretFile)
	dsn := LoadDSN()
	assert.Equal(t, expectedDSN, dsn)
}

func TestNewDisabledWriter(t *testing.T) {
	w := NewDisabledWriter()
	require.NotNil(t, w)
	assert.True(t, w.disabled)
}

func TestWriterCloseIsIdempotentAndRejectsUse(t *testing.T) {
	w := NewWriter(nil, time.Second, 1)

	assert.NoError(t, w.Close())
	assert.NoError(t, w.Close())

	_, err := w.FindCompletedSearch(context.Background(), "query", "location")
	assert.ErrorIs(t, err, ErrWriterClosed)
	assert.ErrorIs(t, w.Run(context.Background(), nil), ErrWriterClosed)
}

func TestProspectLeadMapperAndValidator(t *testing.T) {
	mapper := NewProspectLeadMapper()
	validator := NewProspectLeadValidator()

	t.Run("Valid gmaps Entry with DataID", func(t *testing.T) {
		entry := &gmaps.Entry{
			Title:   "Padaria Central",
			DataID:  "data-12345",
			Phone:   "(67) 99999-1111",
			Address: "Rua Principial, 100",
		}

		lead := mapper.MapToProspectLead(entry, "job-1", "Search Job")
		require.NotNil(t, lead)
		assert.Equal(t, "data-12345", lead.PlaceID)
		assert.Equal(t, "5567999991111", lead.Whatsapp)
		assert.Equal(t, "job-1", lead.JobID)

		err := validator.Validate(lead)
		assert.NoError(t, err)
	})

	t.Run("Fallback to CID when DataID is empty", func(t *testing.T) {
		entry := &gmaps.Entry{
			Title: "Oficina Mecanica",
			Cid:   "cid-998877",
		}

		lead := mapper.MapToProspectLead(entry, "", "")
		require.NotNil(t, lead)
		assert.Equal(t, "cid-cid-998877", lead.PlaceID)

		err := validator.Validate(lead)
		assert.NoError(t, err)
	})

	t.Run("Validator rejects empty place_name", func(t *testing.T) {
		lead := &ProspectLead{
			PlaceID: "place-1",
		}
		err := validator.Validate(lead)
		assert.ErrorIs(t, err, ErrMissingPlaceName)
	})
}

func TestGoogleMapsLinkFallback(t *testing.T) {
	mapper := NewProspectLeadMapper()

	t.Run("Step 1: Direct Link present", func(t *testing.T) {
		entry := &gmaps.Entry{
			Title: "Test Place 1",
			Link:  "https://maps.google.com/?cid=112233",
		}
		lead := mapper.MapToProspectLead(entry, "", "")
		assert.Equal(t, "https://maps.google.com/?cid=112233", lead.GoogleMapsLink)
	})

	t.Run("Step 2: Fallback to PlaceID query", func(t *testing.T) {
		entry := &gmaps.Entry{
			Title:   "Test Place 2",
			PlaceID: "ChIJN1t_tDeuEmsRUsoyG83frY4",
		}
		lead := mapper.MapToProspectLead(entry, "", "")
		assert.Equal(t, "https://www.google.com/maps/search/?api=1&query_place_id=ChIJN1t_tDeuEmsRUsoyG83frY4", lead.GoogleMapsLink)
	})

	t.Run("Step 3: Fallback to CID URL", func(t *testing.T) {
		entry := &gmaps.Entry{
			Title: "Test Place 3",
			Cid:   "1234567890",
		}
		lead := mapper.MapToProspectLead(entry, "", "")
		assert.Equal(t, "https://www.google.com/maps?cid=1234567890", lead.GoogleMapsLink)
	})

	t.Run("Step 4: All missing returns empty without error", func(t *testing.T) {
		entry := &gmaps.Entry{
			Title: "Test Place 4",
		}
		lead := mapper.MapToProspectLead(entry, "", "")
		assert.Equal(t, "", lead.GoogleMapsLink)
	})
}
