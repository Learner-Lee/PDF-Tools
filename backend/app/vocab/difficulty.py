"""难词判定。

两套基准，用户自选：
  - coca ：认识 COCA 词频前 N 千词，其余算难词
  - exam ：认识某考试大纲及以下的词汇，其余算难词

判定只回答"这个词对你难不难"，不负责给释义 —— 释义来自词库（离线、免费），
需要语境义时再单独调模型。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .db import Entry, VocabDB, tokenize

#: 考试词表由易到难。选定某一级即认为掌握该级及以下的全部词汇。
EXAM_ORDER = ["zk", "gk", "cet4", "cet6", "ky", "ielts", "toefl", "gre"]

EXAM_LABELS = {
    "zk": "中考", "gk": "高考", "cet4": "四级", "cet6": "六级",
    "ky": "考研", "ielts": "雅思", "toefl": "托福", "gre": "GRE",
}

COCA_TIERS = [3000, 5000, 8000, 15000]

#: 各考试等级对应的词频底线。
#: 考试大纲只覆盖两万词里的一小部分，没打标签的常用词（participation、media…）
#: 若一律算难词，标注会淹没正文。用词频兜住这批词。
EXAM_COCA_FLOOR = {
    "zk": 1500, "gk": 2500, "cet4": 3500, "cet6": 5000,
    "ky": 6000, "ielts": 6500, "toefl": 7500, "gre": 10000,
}

#: 不含元音的词多半是切分残渣（如 Jablo´nska 被拆出的 nska）
_RE_VOWEL = re.compile(r"[aeiouy]")

#: 功能词与极高频词，无论哪种基准都不该标记
_ALWAYS_KNOWN = {
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "by", "for", "with", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "am", "do", "does", "did", "have", "has", "had", "will", "would",
    "can", "could", "shall", "should", "may", "might", "must", "not", "no",
    "this", "that", "these", "those", "it", "its", "he", "she", "they", "them",
    "we", "us", "you", "i", "me", "my", "our", "their", "his", "her", "there",
    "here", "when", "where", "which", "who", "whom", "whose", "what", "how",
    "why", "all", "any", "some", "such", "than", "then", "so", "too", "very",
    "more", "most", "also", "only", "other", "each", "both", "into", "over",
    "under", "between", "about", "after", "before", "while", "during", "up",
    "out", "off", "down", "again", "further", "s", "t", "d", "ll", "re", "ve",
}

#: 少于这么多字母的词不标记
_MIN_LEN = 3


@dataclass
class Profile:
    basis: str = "coca"                 # coca | exam
    coca_tier: int = 5000
    exam_level: str = "cet6"
    known: set[str] = field(default_factory=set)   # 用户标记为已掌握的原形

    @property
    def known_exams(self) -> set[str]:
        if self.exam_level not in EXAM_ORDER:
            return set()
        return set(EXAM_ORDER[: EXAM_ORDER.index(self.exam_level) + 1])

    def to_dict(self) -> dict:
        return {
            "basis": self.basis,
            "coca_tier": self.coca_tier,
            "exam_level": self.exam_level,
            "known": sorted(self.known),
        }

    @staticmethod
    def from_dict(d: dict | None) -> "Profile":
        d = d or {}
        return Profile(
            basis=d.get("basis", "coca"),
            coca_tier=int(d.get("coca_tier", 5000)),
            exam_level=d.get("exam_level", "cet6"),
            known=set(d.get("known") or []),
        )


@dataclass
class HardWord:
    start: int          # 在块文本中的字符起点
    end: int
    surface: str        # 原文形态
    lemma: str
    phonetic: str = ""
    pos: str = ""
    gloss: str = ""        # 卡片里的完整释义
    brief: str = ""        # 行内跟在原词后的短释义
    coca: int = 0
    tag: str = ""


def _is_difficult(entry: Entry | None, profile: Profile) -> bool:
    if entry is None:
        return True                      # 词库都没收录，必然生僻
    if profile.basis == "exam":
        # 大纲词汇之外，再用词频兜住那些没打标签的常用词
        floor = EXAM_COCA_FLOOR.get(profile.exam_level, 5000)
        if entry.coca and entry.coca <= floor:
            return False
        return not (entry.tags & profile.known_exams)
    # COCA 基准：名次在阈值内算认识；两万开外没有名次，一律算难
    return entry.coca == 0 or entry.coca > profile.coca_tier


def analyze(
    text: str,
    profile: Profile,
    db: VocabDB,
    skip: set[str] | None = None,
) -> list[HardWord]:
    """找出一段文本里的难词。skip 传入术语表等不需要标记的词。"""
    if not db.available:
        return []
    skip = skip or set()
    out: list[HardWord] = []
    seen_lemma: set[str] = set()

    for start, end, surface in tokenize(text):
        low = surface.lower()
        if len(low) < _MIN_LEN or low in _ALWAYS_KNOWN:
            continue
        if not _RE_VOWEL.search(low):
            continue
        # 句中大写多为专有名词，不该当难词
        if surface[0].isupper() and start > 0 and text[start - 1] not in ".!?\n":
            continue
        lemma = db.lemma(low)
        if not lemma or lemma in _ALWAYS_KNOWN or lemma in profile.known or lemma in skip:
            continue
        if lemma in seen_lemma:          # 同一段内同一个词只标一次
            continue
        entry = db.get(lemma)
        if not _is_difficult(entry, profile):
            continue
        # 给不出释义就不要标记：一个点开是空的下划线只会打断阅读。
        # 词库没收录的多半是临时复合词（lifestyle-oriented）或切分残渣。
        gloss = entry.gloss() if entry else ""
        if not gloss:
            continue
        seen_lemma.add(lemma)
        out.append(HardWord(
            start=start, end=end, surface=surface, lemma=lemma,
            phonetic=entry.phonetic, pos=entry.pos, gloss=gloss,
            brief=entry.brief(), coca=entry.coca, tag=entry.tag,
        ))
    return out
