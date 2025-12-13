# (v4.8.0) - Tri-Hybrid + Title Boosting + Indie Rescue + Ghost Book Filter
import os
import httpx
import asyncio
import json
import hashlib
import sys
import re
from datetime import datetime, timedelta # Added timedelta
from pathlib import Path
from fastapi import FastAPI, Query, HTTPException, Request, Depends, Path as FastAPIPath, Header, Response, status
from pydantic import BaseModel, Field, ValidationError
from dotenv import load_dotenv
from typing import List, Optional, Dict, Any
from redis.asyncio import Redis
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from loguru import logger
import fiction
import non_fiction
import loc 

# --------------------------------------------------------------------
# 1. Configuration & Setup
# --------------------------------------------------------------------

logger.remove()
logger.add(
    sys.stderr,
    serialize=True,
    enqueue=True,
    level="INFO",
    format="{time} {level} {message}",
)

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL, default_limits=["100/minute"])

app = FastAPI(
    title="Bookfinder Intelligent API",
    description="A robust, heuristic-driven book API with automated tagging, series detection, and deep mining.",
    version="4.8.0" 
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

API_KEY = os.getenv("GOOGLE_API_KEY")
ADMIN_KEY = os.getenv("ADMIN_KEY")
GOOGLE_BOOKS_API_URL = "https://www.googleapis.com/books/v1/volumes"
OPEN_LIBRARY_API_URL = "https://openlibrary.org"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"

# --- DATA HYGIENE: The Blacklist ---
TITLE_BLACKLIST = [
    "cloud mountain",
    "the great gatsby",
    "1984",
    "animal farm",
    "pride and prejudice",
    "the hobbit",
    "little women",
    "me before you", 
    "the dead zone"
]

try:
    cache = Redis.from_url(REDIS_URL, decode_responses=True, encoding="utf-8")
    logger.info("Redis cache connection established.")
except Exception as e:
    logger.error(f"Could not initialize Redis. Caching will be disabled. Error: {e}")
    cache = None

async def cached_get(
    url: str,
    params: dict,
    timeout_seconds: int = 3600 * 24 * 7 
) -> Any:
    filtered_params = {k: v for k, v in params.items() if v is not None}
    key = hashlib.sha256(f"{url}{sorted(filtered_params.items())}".encode()).hexdigest()

    if cache:
        try:
            cached_data = await cache.get(key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            logger.warning(f"Redis GET error: {e}", exc_info=True)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=filtered_params, timeout=20.0)
            if resp.status_code == 404: return {} 
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.error(f"HTTPX error for {e.request.url!r}: {e}")
        return {}

    if cache and data:
        try:
            await cache.setex(key, timeout_seconds, json.dumps(data))
        except Exception as e:
            logger.warning(f"Redis SET error: {e}", exc_info=True)

    return data


# --------------------------------------------------------------------
# 2. Pydantic Models
# --------------------------------------------------------------------

class GoogleCoverLinks(BaseModel):
    thumbnail: Optional[str] = None
    smallThumbnail: Optional[str] = None
    small: Optional[str] = None
    medium: Optional[str] = None
    large: Optional[str] = None
    extraLarge: Optional[str] = None

class OpenLibraryCoverLinks(BaseModel):
    small: str
    medium: str
    large: str

class Dimensions(BaseModel):
    height: Optional[str] = None
    width: Optional[str] = None
    thickness: Optional[str] = None

class Price(BaseModel):
    amount: Optional[float] = None
    currencyCode: Optional[str] = None

class SaleInfo(BaseModel):
    country: Optional[str] = None
    saleability: Optional[str] = None
    isEbook: bool = False
    buyLink: Optional[str] = None
    listPrice: Optional[Price] = None
    retailPrice: Optional[Price] = None

class AccessInfo(BaseModel):
    country: Optional[str] = None
    viewability: Optional[str] = None
    pdf: Optional[Dict[str, Any]] = None
    epub: Optional[Dict[str, Any]] = None
    webReaderLink: Optional[str] = None

class AuthorItem(BaseModel):
    name: str
    key: Optional[str] = None
    bio: Optional[str] = None 

class SeriesInfo(BaseModel):
    name: str
    order: Optional[int] = None

class MergedBook(BaseModel):
    title: str
    subtitle: Optional[str] = None
    authors: List[AuthorItem]
    isbn_13: str
    isbn_10: Optional[str] = None
    google_book_id: Optional[str] = None
    description: Optional[str] = None
    publisher: Optional[str] = None
    published_date: Optional[str] = None
    page_count: Optional[int] = None
    average_rating: Optional[float] = None
    ratings_count: Optional[int] = None
    dimensions: Optional[Dimensions] = None
    sale_info: Optional[SaleInfo] = None
    access_info: Optional[AccessInfo] = None
    google_cover_links: Optional[GoogleCoverLinks] = None
    open_library_id: Optional[str] = None
    subjects: List[str] = Field(default_factory=list)
    open_library_cover_links: Optional[OpenLibraryCoverLinks] = None
    series: Optional[SeriesInfo] = None
    format_tag: Optional[str] = None
    related_isbns: List[str] = Field(default_factory=list)
    content_flag: Optional[str] = None
    data_source: str = "hybrid"
    data_sources: List[str] = Field(default_factory=list)
    lccn: List[str] = Field(default_factory=list) 

class SearchResultItem(BaseModel):
    title: str
    subtitle: Optional[str] = None
    authors: List[AuthorItem] = Field(default_factory=list)
    isbn_13: Optional[str] = None
    isbn_10: Optional[str] = None
    publisher: Optional[str] = None 
    published_date: Optional[str] = None
    average_rating: Optional[float] = None
    ratings_count: Optional[int] = None
    categories: List[str] = Field(default_factory=list)
    google_book_id: Optional[str] = None
    open_library_work_id: Optional[str] = None
    cover_url: Optional[str] = None
    series: Optional[SeriesInfo] = None
    format_tag: Optional[str] = None
    description: Optional[str] = None
    data_sources: List[str] = Field(default_factory=list)
    lccn: List[str] = Field(default_factory=list)

class HybridSearchResponse(BaseModel):
    query: str
    subject: Optional[str] = None
    num_found: int
    results: List[SearchResultItem]

class NewReleasesResponse(BaseModel):
    subject: Optional[str] = None
    num_found: int
    results: List[SearchResultItem]

class AuthorPageData(BaseModel):
    key: str
    name: str
    bio: Optional[str] = None
    birth_date: Optional[str] = None
    death_date: Optional[str] = None
    photo_url: Optional[str] = None
    books: List[SearchResultItem] = Field(default_factory=list)
    source: str 

class AuthorBio(BaseModel):
    value: str

class AuthorDetails(BaseModel):
    key: str
    name: str
    bio: Optional[AuthorBio | str] = None
    birth_date: Optional[str] = None
    death_date: Optional[str] = None
    
class WorkEdition(BaseModel):
    key: str
    title: str
    publish_date: Optional[str] = None
    isbn_13: Optional[List[str]] = Field(default_factory=list)
    isbn_10: Optional[List[str]] = Field(default_factory=list)

class WorkEditionsResponse(BaseModel):
    key: str
    size: int
    entries: List[WorkEdition]

class ServiceHealth(BaseModel):
    name: str
    status: str
    detail: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    services: List[ServiceHealth]

class CacheStats(BaseModel):
    status: str
    key_count: int
    used_memory: str
    redis_url: str


# --------------------------------------------------------------------
# 3. Helper Functions & Heuristics
# --------------------------------------------------------------------

def ensure_https(url: Optional[str]) -> Optional[str]:
    if not url: return None
    secure_url = url.replace("http://", "https://")
    if "books.google.com" in secure_url:
        secure_url = secure_url.replace("&edge=curl", "")
    return secure_url

def generate_high_res_url(url: Optional[str]) -> Optional[str]:
    if not url: return None
    clean_url = ensure_https(url)
    if "zoom=1" in clean_url:
        return clean_url.replace("zoom=1", "zoom=0")
    return clean_url

def clean_html_text(text: Optional[str]) -> Optional[str]:
    if not text: return None
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = clean.replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")
    return re.sub(r'\s+', ' ', clean).strip()

def detect_series(title: str, subtitle: Optional[str]) -> Optional[SeriesInfo]:
    full_text = f"{title} {subtitle or ''}"
    patterns = [
        r"(?P<name>.+?),?\s+Book\s+(?P<order>\d+)",
        r"Book\s+(?P<order>\d+)\s+of\s+(?P<name>.+)",
        r"(?P<name>.+?)\s+Trilogy",
        r"(?P<name>.+?)\s+Series"
    ]
    
    for pat in patterns:
        match = re.search(pat, full_text, re.IGNORECASE)
        if match:
            groups = match.groupdict()
            order = int(groups['order']) if 'order' in groups else None
            name = groups['name'].strip()
            if len(name) > 50 or name.lower() in ["fiction", "novel", "edition"]: continue
            return SeriesInfo(name=name, order=order)
    return None

def classify_format(page_count: Optional[int], is_ebook: bool) -> str:
    if not page_count: return "Unknown Format"
    if page_count < 50: return "Short Story"
    if page_count < 150: return "Novella"
    if is_ebook: return "eBook"
    return "Novel"

def check_content_safety(description: Optional[str], categories: List[str]) -> Optional[str]:
    text = f"{description or ''} {' '.join(categories)}".lower()
    triggers = ["erotica", "explicit", "mature content", "dark romance", "sexual violence"]
    if any(t in text for t in triggers):
        return "Mature Content"
    return None

def heuristic_tagging(text: str, existing_tags: List[str]) -> List[str]:
    GENRE_KEYWORDS = {
        "vampire": "Paranormal", "werewolf": "Paranormal", "witch": "Fantasy",
        "space": "Sci-Fi", "alien": "Sci-Fi", "robot": "Sci-Fi", 
        "detective": "Mystery", "murder": "Mystery", "crime": "Mystery", "police": "Mystery",
        "spy": "Thriller", "espionage": "Thriller", "agent": "Thriller",
        "dragon": "Fantasy", "magic": "Fantasy", "wizard": "Fantasy", "kingdom": "Fantasy",
        "marriage": "Romance", "kiss": "Romance",
        "computer": "Technology", "ai": "Technology"
    }
    inferred_tags = set(existing_tags)
    lower_text = text.lower()
    for keyword, tag in GENRE_KEYWORDS.items():
        if keyword in lower_text:
            inferred_tags.add(tag)
    return sorted(list(inferred_tags))

def _process_rich_categories(raw_categories: List[Any]) -> List[str]:
    if not raw_categories: return []
    unique_tags = set()
    stop_words = {"general", "electronic books", "books", "juvenile fiction", "young adult fiction"}
    
    for cat in raw_categories:
        if isinstance(cat, dict): cat_str = cat.get("name", "")
        elif isinstance(cat, str): cat_str = cat
        else: continue

        if not cat_str: continue
        parts = re.split(r'[\/]+|--', cat_str)
        
        for part in parts:
            clean = part.strip()
            if not clean: continue
            if clean.lower() in stop_words: continue
            unique_tags.add(clean)

    return sorted(list(unique_tags))

async def get_admin_key(x_admin_key: str = Header(None)):
    if not ADMIN_KEY: raise HTTPException(status_code=500, detail="Admin not configured.")
    if x_admin_key != ADMIN_KEY: raise HTTPException(status_code=401, detail="Invalid key.")
    return True

def _is_valid_isbn10_checksum(isbn: str) -> bool:
    if len(isbn) != 10 or not isbn[:-1].isdigit(): return False
    total = sum(int(isbn[i]) * (10 - i) for i in range(9))
    check_digit = isbn[-1].upper()
    if check_digit == 'X': total += 10
    elif check_digit.isdigit(): total += int(check_digit)
    else: return False
    return total % 11 == 0

def _is_valid_isbn13_checksum(isbn: str) -> bool:
    if len(isbn) != 13 or not isbn.isdigit(): return False
    total = 0
    for i in range(12):
        digit = int(isbn[i])
        total += digit * (1 if i % 2 == 0 else 3)
    check_digit = (10 - (total % 10)) % 10
    return check_digit == int(isbn[12])

def _convert_isbn10_to_isbn13(isbn10: str) -> str:
    base = f"978{isbn10[:-1]}"
    total = sum(int(base[i]) * (1 if i % 2 == 0 else 3) for i in range(12))
    check_digit = (10 - (total % 10)) % 10
    return f"{base}{check_digit}"

def validate_and_clean_isbn(isbn: str = FastAPIPath(...)) -> str:
    cleaned = re.sub(r"[\s-]+", "", isbn)
    if len(cleaned) == 13 and _is_valid_isbn13_checksum(cleaned): return cleaned
    if len(cleaned) == 10 and _is_valid_isbn10_checksum(cleaned): return _convert_isbn10_to_isbn13(cleaned)
    if cleaned.isdigit() and len(cleaned) >= 8: return cleaned 
    raise HTTPException(status_code=400, detail="Invalid ISBN or Identifier.")

def _get_isbns_from_google_item(item: Dict[str, Any]) -> (Optional[str], Optional[str]):
    isbn_13, isbn_10 = None, None
    for i in item.get("volumeInfo", {}).get("industryIdentifiers", []):
        if i.get("type") == "ISBN_13" and not isbn_13: isbn_13 = i.get("identifier")
        elif i.get("type") == "ISBN_10" and not isbn_10: isbn_10 = i.get("identifier")
    return isbn_13, isbn_10

def _get_isbns_from_ol_item(item: Dict[str, Any]) -> (Optional[str], Optional[str]):
    isbn_13, isbn_10 = None, None
    for isbn in item.get("isbn", []):
        if len(isbn) == 13 and not isbn_13: isbn_13 = isbn
        elif len(isbn) == 10 and not isbn_10: isbn_10 = isbn
    return isbn_13, isbn_10


# --- MAPPERS ---

def _google_item_to_search_result(item: Dict[str, Any]) -> SearchResultItem:
    g_info = item.get("volumeInfo", {})
    isbn_13, isbn_10 = _get_isbns_from_google_item(item)
    links = g_info.get("imageLinks", {})
    raw_thumbnail = ensure_https(links.get("thumbnail"))
    extra_large = ensure_https(links.get("extraLarge"))
    if not extra_large and raw_thumbnail: extra_large = generate_high_res_url(raw_thumbnail)
    large = ensure_https(links.get("large"))
    if not large and raw_thumbnail: large = generate_high_res_url(raw_thumbnail)

    g_covers = GoogleCoverLinks(
        thumbnail=raw_thumbnail,
        smallThumbnail=ensure_https(links.get("smallThumbnail")),
        small=ensure_https(links.get("small")),
        medium=ensure_https(links.get("medium")),
        large=large,
        extraLarge=extra_large
    )
    cover_url = g_covers.thumbnail or g_covers.smallThumbnail or g_covers.small or g_covers.medium
    if not cover_url:
        cover_id = isbn_13 if isbn_13 else isbn_10
        if cover_id: cover_url = f"https://covers.openlibrary.org/b/isbn/{cover_id}-M.jpg"

    raw_authors = g_info.get("authors", [])
    author_objects = [AuthorItem(name=a, key=None) for a in raw_authors]
    smart_cats = _process_rich_categories(g_info.get("categories", []))
    if len(smart_cats) < 2:
        desc_text = g_info.get("description", "") + " " + g_info.get("title", "")
        smart_cats = heuristic_tagging(desc_text, smart_cats)
    series = detect_series(g_info.get("title", ""), g_info.get("subtitle"))
    fmt = classify_format(g_info.get("pageCount"), item.get("saleInfo", {}).get("isEbook", False))

    return SearchResultItem(
        title=g_info.get("title", "No Title"),
        subtitle=g_info.get("subtitle"),
        authors=author_objects,
        isbn_13=isbn_13,
        isbn_10=isbn_10,
        publisher=g_info.get("publisher"),
        published_date=g_info.get("publishedDate"),
        average_rating=g_info.get("averageRating"),
        ratings_count=g_info.get("ratingsCount"),
        categories=smart_cats,
        google_book_id=item.get("id"),
        cover_url=cover_url,
        series=series,
        format_tag=fmt,
        description=g_info.get("description"),
        data_sources=["Google Books"] 
    )

def _ol_item_to_search_result(item: Dict[str, Any]) -> SearchResultItem:
    isbn_13, isbn_10 = _get_isbns_from_ol_item(item)
    raw_names = item.get("author_name", [])
    raw_keys = item.get("author_key", [])
    author_objects = []
    for i, name in enumerate(raw_names):
        key = raw_keys[i] if i < len(raw_keys) else None
        author_objects.append(AuthorItem(name=name, key=key))
    smart_cats = _process_rich_categories(item.get("subject", []))[:8]
    pub_date = str(item.get("first_publish_year")) if item.get("first_publish_year") else None
    cover_url = None
    if "cover_i" in item:
         cover_url = f"https://covers.openlibrary.org/b/id/{item['cover_i']}-M.jpg"
    return SearchResultItem(
        title=item.get("title", "No Title"),
        subtitle=item.get("subtitle"),
        authors=author_objects,
        isbn_13=isbn_13,
        isbn_10=isbn_10,
        publisher=item.get("publisher", [None])[0] if item.get("publisher") else None,
        published_date=pub_date,
        categories=smart_cats,
        open_library_work_id=item.get("key"),
        cover_url=cover_url,
        data_sources=["Open Library"]
    )

def _loc_item_to_search_result(item: Dict[str, Any]) -> SearchResultItem:
    raw_authors = item.get("authors", [])
    author_objects = []
    for a in raw_authors:
        if isinstance(a, dict):
            author_objects.append(AuthorItem(name=a.get("name", "Unknown")))
        elif isinstance(a, str):
            author_objects.append(AuthorItem(name=a))

    return SearchResultItem(
        title=item.get("title", "Untitled Document"),
        subtitle=item.get("description")[:100] if item.get("description") else None,
        authors=author_objects,
        published_date=item.get("published_date"),
        publisher=item.get("publisher"),
        isbn_13=None, 
        categories=item.get("subjects", []),
        description=item.get("description"),
        format_tag="Primary Source",
        data_sources=["Library of Congress"],
        lccn=item.get("lccn")
    )

def _merge_and_deduplicate_results(
    google_results: List[SearchResultItem],
    ol_results: List[SearchResultItem],
    loc_results: List[Dict[str, Any]] = [],
    query: str = "" 
) -> List[SearchResultItem]:
    merged_books: Dict[str, SearchResultItem] = {}
    
    def get_fallback_key(item: SearchResultItem):
        if not item.authors: return f"noauth-{item.title.lower().strip()}"
        return f"{item.title.lower().strip()}|{item.authors[0].name.lower().strip()}"

    for item in google_results:
        key = item.isbn_13 or get_fallback_key(item)
        if key: merged_books[key] = item

    for item in ol_results:
        key = item.isbn_13 or get_fallback_key(item)
        if not key: continue
        if key in merged_books:
            existing = merged_books[key]
            if not existing.open_library_work_id: existing.open_library_work_id = item.open_library_work_id
            if not existing.authors and item.authors: existing.authors = item.authors
            if "Open Library" not in existing.data_sources:
                 existing.data_sources.append("Open Library")
        else:
            merged_books[key] = item

    clean_loc_results = [_loc_item_to_search_result(item) for item in loc_results]
    for item in clean_loc_results:
        key = get_fallback_key(item) 
        if key in merged_books:
             existing = merged_books[key]
             if "Library of Congress" not in existing.data_sources:
                 existing.data_sources.append("Library of Congress")
             existing.format_tag = "Primary Source"
             if item.lccn and not existing.lccn:
                 existing.lccn = item.lccn
        else:
             merged_books[key] = item

    def score_book(book: SearchResultItem) -> int:
        score = 0
        if book.cover_url: score += 10
        if book.isbn_13: score += 5
        if "Library of Congress" in book.data_sources: score += 3 
        if book.published_date: score += 1
        
        # --- PHASE 2 & 3: RELEVANCE BOOSTING ---
        if query:
            def norm(s): return re.sub(r'[^a-z0-9]', '', str(s).lower())
            q_clean = norm(query)

            # TITLE MATCH BOOST
            if book.title:
                t_clean = norm(book.title)
                if q_clean == t_clean:
                    score += 500 
                elif q_clean in t_clean and len(q_clean) > 5:
                    score += 20  

            # AUTHOR AUTHORITY BOOST
            if book.authors:
                for author in book.authors:
                    a_clean = norm(author.name)
                    if q_clean == a_clean:
                        score += 600 
                    elif q_clean in a_clean and len(q_clean) > 4:
                        score += 100 

            # INDIE RESCUE
            if book.title and not book.cover_url:
                if norm(query) == norm(book.title):
                    score += 200

        return score

    final_list = list(merged_books.values())
    final_list.sort(key=score_book, reverse=True)
    return final_list


# --------------------------------------------------------------------
# 4. API Service Helpers
# --------------------------------------------------------------------

async def get_google_data_by_isbn(isbn: str) -> dict:
    if not API_KEY: return {}
    FIELDS = "totalItems,items(id,volumeInfo(title,subtitle,authors,publisher,publishedDate,description,pageCount,averageRating,ratingsCount,categories,dimensions,imageLinks(thumbnail,smallThumbnail,small,medium,large,extraLarge),industryIdentifiers,language),saleInfo,accessInfo)"
    params = {"q": f"isbn:{isbn}", "key": API_KEY, "fields": FIELDS}
    data = await cached_get(GOOGLE_BOOKS_API_URL, params)
    if data.get("totalItems", 0) > 0 and "items" in data:
        return data["items"][0]
    return {}

async def get_open_library_data_by_isbn(isbn: str) -> dict:
    params = {"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"}
    data = await cached_get(f"{OPEN_LIBRARY_API_URL}/api/books", params)
    return data.get(f"ISBN:{isbn}", {})

async def get_open_library_work_details(work_key: str) -> dict:
    if not work_key.startswith("/works/"):
        work_key = f"/works/{work_key.split('/')[-1]}" 
    url = f"{OPEN_LIBRARY_API_URL}{work_key}.json"
    return await cached_get(url, params={})

async def search_google(q: str, limit: int, start_index: int, subject: Optional[str] = None) -> List[SearchResultItem]:
    if not API_KEY: return []
    FIELDS = "items(id,volumeInfo(title,subtitle,authors,publisher,publishedDate,averageRating,ratingsCount,categories,imageLinks(thumbnail,small),industryIdentifiers,description,pageCount))"
    query_string = f"{q} subject:{subject}" if subject else q
    params = {
        "q": query_string, 
        "key": API_KEY, 
        "maxResults": limit, 
        "startIndex": start_index,
        "langRestrict": "en",
        "fields": FIELDS
    }
    data = await cached_get(GOOGLE_BOOKS_API_URL, params)
    return [_google_item_to_search_result(item) for item in data.get("items", [])]

async def search_open_library(q: str, limit: int, offset: int, subject: Optional[str] = None) -> List[SearchResultItem]:
    params = {
        "q": q, 
        "limit": limit, 
        "offset": offset,
        "fields": "title,subtitle,author_name,author_key,isbn,key,publisher,subject,first_publish_year,cover_i", 
        "subject": subject,
        "language": "eng" 
    }
    data = await cached_get(f"{OPEN_LIBRARY_API_URL}/search.json", params)
    return [_ol_item_to_search_result(item) for item in data.get("docs", [])]

async def get_open_library_new_releases(limit: int, offset: int, subject: Optional[str] = None) -> List[SearchResultItem]:
    current_year = datetime.now().year
    start_year = current_year - 1
    base_query = f"subject:{subject}" if subject else "language:eng"
    date_query = f"first_publish_year:[{start_year} TO *]"
    final_query = f"{base_query} {date_query}"

    params = {
        "q": final_query,
        "sort": "new",
        "limit": limit,
        "offset": offset,
        "fields": "title,subtitle,author_name,author_key,isbn,key,publisher,subject,first_publish_year,cover_i", 
    }
    data = await cached_get(f"{OPEN_LIBRARY_API_URL}/search.json", params, timeout_seconds=3600)
    return [_ol_item_to_search_result(item) for item in data.get("docs", [])]

async def get_open_library_author(author_key: str) -> dict:
    return await cached_get(f"{OPEN_LIBRARY_API_URL}/authors/{author_key}.json", params={})

async def get_open_library_work_editions(work_key: str) -> dict:
    url = f"{OPEN_LIBRARY_API_URL}/works/{work_key}/editions.json"
    return await cached_get(url, params={"limit": 50})

async def get_wikidata_profile(author_name: str) -> Optional[Dict[str, Any]]:
    query = """
    SELECT ?author ?authorLabel ?bio ?birthDate ?deathDate ?image WHERE {
      ?author wdt:P31 wd:Q5;          # Instance of human
              wdt:P106 wd:Q36180;     # Occupation: writer
              rdfs:label ?authorLabel.
      FILTER(LANG(?authorLabel) = "en").
      FILTER(LCASE(?authorLabel) = LCASE("%s")).
      OPTIONAL { ?author wdt:P569 ?birthDate. }
      OPTIONAL { ?author wdt:P570 ?deathDate. }
      OPTIONAL { ?author wdt:P18 ?image. }
      OPTIONAL { ?author schema:description ?bio. FILTER(LANG(?bio) = "en") }
    } LIMIT 1
    """ % author_name.replace('"', '\\"')

    params = {"query": query, "format": "json"}
    headers = {
        "User-Agent": "Bookfinder/4.0 (https://bookfinder.example.com; contact@example.com)" 
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(WIKIDATA_SPARQL_URL, params=params, headers=headers, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                bindings = data.get("results", {}).get("bindings", [])
                if bindings:
                    res = bindings[0]
                    return {
                        "bio": res.get("bio", {}).get("value"),
                        "birth_date": res.get("birthDate", {}).get("value"),
                        "death_date": res.get("deathDate", {}).get("value"),
                        "photo_url": res.get("image", {}).get("value")
                    }
    except Exception as e:
        logger.warning(f"Wikidata query failed for {author_name}: {e}")
    
    return None

# Health Checks
async def check_redis_health() -> ServiceHealth:
    if not cache: return ServiceHealth(name="redis", status="error", detail="Redis client not initialized.")
    try:
        await cache.ping()
        return ServiceHealth(name="redis", status="ok")
    except Exception as e:
        return ServiceHealth(name="redis", status="error", detail=str(e))

async def check_google_health() -> ServiceHealth:
    if not API_KEY: return ServiceHealth(name="google_books", status="error", detail="GOOGLE_API_KEY not set.")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(GOOGLE_BOOKS_API_URL, params={"q": "a", "maxResults": 1, "fields": "totalItems", "key": API_KEY}, timeout=5.0)
            resp.raise_for_status()
        return ServiceHealth(name="google_books", status="ok")
    except httpx.HTTPError as e:
        return ServiceHealth(name="google_books", status="error", detail=str(e))

async def check_ol_health() -> ServiceHealth:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{OPEN_LIBRARY_API_URL}/works/OL45804W.json", timeout=5.0)
            resp.raise_for_status()
        return ServiceHealth(name="open_library", status="ok")
    except httpx.HTTPError as e:
        return ServiceHealth(name="open_library", status="error", detail=str(e))


# --------------------------------------------------------------------
# 5. API Endpoints
# --------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["Health & Stats"])
async def get_health(response: Response, request: Request):
    results = await asyncio.gather(check_redis_health(), check_google_health(), check_ol_health())
    if any(res.status == "error" for res in results):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="error", services=results)
    return HealthResponse(status="ok", services=results)

@app.get("/cache/stats", response_model=CacheStats, tags=["Health & Stats"])
@limiter.limit("10/minute")
async def get_cache_stats(request: Request, admin: bool = Depends(get_admin_key)):
    if not cache: return CacheStats(status="disabled", key_count=0, used_memory="0B", redis_url=REDIS_URL)
    try:
        key_count = await cache.dbsize()
        memory_info = await cache.info("memory")
        return CacheStats(status="ok", key_count=key_count, used_memory=memory_info.get("used_memory_human", "N/A"), redis_url=REDIS_URL)
    except Exception as e:
        return CacheStats(status="error", key_count=0, used_memory="0B", redis_url=f"Error: {str(e)}")

@app.get("/")
async def read_root(request: Request): return {"message": "Bookfinder Intelligent API v4.8.0 is running!"}

@app.get("/genres/fiction", response_model=List[fiction.Genre])
@limiter.limit("20/minute")
async def get_fiction_genres(request: Request): return fiction.FICTION_GENRES

@app.get("/genres/non-fiction", response_model=List[non_fiction.Genre])
@limiter.limit("20/minute")
async def get_non_fiction_genres(request: Request): return non_fiction.NON_FICTION_GENRES

def _merge_loc_data(book: MergedBook, loc_data: dict) -> MergedBook:
    if not loc_data:
        return book
    
    # FIX: Overwrite default title/description if LOC provides better ones
    if book.title == "Title Not Found" and loc_data.get("title"):
        book.title = loc_data["title"]
    
    if not book.description and loc_data.get("description"):
        book.description = loc_data["description"]
        
    if loc_data.get("published_date"):
        book.published_date = loc_data["published_date"]
    if loc_data.get("subjects"):
        combined = set(book.subjects + loc_data["subjects"])
        book.subjects = sorted(list(combined))
    if not book.publisher and loc_data.get("publisher"):
        book.publisher = loc_data["publisher"]
    
    # FIX: Map LCCN if available
    if loc_data.get("lccn"):
        book.lccn = loc_data["lccn"]
    
    # Attribution
    if book.data_sources is not None and "Library of Congress" not in book.data_sources:
        book.data_sources.append("Library of Congress")
        
    return book

# NEW: Unified Book/ID Handler (Fixed Variable Scope)
@app.get("/book/isbn/{isbn}", response_model=MergedBook, tags=["Books"])
@limiter.limit("100/minute")
async def get_book_by_isbn(request: Request, isbn: str = Depends(validate_and_clean_isbn)):
    # 1. Determine ID Type
    is_lccn = len(isbn) < 13 and isbn.isdigit()
    
    # 2. Strategy Split
    if is_lccn:
        # LCCN Mode: Only query LOC (using Item endpoint)
        google_volume, open_library_book, loc_data = await asyncio.gather(
            asyncio.sleep(0, result={}),
            asyncio.sleep(0, result={}),
            loc.get_loc_data_by_lccn(isbn) # Uses the new Item lookup!
        )
    else:
        # Standard ISBN Mode: Query All
        google_volume, open_library_book, loc_data = await asyncio.gather(
            get_google_data_by_isbn(isbn),
            get_open_library_data_by_isbn(isbn),
            loc.get_loc_data_by_isbn(isbn)
        )
    
    if not google_volume and not open_library_book and not loc_data:
        raise HTTPException(status_code=404, detail="Book not found.")

    g_info = google_volume.get("volumeInfo", {})
    description = clean_html_text(g_info.get("description"))
    if not description:
        desc_raw = open_library_book.get("description")
        if isinstance(desc_raw, dict): description = clean_html_text(desc_raw.get("value"))
        elif isinstance(desc_raw, str): description = clean_html_text(desc_raw)
        if not description and loc_data.get("description"):
            description = clean_html_text(loc_data["description"])
    
    tasks = []
    work_key = None
    ol_works = open_library_book.get("works", [])
    if ol_works and isinstance(ol_works[0], dict) and "key" in ol_works[0]:
        work_key = ol_works[0]["key"]
        tasks.append(get_open_library_work_details(work_key))
    else:
        tasks.append(asyncio.sleep(0))

    ol_authors_list = open_library_book.get("authors", [])
    author_keys_to_fetch = []
    for a in ol_authors_list:
        if "author" in a and "key" in a["author"]: author_keys_to_fetch.append(a["author"]["key"])
        elif "key" in a: author_keys_to_fetch.append(a["key"])
    
    author_fetch_tasks = [get_open_library_author(k) for k in author_keys_to_fetch[:3]]
    secondary_results = await asyncio.gather(tasks[0], *author_fetch_tasks)
    work_data = secondary_results[0] if work_key else None
    author_details_list = secondary_results[1:]

    if not description and work_data:
        raw_desc = work_data.get("description")
        if isinstance(raw_desc, dict): description = clean_html_text(raw_desc.get("value"))
        elif isinstance(raw_desc, str): description = clean_html_text(raw_desc)

    clean_g_categories = _process_rich_categories(g_info.get("categories", []))
    clean_ol_subjects = _process_rich_categories(open_library_book.get("subjects", []))

    work_tags = []
    if work_data:
        work_tags.extend(work_data.get("subjects", []))
        work_tags.extend(work_data.get("subject_places", []))
        work_tags.extend(work_data.get("subject_times", []))
    
    clean_work_tags = _process_rich_categories(work_tags)
    combined_subjects = sorted(list(set(clean_g_categories + clean_ol_subjects + clean_work_tags)))
    
    has_loc_subjects = loc_data and loc_data.get("subjects")
    if not has_loc_subjects and len(combined_subjects) < 3 and description:
        combined_subjects = sorted(list(set(combined_subjects + heuristic_tagging(description + " " + g_info.get("title", ""), combined_subjects))))

    author_bio_map = {}
    for ad in author_details_list:
        if not ad: continue
        k = ad.get("key")
        b = ad.get("bio")
        if isinstance(b, dict): b = b.get("value") 
        if k and b: author_bio_map[k] = clean_html_text(b)

    final_authors = []
    if ol_authors_list: 
        for a in ol_authors_list:
            name = a.get("name", "Unknown") 
            key = None
            if "url" in a: key = a["url"].split("/")[-1]
            elif "key" in a: key = a["key"]
            bio = author_bio_map.get(key) if key else None
            final_authors.append(AuthorItem(name=name, key=key, bio=bio))
            
    if not final_authors:
        final_authors = [AuthorItem(name=a, key=None) for a in g_info.get("authors", [])]
    
    # If authors still empty, try LOC
    if not final_authors and loc_data.get("authors"):
        for a in loc_data.get("authors", []):
             final_authors.append(AuthorItem(name=a.get("name", "Unknown")))

    # Initialize variables to avoid scope errors
    isbn_10 = None
    related_isbns = []
    
    if g_info.get("industryIdentifiers"):
        isbn_10 = next((i["identifier"] for i in g_info.get("industryIdentifiers", []) if i["type"] == "ISBN_10"), None)
        related_isbns = [i["identifier"] for i in g_info.get("industryIdentifiers", [])]
        
    is_ebook = google_volume.get("saleInfo", {}).get("isEbook", False)
    fmt = classify_format(g_info.get("pageCount"), is_ebook)
    content_flag = check_content_safety(description, combined_subjects)
    series = detect_series(g_info.get("title", ""), g_info.get("subtitle"))

    ol_covers = OpenLibraryCoverLinks(
        small=ensure_https(f"https://covers.openlibrary.org/b/isbn/{isbn}-S.jpg"),
        medium=ensure_https(f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"),
        large=ensure_https(f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg")
    )
    
    links = g_info.get("imageLinks", {})
    raw_thumbnail = ensure_https(links.get("thumbnail"))
    extra_large = ensure_https(links.get("extraLarge"))
    if not extra_large and raw_thumbnail: extra_large = generate_high_res_url(raw_thumbnail)
    large = ensure_https(links.get("large"))
    if not large and raw_thumbnail: large = generate_high_res_url(raw_thumbnail)

    g_covers = GoogleCoverLinks(
        thumbnail=raw_thumbnail,
        smallThumbnail=ensure_https(links.get("smallThumbnail")),
        small=ensure_https(links.get("small")),
        medium=ensure_https(links.get("medium")),
        large=large,
        extraLarge=extra_large
    )
    
    cover_url = g_covers.thumbnail or g_covers.smallThumbnail or g_covers.small or g_covers.medium
    if not cover_url:
        # Use the passed ID for cover lookup fallback
        if isbn: cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"

    sources = []
    if google_volume: sources.append("Google Books")
    if open_library_book: sources.append("Open Library")
    if loc_data: sources.append("Library of Congress")

    # FIX: Correct instantiation of MergedBook (Robust Variable Scope)
    merged_book = MergedBook(
        title=g_info.get("title", open_library_book.get("title", "Title Not Found")),
        subtitle=g_info.get("subtitle"),
        authors=final_authors,
        isbn_13=isbn, # Use the requested ID as the primary key
        isbn_10=isbn_10,
        google_book_id=google_volume.get("id"),
        description=description,
        publisher=g_info.get("publisher", open_library_book.get("publishers", [{}])[0].get("name")),
        published_date=g_info.get("publishedDate", open_library_book.get("publish_date")),
        page_count=g_info.get("pageCount", open_library_book.get("number_of_pages")),
        average_rating=g_info.get("averageRating"),
        ratings_count=g_info.get("ratingsCount"),
        dimensions=g_info.get("dimensions"),
        sale_info=google_volume.get("saleInfo"),
        access_info=google_volume.get("accessInfo"),
        google_cover_links=g_covers,
        open_library_id=open_library_book.get("key"),
        subjects=combined_subjects,
        open_library_cover_links=ol_covers,
        series=series,
        format_tag=fmt,
        related_isbns=related_isbns,
        content_flag=content_flag,
        data_source="hybrid",
        data_sources=sources,
        lccn=[] # Default empty list for MergedBook
    )
    
    return _merge_loc_data(merged_book, loc_data)

# --- NEW: Helper to identify LCCN queries ---
def _is_lccn(q: str) -> bool:
    clean = q.replace("-", "").strip()
    return clean.isdigit() and 8 <= len(clean) <= 12

@app.get("/search", response_model=HybridSearchResponse, tags=["Books"])
@limiter.limit("60/minute")
async def search_hybrid(request: Request, q: str, subject: Optional[str] = None, limit: int = 10, start_index: int = 0):
    
    # 1. Determine Search Mode based on Input Type
    is_id_search = _is_lccn(q)
    
    # Use helper list to wrap single result into list for merge function
    def wrap_in_list(item):
        return [item] if item else []

    if is_id_search:
        logger.info(f"Detected LCCN-like query: {q}. Switching to ID search mode.")
        google_task = asyncio.sleep(0, result=[]) # Skip Google for ID search
        ol_task = asyncio.sleep(0, result=[]) # Skip OL for ID search
        
        # Use Item Lookup (get_loc_data_by_lccn) but wrap it in a task that returns a list
        # We need an async wrapper because get_loc_data_by_lccn returns Dict, not List[Dict]
        async def loc_id_wrapper(lccn_id):
            res = await loc.get_loc_data_by_lccn(lccn_id)
            return [res] if res else []
            
        loc_task = loc_id_wrapper(q)
        
        # Parallel Execution (Simulated for single task, but consistent structure)
        google_results, ol_results, loc_results = await asyncio.gather(
            google_task, ol_task, loc_task
        )
        
    else:
        # Phase 1: Literalist Query Injection (The Fix for 'Girl, Incorrupted')
        # If the query is multi-word, launch a parallel "Exact Phrase" search
        if " " in q and len(q) > 5:
            # We fire 4 tasks: Google Fuzzy, Google Exact, OL Fuzzy, OL Exact
            google_task = search_google(q, limit, start_index, subject)
            google_exact = search_google(f'"{q}"', limit, start_index, subject)
            
            ol_task = search_open_library(q, limit, start_index, subject)
            ol_exact = search_open_library(f'"{q}"', limit, start_index, subject)
            
            loc_task = loc.search_loc(q, limit)

            # Gather all 5 tasks
            results_tuple = await asyncio.gather(
                google_task, google_exact, ol_task, ol_exact, loc_task
            )
            
            # Combine Exact + Fuzzy results (Exact first)
            google_results = results_tuple[1] + results_tuple[0] 
            ol_results = results_tuple[3] + results_tuple[2]
            loc_results = results_tuple[4]
            
        else:
            # Standard Path
            google_task = search_google(q, limit, start_index, subject)
            ol_task = search_open_library(q, limit, start_index, subject)
            loc_task = loc.search_loc(q, limit)

            google_results, ol_results, loc_results = await asyncio.gather(
                google_task, 
                ol_task, 
                loc_task
            )
    
    # 3. Merge (Pass query for Title Boosting)
    final_results = _merge_and_deduplicate_results(google_results, ol_results, loc_results, query=q)
    return HybridSearchResponse(query=q, subject=subject, num_found=len(final_results), results=final_results)

# --- QUALITY GATE HELPER ---
def _is_valid_release(book: SearchResultItem) -> bool:
    if not book.cover_url: return False
    if not book.isbn_13 and not book.isbn_10: return False
    if not book.authors or book.authors[0].name == "Unknown": return False
    lower_title = book.title.lower()
    if "<" in lower_title or "{" in lower_title or len(lower_title) > 150: return False
    if any(banned in lower_title for banned in TITLE_BLACKLIST): return False
    reprint_triggers = ["anniversary edition", "classic", "reissue", "reprint"]
    if any(trigger in lower_title for trigger in reprint_triggers): return False
    if not book.published_date: return False
    
    # --- DATE VALIDATION LOGIC (Ghost Book Fix) ---
    try:
        now = datetime.now()
        # Define the window: 1 Year Ago <-> 90 Days Future
        cutoff_past = now - timedelta(days=365)
        cutoff_future = now + timedelta(days=90)

        # 1. Parse Year first (fast fail)
        match = re.search(r"(\d{4})", book.published_date)
        if not match: return False
        year = int(match.group(1))

        # Basic Year Checks
        if year < (now.year - 1): return False # Too Old
        if year > (now.year + 1): return False # Too Far Future (2027+)

        # 2. Strict Date Parsing (if possible)
        # Try YYYY-MM-DD
        try:
            pub_dt = datetime.strptime(book.published_date[:10], "%Y-%m-%d")
            if pub_dt < cutoff_past or pub_dt > cutoff_future:
                return False
        except ValueError:
            # Fallback: If it's just a year (2025), and we are in 2025, it passes.
            # If it is 2026, and we are in Dec 2025, it might be valid.
            # We let the basic year check handle the rough edges.
            pass

    except Exception:
        return False

    return True

# --- THE DEEP DREDGE ENDPOINT ---
@app.get("/new-releases", response_model=NewReleasesResponse, tags=["Books"])
@limiter.limit("30/minute")
async def get_new_releases(request: Request, subject: Optional[str] = None, limit: int = 10, start_index: int = 0):
    valid_books = []
    current_offset = start_index
    depth = 0
    MAX_DEPTH = 5
    INTERNAL_BATCH_SIZE = 40 
    
    while len(valid_books) < limit and depth < MAX_DEPTH:
        ol_results = await get_open_library_new_releases(limit=INTERNAL_BATCH_SIZE, offset=current_offset, subject=subject)
        
        if not ol_results:
            break
            
        for book in ol_results:
            if not book.cover_url:
                isbn = book.isbn_13 or book.isbn_10
                if isbn:
                    try:
                        g_data = await get_google_data_by_isbn(isbn)
                        g_images = g_data.get("volumeInfo", {}).get("imageLinks", {})
                        rescued_cover = g_images.get("thumbnail") or g_images.get("smallThumbnail")
                        if rescued_cover:
                            book.cover_url = ensure_https(rescued_cover)
                    except Exception as e:
                        pass
            
            # Apply the new Date Validator here
            if _is_valid_release(book):
                valid_books.append(book)
                
        current_offset += INTERNAL_BATCH_SIZE
        depth += 1
    
    unique_books = {}
    for b in valid_books:
        k = b.isbn_13 or b.isbn_10 or b.title
        if k not in unique_books:
            unique_books[k] = b
            
    final_list = list(unique_books.values())[:limit]

    return NewReleasesResponse(subject=subject, num_found=len(final_list), results=final_list)

def _mine_bio_from_books(author_name: str, books: List[SearchResultItem]) -> Optional[str]:
    name_parts = author_name.split()
    last_name = name_parts[-1] if name_parts else ""
    bio_signals = [
        "lives in", "based in", "resides in", "grew up", "born in", "currently", 
        "author of", "writer", "books include", "works include", "novels include",
        "award", "bestselling", "degree", "university", "graduate"
    ]
    pronouns = [" he ", " she ", " they ", " her ", " his ", " their "]

    for book in books:
        raw_desc = book.description
        if not raw_desc: continue
        desc = clean_html_text(raw_desc) or ""
        logger.info(f"Scanning book: {book.title} for bio...")
        chunks = re.split(r'\.\s+(?=[A-Z])', desc)
        chunks = [c.strip() for c in chunks if len(c) > 20]
        if not chunks: continue
        tail_chunks = chunks[-5:] 
        for chunk in reversed(tail_chunks):
            score = 0
            lower_chunk = chunk.lower()
            if author_name.lower() in lower_chunk: score += 3
            elif last_name.lower() in lower_chunk: score += 1
            if any(signal in lower_chunk for signal in bio_signals): score += 2
            if any(p in lower_chunk for p in pronouns): score += 1
            if "copyright" in lower_chunk or "rights reserved" in lower_chunk: score -= 5
            if "published by" in lower_chunk: score -= 2
            if score >= 3:
                logger.info(f"Bio found via heuristic scorer in {book.title} (score: {score})")
                return chunk
        tail_len = 1000
        tail = desc[-tail_len:] if len(desc) > tail_len else desc
        match = re.search(f"({re.escape(author_name)}.*)", tail, re.IGNORECASE | re.DOTALL)
        if match:
             candidate = match.group(1).strip()
             if len(candidate) > len(author_name) + 10:
                 logger.info(f"Bio found via Tail Search in {book.title}")
                 return candidate
    return None

def _generate_dynamic_bio(name: str, books: List[SearchResultItem]) -> str:
    if not books:
        return f"{name} is a featured author in our collection."
    genre_counts = {}
    for book in books:
        for cat in book.categories:
            genre_counts[cat] = genre_counts.get(cat, 0) + 1
    top_genre = "Contemporary Fiction"
    if genre_counts:
        top_genre = max(genre_counts, key=genre_counts.get) 
    titles = [f"'{b.title}'" for b in books[:2]]
    works_str = " and ".join(titles)
    return f"{name} is a writer known for {top_genre}. Notable works include {works_str}."

@app.get("/author/{id}", response_model=AuthorPageData, tags=["Discovery"])
@limiter.limit("100/minute")
async def get_author_profile(request: Request, id: str):
    if id.startswith("OL") and id.endswith("A"):
        try:
            author_data = await get_open_library_author(id)
            if not author_data:
                raise HTTPException(status_code=404, detail="Author not found.")
        except Exception:
            raise HTTPException(status_code=404, detail="Author not found.")
        works_results = await search_open_library(q=f"author_key:{id}", limit=20, offset=0)
        photo_url = None
        if "photos" in author_data and author_data["photos"]:
             photo_id = author_data["photos"][0]
             if photo_id > 0:
                 photo_url = f"https://covers.openlibrary.org/a/id/{photo_id}-L.jpg"
        bio_text = None
        if "bio" in author_data:
            bio_val = author_data["bio"]
            if isinstance(bio_val, dict):
                bio_text = bio_val.get("value")
            else:
                bio_text = str(bio_val)
        return AuthorPageData(
            key=id,
            name=author_data.get("name", "Unknown Author"),
            bio=clean_html_text(bio_text),
            birth_date=author_data.get("birth_date"),
            death_date=author_data.get("death_date"),
            photo_url=photo_url,
            books=works_results,
            source="open_library"
        )
    else:
        clean_name = id.replace('"', '').replace('_', ' ').strip()
        google_results = await search_google(q=f'inauthor:"{clean_name}"', limit=20, start_index=0)
        if not google_results:
             google_results = await search_google(q=f'inauthor:{clean_name}', limit=20, start_index=0)
        if not google_results:
             raise HTTPException(status_code=404, detail=f"Author '{clean_name}' not found.")
        display_name = clean_name
        if google_results and google_results[0].authors:
             display_name = google_results[0].authors[0].name
        wikidata_profile = await get_wikidata_profile(display_name)
        if wikidata_profile:
             return AuthorPageData(
                key=id,
                name=display_name,
                bio=wikidata_profile.get("bio") or "Wikidata bio unavailable.",
                birth_date=wikidata_profile.get("birth_date"),
                death_date=wikidata_profile.get("death_date"),
                photo_url=wikidata_profile.get("photo_url"),
                books=google_results,
                source="open_library" 
             )
        mined_bio = _mine_bio_from_books(display_name, google_results)
        if mined_bio:
             return AuthorPageData(
                key=id,
                name=display_name,
                bio=mined_bio,
                books=google_results,
                source="google_books"
             )
        dynamic_bio = _generate_dynamic_bio(display_name, google_results)
        return AuthorPageData(
            key=id, 
            name=display_name,
            bio=dynamic_bio,
            books=google_results,
            source="google_books"
        )

@app.get("/work/{work_key}", response_model=WorkEditionsResponse, tags=["Discovery"])
@limiter.limit("100/minute")
async def get_work_editions(request: Request, work_key: str):
    if not (work_key.startswith("OL") and work_key.endswith("W")): raise HTTPException(status_code=400, detail="Invalid work key.")
    editions_data = await get_open_library_work_editions(work_key)
    if not editions_data: raise HTTPException(status_code=404, detail="Work not found.")
    editions_data["key"] = f"/works/{work_key}"
    editions_data["size"] = editions_data.get("size", len(editions_data.get("entries", [])))
    for entry in editions_data.get("entries", []):
        if not entry.get("isbn_13") and not entry.get("isbn_10"):
            entry["isbn_13"] = entry.get("identifiers", {}).get("isbn_13", [])
            entry["isbn_10"] = entry.get("identifiers", {}).get("isbn_10", [])
    return WorkEditionsResponse(**editions_data)
#test 1.0