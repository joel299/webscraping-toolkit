package web

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gosom/google-maps-scraper/mcpjwt"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type tokenRoundTripper struct {
	base  http.RoundTripper
	token string
}

type tailscaleHostRoundTripper struct{ token string }

func (r tailscaleHostRoundTripper) RoundTrip(request *http.Request) (*http.Response, error) {
	cloned := request.Clone(request.Context())
	cloned.Header = request.Header.Clone()
	cloned.Header.Set("Authorization", "Bearer "+r.token)
	cloned.Header.Set("Tailscale-User-Login", "stark@example.test")
	cloned.Host = "joel.tailnet.example"
	return http.DefaultTransport.RoundTrip(cloned)
}

func (r tokenRoundTripper) RoundTrip(request *http.Request) (*http.Response, error) {
	cloned := request.Clone(request.Context())
	cloned.Header = request.Header.Clone()
	cloned.Header.Set("Authorization", "Bearer "+r.token)
	return r.base.RoundTrip(cloned)
}

func TestMCPExposesAndExecutesEveryAPIOperation(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "current")
	secret := []byte(strings.Repeat("m", 32))
	existingID := "11111111-1111-4111-8111-111111111111"
	existing := Job{ID: existingID, Name: "existing", Date: time.Now().UTC(), Status: StatusOK, Data: JobData{}}
	repo := &mutableJobRepo{mockJobRepo: mockJobRepo{jobs: []Job{existing}}}
	srv := newTestServerWithRepo(t, repo)
	csv := "place_id,title,address,latitude,longitude,link,category,phone,website,review_rating,review_count\nplace-1,Test Pharmacy,Main St,1.5,2.5,https://maps.example/place,Pharmacy,123,https://example.test,4.7,12\n"
	if err := os.WriteFile(filepath.Join(srv.svc.dataFolder, existingID+".csv"), []byte(csv), 0o600); err != nil {
		t.Fatal(err)
	}

	server := httptest.NewServer(newMCPHandler(srv.svc, secret))
	t.Cleanup(server.Close)
	token, err := mcpjwt.Generate(secret, "test-agent", []string{"read", "write", "delete"}, time.Hour, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	client := mcp.NewClient(&mcp.Implementation{Name: "test-client", Version: "1.0.0"}, nil)
	httpClient := &http.Client{Transport: tokenRoundTripper{base: http.DefaultTransport, token: token}}
	session, err := client.Connect(t.Context(), &mcp.StreamableClientTransport{Endpoint: server.URL, HTTPClient: httpClient, DisableStandaloneSSE: true}, nil)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	t.Cleanup(func() { _ = session.Close() })

	listed, err := session.ListTools(t.Context(), nil)
	if err != nil {
		t.Fatalf("list tools: %v", err)
	}
	want := map[string]bool{"create_job": false, "list_jobs": false, "list_leads": false, "get_job": false, "delete_job": false, "download_job_csv": false}
	for _, tool := range listed.Tools {
		if _, ok := want[tool.Name]; ok {
			want[tool.Name] = true
		}
	}
	for name, found := range want {
		if !found {
			t.Errorf("MCP tool %q is missing", name)
		}
	}
	if len(listed.Tools) != len(want) {
		t.Fatalf("expected exactly %d tools, got %d", len(want), len(listed.Tools))
	}

	call := func(name string, args any) *mcp.CallToolResult {
		t.Helper()
		result, callErr := session.CallTool(t.Context(), &mcp.CallToolParams{Name: name, Arguments: args})
		if callErr != nil {
			t.Fatalf("call %s: %v", name, callErr)
		}
		return result
	}
	if result := call("list_jobs", map[string]any{}); result.IsError {
		t.Fatalf("list_jobs: %s", result.Content)
	}
	leads := call("list_leads", map[string]any{"limit": 10, "offset": 0})
	if leads.IsError || !strings.Contains(fmt.Sprint(leads.StructuredContent), "Test Pharmacy") {
		t.Fatalf("list_leads did not return seeded result: %#v", leads)
	}
	download := call("download_job_csv", map[string]any{"id": existingID})
	if download.IsError || !strings.Contains(fmt.Sprint(download.StructuredContent), "Test Pharmacy") {
		t.Fatalf("download_job_csv did not return CSV: %#v", download)
	}
	if get := call("get_job", map[string]any{"id": existingID}); get.IsError {
		t.Fatalf("get_job: %s", get.Content)
	}

	created := call("create_job", map[string]any{
		"confirm": true, "name": "MCP integration", "keywords": []string{"pharmacy in Campo Grande"},
		"lang": "pt", "depth": 1, "max_time": 60,
	})
	if created.IsError {
		t.Fatalf("create_job: %s", created.Content)
	}
	var createdPayload struct {
		ID string `json:"id"`
	}
	encoded, err := json.Marshal(created.StructuredContent)
	if err != nil || json.Unmarshal(encoded, &createdPayload) != nil || createdPayload.ID == "" {
		t.Fatalf("create_job returned no id: %#v", created.StructuredContent)
	}

	deleted := call("delete_job", map[string]any{"id": createdPayload.ID, "confirm": true})
	if deleted.IsError {
		t.Fatalf("delete_job: %s", deleted.Content)
	}
	if missing := call("get_job", map[string]any{"id": createdPayload.ID}); !missing.IsError {
		t.Fatal("get_job returned a job after it was deleted")
	}
}

func TestMCPRequiresBearerJWTAndScopes(t *testing.T) {
	secret := []byte(strings.Repeat("m", 32))
	server := httptest.NewServer(newMCPHandler(NewService(&mockJobRepo{}, t.TempDir()), secret))
	t.Cleanup(server.Close)
	request, err := http.NewRequestWithContext(t.Context(), http.MethodPost, server.URL, strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}`))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	_ = response.Body.Close()
	if response.StatusCode != http.StatusUnauthorized {
		t.Fatalf("unauthenticated MCP request status = %d, want 401", response.StatusCode)
	}

	readToken, err := mcpjwt.Generate(secret, "reader", []string{"read"}, time.Hour, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	client := mcp.NewClient(&mcp.Implementation{Name: "test-client", Version: "1.0.0"}, nil)
	session, err := client.Connect(t.Context(), &mcp.StreamableClientTransport{
		Endpoint:             server.URL,
		HTTPClient:           &http.Client{Transport: tokenRoundTripper{base: http.DefaultTransport, token: readToken}},
		DisableStandaloneSSE: true,
	}, nil)
	if err != nil {
		t.Fatalf("reader connect: %v", err)
	}
	defer session.Close()
	result, err := session.CallTool(t.Context(), &mcp.CallToolParams{Name: "create_job", Arguments: map[string]any{
		"confirm": true, "name": "Denied", "keywords": []string{"pharmacy"}, "lang": "pt", "depth": 1, "max_time": 60,
	}})
	if err != nil {
		t.Fatal(err)
	}
	if !result.IsError {
		t.Fatal("read-only token was allowed to create a job")
	}
}

func TestMCPAcceptsTailscaleServeHostWithIdentityHeader(t *testing.T) {
	secret := []byte(strings.Repeat("m", 32))
	server := httptest.NewServer(newMCPHandler(NewService(&mockJobRepo{}, t.TempDir()), secret))
	t.Cleanup(server.Close)
	token, err := mcpjwt.Generate(secret, "tailnet-agent", []string{"read"}, time.Hour, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	client := mcp.NewClient(&mcp.Implementation{Name: "tailnet-test", Version: "1"}, nil)
	session, err := client.Connect(t.Context(), &mcp.StreamableClientTransport{
		Endpoint: server.URL, HTTPClient: &http.Client{Transport: tailscaleHostRoundTripper{token: token}}, DisableStandaloneSSE: true,
	}, nil)
	if err != nil {
		t.Fatalf("connect through Tailscale Serve host: %v", err)
	}
	defer session.Close()
	tools, err := session.ListTools(t.Context(), nil)
	if err != nil || len(tools.Tools) != 6 {
		t.Fatalf("list tools through Tailscale Serve host: tools=%d err=%v", len(tools.Tools), err)
	}
}

func TestRESTAPIRequiresJWTWhenConfigured(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "current")
	secret := strings.Repeat("x", 32)
	t.Setenv("MCP_JWT_SECRET", secret)
	srv, err := New(NewService(&mockJobRepo{}, t.TempDir()), ":0")
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodGet, "/api/v1/jobs", http.NoBody)
	recorder := httptest.NewRecorder()
	srv.Handler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("no-token REST status = %d, want 401", recorder.Code)
	}
	token, err := mcpjwt.Generate([]byte(secret), "rest-reader", []string{"read"}, time.Hour, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	request = httptest.NewRequest(http.MethodGet, "/api/v1/jobs", http.NoBody)
	request.Header.Set("Authorization", "Bearer "+token)
	recorder = httptest.NewRecorder()
	srv.Handler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("valid-token REST status = %d, want 200: %s", recorder.Code, recorder.Body.String())
	}
	request = httptest.NewRequest(http.MethodPost, "/api/v1/jobs", strings.NewReader(`{}`))
	request.Header.Set("Authorization", "Bearer "+token)
	recorder = httptest.NewRecorder()
	srv.Handler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusForbidden {
		t.Fatalf("read-only REST write status = %d, want 403", recorder.Code)
	}
}

func TestOpenAPIDocumentsMCPRoute(t *testing.T) {
	server := newTestServerWithRepo(t, &mockJobRepo{})
	request := httptest.NewRequest(http.MethodGet, "/static/spec/spec.yaml", http.NoBody)
	recorder := httptest.NewRecorder()
	server.Handler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("OpenAPI spec status = %d, want 200", recorder.Code)
	}
	for _, expected := range []string{"  /mcp:", "MCP Streamable HTTP endpoint", "tools/list", "tools/call", "BearerAuth", "Mcp-Session-Id", "/api/v1/tokens:", "token:issue", "CreateTokenResponse"} {
		if !strings.Contains(recorder.Body.String(), expected) {
			t.Errorf("OpenAPI spec does not document %q", expected)
		}
	}
}

func TestTokenIssuanceRequiresAdminScopeAndReturnsScopedToken(t *testing.T) {
	secret := strings.Repeat("z", 32)
	t.Setenv("MCP_JWT_SECRET_FILE", "")
	t.Setenv("MCP_JWT_SECRET", secret)
	t.Setenv("PROSPECT_READ_MODE", "current")
	srv, err := New(NewService(&mockJobRepo{}, t.TempDir()), ":0")
	if err != nil {
		t.Fatal(err)
	}
	issueToken := func(scopes []string) string {
		t.Helper()
		value, generateErr := mcpjwt.Generate([]byte(secret), "issuer", scopes, time.Hour, time.Now())
		if generateErr != nil {
			t.Fatal(generateErr)
		}
		return value
	}
	request := httptest.NewRequest(http.MethodPost, "/api/v1/tokens", strings.NewReader(`{"subject":"stark-agent","scopes":["read"],"ttl":"1h"}`))
	request.Header.Set("Authorization", "Bearer "+issueToken([]string{"read"}))
	recorder := httptest.NewRecorder()
	srv.Handler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusForbidden {
		t.Fatalf("reader token issuance status = %d, want 403", recorder.Code)
	}

	request = httptest.NewRequest(http.MethodPost, "/api/v1/tokens", strings.NewReader(`{"subject":"stark-agent","scopes":["read"],"ttl":"1h"}`))
	request.Header.Set("Authorization", "Bearer "+issueToken([]string{"token:issue"}))
	recorder = httptest.NewRecorder()
	srv.Handler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusCreated {
		t.Fatalf("admin token issuance status = %d, want 201: %s", recorder.Code, recorder.Body.String())
	}
	var result createTokenResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &result); err != nil || result.AccessToken == "" {
		t.Fatalf("token endpoint returned invalid response: %v", err)
	}

	request = httptest.NewRequest(http.MethodPost, "/api/v1/jobs", strings.NewReader(`{}`))
	request.Header.Set("Authorization", "Bearer "+result.AccessToken)
	recorder = httptest.NewRecorder()
	srv.Handler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusForbidden {
		t.Fatalf("read-only issued token write status = %d, want 403", recorder.Code)
	}
}
