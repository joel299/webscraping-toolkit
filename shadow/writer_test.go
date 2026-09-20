package shadow

import (
	"os"
	"path/filepath"
	"testing"

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
