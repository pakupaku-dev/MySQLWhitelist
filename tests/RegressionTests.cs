// 外部サーバーへ接続しない回帰テスト。実 API のコンパイル確認とは別に実行する。
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using Oxide.Plugins;

namespace Newtonsoft.Json
{
    public sealed class JsonPropertyAttribute : Attribute
    {
        public JsonPropertyAttribute(string name) { }
    }
}
namespace Oxide.Core.Database
{
    public class Connection { }
    public class Sql
    {
        public string SQL;
        public static Sql Builder { get { return new Sql(); } }
        public Sql Append(string sql) { SQL = sql; return this; }
    }
}
namespace Oxide.Core
{
    public static class Interface
    {
        public static readonly FakeOxide Oxide = new FakeOxide();
    }
    public class FakeOxide
    {
        public MySql.Libraries.MySql Database = new MySql.Libraries.MySql();
        public T GetLibrary<T>() { return (T)(object)Database; }
    }
}
namespace Oxide.Core.MySql.Libraries
{
    public class MySql
    {
        public int Opens, Closes, Queries;
        public bool ThrowOnOpen;
        public Action<List<Dictionary<string, object>>> Callback;
        public Database.Connection OpenDb(string host, int port, string db, string user,
            string password, object plugin, bool persistent)
        {
            if (ThrowOnOpen) throw new Exception("test failure");
            Opens++;
            return new Database.Connection();
        }
        public void CloseDb(Database.Connection connection) { Closes++; }
        public void ExecuteNonQuery(Database.Sql sql, Database.Connection connection) { }
        public void Query(Database.Sql sql, Database.Connection connection,
            Action<List<Dictionary<string, object>>> callback)
        {
            if (sql.SQL != "SELECT `steamid` FROM `whitelist`") throw new Exception("Unexpected query");
            Queries++;
            Callback = callback;
        }
    }
}
namespace Oxide.Core.Libraries.Covalence
{
    public interface IPlayer { string Id { get; } void Kick(string reason); }
}
namespace Oxide.Plugins
{
    public sealed class InfoAttribute : Attribute
    {
        public InfoAttribute(string title, string author, string version) { }
    }
    public sealed class DescriptionAttribute : Attribute
    {
        public DescriptionAttribute(string text) { }
    }
    public class FakeConfig
    {
        public bool ThrowOnRead;
        public int Writes;
        public T ReadObject<T>()
        {
            if (ThrowOnRead) throw new Exception("test malformed config");
            return (T)Activator.CreateInstance(typeof(T), true);
        }
        public void WriteObject(object value, bool pretty) { Writes++; }
    }
    public class FakeLang
    {
        public readonly Dictionary<string, Dictionary<string, string>> Messages = new Dictionary<string, Dictionary<string, string>>();
        public void RegisterMessages(Dictionary<string, string> values, object plugin, string language)
        { Messages[language] = values; }
        public string GetMessageByLanguage(string key, object plugin, string language)
        { return Messages[language][key]; }
    }
    public class FakePlayers
    {
        public readonly List<Oxide.Core.Libraries.Covalence.IPlayer> Connected = new List<Oxide.Core.Libraries.Covalence.IPlayer>();
    }
    public class CovalencePlugin
    {
        public readonly FakeConfig Config = new FakeConfig();
        public readonly FakeLang lang = new FakeLang();
        public readonly FakePlayers players = new FakePlayers();
        protected virtual void LoadDefaultConfig() { }
        protected virtual void LoadConfig() { }
        protected virtual void SaveConfig() { }
        protected virtual void LoadDefaultMessages() { }
        protected void PrintError(string message) { }
        protected void PrintWarning(string message) { }
        protected void Puts(string message) { }
    }
}

internal class RegressionTests
{
    private class Player : Oxide.Core.Libraries.Covalence.IPlayer
    {
        public string Id { get; set; }
        public string KickReason;
        public void Kick(string reason) { KickReason = reason; }
    }
    private static int assertions;
    private static object Call(MySQLWhitelist plugin, string method, params object[] args)
    {
        return typeof(MySQLWhitelist).GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(plugin, args);
    }
    private static void Check(bool result, string name)
    {
        assertions++;
        if (!result) throw new Exception(name);
    }
    private static MySQLWhitelist NewPlugin()
    {
        Oxide.Core.Interface.Oxide.Database = new Oxide.Core.MySql.Libraries.MySql();
        var plugin = new MySQLWhitelist();
        Call(plugin, "LoadDefaultMessages");
        Call(plugin, "LoadConfig");
        return plugin;
    }
    private static List<Dictionary<string, object>> Rows(params string[] ids)
    {
        return ids.Select(id => new Dictionary<string, object> { { "steamid", id } }).ToList();
    }
    private static bool Allowed(MySQLWhitelist plugin, string id)
    {
        return Call(plugin, "CanUserLogin", "Test", id, "127.0.0.1") == null;
    }
    public static int Main()
    {
        var plugin = NewPlugin();
        var db = Oxide.Core.Interface.Oxide.Database;
        Check(!Allowed(plugin, "76561198000000001"), "Empty startup rejects login");
        Check(((string)Call(plugin, "CanUserLogin", "Test", "unknown", "127.0.0.1")).Contains("登録"), "Japanese is default");
        Call(plugin, "OnServerInitialized");
        Call(plugin, "OnServerInitialized");
        Check(db.Queries == 1, "Pending query is not duplicated");
        db.Callback(Rows("76561198000000001", "76561198000000001"));
        Check(Allowed(plugin, "76561198000000001"), "Known ID allowed");
        Check(!Allowed(plugin, "76561198000000002"), "Unknown ID rejected");
        var known = new Player { Id = "76561198000000001" };
        var addedLater = new Player { Id = "76561198000000002" };
        plugin.players.Connected.Add(known);
        plugin.players.Connected.Add(addedLater);
        Call(plugin, "OnServerSave");
        Check(known.KickReason == null && addedLater.KickReason != null, "Save checks existing cache before async completion");
        db.Callback(Rows(addedLater.Id));
        Check(Allowed(plugin, known.Id) && Allowed(plugin, addedLater.Id), "Additive cache preserves original removal behavior");
        Call(plugin, "OnServerSave");
        db.Callback(null);
        Check(Allowed(plugin, known.Id), "Database failure preserves cached IDs");
        Call(plugin, "OnServerSave");
        db.Callback(Rows());
        Check(Allowed(plugin, known.Id), "Empty refresh preserves original cache behavior");
        Check(db.Opens == 1, "Connection reused");

        var originalList = new List<string> { known.Id, addedLater.Id };
        var random = new Random(42);
        for (int batch = 0; batch < 100; batch++)
        {
            string[] ids = Enumerable.Range(0, random.Next(0, 30)).Select(i => random.Next(0, 70).ToString()).ToArray();
            originalList.AddRange(ids);
            Call(plugin, "OnServerInitialized");
            db.Callback(Rows(ids));
            for (int id = 0; id < 100; id++)
                Check(Allowed(plugin, id.ToString()) == originalList.Contains(id.ToString()), "Original List and HashSet membership agree");
        }
        object config = typeof(MySQLWhitelist).GetField("configuration", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(plugin);
        config.GetType().GetField("Language").SetValue(config, "en");
        Check((string)Call(plugin, "CanUserLogin", "Test", "unknown", "127.0.0.1") == "You are not whitelisted!", "English is selectable");
        config.GetType().GetField("Language").SetValue(config, "unsupported");
        Check(((string)Call(plugin, "CanUserLogin", "Test", "unknown", "127.0.0.1")).Contains("登録"), "Unknown language falls back to Japanese");
        Call(plugin, "Unload");
        db.Callback(Rows("late"));
        Check(db.Closes == 1 && !Allowed(plugin, "late"), "Unloaded plugin ignores delayed callback");
        var fresh = NewPlugin();
        Check(!Allowed(fresh, known.Id), "Reload clears removed IDs");
        fresh.Config.ThrowOnRead = true;
        Call(fresh, "LoadConfig");
        Call(fresh, "OnServerInitialized");
        Check(Oxide.Core.Interface.Oxide.Database.Queries == 0 && fresh.Config.Writes == 0, "Bad config does not query or overwrite file");
        fresh = NewPlugin();
        db = Oxide.Core.Interface.Oxide.Database;
        db.ThrowOnOpen = true;
        Call(fresh, "OnServerInitialized");
        db.ThrowOnOpen = false;
        Call(fresh, "OnServerSave");
        Check(db.Queries == 1, "Failed submission is retried on next save");
        Console.WriteLine("PASS: " + assertions + " assertions (including 10,000 original/new membership comparisons)");
        return 0;
    }
}
