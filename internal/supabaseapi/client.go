// Package supabaseapi contains the server-side PostgREST client used by the
// application. Credentials are read only from the process environment.
package supabaseapi

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

type Client struct {
	baseURL string
	key     string
	http    *http.Client
}

func NewFromEnv() (*Client, error) {
	base := strings.TrimRight(strings.TrimSpace(os.Getenv("SUPABASE_URL")), "/")
	key := strings.TrimSpace(os.Getenv("SUPABASE_SERVICE_ROLE_KEY"))
	if base == "" || key == "" {
		return nil, errors.New("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured")
	}
	u, err := url.Parse(base)
	if err != nil || u.Scheme != "https" || u.Host == "" {
		return nil, errors.New("SUPABASE_URL must be a valid HTTPS URL")
	}
	return &Client{baseURL: base, key: key, http: &http.Client{Timeout: 30 * time.Second}}, nil
}

func (c *Client) Do(ctx context.Context, method, table, query string, body any, prefer string) ([]byte, http.Header, error) {
	if c == nil {
		return nil, nil, errors.New("Supabase client is not initialized")
	}
	target := c.baseURL + "/rest/v1/" + strings.TrimLeft(table, "/")
	if query != "" {
		target += "?" + query
	}
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return nil, nil, fmt.Errorf("encode Supabase request: %w", err)
		}
		reader = bytes.NewReader(encoded)
	}
	req, err := http.NewRequestWithContext(ctx, method, target, reader)
	if err != nil {
		return nil, nil, fmt.Errorf("build Supabase request: %w", err)
	}
	req.Header.Set("apikey", c.key)
	// New sb_secret_* API keys are not JWTs and must not be sent as a bearer
	// access token. Legacy service_role keys are JWTs and use both headers.
	if strings.HasPrefix(c.key, "eyJ") {
		req.Header.Set("Authorization", "Bearer "+c.key)
	}
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if prefer != "" {
		req.Header.Set("Prefer", prefer)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("Supabase REST request failed: %w", err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return nil, resp.Header, fmt.Errorf("read Supabase response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		// Do not include the request URL or headers: they may contain sensitive data.
		msg := strings.TrimSpace(string(data))
		if len(msg) > 500 {
			msg = msg[:500]
		}
		return data, resp.Header, fmt.Errorf("Supabase REST returned HTTP %d: %s", resp.StatusCode, msg)
	}
	return data, resp.Header, nil
}

func EscapeFilter(value string) string { return url.QueryEscape(value) }
