package mcpjwt

import (
	"errors"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/auth"
)

func TestGenerateAndVerifyToken(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	now := time.Now().UTC()
	token, err := Generate(secret, "agent-1", []string{"read", "write", "read"}, time.Hour, now)
	if err != nil {
		t.Fatal(err)
	}
	info, err := Verifier(secret)(t.Context(), token, httptest.NewRequest("GET", "/mcp", nil))
	if err != nil {
		t.Fatalf("verify: %v", err)
	}
	if info.UserID != "agent-1" || !HasScope(info, "read") || !HasScope(info, "write") || HasScope(info, "delete") {
		t.Fatalf("unexpected token info: %#v", info)
	}
}

func TestVerifierRejectsTamperedAndExpiredTokens(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	now := time.Now().UTC()
	token, err := Generate(secret, "agent-1", []string{"read"}, time.Hour, now.Add(-2*time.Hour))
	if err != nil {
		t.Fatal(err)
	}
	verify := Verifier(secret)
	if _, err := verify(t.Context(), token, httptest.NewRequest("GET", "/mcp", nil)); err == nil {
		t.Fatal("expired token was accepted")
	}

	token, err = Generate(secret, "agent-1", []string{"read"}, time.Hour, now)
	if err != nil {
		t.Fatal(err)
	}
	replacement := "A"
	if token[len(token)-1] == 'A' {
		replacement = "B"
	}
	tampered := token[:len(token)-1] + replacement
	if _, err := verify(t.Context(), tampered, httptest.NewRequest("GET", "/mcp", nil)); err == nil || !errors.Is(err, auth.ErrInvalidToken) {
		t.Fatalf("tampered token should be rejected as invalid, got %v", err)
	}
}

func TestGenerateValidatesScopesAndLifetime(t *testing.T) {
	secret := []byte(strings.Repeat("s", 32))
	if _, err := Generate(secret, "agent-1", []string{"admin"}, time.Hour, time.Now()); err == nil {
		t.Fatal("unknown scope was accepted")
	}
	if _, err := Generate(secret, "agent-1", []string{"read"}, maxTokenTTL+time.Second, time.Now()); err == nil {
		t.Fatal("lifetime longer than 30 days was accepted")
	}
	if _, err := Generate(secret, "agent-1", []string{"read"}, time.Millisecond, time.Now()); err == nil {
		t.Fatal("lifetime shorter than one second was accepted")
	}
}
