"""Sentiment Lexicons and Text Filtering Dictionaries (Bilingual: EN & VI).

Designed to be easily extended with new languages, domain-specific terminology,
or loaded from external resources in the future.
"""

from typing import Set

# -------------------------------------------------------------
# Positive Lexicon
# -------------------------------------------------------------
POSITIVE_WORDS_EN: Set[str] = {
    "great", "awesome", "excellent", "love", "good", "amazing", "helpful", "super",
    "best", "fantastic", "insightful", "valuable", "thank", "thanks", "perfect",
}

POSITIVE_WORDS_VI: Set[str] = {
    "tuyệt", "hay", "tốt", "xuất sắc", "thích", "hữu ích", "cảm ơn", "đẹp", "chuẩn", "đỉnh",
}

POSITIVE_WORDS: Set[str] = POSITIVE_WORDS_EN | POSITIVE_WORDS_VI


# -------------------------------------------------------------
# Negative Lexicon
# -------------------------------------------------------------
NEGATIVE_WORDS_EN: Set[str] = {
    "bad", "terrible", "horrible", "worst", "hate", "boring", "useless", "disappointed",
    "poor", "waste", "confusing", "annoying", "fail", "slow", "broken",
}

NEGATIVE_WORDS_VI: Set[str] = {
    "tệ", "dở", "chán", "thất vọng", "kém", "lãng phí", "vô ích", "sai", "lỗi", "chậm", "xàm"
}

NEGATIVE_WORDS: Set[str] = NEGATIVE_WORDS_EN | NEGATIVE_WORDS_VI


# -------------------------------------------------------------
# Toxic / Spam Lexicon
# -------------------------------------------------------------
TOXIC_WORDS_EN: Set[str] = {
    "scam", "fraud", "fake", "idiot", "stupid", "trash", "spam", "bot", "wtf",
}

TOXIC_WORDS_VI: Set[str] = {
    "lừa đảo", "rác", "ngu", "khốn", "chửi", "spam", "gian lận", "tào lao", "nhảm", "đm", 
    "dm", "xl", "xàm lz", "xàm cứt", "cúc",
}

TOXIC_WORDS: Set[str] = TOXIC_WORDS_EN | TOXIC_WORDS_VI


# -------------------------------------------------------------
# Stop Words for Topic & Keyword Extraction
# -------------------------------------------------------------
STOP_WORDS_EN: Set[str] = {
    "the", "a", "an", "is", "in", "and", "or", "for", "to", "of", "video", "post", "this", "that", "it", "very",
}

STOP_WORDS_VI: Set[str] = {
    "và", "là", "của", "cho", "ở", "với", "rất", "vs"
}

STOP_WORDS: Set[str] = STOP_WORDS_EN | STOP_WORDS_VI


__all__ = [
    "POSITIVE_WORDS",
    "POSITIVE_WORDS_EN",
    "POSITIVE_WORDS_VI",
    "NEGATIVE_WORDS",
    "NEGATIVE_WORDS_EN",
    "NEGATIVE_WORDS_VI",
    "TOXIC_WORDS",
    "TOXIC_WORDS_EN",
    "TOXIC_WORDS_VI",
    "STOP_WORDS",
    "STOP_WORDS_EN",
    "STOP_WORDS_VI",
]
