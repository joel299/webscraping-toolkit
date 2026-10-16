package sqlite

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	_ "modernc.org/sqlite" // sqlite driver

	"github.com/gosom/google-maps-scraper/web"
	"golang.org/x/crypto/bcrypt"
)

type repo struct {
	db *sql.DB
}

func (repo *repo) Close() error {
	return repo.db.Close()
}

func New(path string) (web.JobRepository, error) {
	db, err := initDatabase(path)
	if err != nil {
		return nil, err
	}

	return &repo{db: db}, nil
}

func (repo *repo) Get(ctx context.Context, id string) (web.Job, error) {
	const q = `SELECT id, name, status, data, created_at, updated_at, cache_key FROM jobs WHERE id = ?`

	row := repo.db.QueryRowContext(ctx, q, id)

	return rowToJob(row)
}

func (repo *repo) Create(ctx context.Context, job *web.Job) error {
	item, err := jobToRow(job)
	if err != nil {
		return err
	}

	const q = `INSERT INTO jobs (id, name, status, data, created_at, updated_at, cache_key) VALUES (?, ?, ?, ?, ?, ?, ?)`

	_, err = repo.db.ExecContext(ctx, q, item.ID, item.Name, item.Status, item.Data, item.CreatedAt, item.UpdatedAt, item.CacheKey)
	if err != nil {
		return err
	}

	return nil
}

func (repo *repo) Delete(ctx context.Context, id string) error {
	const q = `DELETE FROM jobs WHERE id = ?`

	_, err := repo.db.ExecContext(ctx, q, id)

	return err
}

func (repo *repo) Select(ctx context.Context, params web.SelectParams) ([]web.Job, error) {
	q := `SELECT id, name, status, data, created_at, updated_at, cache_key FROM jobs`

	var args []any

	if params.Status != "" {
		q += ` WHERE status = ?`

		args = append(args, params.Status)
	}

	q += " ORDER BY created_at DESC, id DESC"

	if params.Limit > 0 {
		q += " LIMIT ?"

		args = append(args, params.Limit)
	}

	if params.Offset > 0 {
		if params.Limit <= 0 {
			q += " LIMIT -1"
		}

		q += " OFFSET ?"

		args = append(args, params.Offset)
	}

	rows, err := repo.db.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, err
	}

	defer rows.Close()

	var ans []web.Job

	for rows.Next() {
		job, err := rowToJob(rows)
		if err != nil {
			return nil, err
		}

		ans = append(ans, job)
	}

	if err := rows.Err(); err != nil {
		return nil, err
	}

	return ans, nil
}

func (repo *repo) ClaimPending(ctx context.Context) (*web.Job, error) {
	const q = `
		UPDATE jobs
		SET status = ?, updated_at = ?
		WHERE id = (
			SELECT id FROM jobs
			WHERE status = ?
			ORDER BY created_at DESC, id DESC
			LIMIT 1
		)
		AND status = ?
		RETURNING id, name, status, data, created_at, updated_at, cache_key`

	row := repo.db.QueryRowContext(ctx, q, web.StatusWorking, time.Now().UTC().Unix(), web.StatusPending, web.StatusPending)
	job, err := rowToJob(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, web.ErrNoJobAvailable
	}
	if err != nil {
		return nil, err
	}

	return &job, nil
}

// RecoverWorking requeues jobs that were interrupted while the process was down.
// It is called once during runner startup, before any workers begin claiming jobs.
func (repo *repo) RecoverWorking(ctx context.Context) (int64, error) {
	result, err := repo.db.ExecContext(ctx,
		`UPDATE jobs SET status = ?, updated_at = ? WHERE status = ?`,
		web.StatusPending, time.Now().UTC().Unix(), web.StatusWorking,
	)
	if err != nil {
		return 0, fmt.Errorf("requeue interrupted jobs: %w", err)
	}

	count, err := result.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("count requeued jobs: %w", err)
	}

	return count, nil
}

func (repo *repo) Count(ctx context.Context, params web.SelectParams) (int, error) {
	q := `SELECT COUNT(*) from jobs`

	var args []any

	if params.Status != "" {
		q += ` WHERE status = ?`

		args = append(args, params.Status)
	}

	var count int

	err := repo.db.QueryRowContext(ctx, q, args...).Scan(&count)
	if err != nil {
		return 0, err
	}

	return count, nil
}

func (repo *repo) Update(ctx context.Context, job *web.Job) error {
	item, err := jobToRow(job)
	if err != nil {
		return err
	}

	const q = `UPDATE jobs SET name = ?, status = ?, data = ?, updated_at = ?, cache_key = ? WHERE id = ?`

	_, err = repo.db.ExecContext(ctx, q, item.Name, item.Status, item.Data, item.UpdatedAt, item.CacheKey, item.ID)

	return err
}

type scannable interface {
	Scan(dest ...any) error
}

func rowToJob(row scannable) (web.Job, error) {
	var j job

	err := row.Scan(&j.ID, &j.Name, &j.Status, &j.Data, &j.CreatedAt, &j.UpdatedAt, &j.CacheKey)
	if err != nil {
		return web.Job{}, err
	}

	ans := web.Job{
		ID:       j.ID,
		Name:     j.Name,
		Status:   j.Status,
		Date:     time.Unix(j.CreatedAt, 0).UTC(),
		CacheKey: j.CacheKey,
	}

	err = json.Unmarshal([]byte(j.Data), &ans.Data)
	if err != nil {
		return web.Job{}, err
	}

	return ans, nil
}

func jobToRow(item *web.Job) (job, error) {
	data, err := json.Marshal(item.Data)
	if err != nil {
		return job{}, err
	}

	return job{
		ID:        item.ID,
		Name:      item.Name,
		Status:    item.Status,
		Data:      string(data),
		CreatedAt: item.Date.Unix(),
		UpdatedAt: time.Now().UTC().Unix(),
		CacheKey:  item.CacheKey,
	}, nil
}

type job struct {
	ID        string
	Name      string
	Status    string
	Data      string
	CreatedAt int64
	UpdatedAt int64
	CacheKey  string
}

func (repo *repo) CreateOrReuseSearch(ctx context.Context, candidate *web.Job, key string, now time.Time, ttl time.Duration, forceRefresh bool) (web.Job, bool, bool, error) {
	tx, err := repo.db.BeginTx(ctx, nil)
	if err != nil {
		return web.Job{}, false, false, err
	}
	defer tx.Rollback()

	const find = `
		SELECT id, status, updated_at FROM jobs
		WHERE cache_key = ? AND status IN (?, ?, ?)
		ORDER BY CASE WHEN status IN (?, ?) THEN 0 ELSE 1 END, updated_at DESC, id DESC
		LIMIT 1`
	var existingID, status string
	var updatedAt int64
	err = tx.QueryRowContext(ctx, find, key, web.StatusPending, web.StatusWorking, web.StatusOK, web.StatusPending, web.StatusWorking).Scan(&existingID, &status, &updatedAt)
	if err == nil {
		active := status == web.StatusPending || status == web.StatusWorking
		fresh := status == web.StatusOK && now.Unix()-updatedAt <= int64(ttl.Seconds())
		if active || (fresh && !forceRefresh) {
			const get = `SELECT id, name, status, data, created_at, updated_at, cache_key FROM jobs WHERE id = ?`
			cached, getErr := rowToJob(tx.QueryRowContext(ctx, get, existingID))
			if getErr != nil {
				return web.Job{}, false, false, getErr
			}
			if err := tx.Commit(); err != nil {
				return web.Job{}, false, false, err
			}
			return cached, true, fresh, nil
		}
	} else if !errors.Is(err, sql.ErrNoRows) {
		return web.Job{}, false, false, err
	}

	item, err := jobToRow(candidate)
	if err != nil {
		return web.Job{}, false, false, err
	}
	const insert = `INSERT INTO jobs (id, name, status, data, created_at, updated_at, cache_key) VALUES (?, ?, ?, ?, ?, ?, ?)`
	if _, err := tx.ExecContext(ctx, insert, item.ID, item.Name, item.Status, item.Data, item.CreatedAt, item.UpdatedAt, key); err != nil {
		return web.Job{}, false, false, err
	}
	candidate.CacheKey = key
	if err := tx.Commit(); err != nil {
		return web.Job{}, false, false, err
	}
	return *candidate, false, false, nil
}

func initDatabase(path string) (*sql.DB, error) {
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}

	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(30 * time.Minute)

	_, err = db.Exec("PRAGMA busy_timeout = 5000")
	if err != nil {
		return nil, err
	}

	_, err = db.Exec("PRAGMA journal_mode=WAL")
	if err != nil {
		return nil, err
	}

	_, err = db.Exec("PRAGMA synchronous=NORMAL")
	if err != nil {
		return nil, err
	}

	_, err = db.Exec("PRAGMA cache_size=1000")
	if err != nil {
		return nil, err
	}

	err = db.Ping()
	if err != nil {
		return nil, err
	}

	return db, createSchema(db)
}

func createSchema(db *sql.DB) error {
	_, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS jobs (
			id TEXT PRIMARY KEY,
			name TEXT NOT NULL,
			status TEXT NOT NULL,
			data TEXT NOT NULL,
			created_at INT NOT NULL,
			updated_at INT NOT NULL,
			cache_key TEXT NOT NULL DEFAULT ''
		);

		CREATE INDEX IF NOT EXISTS idx_jobs_created_at_id
			ON jobs (created_at DESC, id DESC);

		CREATE TABLE IF NOT EXISTS api_credentials (
			email TEXT PRIMARY KEY COLLATE NOCASE,
			password_hash TEXT NOT NULL,
			created_at INT NOT NULL
		);
	`)

	if err != nil {
		return err
	}
	if err := ensureCacheKeyColumn(db); err != nil {
		return err
	}
	if _, err := db.Exec(`CREATE INDEX IF NOT EXISTS idx_jobs_cache_key_created_at ON jobs (cache_key, created_at DESC, id DESC)`); err != nil {
		return err
	}
	return backfillCacheKeys(db)
}

func ensureCacheKeyColumn(db *sql.DB) error {
	rows, err := db.Query(`PRAGMA table_info(jobs)`)
	if err != nil {
		return err
	}
	found := false
	for rows.Next() {
		var cid int
		var name, columnType string
		var notNull, primaryKey int
		var defaultValue any
		if err := rows.Scan(&cid, &name, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
			_ = rows.Close()
			return err
		}
		if name == "cache_key" {
			found = true
		}
	}
	if err := rows.Err(); err != nil {
		_ = rows.Close()
		return err
	}
	if err := rows.Close(); err != nil {
		return err
	}
	if found {
		return nil
	}
	_, err = db.Exec(`ALTER TABLE jobs ADD COLUMN cache_key TEXT NOT NULL DEFAULT ''`)
	return err
}

func backfillCacheKeys(db *sql.DB) error {
	rows, err := db.Query(`SELECT id, data FROM jobs WHERE cache_key = ''`)
	if err != nil {
		return err
	}
	type record struct{ id, data string }
	var records []record
	for rows.Next() {
		var item record
		if err := rows.Scan(&item.id, &item.data); err != nil {
			_ = rows.Close()
			return err
		}
		records = append(records, item)
	}
	if err := rows.Err(); err != nil {
		_ = rows.Close()
		return err
	}
	if err := rows.Close(); err != nil {
		return err
	}
	for _, item := range records {
		var data web.JobData
		if err := json.Unmarshal([]byte(item.data), &data); err != nil {
			// A malformed legacy job must not prevent the service from starting.
			continue
		}
		key, err := web.SearchCacheKey(data)
		if err != nil {
			continue
		}
		if _, err := db.Exec(`UPDATE jobs SET cache_key = ? WHERE id = ? AND cache_key = ''`, key, item.id); err != nil {
			return err
		}
	}
	return nil
}

// CreateFirstCredential bootstraps the first API identity exactly once.
func (repo *repo) CreateFirstCredential(ctx context.Context, email, password string) error {
	email = strings.ToLower(strings.TrimSpace(email))
	if email == "" || len(password) < 12 {
		return fmt.Errorf("email and a password of at least 12 characters are required")
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return err
	}
	tx, err := repo.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var count int
	if err := tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM api_credentials`).Scan(&count); err != nil {
		return err
	}
	if count != 0 {
		return web.ErrCredentialAlreadyInitialized
	}
	if _, err := tx.ExecContext(ctx, `INSERT INTO api_credentials (email, password_hash, created_at) VALUES (?, ?, ?)`, email, string(hash), time.Now().UTC().Unix()); err != nil {
		return err
	}
	return tx.Commit()
}

// PasswordHash returns the saved bcrypt hash for an email address.
func (repo *repo) PasswordHash(ctx context.Context, email string) (string, error) {
	var hash string
	err := repo.db.QueryRowContext(ctx, `SELECT password_hash FROM api_credentials WHERE email = ?`, strings.ToLower(strings.TrimSpace(email))).Scan(&hash)
	if errors.Is(err, sql.ErrNoRows) {
		return "", web.ErrCredentialNotFound
	}
	return hash, err
}
