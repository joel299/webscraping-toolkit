package starkwriter

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/gosom/google-maps-scraper/gmaps"
	"github.com/gosom/scrapemate"
	"log"
	"net/http"
	"reflect"
	"sync"
	"time"
)

type Composite struct{ writers []scrapemate.ResultWriter }

func NewComposite(writers ...scrapemate.ResultWriter) scrapemate.ResultWriter {
	return &Composite{writers: writers}
}
func (c *Composite) Run(ctx context.Context, in <-chan scrapemate.Result) error {
	chs := make([]chan scrapemate.Result, len(c.writers))
	errs := make(chan error, len(c.writers))
	var wg sync.WaitGroup
	for i, w := range c.writers {
		chs[i] = make(chan scrapemate.Result)
		wg.Add(1)
		go func(w scrapemate.ResultWriter, ch <-chan scrapemate.Result) {
			defer wg.Done()
			if err := w.Run(ctx, ch); err != nil && err != context.Canceled {
				errs <- err
			}
		}(w, chs[i])
	}
	for {
		select {
		case <-ctx.Done():
			for _, ch := range chs {
				close(ch)
			}
			wg.Wait()
			return ctx.Err()
		case r, ok := <-in:
			if !ok {
				for _, ch := range chs {
					close(ch)
				}
				wg.Wait()
				select {
				case e := <-errs:
					return e
				default:
					return nil
				}
			}
			for _, ch := range chs {
				select {
				case ch <- r:
				case <-ctx.Done():
					for _, x := range chs {
						close(x)
					}
					wg.Wait()
					return ctx.Err()
				}
			}
		}
	}
}

type Writer struct {
	endpoint, jobID string
	client          *http.Client
}

func New(endpoint, jobID string) *Writer {
	return &Writer{endpoint: endpoint, jobID: jobID, client: &http.Client{Timeout: 10 * time.Second}}
}
func (w *Writer) Run(ctx context.Context, in <-chan scrapemate.Result) error {
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case r, ok := <-in:
			if !ok {
				return nil
			}
			v := reflect.ValueOf(r.Data)
			if v.IsValid() && v.Kind() == reflect.Slice {
				for i := 0; i < v.Len(); i++ {
					w.accept(r, v.Index(i).Interface())
				}
			} else {
				w.accept(r, r.Data)
			}
		}
	}
}
func (w *Writer) accept(r scrapemate.Result, value any) {
	e, ok := value.(*gmaps.Entry)
	if !ok {
		if c, yes := value.(scrapemate.CsvCapable); yes {
			b, err := json.Marshal(c)
			if err == nil {
				var x gmaps.Entry
				if json.Unmarshal(b, &x) == nil {
					e = &x
					ok = true
				}
			}
		}
	}
	if ok {
		w.enqueue(r.Job, e)
	}
}
func (w *Writer) enqueue(job scrapemate.IJob, e *gmaps.Entry) {
	pid := w.jobID
	if job != nil && job.GetID() != "" {
		pid = job.GetID()
	}
	body, _ := json.Marshal(map[string]any{"provider_job_id": pid, "entry": e, "emitted_at": time.Now().UTC().Format(time.RFC3339Nano)})
	go w.deliver(body)
}
func (w *Writer) deliver(body []byte) {
	for i := 0; i < 3; i++ {
		req, _ := http.NewRequest(http.MethodPost, w.endpoint, bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		r, err := w.client.Do(req)
		if err == nil {
			r.Body.Close()
			if r.StatusCode >= 200 && r.StatusCode < 300 {
				return
			}
			log.Printf("starkwriter sink status=%d", r.StatusCode)
		} else {
			log.Printf("starkwriter sink error=%v", err)
		}
		time.Sleep(time.Duration(i+1) * 250 * time.Millisecond)
	}
}
func (w *Writer) String() string { return fmt.Sprintf("starkwriter:%s", w.jobID) }
