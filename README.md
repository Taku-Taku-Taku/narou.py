# narou.py

## 概要
小説家になろうの作品を Kindle 向け縦書き EPUB に変換する Python CLI ツールです。
ある程度の校正機能もついています。（例：一桁の数字は縦書きに）

**[小説家になろう](http://syosetu.com/) のみ**に対応しています。


## 必要環境

- Python 3.12+
- uv
  - pythonであればどれでも可能ですが、依存関係が楽なのでuvをお勧めします
  - インストール方法は後述

## インストール&セットアップ

[Releaseページ](https://github.com/Taku-Taku-Taku/narou.py/releases/)から最新版をダウンロード＆展開
```bash
uv sync
```
- [uvのinstall方法はこちら](https://docs.astral.sh/uv/getting-started/installation/) 

## 使い方

```bash
# 作品全話を変換
uv run python main.py <ncode>

# 話数を指定して変換　(例：1~10話まで) 
uv run python main.py <ncode> --start 1 --end 10

# 画像サイズを指定 (small: 6型, medium: 7型, large: 10型　指定がなければ、元の画像のまま)
uv run python main.py <ncode> --image-size medium

# 出力先を指定(デフォルト:"/output")
uv run python main.py <ncode> -o ./my_output

# キャッシュを無効にして取得
uv run python main.py <ncode> --no-cache

# 特定作品のキャッシュを削除
uv run python main.py <ncode> --clear-cache

# 全キャッシュを削除
uv run python main.py --clear-cache
```

<details>
<summary>ncodeとは？</summary>

各小説のURL https://ncode.syosetu.com/n0498fr/ （例：病毒の王 水木あおい）の **n0498fr** の部分です

</details>

生成されたファイルを、send to kindle (https://www.amazon.co.jp/sendtokindle/) などを用いて送信する必要があります。
（送信可能な容量が大きいのでweb版をお勧めします）

### オプション一覧

| オプション | 説明 |
|---|---|
| `--start N` | 開始話数 |
| `--end N` | 終了話数 |
| `--image-size` | 画像の最大解像度 (`small`(6型) / `medium`(7型) / `large`(10型))。未指定時はリサイズなし |
| `-o`, `--output` | 出力ディレクトリ (デフォルト: `output`(無ければ自動生成)) |
| `--no-cache` | キャッシュを使用しない |
| `--clear-cache` | キャッシュを削除 |


## 更新履歴
- 2026/2/15　リリース

もし、不具合・改善点等ありましたら、issueやpull requestなどを送っていただければ幸いです。

----

## 謝辞

本ツールは [whiteleaf](https://github.com/whiteleaf7) 氏の [Narou.rb](https://github.com/whiteleaf7/narou) を参考に開発されました。


## 免責事項

本ソフトウェアの使用または使用不能により生じた損害について、作者は一切の責任を負いません。
利用者は、対象サイトの利用規約・関連法令・著作権等を自己責任で遵守してください。作者は利用者の行為について責任を負いません。

----
「小説家になろう」は株式会社ヒナプロジェクトの登録商標です
