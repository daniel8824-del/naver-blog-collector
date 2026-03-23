"""네이버 블로그 본문 추출 - 모바일URL GET → Playwright+stealth → httpx fallback"""

import asyncio
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from nblog.clean import clean_blog_body


MOBILE_BASE = "https://m.blog.naver.com"


@dataclass
class Article:
    """추출된 블로그 글"""
    title: str
    url: str
    content: str
    content_length: int
    method: str  # "mobile-get" | "playwright" | "httpx"
    thumbnail: str = ""
    bloggerName: str = ""
    postdate: str = ""
    images: list[str] = field(default_factory=list)
    success: bool = True
    error: str = ""


def _to_mobile_url(url: str) -> str:
    """PC URL → 모바일 URL 변환. 이미 모바일이면 그대로."""
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")

    # m.blog.naver.com 이미 모바일
    if host == "m.blog.naver.com":
        return url

    # blog.naver.com/blogId/postNo → m.blog.naver.com/blogId/postNo
    if host == "blog.naver.com":
        return f"{MOBILE_BASE}{parsed.path}"

    # PostView 형식: blog.naver.com/PostView.naver?blogId=xxx&logNo=yyy
    if "PostView" in parsed.path or "logNo" in (parsed.query or ""):
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        blog_id = qs.get("blogId", [""])[0]
        log_no = qs.get("logNo", [""])[0]
        if blog_id and log_no:
            return f"{MOBILE_BASE}/{blog_id}/{log_no}"

    return url


def _extract_thumbnail(soup: BeautifulSoup, base_url: str) -> str:
    """HTML에서 썸네일 URL 추출."""
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        img = og["content"]
        if img.startswith("http"):
            return img
        if img.startswith("//"):
            return "https:" + img
        return urljoin(base_url, img)

    tw = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find(
        "meta", attrs={"property": "twitter:image"}
    )
    if tw and tw.get("content"):
        img = tw["content"]
        return img if img.startswith("http") else urljoin(base_url, img)

    return ""


def _extract_blogger_name(soup: BeautifulSoup) -> str:
    """블로거 이름 추출."""
    # 모바일: .nickname, .blog_nickname
    for sel in (".nickname", ".blog_nickname", ".nick", ".writer_info .name"):
        el = soup.select_one(sel)
        if el:
            return el.get_text(strip=True)
    # og:site_name
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return og["content"]
    return ""


def _extract_postdate(soup: BeautifulSoup) -> str:
    """작성일 추출."""
    # 모바일: .se_publishDate, .blog_date, .date
    for sel in (".se_publishDate", ".blog_date", ".date", ".post_date", ".se-date"):
        el = soup.select_one(sel)
        if el:
            return el.get_text(strip=True)
    # meta
    for prop in ("article:published_time", "og:regDate"):
        meta = soup.find("meta", property=prop)
        if meta and meta.get("content"):
            return meta["content"]
    return ""


def _extract_images(soup: BeautifulSoup, container) -> list[str]:
    """본문 내 이미지 URL 추출."""
    images = []
    if not container:
        return images
    for img in container.find_all("img"):
        src = img.get("data-lazy-src") or img.get("data-src") or img.get("src") or ""
        if not src or "blank" in src or "static" in src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("http") and ("pstatic.net" in src or "blogpfthumb" in src or "postfiles" in src):
            images.append(src)
    return images


def _parse_blog_html(html: str, url: str) -> tuple[str, str, str, str, str, list[str]]:
    """HTML에서 제목, 본문, 썸네일, 블로거명, 작성일, 이미지 추출."""
    soup = BeautifulSoup(html, "lxml")

    # 불필요한 태그 제거
    for tag in soup(["script", "style", "iframe", "noscript"]):
        tag.decompose()

    # 제목
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"]
    if not title:
        for sel in (".se-title-text", ".tit_h3", ".pcol1", "h3.tit_view"):
            el = soup.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                break
    if not title:
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        # "네이버 블로그" 접미사 제거
        title = re.sub(r"\s*[:\-|]\s*네이버\s*블로그\s*$", "", title)

    thumbnail = _extract_thumbnail(soup, url)
    blogger_name = _extract_blogger_name(soup)
    postdate = _extract_postdate(soup)

    # ── 본문 추출 (네이버 블로그 에디터 구조) ──
    content = ""
    main_container = None

    # 1. SmartEditor 3 (SE3): se-main-container
    se_main = soup.select_one(".se-main-container")
    if se_main:
        main_container = se_main
        parts = []
        for comp in se_main.select("div.se-component"):
            # 텍스트 컴포넌트
            for text_el in comp.select(".se-text-paragraph"):
                t = text_el.get_text(strip=True)
                if t:
                    parts.append(t)
            # 인용구
            for quote_el in comp.select(".se-quote-text"):
                t = quote_el.get_text(strip=True)
                if t:
                    parts.append(t)
        if parts:
            content = "\n\n".join(parts)

    # 2. SmartEditor 2: #postViewArea, .se_component_wrap
    if len(content) < 50:
        for sel in ("#postViewArea", "#post-view", ".se_component_wrap", ".post-view"):
            el = soup.select_one(sel)
            if el:
                main_container = el
                # p 태그 기반 추출
                paragraphs = el.find_all("p")
                texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 1]
                if texts:
                    content = "\n\n".join(texts)
                if len(content) < 50:
                    content = el.get_text(separator="\n", strip=True)
                if len(content) >= 50:
                    break

    # 3. 모바일 본문 영역
    if len(content) < 50:
        for sel in (".se_textarea", ".post_ct", ".sect_dsc", "#viewTypeSelector", "div.__se_component_area"):
            el = soup.select_one(sel)
            if el:
                main_container = el
                content = el.get_text(separator="\n", strip=True)
                if len(content) >= 50:
                    break

    # 4. article / main 태그 fallback
    if len(content) < 50:
        for tag_name in ("article", "main"):
            el = soup.find(tag_name)
            if el:
                main_container = el
                content = el.get_text(separator="\n", strip=True)
                if len(content) >= 50:
                    break

    # 이미지 추출
    images = _extract_images(soup, main_container)

    # 후처리: 연속 빈 줄
    content = re.sub(r"\n\s*\n+", "\n\n", content).strip()

    # 클리닝 적용
    content = clean_blog_body(content)

    return title, content, thumbnail, blogger_name, postdate, images


def _build_article(
    title: str, url: str, content: str, method: str,
    thumbnail: str = "", blogger_name: str = "", postdate: str = "",
    images: list[str] | None = None,
) -> Article:
    """Article 인스턴스 생성 헬퍼."""
    length = len(content)
    if length < 50:
        return Article(
            title=title, url=url, content=content, content_length=length,
            method=method, thumbnail=thumbnail, bloggerName=blogger_name,
            postdate=postdate, images=images or [], success=False,
            error=f"본문이 너무 짧습니다 ({length}자)",
        )
    return Article(
        title=title, url=url, content=content, content_length=length,
        method=method, thumbnail=thumbnail, bloggerName=blogger_name,
        postdate=postdate, images=images or [],
    )


async def extract_with_mobile_get(url: str) -> Article:
    """모바일 URL로 HTTP GET → HTML 파싱 (가장 빠름, n8n 방식)."""
    mobile_url = _to_mobile_url(url)
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=60.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Mobile/15E148 Safari/604.1"
                ),
                "Referer": "https://section.blog.naver.com/",
                "Accept": "text/html,application/xhtml+xml,application/xml",
                "Accept-Language": "ko-KR,ko;q=0.9",
            },
        ) as client:
            resp = await client.get(mobile_url)
            resp.raise_for_status()
            html = resp.text

        title, content, thumbnail, blogger_name, postdate, images = _parse_blog_html(html, mobile_url)
        return _build_article(title, url, content, "mobile-get", thumbnail, blogger_name, postdate, images)

    except Exception as e:
        return Article(
            title="", url=url, content="", content_length=0,
            method="mobile-get", success=False, error=str(e),
        )


async def extract_with_playwright(url: str) -> Article:
    """Playwright+stealth로 JS 렌더링 후 본문 추출."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return Article(
            title="", url=url, content="", content_length=0,
            method="playwright", success=False,
            error="playwright가 설치되지 않았습니다.",
        )

    mobile_url = _to_mobile_url(url)
    try:
        from playwright_stealth import Stealth

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 412, "height": 915},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Mobile/15E148 Safari/604.1"
                ),
                locale="ko-KR",
                timezone_id="Asia/Seoul",
            )
            page = await context.new_page()

            stealth = Stealth()
            await stealth.apply_stealth_async(page)

            # 이미지 차단 (속도 향상) - 블로그 본문 이미지 URL은 HTML에서 추출
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,eot}",
                lambda route: route.abort(),
            )

            try:
                await page.goto(mobile_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3000)
                try:
                    await page.wait_for_selector(
                        ".se-main-container, #postViewArea, .post-view, "
                        ".se_component_wrap, .__se_component_area",
                        timeout=5000,
                    )
                except Exception:
                    pass
            except Exception:
                pass

            html = await page.content()
            await browser.close()

        title, content, thumbnail, blogger_name, postdate, images = _parse_blog_html(html, mobile_url)
        return _build_article(title, url, content, "playwright", thumbnail, blogger_name, postdate, images)

    except Exception as e:
        return Article(
            title="", url=url, content="", content_length=0,
            method="playwright", success=False, error=str(e),
        )


async def extract_with_httpx(url: str) -> Article:
    """httpx + BeautifulSoup으로 PC URL 직접 추출 (최후 fallback)."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=60.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
                ),
                "Referer": "https://section.blog.naver.com/",
                "Accept": "text/html,application/xhtml+xml,application/xml",
                "Accept-Language": "ko-KR,ko;q=0.9",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        title, content, thumbnail, blogger_name, postdate, images = _parse_blog_html(html, url)
        return _build_article(title, url, content, "httpx", thumbnail, blogger_name, postdate, images)

    except Exception as e:
        return Article(
            title="", url=url, content="", content_length=0,
            method="httpx", success=False, error=str(e),
        )


async def extract_blog(url: str) -> Article:
    """
    네이버 블로그 본문 추출.
    전략: (1) 모바일URL GET → (2) Playwright+stealth → (3) httpx fallback.
    """
    # 1단계: 모바일 URL GET (가장 빠름)
    result = await extract_with_mobile_get(url)
    if result.success and result.content_length >= 100:
        return result

    # 2단계: Playwright + stealth (JS 렌더링)
    pw_result = await extract_with_playwright(url)
    if pw_result.success and pw_result.content_length > (result.content_length or 0):
        return pw_result

    # 3단계: httpx PC URL fallback
    httpx_result = await extract_with_httpx(url)
    if httpx_result.success and httpx_result.content_length > max(
        result.content_length or 0, pw_result.content_length or 0
    ):
        return httpx_result

    # 가장 나은 결과 반환
    candidates = [result, pw_result, httpx_result]
    best = max(candidates, key=lambda a: (a.success, a.content_length))
    return best


def extract_blog_sync(url: str) -> Article:
    """동기 래퍼."""
    return asyncio.run(extract_blog(url))
