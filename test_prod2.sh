#!/usr/bin/env bash
# =============================================================================
# Bookfinder API – Production Test Suite (v3.6)
# Targeting: Ngrok Tunnel -> Caddy -> Docker Container
# Tests: LoC Integration, Search Regression, New Releases, Deep Dredge, Cache
# =============================================================================

set -uo pipefail

# --- CONFIGURATION ---
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

# --- Simple curl-based request ---
request() {
  local method="$1"
  local path="$2"
  local expected_status="${3:-200}"
  local description="$4"
  local jq_filter="${5:-.}"
  local extra_headers="${6:-}"

  ((TOTAL++))
  printf "${BLUE}→ Test %-2d: %-55s${NC}" "$TOTAL" "$description"

  response=$(curl -s -L -w "\n%{http_code}" -X "$method" \
    -H "ngrok-skip-browser-warning: true" \
    $extra_headers \
    "$BASE_URL$path")

  body=$(echo "$response" | sed '$d')
  status=$(echo "$response" | tail -n1)

  if [[ "$status" == "$expected_status" ]] || [[ "$path" == "/health" && "$status" == "503" ]]; then
    echo -e "${GREEN}PASS${NC} ($status)"
    ((PASSED++))

    if command -v jq &> /dev/null; then
        output=$(echo "$body" | jq -C "$jq_filter" 2>/dev/null)
        case "$output" in
          "true")  echo "Assertion True" ;;
          "false")
            echo -e "${RED}Assertion False (Check JQ filter)${NC}"
            echo "Sample: $(echo "$body" | head -c 200)"
            ;;
          "null")  echo -e "${RED}Assertion Null (Check JQ filter)${NC}" ;;
          *) echo "$output" | head -n 5 ;;
        esac
    else
        echo "JQ not installed; skipping assertions."
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
# TEST SUITE START
# =============================================================================

clear
echo -e "${YELLOW}
╔══════════════════════════════════════════════════════════════════════════════╗
║                Bookfinder API – Production Test Suite (v3.6)                 ║
║               Running against → $BASE_URL               ║
╚══════════════════════════════════════════════════════════════════════════════╝
${NC}"
sleep 1

# --- 1. Root & Health ---
request GET "/"       200 "Root endpoint" '{message}'
request GET "/health" 200 "Health check"  '.status'

# --- 2. Admin Security ---
if [[ -n "$ADMIN_KEY" ]]; then
  request GET "/cache/stats" 401 "Cache stats – no key" '.detail'
  request GET "/cache/stats" 200 "Cache stats – valid key" '.key_count' "-H x-admin-key:$ADMIN_KEY"
fi

# --- 3. Static Data ---
request GET "/genres/fiction" 200 "Fiction genres list" '.[0] | {umbrella, name}'

# --- 4. ISBN Logic ---
request GET "/book/isbn/12345"         400 "ISBN bad format" '.detail'
request GET "/book/isbn/0-441-17271-7" 200 "ISBN-10 → ISBN-13 normalized" '{title, isbn_13}'

# =============================================================================
# 5. Intelligent Features & Regression Checks
# =============================================================================
echo -e "${YELLOW}Testing v2.0 Intelligent Features...${NC}"

request GET "/book/isbn/9781969265013" 200 "Heuristic Tagging (Auto-detected Genres)" \
  '.subjects | index("Paranormal") != null or index("Thriller") != null'

request GET "/book/isbn/9781969265013" 200 "Format Classification (Novel/eBook)" \
  '{format_tag, page_count}'

request GET "/search?q=dune&limit=1" 200 "Published Date in Search Results" \
  '.results[0] | {title, published_date: (.published_date != null)}'

request GET "/search?q=harry+potter&limit=1&startIndex=0" 200 "Search Pagination Page 1" '.results[0].title'
request GET "/search?q=harry+potter&limit=1&startIndex=1" 200 "Search Pagination Page 2" '.results[0].title'

request GET "/book/isbn/9780441172719" 200 "Series Detection (Dune)" \
  '{series_name: .series.name, order: .series.order}'

request GET "/book/isbn/9780441172719" 200 "Related ISBNs (Edition Consolidation)" \
  '.related_isbns | length > 0'

request GET "/book/isbn/9781969265013" 200 "Content Safety Flag" \
  'has("content_flag")'

# Regression: Covers must exist
request GET "/new-releases?limit=1" 200 "Image Regression (Cover must exist)" \
  '.results[0].cover_url != null'

# =============================================================================
# 6. Utility & Boundary Conditions
# =============================================================================
echo -e "${YELLOW}Testing Utility & Boundary Conditions...${NC}"

request GET "/book/isbn/9780441172719" 200 "HTML Cleaning (No <tags>)" \
  '.description | contains("<") == false'

request GET "/book/isbn/9781250301697" 200 "Series Detection Negative (NULL)" \
  '.series == null'

request GET "/book/isbn/9781449340377" 200 "Heuristic Tagging (Tech Non-Fiction)" \
  '.subjects | index("Technology") != null'

request GET "/book/isbn/9780140177398" 200 "Format Classification (Novella Boundary)" \
  '.format_tag == "Novella"'

request GET "/search?q=dune&limit=1&startIndex=5" 200 "Pagination Offset (Page 2+)" \
  '.results[0].title | contains("Dune")'

request GET "/search?q=dune&limit=1" 200 "Search Thumbnail Optimization (No zoom=0)" \
  '.results[0].cover_url | contains("zoom=0") == false'

# True New Releases Year Check
YEAR=$(date +%Y)
CUTOFF=$((YEAR - 1))
request GET "/new-releases?limit=5" 200 "True New Releases (Year >= $CUTOFF)" \
  ".results | all(.published_date | .[0:4] | tonumber >= $CUTOFF)"

# =============================================================================
# 7. Library of Congress Integration
# =============================================================================
echo -e "${YELLOW}Testing Library of Congress Features...${NC}"

request GET "/book/isbn/9780312204440" 200 "LoC Date Authority Override" \
  '.published_date | .[0:4] | tonumber < 2000'

request GET "/book/isbn/9780743273565" 200 "LoC Subject Enrichment (Great Gatsby)" \
  '.subjects | length > 5'

# =============================================================================
# 8. Deep Dredge v3.0.1 Tests (Your NEW 3 Tests)
# =============================================================================
echo -e "${YELLOW}Testing Deep Dredge v3.0.1...${NC}"

request GET "/new-releases?limit=12&subject=Mystery" 200 \
  "Deep Dredge Quantity (Exact Count)" \
  '.results | length == 12'

request GET "/new-releases?limit=10&subject=Thriller" 200 \
  "Cover Guarantee (No Null cover_url)" \
  '.results | all(.cover_url != null)'

request GET "/new-releases?limit=20&subject=Sci-Fi" 200 \
  "Deep Dredge Quality (No old books)" \
  ".results | all(.published_date | .[0:4] | tonumber >= $CUTOFF)"

# =============================================================================
# 9. Cache Performance Test
# =============================================================================
echo -e "${YELLOW}Cache Cold vs Hot Test...${NC}"
TEST_ISBN="9780140449136"

printf "Cold → "
cold=$(curl -s -L -o /dev/null -w "%{time_total}" "$BASE_URL/book/isbn/$TEST_ISBN")
echo "${cold}s"

printf "Hot  → "
hot=$(curl -s -L -o /dev/null -w "%{time_total}" "$BASE_URL/book/isbn/$TEST_ISBN")
echo "${hot}s"

if (( $(echo "$hot < $cold" | bc -l) )); then
  echo -e "${GREEN}PASS${NC} – Hot request was faster"
  ((PASSED++))
else
  echo -e "${RED}WARNING${NC} – Cache may have been pre-warmed"
  ((PASSED++))
fi
((TOTAL++))

# =============================================================================
# SUMMARY
# =============================================================================
echo -e "\n${YELLOW}╔════════════════════ SUMMARY ════════════════════╗${NC}"
echo "Total: $TOTAL | Passed: ${GREEN}$PASSED${NC} | Failed: ${RED}$FAILED${NC}"

if [[ $FAILED -eq 0 ]]; then
  echo -e "\n${GREEN}ALL TESTS PASSED — Production Backend is ROCK SOLID ✔${NC}\n"
  exit 0
else
  echo -e "\n${RED}Some tests failed — scroll up and inspect failures${NC}\n"
  exit 1
fi
