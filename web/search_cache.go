package web

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sort"
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

// SearchCacheKey returns a stable key for equivalent searches and their result-affecting options.
func SearchCacheKey(data JobData) (string, error) {
	keywords := make([]string, 0, len(data.Keywords))
	for _, keyword := range data.Keywords {
		keyword = normalizeKeyword(keyword)
		if keyword != "" {
			keywords = append(keywords, keyword)
		}
	}
	if len(keywords) == 0 {
		return "", errors.New("search cache requires at least one keyword")
	}
	sort.Strings(keywords)
	keywords = compactStrings(keywords)
	query := strings.Join(keywords, " | ")

	category := normalizeCategory(data.Category)
	city := normalizeSearchText(data.City)
	state := normalizeSearchText(data.State)
	if category != "" || city != "" || state != "" {
		structured := strings.TrimSpace(strings.Join([]string{category, city, state}, " "))
		structured = strings.TrimSpace(strings.ReplaceAll(structured, "  ", " "))
		if structured != query {
			query = structured + " | " + query
		}
	}

	proxies := make([]string, 0, len(data.Proxies))
	for _, proxy := range data.Proxies {
		proxy = strings.TrimSpace(proxy)
		if proxy != "" {
			proxies = append(proxies, proxy)
		}
	}
	sort.Strings(proxies)
	proxies = compactStrings(proxies)

	identity := struct {
		Query        string   `json:"query"`
		Lang         string   `json:"lang"`
		Zoom         int      `json:"zoom"`
		Lat          string   `json:"lat"`
		Lon          string   `json:"lon"`
		FastMode     bool     `json:"fast_mode"`
		Radius       int      `json:"radius"`
		Depth        int      `json:"depth"`
		Email        bool     `json:"email"`
		ExtraReviews bool     `json:"extra_reviews"`
		Proxies      []string `json:"proxies"`
	}{
		Query: query, Lang: strings.ToLower(strings.TrimSpace(data.Lang)), Zoom: data.Zoom,
		Lat: strings.TrimSpace(data.Lat), Lon: strings.TrimSpace(data.Lon), FastMode: data.FastMode,
		Radius: data.Radius, Depth: data.Depth, Email: data.Email, ExtraReviews: data.ExtraReviews,
		Proxies: proxies,
	}

	encoded, err := json.Marshal(identity)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:]), nil
}

func normalizeKeyword(keyword string) string {
	parts := strings.Fields(normalizeSearchText(keyword))
	if len(parts) == 0 {
		return ""
	}
	parts[0] = normalizeCategory(parts[0])
	if len(parts) > 1 && parts[1] == "em" {
		parts = append(parts[:1], parts[2:]...)
	}
	return strings.Join(parts, " ")
}

func normalizeCategory(category string) string {
	normalized := normalizeSearchText(category)
	switch normalized {
	case "farmacias":
		return "farmacia"
	case "drogarias":
		return "drogaria"
	case "restaurantes":
		return "restaurante"
	case "clinicas":
		return "clinica"
	case "pizzarias":
		return "pizzaria"
	case "padarias":
		return "padaria"
	case "mercados":
		return "mercado"
	case "bares":
		return "bar"
	case "hoteis":
		return "hotel"
	default:
		return normalized
	}
}

func normalizeSearchText(value string) string {
	value = strings.ToLower(norm.NFD.String(strings.TrimSpace(value)))
	var builder strings.Builder
	space := true
	for _, char := range value {
		if unicode.Is(unicode.Mn, char) {
			continue
		}
		if unicode.IsLetter(char) || unicode.IsDigit(char) {
			builder.WriteRune(char)
			space = false
			continue
		}
		if !space {
			builder.WriteByte(' ')
			space = true
		}
	}
	return strings.TrimSpace(builder.String())
}

func compactStrings(values []string) []string {
	if len(values) < 2 {
		return values
	}
	unique := values[:1]
	for _, value := range values[1:] {
		if value != unique[len(unique)-1] {
			unique = append(unique, value)
		}
	}
	return unique
}
