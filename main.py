import os
import time
import hashlib
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# 起動ごとに変わるユニークなソルト（再起動トリガー用）
BOOT_SALT = str(int(time.time()))

# アイコン用絵文字プール
AVATAR_EMOJIS = [
    "🤖", "👾", "👻", "🦊", "🐼", "🐨", "🐸", "🦉",
    "🦄", "🐙", "🦖", "🦁", "🐧", "🐱", "🐶", "🐻",
    "🍕", "🍩", "🍣", "🚀", "🪐", "🔥", "💎", "⭐",
    "🎩", "🎭", "🎃", "🌵", "🥑", "🧁"
]

# 12時間周期 ＋ Bot再起動時に自動ローテーションする識別情報生成
def get_anon_identity(user_id: int, room_name: str) -> tuple[str, str]:
    # 12時間（43200秒）ごとに加算されるウィンドウ値
    time_window = int(time.time() // 43200)

    # ユーザーID・部屋名・12時間枠・起動ソルトを混合
    seed = f"{user_id}:{room_name}:{time_window}:{BOOT_SALT}"
    hash_obj = hashlib.sha256(seed.encode())
    hash_int = int(hash_obj.hexdigest(), 16)

    emoji = AVATAR_EMOJIS[hash_int % len(AVATAR_EMOJIS)]
    short_id = hash_obj.hexdigest()[:4].upper()
    anon_name = f"匿名#{short_id}"
    return emoji, anon_name

# 退出ボタン付きView（個室用）
class LeaveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="この部屋を退出する", style=discord.ButtonStyle.danger, emoji="🚪", custom_id="anon_leave_btn")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = interaction.channel
        if isinstance(ch, discord.TextChannel) and ch.topic and ch.topic.startswith("anon_isolated:"):
            await interaction.response.send_message("退出しています...", ephemeral=True)
            await handle_leave(ch, interaction.user.name)
        else:
            await interaction.response.send_message("ここは匿名個室ではありません。", ephemeral=True)

# 募集メッセージ用の参加ボタンView
class JoinView(discord.ui.View):
    def __init__(self, room_name: str = ""):
        super().__init__(timeout=None)
        if room_name:
            self.add_item(
                discord.ui.Button(
                    label="匿名部屋に参加する",
                    style=discord.ButtonStyle.success,
                    emoji="🚪",
                    custom_id=f"anon_join:{room_name}"
                )
            )

# 個人部屋作成
async def create_user_room(guild: discord.Guild, member: discord.Member, room_name: str, base_channel: discord.TextChannel):
    emoji, anon_name = get_anon_identity(member.id, room_name)
    current_window = int(time.time() // 43200)
    # トピック末尾に「ウィンドウ番号:起動ソルト」を保持
    topic = f"anon_isolated:{room_name}:{member.id}:{current_window}:{BOOT_SALT}"

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }

    private_ch = await guild.create_text_channel(
        name=room_name,
        overwrites=overwrites,
        category=base_channel.category,
        topic=topic
    )

    try:
        await private_ch.edit(position=base_channel.position + 1)
    except Exception:
        pass

    await private_ch.send(
        f"🔒 **「{room_name}」へようこそ**\n"
        f"現在のアバター: {emoji} **{anon_name}**（※12時間ごと/再起動時に自動シャッフル）\n\n"
        f"・メンバーリストにはあなたとBotしか表示されません。\n"
        f"・送信したメッセージ・画像は参加者全員の部屋へサイレント転送されます。\n"
        f"・抜けるときは下のボタン、または `/leave` で退出できます（全員退出で部屋は消滅します）。",
        view=LeaveView()
    )
    return private_ch

# 退出処理
async def handle_leave(ch: discord.TextChannel, user_name: str):
    if not (isinstance(ch, discord.TextChannel) and ch.topic and ch.topic.startswith("anon_isolated:")):
        return

    parts = ch.topic.split(":")
    room_name = parts[1]
    guild = ch.guild

    try:
        await ch.delete(reason=f"{user_name} が退出")
    except Exception as e:
        print(f"削除エラー: {e}")
        return

    remaining = sum(
        1 for c in guild.text_channels
        if c.topic and c.topic.startswith(f"anon_isolated:{room_name}:")
    )

    if remaining == 0:
        print(f"「{room_name}」の参加者が0人になったため、部屋は完全に自然消滅しました。")
    else:
        print(f"「{room_name}」の残存メンバー数: {remaining}")

class AnonBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(LeaveView())
        await self.tree.sync()
        print("スラッシュコマンド同期完了")

bot = AnonBot()

# ボタンクリック検知
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get("custom_id", "")
        if custom_id.startswith("anon_join:"):
            room_name = custom_id.split(":", 1)[1]
            guild = interaction.guild
            member = interaction.user
            current_ch = interaction.channel

            user_prefix = f"anon_isolated:{room_name}:{member.id}:"
            for ch in guild.text_channels:
                if ch.topic and ch.topic.startswith(user_prefix):
                    await interaction.response.send_message(f"すでにあなたの部屋（{ch.mention}）があります！", ephemeral=True)
                    return

            await interaction.response.defer(ephemeral=True)
            private_ch = await create_user_room(guild, member, room_name, current_ch)
            await interaction.followup.send(f"参加しました！あなた専用の部屋はこちら: {private_ch.mention}", ephemeral=True)
            return

@bot.event
async def on_ready():
    print(f"=== Botログイン完了 (Boot Salt: {BOOT_SALT}): {bot.user} ===")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ このコマンドは**サーバー管理者のみ**実行できます。"
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)

# 1. /create（管理者専用）
@bot.tree.command(name="create", description="【管理者専用】新しい匿名部屋を作成し、参加ボタンを設置します")
@app_commands.describe(room_name="部屋の名前（例: 雑談）")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def create(interaction: discord.Interaction, room_name: str):
    guild = interaction.guild
    member = interaction.user
    current_ch = interaction.channel

    user_prefix = f"anon_isolated:{room_name}:{member.id}:"
    for ch in guild.text_channels:
        if ch.topic and ch.topic.startswith(user_prefix):
            await interaction.response.send_message(f"すでに「{room_name}」用のあなたの部屋（{ch.mention}）が存在します！", ephemeral=True)
            return

    await interaction.response.defer(ephemeral=True)

    await current_ch.send(
        f"🎉 **完全匿名部屋「{room_name}」がオープンしました！**\n"
        f"下のボタンを押すだけで、あなた専用の個室が生成されます。\n"
        f"※他人の視線やタイピング表示は一切ありません。アイコン・IDは12時間ごと/再起動時に自動シャッフルされます。",
        view=JoinView(room_name=room_name)
    )

    private_ch = await create_user_room(guild, member, room_name, current_ch)
    await interaction.followup.send(f"「{room_name}」の受付を開始しました！\nあなた専用の部屋はこちら: {private_ch.mention}")

# 2. /leave（手動退出）
@bot.tree.command(name="leave", description="現在の匿名部屋から退出（チャンネル削除）します")
async def leave(interaction: discord.Interaction):
    ch = interaction.channel
    if isinstance(ch, discord.TextChannel) and ch.topic and ch.topic.startswith("anon_isolated:"):
        await interaction.response.send_message("退出しています...", ephemeral=True)
        await handle_leave(ch, interaction.user.name)
    else:
        await interaction.response.send_message("ここは匿名個人部屋ではありません。", ephemeral=True)

# 3. チャット同期配信（再起動/時間経過のアバター変更検知 ＆ 画像転送対応）
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if not isinstance(message.channel, discord.TextChannel):
        return

    if message.channel.topic and message.channel.topic.startswith("anon_isolated:"):
        parts = message.channel.topic.split(":")
        room_name = parts[1]
        sender_id = message.author.id

        if not message.content and not message.attachments:
            return

        current_window = int(time.time() // 43200)
        
        # トピックから前回のウィンドウ値とソルトを抽出
        last_window = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else current_window
        last_salt = parts[4] if len(parts) >= 5 else BOOT_SALT

        # 12時間経過、またはBot再起動（ソルト変化）があった場合
        if current_window != last_window or last_salt != BOOT_SALT:
            new_emoji, new_anon_name = get_anon_identity(sender_id, room_name)
            await message.channel.send(
                f"🔄 **アバターが新しく更新されました！**\n"
                f"新しいアバター: {new_emoji} **{new_anon_name}**",
                silent=True
            )
            # トピックを最新状態に上書き
            try:
                await message.channel.edit(topic=f"anon_isolated:{room_name}:{sender_id}:{current_window}:{BOOT_SALT}")
            except Exception as e:
                print(f"トピック更新エラー: {e}")

        # 送信メッセージの整形
        emoji, anon_name = get_anon_identity(sender_id, room_name)
        if message.content:
            broadcast_content = f"{emoji} **[{anon_name}]**: {message.content}"
        else:
            broadcast_content = f"{emoji} **[{anon_name}]**:"

        files_to_send = []
        for att in message.attachments:
            try:
                files_to_send.append(await att.to_file())
            except Exception as e:
                print(f"ファイル取得エラー: {e}")

        try:
            await message.delete()
        except Exception:
            pass

        target_prefix = f"anon_isolated:{room_name}:"
        for ch in message.guild.text_channels:
            if ch.topic and ch.topic.startswith(target_prefix):
                if files_to_send:
                    ready_files = []
                    for f in files_to_send:
                        f.fp.seek(0)
                        ready_files.append(discord.File(fp=f.fp, filename=f.filename, spoiler=f.spoiler))
                    await ch.send(broadcast_content, files=ready_files, silent=True)
                else:
                    await ch.send(broadcast_content, silent=True)

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)