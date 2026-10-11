# MySQLWhitelist

Rust サーバー向けの MySQL ホワイトリストプラグインです。`whitelist` テーブルの `steamid` を読み込み、登録された Steam ID の接続を許可します。

- バージョン: **1.0.0**
- 作者: **pakupaku**
- 対象: Rust Dedicated Server + Oxide.Rust
- 日本語が標準。設定で英語へ切り替え可能。

Discord から登録・解除したい場合は、同梱の [Discord Bot と導入手順](Discord_Bot/README.md) を利用できます。

## 導入

1. [Releases](https://github.com/pakupaku-dev/MySQLWhitelist/releases/latest) から `MySQLWhitelist.cs` をダウンロードし、サーバーの `oxide/plugins/` に配置します。Rust/Oxide が C# をコンパイルするため、JAR や事前ビルドした DLL は不要です。
2. 生成された `oxide/config/MySQLWhitelist.json` に MySQL の接続情報を設定します。[設定例](examples/MySQLWhitelist.json) も利用できます。
3. サーバーコンソールで `oxide.reload MySQLWhitelist` を実行します。

MySQL データベース自体は事前に用意してください。接続ユーザーには対象テーブルへの `SELECT` と、初回テーブル作成時の `CREATE` 権限が必要です。接続情報はご自身のサーバーの設定ファイルだけに保存します。

## 設定

```json
{
  "host": "localhost",
  "port": 3306,
  "username": "rust_whitelist",
  "password": "",
  "database": "rust",
  "language": "ja"
}
```

`language` は `ja` または `en`。省略時・未対応の値は日本語になります。ログイン拒否、切断、取得結果のメッセージに適用されます。メッセージ本文は `oxide/lang/ja/MySQLWhitelist.json` または `oxide/lang/en/MySQLWhitelist.json` で編集できます。サーバー共通の言語設定なので、プレイヤー個別の言語設定には依存しません。

既存の `host` / `port` / `username` / `password` / `database` キーは継続利用できます。既存設定を読み込み時に書き換えることはありません。設定ファイルが不正な場合は接続を拒否し、修正・再読み込みを待ちます。

## DB と判定の動作

未作成の場合は次のテーブルを自動作成します。既存テーブルの構造は変更しません。

```sql
CREATE TABLE IF NOT EXISTS `whitelist` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `steamid` VARCHAR(255) NOT NULL,
  PRIMARY KEY (`id`)
);
```

既存の管理ツール、または同梱の [Discord Bot](Discord_Bot/README.md) から Steam ID を登録してください。Bot はプラグインと同じデータベースを使用します。

判定結果を維持するため、従来の動作を次のとおり引き継いでいます。

- 起動時・プラグイン再読み込み時と、サーバー保存時に DB を非同期で取得します。
- 読み込んだ Steam ID と完全一致する場合に接続を許可します。管理者も例外ではありません。初回取得の完了前は未登録として接続を拒否します。
- 取得した ID をメモリに追加します。重複はまとめますが、接続可否は従来のリスト検索と同じです。
- **DB から ID を削除した場合、プラグインを再読み込みするまで登録状態を保持します。** 即時に削除を反映するには `oxide.reload MySQLWhitelist` を実行してください。
- サーバー保存時は、その時点でメモリにある登録情報で接続中のプレイヤーを確認し、未登録なら切断します。その保存時に開始した DB 取得結果は、以降のログイン・保存時の判定に利用されます。
- 取得エラー時は読み込み済みの ID を保持し、次のサーバー保存時に再試行します。
- このプラグインで許可された場合も、BAN や他のプラグインによる接続制限は引き続き適用されます。

## 1.0.0 の整理内容

既存の個人用コードを公開版 **1.0.0** として整理しました。

- 日本語・英語メッセージと日本語の導入説明を追加。
- 検索を `List` から `HashSet` に変更し、同じ ID の重複蓄積を抑制。
- 現行の `CanUserLogin(name, id, ipAddress)` を使用。許可時は `null`、拒否時は理由を返す構成。
- Oxide の Covalence API で接続中プレイヤーを扱い、Rust のゲーム内部クラスへの直接依存を削減。
- DB 接続を再利用し、アンロード時に解放。取得の重複・失敗・アンロード後のコールバックを処理。

## 確認状況

2026-10-11 時点の公式最新リリース [Oxide.Rust 2.0.7820](https://github.com/OxideMod/Oxide.Rust/releases/tag/2.0.7820) の配布 DLL を参照し、警告をエラーとしてコンパイルを確認しました。

回帰テストでは、旧方式との接続可否の比較、重複 ID、空の取得結果、削除後のキャッシュ、非同期取得と保存時の判定順序、DB エラー、日本語・英語、アンロード後の結果無視を確認しています。テスト内の外部 API はスタブです。

**実サーバーでの接続テストも、ユーザーによる実施・確認済みです（2026-10-11）。**

Windows の .NET Framework C# コンパイラーで実行できます。

```powershell
.\tests\verify.ps1 -ManagedDirectory 'C:\path\to\Oxide\RustDedicated_Data\Managed'
```

`ManagedDirectory` には公式 Oxide.Rust 配布物のディレクトリを指定してください。省略時は回帰テストのみ実行します。出力は `tests/output/` に保存します。

参照: [Oxide 接続フック](https://docs.oxidemod.com/guides/developers/server-lifecycle)、[MySQL API](https://docs.oxidemod.com/guides/developers/database)。
