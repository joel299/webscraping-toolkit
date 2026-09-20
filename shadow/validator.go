package shadow

import (
	"errors"
	"strings"
)

var (
	ErrMissingPlaceID   = errors.New("prospect lead missing place_id")
	ErrMissingPlaceName = errors.New("prospect lead missing place_name")
)

// ProspectLeadValidator validates minimal required attributes for a prospect lead before persistence.
type ProspectLeadValidator struct{}

// NewProspectLeadValidator initializes a new validator.
func NewProspectLeadValidator() *ProspectLeadValidator {
	return &ProspectLeadValidator{}
}

// Validate checks whether a ProspectLead meets persistence constraints.
func (v *ProspectLeadValidator) Validate(lead *ProspectLead) error {
	if lead == nil {
		return errors.New("nil prospect lead")
	}

	if strings.TrimSpace(lead.PlaceID) == "" {
		return ErrMissingPlaceID
	}

	if strings.TrimSpace(lead.PlaceName) == "" {
		return ErrMissingPlaceName
	}

	return nil
}
