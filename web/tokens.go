package web

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/gosom/google-maps-scraper/mcpjwt"
)

type createTokenRequest struct {
	Subject string   `json:"subject"`
	Scopes  []string `json:"scopes"`
	TTL     string   `json:"ttl,omitempty"`
}

type createTokenResponse struct {
	AccessToken string    `json:"access_token"`
	TokenType   string    `json:"token_type"`
	Subject     string    `json:"subject"`
	Scopes      []string  `json:"scopes"`
	ExpiresAt   time.Time `json:"expires_at"`
}

func (s *Server) apiCreateToken(w http.ResponseWriter, r *http.Request) {
	if !s.authEnabled || len(s.jwtSecret) == 0 {
		renderJSON(w, http.StatusServiceUnavailable, apiError{Code: http.StatusServiceUnavailable, Message: "JWT authentication is not configured"})
		return
	}
	var input createTokenRequest
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&input); err != nil {
		renderJSON(w, http.StatusBadRequest, apiError{Code: http.StatusBadRequest, Message: "invalid JSON request"})
		return
	}
	if strings.TrimSpace(input.TTL) == "" {
		input.TTL = "720h"
	}
	ttl, err := time.ParseDuration(input.TTL)
	if err != nil {
		renderJSON(w, http.StatusBadRequest, apiError{Code: http.StatusBadRequest, Message: "ttl must be a duration such as 30m or 24h"})
		return
	}
	now := time.Now().UTC()
	token, err := mcpjwt.Generate(s.jwtSecret, input.Subject, input.Scopes, ttl, now)
	if err != nil {
		renderJSON(w, http.StatusUnprocessableEntity, apiError{Code: http.StatusUnprocessableEntity, Message: err.Error()})
		return
	}
	renderJSON(w, http.StatusCreated, createTokenResponse{
		AccessToken: token,
		TokenType:   "Bearer",
		Subject:     strings.TrimSpace(input.Subject),
		Scopes:      input.Scopes,
		ExpiresAt:   now.Add(ttl),
	})
}
