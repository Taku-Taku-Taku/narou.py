"""ルビ記法パーサー・テキスト変換

なろう記法:
  ｜親文字《ルビ》  → <ruby>親文字<rp>（</rp><rt>ルビ</rt><rp>）</rp></ruby>
  漢字《ルビ》      → <ruby>漢字<rp>（</rp><rt>ルビ</rt><rp>）</rp></ruby>
  《《傍点対象》》  → <em class="sesame">傍点対象</em>

縦書き向けの文字変換（タグ外のテキストのみ）:
  英数字のかたまり（12,000 / Lv.10 / B-29 など記号でつながった単位）を全体の文字数で判定
    1文字      → 全角 (A→Ａ, 5→５)
    2文字      → 縦中横 <span class="tcy">（横書きのまま1文字分に収める）
    3文字以上  → すべて全角にして縦に並べる
  元から全角の英数字（２９, ＨＰ）も同じルールで判定する
  ！？の連続も同様（2文字まで縦中横、3文字以上は全角）
  ギリシャ・キリル文字   → <span class="upright">（横倒しを防ぐ）
  その他の半角記号       → 全角 (%→％, (→（, -→－ など)
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
# 全角英数字 → 半角（判定ルールを半角・全角で揃えるため最初に正規化する）
_ZENKAKU_ALNUM_TO_ASCII = str.maketrans(
    "０１２３４５６７８９"
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
)

# 個別に置き換える文字（縦書きで横倒し・位置ずれするもの）
_CHAR_REPLACE = {
    "\u2212": "－",  # − マイナス
    "\u2010": "－",  # ‐ ハイフン
    "\u2011": "－",  # ‑ ノーブレークハイフン
    "\u22ef": "…",  # ⋯ 数学用の三点リーダ（縦書きで縦にならない）
    "\u2018": "＇",  # ‘
    "\u2019": "＇",  # ’
}

# 直後の引用符を「開き」とみなす文字（開き括弧類）
_OPENERS = "「『（(［[｛{〔【〈《〝"

# HTMLタグを避けてテキスト部分だけを処理するためのパターン
_TEXT_OUTSIDE_TAGS = re.compile(r"([^<>]+)(?=<|$)")

# 英数字のかたまり: 英数字の間に挟まった区切り記号も含めて1単位とする
# 「、」は「12、000」のように後ろが3桁ちょうどの数字のときだけ桁区切りとみなす
_ALNUM_TOKEN = re.compile(
    r"[A-Za-z0-9]+"
    r"(?:(?:[.,:'/\-，．：]|(?<=[0-9])、(?=[0-9]{3}(?![0-9])))[A-Za-z0-9]+)*"
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


def _convert_vertical(text: str) -> str:
    """エスケープ解除済みのテキストを縦書き向けに変換し、HTML断片を返す"""
    text = text.translate(_ZENKAKU_ALNUM_TO_ASCII)
    text = "".join(_CHAR_REPLACE.get(c, c) for c in text)
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
            # “ は常に開き。” と " は書き手によって向きがばらつくため、直前の文字で決める
            prev = text[m.start() - 1] if m.start() > 0 else ""
            is_open = s == "\u201c" or prev == "" or prev.isspace() or prev in _OPENERS
            out.append("〝" if is_open else "〟")
        else:
            out.append(_to_zenkaku(s))
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def to_vertical_html(text: str) -> str:
    """プレーンテキスト（タイトル等）を縦書き向けに変換し、エスケープ済みHTMLを返す"""
    return _convert_vertical(text)


def _convert_text_segment(match: re.Match) -> str:
    """HTMLタグの外側のテキスト部分を縦書き向けに変換

    &amp; などのエンティティは一度文字に戻してから変換する（記号は全角になる）
    """
    return _convert_vertical(html.unescape(match.group(0)))


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
        text = _TEXT_OUTSIDE_TAGS.sub(_convert_text_segment, text)
        return text
