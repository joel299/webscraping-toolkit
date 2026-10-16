package web

import (
	"context"
	"errors"
	"strconv"
	"strings"
	"time"
)

var jobs []Job

var ErrNoJobAvailable = errors.New("no job available")

const (
	StatusPending = "pending"
	StatusWorking = "working"
	StatusOK      = "ok"
	StatusFailed  = "failed"
)

type SelectParams struct {
	Status string
	Limit  int
	Offset int
}

// JobPage contains one page of jobs and the metadata needed to navigate it.
type JobPage struct {
	Jobs        []Job
	CurrentPage int
	TotalPages  int
	Total       int
	HasPrev     bool
	HasNext     bool
	PrevPage    int
	NextPage    int
	HasPages    bool
}

type JobRepository interface {
	Get(context.Context, string) (Job, error)
	Create(context.Context, *Job) error
	Delete(context.Context, string) error
	Select(context.Context, SelectParams) ([]Job, error)
	Update(context.Context, *Job) error
}

// DatabaseReader provides the read-only database-first view of persisted
// searches. Implementations must resolve leads through search provenance.
type DatabaseReader interface {
	ListAllJobs(context.Context) ([]Job, error)
	ListJobs(context.Context, int, int) (JobPage, error)
	ListGlobalLeads(context.Context, int, int) (GlobalLeadsPage, error)
	GetJob(context.Context, string) (Job, error)
	GetPlaces(context.Context, string) ([]Place, error)
	ExportCSV(context.Context, string, string) error
}

// GlobalLeadsPage is the bounded, server-deduplicated global leads response.
type GlobalLeadsPage struct {
	Items  []Place `json:"items"`
	Total  int     `json:"total"`
	Limit  int     `json:"limit"`
	Offset int     `json:"offset"`
}

// JobClaimer atomically claims one pending job for processing.
type JobClaimer interface {
	ClaimPending(context.Context) (*Job, error)
}

type Job struct {
	ID     string
	Name   string
	Date   time.Time
	Status string
	Data   JobData
}

func (j *Job) Validate() error {
	if j.ID == "" {
		return errors.New("missing id")
	}

	if j.Name == "" {
		return errors.New("missing name")
	}

	if j.Status == "" {
		return errors.New("missing status")
	}

	if j.Date.IsZero() {
		return errors.New("missing date")
	}

	if err := j.Data.Validate(); err != nil {
		return err
	}

	return nil
}

type JobData struct {
	Keywords     []string      `json:"keywords"`
	Lang         string        `json:"lang"`
	Zoom         int           `json:"zoom"`
	Lat          string        `json:"lat"`
	Lon          string        `json:"lon"`
	FastMode     bool          `json:"fast_mode"`
	Radius       int           `json:"radius"`
	Depth        int           `json:"depth"`
	Email        bool          `json:"email"`
	ExtraReviews bool          `json:"extra_reviews"`
	MaxTime      time.Duration `json:"max_time"`
	Proxies      []string      `json:"proxies"`
}

func (d *JobData) Validate() error {
	if len(d.Keywords) == 0 {
		return errors.New("missing keywords")
	}

	if d.Lang == "" {
		return errors.New("missing lang")
	}

	if len(d.Lang) != 2 {
		return errors.New("invalid lang")
	}

	if d.Depth == 0 {
		return errors.New("missing depth")
	}

	if d.MaxTime == 0 {
		return errors.New("missing max time")
	}

	latText := strings.TrimSpace(d.Lat)
	lonText := strings.TrimSpace(d.Lon)
	if latText != "" || lonText != "" {
		if latText == "" || lonText == "" {
			return errors.New("latitude and longitude must both be set")
		}

		lat, err := strconv.ParseFloat(latText, 64)
		if err != nil || lat < -90 || lat > 90 {
			return errors.New("invalid latitude")
		}

		lon, err := strconv.ParseFloat(lonText, 64)
		if err != nil || lon < -180 || lon > 180 {
			return errors.New("invalid longitude")
		}

		// The web form historically used 0,0 as its empty-field sentinel.
		// Keep old saved jobs from searching around Null Island.
		if lat == 0 && lon == 0 && d.FastMode {
			return errors.New("missing geo coordinates")
		}
	} else if d.FastMode {
		return errors.New("missing geo coordinates")
	}

	return nil
}

// GeoCoordinates returns optional map coordinates, ignoring the legacy 0,0
// sentinel used by older web searches when no point was selected.
func (d *JobData) GeoCoordinates() string {
	lat := strings.TrimSpace(d.Lat)
	lon := strings.TrimSpace(d.Lon)
	if lat == "" || lon == "" {
		return ""
	}
	if latValue, err := strconv.ParseFloat(lat, 64); err == nil && latValue == 0 {
		if lonValue, err := strconv.ParseFloat(lon, 64); err == nil && lonValue == 0 {
			return ""
		}
	}

	return lat + "," + lon
}
