import json
import os
import time
from pathlib import Path

import discord
import mysql.connector
import requests
import websocket
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

__version__ = "1.0.0"
__author__ = "pakupaku"

# Bot configuration
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "rust_whitelist")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "rust")
STEAM_API_KEY = os.getenv("STEAM_API_KEY", "").strip()
STEAM_REQUEST_TIMEOUT_SECONDS = float(os.getenv("STEAM_REQUEST_TIMEOUT_SECONDS", "10"))

# Restrict slash commands to one channel
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID", "0"))
TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", "0"))

# Admin role ID
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))

# RCON configuration
RCON_HOST = os.getenv("RCON_HOST", "localhost")
RCON_PORT = os.getenv("RCON_PORT", "28016")
RCON_PASSWORD = os.getenv("RCON_PASSWORD", "")

intents = discord.Intents.default()


class WhitelistBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.commands_synced = False
        self.panel_view_registered = False


bot = WhitelistBot()


class SteamApiConfigurationError(RuntimeError):
    pass


def is_placeholder_secret(value, placeholder):
    return not value or value.strip().lower() == placeholder


def ensure_steam_api_key():
    if is_placeholder_secret(STEAM_API_KEY, "change-this-steam-api-key"):
        raise SteamApiConfigurationError(
            "Steam APIキーが未設定です。管理者は .env の STEAM_API_KEY に有効なキーを設定して Bot を再起動してください。"
        )


def get_db_connection():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        connection_timeout=10,
    )


def get_player_info(steam_id):
    ensure_steam_api_key()
    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
    response = requests.get(
        url,
        params={
            "key": STEAM_API_KEY,
            "steamids": steam_id,
            "format": "json",
        },
        timeout=STEAM_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    players = (data.get("response") or {}).get("players") or []
    return players[0] if players else None


def build_help_embed():
    embed = discord.Embed(
        title="ホワイトリスト管理ボットのヘルプ",
        description="以下のスラッシュコマンドが使用できます。",
        color=discord.Color.blue(),
    )
    embed.add_field(name="/rustpanel", value="管理者が参加者向けのホワイトリスト操作パネルを表示します。", inline=False)
    embed.add_field(name="/check", value="自分の Steam ID の登録状態を確認します。", inline=False)
    embed.add_field(name="/block", value="管理者用。モーダルで Steam ID と任意の Discord ID を入力してブロックします。", inline=False)
    embed.add_field(name="/unblock", value="管理者用。モーダルで Steam ID を入力してブロック解除します。", inline=False)
    embed.add_field(name="/help", value="このヘルプを表示します。", inline=False)
    embed.set_footer(text="これらのコマンドは指定されたチャンネルでのみ使用できます。")
    return embed


def build_panel_embed():
    embed = discord.Embed(
        title="Rust ホワイトリスト操作パネル",
        description="下のボタンから登録または解除を選び、ポップアップに Steam ID を入力してください。",
        color=discord.Color.orange(),
    )
    embed.add_field(name="登録", value="自分の Discord アカウントと Steam ID を紐づけてホワイトリストへ追加します。", inline=False)
    embed.add_field(name="解除", value="自分に紐づく Steam ID をホワイトリストから削除します。", inline=False)
    embed.set_footer(text="このパネルは指定チャンネル用です。")
    return embed


async def send_response(interaction, content=None, embed=None, ephemeral=True):
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
        return
    await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)


async def ensure_allowed_channel(interaction):
    if interaction.guild is None:
        await send_response(interaction, "このコマンドはサーバー内でのみ使用できます。")
        return False

    if not interaction.channel or interaction.channel.id != ALLOWED_CHANNEL_ID:
        await send_response(interaction, "このコマンドは指定されたチャンネルでのみ使用できます。")
        return False

    return True


def user_has_admin_role(user):
    return any(role.id == ADMIN_ROLE_ID for role in getattr(user, "roles", []))


async def ensure_admin(interaction):
    if not await ensure_allowed_channel(interaction):
        return False

    if not user_has_admin_role(interaction.user):
        await send_response(interaction, "このコマンドは管理者のみが使用できます。")
        return False

    return True


def validate_steam_id(steam_id):
    steam_id = (steam_id or "").strip()
    return steam_id.isdigit() and len(steam_id) == 17


def connect_rust_rcon(command):
    server_uri = f"ws://{RCON_HOST}:{RCON_PORT}/{RCON_PASSWORD}"
    ws = websocket.WebSocket()
    command_json = json.dumps(
        {
            "Identifier": 1,
            "Message": command,
            "Name": "WebRcon",
        }
    )

    try:
        ws.connect(server_uri, timeout=10)
        ws.send(command_json)
        time.sleep(1)
    finally:
        ws.close()


def reload_rust_whitelist(kick_steam_id=None):
    connect_rust_rcon("oxide.reload MySQLWhitelist")
    if kick_steam_id:
        time.sleep(1)
        connect_rust_rcon(f"global.kick {kick_steam_id}")


async def sync_slash_commands():
    if bot.commands_synced:
        return

    guilds_to_sync = []

    if TARGET_GUILD_ID:
        target_guild = bot.get_guild(TARGET_GUILD_ID)
        if target_guild is not None:
            guilds_to_sync.append(target_guild)
        else:
            print(
                f"TARGET_GUILD_ID={TARGET_GUILD_ID} にアクセスできません。"
                " ALLOWED_CHANNEL_ID から同期先を推定します。"
            )

    if not guilds_to_sync and ALLOWED_CHANNEL_ID:
        allowed_channel = bot.get_channel(ALLOWED_CHANNEL_ID)
        if allowed_channel is None:
            try:
                allowed_channel = await bot.fetch_channel(ALLOWED_CHANNEL_ID)
            except (discord.Forbidden, discord.HTTPException) as exc:
                print(f"ALLOWED_CHANNEL_ID={ALLOWED_CHANNEL_ID} の取得に失敗しました: {exc}")

        guild = getattr(allowed_channel, "guild", None)
        if guild is not None:
            guilds_to_sync.append(guild)
            print(f"ALLOWED_CHANNEL_ID から同期先ギルドを解決しました: {guild.name} ({guild.id})")

    if not guilds_to_sync and bot.guilds:
        guilds_to_sync.extend(bot.guilds)
        print("同期先ギルドを設定から解決できなかったため、参加中の全サーバーへ同期します。")

    synced_any = False
    if guilds_to_sync:
        seen_guild_ids = set()
        for guild in guilds_to_sync:
            if guild.id in seen_guild_ids:
                continue
            seen_guild_ids.add(guild.id)
            try:
                bot.tree.clear_commands(guild=guild)
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                print(f"Synced {len(synced)} command(s) to guild {guild.name} ({guild.id})")
                synced_any = True
            except discord.Forbidden as exc:
                print(f"Guild {guild.id} への同期が拒否されました: {exc}")
            except discord.HTTPException as exc:
                print(f"Guild {guild.id} への同期に失敗しました: {exc}")
    else:
        try:
            synced = await bot.tree.sync()
            print(f"Globally synced {len(synced)} command(s)")
            synced_any = True
        except discord.HTTPException as exc:
            print(f"Global sync failed: {exc}")

    if not synced_any:
        joined = ", ".join(f"{guild.name} ({guild.id})" for guild in bot.guilds) or "なし"
        print(f"スラッシュコマンドを同期できませんでした。Bot が参加中のサーバー: {joined}")
        return

    bot.commands_synced = True


@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")
    print(f"Target guild ID: {TARGET_GUILD_ID if TARGET_GUILD_ID else 'all joined guilds'}")
    print(f"Whitelist commands are restricted to channel ID: {ALLOWED_CHANNEL_ID}")
    print(f"Admin commands require role ID: {ADMIN_ROLE_ID}")
    joined = ", ".join(f"{guild.name} ({guild.id})" for guild in bot.guilds) or "なし"
    print(f"Joined guilds: {joined}")
    if not bot.panel_view_registered:
        bot.add_view(WhitelistPanelView())
        bot.panel_view_registered = True
    await sync_slash_commands()


async def handle_register(interaction, steam_id):
    steam_id = steam_id.strip()
    if not validate_steam_id(steam_id):
        await interaction.followup.send("無効なSteam IDです。17桁の有効なSteam IDを入力してください。", ephemeral=True)
        return

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        discord_id = interaction.user.id

        cursor.execute("SELECT * FROM blocked_users WHERE steamid = %s OR discord_id = %s", (steam_id, discord_id))
        blocked_user = cursor.fetchone()
        if blocked_user:
            blocked_identifier = "Steam ID" if blocked_user[0] == steam_id else "Discord ID"
            blocked_value = blocked_user[0] if blocked_user[0] == steam_id else blocked_user[1]
            await interaction.followup.send(
                f"{blocked_identifier} {blocked_value} はブロックされているため、登録できません。",
                ephemeral=True,
            )
            return

        cursor.execute("SELECT steamid FROM player_info WHERE discord_id = %s", (discord_id,))
        existing_steam_id = cursor.fetchone()
        if existing_steam_id:
            await interaction.followup.send(
                f"あなたのDiscordアカウントには既にSteam ID {existing_steam_id[0]} が登録されています。"
                "Steam IDの変更が必要な場合は、管理者に連絡してください。",
                ephemeral=True,
            )
            return

        try:
            player_info = get_player_info(steam_id)
        except SteamApiConfigurationError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            print(f"Steam API configuration error: {exc}")
            return
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            if status_code in (401, 403):
                message = (
                    "Steam APIキーが無効、または権限がありません。"
                    "管理者は .env の STEAM_API_KEY を確認して Bot を再起動してください。"
                )
            else:
                message = f"Steam API からエラーが返りました。時間を置いて再試行してください。status={status_code}"
            await interaction.followup.send(message, ephemeral=True)
            print(f"Steam API HTTP error: status={status_code}")
            return
        except requests.RequestException as exc:
            await interaction.followup.send(
                "Steam API への接続に失敗しました。時間を置いて再試行してください。",
                ephemeral=True,
            )
            print(f"Steam API request error: {type(exc).__name__}")
            return

        if not player_info:
            await interaction.followup.send(
                f"Steam ID {steam_id} の情報を取得できませんでした。有効なSteam IDであることを確認してください。",
                ephemeral=True,
            )
            return

        persona_name = player_info["personaname"]
        avatar = player_info["avatar"]

        cursor.execute("SELECT personaname FROM player_info WHERE steamid = %s", (steam_id,))
        existing_player = cursor.fetchone()
        if existing_player:
            cursor.execute(
                "UPDATE player_info SET personaname = %s, avatar = %s, discord_id = %s WHERE steamid = %s",
                (persona_name, avatar, discord_id, steam_id),
            )
        else:
            cursor.execute(
                "INSERT INTO player_info (steamid, personaname, avatar, discord_id) VALUES (%s, %s, %s, %s)",
                (steam_id, persona_name, avatar, discord_id),
            )

        cursor.execute("SELECT * FROM whitelist WHERE steamid = %s", (steam_id,))
        if cursor.fetchone():
            await interaction.followup.send(
                f"Steam ID {steam_id} は既にホワイトリストに登録されています。",
                ephemeral=True,
            )
            return

        cursor.execute("INSERT INTO whitelist (steamid) VALUES (%s)", (steam_id,))
        conn.commit()

        try:
            reload_rust_whitelist()
            rcon_message = "Rustサーバーへホワイトリスト再読み込みコマンドを送信しました。"
        except Exception as exc:
            rcon_message = "DBの更新は完了しましたが、Rustサーバーへのコマンド送信に失敗しました。管理者に連絡してください。"
            print(f"RCON error: {type(exc).__name__}")

        await interaction.followup.send(
            f"Steam ID {steam_id} (プレイヤー名: {persona_name}) をホワイトリストへ登録し、Discord アカウントとリンクしました。\n{rcon_message}",
            ephemeral=True,
        )

    except mysql.connector.Error as err:
        await interaction.followup.send(
            "データベースエラーが発生しました。管理者に連絡してください。",
            ephemeral=True,
        )
        print(f"Database error: {type(err).__name__}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


async def handle_unregister(interaction, steam_id):
    steam_id = steam_id.strip()
    if not validate_steam_id(steam_id):
        await interaction.followup.send("無効なSteam IDです。17桁の有効なSteam IDを入力してください。", ephemeral=True)
        return

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        discord_id = interaction.user.id
        cursor.execute("SELECT steamid FROM player_info WHERE discord_id = %s", (discord_id,))
        result = cursor.fetchone()
        if not result:
            await send_response(interaction, "あなたのDiscordアカウントに紐づけられたSteam IDが見つかりません。")
            return

        linked_steam_id = result[0]
        if linked_steam_id != steam_id:
            await interaction.followup.send(
                f"入力した Steam ID {steam_id} は、あなたに紐づく Steam ID {linked_steam_id} と一致しません。",
                ephemeral=True,
            )
            return

        cursor.execute("SELECT * FROM whitelist WHERE steamid = %s", (linked_steam_id,))
        if not cursor.fetchone():
            await interaction.followup.send(
                f"あなたのSteam ID {linked_steam_id} はホワイトリストに登録されていません。",
                ephemeral=True,
            )
            return

        cursor.execute("DELETE FROM whitelist WHERE steamid = %s", (linked_steam_id,))
        cursor.execute("DELETE FROM player_info WHERE steamid = %s", (linked_steam_id,))
        conn.commit()

        try:
            reload_rust_whitelist(kick_steam_id=linked_steam_id)
            rcon_message = "Rustサーバーへ再読み込み・キックコマンドを送信しました。"
        except Exception as exc:
            rcon_message = "DBの更新は完了しましたが、Rustサーバーへのコマンド送信に失敗しました。管理者に連絡してください。"
            print(f"RCON error: {type(exc).__name__}")

        await interaction.followup.send(
            f"あなたのSteam ID {linked_steam_id} をホワイトリストから削除しました。\n{rcon_message}",
            ephemeral=True,
        )

    except mysql.connector.Error as err:
        await interaction.followup.send(
            "データベースエラーが発生しました。管理者に連絡してください。",
            ephemeral=True,
        )
        print(f"Database error: {type(err).__name__}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


async def handle_check(interaction):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        discord_id = interaction.user.id
        cursor.execute("SELECT steamid, personaname FROM player_info WHERE discord_id = %s", (discord_id,))
        result = cursor.fetchone()
        if not result:
            await send_response(interaction, "あなたのDiscordアカウントに紐づけられたSteam IDが見つかりません。")
            return

        steam_id, persona_name = result

        cursor.execute("SELECT * FROM blocked_users WHERE discord_id = %s", (discord_id,))
        discord_blocked = cursor.fetchone() is not None

        cursor.execute("SELECT * FROM blocked_users WHERE steamid = %s", (steam_id,))
        steam_blocked = cursor.fetchone() is not None

        cursor.execute("SELECT * FROM whitelist WHERE steamid = %s", (steam_id,))
        whitelisted = cursor.fetchone() is not None

        status = (
            "ブロックされています"
            if discord_blocked or steam_blocked
            else "ホワイトリストに登録されています" if whitelisted else "ホワイトリストに登録されていません"
        )

        await send_response(
            interaction,
            f"あなたのSteam ID {steam_id} (プレイヤー名: {persona_name}) は {status}。",
        )

    except mysql.connector.Error as err:
        await send_response(
            interaction,
            "データベースエラーが発生しました。管理者に連絡してください。",
        )
        print(f"Database error: {type(err).__name__}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


async def handle_block(interaction, steam_id, discord_id_text):
    steam_id = steam_id.strip()
    discord_id_text = discord_id_text.strip()

    if not validate_steam_id(steam_id):
        await interaction.followup.send("無効なSteam IDです。17桁の有効なSteam IDを入力してください。", ephemeral=True)
        return

    discord_id = None
    if discord_id_text:
        if not discord_id_text.isdigit():
            await interaction.followup.send("Discord ID は数字で入力してください。", ephemeral=True)
            return
        discord_id = int(discord_id_text)

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM blocked_users WHERE steamid = %s", (steam_id,))
        if cursor.fetchone():
            await interaction.followup.send(f"Steam ID {steam_id} は既にブロックされています。", ephemeral=True)
            return

        if discord_id is not None:
            cursor.execute("SELECT * FROM blocked_users WHERE discord_id = %s", (discord_id,))
            if cursor.fetchone():
                await interaction.followup.send(f"Discord ID {discord_id} は既にブロックされています。", ephemeral=True)
                return

        cursor.execute("DELETE FROM whitelist WHERE steamid = %s", (steam_id,))
        cursor.execute("DELETE FROM player_info WHERE steamid = %s", (steam_id,))
        cursor.execute("INSERT INTO blocked_users (steamid, discord_id) VALUES (%s, %s)", (steam_id, discord_id))
        conn.commit()

        try:
            reload_rust_whitelist(kick_steam_id=steam_id)
            rcon_message = "Rustサーバーへ再読み込み・キックコマンドを送信しました。"
        except Exception as exc:
            rcon_message = "DBの更新は完了しましたが、Rustサーバーへのコマンド送信に失敗しました。管理者に連絡してください。"
            print(f"RCON error: {type(exc).__name__}")

        await interaction.followup.send(
            f"Steam ID {steam_id} をブロックしました。Discord ID: {discord_id if discord_id is not None else 'なし'}\n{rcon_message}",
            ephemeral=True,
        )

    except mysql.connector.Error as err:
        await interaction.followup.send(
            "データベースエラーが発生しました。管理者に連絡してください。",
            ephemeral=True,
        )
        print(f"Database error: {type(err).__name__}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


async def handle_unblock(interaction, steam_id):
    steam_id = steam_id.strip()
    if not validate_steam_id(steam_id):
        await interaction.followup.send("無効なSteam IDです。17桁の有効なSteam IDを入力してください。", ephemeral=True)
        return

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM blocked_users WHERE steamid = %s", (steam_id,))
        if not cursor.fetchone():
            await interaction.followup.send(f"Steam ID {steam_id} はブロックされていません。", ephemeral=True)
            return

        cursor.execute("DELETE FROM blocked_users WHERE steamid = %s", (steam_id,))
        conn.commit()

        try:
            reload_rust_whitelist()
            rcon_message = "Rustサーバーへホワイトリスト再読み込みコマンドを送信しました。"
        except Exception as exc:
            rcon_message = "DBの更新は完了しましたが、Rustサーバーへのコマンド送信に失敗しました。管理者に連絡してください。"
            print(f"RCON error: {type(exc).__name__}")

        await interaction.followup.send(
            f"Steam ID {steam_id} のブロックを解除しました。\n{rcon_message}",
            ephemeral=True,
        )

    except mysql.connector.Error as err:
        await interaction.followup.send(
            "データベースエラーが発生しました。管理者に連絡してください。",
            ephemeral=True,
        )
        print(f"Database error: {type(err).__name__}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


class RegisterModal(discord.ui.Modal, title="Steam ID を入力"):
    steam_id = discord.ui.TextInput(
        label="Steam ID",
        placeholder="17桁の Steam ID を入力",
        min_length=17,
        max_length=17,
    )

    async def on_submit(self, interaction):
        if not await ensure_allowed_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await handle_register(interaction, str(self.steam_id))


class UnregisterModal(discord.ui.Modal, title="解除する Steam ID を入力"):
    steam_id = discord.ui.TextInput(
        label="Steam ID",
        placeholder="登録時に使った 17桁の Steam ID を入力",
        min_length=17,
        max_length=17,
    )

    async def on_submit(self, interaction):
        if not await ensure_allowed_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await handle_unregister(interaction, str(self.steam_id))


class BlockModal(discord.ui.Modal, title="ブロック対象を入力"):
    steam_id = discord.ui.TextInput(
        label="Steam ID",
        placeholder="17桁の Steam ID を入力",
        min_length=17,
        max_length=17,
    )
    discord_id = discord.ui.TextInput(
        label="Discord ID",
        placeholder="必要な場合だけ入力",
        required=False,
        max_length=20,
    )

    async def on_submit(self, interaction):
        if not await ensure_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await handle_block(interaction, str(self.steam_id), str(self.discord_id))


class UnblockModal(discord.ui.Modal, title="ブロック解除する Steam ID を入力"):
    steam_id = discord.ui.TextInput(
        label="Steam ID",
        placeholder="17桁の Steam ID を入力",
        min_length=17,
        max_length=17,
    )

    async def on_submit(self, interaction):
        if not await ensure_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await handle_unblock(interaction, str(self.steam_id))


class WhitelistPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="登録",
        style=discord.ButtonStyle.success,
        custom_id="whitelist_panel_register",
    )
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_allowed_channel(interaction):
            return
        await interaction.response.send_modal(RegisterModal())

    @discord.ui.button(
        label="解除",
        style=discord.ButtonStyle.danger,
        custom_id="whitelist_panel_unregister",
    )
    async def unregister_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ensure_allowed_channel(interaction):
            return
        await interaction.response.send_modal(UnregisterModal())


@bot.tree.command(name="rustpanel", description="管理者用。参加者向けのホワイトリスト操作パネルを表示します。")
async def rustpanel_command(interaction: discord.Interaction):
    if not await ensure_admin(interaction):
        return
    await interaction.response.send_message(
        embed=build_panel_embed(),
        view=WhitelistPanelView(),
    )


@bot.tree.command(name="check", description="自分の Steam ID のホワイトリスト状態を確認します。")
async def check_command(interaction: discord.Interaction):
    if not await ensure_allowed_channel(interaction):
        return
    await handle_check(interaction)


@bot.tree.command(name="block", description="管理者用。Steam ID と任意の Discord ID を入力してブロックします。")
async def block_command(interaction: discord.Interaction):
    if not await ensure_admin(interaction):
        return
    await interaction.response.send_modal(BlockModal())


@bot.tree.command(name="unblock", description="管理者用。Steam ID を入力してブロック解除します。")
async def unblock_command(interaction: discord.Interaction):
    if not await ensure_admin(interaction):
        return
    await interaction.response.send_modal(UnblockModal())


@bot.tree.command(name="help", description="ホワイトリスト管理コマンドの使用方法を表示します。")
async def help_command(interaction: discord.Interaction):
    if not await ensure_allowed_channel(interaction):
        return
    await send_response(interaction, embed=build_help_embed())

def validate_configuration():
    required = {
        "DISCORD_TOKEN": TOKEN,
        "MYSQL_HOST": MYSQL_HOST,
        "MYSQL_USER": MYSQL_USER,
        "MYSQL_PASSWORD": MYSQL_PASSWORD,
        "MYSQL_DATABASE": MYSQL_DATABASE,
        "STEAM_API_KEY": STEAM_API_KEY,
        "RCON_HOST": RCON_HOST,
        "RCON_PASSWORD": RCON_PASSWORD,
    }
    missing = [key for key, value in required.items()
               if not value or value.lower().startswith("change-this-")]
    missing.extend(key for key, value in {
        "TARGET_GUILD_ID": TARGET_GUILD_ID,
        "ALLOWED_CHANNEL_ID": ALLOWED_CHANNEL_ID,
        "ADMIN_ROLE_ID": ADMIN_ROLE_ID,
    }.items() if value <= 0)
    if missing:
        raise RuntimeError(".env の設定が必要です: " + ", ".join(missing))
    if not 1 <= MYSQL_PORT <= 65535 or not 1 <= int(RCON_PORT) <= 65535:
        raise RuntimeError("MYSQL_PORT / RCON_PORT は 1〜65535 で指定してください。")
    if not 0 < STEAM_REQUEST_TIMEOUT_SECONDS <= 120:
        raise RuntimeError("STEAM_REQUEST_TIMEOUT_SECONDS は 0 より大きく 120 以下で指定してください。")


if __name__ == "__main__":
    validate_configuration()
    bot.run(TOKEN)
