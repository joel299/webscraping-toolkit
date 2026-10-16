package web

import (
	"testing"
	"time"
)

func TestGeoCoordinatesIgnoresLegacyZeroSentinel(t *testing.T) {
	data := JobData{Lat: "0", Lon: "0"}
	if got := data.GeoCoordinates(); got != "" {
		t.Fatalf("GeoCoordinates() = %q, want empty", got)
	}
}

func TestGeoCoordinatesReturnsSelectedPoint(t *testing.T) {
	data := JobData{Lat: "-20.4486", Lon: "-54.6295"}
	if got, want := data.GeoCoordinates(), "-20.4486,-54.6295"; got != want {
		t.Fatalf("GeoCoordinates() = %q, want %q", got, want)
	}
}

func TestValidateRejectsFastModeWithoutSelectedPoint(t *testing.T) {
	data := JobData{
		Keywords: []string{"farmacia em Campo Grande"},
		Lang:     "pt",
		Depth:    10,
		MaxTime:  5 * time.Minute,
		FastMode: true,
		Lat:      "0",
		Lon:      "0",
	}
	if err := data.Validate(); err == nil {
		t.Fatal("Validate() accepted fast mode with the legacy empty-point sentinel")
	}
}
