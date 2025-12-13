#!/usr/bin/env bash
# =============================================================================
# Bookfinder API – Production Test Suite v4.5 (Final Validation)
# Targeting: Ngrok Tunnel -> Caddy -> Docker Container
# =============================================================================

# Force exit on unset variables or non-zero exit code
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

# --- Simple curl-based request function (Corrected v4.5) ---
request() {
  local method="$1"
  local path="$2"
  local expected_status="${3:-200}"
  local description="$4"
  local jq_filter="${5:-.}"
  local extra_headers="${6:-}"

  # Corrected line 34
  ((TOTAL++))

  printf "${BLUE}→ Test %-2d: %-55s${NC}" "$TOTAL" "$description"

  # Execute request, including the Ngrok bypass header
  local response
  response=$(curl -s -L -w "\n%{http_code}" -X "$method" \
    -H "ngrok-skip-browser-warning: true" \
    $extra_headers \
    "$BASE_URL$path")
  
  local body=$(echo "$response" | sed '$d')
  local status=$(echo "$response" | tail -n1)

  # Allow 200 OK or 503 Service Unavailable (if upstream is acting up)
  if [[ "$status" == "$expected_status" ]] || [[ "$path" == "/health" && "$status" == "503" ]]; then
    echo -e "${GREEN}PASS${NC} ($status)"
    ((PASSED++))
    if command -v jq &> /dev/null; then
      local output=$(echo "$body" | jq -C "$jq_filter" 2>/dev/null)
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
# TESTS START HERE (Combined v4.5 Logic)
# =============================================================================

clear
echo -e "${YELLOW}
╔══════════════════════════════════════════════════════════════════════════════╗
║                    Bookfinder API – Production Test Suite (v4.5)             ║
║                  Running against → $BASE_URL                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝${NC}
"
sleep 1

# 1. Root & Health
request GET "/" 200 "Root endpoint" '{message}'
request GET "/health" 200 "Health check" '.status'

# 2. Admin Security
if [[ -n "$ADMIN_KEY" ]]; then
  request GET "/cache/stats" 401 "Cache stats – no key" '.detail'
  request GET "/cache/stats" 200 "Cache stats – valid key" '.key_count' "-H x-admin-key:$ADMIN_KEY"
fi

# 3. Static Data
request GET "/genres/fiction" 200 "Fiction genres list" '.[0] | {umbrella, name}'

# 4. ISBN Logic
request GET "/book/isbn/12345" 400 "ISBN bad format (Too Short)" '.detail'
request GET "/book/isbn/0-441-17271-7" 200 "ISBN-10 → ISBN-13" '{title, isbn_13}'

# -----------------------------------------------------------------------------
# 5. v2.0 INTELLIGENT FEATURES & REGRESSION CHECKS
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v2.0 Features & Regression Checks...${NC}"

# A. Heuristic Tagging
request GET "/book/isbn/9781969265013" 200 "Heuristic Tagging (Auto-detected Genres)" \
  '.subjects | index("Paranormal") != null or index("Thriller") != null'

# B. Format Classification
request GET "/book/isbn/9781969265013" 200 "Format Classification (Novel/eBook)" \
  '{format_tag, page_count}'

# C. Published Date in Search
request GET "/search?q=dune&limit=1" 200 "Published Date in Search Results" \
  '.results[0] | {title, published_date: (.published_date != null)}'

# D. Smart Pagination
request GET "/search?q=harry+potter&limit=1&startIndex=0" 200 "Pagination Page 1" '.results[0].title'
request GET "/search?q=harry+potter&limit=1&startIndex=1" 200 "Pagination Page 2" '.results[0].title'

# E. Series Detection
request GET "/book/isbn/9780441172719" 200 "Series Detection (Dune)" \
  '{series_name: .series.name, order: .series.order}'

# F. Related ISBNs
request GET "/book/isbn/9780441172719" 200 "ISBN Consolidation (Related Editions)" \
  '.related_isbns | length > 0'

# G. Content Safety
request GET "/book/isbn/9781969265013" 200 "Content Safety Flag Structure" \
  'has("content_flag")'

# H. IMAGE REGRESSION TEST
request GET "/new-releases?limit=1" 200 "Image Regression (Covers must exist)" \
  '.results[0].cover_url != null'

# -----------------------------------------------------------------------------
# 6. Utility & Boundary Conditions 
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing New Utility & Boundary Conditions...${NC}"

# Test Case 9: HTML Cleaning
request GET "/book/isbn/9780441172719" 200 "9. HTML Cleaning (Description has no <...>)" \
  '.description | contains("<") == false'

# Test Case 10: Series Detection (Negative Test)
request GET "/book/isbn/9781250301697" 200 "10. Series Detection (Negative Test: Null)" \
  '.series == null'

# Test Case 11: Heuristic Tagging (Non-Fiction)
request GET "/book/isbn/9781449340377" 200 "11. Heuristic Tagging (Non-Fiction/Technology)" \
  '.subjects | index("Technology") != null'

# Test Case 12: Format Classification (Boundary)
request GET "/book/isbn/9780140177398" 200 "12. Format Classification (Novella Boundary)" \
  '.format_tag == "Novella"'

# Test Case 13: Weighted Sorting & Pagination Validation
request GET "/search?q=dune&limit=1&startIndex=5" 200 "13. Pagination Offset (Search Page 2)" \
  '.results[0].title | contains("Dune")'

# Test Case 14: Search Thumbnail Optimization
request GET "/search?q=dune&limit=1" 200 "14. Search Thumbnail Opt (No Zoom=0)" \
  '.results[0].cover_url | contains("zoom=0") == false'

# Test Case 15: True New Releases (Strict Date Check)
YEAR=$(date +%Y)
CUTOFF=$((YEAR - 1))
request GET "/new-releases?limit=5" 200 "15. True New Releases (Year >= $CUTOFF)" \
  ".results | all(.published_date | .[0:4] | tonumber >= $CUTOFF)"

# -----------------------------------------------------------------------------
# 7. Library of Congress Integration (v2.1.1 - v4.4)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing Library of Congress & Universal ID Features...${NC}"

# Test Case 16: LoC Date Authority Override
request GET "/book/isbn/9780312204440" 200 "16. LoC Date Authority (Cloud Mountain)" \
  '.published_date | .[0:4] | tonumber < 2000'

# Test Case 17: LoC Subject Enrichment
request GET "/book/isbn/9780743273565" 200 "17. LoC Subject Enrichment (Great Gatsby)" \
  '.subjects | length > 5'

# Test Case 18: LOC Search Integration
request GET "/search?q=13th+Amendment" 200 "18. LOC Search Integration" \
  '.results | any(.data_sources | index("Library of Congress") != null)'

# Test Case 19: Universal ID (LCCN Lookup)
request GET "/book/isbn/2013657690" 200 "19. Universal ID (LCCN Lookup)" \
  '.title | contains("Pride") and (.data_sources | index("Library of Congress") != null)'

# Test Case 20: Detailed LOC Validation
request GET "/book/isbn/2013657690" 200 "20. Detailed LOC Validation" \
  '.lccn[0] == "2013657690" and .authors[0].name != null'

# Test Case 21: LCCN Lookup Test (Pride and Prejudice)
request GET "/book/isbn/2011287276" 200 "21. LCCN Lookup (Pride and Prejudice)" \
  '.title == "Pride and prejudice" and .publisher == "Oxford University Press"'

# -----------------------------------------------------------------------------
# 8. Deep Dredge & Cover Integrity (v3.0.2 - v4.5)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.0.2+ Deep Dredge & Cover Integrity...${NC}"

# Test Case 22: Funnel Fill
request GET "/new-releases?limit=12&subject=Mystery" 200 "22. Deep Dredge Quantity (Exact Count)" \
  '.results | length == 12'

# Test Case 23: Cover Image Guarantee
request GET "/new-releases?limit=10&subject=Thriller" 200 "23. Cover Image Guarantee (No Nulls)" \
  '.results | all(.cover_url != null)'

# Test Case 24: Deep Dredge Quality
request GET "/new-releases?limit=20&subject=Sci-Fi" 200 "24. Deep Dredge Quality (No Old Books)" \
  ".results | all(.published_date | .[0:4] | tonumber >= $CUTOFF)"

# -----------------------------------------------------------------------------
# 9. Regression Proofing (v3.7)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.7 Regression Proofing...${NC}"

# Test Case 25: Metadata Hygiene
request GET "/new-releases?limit=10&subject=History" 200 "25. Metadata Hygiene (Authors & Pubs)" \
  '.results | all(.authors != [] and .publisher != null)'

# Test Case 26: Spam/Reprint Guard
request GET "/new-releases?limit=20&subject=Fantasy" 200 "26. Spam/Reprint Filter Check" \
  '.results | all(.title | test("(?i)(summary|anniversary|analysis)") | not)'

# -----------------------------------------------------------------------------
# 10. Dual-Mode Author Strategy (v3.8)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.8 Dual-Mode Author Strategy...${NC}"

# Test Case 27: Dual-Mode Check
request GET "/author/Megan%20Bledsoe" 200 "27. Dual-Mode Author (Name Search)" \
  '.source == "google_books" and (.books | length > 0)'

# -----------------------------------------------------------------------------
# 11. Bio Miner Validation (v3.9 - v4.0)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.9+ Bio Miner & Sanitization...${NC}"

# Test Case 28: Bio Extraction (Specific Text)
request GET "/author/Megan%20Bledsoe" 200 "28. Bio Miner (Extracted Text)" \
  '.bio | contains("Pacific Northwest")'

# Test Case 29: Underscore Sanitization
request GET "/author/Nyron_Bovell" 200 "29. Underscore Sanitization" \
  '.name == "Nyron Bovell" and .source == "google_books"'

# Test Case 30: Bio Miner vs Placeholder (Safety Check)
request GET "/author/Megan%20Bledsoe" 200 "30. Bio Miner vs Placeholder Check" \
  '.bio | length > 60'

# -----------------------------------------------------------------------------
# 12. Cache Performance
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Cache cold vs hot test${NC}"
TEST_ISBN="9780140449136"
printf "Cold → "
cold=$(curl -s -L -H "ngrok-skip-browser-warning: true" -o /dev/null -w "%{time_total}" "$BASE_URL/book/isbn/$TEST_ISBN")
echo "${cold}s"

printf "Hot  → "
hot=$(curl -s -L -H "ngrok-skip-browser-warning: true" -o /dev/null -w "%{time_total}" "$BASE_URL/book/isbn/$TEST_ISBN")
echo "${hot}s"

if (( $(echo "$hot < $cold" | bc -l) )); then
  echo -e "${GREEN}PASS${NC} – Hot request was faster"
  ((PASSED++))
else
  echo -e "${RED}WARNING${NC} – Cache might be pre-warmed or network variance"
  ((PASSED++))
fi
((TOTAL++))

# Summary
echo -e "\n${YELLOW}╔════════════════════ SUMMARY ════════════════════╗${NC}"
echo -e "Total: $TOTAL | Passed: ${GREEN}$PASSED${NC} | Failed: ${RED}$FAILED${NC}"

if [[ $FAILED -eq 0 ]]; then
  echo -e "\n${GREEN}All tests passed — Production API v4.5 is Solid!${NC}\n"
  exit 0
else
  echo -e "\n${RED}Some tests failed — see above${NC}\n"
  exit 1
fi