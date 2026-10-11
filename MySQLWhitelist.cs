using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json;
using Oxide.Core;
using Oxide.Core.Database;
using Oxide.Core.Libraries.Covalence;
using Oxide.Core.MySql.Libraries;

namespace Oxide.Plugins
{
    [Info("MySQL Whitelist", "pakupaku", "1.0.0")]
    [Description("MySQL の登録 Steam ID で接続を制限する日本語対応ホワイトリスト")]
    public class MySQLWhitelist : CovalencePlugin
    {
        private const string SelectQuery = "SELECT `steamid` FROM `whitelist`";
        private const string CreateQuery = "CREATE TABLE IF NOT EXISTS `whitelist` (`id` INT(11) NOT NULL AUTO_INCREMENT, `steamid` VARCHAR(255) NOT NULL, PRIMARY KEY (`id`))";

        private readonly MySql database = Interface.Oxide.GetLibrary<MySql>();
        private readonly HashSet<string> allowedIds = new HashSet<string>(StringComparer.Ordinal);
        private Configuration configuration;
        private Connection connection;
        private bool configurationValid;
        private bool refreshPending;
        private bool unloaded;

        private class Configuration
        {
            [JsonProperty("host")] public string Host = "localhost";
            [JsonProperty("port")] public int Port = 3306;
            [JsonProperty("username")] public string Username = "rust_whitelist";
            [JsonProperty("password")] public string Password = "";
            [JsonProperty("database")] public string Database = "rust";
            [JsonProperty("language")] public string Language = "ja";
        }

        protected override void LoadDefaultConfig()
        {
            configuration = new Configuration();
        }

        protected override void LoadConfig()
        {
            base.LoadConfig();
            configurationValid = false;
            try
            {
                configuration = Config.ReadObject<Configuration>();
                if (configuration == null || string.IsNullOrWhiteSpace(configuration.Host)
                    || string.IsNullOrWhiteSpace(configuration.Username)
                    || string.IsNullOrWhiteSpace(configuration.Database)
                    || configuration.Port < 1 || configuration.Port > 65535)
                {
                    throw new InvalidOperationException();
                }
                configurationValid = true;
            }
            catch (Exception)
            {
                // 接続情報を含む例外や設定内容をログへ出さない。
                configuration = new Configuration();
                PrintError("MySQLWhitelist の設定を読み込めません。host / port / username / password / database を確認してください。設定ファイルは上書きしていません。");
            }
        }

        protected override void SaveConfig()
        {
            Config.WriteObject(configuration, true);
        }

        private void OnServerInitialized()
        {
            RefreshWhitelist();
        }

        private void OnServerSave()
        {
            // 元の処理と同様、保存時は現在のキャッシュで判定する。
            // 非同期の取得結果は以降のログイン・保存時の判定に反映される。
            IPlayer[] connected = players.Connected.ToArray();
            RefreshWhitelist();
            foreach (IPlayer player in connected)
            {
                if (!IsWhitelisted(player.Id))
                    player.Kick(Message("NotWhitelisted"));
            }
        }

        private object CanUserLogin(string name, string id, string ipAddress)
        {
            // 許可時は他プラグインの接続制限も処理できるよう null を返す。
            return IsWhitelisted(id) ? null : (object)Message("NotWhitelisted");
        }

        private bool IsWhitelisted(string id)
        {
            return id != null && allowedIds.Contains(id);
        }

        private void RefreshWhitelist()
        {
            if (!configurationValid || unloaded || refreshPending)
                return;

            refreshPending = true;
            try
            {
                if (connection == null)
                {
                    connection = database.OpenDb(configuration.Host, configuration.Port,
                        configuration.Database, configuration.Username, configuration.Password, this, true);
                }
                database.ExecuteNonQuery(Sql.Builder.Append(CreateQuery), connection);
                database.Query(Sql.Builder.Append(SelectQuery), connection, OnWhitelistLoaded);
            }
            catch (Exception)
            {
                refreshPending = false;
                PrintWarning(Message("DatabaseError"));
            }
        }

        private void OnWhitelistLoaded(List<Dictionary<string, object>> rows)
        {
            if (unloaded)
                return;

            refreshPending = false;
            if (rows == null)
            {
                PrintWarning(Message("DatabaseError"));
                return;
            }

            // 元の追加方式を維持。DBからの削除はプラグイン再読み込みで反映する。
            foreach (Dictionary<string, object> row in rows)
            {
                object value;
                if (row != null && row.TryGetValue("steamid", out value) && value != null)
                    allowedIds.Add(value.ToString());
            }
            Puts(string.Format(Message("Updated"), allowedIds.Count));
        }

        private void Unload()
        {
            unloaded = true;
            if (connection != null)
            {
                database.CloseDb(connection);
                connection = null;
            }
            allowedIds.Clear();
        }

        protected override void LoadDefaultMessages()
        {
            lang.RegisterMessages(new Dictionary<string, string>
            {
                { "NotWhitelisted", "このサーバーのホワイトリストに登録されていません。" },
                { "DatabaseError", "ホワイトリストを取得できませんでした。現在の登録情報を維持し、次のサーバー保存時に再試行します。" },
                { "Updated", "ホワイトリストを読み込みました（登録済み: {0} 人）。" }
            }, this, "ja");
            lang.RegisterMessages(new Dictionary<string, string>
            {
                { "NotWhitelisted", "You are not whitelisted!" },
                { "DatabaseError", "Could not load the whitelist. Keeping cached IDs; retrying on the next server save." },
                { "Updated", "Whitelist loaded ({0} cached players)." }
            }, this, "en");
        }

        private string Message(string key)
        {
            string language = configuration != null && configuration.Language == "en" ? "en" : "ja";
            return lang.GetMessageByLanguage(key, this, language);
        }
    }
}
