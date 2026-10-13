"""ルビ記法パーサー・テキスト変換

なろう記法:
  ｜親文字《ルビ》  → <ruby>親文字<rp>（</rp><rt>ルビ</rt><rp>）</rp></ruby>
  漢字《ルビ》      → <ruby>漢字<rp>（</rp><rt>ルビ</rt><rp>）</rp></ruby>
  《《傍点対象》》  → <em class="sesame">傍点対象</em>

縦書き向けの文字変換（タグ外のテキストのみ）:
  英文（2語以上、または8文字以上） → 半角にして横倒し（全角で書かれた英文も同じ）
  英数字のかたまり（12,000 / Lv.10 / B-29 など記号でつながった単位）を全体の文字数で判定
    1文字      → 全角 (A→Ａ, 5→５)
    2文字      → 縦中横 <span class="tcy">（横書きのまま1文字分に収める）
    3文字以上  → すべて全角にして縦に並べる
  元から全角の英数字（２９, ＨＰ）も同じルールで判定する
  ！？の連続も同様（2文字まで縦中横、3文字以上は全角）
  ギリシャ・キリル文字   → <span class="upright">（横倒しを防ぐ）
  その他の半角記号       → 全角 (%→％, (→（, -→－ など)
  " と ”                → 段落内で交互に 〝 〟（“ は常に 〝）

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
# 字下げしない段落の先頭文字（既に字下げ済み・括弧で始まる会話文など）
_NO_INDENT_HEAD = "\u3000 「『（(［[｛{〔【〈《〝\"“"

# 英文: 英数字・記号の単語が空白で続く部分（全角英数字は半角に正規化した後で判定する）
_ENGLISH_WORD = r"[A-Za-z0-9_.,!?'&:;\-．，！？＇＆：；－]+"
_ENGLISH_CANDIDATE = re.compile(rf"{_ENGLISH_WORD}(?:[ \u3000]+{_ENGLISH_WORD})*")
# 英文中の全角の記号・空白 → 半角
_ENGLISH_TO_ASCII = str.maketrans("．，！？＇＆：；－\u3000", ".,!?'&:;- ")
# 英文とみなす最小文字数（これ以上でアルファベットを含めば、2語未満でも英文とする）
_ENGLISH_MIN_LENGTH = 8

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


class _QuoteState:
    """段落内の \" と ” の開き・閉じを交互に決めるための状態"""

    def __init__(self):
        self.is_open = False


def _is_english_sentence(text: str) -> bool:
    """2語以上、または一定長以上でアルファベットを含む"""
    if not re.search(r"[A-Za-z]", text):
        return False
    return " " in text or len(text) >= _ENGLISH_MIN_LENGTH


def to_vertical_html(text: str, quote: _QuoteState | None = None) -> str:
    """エスケープ解除済みのテキスト（タイトル等）を縦書き向けに変換し、エスケープ済みHTMLを返す

    英文は1文字ずつ縦に並べると読みにくいため、半角のまま（縦書きでは横倒し）残す
    quote: 段落の途中にタグを挟んで続けて変換するときに、引用符の対応を引き継ぐ
    """
    if quote is None:
        quote = _QuoteState()
    out = []
    pos = 0
    text = text.translate(_NORMALIZE)
    for m in _ENGLISH_CANDIDATE.finditer(text):
        english = m.group(0).translate(_ENGLISH_TO_ASCII)
        if _is_english_sentence(english):
            out.append(_convert_part(text[pos : m.start()], quote))
            out.append(html.escape(english, quote=False))
            pos = m.end()
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
            # “ は常に開き。” と " は書き手によって向きがばらつくため、段落内で開き・閉じを交互にする
            quote.is_open = s == "\u201c" or not quote.is_open
            out.append("〝" if quote.is_open else "〟")
        else:
            out.append(_to_zenkaku(s))
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def _convert_outside_tags(text: str) -> str:
    """HTMLタグの外側のテキスト部分を縦書き向けに変換

    &amp; などのエンティティは一度文字に戻してから変換する（記号は全角になる）
    ルビなどのタグをまたいでも、段落内の引用符の対応は引き継ぐ
    """
    out = []
    quote = _QuoteState()
    for part in _TAG_SPLIT.split(text):
        if part.startswith("<"):
            if _PARAGRAPH_BOUNDARY.match(part):
                quote = _QuoteState()
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
