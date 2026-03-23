# nblog - 네이버 블로그 수집기 (Python Learn Friendly)

파이썬 설치나 복잡한 환경 설정 없이, **한 줄의 명령어로 네이버 블로그를 검색하고 본문을 추출해서 CSV로 저장**하고 싶으신가요?
`nblog`는 네이버 블로그 검색 API와 Playwright stealth 본문 추출을 결합하여, 누구나 손쉽게 블로그 데이터를 수집하고 텍스트 마이닝까지 할 수 있도록 설계된 도구입니다.

---

## 🌟 주요 특징

- **네이버 공식 API 검색:** 네이버 블로그 검색 API를 사용하여 정확하고 빠르게 블로그 글을 찾습니다.
- **Playwright stealth 본문 추출:** iframe 안에 숨겨진 네이버 블로그 본문도 스마트에디터 2/3, 구형 에디터 모두 지원하여 깔끔하게 추출합니다.
- **봇 차단 방지:** 10건 배치 + 1~2초 랜덤 딜레이 + Referer/Accept 헤더 + Playwright stealth로 안정적으로 수집합니다.
- **CSV 자동 저장:** 수집 결과를 `~/Downloads/blog_키워드_날짜.csv`에 자동 저장하여 엑셀에서 바로 분석할 수 있습니다.
- **텍스트 마이닝:** TF-IDF 키워드 추출, LDA 토픽 모델링, 감성분석, 워드클라우드까지 한 번에 돌릴 수 있습니다.

---

## 🚀 5분 완성! 단계별 설치 및 설정 가이드

스크린샷 없이도 따라 할 수 있도록 차근차근 안내해 드립니다.

### 1단계: 'uv' 도구 설치
`uv`는 파이썬 버전을 자동으로 관리해 주는 가장 빠르고 편리한 도구입니다. 터미널(또는 CMD/PowerShell)을 열고 아래 명령어를 입력하세요.

- **Mac/Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
*(설치 후 터미널을 껐다가 다시 켜야 `uv` 명령어가 인식될 수 있습니다.)*

### 2단계: `nblog` 프로그램 설치
이제 `uv`를 이용해 `nblog`를 시스템에 등록합니다.

```bash
# 최신 버전 바로 설치
uv tool install git+https://github.com/daniel8824/naver-blog-collector
```

설치 없이 1회 실행만 하고 싶다면 `uvx`도 가능합니다.

```bash
uvx --from git+https://github.com/daniel8824/naver-blog-collector nblog doctor
```

### 3단계: 네이버 검색 API 키 발급 받기
블로그 검색 기능을 사용하려면 API 키가 필요합니다.

1. [네이버 개발자센터](https://developers.naver.com/apps)에 접속합니다.
2. **애플리케이션 등록** 버튼을 클릭합니다.
3. 사용 API에서 **검색**을 선택합니다.
4. 등록 후 발급되는 **Client ID**와 **Client Secret**을 복사합니다.

### 4단계: 초기 설정 (매우 중요!)
복사한 키를 프로그램이 인식할 수 있도록 설정하고, 본문 추출용 브라우저를 설치합니다.

```bash
blog setup
```

실행하면 아래 두 가지를 순서대로 진행합니다:
1. **네이버 API 키 입력** — Client ID와 Client Secret을 붙여넣기
2. **Playwright Chromium 설치** — 블로그 본문 추출용 브라우저 자동 설치

*(설정이 완료되면 이제 준비 끝입니다!)*

---

## 💡 실전 사용법

### 1. 블로그 검색하고 CSV로 저장하기
가장 기본적인 사용법입니다. 검색 + 본문 추출 + CSV 저장이 한 번에 실행됩니다.
```bash
# "맛집 추천" 관련 블로그 10건 검색 (기본값)
blog search "맛집 추천" 10

# 멀티 키워드 검색 (콤마로 구분)
blog search "서울 카페,부산 맛집" 5

# 정확도순 정렬
blog search "파이썬" -sort sim

# 본문 추출 없이 빠르게 검색만
blog search "맛집" -fast
```

> `blog`와 `nblog` 둘 다 사용 가능합니다. 편한 걸 쓰세요!

### 2. 단일 URL에서 본문만 추출하기
이미 알고 있는 블로그 글에서 본문만 뽑아낼 수 있습니다.
```bash
blog extract https://blog.naver.com/xxx/yyy

# 파일로 저장
blog extract https://blog.naver.com/xxx/yyy -s output.txt
```

### 3. 환경 점검
API 키, 브라우저, KoNLPy 설치 상태를 한눈에 확인합니다.
```bash
blog doctor
```

---

## 📊 CSV 저장 형식

수집된 데이터는 `~/Downloads/blog_키워드_날짜.csv`에 자동 저장됩니다.

| 컬럼 | 설명 |
|------|------|
| 키워드 | 검색에 사용한 키워드 |
| 타이틀 | 블로그 글 제목 |
| 본문 | 추출된 본문 내용 |
| 블로거 | 블로거 닉네임 |
| 링크 | 블로거 프로필 링크 |
| 날짜 | 글 작성일 (YYYYMMDD) |
| URL | 블로그 글 URL |

---

## 🛡 봇 차단 방지 전략

네이버 블로그에서 안정적으로 본문을 추출하기 위해 다음 전략을 사용합니다:

- **10건 배치 처리:** 한 번에 최대 10건씩 나눠서 요청
- **1~2초 랜덤 딜레이:** 요청 사이에 랜덤 대기 시간 적용
- **Referer/Accept 헤더:** 브라우저와 동일한 HTTP 헤더 설정
- **Playwright stealth:** 브라우저 자동화 탐지를 우회하는 stealth 모드 적용
- **최대 200건 제한:** 과도한 요청 방지를 위한 안전장치

---

## 🔬 텍스트 마이닝

수집한 블로그 데이터로 다양한 텍스트 분석을 수행할 수 있습니다. (KoNLPy 필요)

| 기능 | 설명 |
|------|------|
| **TF-IDF 키워드 추출** | 블로그 글에서 핵심 키워드를 중요도순으로 추출 |
| **LDA 토픽 모델링** | 수집된 글들을 주제별로 자동 분류 |
| **감성분석** | 긍정/부정/중립 비율을 한국어 감성 사전으로 분석 |
| **워드클라우드** | 핵심 키워드를 시각적으로 보여주는 이미지 생성 |

한국어 불용어(블로그, 포스팅, 리뷰, 후기 등 60여 개)가 기본 내장되어 있어 별도 설정 없이 깔끔한 결과를 얻을 수 있습니다.

---

## ❓ 자주 묻는 질문 (FAQ)

**Q: "NAVER_CLIENT_ID가 설정되지 않았습니다"라고 떠요.**
A: `blog setup`을 다시 실행해 주세요. 또는 `~/.env` 파일에 `NAVER_CLIENT_ID`와 `NAVER_CLIENT_SECRET`이 제대로 들어있는지 확인해 보세요. `blog doctor`로 상태를 점검할 수 있습니다.

**Q: 본문이 빈 칸으로 나와요.**
A: 네이버 블로그는 iframe 안에 본문이 있어서 추출이 실패할 수 있습니다. `blog setup`으로 Playwright Chromium이 설치되었는지 확인하세요. 그래도 안 되는 URL이 있다면 알려주시면 개선에 큰 도움이 됩니다.

**Q: 최신 버전으로 업데이트하려면?**
A: 아래 명령어로 간단히 업데이트할 수 있습니다.
```bash
uv tool upgrade naver-blog-collector
```

---

**Happy Blog Collecting!** 🚀
