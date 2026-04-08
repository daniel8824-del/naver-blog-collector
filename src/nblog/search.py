"""네이버 블로그 검색 API 모듈"""

import os
import re
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urlparse, parse_qs

import httpx
from dotenv import load_dotenv


@dataclass
class BlogResult:
    """블로그 검색 결과 하나"""
    title: str
    link: str
    description: str = ""
    bloggerName: str = ""
    bloggerLink: str = ""
    postdate: str = ""


def _strip_html(text: str) -> str:
    """HTML 태그 제거 + 엔티티 디코드."""
    return unescape(re.sub(r"<[^>]+>", "", text))


def _normalize_url(url: str) -> str:
    """모바일 URL → PC URL 변환, 중복 방지용 정규화."""
    # m.blog.naver.com/PostView.naver?blogId=xxx&logNo=yyy
    # → blog.naver.com/xxx/yyy
    parsed = urlparse(url)

    if parsed.netloc == "m.blog.naver.com":
        # 패턴 1: m.blog.naver.com/PostView.naver?blogId=xxx&logNo=yyy
        if "PostView" in parsed.path:
            qs = parse_qs(parsed.query)
            blog_id = qs.get("blogId", [""])[0]
            log_no = qs.get("logNo", [""])[0]
            if blog_id and log_no:
                return f"https://blog.naver.com/{blog_id}/{log_no}"
        # 패턴 2: m.blog.naver.com/xxx/yyy
        return url.replace("m.blog.naver.com", "blog.naver.com")

    return url


def search_blogs(
    query: str,
    count: int = 100,
    sort: str = "date",
) -> list[BlogResult]:
    """
    네이버 블로그 검색 API로 블로그 글 검색.

    Args:
        query: 검색어
        count: 최대 결과 수 (최대 100, API 제한)
        sort: 정렬 기준 - "date"(최신순) 또는 "sim"(정확도순)

    Returns:
        BlogResult 리스트 (URL 중복 제거 완료)
    """
    home_env = os.path.expanduser("~/.env")
    if os.path.exists(home_env):
        load_dotenv(home_env)
    load_dotenv()

    client_id = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        raise SystemExit(
            "\n[오류] 네이버 API 키가 설정되지 않았습니다.\n\n"
            "설정 방법 (택 1):\n"
            "  1) 환경변수:\n"
            "     export NAVER_CLIENT_ID=...\n"
            "     export NAVER_CLIENT_SECRET=...\n"
            "  2) .env 파일:\n"
            "     NAVER_CLIENT_ID=...\n"
            "     NAVER_CLIENT_SECRET=...\n\n"
            "API 키 발급: https://developers.naver.com/apps\n"
            "  → 애플리케이션 등록 → 검색 API 선택\n"
        )

    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    results: list[BlogResult] = []
    seen_urls: set[str] = set()

    # API는 한 번에 최대 100건, start는 1~1000
    # 외부 블로그 필터링으로 결과가 줄 수 있으므로 충분히 가져옴
    start = 1
    per_page = min(count * 2, 100)  # 필터링 감안해 2배 요청

    while len(results) < count:
        params = {
            "query": query,
            "display": str(per_page),
            "start": str(start),
            "sort": sort,
        }

        resp = httpx.get(
            "https://openapi.naver.com/v1/search/blog",
            headers=headers,
            params=params,
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        if not items:
            break

        for item in items:
            link = _normalize_url(item.get("link", ""))
            if link in seen_urls:
                continue
            # 네이버 블로그만 수집 (티스토리 등 외부 블로그 제외)
            parsed_link = urlparse(link)
            if parsed_link.netloc not in ("blog.naver.com", "m.blog.naver.com"):
                continue
            seen_urls.add(link)

            # 제목 또는 설명에 검색어 핵심 단어가 포함된 글만 수집
            title_text = _strip_html(item.get("title", ""))
            desc_text = _strip_html(item.get("description", ""))
            query_core = query.replace('"', '').strip()
            if query_core not in title_text and query_core not in desc_text:
                continue

            results.append(BlogResult(
                title=title_text,
                link=link,
                description=desc_text,
                bloggerName=item.get("bloggername", ""),
                bloggerLink=item.get("bloggerlink", ""),
                postdate=item.get("postdate", ""),
            ))

            if len(results) >= count:
                break

        start += per_page

        # API 총 결과 수 확인 / 페이징 한계
        total = data.get("total", 0)
        if start > min(total, 1000) or len(items) < per_page:
            break

    return results[:count]
