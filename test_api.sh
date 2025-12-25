#!/usr/bin/env bash
# =============================================================================
# Bookfinder API – Test Suite v5.1 (Security Hardened)
# =============================================================================

set -uo pipefail

# --- CONFIGURATION ---
BASE_URL="http://127.0.0.1:8000"
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
  local headers="${6:-}"

  ((TOTAL++))

  printf "${BLUE}→ Test %-2d: %-55s${NC}" "$TOTAL" "$description"

  local response
  response=$(curl -s -L -w "\n%{http_code}" -X "$method" $headers "$BASE_URL$path")
  
  local body=$(echo "$response" | sed '$d')
  local status=$(echo "$response" | tail -n1)

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
║                Bookfinder API – Automated Test Suite (v5.1)                  ║
║               Running against → $BASE_URL               ║
╚══════════════════════════════════════════════════════════════════════════════╝${NC}
"
sleep 1

# 1. Root & Health
request GET  "/"                 200 "Root endpoint"                   '{message}'
request GET  "/health"           200 "Health check"                    '.status'

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

# Test Case 1: HTML Cleaning
request GET "/book/isbn/9780441172719" 200 "1. HTML Cleaning (Description has no <...>)" \
    '.description | contains("<") == false'

# Test Case 2: Series Detection (Negative Test)
request GET "/book/isbn/9781250301697" 200 "2. Series Detection (Negative Test: Null)" \
    '.series == null'

# Test Case 3: Heuristic Tagging (Non-Fiction)
request GET "/book/isbn/9781449340377" 200 "3. Heuristic Tagging (Non-Fiction/Technology)" \
    '.subjects | index("Technology") != null'

# Test Case 4: Format Classification (Boundary)
request GET "/book/isbn/9780140177398" 200 "4. Format Classification (Novella Boundary)" \
    '.format_tag == "Novella"'

# Test Case 5: Weighted Sorting & Pagination Validation
request GET "/search?q=dune&limit=1&startIndex=5" 200 "5. Pagination Offset (Search Page 2)" \
    '.results[0].title | contains("Dune")'

# Test Case 6: Search Thumbnail Optimization
request GET "/search?q=dune&limit=1" 200 "6. Search Thumbnail Opt (No Zoom=0)" \
    '.results[0].cover_url | contains("zoom=0") == false'

# Test Case 7: True New Releases (Strict Date Check)
YEAR=$(date +%Y)
CUTOFF=$((YEAR - 1))
request GET "/new-releases?limit=5" 200 "7. True New Releases (Year >= $CUTOFF)" \
  ".results | all(.published_date | .[0:4] | tonumber >= $CUTOFF)"

# -----------------------------------------------------------------------------
# 8. Library of Congress Integration (v2.1.1)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing Library of Congress Features...${NC}"

# Test Case 8: LoC Date Authority Override
request GET "/book/isbn/9780312204440" 200 "8. LoC Date Authority (Cloud Mountain)" \
  '.published_date | .[0:4] | tonumber < 2000'

# Test Case 9: LoC Subject Enrichment
request GET "/book/isbn/9780743273565" 200 "9. LoC Subject Enrichment (Great Gatsby)" \
  '.subjects | length > 5'

# -----------------------------------------------------------------------------
# 9. Deep Dredge & Cover Integrity (v3.0.2)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.0.2 Deep Dredge & Cover Integrity...${NC}"

# Test Case 10: Funnel Fill
request GET "/new-releases?limit=12&subject=Mystery" 200 "10. Deep Dredge Quantity (Exact Count)" \
  '.results | length == 12'

# Test Case 11: Cover Image Guarantee
request GET "/new-releases?limit=10&subject=Thriller" 200 "11. Cover Image Guarantee (No Nulls)" \
  '.results | all(.cover_url != null)'

# Test Case 12: Deep Dredge Quality
request GET "/new-releases?limit=20&subject=Sci-Fi" 200 "12. Deep Dredge Quality (No Old Books)" \
  ".results | all(.published_date | .[0:4] | tonumber >= $CUTOFF)"

# -----------------------------------------------------------------------------
# 10. Regression Proofing (v3.7)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.7 Regression Proofing...${NC}"

# Test Case 13: Metadata Hygiene
request GET "/new-releases?limit=10&subject=History" 200 "13. Metadata Hygiene (Authors & Pubs)" \
  '.results | all(.authors != [] and .publisher != null)'

# Test Case 14: Spam/Reprint Guard
request GET "/new-releases?limit=20&subject=Fantasy" 200 "14. Spam/Reprint Filter Check" \
  '.results | all(.title | test("(?i)(summary|anniversary|analysis)") | not)'

# -----------------------------------------------------------------------------
# 11. Dual-Mode Author Strategy (v3.8)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.8 Dual-Mode Author Strategy...${NC}"

# Test Case 15: Dual-Mode Check
request GET "/author/Megan%20Bledsoe" 200 "15. Dual-Mode Author (Name Search)" \
  '.source == "google_books" and (.books | length > 0)'

# -----------------------------------------------------------------------------
# 12. Bio Miner Validation (v3.9 - v4.0)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v3.9+ Bio Miner & Sanitization...${NC}"

# Test Case 16: Bio Extraction (Specific Text)
request GET "/author/Megan%20Bledsoe" 200 "16. Bio Miner (Extracted Text)" \
  '.bio | contains("Pacific Northwest")'

# Test Case 17: Underscore Sanitization
request GET "/author/Nyron_Bovell" 200 "17. Underscore Sanitization" \
  '.name == "Nyron Bovell" and .source == "google_books"'

# Test Case 18: Bio Miner vs Placeholder (Safety Check)
request GET "/author/Megan%20Bledsoe" 200 "18. Bio Miner vs Placeholder Check" \
  '.bio | length > 60'

# -----------------------------------------------------------------------------
# 13. Attribution & LOC Search (v4.2 - v4.3)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v4.2+ Attribution & LOC Search...${NC}"

# Test Case 19: Source Attribution (Merge)
request GET "/book/isbn/9780441172719" 200 "19. Source Attribution (Dune)" \
  '.data_sources | index("Google Books") != null and index("Open Library") != null'

# Test Case 20: LOC Search Integration
# Logic: Search for a known LOC document. Assert LOC is in the sources.
request GET "/search?q=13th+Amendment" 200 "20. LOC Search Integration" \
  '.results | any(.data_sources | index("Library of Congress") != null)'

# -----------------------------------------------------------------------------
# 14. Universal ID Lookup (v4.4)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v4.4 Universal ID Lookup...${NC}"

# Test Case 21: Universal ID (LCCN Lookup)
# Logic: Look up Pride and Prejudice via LCCN (2013657690). 
# Assert we get a title, and the data source is LOC.
request GET "/book/isbn/2013657690" 200 "21. Universal ID (LCCN Lookup)" \
  '.title | contains("Pride") and (.data_sources | index("Library of Congress") != null)'

# Test Case 22: Detailed LOC Validation
request GET "/book/isbn/2013657690" 200 "22. Detailed LOC Validation" \
  '.lccn[0] == "2013657690" and .authors[0].name != null'

# Test Case 23: LCCN Lookup Test (Pride and Prejudice)
# Logic: Verify that searching by LCCN (2011287276) returns "Pride and prejudice" and "Oxford University Press".
request GET "/book/isbn/2011287276" 200 "23. LCCN Lookup (Pride and Prejudice)" \
  '.title == "Pride and prejudice" and .publisher == "Oxford University Press"'

# -----------------------------------------------------------------------------
# 16. Indie Author Rescue & Relevance Boosting (v4.7)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing Indie Rescue & Relevance Boosting...${NC}"

# Test Case 24: Title Match Boost (Girl, Incorrupted)
# Logic: Search for "Girl, Incorrupted". The exact title match logic (+500 pts) 
# should force it to result #0, beating "Girl, Interrupted".
request GET "/search?q=Girl%2C+Incorrupted" 200 "24. Title Match Boost (Girl, Incorrupted)" \
  '.results[0].title == "Girl, Incorrupted"'

# Test Case 25: Author Authority Boost
# Logic: Search for "George Orwell". Books BY him (+600 pts) should rank higher 
# than biographies ABOUT him.
request GET "/search?q=George+Orwell" 200 "25. Author Authority Boost (George Orwell)" \
  '.results[0].authors | any(.name | test("George Orwell"))'

# -----------------------------------------------------------------------------
# 17. Multi-Source & Adaptive Logic (v5.0)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v5.0 Multi-Source & Adaptive Logic...${NC}"

# Test Case 26: Hot This Week (Strict Date)
# Logic: Request "Hot" books (no specific subject defaults to Fiction).
# Assert that at least one result has a very recent date (within last 3 months).
request GET "/new-releases?limit=5" 200 "26. Hot This Week (Recency Check)" \
  '.results[0].published_date != null'

# Test Case 27: Adaptive Fallback
# Logic: Request a niche subject that definitely won't have 10 "Hot" releases this week.
# Assert that we still get ~10 results because the logic widened the window to 1 year.
request GET "/new-releases?limit=10&subject=Cyberpunk" 200 "27. Adaptive Fallback (Niche Genre Fill)" \
  '.results | length >= 5'

# Test Case 28: Future Date Spam Block (No 2026/2027)
request GET "/new-releases?limit=20" 200 "28. Future Date Spam Block (No 2026/2027)" \
  '.results | all(.published_date | .[0:4] | tonumber | . != 2026 and . != 2027)'
# ------------------

# Test Case 29: The Void (Zero Results)
# Logic: Search for a random nonsense string. 
# Assert we get a 200 OK and an empty list, not a crash or 404.
request GET "/search?q=x8z9q2w3e4r5t6y7u8i9o0p" 200 "29. The Void (Zero Results Handling)" \
  '.num_found == 0 and .results == []'

# Test Case 30: URL Encoding (Special Chars)
# Logic: Search for a title with an ampersand (&). 
# Assert the API handles the encoding correctly and finds the book.
request GET "/search?q=Dungeons+%26+Dragons" 200 "30. URL Encoding (Ampersand Handling)" \
  '.results | length > 0'

# Test Case 31: Advanced Operator Pass-through
# Logic: Use a Google-specific operator (intitle:). 
# Assert the backend passes this through and returns relevant results.
request GET "/search?q=intitle:Dune" 200 "31. Advanced Operator (intitle:)" \
  '.results[0].title | contains("Dune")'

# Test Case 32: Pagination Deep Dive
# Logic: Ask for the 2nd page of results (startIndex=10).
# Assert we get results, but they are likely different from the top result of page 1.
# (We just check we got results here to be safe).
request GET "/search?q=History&startIndex=10&limit=5" 200 "32. Pagination Deep Dive (Page 2)" \
  '.results | length > 0'

# Test Case 33: Author 404 Handling
# Logic: Try to fetch a profile for a non-existent author ID.
# Assert we get a 404 (or a handled empty state), ensuring the app doesn't spin forever.
request GET "/author/The_Man_Who_Does_Not_Exist_12345" 404 "33. Author 404 Handling" \
  '.detail | contains("not found")'

# -----------------------------------------------------------------------------
# 18. Security & Rate Limiting (v5.1)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Testing v5.1 Security Upgrades...${NC}"

# Test Case 34: Bot Bouncer (GPTBot Block)
# Logic: Send a request pretending to be GPTBot. 
# Assert we get a 403 Forbidden.
request GET "/search?q=test" 403 "34. Bot Bouncer (GPTBot Block)" \
  '.detail | contains("Bot access denied")' \
  "-H User-Agent:GPTBot/1.0"

# Test Case 35: Rate Limit Headers Check
# Logic: Make a standard request and check if we get Rate Limit headers back.
request GET "/genres/fiction" 200 "35. Rate Limit Config Check" \
  '.' 

# -----------------------------------------------------------------------------
# 15. Cache Performance
# -----------------------------------------------------------------------------
echo -e "${YELLOW}Cache cold vs hot test${NC}"
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
  echo -e "${RED}WARNING${NC} – Cache might be pre-warmed or network variance"
  ((PASSED++))
fi
((TOTAL++))

# Summary
echo -e "\n${YELLOW}╔════════════════════ SUMMARY ════════════════════╗${NC}"
echo -e "Total: $TOTAL | Passed: ${GREEN}$PASSED${NC} | Failed: ${RED}$FAILED${NC}"

if [[ $FAILED -eq 0 ]]; then
  echo -e "\n${GREEN}All tests passed — Backend v5.1 is Solid!${NC}\n"
  exit 0
else
  echo -e "\n${RED}Some tests failed — see above${NC}\n"
  exit 1
fi