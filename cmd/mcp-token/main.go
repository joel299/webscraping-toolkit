package main

import (
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/gosom/google-maps-scraper/mcpjwt"
)

func main() {
	subject := flag.String("subject", "local-agent", "identity recorded in the token")
	scopeText := flag.String("scopes", "read,write,delete", "comma-separated scopes: read,write,delete")
	ttlText := flag.String("ttl", "24h", "token lifetime (maximum 720h / 30 days)")
	flag.Parse()

	secret, err := mcpjwt.LoadSecret()
	if err != nil {
		fatal(err)
	}
	if len(secret) == 0 {
		fatal(fmt.Errorf("MCP_JWT_SECRET_FILE is not set; run scripts/setup-mcp-auth.ps1 first"))
	}
	ttl, err := time.ParseDuration(*ttlText)
	if err != nil {
		fatal(fmt.Errorf("invalid token lifetime: %w", err))
	}
	scopes := strings.Split(*scopeText, ",")
	token, err := mcpjwt.Generate(secret, *subject, scopes, ttl, time.Now())
	if err != nil {
		fatal(err)
	}
	fmt.Println(token)
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
