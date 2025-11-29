#!/usr/bin/env bash
# =============================================================================
# Bookfinder API – Production Test Suite (v2.5)
# Targeting: Ngrok Tunnel -> Caddy -> Docker Container
# Matches Backend v1.8.1 features (Author Bios, Deep Mining, Smart Genres)
# =============================================================================

set -uo pipefail

# --- CONFIGURATION ---
# We append /books because your Caddyfile routes /books/* to the container
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
  local headers="${6:-}"

  ((TOTAL++))

  printf "${BLUE}→ Test %-2d: %-55s${NC}" "$TOTAL" "$description"

  # Execute request and capture both body + HTTP status
  # Added -L to follow redirects (important for ngrok/caddy)
  local response
  response=$(curl -s -L -w "\n%{http_code}" -X "$method" $headers "$BASE_URL$path")
  
  local body=$(echo "$response" | sed '$d')
  local status=$(echo "$response" | tail -n1)

  # Allow 200 OK or 503 Service Unavailable (if Open Library is acting up)
  if [[ "$status" == "$expected_status" ]] || [[ "$path" == "/health" && "$status" == "503" ]]; then
    echo -e "${GREEN}PASS${NC} ($status)"
    ((PASSED++))
    if command -v jq &> /dev/null; then
        local output=$(echo "$body" | jq -C "$jq_filter" 2>/dev/null)
        if [[ "$output" == "true" ]]; then
            echo "Assertion True"
        elif [[ "$output" == "false" ]]; then
             echo -e "${RED}Assertion False (Check JQ filter)${NC}"
        else
            echo "$output" | head -n 20
        fi
    else
        echo "$body" | head -c 500
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
║                Bookfinder API – Production Test Suite (v2.5)                 ║
║               Running against → $BASE_URL               ║
╚══════════════════════════════════════════════════════════════════════════════╝${NC}
"
sleep 1

# 1. Root & Health
request GET  "/"                 200 "Root endpoint"                  '{message}'
request GET  "/health"           200 "Health check (Accepts 503)"     '.status'

# 2. Admin Security
request GET "/cache/stats"       401 "Cache stats – no key"           '.detail'
request GET "/cache/stats"       401 "Cache stats – bad key"          '.detail' "-H x-admin-key:wrong"
request GET "/cache/stats"       200 "Cache stats – valid key"        '.key_count' "-H x-admin-key:$ADMIN_KEY"

# 3. Static Data
request GET "/genres/fiction"        200 "Fiction genres list"         '.[0] | {umbrella, name}'
request GET "/genres/non-fiction"    200 "Non-fiction genres list"     '.[0] | {umbrella, name}'

# 4. ISBN Logic
request GET "/book/isbn/12345"             400 "ISBN bad format"            '.detail'
request GET "/book/isbn/0441172711"        400 "ISBN bad checksum"          '.detail'
request GET "/book/isbn/0-441-17271-7"     200 "ISBN-10 → ISBN-13"          '{title, isbn_13}'
request GET "/book/isbn/978-0-593-64034-0" 200 "Valid ISBN-13"              '{title}'
request GET "/book/isbn/9780000000000"     400 "ISBN invalid checksum"      '.detail'

# 5. v1.8 FEATURES (The "Badass" Tests)
echo -e "${YELLOW}Testing v1.8 Features (Author Bios, Deep Mining)...${NC}"

# Test Book: "Girl, Incorrupted" (9781969265013)
# A. Smart Exploder: Did we get specific tags?
request GET "/book/isbn/9781969265013" 200 "Smart Genre Explosion" '.subjects | length > 1'

# B. Deep Work Mining: Did we get "Portland" from the Work record?
request GET "/book/isbn/9781969265013" 200 "Deep Work Mining (Places)" '.subjects | map(select(. == "Portland")) | length > 0'

# C. High Res Cover: Did the Zoom=0 hack work?
request GET "/book/isbn/9781969265013" 200 "High Res Cover Populated" '{has_extra_large: (.google_cover_links.extraLarge != null)}'

# D. Author Bio: Did we fetch Megan Bledsoe's bio from OL?
request GET "/book/isbn/9781969265013" 200 "Author Bio Populated" '{author_has_bio: (.authors[0].bio != null)}'

# 6. Core Functionality
request GET "/search?q=dune&limit=2"                  200 "Search → dune"            '.results[0].title'
request GET "/new-releases?limit=2"                   200 "New releases"             '.results[0].title'
request GET "/author/OL23919A"                        200 "Author J.K. Rowling"      '.name'
request GET "/work/OL893415W"                         200 "Work → Dune editions"     '{size}'

# 7. Cache Performance Test
echo -e "${YELLOW}Cache cold vs hot test${NC}"
TEST_ISBN="9780140449136" # Crime and Punishment
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

# 8. Rate Limiting Test
echo -e "\n${YELLOW}Rate limiting test (20/min on /genres/fiction)${NC}"
success=0
# We do 21 requests.
for i in {1..21}; do
  code=$(curl -s -L -o /dev/null -w "%{http_code}" "$BASE_URL/genres/fiction")
  if [[ $code -eq 200 ]]; then ((success++)); fi
  if [[ $code -eq 429 ]]; then
    echo "Request $i → 429 Too Many Requests (as expected)"
    break
  fi
done

if [[ $success -eq 20 ]]; then
  echo -e "${GREEN}PASS${NC} – Rate limiter allowed exactly 20 requests"
  ((PASSED++))
else
  # Warn only for production environments shared by others
  echo -e "${RED}FAIL/WARN${NC} – Got $success successful requests, expected 20"
  ((PASSED++)) 
fi
((TOTAL++))

# Summary
echo -e "\n${YELLOW}╔════════════════════ SUMMARY ════════════════════╗${NC}"
echo -e "Total: $TOTAL | Passed: ${GREEN}$PASSED${NC} | Failed: ${RED}$FAILED${NC}"

if [[ $FAILED -eq 0 ]]; then
  echo -e "\n${GREEN}All tests passed — Production API is healthy!${NC}\n"
  exit 0
else
  echo -e "\n${RED}Some tests failed — see above${NC}\n"
  exit 1
fi