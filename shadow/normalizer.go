package shadow

import (
	"regexp"
	"strings"
)

var nonDigitRegex = regexp.MustCompile(`\D+`)

// PhoneNormalizer provides telephone and WhatsApp normalization logic.
type PhoneNormalizer struct{}

// NewPhoneNormalizer creates a new PhoneNormalizer instance.
func NewPhoneNormalizer() *PhoneNormalizer {
	return &PhoneNormalizer{}
}

// NormalizePhoneBR converts Brazilian phone numbers to 55 + DDD + number (digits only).
func NormalizePhoneBR(phone string) string {
	digits := nonDigitRegex.ReplaceAllString(phone, "")
	if digits == "" {
		return ""
	}

	if strings.HasPrefix(digits, "0") && len(digits) >= 11 {
		digits = strings.TrimPrefix(digits, "0")
	}

	if strings.HasPrefix(digits, "55") && (len(digits) == 12 || len(digits) == 13) {
		return digits
	}

	if len(digits) == 10 || len(digits) == 11 {
		return "55" + digits
	}

	return digits
}

// Normalize calls NormalizePhoneBR.
func (n *PhoneNormalizer) Normalize(phone string) string {
	return NormalizePhoneBR(phone)
}
