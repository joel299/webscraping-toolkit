from src.gmaps_playwright_scraper import parse_google_web_result_payload


def test_google_web_results_extracts_site_instagram_and_cnpj():
    result = parse_google_web_result_payload({
        "text": "CNPJ da empresa: 57.185.700/0001-15",
        "links": [
            "https://www.instagram.com/don_gigio.barbe...",
            "https://dongigio.com.br/",
            "https://www.facebook.com/don-gigio/",
        ],
    })

    assert result["website"] == "https://dongigio.com.br/"
    assert result["instagram"] == ["https://www.instagram.com/don_gigio.barbe"]
    assert result["cnpj"] == "57.185.700/0001-15"


def test_google_web_results_ignores_social_and_google_links_as_site():
    result = parse_google_web_result_payload({
        "text": "Nenhum CNPJ localizado",
        "links": [
            "https://www.facebook.com/example",
            "https://www.google.com/search?q=example",
            "https://www.instagram.com/example/",
        ],
    })

    assert result["website"] == ""
    assert result["instagram"] == ["https://www.instagram.com/example/"]
    assert result["cnpj"] == ""
