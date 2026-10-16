package web

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/mail"
	"strings"
	"time"

	"github.com/gosom/google-maps-scraper/mcpjwt"
	"golang.org/x/crypto/bcrypt"
)

const apiAccountTokenTTL = 30 * 24 * time.Hour

type credentialRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type accountTokenResponse struct {
	AccessToken string    `json:"access_token"`
	TokenType   string    `json:"token_type"`
	Subject     string    `json:"subject"`
	Scopes      []string  `json:"scopes"`
	ExpiresAt   time.Time `json:"expires_at"`
}

func (s *Server) apiSetupCredential(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", http.MethodPost)
		renderJSON(w, http.StatusMethodNotAllowed, apiError{Code: http.StatusMethodNotAllowed, Message: methodNotAllowedMessage})
		return
	}
	if s.svc.credentials == nil {
		renderJSON(w, http.StatusServiceUnavailable, apiError{Code: http.StatusServiceUnavailable, Message: "persistent API account storage is unavailable"})
		return
	}
	input, ok := decodeCredentialRequest(w, r)
	if !ok {
		return
	}
	if !s.authEnabled || len(s.jwtSecret) == 0 {
		renderJSON(w, http.StatusServiceUnavailable, apiError{Code: http.StatusServiceUnavailable, Message: "JWT authentication is not configured"})
		return
	}
	if err := s.svc.credentials.CreateFirstCredential(r.Context(), input.Email, input.Password); err != nil {
		if errors.Is(err, ErrCredentialAlreadyInitialized) {
			renderJSON(w, http.StatusConflict, apiError{Code: http.StatusConflict, Message: "API account is already initialized"})
			return
		}
		renderJSON(w, http.StatusInternalServerError, apiError{Code: http.StatusInternalServerError, Message: "could not save API account"})
		return
	}
	s.issueAccountToken(w, input.Email)
}

func (s *Server) apiLogin(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", http.MethodPost)
		renderJSON(w, http.StatusMethodNotAllowed, apiError{Code: http.StatusMethodNotAllowed, Message: methodNotAllowedMessage})
		return
	}
	if s.svc.credentials == nil {
		renderJSON(w, http.StatusServiceUnavailable, apiError{Code: http.StatusServiceUnavailable, Message: "persistent API account storage is unavailable"})
		return
	}
	input, ok := decodeCredentialRequest(w, r)
	if !ok {
		return
	}
	hash, err := s.svc.credentials.PasswordHash(r.Context(), input.Email)
	if err != nil || bcrypt.CompareHashAndPassword([]byte(hash), []byte(input.Password)) != nil {
		renderJSON(w, http.StatusUnauthorized, apiError{Code: http.StatusUnauthorized, Message: "email or password is incorrect"})
		return
	}
	s.issueAccountToken(w, input.Email)
}

func decodeCredentialRequest(w http.ResponseWriter, r *http.Request) (credentialRequest, bool) {
	var input credentialRequest
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&input); err != nil {
		renderJSON(w, http.StatusBadRequest, apiError{Code: http.StatusBadRequest, Message: "invalid JSON request"})
		return input, false
	}
	input.Email = strings.ToLower(strings.TrimSpace(input.Email))
	address, err := mail.ParseAddress(input.Email)
	if err != nil || address.Address != input.Email || len(input.Email) > 254 || strings.TrimSpace(input.Password) != input.Password || len(input.Password) < 12 || len(input.Password) > 72 {
		renderJSON(w, http.StatusUnprocessableEntity, apiError{Code: http.StatusUnprocessableEntity, Message: "provide a valid email and a password of 12 to 72 bytes without surrounding whitespace"})
		return input, false
	}
	return input, true
}

func (s *Server) issueAccountToken(w http.ResponseWriter, email string) {
	now := time.Now().UTC()
	scopes := []string{"read", "write", "delete", "token:issue"}
	token, err := mcpjwt.Generate(s.jwtSecret, email, scopes, apiAccountTokenTTL, now)
	if err != nil {
		renderJSON(w, http.StatusInternalServerError, apiError{Code: http.StatusInternalServerError, Message: "could not create access token"})
		return
	}
	renderJSON(w, http.StatusOK, accountTokenResponse{
		AccessToken: token,
		TokenType:   "Bearer",
		Subject:     email,
		Scopes:      scopes,
		ExpiresAt:   now.Add(apiAccountTokenTTL),
	})
}
