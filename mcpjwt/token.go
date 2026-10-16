// Package mcpjwt issues and verifies short-lived bearer tokens for the MCP API.
package mcpjwt

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/auth"
)

const (
	issuer       = "central-de-leads"
	audience     = "central-de-leads-mcp"
	maxTokenTTL  = 30 * 24 * time.Hour
	minimumBytes = 32
)

var allowedScopes = map[string]struct{}{"read": {}, "write": {}, "delete": {}}

type claims struct {
	Issuer   string   `json:"iss"`
	Subject  string   `json:"sub"`
	Audience string   `json:"aud"`
	IssuedAt int64    `json:"iat"`
	Expires  int64    `json:"exp"`
	Scopes   []string `json:"scope"`
}

// LoadSecret reads MCP_JWT_SECRET_FILE or MCP_JWT_SECRET. An absent value
// disables HTTP API authentication while the MCP endpoint remains unavailable.
func LoadSecret() ([]byte, error) {
	if path := strings.TrimSpace(os.Getenv("MCP_JWT_SECRET_FILE")); path != "" {
		data, err := os.ReadFile(path)
		if err != nil {
			return nil, fmt.Errorf("read MCP JWT secret file: %w", err)
		}
		return decodeSecret(string(data))
	}
	if value := strings.TrimSpace(os.Getenv("MCP_JWT_SECRET")); value != "" {
		return decodeSecret(value)
	}
	return nil, nil
}

func decodeSecret(value string) ([]byte, error) {
	value = strings.TrimSpace(value)
	if decoded, err := base64.RawURLEncoding.DecodeString(value); err == nil && len(decoded) >= minimumBytes {
		return decoded, nil
	}
	if len(value) < minimumBytes {
		return nil, fmt.Errorf("MCP JWT secret must contain at least %d bytes", minimumBytes)
	}
	return []byte(value), nil
}

// Generate signs a short-lived JWT. Supported scopes are read, write, delete.
func Generate(secret []byte, subject string, scopes []string, ttl time.Duration, now time.Time) (string, error) {
	if len(secret) < minimumBytes {
		return "", fmt.Errorf("MCP JWT secret must contain at least %d bytes", minimumBytes)
	}
	if strings.TrimSpace(subject) == "" {
		return "", errors.New("subject is required")
	}
	if ttl < time.Second || ttl > maxTokenTTL {
		return "", fmt.Errorf("token lifetime must be between 1 second and %s", maxTokenTTL)
	}
	cleanScopes := make([]string, 0, len(scopes))
	seen := make(map[string]struct{}, len(scopes))
	for _, scope := range scopes {
		scope = strings.TrimSpace(scope)
		if _, ok := allowedScopes[scope]; !ok {
			return "", fmt.Errorf("unsupported scope %q", scope)
		}
		if _, ok := seen[scope]; !ok {
			seen[scope] = struct{}{}
			cleanScopes = append(cleanScopes, scope)
		}
	}
	if len(cleanScopes) == 0 {
		return "", errors.New("at least one scope is required")
	}

	header, _ := json.Marshal(map[string]string{"alg": "HS256", "typ": "JWT"})
	now = now.UTC()
	payload, err := json.Marshal(claims{
		Issuer: issuer, Subject: strings.TrimSpace(subject), Audience: audience,
		IssuedAt: now.Unix(), Expires: now.Add(ttl).Unix(), Scopes: cleanScopes,
	})
	if err != nil {
		return "", fmt.Errorf("encode JWT claims: %w", err)
	}
	unsigned := base64.RawURLEncoding.EncodeToString(header) + "." + base64.RawURLEncoding.EncodeToString(payload)
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(unsigned))
	return unsigned + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil)), nil
}

// Verifier validates issuer, audience, time claims, scope names and HS256 signature.
func Verifier(secret []byte) auth.TokenVerifier {
	return func(_ context.Context, token string, _ *http.Request) (*auth.TokenInfo, error) {
		parts := strings.Split(token, ".")
		if len(parts) != 3 {
			return nil, auth.ErrInvalidToken
		}
		var header struct {
			Algorithm string `json:"alg"`
			Type      string `json:"typ"`
		}
		headerJSON, err := base64.RawURLEncoding.DecodeString(parts[0])
		if err != nil || json.Unmarshal(headerJSON, &header) != nil || header.Algorithm != "HS256" || header.Type != "JWT" {
			return nil, auth.ErrInvalidToken
		}
		provided, err := base64.RawURLEncoding.DecodeString(parts[2])
		if err != nil {
			return nil, auth.ErrInvalidToken
		}
		mac := hmac.New(sha256.New, secret)
		_, _ = mac.Write([]byte(parts[0] + "." + parts[1]))
		if !hmac.Equal(provided, mac.Sum(nil)) {
			return nil, auth.ErrInvalidToken
		}
		payloadJSON, err := base64.RawURLEncoding.DecodeString(parts[1])
		if err != nil {
			return nil, auth.ErrInvalidToken
		}
		var payload claims
		if json.Unmarshal(payloadJSON, &payload) != nil {
			return nil, auth.ErrInvalidToken
		}
		now := time.Now().Unix()
		if payload.Issuer != issuer || payload.Audience != audience || payload.Subject == "" || payload.Expires <= now || payload.IssuedAt > now+60 || payload.Expires-payload.IssuedAt > int64(maxTokenTTL.Seconds()) {
			return nil, auth.ErrInvalidToken
		}
		for _, scope := range payload.Scopes {
			if _, ok := allowedScopes[scope]; !ok {
				return nil, auth.ErrInvalidToken
			}
		}
		return &auth.TokenInfo{UserID: payload.Subject, Scopes: payload.Scopes, Expiration: time.Unix(payload.Expires, 0)}, nil
	}
}

// HasScope reports whether an authenticated MCP token grants the requested scope.
func HasScope(info *auth.TokenInfo, scope string) bool {
	if info == nil {
		return false
	}
	for _, candidate := range info.Scopes {
		if candidate == scope {
			return true
		}
	}
	return false
}
