import httpx
import re
from typing import Optional, List, Dict, Any
from loguru import logger

LOC_API_BASE = "https://www.loc.gov/books"

async def get_loc_data_by_isbn(isbn: str) -> Dict[str, Any]:
    """
    Fetches bibliographic data from the Library of Congress API.
    Returns a normalized dictionary or empty dict if not found.
    """
    params = {
        "q": f"isbn:{isbn}",
        "fo": "json",
        "at": "results,pagination"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(LOC_API_BASE, params=params, timeout=8.0)
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
            
    except httpx.HTTPError as e:
        logger.warning(f"LoC API error for ISBN {isbn}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error fetching LoC data: {e}")
        return {}

def _normalize_loc_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts useful metadata from the raw LoC response.
    """
    # 1. Extract Date (The most critical field)
    # LoC dates can be "1998", "c1998", "[1998]", "1998-05-01"
    raw_date = item.get("date", "")
    clean_date = _clean_loc_date(raw_date)
    
    # 2. Extract Edition (e.g., "1st ed.")
    edition = item.get("edition", None)
    if isinstance(edition, list):
        edition = edition[0] if edition else None

    # 3. Extract Subjects
    subjects = item.get("subject", [])
    if isinstance(subjects, str):
        subjects = [subjects]
        
    # 4. Extract Description/Summary
    description = ""
    # LoC descriptions are often buried in 'description' or 'summary' lists
    raw_desc = item.get("description") or item.get("summary")
    if raw_desc and isinstance(raw_desc, list):
        description = " ".join(raw_desc)
    elif isinstance(raw_desc, str):
        description = raw_desc

    return {
        "title": item.get("title"),
        "contributors": item.get("contributor", []),
        "published_date": clean_date,
        "publisher": item.get("publisher"), # LoC usually returns a list/string for 'created_published'
        "edition": edition,
        "subjects": subjects,
        "description": description,
        "lccn": item.get("lccn"), # Library of Congress Control Number
        "call_number": item.get("call_number") # e.g., "PS3562.I783 C55 1998"
    }

def _clean_loc_date(date_str: str) -> Optional[str]:
    """
    Normalizes messy library date formats.
    c1998 -> 1998
    [1998] -> 1998
    1998? -> 1998
    199- -> None (Reject ambiguous decades)
    """
    if not date_str:
        return None
        
    # Extract the first 4-digit year found
    match = re.search(r"(\d{4})", date_str)
    if match:
        return match.group(1)
        
    return None