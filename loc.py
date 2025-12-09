import httpx
import re
from typing import Optional, List, Dict, Any
from loguru import logger

# Base for specific book lookups
LOC_BOOK_API_BASE = "https://www.loc.gov/books"
# Base for general searches
LOC_SEARCH_API_BASE = "https://www.loc.gov/search"
# Base for direct item retrieval (The Fix)
LOC_ITEM_API_BASE = "https://www.loc.gov/item"

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
            resp = await client.get(LOC_BOOK_API_BASE, params=params, timeout=8.0)
            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            data = resp.json()
            
            results = data.get("results", [])
            if not results:
                return {}
            
            item = results[0]
            return _normalize_loc_item(item)
            
    except httpx.HTTPError as e:
        logger.warning(f"LoC API error for ISBN {isbn}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error fetching LoC data: {e}")
        return {}

# --- UPDATED: Specific Lookup by LCCN (Item Endpoint Strategy) ---
async def get_loc_data_by_lccn(lccn: str) -> Dict[str, Any]:
    """
    Fetches data using the Direct Item Endpoint.
    URL: https://www.loc.gov/item/{lccn}/?fo=json
    This is much more reliable than the search endpoint for specific IDs.
    """
    url = f"{LOC_ITEM_API_BASE}/{lccn}/"
    params = {"fo": "json"}
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=8.0)
            
            # If the ID doesn't exist, LOC returns 404
            if resp.status_code == 404:
                return {}
                
            resp.raise_for_status()
            data = resp.json()
            
            # The Item Endpoint structure is different. 
            # The data is inside "item" dict, not a "results" list.
            item_data = data.get("item", {})
            if not item_data:
                return {}
            
            return _normalize_loc_item(item_data)
            
    except httpx.HTTPError as e:
        logger.warning(f"LoC Item API error for LCCN {lccn}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error fetching LoC Item data: {e}")
        return {}

# --- General Search Function for Researchers ---
async def search_loc(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Performs a general search on the Library of Congress.
    """
    params = {
        "q": query,
        "fo": "json",
        "c": limit,
        "at": "results"
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(LOC_SEARCH_API_BASE, params=params, timeout=10.0)
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            results = data.get("results", [])
            
            normalized_results = []
            for item in results:
                if "web page" in item.get("original_format", []):
                    continue
                    
                normalized = _normalize_loc_item(item)
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

    # 6. Extract Link
    loc_url = item.get("id") or item.get("url")
    if isinstance(loc_url, list): loc_url = loc_url[0] # Item endpoint might return list

    # 7. Extract LCCN (Critical for lookup)
    lccn = item.get("lccn") or item.get("library_of_congress_control_number")
    if isinstance(lccn, list): lccn = lccn[0]

    return {
        "title": item.get("title", "Untitled Document"),
        "authors": authors,
        "published_date": clean_date,
        "publisher": item.get("publisher"), 
        "edition": edition,
        "subjects": subjects,
        "description": description,
        "lccn": [lccn] if lccn else [], 
        "call_number": item.get("call_number"),
        "loc_url": loc_url,
        "format": item.get("original_format", ["Unknown"])[0] 
    }

def _clean_loc_date(date_str: str) -> Optional[str]:
    """
    Normalizes messy library date formats.
    """
    if not date_str:
        return None
    match = re.search(r"(\d{4})", str(date_str))
    if match:
        return match.group(1)
    return None