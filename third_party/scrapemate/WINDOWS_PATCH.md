# Local Windows compatibility patch

This is the upstream `github.com/gosom/scrapemate` v1.4.0 module with one
platform-specific browser launch adjustment in
`adapters/fetchers/jshttp/jshttp.go`: Chromium's `--single-process` argument
is omitted on Windows. On this workstation the argument made Playwright close
the target when navigating to Google Maps; without it, the same navigation
completed and returned the page title.

The argument remains enabled on other platforms. Compare the upstream source:
https://github.com/gosom/scrapemate/tree/v1.4.0
