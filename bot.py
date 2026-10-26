import asyncio
import logging
import math
import os
import random
import time

import discord
from discord import app_commands
from discord.ext import tasks

import card
import db

log = logging.getLogger("levels")

CHAT_XP = (15, 25)
CHAT_COOLDOWN = 60
BLURPLE = discord.Color.blurple()
PAGE = 10
ANNOUNCE_LABELS = {"current": "레벨업한 채널", "channel": "지정 채널", "dm": "DM", "off": "끄기"}

last_chat: dict[tuple[int, int], float] = {}


class LevelBot(discord.AutoShardedClient):
    def __init__(self):
        super().__init__(intents=discord.Intents.default(), allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.add_command(settings_group)
        self.tree.add_command(admin_group)
        self.tree.on_error = on_command_error
        await self.tree.sync()
        voice_tick.start()

    async def on_ready(self):
        log.info("%s 로그인, 서버 %d개", self.user, len(self.guilds))


client = LevelBot()
tree = client.tree


def blocked_ids(guild_id):
    return {target for target, _ in db.no_xp(guild_id)}


def is_blocked(member, channel, blocked):
    scopes = {channel.id, getattr(channel, "parent_id", None), getattr(channel, "category_id", None)}
    parent = getattr(channel, "parent", None)
    if parent is not None:
        scopes.add(getattr(parent, "category_id", None))
    return bool(blocked & (scopes | {r.id for r in member.roles}))


def role_diff(rewards, level, stack, have):
    earned = [role for lv, role in rewards if lv <= level]
    want = set(earned if stack else earned[-1:])
    every = {role for _, role in rewards}
    return want - have, (every - want) & have


async def sync_roles(member, level, stack):
    rewards = db.level_roles(member.guild.id)
    if not rewards:
        return
    add, remove = role_diff(rewards, level, stack, {r.id for r in member.roles})
    add = [r for r in map(member.guild.get_role, add) if r]
    remove = [r for r in map(member.guild.get_role, remove) if r]
    try:
        if add:
            await member.add_roles(*add, reason=f"레벨 {level} 달성 보상")
        if remove:
            await member.remove_roles(*remove, reason=f"레벨 {level} 보상 역할 교체")
    except discord.HTTPException as e:
        log.warning("역할 지급 실패 guild=%s member=%s: %s", member.guild.id, member.id, e)


def render_message(template, member, level, points):
    for key, value in {"{user}": member.mention, "{name}": member.display_name, "{level}": str(level),
                       "{points}": f"{points:,}", "{server}": member.guild.name}.items():
        template = template.replace(key, value)
    return template


async def announce(member, level, reward, settings, origin):
    mode = settings["announce"]
    if mode == "off":
        return
    text = render_message(settings["message"], member, level, reward)
    try:
        if mode == "dm":
            await member.send(text)
            return
        target = member.guild.get_channel(settings["announce_channel"]) if mode == "channel" else origin
        if target is not None:
            await target.send(text, allowed_mentions=discord.AllowedMentions(users=[member]))
    except discord.HTTPException as e:
        log.warning("레벨업 알림 실패 guild=%s member=%s: %s", member.guild.id, member.id, e)


async def grant(member, amount, settings, origin, always_sync):
    old, new, reward = db.add_xp(member.guild.id, member.id, amount, settings["level_points"])
    if always_sync or new != old:
        await sync_roles(member, new, settings["stack_roles"])
    if new > old:
        await announce(member, new, reward, settings, origin)


@client.event
async def on_message(message):
    member = message.author
    if member.bot or message.webhook_id or not isinstance(member, discord.Member):
        return
    key = (message.guild.id, member.id)
    now = time.monotonic()
    if now - last_chat.get(key, -math.inf) < CHAT_COOLDOWN:
        return
    if is_blocked(member, message.channel, blocked_ids(message.guild.id)):
        return
    settings = db.get_settings(message.guild.id)
    amount = round(random.randint(*CHAT_XP) * settings["xp_rate"])
    if amount <= 0:
        return
    last_chat[key] = now
    await grant(member, amount, settings, message.channel, always_sync=True)


@tasks.loop(minutes=1)
async def voice_tick():
    cutoff = time.monotonic() - CHAT_COOLDOWN
    for key in [k for k, t in last_chat.items() if t < cutoff]:
        del last_chat[key]
    for guild in client.guilds:
        try:
            await voice_guild(guild)
        except Exception:
            log.exception("통화 경험치 처리 실패 guild=%s", guild.id)


async def voice_guild(guild):
    settings = db.get_settings(guild.id)
    amount = round(settings["voice_xp"] * settings["xp_rate"])
    if amount <= 0:
        return
    blocked = blocked_ids(guild.id)
    for channel in [*guild.voice_channels, *guild.stage_channels]:
        if channel == guild.afk_channel:
            continue
        listeners = [m for m in channel.members
                     if not m.bot and m.voice and not (m.voice.self_deaf or m.voice.deaf)]
        if len(listeners) < 2:
            continue
        for member in listeners:
            if not is_blocked(member, channel, blocked):
                await grant(member, amount, settings, channel, always_sync=False)


@voice_tick.before_loop
async def before_voice_tick():
    await client.wait_until_ready()


def accent_of(member):
    return member.color.to_rgb() if member.color.value else BLURPLE.to_rgb()


@tree.command(name="랭크", description="레벨 카드를 봅니다")
@app_commands.guild_only()
@app_commands.describe(멤버="확인할 멤버 (비워 두면 본인)")
async def rank_cmd(interaction: discord.Interaction, 멤버: discord.Member | None = None):
    member = 멤버 or interaction.user
    if member.bot:
        return await interaction.response.send_message("봇은 레벨이 없습니다.", ephemeral=True)
    await interaction.response.defer()
    xp, points = db.get_user(interaction.guild_id, member.id)
    level, current, need = db.level_progress(xp)
    try:
        avatar = await member.display_avatar.replace(size=256, format="png").read()
    except discord.HTTPException:
        avatar = None
    image = await asyncio.to_thread(card.render, member.display_name, member.name, avatar,
                                    db.rank(interaction.guild_id, member.id), level, current, need, points,
                                    accent_of(member))
    await interaction.followup.send(file=discord.File(image, "rank.png"))


class Board(discord.ui.View):
    def __init__(self, guild, column):
        super().__init__(timeout=180)
        self.guild, self.column, self.page = guild, column, 0
        self.message = None

    def embed(self):
        pages = max(1, math.ceil(db.member_count(self.guild.id) / PAGE))
        self.page = min(self.page, pages - 1)
        rows = db.leaderboard(self.guild.id, self.column, self.page * PAGE, PAGE)
        lines = []
        for i, (user, xp, points) in enumerate(rows, self.page * PAGE + 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"`{i:>2}`")
            stat = f"포인트 **{points:,}**" if self.column == "points" else f"레벨 **{db.level_of(xp)}** · {xp:,} XP"
            lines.append(f"{medal} <@{user}> · {stat}")
        title = "포인트 순위" if self.column == "points" else "레벨 순위"
        embed = discord.Embed(title=f"{self.guild.name} {title}", color=BLURPLE,
                              description="\n".join(lines) or "아직 기록이 없습니다.")
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"{self.page + 1} / {pages}")
        self.prev.disabled = self.page == 0
        self.next.disabled = self.page >= pages - 1
        return embed

    async def turn(self, interaction, step):
        self.page += step
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, _):
        await self.turn(interaction, -1)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, _):
        await self.turn(interaction, 1)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


@tree.command(name="순위", description="서버 순위표를 봅니다")
@app_commands.guild_only()
@app_commands.choices(기준=[app_commands.Choice(name="레벨", value="xp"),
                          app_commands.Choice(name="포인트", value="points")])
async def board_cmd(interaction: discord.Interaction, 기준: str = "xp"):
    view = Board(interaction.guild, 기준)
    await interaction.response.send_message(embed=view.embed(), view=view)
    view.message = await interaction.original_response()


@tree.command(name="포인트", description="포인트를 확인합니다")
@app_commands.guild_only()
async def points_cmd(interaction: discord.Interaction, 멤버: discord.Member | None = None):
    member = 멤버 or interaction.user
    points = db.get_user(interaction.guild_id, member.id)[1]
    await interaction.response.send_message(f"{member.display_name} 님의 보유 포인트는 {points:,}입니다.")


@tree.command(name="송금", description="다른 멤버에게 포인트를 보냅니다")
@app_commands.guild_only()
async def send_cmd(interaction: discord.Interaction, 멤버: discord.Member, 금액: app_commands.Range[int, 1]):
    if 멤버.bot:
        return await interaction.response.send_message("봇에게는 송금할 수 없습니다.", ephemeral=True)
    if 멤버.id == interaction.user.id:
        return await interaction.response.send_message("자신에게는 송금할 수 없습니다.", ephemeral=True)
    if not db.transfer(interaction.guild_id, interaction.user.id, 멤버.id, 금액):
        balance = db.get_user(interaction.guild_id, interaction.user.id)[1]
        return await interaction.response.send_message(f"포인트가 부족합니다. (보유: {balance:,})", ephemeral=True)
    await interaction.response.send_message(f"{interaction.user.mention} 님이 {멤버.mention} 님에게 {금액:,} 포인트를 송금했습니다.",
                                            allowed_mentions=discord.AllowedMentions(users=[멤버]))


manage = discord.Permissions(manage_guild=True)
settings_group = app_commands.Group(name="설정", description="레벨 시스템 설정", guild_only=True,
                                    default_permissions=manage)
admin_group = app_commands.Group(name="관리", description="경험치·포인트 관리", guild_only=True,
                                 default_permissions=manage)


@settings_group.command(name="보기", description="현재 설정을 봅니다")
async def show_settings(interaction: discord.Interaction):
    gid = interaction.guild_id
    s = db.get_settings(gid)
    announce_to = {"current": "레벨업한 채널", "channel": f"<#{s['announce_channel']}>", "dm": "DM",
                   "off": "꺼짐"}[s["announce"]]
    embed = discord.Embed(title="레벨 설정", color=BLURPLE)
    embed.add_field(name="레벨업 알림", value=announce_to)
    embed.add_field(name="경험치 배율", value=f"{s['xp_rate']:g}배")
    embed.add_field(name="통화 경험치", value=f"분당 {s['voice_xp']}")
    embed.add_field(name="레벨당 포인트", value=f"{s['level_points']:,} × 레벨")
    embed.add_field(name="보상 역할", value="누적" if s["stack_roles"] else "최고 레벨만")
    embed.add_field(name="알림 메시지", value=s["message"][:1024], inline=False)
    roles = "\n".join(f"레벨 {lv} · <@&{role}>" for lv, role in db.level_roles(gid))
    embed.add_field(name="레벨 보상 역할", value=roles or "없음", inline=False)
    blocked = " ".join(f"<#{t}>" if kind == "channel" else f"<@&{t}>" for t, kind in db.no_xp(gid))
    embed.add_field(name="경험치 제외", value=blocked[:1024] or "없음", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@settings_group.command(name="알림", description="레벨업 알림 방식과 문구 설정")
@app_commands.describe(메시지="{user} 멘션, {name} 이름, {level} 레벨, {points} 지급 포인트, {server} 서버 이름")
@app_commands.choices(방식=[app_commands.Choice(name=label, value=key) for key, label in ANNOUNCE_LABELS.items()])
async def set_announce(interaction: discord.Interaction, 방식: str, 채널: discord.TextChannel | None = None,
                       메시지: app_commands.Range[str, 1, 1500] | None = None):
    if 방식 == "channel" and 채널 is None:
        return await interaction.response.send_message("알림을 보낼 채널도 지정해 주세요.", ephemeral=True)
    fields = {"announce": 방식}
    if 채널:
        fields["announce_channel"] = 채널.id
    if 메시지:
        fields["message"] = 메시지
    db.update_settings(interaction.guild_id, **fields)
    done = {"current": "레벨이 오르면 레벨업한 채널에 알림을 보냅니다.",
            "channel": f"레벨이 오르면 {채널 and 채널.mention}에 알림을 보냅니다.",
            "dm": "레벨이 오르면 DM으로 알림을 보냅니다.", "off": "레벨업 알림을 껐습니다."}
    await interaction.response.send_message(done[방식], ephemeral=True)


@settings_group.command(name="수치", description="경험치·포인트 수치 설정")
@app_commands.rename(xp_rate="경험치배율", voice_xp="통화경험치", level_points="레벨당포인트", stack_roles="역할누적")
@app_commands.describe(xp_rate="채팅·통화 경험치 배율", voice_xp="통화 1분당 경험치",
                       level_points="레벨 N 달성 시 N × 이 값만큼 포인트 지급", stack_roles="끄면 최고 레벨 보상 역할만 유지")
async def set_numbers(interaction: discord.Interaction, xp_rate: app_commands.Range[float, 0] | None = None,
                      voice_xp: app_commands.Range[int, 0] | None = None,
                      level_points: app_commands.Range[int, 0] | None = None, stack_roles: bool | None = None):
    fields = {k: v for k, v in {"xp_rate": xp_rate, "voice_xp": voice_xp, "level_points": level_points,
                                "stack_roles": stack_roles}.items() if v is not None}
    if not fields:
        return await interaction.response.send_message("바꿀 값을 하나 이상 입력해 주세요.", ephemeral=True)
    db.update_settings(interaction.guild_id, **fields)
    await interaction.response.send_message("저장했습니다.", ephemeral=True)


@settings_group.command(name="보상역할", description="레벨 보상 역할 지정 (역할을 비워 두면 제거)")
async def set_level_role(interaction: discord.Interaction, 레벨: app_commands.Range[int, 1],
                         역할: discord.Role | None = None):
    if 역할 is not None:
        if 역할.is_default() or 역할.managed:
            return await interaction.response.send_message("@everyone이나 다른 봇이 관리하는 역할은 지급할 수 없습니다.", ephemeral=True)
        if 역할 >= interaction.guild.me.top_role:
            bot_role = interaction.guild.self_role or interaction.guild.me.top_role
            return await interaction.response.send_message(
                f"{역할.mention} 역할을 줄 권한이 없어요. 서버 설정에서 {bot_role.mention} 역할을 {역할.mention}보다 위로 옮겨 주세요.", ephemeral=True)
    db.set_level_role(interaction.guild_id, 레벨, 역할 and 역할.id)
    text = f"레벨 {레벨}에 도달하면 {역할.mention} 역할을 지급합니다." if 역할 else f"레벨 {레벨} 역할을 제거했습니다."
    await interaction.response.send_message(text, ephemeral=True)


@settings_group.command(name="경험치제외", description="경험치를 지급하지 않을 채널·카테고리·역할 (다시 지정하면 해제)")
async def toggle_no_xp(interaction: discord.Interaction, 채널: discord.abc.GuildChannel | None = None,
                       역할: discord.Role | None = None):
    targets = [(t, kind) for t, kind in ((채널, "channel"), (역할, "role")) if t is not None]
    if not targets:
        return await interaction.response.send_message("채널이나 역할을 하나 이상 지정해 주세요.", ephemeral=True)
    lines = []
    for t, kind in targets:
        where = f"{t.mention}에서" if kind == "channel" else f"{t.mention} 역할에"
        blocked = db.toggle_no_xp(interaction.guild_id, t.id, kind)
        lines.append(f"이제부터 {where} {'경험치가 지급되지 않습니다.' if blocked else '경험치를 지급합니다.'}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


MODES = [app_commands.Choice(name="지급", value="add"), app_commands.Choice(name="차감", value="sub"),
         app_commands.Choice(name="설정", value="set")]


def delta(mode, amount, current):
    return {"add": amount, "sub": -amount, "set": amount - current}[mode]


@admin_group.command(name="경험치", description="멤버 경험치 변경 (레벨이 올라도 포인트는 지급되지 않음)")
@app_commands.choices(방식=MODES)
async def admin_xp(interaction: discord.Interaction, 멤버: discord.Member, 방식: str,
                   양: app_commands.Range[int, 0]):
    if 멤버.bot:
        return await interaction.response.send_message("봇의 경험치는 바꿀 수 없습니다.", ephemeral=True)
    current = db.get_user(interaction.guild_id, 멤버.id)[0]
    _, level, _ = db.add_xp(interaction.guild_id, 멤버.id, delta(방식, 양, current), 0)
    await interaction.response.defer(ephemeral=True)
    await sync_roles(멤버, level, db.get_settings(interaction.guild_id)["stack_roles"])
    xp = db.get_user(interaction.guild_id, 멤버.id)[0]
    await interaction.followup.send(f"{멤버.mention} 님의 경험치를 변경했습니다. (현재: {xp:,}, 레벨 {level})", ephemeral=True)


@admin_group.command(name="포인트", description="멤버 포인트 변경")
@app_commands.choices(방식=MODES)
async def admin_points(interaction: discord.Interaction, 멤버: discord.Member, 방식: str,
                       양: app_commands.Range[int, 0]):
    if 멤버.bot:
        return await interaction.response.send_message("봇의 포인트는 바꿀 수 없습니다.", ephemeral=True)
    current = db.get_user(interaction.guild_id, 멤버.id)[1]
    points = db.add_points(interaction.guild_id, 멤버.id, delta(방식, 양, current))
    await interaction.response.send_message(f"{멤버.mention} 님의 포인트를 변경했습니다. (현재: {points:,})", ephemeral=True)


class ConfirmReset(discord.ui.View):
    def __init__(self, owner):
        super().__init__(timeout=60)
        self.owner = owner

    async def interaction_check(self, interaction):
        return interaction.user.id == self.owner

    @discord.ui.button(label="전체 초기화", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, _):
        db.reset(interaction.guild_id)
        self.stop()
        await interaction.response.edit_message(content="서버 전체 경험치와 포인트를 초기화했습니다.", view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, _):
        self.stop()
        await interaction.response.edit_message(content="취소했습니다.", view=None)


@admin_group.command(name="초기화", description="경험치·포인트 초기화 (멤버를 비워 두면 서버 전체)")
async def admin_reset(interaction: discord.Interaction, 멤버: discord.Member | None = None):
    if 멤버 is None:
        return await interaction.response.send_message("서버 전체 경험치와 포인트를 초기화할까요?",
                                                       view=ConfirmReset(interaction.user.id), ephemeral=True)
    db.reset(interaction.guild_id, 멤버.id)
    await interaction.response.defer(ephemeral=True)
    await sync_roles(멤버, 0, True)
    await interaction.followup.send(f"{멤버.mention} 님의 경험치와 포인트를 초기화했습니다.", ephemeral=True)


async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
        text = "이 명령어를 사용할 권한이 없습니다."
    else:
        log.exception("명령 처리 실패 /%s", interaction.command and interaction.command.qualified_name,
                      exc_info=error)
        text = "명령어를 처리하는 중 오류가 발생했습니다."
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    try:
        await send(text, ephemeral=True)
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    db.open_db(os.getenv("DB_PATH", "points.db"))
    client.run(os.environ["DISCORD_TOKEN"], root_logger=True)
