"""从 PDF 抽取 span 并修复 LaTeX 排版导致的文本粘连与断词。

PyMuPDF 给出的 span 文本不含定位性空格：LaTeX 用位移而非空格字符来分隔
"4.4" 与 "Corpus"，直接拼接会得到 "4.4Corpus"。同理行尾连字符断词
("classi-" / "fiers") 需要还原。这两件事必须在翻译前做掉。
"""
from __future__ import annotations

import re

import pymupdf

from .model import Span

# PyMuPDF span flags 位
_F_ITALIC = 1 << 1
_F_BOLD = 1 << 4

_RE_MONO = re.compile(r"Inconsolata|SFTT|Courier|Mono|Typewriter|CMTT", re.I)
# 数学字体只认这几族。CMR/CMB 是 Computer Modern 的正文体，
# 论文里用来排编号列表，绝不能当公式排除掉。
_RE_MATH = re.compile(r"CM(MI|SY|EX)|MS[AB]M|EU[FSMB]|rsfs|stmary|LASY", re.I)

_RE_CJK = re.compile(r"[一-鿿㐀-䶿]")
_RE_LATIN_WORD = re.compile(r"[A-Za-z]")


def make_span(raw: dict) -> Span:
    font = raw["font"]
    flags = raw["flags"]
    return Span(
        text=raw["text"],
        font=font,
        size=round(raw["size"], 2),
        color=raw.get("color", 0),
        # 字体名兜底：部分 PDF 只在名字里体现字重，不设 flag
        bold=bool(flags & _F_BOLD) or bool(re.search(r"Bold|Medi|Black", font)),
        italic=bool(flags & _F_ITALIC) or bool(re.search(r"Ital|Oblique", font)),
        mono=bool(_RE_MONO.search(font)),
        math=bool(_RE_MATH.search(font)),
        bbox=tuple(raw["bbox"]),
    )


def line_text(spans: list[Span]) -> str:
    """拼接一行内的 span，按 bbox 间距补回缺失的空格。"""
    out: list[str] = []
    prev: Span | None = None
    for sp in spans:
        if prev is not None:
            gap = sp.bbox[0] - prev.bbox[2]
            # 阈值取字号的 15%：小于此为字距抖动，大于此才是真正的词间空格
            threshold = 0.15 * max(prev.size, 1.0)
            prev_ch = out[-1][-1] if out and out[-1] else ""
            next_ch = sp.text[:1]
            # 中文逐字成 span，字间距天然超阈值，插空格会得到 "AI最 新 排 行 榜"
            both_cjk = bool(_RE_CJK.match(prev_ch or " ")) and bool(_RE_CJK.match(next_ch or " "))
            need = (
                gap > threshold
                and out
                and not both_cjk
                and not out[-1].endswith((" ", "-", "‐"))
                and not sp.text.startswith(" ")
            )
            if need:
                out.append(" ")
        out.append(sp.text)
        prev = sp
    return "".join(out)


_RE_COMPOUND = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)+")
# 截连字符前的完整复合片段："part-of-" 要拿到 "part-of" 而不是 "of"
_RE_TAIL_WORD = re.compile(r"([A-Za-z]+(?:-[A-Za-z]+)*)-$")
_RE_WORD = re.compile(r"[A-Za-z]{2,}")
_RE_HEAD_WORD = re.compile(r"^([A-Za-z]+)")


def collect_words(all_lines: list[str]) -> set[str]:
    """全文出现过的独立英文单词，用于判断断词两半是否各自成词。"""
    words: set[str] = set()
    for ln in all_lines:
        for m in _RE_WORD.finditer(ln):
            words.add(m.group(0).lower())
    return words


def collect_hyphen_vocab(all_lines: list[str]) -> set[str]:
    """扫全文行内的连字符复合词，作为"这个连字符是真的"的证据。

    LaTeX 的换行软连字符与复合词本身的连字符在 PDF 里无法区分。但同一篇文档
    里，"text-only"、"part-of-speech" 这类复合词几乎必然也在别处的行中间出现过。
    以文档自身为词典，就能把 "classi-/fiers" 与 "text-/only" 区分开。
    """
    vocab: set[str] = set()
    for ln in all_lines:
        # 只取行内的：行尾那个可能是断词，不能作为证据
        for m in _RE_COMPOUND.finditer(ln.rstrip()):
            if m.end() < len(ln.rstrip()):
                vocab.add(m.group(0).lower())
    return vocab


def stitch_hyphen(
    head: str,
    tail: str,
    hyphen_vocab: set[str] | None = None,
    words: set[str] | None = None,
) -> str:
    """把以连字符结尾的 head 与 tail 接起来，判断该连字符是断词还是复合词。

    块内换行与跨块换行都会遇到这个问题（实测 "part-of-" 与 "speech," 分属
    两个块），所以判定逻辑必须只有一份。
    """
    hyphen_vocab = hyphen_vocab or set()
    words = words or set()
    m_tail = _RE_TAIL_WORD.search(head)
    m_head = _RE_HEAD_WORD.match(tail)
    if not m_tail or not m_head:
        # "Qwen3-" + "235B"：数字续写，直连且保留连字符
        return head + tail
    # 最强判据：去掉连字符后的形式本就是文档里的词，说明这是换行断词。
    # "Xiao-hongshu" -> "xiaohongshu" 全文出现数十次，必须合并，
    # 否则同一个专有名词会裂成 Xiaohongshu / Xiao-hongshu / Xiaohong-shu 三个变体。
    last = m_tail.group(1).rsplit("-", 1)[-1]
    if f"{last}{m_head.group(1)}".lower() in words:
        return head[:-1] + tail
    if f"{m_tail.group(1)}-{m_head.group(1)}".lower() in hyphen_vocab:
        return head + tail          # 复合词在文档别处整体出现过，连字符是真的
    if last.lower() in words and m_head.group(1).lower() in words:
        # 断开的两半各自都是文档里的独立词（mass|produce）→ 复合词；
        # 若两半都不成词（classi|fiers）→ 换行断词
        return head + tail
    if tail[:1].islower():
        return head[:-1] + tail     # 换行软连字符，删掉
    return head + tail


def join_lines(
    lines: list[str],
    hyphen_vocab: set[str] | None = None,
    words: set[str] | None = None,
) -> str:
    """合并块内多行，处理行尾连字符断词。"""
    hyphen_vocab = hyphen_vocab or set()
    words = words or set()
    out = ""
    for raw in lines:
        cur = raw.strip()
        if not cur:
            continue
        if not out:
            out = cur
            continue
        if out.endswith("-") and len(out) >= 2 and out[-2].isalnum():
            out = stitch_hyphen(out, cur, hyphen_vocab, words)
        elif _RE_CJK.search(out[-1]) and _RE_CJK.search(cur[0]):
            out += cur                      # 中文之间不加空格
        else:
            out += " " + cur
    return out


def extract_blocks(page: pymupdf.Page) -> list[tuple[tuple, list[Span], list[str]]]:
    """返回 [(bbox, spans, lines)]，保持 PyMuPDF 的原始块序。

    这里不做行合并 —— 连字符判定需要全文词表，必须等所有页抽完再拼。
    """
    result = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:            # 非文本块
            continue
        spans: list[Span] = []
        lines: list[str] = []
        for ln in blk["lines"]:
            ln_spans = [make_span(s) for s in ln["spans"] if s["text"]]
            if not ln_spans:
                continue
            spans.extend(ln_spans)
            lines.append(line_text(ln_spans))
        if not any(l.strip() for l in lines):
            continue
        result.append((tuple(blk["bbox"]), spans, lines))
    return result


def detect_lang(text: str) -> str:
    """按 CJK 字符占比判断块语言。中文块不该再被翻译一遍。"""
    stripped = re.sub(r"\s", "", text)
    if not stripped:
        return "en"
    cjk = len(_RE_CJK.findall(stripped))
    ratio = cjk / len(stripped)
    if ratio > 0.30:
        return "zh"
    if ratio > 0.05:
        return "mixed"      # 英文正文里嵌了中文词，仍需翻译
    return "en"
