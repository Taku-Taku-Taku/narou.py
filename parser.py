"""ルビ記法パーサー・テキスト変換

なろう記法:
  ｜親文字《ルビ》  → <ruby>親文字<rp>（</rp><rt>ルビ</rt><rp>）</rp></ruby>
  漢字《ルビ》      → <ruby>漢字<rp>（</rp><rt>ルビ</rt><rp>）</rp></ruby>
  《《傍点対象》》  → <em class="sesame">傍点対象</em>

縦書き向けの文字変換（タグ外のテキストのみ）:
  英文（2語以上、または英字8文字以上） → 半角にして横倒し（全角で書かれた英文も同じ）
  英数字のかたまり（12,000 / Lv.10 / B-29 など記号でつながった単位）を全体の文字数で判定
    1文字      → 全角 (A→Ａ, 5→５)
    2文字      → 縦中横 <span class="tcy">（横書きのまま1文字分に収める）
    3文字以上  → すべて全角にして縦に並べる
  元から全角の英数字（２９, ＨＰ）も同じルールで判定する
  ！？の連続も同様（2文字まで縦中横、3文字以上は全角）
  ギリシャ・キリル文字   → <span class="upright">（横倒しを防ぐ）
  その他の半角記号       → 全角 (%→％, (→（, -→－ など)
  " と ”                → 段落内で交互に 〝 〟（“ は常に 〝。数字の直後の " は ″。対応が取れない段落は ＂）

行頭に全角スペースのない地の文の段落には <p class="indent"> を付けて字下げする
"""

import html
import re

# 漢字の範囲（CJK統合漢字 + 拡張A）
_KANJI = r"\u3400-\u9FFF\uF900-\uFAFF"
# ルビ対象になる文字（漢字 + 一部の記号）
_RUBY_TARGET = rf"[{_KANJI}々〇〻]"

# ｜親文字《ルビ》 パターン（明示的指定）
_EXPLICIT_RUBY = re.compile(
    r"[｜|](.+?)《(.+?)》"
)

# 漢字《ルビ》 パターン（自動検出）
_AUTO_RUBY = re.compile(
    rf"({_RUBY_TARGET}+)《(.+?)》"
)

# 《《傍点》》 パターン
_SESAME = re.compile(
    r"《《(.+?)》》"
)


def _ruby_tag(base: str, ruby: str) -> str:
    return f"<ruby>{base}<rp>（</rp><rt>{ruby}</rt><rp>）</rp></ruby>"


# ASCIIの記号・英数字(0x21-0x7E) → 全角(0xFF01-0xFF5E)
_ASCII_TO_ZENKAKU = {c: c + 0xFEE0 for c in range(0x21, 0x7F)}
# ~ は全角チルダ(～)ではなく、縦書きで正しく回転する波ダッシュ(〜)にする
_ASCII_TO_ZENKAKU[ord("~")] = "〜"
# 変換前の正規化（1回のtranslateでまとめて行う）
# - 全角英数字 → 半角（判定ルールを半角・全角で揃えるため）
# - 縦書きで横倒し・位置ずれする文字の置き換え
_NORMALIZE = str.maketrans(
    {
        **{
            z: a
            for z, a in zip(
                "０１２３４５６７８９"
                "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
                "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
                "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
            )
        },
        "\u2212": "－",  # − マイナス
        "\u2010": "－",  # ‐ ハイフン
        "\u2011": "－",  # ‑ ノーブレークハイフン
        "\u22ef": "…",  # ⋯ 数学用の三点リーダ（縦書きで縦にならない）
        "\u2018": "＇",  # ‘
        "\u2019": "＇",  # ’
    }
)

# HTMLタグとそれ以外（テキスト）に分けるパターン
_TAG_SPLIT = re.compile(r"(<[^>]*>)")
# 引用符の開き・閉じの対応をリセットする段落の区切り
_PARAGRAPH_BOUNDARY = re.compile(r"</?(?:p|div|br|hr)\b", re.IGNORECASE)

# 段落の最初の文字（ルビなどのタグは飛ばす。改行・挿絵・空段落なら文字なし）
_PARAGRAPH_HEAD = re.compile(r"<p>((?:<(?!br|img|/p)[^>]*>)*)([^<])?")
# 字下げしない段落の先頭文字（既に字下げ済み・括弧で始まる会話文など。縦書き変換後の文字で判定）
_NO_INDENT_HEAD = "\u3000 「『（［｛〔【〈《〘〖＜≪〝＂"

# 英文: 英数字・記号の単語が空白で続く部分（全角英数字は半角に正規化した後で判定する）
_ENGLISH_WORD = r"[A-Za-z0-9_.,!?'&:;\-．，！？＇＆：；－]+"
_ENGLISH_CANDIDATE = re.compile(rf"{_ENGLISH_WORD}(?:[ \u3000]+{_ENGLISH_WORD})*")
# 英文候補を単語と空白に分ける
_ENGLISH_SPLIT = re.compile(r"([ \u3000]+)")
# 英文中の全角の記号・空白 → 半角
_ENGLISH_TO_ASCII = str.maketrans("．，！？＇＆：；－\u3000", ".,!?'&:;- ")
# 英文とみなす最小の英字数（これ以上なら1語でも英文とする）
_ENGLISH_MIN_LETTERS = 8
_LETTER = re.compile(r"[A-Za-z]")

# 英数字のかたまり: 英数字の間に挟まった区切り記号も含めて1単位とする
# 「、」は「12、000」のように後ろが3桁ちょうどの数字のときだけ桁区切りとみなす
# 末尾の「:」（Re:ゼロ など）もかたまりに含める
_ALNUM_TOKEN = re.compile(
    r"[A-Za-z0-9]+"
    r"(?:(?:[.,:'/\-&+，．：＆＋]|(?<=[0-9])、(?=[0-9]{3}(?![0-9])))[A-Za-z0-9]+)*"
    r"[:：]?"
)
# 感嘆符・疑問符の連続
_EXCLAMATION = re.compile(r"[!?！？]+")
# ギリシャ文字・キリル文字
_UPRIGHT_SCRIPT = re.compile(r"[\u0370-\u03FF\u0400-\u04FF]+")
# 和文中の半角スペース（行頭・行末は除く）
_INNER_SPACE = re.compile(r"(?<=\S) (?=\S)")

# 縦書き変換の対象をまとめて走査するパターン（それ以外の文字はそのまま）
_VERTICAL_TARGET = re.compile(
    rf"(?P<alnum>{_ALNUM_TOKEN.pattern})"
    rf"|(?P<excl>{_EXCLAMATION.pattern})"
    rf"|(?P<upright>{_UPRIGHT_SCRIPT.pattern})"
    r"|(?P<dquote>[\"\u201c\u201d])"
    r"|(?P<symbol>[\x21-\x7E])"
)


def _tcy(text: str) -> str:
    return f'<span class="tcy">{html.escape(text)}</span>'


def _to_zenkaku(text: str) -> str:
    return text.translate(_ASCII_TO_ZENKAKU)


# 引用符（変換後の文字を決めるため、段落ごとに先に数える）
_QUOTE = re.compile(r"[\"\u201c\u201d]")


def _decide_quotes(text: str) -> list[str]:
    """段落（_NORMALIZE で正規化済み）の引用符を、出現順に変換後の文字にする

    “ は開き。\" と ” は書き手によって向きがばらつくため、開き・閉じを交互にする
    開いていないときに数字の直後にある \" は、インチ・秒の記号（″）とみなす
    開き・閉じの対応が取れない段落は、向きを間違えないよう向きのない ＂ にする
    """
    marks = []
    is_open = False
    paired = True
    for m in _QUOTE.finditer(text):
        s = m.group(0)
        prev = text[m.start() - 1] if m.start() > 0 else ""
        if s == "\u201c":
            paired = paired and not is_open
            is_open = True
            marks.append("〝")
        elif is_open:
            is_open = False
            marks.append("〟")
        elif s == '"' and prev and prev in "0123456789":
            marks.append("″")
        else:
            is_open = True
            marks.append("〝")
    if is_open or not paired:
        marks = [m if m == "″" else "＂" for m in marks]
    return marks


class _QuoteState:
    """段落内の引用符の変換後の文字を、出現順に渡すための状態"""

    def __init__(self, marks: list[str]):
        self._marks = iter(marks)

    def next(self) -> str:
        return next(self._marks, "＂")


def _is_english_sentence(text: str) -> bool:
    """2語以上、または一定数以上の英字を含む（www のような同じ文字の繰り返しは除く）"""
    letters = _LETTER.findall(text)
    if not letters:
        return False
    if " " in text:
        return True
    return len(letters) >= _ENGLISH_MIN_LETTERS and len({c.lower() for c in letters}) > 1


def _english_spans(text: str):
    """英文とみなす部分の (開始, 終了) を返す

    全角スペースは、両側の単語が英字を含むときだけ英文の単語の区切りとみなす
    （「#3　Aランク」「！？　S」の全角スペースは和文の空白として残す）
    """
    for m in _ENGLISH_CANDIDATE.finditer(text):
        parts = _ENGLISH_SPLIT.split(m.group(0))
        start = pos = m.start()
        for i in range(1, len(parts), 2):
            pos += len(parts[i - 1])
            sep = parts[i]
            if "\u3000" in sep and not (
                _LETTER.search(parts[i - 1]) and _LETTER.search(parts[i + 1])
            ):
                yield start, pos
                start = pos + len(sep)
            pos += len(sep)
        yield start, m.end()


def to_vertical_html(text: str, quote: _QuoteState | None = None) -> str:
    """エスケープ解除済みのテキスト（タイトル等）を縦書き向けに変換し、エスケープ済みHTMLを返す

    英文は1文字ずつ縦に並べると読みにくいため、半角のまま（縦書きでは横倒し）残す
    quote: 段落の途中にタグを挟んで続けて変換するときに、段落全体で決めた引用符を引き継ぐ
    """
    text = text.translate(_NORMALIZE)
    if quote is None:
        quote = _QuoteState(_decide_quotes(text))
    out = []
    pos = 0
    for start, end in _english_spans(text):
        english = text[start:end].translate(_ENGLISH_TO_ASCII)
        if _is_english_sentence(english):
            out.append(_convert_part(text[pos:start], quote))
            out.append(html.escape(english, quote=False))
            pos = end
    out.append(_convert_part(text[pos:], quote))
    return "".join(out)


def _convert_part(text: str, quote: _QuoteState) -> str:
    """英文以外の部分（_NORMALIZE で正規化済み）を縦書き向けに変換する"""
    text = _INNER_SPACE.sub("\u3000", text)

    out = []
    pos = 0
    for m in _VERTICAL_TARGET.finditer(text):
        out.append(html.escape(text[pos : m.start()], quote=False))
        pos = m.end()
        s = m.group(0)
        kind = m.lastgroup
        if kind in ("alnum", "excl"):
            if kind == "excl":
                s = s.replace("！", "!").replace("？", "?")
            if len(s) == 2:
                out.append(_tcy(s))
            else:
                out.append(_to_zenkaku(s))
        elif kind == "upright":
            out.append(f'<span class="upright">{s}</span>')
        elif kind == "dquote":
            out.append(quote.next())
        else:
            out.append(_to_zenkaku(s))
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def _convert_outside_tags(text: str) -> str:
    """HTMLタグの外側のテキスト部分を縦書き向けに変換

    &amp; などのエンティティは一度文字に戻してから変換する（記号は全角になる）
    ルビなどのタグをまたいでも、引用符は段落全体で対応を決める
    """
    # 段落ごとにテキスト部分をまとめ、引用符の変換後の文字を先に決める
    # （エスケープを戻した文字が < で始まることがあるため、タグかどうかは分割位置で判定する）
    parts = _TAG_SPLIT.split(text)  # 偶数番目がテキスト、奇数番目がタグ
    paragraph_quotes = []
    texts = []
    for i, part in enumerate(parts + ["<p>"]):  # 末尾に段落の区切りを補う
        if i % 2 and _PARAGRAPH_BOUNDARY.match(part):
            paragraph_quotes.append(_decide_quotes("".join(texts).translate(_NORMALIZE)))
            texts = []
        elif not i % 2:
            texts.append(html.unescape(part))

    out = []
    paragraphs = iter(paragraph_quotes)
    quote = _QuoteState(next(paragraphs))
    for i, part in enumerate(parts):
        if i % 2:
            if _PARAGRAPH_BOUNDARY.match(part):
                quote = _QuoteState(next(paragraphs))
            out.append(part)
        elif part:
            out.append(to_vertical_html(html.unescape(part), quote))
    return "".join(out)


def _add_indent(match: re.Match) -> str:
    """行頭を字下げしていない地の文の段落に字下げ用のclassを付ける"""
    head = match.group(2)
    if head is None or head in _NO_INDENT_HEAD:
        return match.group(0)
    return '<p class="indent">' + match.group(0)[len("<p>") :]


class RubyParser:
    def convert(self, html: str) -> str:
        """本文HTML中のなろうルビ記法をHTMLルビタグに変換"""
        # 傍点を先に処理（《《》》が《》と誤マッチしないように）
        text = _SESAME.sub(
            r'<em class="sesame">\1</em>',
            html,
        )
        # 明示的ルビ（｜指定）
        text = _EXPLICIT_RUBY.sub(
            lambda m: _ruby_tag(m.group(1), m.group(2)),
            text,
        )
        # 自動ルビ（漢字のみ）
        text = _AUTO_RUBY.sub(
            lambda m: _ruby_tag(m.group(1), m.group(2)),
            text,
        )
        # 縦書き向けの文字変換（タグ外のテキスト部分のみ）
        text = _convert_outside_tags(text)
        # 行頭に全角スペースを入れない作品向けに、地の文の段落を字下げ
        text = _PARAGRAPH_HEAD.sub(_add_indent, text)
        return text
