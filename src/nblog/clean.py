"""
네이버 블로그 본문 텍스트 클리닝 - n8n Blog Cleaning 로직 Python 포팅.

처리 순서:
1. HTML 태그/엔티티 정리
2. 이모지 제거
3. 해시태그 라인 감지/제거 (#비율 5% 이상)
4. 본문 시작점 찾기 (신고하기 패턴 이후)
5. 광고/푸터/공유버튼 제거
6. 블로그 특화 노이즈 제거 (위젯, 이웃추가, 공감, 댓글, 카테고리)
7. 연속 공백/빈줄 정리
"""

import re
from html import unescape


def clean_blog_body(html_or_text: str) -> str:
    """
    네이버 블로그 본문을 정제합니다.

    Args:
        html_or_text: 원본 텍스트 또는 HTML (추출기에서 text 변환 후 전달)

    Returns:
        정제된 본문 텍스트
    """
    if not html_or_text or not isinstance(html_or_text, str):
        return ""
    if len(html_or_text) < 30:
        return html_or_text

    text = html_or_text

    # ══════════════════════════════════════
    # 선행: Zero-Width 문자 즉시 제거 (후속 정규식 매칭 정확도 향상)
    # ══════════════════════════════════════
    text = re.sub("[\u200b\u200c\u200d\u200e\u200f\ufeff\u00a0\u2060\u2028\u2029]", "", text)

    # ══════════════════════════════════════
    # 0단계: script/style 태그 통째 제거 (n8n Blog Cleaning 필수)
    # ══════════════════════════════════════
    text = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<noscript\b[^<]*(?:(?!</noscript>)<[^<]*)*</noscript>", "", text, flags=re.IGNORECASE)

    # ══════════════════════════════════════
    # 1단계: HTML 태그/엔티티 정리
    # ══════════════════════════════════════
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:p|div|li|h[1-6]|blockquote|section|article)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    # HTML 엔티티 잔재
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"\xa0", " ", text)  # &nbsp;

    # ══════════════════════════════════════
    # 2단계: 이모지 제거
    # ══════════════════════════════════════
    text = re.sub(r"[\U0001F300-\U0001F9FF]", "", text)  # Misc Symbols & Pictographs ~ Supplemental
    text = re.sub(r"[\U0001FA00-\U0001FA6F]", "", text)  # Chess Symbols
    text = re.sub(r"[\U0001FA70-\U0001FAFF]", "", text)  # Symbols and Pictographs Extended-A
    text = re.sub(r"[\u2600-\u26FF]", "", text)           # Misc Symbols
    text = re.sub(r"[\u2700-\u27BF]", "", text)           # Dingbats
    text = re.sub(r"[\uFE00-\uFE0F]", "", text)           # Variation Selectors
    text = re.sub(r"[\u200D]", "", text)                   # Zero Width Joiner
    text = re.sub(r"[\u20E3]", "", text)                   # Combining Enclosing Keycap

    # ══════════════════════════════════════
    # 3단계: 본문 시작점 찾기 (n8n: 신고하기 패턴 이후)
    # ══════════════════════════════════════
    # 네이버 블로그 상단: "공유하기 신고하기" 이후가 실제 본문
    share_report = re.search(r"공유하기\s*신고하기", text)
    if share_report and share_report.start() < len(text) * 0.3:
        text = text[share_report.end():]

    # "URL 복사 이웃추가" 패턴
    url_copy = re.search(r"URL\s*복사\s*이웃추가", text)
    if url_copy and url_copy.start() < len(text) * 0.3:
        text = text[url_copy.end():]

    # 블로그 헤더 노이즈: "본문 기타 기능" 이후
    etc_func = re.search(r"본문\s*기타\s*기능", text)
    if etc_func and etc_func.start() < len(text) * 0.3:
        text = text[etc_func.end():]

    # ══════════════════════════════════════
    # 4단계: 라인 단위 처리
    # ══════════════════════════════════════
    lines = text.split("\n")
    filtered = []

    for line in lines:
        line = line.strip()
        if not line:
            filtered.append("")
            continue

        # ── 해시태그 라인 감지 (n8n: # 비율 5% 이상이면 제거) ──
        if "#" in line:
            hash_count = line.count("#")
            total_len = len(line.replace(" ", ""))
            if total_len > 0 and hash_count / total_len >= 0.05:
                # 해시태그 밀집 라인
                if re.search(r"#[가-힣a-zA-Z0-9_]+", line):
                    continue

        # ── 광고/프로모션 패턴 ──
        if re.search(
            r"(체험단|원고료|소정의\s*원고|광고\s*포함|제공\s*받아|협찬|제휴|"
            r"이\s*글은\s*.*?지원.*?작성|본\s*포스팅은\s*.*?일환)",
            line,
        ):
            continue

        # ── 블로그 위젯/UI 노이즈 ──
        if re.match(
            r"^(이웃추가|팬하기|블로그 홈|블로그 관리|글쓰기|메뉴 바로가기|"
            r"본문 바로가기|블로그 카테고리|전체보기|카테고리 이동|"
            r"댓글\s*\d*|공감\s*\d*|좋아요\s*\d*|공유하기|구독하기|"
            r"블로그 앱으로 보기|블로그 앱에서 열기|"
            r"인쇄|스크랩|서재에 담기|내 블로그|이 블로그|"
            r"블로그 검색|이 글에 공감한|레이어 닫기|"
            r"통계|방문자|전체 방문|오늘|어제)$",
            line,
        ):
            continue

        # ── 이웃/공감/댓글 영역 ──
        if re.search(r"(이웃으로\s*추가|이웃\s*목록|공감한\s*사람|공감\s*보내기)", line):
            continue

        # ── 공유 버튼 영역 ──
        if re.match(r"^(페이스북|트위터|카카오스토리|밴드|네이버|URL\s*복사)\s*$", line):
            continue
        if re.search(r"(카카오톡으로\s*공유|페이스북으로\s*공유|트위터로\s*공유|밴드로\s*공유)", line):
            continue

        # ── 카테고리/네비게이션 ──
        if re.match(r"^(이전글|다음글|목록으로|맨\s*위로|TOP)$", line):
            continue
        if re.match(r"^[가-힣/\s]+카테고리의\s*다른\s*글$", line):
            continue
        if re.match(r"^태그\s*:", line):
            continue

        # ── 댓글 영역 ──
        if re.search(r"(댓글을\s*입력|댓글\s*등록|비밀\s*댓글|등록\s*취소)", line):
            continue
        if re.match(r"^댓글\s*\d+$", line):
            continue

        # ── 푸터/저작권 ──
        if re.search(r"(저작권자|무단\s*(전재|복제|배포)|All Rights Reserved)", line, re.IGNORECASE):
            continue
        if re.search(r"Copyright", line, re.IGNORECASE) and len(line) < 100:
            continue

        # ── 구독/알림 ──
        if re.search(r"(새\s*글\s*알림|구독\s*알림|이메일\s*구독|RSS\s*구독)", line):
            continue

        # ── 네이버 블로그 하단 UI ──
        if re.match(r"^(블로그 정보|블로그 소개|프로필|닉네임|포스트|방명록)\s*$", line):
            continue

        # ── 지도/위치 위젯 ──
        if re.match(r"^(지도\s*크게\s*보기|지도를\s*클릭|네이버\s*지도|길찾기)\s*$", line):
            continue
        if re.match(r"^[가-힣\s]+동\s*\d+[-\d]*\s*$", line):
            continue

        # ── 매우 짧은 노이즈 라인 ──
        if len(line) <= 2 and not re.search(r"[가-힣]", line):
            continue

        # ── 특수 기호만 ──
        if re.match(r"^[▶▷●◆■★※▲▼→←↑↓♥♡✓✔☞◎·\-=_~.·ㆍ\s]+$", line):
            continue

        # ── 숫자만 ──
        if re.match(r"^\d+\.?\s*$", line):
            continue

        filtered.append(line)

    # ══════════════════════════════════════
    # 5단계: 끝부분 노이즈 제거
    # ══════════════════════════════════════
    # 뒤에서부터 노이즈 라인 잘라내기
    while filtered and _is_tail_noise(filtered[-1]):
        filtered.pop()

    text = "\n".join(filtered)

    # ══════════════════════════════════════
    # 6단계: 최종 후처리
    # ══════════════════════════════════════
    # URL 제거
    text = re.sub(r"https?://[^\s)]+", "", text)
    # 특수 기호 정리
    text = re.sub(r"[▶▷●◆■★※▲▼→←↑↓#♥♡✓✔☞◎]", "", text)
    text = re.sub(r"[|│┃]+", "", text)
    # 마크다운 잔재
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"={4,}", "", text)
    text = re.sub(r"-{4,}", "", text)
    text = re.sub(r"```", "", text)
    # 마크다운 링크
    text = re.sub(r"\[[^\]]+\]\([^\)]+\)", "", text)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Zero-Width Space 및 보이지 않는 문자 제거 (이미지 자리 잔재)
    text = re.sub("[\u200b\u200c\u200d\u200e\u200f\ufeff\u00a0]", "", text)
    # 공백 정리
    text = re.sub(r"\n{2,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"^\s+$", "", text, flags=re.MULTILINE)
    # 빈 줄 재정리 (위에서 빈 줄만 남은 라인 제거 후)
    text = re.sub(r"\n{2,}", "\n\n", text)
    text = text.strip()

    if len(text) < 20:
        return ""

    return text


def _is_tail_noise(line: str) -> bool:
    """뒤에서부터 제거할 노이즈 라인인지 판별."""
    if not line or not line.strip():
        return True
    line = line.strip()

    # 빈 줄
    if not line:
        return True

    # 공감/댓글 숫자
    if re.match(r"^(공감|좋아요|댓글)\s*\d*$", line):
        return True

    # 공유 버튼
    if re.match(r"^(페이스북|트위터|카카오|밴드|네이버|URL\s*복사)$", line):
        return True

    # 구독/이웃
    if re.match(r"^(구독하기|이웃추가|팬하기)$", line):
        return True

    # 블로그 정보
    if re.match(r"^(블로그 정보|프로필|닉네임|포스트|방명록)\s*$", line):
        return True

    # 숫자만
    if re.match(r"^\d+\.?\s*$", line):
        return True

    # 특수문자만
    if re.match(r"^[▶▷●◆■★※▲▼→←↑↓♥♡✓✔☞◎·\-=_~.\s]+$", line):
        return True

    return False
