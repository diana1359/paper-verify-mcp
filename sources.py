"""
sources.py
----------
Crossref, OpenAlex, PubMed 세 곳에 논문 실재 여부를 비동기로 조회한다.
각 함수는 아래와 같은 정규화된 dict 를 돌려준다:

    {
      "source":      "crossref" | "openalex" | "pubmed",
      "found":       bool,
      "doi":         str | None,
      "title":       str | None,
      "authors":     [str, ...],
      "year":        int | None,
      "journal":     str | None,
      "url":         str | None,     # 원본 레코드 링크
      "match_score": float | None,   # 제목 검색일 때 유사도 (0~1)
      "error":       str | None,     # 조회 실패 사유
    }
"""

from __future__ import annotations

import os
import re
import difflib
from typing import Any

import httpx

# --- 설정 -------------------------------------------------------------------
# Crossref / OpenAlex 는 연락용 이메일을 넣으면 "polite pool" 로 분류돼 더 안정적이다.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "anonymous@example.com")
# PubMed(NCBI) API 키가 있으면 초당 요청 한도가 3 -> 10 으로 늘어난다. 없어도 동작.
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")

USER_AGENT = f"paper-verify-mcp/1.0 (mailto:{CONTACT_EMAIL})"
TIMEOUT = httpx.Timeout(15.0, connect=10.0)

CROSSREF_BASE = "https://api.crossref.org"
OPENALEX_BASE = "https://api.openalex.org"
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)


# --- 유틸 -------------------------------------------------------------------
def extract_doi(text: str) -> str | None:
    """자유 형식 인용 문자열에서 DOI 를 뽑아낸다."""
    if not text:
        return None
    m = DOI_RE.search(text)
    if not m:
        return None
    # 뒤에 붙는 문장부호 제거
    return m.group(0).rstrip(".,;)")


def _normalize(s: str) -> str:
    """제목 비교용 정규화: 소문자 + 영숫자만."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def similarity(a: str, b: str) -> float:
    """두 제목의 유사도(0~1). 표준 라이브러리만 사용."""
    return round(difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio(), 3)


def _empty(source: str, error: str | None = None) -> dict[str, Any]:
    return {
        "source": source, "found": False, "doi": None, "title": None,
        "authors": [], "year": None, "journal": None, "url": None,
        "match_score": None, "error": error,
    }


# --- Crossref ---------------------------------------------------------------
def _crossref_pack(item: dict, source_error=None) -> dict[str, Any]:
    title = (item.get("title") or [None])[0]
    authors = [
        " ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name", "")
        for a in item.get("author", [])
    ]
    year = None
    for key in ("published", "published-print", "published-online", "issued"):
        parts = (item.get(key) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = parts[0][0]
            break
    doi = item.get("DOI")
    return {
        "source": "crossref", "found": True, "doi": doi, "title": title,
        "authors": [a for a in authors if a], "year": year,
        "journal": (item.get("container-title") or [None])[0],
        "url": f"https://doi.org/{doi}" if doi else item.get("URL"),
        "match_score": None, "error": source_error,
    }


async def crossref_by_doi(client: httpx.AsyncClient, doi: str) -> dict[str, Any]:
    try:
        r = await client.get(f"{CROSSREF_BASE}/works/{doi}", params={"mailto": CONTACT_EMAIL})
        if r.status_code == 404:
            return _empty("crossref")
        r.raise_for_status()
        return _crossref_pack(r.json()["message"])
    except Exception as e:
        return _empty("crossref", str(e))


async def crossref_by_title(client: httpx.AsyncClient, title: str) -> dict[str, Any]:
    try:
        r = await client.get(
            f"{CROSSREF_BASE}/works",
            params={"query.bibliographic": title, "rows": 5, "mailto": CONTACT_EMAIL,
                    "select": "DOI,title,author,issued,container-title,URL"},
        )
        r.raise_for_status()
        items = r.json()["message"].get("items", [])
        best, best_score = None, 0.0
        for it in items:
            cand = (it.get("title") or [""])[0]
            sc = similarity(title, cand)
            if sc > best_score:
                best, best_score = it, sc
        if not best:
            return _empty("crossref")
        packed = _crossref_pack(best)
        packed["match_score"] = best_score
        packed["found"] = best_score >= 0.85
        return packed
    except Exception as e:
        return _empty("crossref", str(e))


# --- OpenAlex ---------------------------------------------------------------
def _openalex_pack(w: dict) -> dict[str, Any]:
    doi_url = w.get("doi")
    doi = doi_url.replace("https://doi.org/", "") if doi_url else None
    journal = None
    loc = w.get("primary_location") or {}
    if loc.get("source"):
        journal = loc["source"].get("display_name")
    return {
        "source": "openalex", "found": True, "doi": doi,
        "title": w.get("title") or w.get("display_name"),
        "authors": [a["author"]["display_name"] for a in w.get("authorships", [])
                    if a.get("author")],
        "year": w.get("publication_year"),
        "journal": journal, "url": w.get("id"),
        "match_score": None, "error": None,
    }


async def openalex_by_doi(client: httpx.AsyncClient, doi: str) -> dict[str, Any]:
    try:
        r = await client.get(f"{OPENALEX_BASE}/works/https://doi.org/{doi}",
                             params={"mailto": CONTACT_EMAIL})
        if r.status_code == 404:
            return _empty("openalex")
        r.raise_for_status()
        return _openalex_pack(r.json())
    except Exception as e:
        return _empty("openalex", str(e))


async def openalex_by_title(client: httpx.AsyncClient, title: str) -> dict[str, Any]:
    try:
        r = await client.get(
            f"{OPENALEX_BASE}/works",
            params={"filter": f"title.search:{title}", "per-page": 5, "mailto": CONTACT_EMAIL},
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        best, best_score = None, 0.0
        for w in results:
            cand = w.get("title") or w.get("display_name") or ""
            sc = similarity(title, cand)
            if sc > best_score:
                best, best_score = w, sc
        if not best:
            return _empty("openalex")
        packed = _openalex_pack(best)
        packed["match_score"] = best_score
        packed["found"] = best_score >= 0.85
        return packed
    except Exception as e:
        return _empty("openalex", str(e))


# --- PubMed (NCBI E-utilities) ---------------------------------------------
def _eutils_params(extra: dict) -> dict:
    p = {"db": "pubmed", "retmode": "json", **extra}
    if NCBI_API_KEY:
        p["api_key"] = NCBI_API_KEY
    return p


async def _pubmed_summary(client: httpx.AsyncClient, pmid: str,
                          match_score: float | None = None) -> dict[str, Any]:
    r = await client.get(f"{EUTILS_BASE}/esummary.fcgi", params=_eutils_params({"id": pmid}))
    r.raise_for_status()
    doc = r.json()["result"][pmid]
    doi = None
    for aid in doc.get("articleids", []):
        if aid.get("idtype") == "doi":
            doi = aid.get("value")
    return {
        "source": "pubmed", "found": True, "doi": doi, "title": doc.get("title"),
        "authors": [a.get("name") for a in doc.get("authors", []) if a.get("name")],
        "year": int(doc["pubdate"][:4]) if doc.get("pubdate", "")[:4].isdigit() else None,
        "journal": doc.get("fulljournalname") or doc.get("source"),
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "match_score": match_score, "error": None,
    }


async def pubmed_by_doi(client: httpx.AsyncClient, doi: str) -> dict[str, Any]:
    try:
        r = await client.get(f"{EUTILS_BASE}/esearch.fcgi",
                             params=_eutils_params({"term": f"{doi}[DOI]"}))
        r.raise_for_status()
        ids = r.json()["esearchresult"].get("idlist", [])
        if not ids:
            return _empty("pubmed")
        return await _pubmed_summary(client, ids[0])
    except Exception as e:
        return _empty("pubmed", str(e))


async def pubmed_by_title(client: httpx.AsyncClient, title: str) -> dict[str, Any]:
    try:
        r = await client.get(f"{EUTILS_BASE}/esearch.fcgi",
                             params=_eutils_params({"term": f"{title}[Title]", "retmax": 5}))
        r.raise_for_status()
        ids = r.json()["esearchresult"].get("idlist", [])
        if not ids:
            return _empty("pubmed")
        best = None
        for pmid in ids:
            summ = await _pubmed_summary(client, pmid)
            sc = similarity(title, summ.get("title") or "")
            if best is None or sc > best["match_score"]:
                summ["match_score"] = sc
                best = summ
        best["found"] = best["match_score"] >= 0.85
        return best
    except Exception as e:
        return _empty("pubmed", str(e))


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                            follow_redirects=True)
