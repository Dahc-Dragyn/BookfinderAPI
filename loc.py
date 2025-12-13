import httpx
import re
from typing import Optional, List, Dict, Any
from loguru import logger

# --- CONFIGURATION ---
# Base for specific book lookups
LOC_BOOK_API_BASE = "https://www.loc.gov/books"
# Base for general searches (manuscripts, legislation, etc.)
LOC_SEARCH_API_BASE = "https://www.loc.gov/search"
# Base for direct item retrieval (The Fix for LCCNs)
LOC_ITEM_API_BASE = "https://www.loc.gov/item"

# HEADERS: Critical for avoiding 403/404 blocks from government APIs
HEADERS = {
    "User-Agent": "Bookfinder/4.0 (educational-research-tool; contact@example.com)",
    "Accept": "application/json"
}

async def get_loc_data_by_isbn(isbn: str) -> Dict[str, Any]:
    """
    Fetches bibliographic data from the Library of Congress API using ISBN.
    """
    params = {
        "q": f"isbn:{isbn}",
        "fo": "json",
        "at": "results,pagination"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(LOC_BOOK_API_BASE, params=params, headers=HEADERS, timeout=10.0)
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            data = resp.json()
            
            results = data.get("results", [])
            if not results:
                return {}
            
            # Use the first result (most relevant)
            item = results[0]
            return _normalize_loc_item(item)
            
    except Exception as e:
        logger.warning(f"LoC API error for ISBN {isbn}: {e}")
        return {}

# --- NEW: Specific Lookup by LCCN (Item Endpoint Strategy) ---
async def get_loc_data_by_lccn(lccn: str) -> Dict[str, Any]:
    """
    Fetches bibliographic data using the Direct Item Endpoint.
    URL: https://www.loc.gov/item/{lccn}/?fo=json
    This is much more reliable than the search endpoint for specific IDs.
    """
    # Clean the LCCN just in case (remove whitespace)
    clean_lccn = lccn.strip()
    url = f"{LOC_ITEM_API_BASE}/{clean_lccn}/"
    params = {"fo": "json"}
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers=HEADERS, timeout=10.0)
            
            # If the ID doesn't exist, LOC returns 404
            if resp.status_code == 404:
                logger.info(f"LOC: Item {clean_lccn} not found (404).")
                return {}
                
            resp.raise_for_status()
            data = resp.json()
            
            # The Item Endpoint structure is different. 
            # The data is inside "item" dict, not a "results" list.
            item_data = data.get("item", {})
            if not item_data:
                logger.warning(f"LOC: Item {clean_lccn} returned valid JSON but no 'item' field.")
                return {}
            
            return _normalize_loc_item(item_data)
            
    except Exception as e:
        logger.error(f"Error fetching LOC Item {lccn}: {e}")
        return {}

# --- General Search Function for Researchers ---
async def search_loc(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Performs a general search on the Library of Congress (Documents, Legislation, etc).
    Useful for 'Primary Source' searches where ISBNs don't exist.
    """
    params = {
        "q": query,
        "fo": "json",
        "c": limit, # Count limit
        "at": "results" # Minimal response
    }

    try:
        async with httpx.AsyncClient() as client:
            # We use the General Search endpoint here, not just /books
            resp = await client.get(LOC_SEARCH_API_BASE, params=params, headers=HEADERS, timeout=10.0)
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            results = data.get("results", [])
            
            normalized_results = []
            for item in results:
                # We skip items that are just web pages about the library
                if "web page" in item.get("original_format", []):
                    continue
                    
                normalized = _normalize_loc_item(item)
                # Mark as a "Primary Source" so the frontend can show a special badge
                normalized["is_primary_source"] = True 
                normalized_results.append(normalized)
                
            return normalized_results

    except Exception as e:
        logger.error(f"LoC Search error: {e}")
        return []

def _normalize_loc_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts useful metadata from the raw LoC response.
    Handles both 'Search' results (lists) and 'Item' results (dicts).
    """
    # 1. Extract Date
    raw_date = item.get("date", "")
    clean_date = _clean_loc_date(raw_date)
    
    # 2. Extract Edition
    edition = item.get("edition", None)
    if isinstance(edition, list):
        edition = edition[0] if edition else None

    # 3. Extract Subjects
    subjects = item.get("subject", [])
    if isinstance(subjects, str):
        subjects = [subjects]
        
    # 4. Extract Description
    description = ""
    # Check 'summary' first (common in Item endpoint), then 'description'
    raw_desc = item.get("summary") or item.get("description")
    
    if raw_desc and isinstance(raw_desc, list):
        description = " ".join(raw_desc)
    elif isinstance(raw_desc, str):
        description = raw_desc

    # 5. Extract Authors/Contributors
    authors = []
    # Item endpoint uses "contributor_names" or "contributors"
    contributors = item.get("contributor_names") or item.get("contributor") or []
    
    if contributors:
        # Normalize list if it contains dicts (Item endpoint sometimes does this)
        for c in contributors[:3]:
            if isinstance(c, str):
                authors.append({"name": c})
            elif isinstance(c, dict):
                # Sometimes it's a dict like {"name": "..."}
                name = c.get("name") or list(c.keys())[0] # Fallback for odd LOC structures
                if name: authors.append({"name": name})

    # 6. Extract Link (The "Read Online" link)
    loc_url = item.get("id") or item.get("url")
    if isinstance(loc_url, list): loc_url = loc_url[0] # Item endpoint might return list

    # 7. Extract LCCN (Critical for lookup)
    lccn = item.get("lccn") or item.get("library_of_congress_control_number")
    # Ensure LCCN is a list of strings
    if isinstance(lccn, str): lccn = [lccn]
    elif not lccn: lccn = []

    return {
        "title": item.get("title", "Untitled Document"),
        "authors": authors,
        "published_date": clean_date,
        "publisher": item.get("publisher"), 
        "edition": edition,
        "subjects": subjects,
        "description": description,
        "lccn": lccn, 
        "call_number": item.get("call_number"),
        "loc_url": loc_url, # Link to the item on loc.gov
        "format": item.get("original_format", ["Unknown"])[0] # e.g. "Manuscript/Mixed Material"
    }

def _clean_loc_date(date_str: str) -> Optional[str]:
    """
    Normalizes messy library date formats.
    """
    if not date_str:
        return None
    # Extract the first 4-digit year found
    match = re.search(r"(\d{4})", str(date_str))
    if match:
        return match.group(1)
    return None