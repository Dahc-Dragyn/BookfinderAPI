import os
import httpx
import asyncio
import json
import hashlib
import sys
import re
from fastapi import FastAPI, Query, HTTPException, Request, Depends, Path, Header, Response, status
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

load_dotenv()
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Initialize Rate Limiter with Redis storage
limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL, default_limits=["100/minute"])

app = FastAPI(
    title="Bookfinder Hybrid API",
    description="A clean, cached, and rate-limited API wrapper with intelligent high-res image fallback and deep genre mining.",
    version="1.8.1"  # Bumped for Author Variable Fix
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

API_KEY = os.getenv("GOOGLE_API_KEY")
ADMIN_KEY = os.getenv("ADMIN_KEY")
GOOGLE_BOOKS_API_URL = "https://www.googleapis.com/books/v1/volumes"
OPEN_LIBRARY_API_URL = "https://openlibrary.org"

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

class SearchResultItem(BaseModel):
    title: str
    subtitle: Optional[str] = None
    authors: List[AuthorItem] = Field(default_factory=list)
    isbn_13: Optional[str] = None
    isbn_10: Optional[str] = None
    publisher: Optional[str] = None 
    average_rating: Optional[float] = None
    ratings_count: Optional[int] = None
    categories: List[str] = Field(default_factory=list)
    google_book_id: Optional[str] = None
    open_library_work_id: Optional[str] = None
    cover_url: Optional[str] = None

class HybridSearchResponse(BaseModel):
    query: str
    subject: Optional[str] = None
    num_found: int
    results: List[SearchResultItem]

class NewReleasesResponse(BaseModel):
    subject: Optional[str] = None
    num_found: int
    results: List[SearchResultItem]

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
# 3. Helper Functions
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

# --- Smart Genre Exploder (v1.8 - Relaxed) ---
def _process_rich_categories(raw_categories: List[Any]) -> List[str]:
    """
    Explodes 'Fiction / Fantasy' into distinct tags.
    v1.8: Relaxed stop words list to allow 'Fiction', 'Literature' to show up.
    """
    if not raw_categories: return []
    
    unique_tags = set()
    # Reduced stop words list
    stop_words = {
        "general", "electronic books", "books", "juvenile fiction", "young adult fiction"
    }
    
    for cat in raw_categories:
        # Handle OL objects vs Google Strings
        if isinstance(cat, dict):
            cat_str = cat.get("name", "")
        elif isinstance(cat, str):
            cat_str = cat
        else:
            continue

        if not cat_str: continue

        # 1. Split by Slashes or Double Dashes
        parts = re.split(r'[\/]+|--', cat_str)
        
        for part in parts:
            clean = part.strip()
            if not clean: continue
            
            # 2. Filter Stop Words (Strict Case Insensitive)
            if clean.lower() in stop_words:
                continue
            
            # 3. Add to set
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

def validate_and_clean_isbn(isbn: str = Path(...)) -> str:
    cleaned_isbn = re.sub(r"[\s-]+", "", isbn)
    if len(cleaned_isbn) == 13:
        if _is_valid_isbn13_checksum(cleaned_isbn): return cleaned_isbn
        raise HTTPException(status_code=400, detail="Invalid ISBN.")
    elif len(cleaned_isbn) == 10 and _is_valid_isbn10_checksum(cleaned_isbn):
        return _convert_isbn10_to_isbn13(cleaned_isbn)
    raise HTTPException(status_code=400, detail="Invalid ISBN.")

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

def _google_item_to_search_result(item: Dict[str, Any]) -> SearchResultItem:
    g_info = item.get("volumeInfo", {})
    isbn_13, isbn_10 = _get_isbns_from_google_item(item)
    
    cover_url = ensure_https(g_info.get("imageLinks", {}).get("thumbnail"))
    if not cover_url:
        cover_id = isbn_13 if isbn_13 else isbn_10
        if cover_id:
            cover_url = f"https://covers.openlibrary.org/b/isbn/{cover_id}-M.jpg"

    raw_authors = g_info.get("authors", [])
    author_objects = [AuthorItem(name=a, key=None) for a in raw_authors]

    # Use smart parser
    smart_cats = _process_rich_categories(g_info.get("categories", []))

    return SearchResultItem(
        title=g_info.get("title", "No Title"),
        subtitle=g_info.get("subtitle"),
        authors=author_objects,
        isbn_13=isbn_13,
        isbn_10=isbn_10,
        publisher=g_info.get("publisher"),
        average_rating=g_info.get("averageRating"),
        ratings_count=g_info.get("ratingsCount"),
        categories=smart_cats,
        google_book_id=item.get("id"),
        cover_url=cover_url
    )

def _ol_item_to_search_result(item: Dict[str, Any]) -> SearchResultItem:
    isbn_13, isbn_10 = _get_isbns_from_ol_item(item)
    cover_id = isbn_13 if isbn_13 else isbn_10
    
    raw_names = item.get("author_name", [])
    raw_keys = item.get("author_key", [])
    author_objects = []
    for i, name in enumerate(raw_names):
        key = raw_keys[i] if i < len(raw_keys) else None
        author_objects.append(AuthorItem(name=name, key=key))

    # Use smart parser
    smart_cats = _process_rich_categories(item.get("subject", []))[:8]

    return SearchResultItem(
        title=item.get("title", "No Title"),
        subtitle=item.get("subtitle"),
        authors=author_objects,
        isbn_13=isbn_13,
        isbn_10=isbn_10,
        publisher=item.get("publisher", [None])[0] if item.get("publisher") else None,
        categories=smart_cats,
        open_library_work_id=item.get("key"),
        cover_url=f"https://covers.openlibrary.org/b/isbn/{cover_id}-M.jpg" if cover_id else None
    )

def _merge_and_deduplicate_results(
    google_results: List[SearchResultItem],
    ol_results: List[SearchResultItem]
) -> List[SearchResultItem]:
    merged_books: Dict[str, SearchResultItem] = {}
    
    def get_fallback_key(item: SearchResultItem):
        if not item.authors: return None
        return f"{item.title.lower().strip()}|{item.authors[0].name.lower().strip()}"

    for item in google_results:
        if item.isbn_13:
            merged_books[item.isbn_13] = item
        else:
            fallback_key = get_fallback_key(item)
            if fallback_key: merged_books[fallback_key] = item

    for item in ol_results:
        key_to_check = item.isbn_13 or get_fallback_key(item)
        
        if key_to_check and key_to_check in merged_books:
            existing = merged_books[key_to_check]
            if not existing.open_library_work_id:
                existing.open_library_work_id = item.open_library_work_id
            
            if item.authors and (not existing.authors or not existing.authors[0].key):
                existing.authors = item.authors

            if not existing.publisher and item.publisher:
                existing.publisher = item.publisher
            
            if not existing.cover_url and item.cover_url:
                existing.cover_url = item.cover_url

            combined_subjects = set(existing.categories + item.categories)
            existing.categories = sorted(list(combined_subjects))
            
        elif key_to_check:
            merged_books[key_to_check] = item
        elif item.open_library_work_id:
            merged_books[item.open_library_work_id] = item

    return list(merged_books.values())


# --------------------------------------------------------------------
# 4. API Service Helpers
# --------------------------------------------------------------------

async def get_google_data_by_isbn(isbn: str) -> dict:
    if not API_KEY: return {}
    FIELDS = "totalItems,items(id,volumeInfo(title,subtitle,authors,publisher,publishedDate,description,pageCount,averageRating,ratingsCount,categories,dimensions,imageLinks(thumbnail,smallThumbnail,small,medium,large,extraLarge),industryIdentifiers),saleInfo,accessInfo)"
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

async def search_google(q: str, limit: int, subject: Optional[str] = None) -> List[SearchResultItem]:
    if not API_KEY: return []
    FIELDS = "items(id,volumeInfo(title,subtitle,authors,publisher,averageRating,ratingsCount,categories,imageLinks(thumbnail,small),industryIdentifiers))"
    query_string = f"{q} subject:{subject}" if subject else q
    params = {"q": query_string, "key": API_KEY, "maxResults": limit, "fields": FIELDS}
    data = await cached_get(GOOGLE_BOOKS_API_URL, params)
    return [_google_item_to_search_result(item) for item in data.get("items", [])]

async def search_open_library(q: str, limit: int, subject: Optional[str] = None) -> List[SearchResultItem]:
    params = {"q": q, "limit": limit, "fields": "title,subtitle,author_name,author_key,isbn,key,publisher,subject", "subject": subject}
    data = await cached_get(f"{OPEN_LIBRARY_API_URL}/search.json", params)
    return [_ol_item_to_search_result(item) for item in data.get("docs", [])]

async def get_google_new_releases(limit: int, subject: Optional[str] = None) -> List[SearchResultItem]:
    if not API_KEY: return []
    FIELDS = "items(id,volumeInfo(title,subtitle,authors,publisher,averageRating,ratingsCount,categories,imageLinks(thumbnail),industryIdentifiers))"
    query_string = f"subject:{subject}" if subject else "*"
    params = {"q": query_string, "orderBy": "newest", "key": API_KEY, "maxResults": limit, "fields": FIELDS}
    data = await cached_get(GOOGLE_BOOKS_API_URL, params)
    return [_google_item_to_search_result(item) for item in data.get("items", [])]

async def get_open_library_new_releases(limit: int, subject: Optional[str] = None) -> List[SearchResultItem]:
    query = f"subject:{subject}" if subject else "language:eng"
    params = {
        "q": query,
        "sort": "new",
        "limit": limit,
        "fields": "title,subtitle,author_name,author_key,isbn,key,publisher,subject",
    }
    data = await cached_get(f"{OPEN_LIBRARY_API_URL}/search.json", params)
    return [_ol_item_to_search_result(item) for item in data.get("docs", [])]

async def get_open_library_author(author_key: str) -> dict:
    return await cached_get(f"{OPEN_LIBRARY_API_URL}/authors/{author_key}.json", params={})

async def get_open_library_work_editions(work_key: str) -> dict:
    url = f"{OPEN_LIBRARY_API_URL}/works/{work_key}/editions.json"
    return await cached_get(url, params={"limit": 50})

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
async def read_root(request: Request): return {"message": "Bookfinder Hybrid API v1.8.1 (Author Fixed) is running!"}

@app.get("/genres/fiction", response_model=List[fiction.Genre])
@limiter.limit("20/minute")
async def get_fiction_genres(request: Request): return fiction.FICTION_GENRES

@app.get("/genres/non-fiction", response_model=List[non_fiction.Genre])
@limiter.limit("20/minute")
async def get_non_fiction_genres(request: Request): return non_fiction.NON_FICTION_GENRES

@app.get("/book/isbn/{isbn}", response_model=MergedBook, tags=["Books"])
@limiter.limit("100/minute")
async def get_book_by_isbn(request: Request, isbn: str = Depends(validate_and_clean_isbn)):
    google_volume, open_library_book = await asyncio.gather(
        get_google_data_by_isbn(isbn),
        get_open_library_data_by_isbn(isbn)
    )
    
    if not google_volume and not open_library_book:
        raise HTTPException(status_code=404, detail="Book not found.")

    g_info = google_volume.get("volumeInfo", {})
    
    description = g_info.get("description")
    if not description:
        desc_raw = open_library_book.get("description")
        if isinstance(desc_raw, dict): description = desc_raw.get("value")
        elif isinstance(desc_raw, str): description = desc_raw
    
    # --- MINING: Work Data & Author Bios ---
    tasks = []
    
    # Task 1: Work Data (Always try to fetch if key exists)
    work_key = None
    ol_works = open_library_book.get("works", [])
    if ol_works and isinstance(ol_works[0], dict) and "key" in ol_works[0]:
        work_key = ol_works[0]["key"]
        tasks.append(get_open_library_work_details(work_key))
    else:
        tasks.append(asyncio.sleep(0))

    # Task 2..N: Author Bios (Get keys from OL)
    ol_authors_list = open_library_book.get("authors", [])
    author_keys_to_fetch = []
    for a in ol_authors_list:
        if "author" in a and "key" in a["author"]:
             author_keys_to_fetch.append(a["author"]["key"])
        elif "key" in a:
             author_keys_to_fetch.append(a["key"])
    
    author_fetch_tasks = [get_open_library_author(k) for k in author_keys_to_fetch[:3]]
    
    secondary_results = await asyncio.gather(tasks[0], *author_fetch_tasks)
    
    work_data = secondary_results[0] if work_key else None
    author_details_list = secondary_results[1:]

    # --- DEEP DESCRIPTION FALLBACK ---
    if not description and work_data:
        raw_desc = work_data.get("description")
        if isinstance(raw_desc, dict): description = raw_desc.get("value")
        elif isinstance(raw_desc, str): description = raw_desc

    # --- DEEP GENRE MINING ---
    clean_g_categories = _process_rich_categories(g_info.get("categories", []))
    clean_ol_subjects = _process_rich_categories(open_library_book.get("subjects", []))

    work_tags = []
    if work_data:
        work_tags.extend(work_data.get("subjects", []))
        work_tags.extend(work_data.get("subject_places", []))
        work_tags.extend(work_data.get("subject_times", []))
        work_tags.extend(work_data.get("subject_people", []))

    clean_work_tags = _process_rich_categories(work_tags)
    combined_subjects = sorted(list(set(clean_g_categories + clean_ol_subjects + clean_work_tags)))

    # --- AUTHOR MERGE & ENRICHMENT ---
    author_bio_map = {}
    for ad in author_details_list:
        if not ad: continue
        k = ad.get("key")
        b = ad.get("bio")
        if isinstance(b, dict): b = b.get("value") 
        if k and b:
            author_bio_map[k] = b

    final_authors = []
    if ol_authors_list: # FIX: Use correct variable name
        for a in ol_authors_list:
            name = a.get("name", "Unknown") 
            key = None
            if "url" in a: key = a["url"].split("/")[-1]
            elif "key" in a: key = a["key"]
            
            bio = author_bio_map.get(key) if key else None
            final_authors.append(AuthorItem(name=name, key=key, bio=bio))
            
    if not final_authors:
        final_authors = [AuthorItem(name=a, key=None) for a in g_info.get("authors", [])]

    isbn_10 = next((i["identifier"] for i in g_info.get("industryIdentifiers", []) if i["type"] == "ISBN_10"), None)
    
    ol_covers = OpenLibraryCoverLinks(
        small=ensure_https(f"https://covers.openlibrary.org/b/isbn/{isbn}-S.jpg"),
        medium=ensure_https(f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"),
        large=ensure_https(f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg")
    )
    
    g_covers = None
    if "imageLinks" in g_info:
        raw_thumbnail = ensure_https(g_info["imageLinks"].get("thumbnail"))
        extra_large = ensure_https(g_info["imageLinks"].get("extraLarge"))
        if not extra_large and raw_thumbnail:
            extra_large = generate_high_res_url(raw_thumbnail)
        large = ensure_https(g_info["imageLinks"].get("large"))
        if not large and raw_thumbnail:
             large = generate_high_res_url(raw_thumbnail)

        g_covers = GoogleCoverLinks(
            thumbnail=raw_thumbnail,
            smallThumbnail=ensure_https(g_info["imageLinks"].get("smallThumbnail")),
            small=ensure_https(g_info["imageLinks"].get("small")),
            medium=ensure_https(g_info["imageLinks"].get("medium")),
            large=large,
            extraLarge=extra_large
        )

    return MergedBook(
        title=g_info.get("title", open_library_book.get("title", "Title Not Found")),
        subtitle=g_info.get("subtitle"),
        authors=final_authors,
        isbn_13=isbn,
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
        open_library_cover_links=ol_covers
    )

@app.get("/search", response_model=HybridSearchResponse, tags=["Books"])
@limiter.limit("60/minute")
async def search_hybrid(request: Request, q: str, subject: Optional[str] = None, limit: int = 10):
    google_results, ol_results = await asyncio.gather(search_google(q, limit, subject), search_open_library(q, limit, subject))
    final_results = _merge_and_deduplicate_results(google_results, ol_results)
    return HybridSearchResponse(query=q, subject=subject, num_found=len(final_results), results=final_results)

@app.get("/new-releases", response_model=NewReleasesResponse, tags=["Books"])
@limiter.limit("30/minute")
async def get_new_releases(request: Request, subject: Optional[str] = None, limit: int = 10):
    google_results, ol_results = await asyncio.gather(get_google_new_releases(limit, subject), get_open_library_new_releases(limit, subject))
    final_results = _merge_and_deduplicate_results(google_results, ol_results)
    return NewReleasesResponse(subject=subject, num_found=len(final_results), results=final_results)

@app.get("/author/{author_key}", response_model=AuthorDetails, tags=["Discovery"])
@limiter.limit("100/minute")
async def get_author(request: Request, author_key: str):
    if not (author_key.startswith("OL") and author_key.endswith("A")): raise HTTPException(status_code=400, detail="Invalid author key.")
    author_data = await get_open_library_author(author_key)
    if not author_data: raise HTTPException(status_code=404, detail="Author not found.")
    return AuthorDetails(**author_data)

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