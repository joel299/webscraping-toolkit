package web

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestListGlobalLeadsUsesLocalCSVResults(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "current")
	dataFolder := t.TempDir()
	jobs := []Job{
		{ID: "newer", Name: "Farmácias CG", Status: StatusOK},
		{ID: "older", Name: "Drogarias CG", Status: StatusOK},
		{ID: "pending", Name: "Pending", Status: StatusPending},
	}
	contents := map[string]string{
		"newer": "place_id,title,address,latitude,longitude,link,category,phone,website,review_rating,review_count\n" +
			"place-a,Farmácia A,Rua A,-20.4,-54.6,https://maps.test/a,Pharmacy,111,,4.5,10\n",
		"older": "place_id,title,address,latitude,longitude,link,category,phone,website,review_rating,review_count\n" +
			"place-a,Farmácia A,Rua A,-20.4,-54.6,https://maps.test/a,Pharmacy,111,,4.5,10\n" +
			"place-b,Farmácia B,Rua B,-20.5,-54.7,https://maps.test/b,Pharmacy,222,,4.2,5\n",
	}
	for id, content := range contents {
		if err := os.WriteFile(filepath.Join(dataFolder, id+".csv"), []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
	}

	svc := NewService(&mockJobRepo{jobs: jobs}, dataFolder)
	page, err := svc.ListGlobalLeads(context.Background(), 1, 0)
	if err != nil {
		t.Fatalf("ListGlobalLeads: %v", err)
	}
	if page.Total != 2 || len(page.Items) != 1 || page.Items[0].PlaceID != "place-a" {
		t.Fatalf("first page = %+v, want one of two deduplicated local leads", page)
	}
	if page.Items[0].JobID != "newer" || page.Items[0].JobName != "Farmácias CG" {
		t.Fatalf("lead provenance = %+v, want newest search metadata", page.Items[0])
	}

	page, err = svc.ListGlobalLeads(context.Background(), 1, 1)
	if err != nil {
		t.Fatalf("ListGlobalLeads page 2: %v", err)
	}
	if page.Total != 2 || len(page.Items) != 1 || page.Items[0].PlaceID != "place-b" {
		t.Fatalf("second page = %+v, want place-b", page)
	}
}

func TestListGlobalLeadsDeduplicatesByNormalizedPhoneAndAddress(t *testing.T) {
	t.Setenv("PROSPECT_READ_MODE", "current")
	dataFolder := t.TempDir()
	jobs := []Job{
		{ID: "newer", Name: "Farmácias — Nova Andradina", Status: StatusOK},
		{ID: "older", Name: "Farmácias — MS", Status: StatusOK},
	}
	contents := map[string]string{
		"newer": "place_id,title,address,latitude,longitude,link,category,phone,website,review_rating,review_count\n" +
			"place-new,Farmácia Central,Rua A,-22.2,-53.3,https://maps.test/new,Pharmacy,(67) 3333-0000,,4.5,10\n",
		"older": "place_id,title,address,latitude,longitude,link,category,phone,website,review_rating,review_count\n" +
			"place-old,Farmácia Central,Farmácia Central - Rúa Á,-22.2,-53.3,https://maps.test/old,Pharmacy,+55 67 3333-0000,,4.7,12\n" +
			"place-other-address,Outra unidade,Rua B,-22.2,-53.3,https://maps.test/other,Pharmacy,(67) 3333-0000,,4.1,4\n" +
			"place-other-phone,Farmácia da Rua A,Rua A,-22.2,-53.3,https://maps.test/phone,Pharmacy,(67) 3333-9999,,4.2,5\n",
	}
	for id, content := range contents {
		if err := os.WriteFile(filepath.Join(dataFolder, id+".csv"), []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
	}

	svc := NewService(&mockJobRepo{jobs: jobs}, dataFolder)
	page, err := svc.ListGlobalLeads(context.Background(), 20, 0)
	if err != nil {
		t.Fatalf("ListGlobalLeads: %v", err)
	}
	if page.Total != 3 || len(page.Items) != 3 {
		t.Fatalf("got %d consolidated leads, want duplicate phone/address pair collapsed and distinct businesses retained: %+v", page.Total, page.Items)
	}
	if page.Items[0].PlaceID != "place-new" {
		t.Fatalf("canonical lead = %+v, want newest record retained", page.Items[0])
	}
}
