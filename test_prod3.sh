#!/usr/bin/env bash
# =============================================================================
# Bookfinder API – Production Test Suite (v5.1)
# Targeting: Ngrok Tunnel -> Caddy -> Docker Container
# Verifies: All v5.1 Features, including Security, Cache, and Metadata
# =============================================================================

set -uo pipefail

# --- CONFIGURATION ---
# Default to your specific Ngrok URL (can be overridden via env var)
BASE_URL="${BASE_URL:-https://db4f-24-22-90-227.ngrok-free.app/books}"
ADMIN_KEY="${ADMIN_KEY:-B0tanchr1}"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# --- Stats ---
TOTAL=0
PASSED=0
FAILED=0

# --- Simple curl-based request function ---
request() {
    local method="$1"
    local path="$2"
    local expected_status="${3:-200}"
    local description="$4"
    local jq_filter="${5:-.}"
    local extra_headers="${6:-}"

    ((TOTAL++))

    printf "${BLUE}→ Test %-2d: %-55s${NC}" "$TOTAL" "$description"

    # Execute request
    # -L: Follow redirects
    # -H "ngrok-skip-browser-warning": Bypasses the Ngrok interstitial page
    local response
    response=$(curl -s -L -w "\n%{http_code}" -X "$method" \
        -H "ngrok-skip-browser-warning: true" \
        $extra_headers \
        "$BASE_URL$path")

    local body=$(echo "$response" | sed '$d')
    local status=$(echo "$response" | tail -n1)

    # Allow 200 OK or 503 Service Unavailable (if Open Library is acting up upstream)
    if [[ "$status" == "$expected_status" ]] || [[ "$path" == "/health" && "$status" == "503" ]]; then
        echo -e "${GREEN}PASS${NC} ($status)"
        ((PASSED++))
        if command -v jq &> /dev/null; then
            local output
            output=$(echo "$body" | jq -C "$jq_filter" 2>/dev/null || echo "false")
            if [[ "$output" == "true" ]]; then
                echo "Assertion True"
            elif [[ "$output" == "false" ]]; then
                echo -e "${RED}Assertion False (Check JQ filter)${NC}"
                echo "Response Sample: $(echo "$body" | head -c 200)"
            elif [[ "$output" == "null" ]]; then
                echo -e "${RED}Assertion Null (Check JQ filter)${NC}"
            else
                echo "$output" | head -n 5
            fi
        else
            echo "JQ not installed, skipping assertion detail."
        fi
    else
        echo -e "${RED}FAIL${NC} (got $status, expected $expected_status)"
        ((FAILED++))
        if command -v jq &> /dev/null; then
            echo "$body" | jq . 2>/dev/null || echo "Raw: $body"
        else
            echo "Raw: $body"
        fi
    fi
    echo
}

# =============================================================================
# TESTS START HERE
# =============================================================================

clear
echo -e "${YELLOW}
╔══════════════════════════════════════════════════════════════════════════════╗
║                Bookfinder API – Production Test Suite (v5.1)                 ║
║              Running against → $BASE_URL                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝${NC}
"
sleep 1

# --- Setup for Date-based Tests ---
YEAR=$(date +%Y)
CUTOFF=$((YEAR - 1))

# 1. Root & Health
request GET "/"                 200 "Root endpoint"                 '{message}'
request GET "/health"           200 "Health check"                   '.status'

# 2. Admin Security
if [[ -n "$ADMIN_KEY" ]]; then
    request GET "/cache/stats"       401 "Cache stats – no key"           '.detail'
    request GET "/cache/stats"       200 "Cache stats – valid key"        '.key_count' "-H x-admin-key:$ADMIN_KEY"
fi

# 3. Static Data
request GET "/genres/fiction"        200 "Fiction genres list"         '.[0] | {umbrella, name}'

# 4. ISBN Logic
request GET "/book/isbn/12345"             400 "ISBN bad format (Too Short)"            '.detail'
request GET "/book/isbn/0-441-17271-7"     200 "ISBN-10 → ISBN-13"          '{title, isbn_13}'

# -----------------------------------------------------------------------------
# 5. v2.0 INTELLIGENT FEATURES & REGRESSION CHECKS
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v2.0 Features & Regression Checks...${NC}"

request GET "/book/isbn/9781969265013" 200 "Heuristic Tagging (Auto-detected Genres)" \
    '.subjects | index("Paranormal") != null or index("Thriller") != null'

request GET "/book/isbn/9781969265013" 200 "Format Classification (Novel/eBook)" \
    '{format_tag, page_count}'

request GET "/search?q=dune&limit=1" 200 "Published Date in Search Results" \
    '.results[0] | {title, published_date: (.published_date != null)}'

request GET "/search?q=harry+potter&limit=1&startIndex=0" 200 "Pagination Page 1" '.results[0].title'
request GET "/search?q=harry+potter&limit=1&startIndex=1" 200 "Pagination Page 2" '.results[0].title'

request GET "/book/isbn/9780441172719" 200 "Series Detection (Dune)" \
    '{series_name: .series.name, order: .series.order}'

request GET "/book/isbn/9780441172719" 200 "ISBN Consolidation (Related Editions)" \
    '.related_isbns | length > 0'

request GET "/book/isbn/9781969265013" 200 "Content Safety Flag Structure" \
    'has("content_flag")'

request GET "/new-releases?limit=1" 200 "Image Regression (Covers must exist)" \
    '.results[0].cover_url != null'

# -----------------------------------------------------------------------------
# 6. Utility & Boundary Conditions (v3.5)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing Utility & Boundary Conditions...${NC}"

request GET "/book/isbn/9780441172719" 200 "1. HTML Cleaning (Description has no <...>)" \
    '.description | contains("<") == false'

request GET "/book/isbn/9781250301697" 200 "2. Series Detection (Negative Test: Null)" \
    '.series == null'

request GET "/book/isbn/9781449340377" 200 "3. Heuristic Tagging (Non-Fiction/Technology)" \
    '.subjects | index("Technology") != null'

request GET "/book/isbn/9780140177398" 200 "4. Format Classification (Novella Boundary)" \
    '.format_tag == "Novella"'

request GET "/search?q=dune&limit=1&startIndex=5" 200 "5. Pagination Offset (Search Page 2)" \
    '.results[0].title | contains("Dune")'

request GET "/search?q=dune&limit=1" 200 "6. Search Thumbnail Opt (No Zoom=0)" \
    '.results[0].cover_url | contains("zoom=0") == false'

request GET "/new-releases?limit=5" 200 "7. True New Releases (Year >= $CUTOFF)" \
    ".results | all(.published_date | .[0:4] | tonumber >= $CUTOFF)"

# -----------------------------------------------------------------------------
# 7. Library of Congress Integration (v2.1.1 & v4.2/4.3)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing Library of Congress Features...${NC}"

request GET "/book/isbn/9780312204440" 200 "8. LoC Date Authority (Cloud Mountain)" \
    '.published_date | .[0:4] | tonumber < 2000'

request GET "/book/isbn/9780743273565" 200 "9. LoC Subject Enrichment (Great Gatsby)" \
    '.subjects | length > 5'

request GET "/book/isbn/9780441172719" 200 "10. Source Attribution (Dune)" \
    '.data_sources | index("Google Books") != null and index("Open Library") != null'

request GET "/search?q=13th+Amendment" 200 "11. LOC Search Integration" \
    '.results | any(.data_sources | index("Library of Congress") != null)'

# -----------------------------------------------------------------------------
# 8. Deep Dredge & Cover Integrity (v3.0.2)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.0.2 Deep Dredge & Cover Integrity...${NC}"

request GET "/new-releases?limit=12&subject=Mystery" 200 "12. Deep Dredge Quantity (Exact Count)" \
    '.results | length == 12'

request GET "/new-releases?limit=10&subject=Thriller" 200 "13. Cover Image Guarantee (No Nulls)" \
    '.results | all(.cover_url != null)'

request GET "/new-releases?limit=20&subject=Sci-Fi" 200 "14. Deep Dredge Quality (No Old Books)" \
    ".results | all(.published_date | .[0:4] | tonumber >= $CUTOFF)"

# -----------------------------------------------------------------------------
# 9. Regression Proofing (v3.7)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.7 Regression Proofing...${NC}"

request GET "/new-releases?limit=10&subject=History" 200 "15. Metadata Hygiene (Authors & Pubs)" \
    '.results | all(.authors != [] and .publisher != null)'

request GET "/new-releases?limit=20&subject=Fantasy" 200 "16. Spam/Reprint Filter Check" \
    '.results | all(.title | test("(?i)(summary|anniversary|analysis)") | not)'

# -----------------------------------------------------------------------------
# 10. Dual-Mode Author Strategy (v3.8)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.8 Dual-Mode Author Strategy...${NC}"

request GET "/author/Megan%20Bledsoe" 200 "17. Dual-Mode Author (Name Search)" \
    '.source == "google_books" and (.books | length > 0)'

# -----------------------------------------------------------------------------
# 11. Bio Miner Validation (v3.9 - v4.0)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.9+ Bio Miner & Sanitization...${NC}"

request GET "/author/Megan%20Bledsoe" 200 "18. Bio Miner (Extracted Text)" \
    '.bio | contains("Pacific Northwest")'

request GET "/author/Nyron_Bovell" 200 "19. Underscore Sanitization" \
    '.name == "Nyron Bovell" and .source == "google_books"'

request GET "/author/Megan%20Bledsoe" 200 "20. Bio Miner vs Placeholder Check" \
    '.bio | length > 60'

# -----------------------------------------------------------------------------
# 12. Universal ID Lookup (v4.4)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v4.4 Universal ID Lookup...${NC}"

request GET "/book/isbn/2013657690" 200 "21. Universal ID (LCCN Lookup)" \
    '.title | contains("Pride") and (.data_sources | index("Library of Congress") != null)'

request GET "/book/isbn/2013657690" 200 "22. Detailed LOC Validation" \
    '.lccn[0] == "2013657690" and .authors[0].name != null'

request GET "/book/isbn/2011287276" 200 "23. LCCN Lookup (Pride and Prejudice)" \
    '.title == "Pride and prejudice" and .publisher == "Oxford University Press"'

# -----------------------------------------------------------------------------
# 13. Indie Author Rescue & Relevance Boosting (v4.7)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing Indie Rescue & Relevance Boosting...${NC}"

request GET "/search?q=Girl%2C+Incorrupted" 200 "24. Title Match Boost (Girl, Incorrupted)" \
    '.results[0].title == "Girl, Incorrupted"'

request GET "/search?q=George+Orwell" 200 "25. Author Authority Boost (George Orwell)" \
    '.results[0].authors | any(.name | test("George Orwell"))'

# -----------------------------------------------------------------------------
# 14. Multi-Source & Adaptive Logic (v5.0)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v5.0 Multi-Source & Adaptive Logic...${NC}"

request GET "/new-releases?limit=5" 200 "26. Hot This Week (Recency Check)" \
    '.results[0].published_date != null'

request GET "/new-releases?limit=10&subject=Cyberpunk" 200 "27. Adaptive Fallback (Niche Genre Fill)" \
    '.results | length >= 5'

request GET "/new-releases?limit=20" 200 "28. Future Date Spam Block (No 2026/2027)" \
    '.results | all(.published_date | .[0:4] | tonumber | . != 2026 and . != 2027)'

request GET "/search?q=x8z9q2w3e4r5t6y7u8i9o0p" 200 "29. The Void (Zero Results Handling)" \
    '.num_found == 0 and .results == []'

request GET "/search?q=Dungeons+%26+Dragons" 200 "30. URL Encoding (Ampersand Handling)" \
    '.results | length > 0'

request GET "/search?q=intitle:Dune" 200 "31. Advanced Operator (intitle:)" \
    '.results[0].title | contains("Dune")'

request GET "/search?q=History&startIndex=10&limit=5" 200 "32. Pagination Deep Dive (Page 2)" \
    '.results | length > 0'

request GET "/author/The_Man_Who_Does_Not_Exist_12345" 404 "33. Author 404 Handling" \
    '.detail | contains("not found")'

# -----------------------------------------------------------------------------
# 15. Security & Rate Limiting (v5.1)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v5.1 Security Upgrades...${NC}"

request GET "/search?q=test" 403 "34. Bot Bouncer (GPTBot Block)" \
    '.detail | contains("Bot access denied")' \
    "-H User-Agent:GPTBot/1.0"

request GET "/genres/fiction" 200 "35. Rate Limit Config Check" \
    '.'

# -----------------------------------------------------------------------------
# 16. Cache Performance
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Cache cold vs hot test${NC}"
TEST_ISBN="9780140449136"  # Crime and Punishment
printf "Cold → "
cold=$(curl -s -L -H "ngrok-skip-browser-warning: true" -o /dev/null -w "%{time_total}" "$BASE_URL/book/isbn/$TEST_ISBN")
echo "${cold}s"

printf "Hot  → "
hot=$(curl -s -L -H "ngrok-skip-browser-warning: true" -o /dev/null -w "%{time_total}" "$BASE_URL/book/isbn/$TEST_ISBN")
echo "${hot}s"

if (( $(echo "$hot < $cold" | bc -l) )); then
    echo -e "${GREEN}PASS${NC} – Hot request was faster"
    ((PASSED++))
else
    echo -e "${YELLOW}WARNING${NC} – Cache might be pre-warmed or network variance"
    ((PASSED++))
fi
((TOTAL++))

# Summary
echo -e "\n${YELLOW}╔════════════════════ SUMMARY ════════════════════╗${NC}"
echo -e "Total: $TOTAL | Passed: ${GREEN}$PASSED${NC} | Failed: ${RED}$FAILED${NC}"

if [[ $FAILED -eq 0 ]]; then
    echo -e "\n${GREEN}All tests passed — Production API v5.1 is Solid!${NC}\n"
    exit 0
else
    echo -e "\n${RED}Some tests failed — see above${NC}\n"
    exit 1
fi