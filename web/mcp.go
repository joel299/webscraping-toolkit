package web

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/gosom/google-maps-scraper/mcpjwt"
	"github.com/modelcontextprotocol/go-sdk/auth"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type mcpJob struct {
	ID     string     `json:"id"`
	Name   string     `json:"name"`
	Date   time.Time  `json:"date"`
	Status string     `json:"status"`
	Data   mcpJobData `json:"data"`
}

type mcpJobData struct {
	Keywords     []string `json:"keywords"`
	Lang         string   `json:"lang"`
	Zoom         int      `json:"zoom"`
	Lat          string   `json:"lat"`
	Lon          string   `json:"lon"`
	FastMode     bool     `json:"fast_mode"`
	Radius       int      `json:"radius"`
	Depth        int      `json:"depth"`
	Email        bool     `json:"email"`
	ExtraReviews bool     `json:"extra_reviews"`
	MaxTime      int64    `json:"max_time"`
	Proxies      []string `json:"proxies,omitempty"`
}

type listJobsToolOutput struct {
	Jobs []mcpJob `json:"jobs"`
}

type createJobToolInput struct {
	Confirm      bool     `json:"confirm" jsonschema:"Set true to confirm that this search should start"`
	Name         string   `json:"name" jsonschema:"Search name shown in the dashboard"`
	Keywords     []string `json:"keywords" jsonschema:"Search terms to run on Google Maps"`
	Lang         string   `json:"lang" jsonschema:"Two-letter language code, for example pt"`
	Zoom         int      `json:"zoom,omitempty"`
	Lat          string   `json:"lat,omitempty"`
	Lon          string   `json:"lon,omitempty"`
	FastMode     bool     `json:"fast_mode,omitempty"`
	Radius       int      `json:"radius,omitempty"`
	Depth        int      `json:"depth" jsonschema:"Maximum number of pages per search"`
	Email        bool     `json:"email,omitempty"`
	ExtraReviews bool     `json:"extra_reviews,omitempty"`
	MaxTime      int      `json:"max_time" jsonschema:"Maximum run time in seconds"`
	Proxies      []string `json:"proxies,omitempty"`
}

type createJobToolOutput struct {
	ID string `json:"id"`
}

type listLeadsToolInput struct {
	Limit  int `json:"limit,omitempty" jsonschema:"Maximum number of results, 1 to 500; defaults to 100"`
	Offset int `json:"offset,omitempty" jsonschema:"Number of results to skip"`
}

type getJobToolInput struct {
	ID string `json:"id" jsonschema:"UUID of the search job"`
}

type deleteJobToolInput struct {
	ID      string `json:"id" jsonschema:"UUID of the job to permanently delete"`
	Confirm bool   `json:"confirm" jsonschema:"Set true to confirm permanent deletion"`
}

type downloadJobToolInput struct {
	ID string `json:"id" jsonschema:"UUID of the completed job"`
}

type downloadJobToolOutput struct {
	Filename string `json:"filename"`
	CSV      string `json:"csv"`
}

func newMCPHandler(svc *Service, secret []byte) http.Handler {
	server := mcp.NewServer(&mcp.Implementation{
		Name:        "central-de-leads",
		Title:       "Central de Leads",
		Version:     "1.0.0",
		Description: "Ferramentas autenticadas para pesquisas e leads da Central de Leads.",
	}, nil)
	registerMCPTools(server, svc)
	handler := mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server { return server }, &mcp.StreamableHTTPOptions{
		JSONResponse: true,
	})
	authenticated := auth.RequireBearerToken(mcpjwt.Verifier(secret), &auth.RequireBearerTokenOptions{})(handler)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Tailscale Serve terminates HTTPS and proxies to the loopback listener,
		// so the MCP SDK's DNS-rebinding check sees a loopback local address and
		// the external MagicDNS Host. Serve strips spoofed identity headers and
		// injects this header itself; rewrite Host only for that trusted proxy.
		if strings.TrimSpace(r.Header.Get("Tailscale-User-Login")) != "" {
			proxied := r.Clone(r.Context())
			proxied.Host = "localhost"
			r = proxied
		}
		authenticated.ServeHTTP(w, r)
	})
}

func registerMCPTools(server *mcp.Server, svc *Service) {
	readOnly := &mcp.ToolAnnotations{ReadOnlyHint: true}
	write := &mcp.ToolAnnotations{ReadOnlyHint: false, DestructiveHint: boolPointer(false), Title: "Create search"}
	destructive := &mcp.ToolAnnotations{ReadOnlyHint: false, DestructiveHint: boolPointer(true), Title: "Delete search"}

	mcp.AddTool(server, &mcp.Tool{Name: "create_job", Title: "Create a Google Maps search", Description: "Starts a Google Maps scraping job. Requires the write scope. This may use scraper resources and take time.", Annotations: write}, func(ctx context.Context, _ *mcp.CallToolRequest, input createJobToolInput) (*mcp.CallToolResult, createJobToolOutput, error) {
		if err := requireMcpScope(ctx, "write"); err != nil {
			return nil, createJobToolOutput{}, err
		}
		if !input.Confirm {
			return nil, createJobToolOutput{}, errors.New("confirm must be true to start a scraping job")
		}
		job := Job{
			ID: uuid.NewString(), Name: strings.TrimSpace(input.Name), Date: time.Now().UTC(), Status: StatusPending,
			Data: JobData{
				Keywords: input.Keywords, Lang: input.Lang, Zoom: input.Zoom, Lat: input.Lat, Lon: input.Lon,
				FastMode: input.FastMode, Radius: input.Radius, Depth: input.Depth, Email: input.Email,
				ExtraReviews: input.ExtraReviews, MaxTime: time.Duration(input.MaxTime) * time.Second, Proxies: input.Proxies,
			},
		}
		if err := job.Validate(); err != nil {
			return nil, createJobToolOutput{}, err
		}
		if err := svc.Create(ctx, &job); err != nil {
			return nil, createJobToolOutput{}, fmt.Errorf("create search job: %w", err)
		}
		return nil, createJobToolOutput{ID: job.ID}, nil
	})

	mcp.AddTool(server, &mcp.Tool{Name: "list_jobs", Title: "List search jobs", Description: "Returns all saved search jobs and their status in a jobs array. Requires the read scope.", Annotations: readOnly}, func(ctx context.Context, _ *mcp.CallToolRequest, _ struct{}) (*mcp.CallToolResult, listJobsToolOutput, error) {
		if err := requireMcpScope(ctx, "read"); err != nil {
			return nil, listJobsToolOutput{}, err
		}
		jobs, err := svc.All(ctx)
		if err != nil {
			return nil, listJobsToolOutput{}, err
		}
		result := make([]mcpJob, 0, len(jobs))
		for _, job := range jobs {
			result = append(result, asMCPJob(job))
		}
		return nil, listJobsToolOutput{Jobs: result}, nil
	})

	mcp.AddTool(server, &mcp.Tool{Name: "list_leads", Title: "List consolidated leads", Description: "Returns deduplicated leads with pagination. Requires the read scope.", Annotations: readOnly}, func(ctx context.Context, _ *mcp.CallToolRequest, input listLeadsToolInput) (*mcp.CallToolResult, GlobalLeadsPage, error) {
		if err := requireMcpScope(ctx, "read"); err != nil {
			return nil, GlobalLeadsPage{}, err
		}
		limit := input.Limit
		if limit == 0 {
			limit = 100
		}
		if limit < 1 || limit > 500 || input.Offset < 0 {
			return nil, GlobalLeadsPage{}, errors.New("limit must be 1..500 and offset must be nonnegative")
		}
		page, err := svc.ListGlobalLeads(ctx, limit, input.Offset)
		return nil, page, err
	})

	mcp.AddTool(server, &mcp.Tool{Name: "get_job", Title: "Get a search job", Description: "Returns one search job by UUID. Requires the read scope.", Annotations: readOnly}, func(ctx context.Context, _ *mcp.CallToolRequest, input getJobToolInput) (*mcp.CallToolResult, mcpJob, error) {
		if err := requireMcpScope(ctx, "read"); err != nil {
			return nil, mcpJob{}, err
		}
		id, err := parseJobID(input.ID)
		if err != nil {
			return nil, mcpJob{}, err
		}
		job, err := svc.Get(ctx, id)
		if err != nil {
			return nil, mcpJob{}, err
		}
		return nil, asMCPJob(job), nil
	})

	mcp.AddTool(server, &mcp.Tool{Name: "delete_job", Title: "Delete a search job", Description: "Permanently deletes a search job and its CSV output. Requires the delete scope.", Annotations: destructive}, func(ctx context.Context, _ *mcp.CallToolRequest, input deleteJobToolInput) (*mcp.CallToolResult, map[string]bool, error) {
		if err := requireMcpScope(ctx, "delete"); err != nil {
			return nil, nil, err
		}
		if !input.Confirm {
			return nil, nil, errors.New("confirm must be true to permanently delete a search job")
		}
		id, err := parseJobID(input.ID)
		if err != nil {
			return nil, nil, err
		}
		if err := svc.Delete(ctx, id); err != nil {
			return nil, nil, err
		}
		return nil, map[string]bool{"deleted": true}, nil
	})

	mcp.AddTool(server, &mcp.Tool{Name: "download_job_csv", Title: "Download search CSV", Description: "Returns a completed job's CSV content. Requires the read scope.", Annotations: readOnly}, func(ctx context.Context, _ *mcp.CallToolRequest, input downloadJobToolInput) (*mcp.CallToolResult, downloadJobToolOutput, error) {
		if err := requireMcpScope(ctx, "read"); err != nil {
			return nil, downloadJobToolOutput{}, err
		}
		id, err := parseJobID(input.ID)
		if err != nil {
			return nil, downloadJobToolOutput{}, err
		}
		path, err := svc.GetCSV(ctx, id)
		if err != nil {
			return nil, downloadJobToolOutput{}, err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return nil, downloadJobToolOutput{}, fmt.Errorf("read search CSV: %w", err)
		}
		return nil, downloadJobToolOutput{Filename: id + ".csv", CSV: string(data)}, nil
	})
}

func asMCPJob(job Job) mcpJob {
	data := job.Data
	return mcpJob{ID: job.ID, Name: job.Name, Date: job.Date, Status: job.Status, Data: mcpJobData{
		Keywords: data.Keywords, Lang: data.Lang, Zoom: data.Zoom, Lat: data.Lat, Lon: data.Lon,
		FastMode: data.FastMode, Radius: data.Radius, Depth: data.Depth, Email: data.Email,
		ExtraReviews: data.ExtraReviews, MaxTime: int64(data.MaxTime / time.Second), Proxies: data.Proxies,
	}}
}

func parseJobID(raw string) (string, error) {
	id, err := uuid.Parse(strings.TrimSpace(raw))
	if err != nil {
		return "", errors.New("invalid job UUID")
	}
	return id.String(), nil
}

func requireMcpScope(ctx context.Context, scope string) error {
	if !mcpjwt.HasScope(auth.TokenInfoFromContext(ctx), scope) {
		return fmt.Errorf("token is missing the %q scope", scope)
	}
	return nil
}

func boolPointer(value bool) *bool { return &value }
