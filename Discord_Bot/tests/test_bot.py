import contextlib
import importlib.util
import io
import os
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


# 実際の .env を読み込まず、Bot のログインも開始しない。
with patch.dict(os.environ, {}, clear=True), patch("dotenv.load_dotenv"):
    spec = importlib.util.spec_from_file_location("whitelist_bot", Path(__file__).parents[1] / "main.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)


def interaction():
    return SimpleNamespace(
        user=SimpleNamespace(id=123, roles=[]),
        guild=SimpleNamespace(id=456),
        channel=SimpleNamespace(id=789),
        response=SimpleNamespace(is_done=Mock(return_value=True), send_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


class ConfigurationTests(unittest.TestCase):
    def test_public_defaults_do_not_connect(self):
        with self.assertRaisesRegex(RuntimeError, "DISCORD_TOKEN"):
            app.validate_configuration()

    def test_placeholder_rejected_without_echoing_secrets(self):
        with patch.object(app, "TOKEN", "change-this-discord-token"):
            with self.assertRaises(RuntimeError) as result:
                app.validate_configuration()
        self.assertNotIn("change-this-discord-token", str(result.exception))

    def test_valid_configuration(self):
        values = dict(TOKEN="test-token", MYSQL_PASSWORD="test-password",
                      STEAM_API_KEY="test-key", RCON_PASSWORD="test-rcon",
                      TARGET_GUILD_ID=1, ALLOWED_CHANNEL_ID=2, ADMIN_ROLE_ID=3)
        with patch.multiple(app, **values):
            app.validate_configuration()

    def test_steam_id_validation(self):
        self.assertTrue(app.validate_steam_id("76561198000000001"))
        self.assertFalse(app.validate_steam_id("not-an-id"))
        self.assertFalse(app.validate_steam_id("76561198000000001; quit"))


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_commits_before_rcon(self):
        request = interaction()
        conn, cursor = Mock(), Mock()
        conn.cursor.return_value = cursor
        cursor.fetchone.side_effect = [None, None, None, None]
        order = []
        conn.commit.side_effect = lambda: order.append("commit")
        with patch.object(app, "get_db_connection", return_value=conn), \
             patch.object(app, "get_player_info", return_value={"personaname": "Test", "avatar": "https://example.com/avatar.png"}), \
             patch.object(app, "reload_rust_whitelist", side_effect=lambda: order.append("rcon")):
            await app.handle_register(request, "76561198000000001")
        self.assertEqual(order, ["commit", "rcon"])
        self.assertTrue(any(call.args == ("INSERT INTO whitelist (steamid) VALUES (%s)", ("76561198000000001",))
                            for call in cursor.execute.call_args_list))
        cursor.close.assert_called_once()
        conn.close.assert_called_once()

    async def test_blocked_registration_does_not_write(self):
        request, conn = interaction(), Mock()
        conn.cursor.return_value.fetchone.return_value = ("76561198000000001", None)
        with patch.object(app, "get_db_connection", return_value=conn), \
             patch.object(app, "get_player_info") as steam:
            await app.handle_register(request, "76561198000000001")
        steam.assert_not_called()
        conn.commit.assert_not_called()

    async def test_unregister_only_own_id(self):
        request, conn = interaction(), Mock()
        conn.cursor.return_value.fetchone.return_value = ("76561198000000002",)
        with patch.object(app, "get_db_connection", return_value=conn), \
             patch.object(app, "reload_rust_whitelist") as rcon:
            await app.handle_unregister(request, "76561198000000001")
        conn.commit.assert_not_called()
        rcon.assert_not_called()

    async def test_unregister_deletes_and_kicks(self):
        request, conn = interaction(), Mock()
        conn.cursor.return_value.fetchone.side_effect = [("76561198000000001",), (1, "76561198000000001")]
        with patch.object(app, "get_db_connection", return_value=conn), \
             patch.object(app, "reload_rust_whitelist") as rcon:
            await app.handle_unregister(request, "76561198000000001")
        conn.commit.assert_called_once()
        rcon.assert_called_once_with(kick_steam_id="76561198000000001")

    async def test_connection_error_does_not_disclose_details(self):
        request = interaction()
        log = io.StringIO()
        with patch.object(app, "get_db_connection", side_effect=app.mysql.connector.Error("private-db-details")), \
             contextlib.redirect_stdout(log):
            await app.handle_check(request)
        self.assertNotIn("private-db-details", str(request.followup.send.call_args))
        self.assertNotIn("private-db-details", log.getvalue())
        request.followup.send.assert_awaited_once()

    async def test_rcon_error_does_not_disclose_password(self):
        request, conn = interaction(), Mock()
        conn.cursor.return_value.fetchone.side_effect = [("76561198000000001",), (1, "76561198000000001")]
        log = io.StringIO()
        with patch.object(app, "get_db_connection", return_value=conn), \
             patch.object(app, "reload_rust_whitelist", side_effect=RuntimeError("private-rcon-password")), \
             contextlib.redirect_stdout(log):
            await app.handle_unregister(request, "76561198000000001")
        self.assertNotIn("private-rcon-password", str(request.followup.send.call_args))
        self.assertNotIn("private-rcon-password", log.getvalue())
        conn.commit.assert_called_once()

    async def test_wrong_channel_denied(self):
        with patch.object(app, "ALLOWED_CHANNEL_ID", 999):
            self.assertFalse(await app.ensure_allowed_channel(interaction()))

    async def test_admin_requires_configured_role(self):
        request = interaction()
        with patch.multiple(app, ALLOWED_CHANNEL_ID=789, ADMIN_ROLE_ID=999):
            self.assertFalse(await app.ensure_admin(request))
            request.user.roles = [SimpleNamespace(id=999)]
            self.assertTrue(await app.ensure_admin(request))


if __name__ == "__main__":
    unittest.main()
