package shadow

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/gosom/google-maps-scraper/gmaps"
)

// ProspectLead represents the internal model for public.prospect_leads_google.
type ProspectLead struct {
	PlaceID        string          `json:"place_id"`
	Cid            string          `json:"cid"`
	PlaceName      string          `json:"place_name"`
	Category       string          `json:"category"`
	Categories     []string        `json:"categories"`
	Address        string          `json:"address"`
	Street         string          `json:"street"`
	City           string          `json:"city"`
	State          string          `json:"state"`
	PostalCode     string          `json:"postal_code"`
	Country        string          `json:"country"`
	Phone          string          `json:"phone"`
	Whatsapp       string          `json:"whatsapp"`
	Website        string          `json:"website"`
	Emails         []string        `json:"emails"`
	Email          string          `json:"email"`
	ReviewRating   float64         `json:"review_rating"`
	ReviewCount    int             `json:"review_count"`
	Latitude       float64         `json:"latitude"`
	Longitude      float64         `json:"longitude"`
	GoogleMapsLink string          `json:"google_maps_link"`
	JobID          string          `json:"job_id"`
	JobName        string          `json:"job_name"`
	CategoriesJSON json.RawMessage `json:"-"`
	EmailsJSON     json.RawMessage `json:"-"`
}

// ProspectLeadMapper maps scraped gmaps.Entry instances to ProspectLead structs.
type ProspectLeadMapper struct {
	normalizer *PhoneNormalizer
}

// NewProspectLeadMapper initializes a new mapper.
func NewProspectLeadMapper() *ProspectLeadMapper {
	return &ProspectLeadMapper{
		normalizer: NewPhoneNormalizer(),
	}
}

// MapToProspectLead converts a gmaps.Entry to a ProspectLead with normalized phone/WhatsApp.
func (m *ProspectLeadMapper) MapToProspectLead(entry *gmaps.Entry, jobID, jobName string) *ProspectLead {
	if entry == nil {
		return nil
	}

	// Deterministic Identity Fallback (GATE 7)
	placeID := entry.DataID
	if placeID == "" {
		placeID = entry.PlaceID
	}
	if placeID == "" {
		placeID = entry.ID
	}
	if placeID == "" {
		if entry.Cid != "" {
			placeID = fmt.Sprintf("cid-%s", entry.Cid)
		} else {
			cleanTitle := strings.TrimSpace(strings.ToLower(entry.Title))
			cleanAddr := strings.TrimSpace(strings.ToLower(entry.Address))
			placeID = fmt.Sprintf("hash-%s|%s", cleanTitle, cleanAddr)
		}
	}

	phoneNorm := m.normalizer.Normalize(entry.Phone)

	var emailFirst string
	if len(entry.Emails) > 0 {
		emailFirst = entry.Emails[0]
	}

	categoriesJSON, _ := json.Marshal(entry.Categories)
	emailsJSON, _ := json.Marshal(entry.Emails)

	return &ProspectLead{
		PlaceID:        placeID,
		Cid:            entry.Cid,
		PlaceName:      entry.Title,
		Category:       entry.Category,
		Categories:     entry.Categories,
		Address:        entry.Address,
		Street:         entry.CompleteAddress.Street,
		City:           entry.CompleteAddress.City,
		State:          entry.CompleteAddress.State,
		PostalCode:     entry.CompleteAddress.PostalCode,
		Country:        entry.CompleteAddress.Country,
		Phone:          entry.Phone,
		Whatsapp:       phoneNorm,
		Website:        entry.WebSite,
		Emails:         entry.Emails,
		Email:          emailFirst,
		ReviewRating:   entry.ReviewRating,
		ReviewCount:    entry.ReviewCount,
		Latitude:       entry.Latitude,
		Longitude:      entry.Longtitude,
		GoogleMapsLink: entry.Link,
		JobID:          jobID,
		JobName:        jobName,
		CategoriesJSON: categoriesJSON,
		EmailsJSON:     emailsJSON,
	}
}
