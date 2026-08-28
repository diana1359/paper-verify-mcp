"""
server.py
---------
논문이 PubMed / Crossref / OpenAlex 에 실제로 존재하는지 검증하는 MCP 서버.
Streamable HTTP 전송으로 노출되며, Claude 커스텀 커넥터로 등록해서 쓴다.

로컬 실행:      python server.py
기본 엔드포인트: http://0.0.0.0:8000/mcp/
"""

from __future__ import annotations

import os
import asyncio
from typing import Any

from fastmcp import FastMCP

import sources as S

mcp = FastMCP(
    name="paper-verifier",
    instructions=(
        "Verify whether an academic paper actually exists by cross-checking "
        "PubMed, Crossref, and OpenAlex. Use this to catch fabricated or "
        "hallucinated citations before trusting them."
    ),
)


def _verdict(results: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    """세 소스 결과를 모아 최종 판정을 만든다."""
    confirming = [r for r in results if r.get("found")]
    errored = [r for r in results if r.get("error")]

    # DOI 조회: 한 곳이라도 확인되면 실재로 본다 (색인 시차 존재).
    # 제목 조회: 유사도 기반이므로 동일하게 처리하되 점수를 함께 노출한다.
    exists = len(confirming) >= 1

    if exists:
        verdict = "LIKELY_REAL" if len(confirming) >= 2 else "POSSIBLY_REAL"
    elif len(errored) == len(results):
        verdict = "UNKNOWN"  # 전부 조회 실패 -> 판단 불가
    else:
        verdict = "NOT_FOUND"

    return {
        "verdict": verdict,
        "confirmed_by": [r["source"] for r in confirming],
        "checked": len(results),
        "mode": mode,
        "sources": results,
        "note": _note(verdict, confirming),
    }


def _note(verdict: str, confirming: list[dict]) -> str:
    if verdict == "LIKELY_REAL":
        return "여러 데이터베이스에서 확인됨. 실재하는 논문일 가능성이 높음."
    if verdict == "POSSIBLY_REAL":
        return ("한 곳에서만 확인됨. 색인 시차이거나 제목 유사도 매칭일 수 있으니 "
                "메타데이터(저자/연도/저널)를 함께 대조할 것.")
    if verdict == "UNKNOWN":
        return "모든 데이터베이스 조회에 실패함. 네트워크/요청 한도 문제일 수 있음. 재시도 권장."
    return "세 데이터베이스 어디에서도 찾지 못함. 환각/오기재 인용일 가능성이 있음."


@mcp.tool
async def verify_by_doi(doi: str) -> dict[str, Any]:
    """Verify a paper by its DOI across PubMed, Crossref, and OpenAlex.

    Args:
        doi: The DOI, e.g. "10.1038/nature12373" (with or without a URL prefix).

    Returns a verdict plus per-source metadata (title, authors, year, journal, url).
    """
    doi = (doi or "").strip()
    for pre in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(pre):
            doi = doi[len(pre):]
    if not doi:
        return {"verdict": "UNKNOWN", "error": "empty DOI"}

    async with S.new_client() as client:
        results = await asyncio.gather(
            S.crossref_by_doi(client, doi),
            S.openalex_by_doi(client, doi),
            S.pubmed_by_doi(client, doi),
        )
    return _verdict(list(results), mode="doi")


@mcp.tool
async def verify_by_title(title: str, author: str = "", year: int = 0) -> dict[str, Any]:
    """Verify a paper by title (optionally author/year) across the three databases.

    Matching is fuzzy: each source returns its best candidate with a
    match_score (0-1). Scores >= 0.85 count as a match. Always compare the
    returned metadata against the citation you are checking.

    Args:
        title: The paper title.
        author: Optional author surname to help disambiguate (currently informational).
        year: Optional publication year to help disambiguate (currently informational).
    """
    title = (title or "").strip()
    if not title:
        return {"verdict": "UNKNOWN", "error": "empty title"}

    async with S.new_client() as client:
        results = await asyncio.gather(
            S.crossref_by_title(client, title),
            S.openalex_by_title(client, title),
            S.pubmed_by_title(client, title),
        )
    out = _verdict(list(results), mode="title")
    out["query"] = {"title": title, "author": author or None, "year": year or None}
    return out


@mcp.tool
async def check_citation(citation: str) -> dict[str, Any]:
    """Verify a free-form citation string. Auto-detects a DOI if present,
    otherwise treats the longest quoted/plain segment as a title.

    Args:
        citation: A raw reference string, e.g.
            'Smith J. Deep learning for X. Nature. 2021. doi:10.1038/xxxxx'
    """
    citation = (citation or "").strip()
    if not citation:
        return {"verdict": "UNKNOWN", "error": "empty citation"}

    doi = S.extract_doi(citation)
    if doi:
        result = await verify_by_doi.fn(doi)
        result["detected"] = {"doi": doi}
        return result

    # DOI 가 없으면 제목 후보를 추출: 따옴표 안 문자열 우선, 없으면 가장 긴 문장 조각.
    import re
    m = re.search(r'[""\"]([^""\"]{10,})[""\"]', citation)
    if m:
        title = m.group(1)
    else:
        segments = re.split(r"[.;]\s+", citation)
        title = max(segments, key=len).strip() if segments else citation
    result = await verify_by_title.fn(title)
    result["detected"] = {"title": title}
    return result


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    # transport="http" -> Streamable HTTP. 엔드포인트: /mcp/
    mcp.run(transport="http", host=host, port=port)
