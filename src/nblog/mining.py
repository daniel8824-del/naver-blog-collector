"""Korean blog text mining helpers."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from wordcloud import WordCloud

try:
    from kiwipiepy import Kiwi
except ImportError:  # pragma: no cover - depends on local runtime
    Kiwi = None  # type: ignore[assignment]


DEFAULT_STOPWORDS = {
    "블로그", "포스팅", "리뷰", "후기", "오늘", "정말", "진짜", "너무", "이번", "그냥",
    "약간", "조금", "완전", "요즘", "최근", "이제", "바로", "거의", "먼저", "나중",
    "여기", "저기", "이것", "저것", "그것", "이런", "저런", "그런", "같은", "대한",
    "관련", "통해", "때문", "정도", "생각", "느낌", "부분", "모습", "경우", "사실",
    "사진", "영상", "첨부", "공유", "소개", "추천", "정리", "방문", "사용", "구매",
    "제품", "상품", "내용", "정보", "기록", "일상", "하루", "주말", "평일", "이야기",
    "포함", "진행", "준비", "결과", "마무리", "확인", "참고", "클릭", "링크", "댓글",
    "공감", "서이추", "이웃", "소통", "구독", "광고", "협찬", "원고료", "체험단",
    "내돈내산", "직접", "개인", "개인적", "처음", "마지막", "중간", "예정", "필수",
    "가능", "최고", "최악", "매우", "엄청", "한번", "계속", "가장", "다음", "이전",
    "근데", "그래서", "그리고", "하지만", "또한", "혹시", "아주", "진행", "포함",
}

POSITIVE_LEXICON = {
    "좋다": 2, "만족": 2, "훌륭하다": 2, "추천": 1, "깔끔하다": 1, "편하다": 1,
    "예쁘다": 1, "맛있다": 2, "친절하다": 2, "빠르다": 1, "유용하다": 1, "든든하다": 1,
    "최고": 2, "완벽하다": 2, "재밌다": 1, "쾌적하다": 1, "감동": 2, "행복": 2,
    "괜찮다": 1, "알차다": 1, "부드럽다": 1, "가성비": 1, "든다": 1, "성공": 1,
}

NEGATIVE_LEXICON = {
    "별로": -1, "불편하다": -2, "아쉽다": -1, "실망": -2, "최악": -2, "느리다": -1,
    "비싸다": -1, "어렵다": -1, "불친절": -2, "지저분하다": -1, "짜증": -2, "후회": -2,
    "부족하다": -1, "문제": -1, "불량": -2, "고장": -2, "아프다": -1, "힘들다": -1,
    "답답하다": -1, "나쁘다": -2, "심하다": -1, "낡다": -1, "늦다": -1, "불안": -1,
}

SENTIMENT_LEXICON = {**POSITIVE_LEXICON, **NEGATIVE_LEXICON}

try:
    kiwi = Kiwi() if Kiwi is not None else None
except Exception:  # pragma: no cover - depends on local runtime
    kiwi = None


def _tokenize_with_kiwi(text: str) -> list:
    if kiwi is None:
        raise ImportError("kiwipiepy is required for Korean text mining. Install `kiwipiepy` first.")
    return kiwi.tokenize(text)


def _normalize_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"https?://\S+|www\.\S+", " ", value)
    value = re.sub(r"[^0-9A-Za-z가-힣\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokenize_korean(text: str, stopwords: set[str] | None = None) -> list[str]:
    stopword_set = stopwords or DEFAULT_STOPWORDS
    normalized = _normalize_text(text)
    if not normalized:
        return []

    tokenized = [
        token.form
        for token in _tokenize_with_kiwi(normalized)
        if token.tag.startswith("NN") or token.tag.startswith("VA") or token.tag.startswith("VV")
    ]
    tokens: list[str] = []
    for word in tokenized:
        if len(word) < 2:
            continue
        if word in stopword_set:
            continue
        if word.isdigit():
            continue
        tokens.append(word)
    return tokens


def _prepare_documents(texts: list[str], stopwords: set[str] | None = None) -> list[str]:
    docs = [" ".join(_tokenize_korean(text, stopwords=stopwords)) for text in texts]
    return [doc for doc in docs if doc.strip()]


def _get_font_path() -> str:
    preferred = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "/usr/share/fonts/opentype/nanum/NanumGothic.otf",
    ]
    for path in preferred:
        if Path(path).exists():
            return path

    for font in fm.fontManager.ttflist:
        if "NanumGothic" in font.name or "Nanum Gothic" in font.name:
            return font.fname

    raise FileNotFoundError("NanumGothic font not found")


def _safe_float(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return float(value)


def extract_keywords(texts: list[str], top_n: int = 20) -> list[tuple[str, float]]:
    """Extract TF-IDF keywords from Korean blog texts."""
    docs = _prepare_documents(texts)
    if not docs:
        return []

    vectorizer = TfidfVectorizer(
        tokenizer=str.split,
        preprocessor=None,
        token_pattern=None,
        lowercase=False,
        min_df=1,
        max_df=0.9,
        sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform(docs)
    scores = np.asarray(matrix.mean(axis=0)).ravel()
    features = vectorizer.get_feature_names_out()
    ranked = sorted(
        zip(features, scores),
        key=lambda item: item[1],
        reverse=True,
    )
    return [(word, round(_safe_float(score), 6)) for word, score in ranked[:top_n]]


def extract_topics(texts: list[str], n_topics: int = 5) -> list[dict]:
    """Run LDA topic modeling and return labels with top words."""
    docs = _prepare_documents(texts)
    if not docs:
        return []

    topic_count = max(1, min(n_topics, len(docs)))
    vectorizer = CountVectorizer(
        tokenizer=str.split,
        preprocessor=None,
        token_pattern=None,
        lowercase=False,
        min_df=1,
        max_df=0.95,
    )
    dtm = vectorizer.fit_transform(docs)
    if dtm.shape[1] == 0:
        return []

    lda = LatentDirichletAllocation(
        n_components=min(topic_count, dtm.shape[1]),
        random_state=42,
        learning_method="batch",
        max_iter=20,
    )
    lda.fit(dtm)

    feature_names = vectorizer.get_feature_names_out()
    topics: list[dict] = []
    for index, topic_weights in enumerate(lda.components_, start=1):
        top_indices = topic_weights.argsort()[::-1][:7]
        top_words = [feature_names[i] for i in top_indices]
        topics.append(
            {
                "topic_id": index,
                "label": " / ".join(top_words[:3]),
                "top_words": top_words,
            }
        )
    return topics


def analyze_sentiment(texts: list[str]) -> dict:
    """Analyze sentiment ratios using a simple Korean lexicon."""
    counts = Counter({"positive": 0, "negative": 0, "neutral": 0})
    score_list: list[int] = []

    for text in texts:
        tokens = _tokenize_korean(text, stopwords=set())
        score = sum(SENTIMENT_LEXICON.get(token, 0) for token in tokens)
        score_list.append(score)
        if score > 0:
            counts["positive"] += 1
        elif score < 0:
            counts["negative"] += 1
        else:
            counts["neutral"] += 1

    total = max(len(texts), 1)
    ratios = {
        key: round(counts[key] / total, 4)
        for key in ("positive", "negative", "neutral")
    }
    return {
        "counts": dict(counts),
        "ratios": ratios,
        "average_score": round(sum(score_list) / total, 4),
        "lexicon_size": len(SENTIMENT_LEXICON),
    }


def generate_wordcloud(texts: list[str], output_path: str) -> str:
    """Generate and save a Korean wordcloud image."""
    docs = _prepare_documents(texts)
    if not docs:
        raise ValueError("No tokenizable Korean text provided")

    frequencies = Counter(" ".join(docs).split())
    font_path = _get_font_path()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    wc = WordCloud(
        font_path=font_path,
        width=1600,
        height=900,
        background_color="white",
        max_words=120,
        colormap="viridis",
    )
    wc.generate_from_frequencies(frequencies)

    plt.rcParams["font.family"] = "NanumGothic"
    fig, ax = plt.subplots(figsize=(16, 9))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title("Naver Blog Wordcloud", fontsize=18)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(output)


def run_full_analysis(texts: list[str], output_dir: str) -> dict:
    """Run the full text mining pipeline and save outputs."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    keywords = extract_keywords(texts)
    topics = extract_topics(texts)
    sentiment = analyze_sentiment(texts)
    wordcloud_path = generate_wordcloud(texts, str(output / "wordcloud.png"))

    summary = {
        "document_count": len(texts),
        "keywords": [{"word": word, "score": score} for word, score in keywords],
        "topics": topics,
        "sentiment": sentiment,
        "artifacts": {
            "wordcloud": wordcloud_path,
            "results_json": str(output / "analysis_results.json"),
        },
    }

    with (output / "analysis_results.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    return summary
