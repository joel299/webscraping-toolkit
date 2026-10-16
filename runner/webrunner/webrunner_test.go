//nolint:testpackage // This test needs unexported hooks to avoid running a browser.
package webrunner

import (
	"context"
	"io"
	"sync"
	"testing"
	"time"

	"github.com/gosom/google-maps-scraper/runner"
	"github.com/gosom/google-maps-scraper/web"
	"github.com/gosom/scrapemate"
	"github.com/stretchr/testify/require"
)

func TestFanoutResultWriterDeliversEveryResultToEveryWriter(t *testing.T) {
	first := &recordingResultWriter{}
	second := &recordingResultWriter{}
	writer := fanoutResultWriter{writers: []scrapemate.ResultWriter{first, second}}
	input := make(chan scrapemate.Result, 3)
	for i := range 3 {
		input <- scrapemate.Result{Data: i}
	}
	close(input)

	if err := writer.Run(context.Background(), input); err != nil {
		t.Fatalf("fanout Run: %v", err)
	}

	if got := first.count(); got != 3 {
		t.Fatalf("first writer received %d results, want 3", got)
	}
	if got := second.count(); got != 3 {
		t.Fatalf("second writer received %d results, want 3", got)
	}
}

func TestFanoutResultWriterDrainsAfterContextCancellation(t *testing.T) {
	first := &recordingResultWriter{}
	second := &recordingResultWriter{}
	writer := fanoutResultWriter{writers: []scrapemate.ResultWriter{first, second}}
	ctx, cancel := context.WithCancel(context.Background())
	input := make(chan scrapemate.Result, 3)
	input <- scrapemate.Result{Data: 1}
	cancel()
	input <- scrapemate.Result{Data: 2}
	input <- scrapemate.Result{Data: 3}
	close(input)

	if err := writer.Run(ctx, input); err != nil {
		t.Fatalf("fanout Run after cancellation: %v", err)
	}

	if got := first.count(); got != 3 {
		t.Fatalf("first writer received %d results, want 3", got)
	}
	if got := second.count(); got != 3 {
		t.Fatalf("second writer received %d results, want 3", got)
	}
}

type recordingResultWriter struct {
	mu      sync.Mutex
	results []scrapemate.Result
}

func (w *recordingResultWriter) Run(_ context.Context, in <-chan scrapemate.Result) error {
	for result := range in {
		w.mu.Lock()
		w.results = append(w.results, result)
		w.mu.Unlock()
	}
	return nil
}

func (w *recordingResultWriter) count() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return len(w.results)
}

func TestNewWebRunnerRequiresSupabaseConfiguration(t *testing.T) {
	t.Setenv("SUPABASE_URL", "")
	t.Setenv("SUPABASE_SERVICE_ROLE_KEY", "")

	_, err := New(&runner.Config{DataFolder: t.TempDir(), Addr: "127.0.0.1:0"})
	require.ErrorContains(t, err, "Supabase is required for active job/lead persistence")
}

func TestScrapeJobMarksOKBeforeClosingMate(t *testing.T) {
	t.Parallel()

	repo := &memoryJobRepo{}
	svc := web.NewService(repo, t.TempDir())
	job := web.Job{
		ID:     "job-1",
		Name:   "coffee",
		Date:   time.Now().UTC(),
		Status: web.StatusPending,
		Data: web.JobData{
			Keywords: []string{"coffee"},
			Lang:     "en",
			Zoom:     15,
			Lat:      "37.7749",
			Lon:      "-122.4194",
			FastMode: true,
			Radius:   1000,
			Depth:    10,
			MaxTime:  time.Minute,
		},
	}

	if err := svc.Create(context.Background(), &job); err != nil {
		t.Fatalf("create job: %v", err)
	}

	w := &webrunner{
		svc: svc,
		cfg: &runner.Config{DataFolder: t.TempDir(), Concurrency: 1},
		setupMate: func(_ context.Context, output io.Writer, _ *web.Job) (mateRunner, error) {
			if _, err := io.WriteString(output, "csv result"); err != nil {
				t.Fatalf("write fixture result: %v", err)
			}

			return fakeMate{
				onClose: func() {
					got, err := svc.Get(context.Background(), job.ID)
					if err != nil {
						t.Fatalf("get job during close: %v", err)
					}

					if got.Status != web.StatusOK {
						t.Fatalf("status during close = %q, want %q", got.Status, web.StatusOK)
					}
				},
			}, nil
		},
	}

	if err := w.scrapeJob(context.Background(), &job); err != nil {
		t.Fatalf("scrape job: %v", err)
	}
}

func TestScrapeJobMarksEmptyOutputFailed(t *testing.T) {
	t.Parallel()

	repo := &memoryJobRepo{}
	svc := web.NewService(repo, t.TempDir())
	job := web.Job{
		ID:     "empty-job",
		Name:   "coffee",
		Date:   time.Now().UTC(),
		Status: web.StatusPending,
		Data: web.JobData{
			Keywords: []string{"coffee"},
			Lang:     "en",
			Zoom:     15,
			FastMode: true,
			Lat:      "37.7749",
			Lon:      "-122.4194",
			Radius:   1000,
			Depth:    10,
			MaxTime:  time.Minute,
		},
	}
	if err := svc.Create(context.Background(), &job); err != nil {
		t.Fatalf("create job: %v", err)
	}

	w := &webrunner{
		svc: svc,
		cfg: &runner.Config{DataFolder: t.TempDir(), Concurrency: 1},
		setupMate: func(context.Context, io.Writer, *web.Job) (mateRunner, error) {
			return fakeMate{}, nil
		},
	}

	if err := w.scrapeJob(context.Background(), &job); err == nil {
		t.Fatal("scrapeJob() succeeded with empty output")
	}
	if job.Status != web.StatusFailed {
		t.Fatalf("job status = %q, want %q", job.Status, web.StatusFailed)
	}
}

type fakeMate struct {
	onClose func()
}

func (m fakeMate) Start(context.Context, ...scrapemate.IJob) error {
	return nil
}

func (m fakeMate) Close() error {
	if m.onClose != nil {
		m.onClose()
	}

	return nil
}

type memoryJobRepo struct {
	jobs map[string]web.Job
}

func (r *memoryJobRepo) Get(_ context.Context, id string) (web.Job, error) {
	return r.jobs[id], nil
}

func (r *memoryJobRepo) Create(_ context.Context, job *web.Job) error {
	if r.jobs == nil {
		r.jobs = make(map[string]web.Job)
	}

	r.jobs[job.ID] = *job

	return nil
}

func (r *memoryJobRepo) Delete(_ context.Context, id string) error {
	delete(r.jobs, id)
	return nil
}

func (r *memoryJobRepo) Select(_ context.Context, params web.SelectParams) ([]web.Job, error) {
	var jobs []web.Job

	for id := range r.jobs {
		job := r.jobs[id]

		if params.Status == "" || job.Status == params.Status {
			jobs = append(jobs, job)
		}
	}

	// Sort by created_at DESC (Date)
	for i := 0; i < len(jobs); i++ {
		for j := i + 1; j < len(jobs); j++ {
			if jobs[i].Date.Before(jobs[j].Date) || (jobs[i].Date.Equal(jobs[j].Date) && jobs[i].ID < jobs[j].ID) {
				jobs[i], jobs[j] = jobs[j], jobs[i]
			}
		}
	}

	if params.Offset > 0 {
		if params.Offset > len(jobs) {
			jobs = nil
		} else {
			jobs = jobs[params.Offset:]
		}
	}

	if params.Limit > 0 && len(jobs) > params.Limit {
		jobs = jobs[:params.Limit]
	}

	return jobs, nil
}

func (r *memoryJobRepo) Count(_ context.Context, params web.SelectParams) (int, error) {
	count := 0

	for id := range r.jobs {
		job := r.jobs[id]
		if params.Status == "" || job.Status == params.Status {
			count++
		}
	}

	return count, nil
}

func (r *memoryJobRepo) Update(_ context.Context, job *web.Job) error {
	r.jobs[job.ID] = *job
	return nil
}
