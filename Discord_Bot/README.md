# Rust ホワイトリスト Discord Bot

Discord のボタンと入力フォームから、[MySQLWhitelist](../README.md) と共通の MySQL データベースへ Steam ID を登録する Bot です。日本語対応、バージョン **1.0.0**、作者 **pakupaku**。

## 機能

| 操作 | 内容 | 利用者 |
| --- | --- | --- |
| `/rustpanel` | 登録・解除ボタンのあるパネルを投稿 | 指定の管理者ロール |
| パネルの「登録」 | Steam ID を入力し、Discord アカウントと紐づけて登録 | 参加者 |
| パネルの「解除」 | 自分に紐づく Steam ID の登録を解除 | 参加者 |
| `/check` | 自分の登録・ブロック状態を確認 | 参加者 |
| `/block` | Steam ID と任意の Discord ID をブロック | 指定の管理者ロール |
| `/unblock` | Steam ID のブロックを解除 | 指定の管理者ロール |
| `/help` | コマンドの説明 | 参加者 |

操作は指定チャンネルに限定されます。登録結果などは操作した本人だけに表示します。パネルのボタンは Bot の再起動後も使用できます。

## 準備

- Python 3.11 以上
- Discord Bot のトークンと、登録先サーバー・操作チャンネル・管理者ロールの ID
- Steam Web API キー
- MySQL データベースと接続ユーザー
- MySQLWhitelist を導入済みの Rust / Oxide サーバーと WebRCON 接続情報

[Discord Developer Portal](https://discord.com/developers/applications) で Bot を用意し、`bot` と `applications.commands` スコープで対象サーバーに招待します。対象チャンネルで「チャンネルを見る」「メッセージを送信」「埋め込みリンク」の権限を付与してください。スラッシュコマンドとボタンを使用するため、Message Content Intent は不要です。

## 起動手順（Windows PowerShell）

リポジトリをダウンロードし、`Discord_Bot` フォルダーで実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` を編集して実際の設定を入力します。サンプルのままでは起動しません。

| 変数 | 設定内容 |
| --- | --- |
| `DISCORD_TOKEN` | Discord Bot トークン |
| `TARGET_GUILD_ID` | 対象の Discord サーバー ID |
| `ALLOWED_CHANNEL_ID` | 操作を許可するチャンネル ID |
| `ADMIN_ROLE_ID` | 管理用コマンドを許可するロール ID |
| `MYSQL_HOST` / `MYSQL_PORT` | MySQL ホスト名 / ポート（標準 3306） |
| `MYSQL_USER` / `MYSQL_PASSWORD` | DB 接続ユーザー / パスワード |
| `MYSQL_DATABASE` | MySQLWhitelist と同じデータベース名 |
| `STEAM_API_KEY` | [Steam Web API キー](https://steamcommunity.com/dev/apikey) |
| `STEAM_REQUEST_TIMEOUT_SECONDS` | Steam API の待ち時間（標準 10 秒） |
| `RCON_HOST` / `RCON_PORT` / `RCON_PASSWORD` | Rust の WebRCON ホスト / ポート / パスワード |

MySQL の管理ツールで対象データベースを選び、[`schema.sql`](schema.sql) を実行します。Bot の DB ユーザーにはこの3テーブルへの `SELECT`・`INSERT`・`UPDATE`・`DELETE` 権限が必要です。既存 DB を使う場合はテーブルと列を確認してください。SQL は既存テーブルを変更しません。

Rust サーバーで WebRCON（`rcon.web 1`）を有効にし、`.env` の接続先と一致させます。Bot と Rust サーバーが別のマシンにある場合は `localhost` を実際のホスト名へ変更してください。WebRCON はサーバー操作権限を持つため、接続を Bot のホストなど必要な接続元に限定します。

```powershell
.\.venv\Scripts\python.exe main.py
```

指定ロールを持つ管理者が、指定チャンネルで `/rustpanel` を実行すると、参加者向けパネルが表示されます。

Linux では仮想環境内の `bin/python` を使用してください。`.env` は `main.py` と同じフォルダーから読み込まれ、プロセスの環境変数が優先されます。

## Rust への反映

登録・解除・ブロック操作は DB 更新後、WebRCON で `oxide.reload MySQLWhitelist` を送信します。解除・ブロック時は対象への `global.kick` も送信します。ブロック解除は自動の再登録を行いません。

RCON 接続に失敗しても、コミット済みの DB 更新は残ります。その場合は接続情報を確認し、サーバー側でプラグインを再読み込みしてください。送信成功はコマンド実行完了の確認ではないため、反映はサーバーログで確認できます。

登録時は Steam API で指定 ID のプロフィールを取得します。**Steam OpenID によるアカウント所有者確認は行いません。** Steam ID を本人が入力する方式のため、信頼できる参加者向けの運用を想定しています。

## 設定ファイル

`.env.example` は架空の設定例です。実際の `.env`、トークン、パスワード、サーバー固有の ID は Git に含めないでください。`.gitignore` で `.env` と仮想環境を除外しています。接続失敗時の応答には、接続情報が含まれる可能性のある例外本文を表示しません。

## テスト

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

設定検証、登録・解除の DB 操作、管理者制限、接続エラー時の情報非表示を外部通信なしで確認します。この公開用 Bot の Discord / MySQL / Rust への接続はテスト中に行いません。

参考: [discord.py](https://discordpy.readthedocs.io/en/stable/intro.html)、[MySQL Connector/Python](https://dev.mysql.com/doc/connector-python/en/connector-python-example-connecting.html)、[Facepunch WebRCON](https://github.com/Facepunch/webrcon)。
