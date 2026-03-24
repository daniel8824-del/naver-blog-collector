"""nblog CLI - 네이버 블로그 수집기 명령줄 인터페이스"""

import argparse
import os
import random
import subprocess
import sys
import time
from datetime import datetime as _dt
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn
from rich.table import Table

console = Console()


# ─── search ───


def _parse_queries(args) -> tuple[list[str], int]:
    """쿼리와 건수를 파싱. 'A,B,C' 10 또는 'A,B,C' -n 10 모두 지원."""
    raw_parts = args.query  # nargs="+" 로 받은 리스트
    count = args.count  # -n 값 또는 기본값

    # 마지막 인자가 숫자면 건수로 사용 (positional count)
    if len(raw_parts) > 1 and raw_parts[-1].isdigit():
        count = int(raw_parts[-1])
        raw_parts = raw_parts[:-1]

    # 콤마 구분 키워드 분리
    query_text = " ".join(raw_parts)
    queries = [q.strip() for q in query_text.split(",") if q.strip()]

    return queries, count


def _extract_blog_content(url: str) -> dict:
    """Playwright로 블로그 본문 추출."""
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except ImportError:
        return {"content": "", "success": False, "error": "playwright 미설치"}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            stealth = Stealth()
            stealth.apply_stealth_sync(page)

            # 네이버 블로그는 iframe 내부에 본문이 있음
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)

            content = ""
            title = ""

            # iframe 내부 접근 시도
            frames = page.frames
            for frame in frames:
                try:
                    # 본문 컨테이너 탐색
                    for selector in [
                        ".se-main-container",       # 스마트에디터 3
                        ".se_component_wrap",        # 스마트에디터 2
                        "#postViewArea",             # 구형 에디터
                        ".post-view",                # 모바일
                        "#content-area",
                    ]:
                        el = frame.query_selector(selector)
                        if el:
                            content = el.inner_text().strip()
                            break
                    # 제목
                    for sel in [".se-title-text", ".pcol1", ".tit_h3", "h3.se_textarea"]:
                        el = frame.query_selector(sel)
                        if el:
                            title = el.inner_text().strip()
                            break
                    if content:
                        break
                except Exception:
                    continue

            # iframe 실패 시 메인 페이지에서 시도
            if not content:
                for selector in [
                    ".se-main-container",
                    "#postViewArea",
                    ".blog_view_content",
                    "div.post_ct",
                ]:
                    el = page.query_selector(selector)
                    if el:
                        content = el.inner_text().strip()
                        break

            browser.close()

            return {
                "title": title,
                "content": content,
                "content_length": len(content),
                "success": bool(content),
                "error": "" if content else "본문을 찾을 수 없음",
            }

    except Exception as e:
        return {"content": "", "success": False, "error": str(e)[:200]}



def cmd_search(args):
    """블로그 검색 + 본문 추출 + CSV 저장."""
    from nblog.search import search_blogs

    queries, count = _parse_queries(args)

    if len(queries) > 1:
        console.print(f"\n[bold blue]멀티 키워드 검색[/bold blue] {len(queries)}개: {', '.join(queries)}")
    else:
        console.print(f"\n[bold blue]네이버 블로그 검색 중...[/bold blue] '{queries[0]}'")
    sort = "sim" if getattr(args, "relevance", False) else "date"
    console.print(f"  키워드당 {count}건 / 정렬: {'관련성순' if sort == 'sim' else '최신순'}", style="dim")

    # 1단계: 검색 (키워드별 실행 후 병합)
    results = []
    seen_urls = set()
    for qi, query in enumerate(queries, 1):
        if len(queries) > 1:
            console.print(f"\n  [cyan][{qi}/{len(queries)}][/cyan] '{query}' 검색 중...")
        try:
            hits = search_blogs(query=query, count=count, sort=sort)
        except SystemExit as e:
            console.print(str(e))
            return

        for r in hits:
            if r.link not in seen_urls:
                seen_urls.add(r.link)
                results.append((query, r))

        if len(queries) > 1:
            console.print(f"    [green]{len(hits)}건[/green]")

    if not results:
        console.print("[yellow]검색 결과가 없습니다.[/yellow]")
        return

    console.print(f"\n  [green]총 {len(results)}건 검색 완료[/green] (중복 제거 후)")

    # 2단계: 본문 추출 (Playwright, 배치 순차)
    articles = []
    extraction_targets = []

    for i, (keyword, r) in enumerate(results):
        article_data = {
            "keyword": keyword,
            "title": r.title,
            "url": r.link,
            "bloggerName": r.bloggerName,
            "postdate": r.postdate,
            "description": r.description,
            "method": "",
            "content": "",
            "content_length": 0,
            "success": True,
        }
        articles.append(article_data)
        if not args.fast:
            extraction_targets.append((i, r.link))
            console.print(f"  [{i+1}/{len(results)}] [dim]본문 추출 예정: {r.title[:40]}...[/dim]")

    if extraction_targets:
        # 최대 200건 제한
        MAX_ITEMS = 200
        if len(extraction_targets) > MAX_ITEMS:
            console.print(f"  [yellow]추출 대상 {len(extraction_targets)}건 → 최대 {MAX_ITEMS}건으로 제한[/yellow]")
            extraction_targets = extraction_targets[:MAX_ITEMS]

        BATCH_SIZE = 10
        batches = [
            extraction_targets[i:i + BATCH_SIZE]
            for i in range(0, len(extraction_targets), BATCH_SIZE)
        ]
        total = len(extraction_targets)
        console.print(f"\n  [cyan]{total}건 본문 추출 중...[/cyan] ({len(batches)}배치 × 최대{BATCH_SIZE}건)")

        success_count = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("[dim]{task.fields[status]}[/dim]"),
            console=console,
        ) as progress:
            task = progress.add_task("본문 추출", total=total, status="")

            for bi, batch in enumerate(batches, 1):
                progress.update(task, status=f"배치 {bi}/{len(batches)}")

                for idx, url in batch:
                    extracted = _extract_blog_content(url)
                    if extracted.get("success"):
                        articles[idx]["content"] = extracted["content"]
                        articles[idx]["content_length"] = extracted.get("content_length", 0)
                        success_count += 1
                    else:
                        articles[idx]["success"] = False
                        articles[idx]["content"] = articles[idx]["description"]
                        articles[idx]["content_length"] = len(articles[idx]["description"])

                    progress.advance(task)
                    # 요청 간 1~2초 랜덤 딜레이
                    time.sleep(random.uniform(1, 2))

                # 배치 완료 후 2초 대기 (마지막 배치 제외)
                if bi < len(batches):
                    progress.update(task, status=f"배치 {bi} 완료, 대기 중...")
                    time.sleep(2)

        console.print(f"  [green]{success_count}/{total}건 추출 성공[/green]")

    # 3단계: 결과 출력
    table = Table(title="네이버 블로그 검색 결과")
    table.add_column("#", style="dim", width=4)
    table.add_column("제목", max_width=40)
    table.add_column("블로거", width=12)
    table.add_column("날짜", width=10)
    table.add_column("글자수", justify="right", width=7)

    for i, a in enumerate(articles, 1):
        date_str = a.get("postdate", "")
        if len(date_str) == 8:
            date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        table.add_row(
            str(i),
            a["title"][:40],
            a.get("bloggerName", "")[:12],
            date_str,
            str(a.get("content_length", 0)),
        )

    console.print(table)

    # 4단계: CSV 자동 저장
    query_label = queries[0] if len(queries) == 1 else ",".join(queries)
    slug = query_label.replace(" ", "_").replace(",", "_")[:20]
    timestamp = _dt.now().strftime("%Y%m%d_%H%M")
    filename = getattr(args, "file", None) or f"blog_{slug}_{timestamp}.csv"
    if not filename.endswith(".csv"):
        filename += ".csv"

    # WSL이면 Windows 다운로드 폴더 우선
    win_downloads = Path("/mnt/c/Users") / os.getenv("USER", "daniel") / "Downloads"
    linux_downloads = Path.home() / "Downloads"
    if win_downloads.is_dir():
        downloads = win_downloads
    elif linux_downloads.is_dir():
        downloads = linux_downloads
    else:
        downloads = Path.home()
    save_path = str(downloads / filename)

    from nblog.output import to_csv, to_txt
    to_csv(articles, save_path, query_label)
    txt_path = save_path.rsplit(".", 1)[0] + ".txt"
    to_txt(articles, txt_path, query_label)
    console.print(f"  총 {len(articles)}건 수집 완료\n")


# ─── extract ───


def cmd_extract(args):
    """단일 URL에서 블로그 본문 추출."""
    if not args.url:
        console.print("[red]URL을 지정하세요.[/red]")
        return

    console.print(f"\n[bold blue]블로그 본문 추출 중...[/bold blue] {args.url}")

    result = _extract_blog_content(args.url)

    if result.get("success"):
        console.print(f"\n[green]추출 성공[/green] ({result.get('content_length', 0)}자)\n")
        console.print(result.get("content", "")[:2000])
        if result.get("content_length", 0) > 2000:
            console.print(f"\n[dim]... ({result['content_length'] - 2000}자 더 있음)[/dim]")
    else:
        console.print(f"[red]추출 실패:[/red] {result.get('error', '알 수 없는 오류')}")

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(result.get("content", ""))
        console.print(f"\n[green]저장 완료:[/green] {args.save}")


# ─── setup ───


def cmd_setup(args):
    """초기 설정: 네이버 API 키 입력 + Playwright 브라우저 설치."""
    console.print("\n[bold blue]nblog 초기 설정[/bold blue]\n")

    # ── 1. 네이버 API 키 설정 ──
    target = Path.home() / ".env"
    existing = {}
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()

    console.print("[bold]1. 네이버 검색 API 키[/bold] (필수)")
    console.print("   발급: https://developers.naver.com/apps")
    console.print("   → 애플리케이션 등록 → 검색 API 선택\n")

    # Client ID
    current_id = existing.get("NAVER_CLIENT_ID", "")
    if current_id:
        masked = f"{current_id[:4]}...{current_id[-4:]}"
        console.print(f"   Client ID 현재: {masked}")
        id_input = input("   새 Client ID (Enter=유지): ").strip()
        naver_id = id_input if id_input else current_id
    else:
        naver_id = input("   Client ID 입력: ").strip()

    # Client Secret
    current_secret = existing.get("NAVER_CLIENT_SECRET", "")
    if current_secret:
        masked = f"{current_secret[:4]}...{current_secret[-4:]}"
        console.print(f"   Client Secret 현재: {masked}")
        secret_input = input("   새 Client Secret (Enter=유지): ").strip()
        naver_secret = secret_input if secret_input else current_secret
    else:
        naver_secret = input("   Client Secret 입력: ").strip()

    # 저장
    lines = []
    if naver_id:
        lines.append(f"NAVER_CLIENT_ID={naver_id}")
    if naver_secret:
        lines.append(f"NAVER_CLIENT_SECRET={naver_secret}")
    for k, v in existing.items():
        if k not in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"):
            lines.append(f"{k}={v}")

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if naver_id and naver_secret:
        console.print(f"\n[green]OK[/green] 네이버 API 키 저장됨")

    # ── 2. Playwright 브라우저 설치 ──
    console.print(f"\n[bold]2. Playwright Chromium 설치[/bold]")
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=False,
    )
    if result.returncode == 0:
        console.print("[green]OK[/green] 브라우저 설치 완료")
    else:
        console.print("[red]FAIL[/red] 브라우저 설치 실패. 직접 실행: playwright install chromium")

    console.print("\n[bold]설정 완료! 바로 사용하세요:[/bold]")
    console.print('  nblog search "맛집 추천" 10')
    console.print()


# ─── doctor ───


def cmd_doctor(args):
    """환경 설정 상태 점검."""
    console.print(f"\n[bold blue]nblog 환경 점검[/bold blue] [dim]v0.1.0[/dim]\n")

    # 네이버 API 키
    client_id = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")

    if client_id and client_secret:
        masked_id = f"{client_id[:4]}...{client_id[-4:]}" if len(client_id) > 8 else "(설정됨)"
        console.print(f"[green]OK[/green] NAVER_CLIENT_ID: {masked_id}")
        console.print(f"[green]OK[/green] NAVER_CLIENT_SECRET: (설정됨)")
    elif client_id:
        console.print(f"[green]OK[/green] NAVER_CLIENT_ID: (설정됨)")
        console.print("[red]FAIL[/red] NAVER_CLIENT_SECRET: 설정되지 않음")
    else:
        console.print("[red]FAIL[/red] NAVER_CLIENT_ID: 설정되지 않음")
        console.print("[red]FAIL[/red] NAVER_CLIENT_SECRET: 설정되지 않음")

    # Playwright
    playwright_ok = False
    browser_ok = False
    browser_path = ""

    try:
        from playwright.sync_api import sync_playwright

        playwright_ok = True
        console.print("[green]OK[/green] playwright 패키지: 설치됨")

        with sync_playwright() as p:
            browser_path = p.chromium.executable_path
        browser_ok = bool(browser_path) and Path(browser_path).exists()
    except ImportError:
        console.print("[red]FAIL[/red] playwright 패키지: 가져올 수 없음")
    except Exception:
        browser_ok = False

    if playwright_ok and browser_ok:
        console.print(f"[green]OK[/green] Chromium 브라우저: 설치됨 [dim]({browser_path})[/dim]")
    elif playwright_ok:
        console.print("[yellow]WARN[/yellow] Chromium 브라우저: 아직 설치되지 않음")
        console.print("      해결: nblog setup")

    # KoNLPy
    try:
        import konlpy
        console.print("[green]OK[/green] konlpy 패키지: 설치됨")
    except ImportError:
        console.print("[yellow]WARN[/yellow] konlpy 패키지: 설치되지 않음 (텍스트마이닝 사용 불가)")

    console.print("\n[bold]추천 시작 명령[/bold]")
    console.print("  nblog setup")
    console.print('  nblog search "맛집 추천"')
    console.print('  nblog search "서울 카페,부산 맛집" 5')
    console.print("  nblog extract https://blog.naver.com/xxx/yyy")
    console.print()


# ─── main ───


def main():
    """CLI 진입점."""
    load_dotenv()
    home_env = Path.home() / ".env"
    if home_env.exists():
        load_dotenv(home_env)

    parser = argparse.ArgumentParser(
        prog="nblog",
        description="네이버 블로그 수집기 - 검색 + 본문 추출 + 저장",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  nblog setup                                 최초 설정 (API 키 + 브라우저)
  nblog doctor                                환경 점검
  nblog search "맛집 추천"                    검색 + CSV 자동 저장
  nblog search "서울 카페,부산 맛집" 5        멀티 키워드, 5건
  nblog search "파이썬" -sort sim             정확도순
  nblog extract https://blog.naver.com/xxx/yyy  단일 URL 본문 추출
        """,
    )
    parser.add_argument("-v", "--version", action="version", version="nblog 0.1.0")

    sub = parser.add_subparsers(dest="command", help="명령어")

    # search
    p_search = sub.add_parser("search", help="블로그 검색 + 본문 추출 + CSV 저장")
    p_search.add_argument("query", nargs="+", help="검색어 (콤마로 멀티 키워드, 마지막 숫자는 건수)")
    p_search.add_argument("-n", "--count", type=int, default=10, help="키워드당 검색 건수 (기본: 10)")
    p_search.add_argument("-r", action="store_true", dest="relevance", help="관련성순 정렬 (기본: 최신순)")
    p_search.add_argument("-f", dest="file", help="저장 파일명")
    p_search.add_argument("-fast", action="store_true", help="본문 추출 생략 (검색 결과만)")
    p_search.set_defaults(func=cmd_search)

    # collect (별칭)
    p_collect = sub.add_parser("collect", help="search와 동일")
    p_collect.add_argument("query", nargs="+", help="검색어")
    p_collect.add_argument("-n", "--count", type=int, default=10, help="키워드당 검색 건수")
    p_collect.add_argument("-r", action="store_true", dest="relevance", help="관련성순 정렬")
    p_collect.add_argument("-f", dest="file", help="저장 파일명")
    p_collect.add_argument("-fast", action="store_true", help="본문 추출 생략")
    p_collect.set_defaults(func=cmd_search)

    # extract
    p_extract = sub.add_parser("extract", help="URL에서 블로그 본문 추출")
    p_extract.add_argument("url", nargs="?", help="추출할 블로그 URL")
    p_extract.add_argument("-s", "--save", help="저장 파일 경로")
    p_extract.set_defaults(func=cmd_extract)

    # setup
    p_setup = sub.add_parser("setup", help="초기 설정 (API 키 + 브라우저 설치)")
    p_setup.set_defaults(func=cmd_setup)

    # doctor
    p_doctor = sub.add_parser("doctor", help="환경 점검")
    p_doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
