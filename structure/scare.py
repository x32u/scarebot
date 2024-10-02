import asyncio
import json
import math
import os
import random
import re
from copy import copy

import humanize
import parsedatetime as pdt
from bs4 import BeautifulSoup
from discord import (
    Activity,
    ActivityType,
    AllowedMentions,
    CustomActivity,
    Embed,
    File,
    Guild,
    Intents,
    Interaction,
    Member,
    Message,
    Permissions,
    Status,
    User,
)
from discord.app_commands.errors import CommandInvokeError
from discord.ext import tasks
from discord.ext.commands import (
    AutoShardedBot,
    BadArgument,
    BadLiteralArgument,
    CheckFailure,
    CommandError,
    CommandNotFound,
    CommandOnCooldown,
    MissingPermissions,
    MissingRequiredArgument,
    MissingRequiredAttachment,
    MissingRequiredFlag,
    NotOwner,
    UserInputError,
    when_mentioned_or,
)

from structure.config import API, SCARE, ShardStatus
from structure.managers import (
    Cache,
    ClientSession,
    Context,
    Help,
    Workers,
    database,
    getLogger,
    ratelimiter,
)
from structure.patcher import cmds, guild, interaction, member
from structure.utilities import Afk, ApplicationInfo, ApplicationLegal
from structure.utilities import Embed as ScriptedEmbed
from structure.utilities import (
    Error,
    Giveaway,
    Proxy,
    TicketClose,
    TicketView,
    VoiceMasterView,
)

logger = getLogger(__name__)

from collections import defaultdict
from contextlib import suppress
from datetime import datetime
from datetime import timezone as date_timezone
from io import BytesIO
from os import environ
from pathlib import Path
from typing import List, Optional, Union

from aiohttp.client_exceptions import ClientConnectorError, ClientResponseError
from discord.utils import format_dt, oauth_url, utcnow
from nudenet import NudeDetector
from pomice import Node
from pyppeteer import launch
from pytz import timezone

environ["JISHAKU_HIDE"] = "True"
environ["JISHAKU_RETAIN"] = "True"
environ["JISHAKU_NO_UNDERSCORE"] = "True"
environ["JISHAKU_SHELL_NO_DM_TRACEBACK"] = "True"
environ["JISHAKU_NO_DM_TRACEBACK"] = "True"


class Scare(AutoShardedBot):
    def __init__(
        self: "Scare",
        instance_owner_id: int = 1,
        color: Optional[int] = None,
        node: Optional[Node] = None,
        instance: bool = False,
        dbname: str = "scare",
        status: Status = Status.online,
        activity: Optional[CustomActivity] = None,
    ):
        super().__init__(
            mobile_status=True,
            help_command=Help(),
            command_prefix=bot_prefix,
            intents=Intents.all(),
            case_insensitive=True,
            strip_after_prefix=True,
            owner_ids=SCARE.owners,
            allowed_mentions=AllowedMentions(
                replied_user=False,
                everyone=False,
                roles=False,
                users=True,
            ),
            status=status,
            activity=activity,
        )
        self.uptime: datetime = utcnow()
        self.browser = None
        self.dbname = dbname
        self.isinstance = instance
        self.logger = logger
        self.node: Node = node
        self.instance_owner_id = instance_owner_id
        self.color = color or 2829617
        self.cache = Cache()
        self.proxy = SCARE.proxy
        self.weather = API.weather
        self.captcha = SCARE.captcha
        self.workers = Workers(SCARE.workers, self.captcha)
        self.embed = ScriptedEmbed()
        self.shard_status = ShardStatus()
        self.luma_headers = {"Authorization": API.luma}
        self.started_at = datetime.now()
        self.sslock = defaultdict(asyncio.Lock)
        self.shard_connected = {}
        self.toggled = False
        self.afk = {}
        self.reminder_tasks = {}
        self.giveaways = {}
        self.prefixes = {}
        self.bots = {}
        self.blacktea_matches = {}
        self.blackjack_matches = []
        self.invite_regex = r"(https?://)?(www.|canary.|ptb.)?(discord.gg|discordapp.com/invite|discord.com/invite)/?[a-zA-Z0-9]+/?"

    async def close(self):
        #await self.browser.close()
        #await self.session.close()

        #for file in os.listdir("./screenshots"):
        #    os.remove(f"./screenshots/{file}")

        return await super().close()

    def run(self):
        return super().run(SCARE.token, log_handler=None, reconnect=True)

    async def setup_hook(self: "Scare"):
        self.session = ClientSession()
        self.db = await database.connect(self.dbname)
        self.add_check(self.check_command)

        blacklisted = await self.db.fetch("SELECT target_id FROM blacklist")
        self.blacklisted = list(map(lambda r: r["target_id"], blacklisted))
        self.tree.interaction_check = self.check_blacklisted

        afk = await self.db.fetch("SELECT * FROM afk")
        for a in afk:
            model = Afk(**a)
            self.afk[str(model)] = model

        await self.load_extension("jishaku")

        for cog in Path("features").glob("**/*.py"):
            if not (self.isinstance and cog.stem == "web"):
                *tree, _ = cog.parts
                module = ".".join(tree)
                await self.load_extension(f"{module}.{cog.stem}")

        self.add_view(VoiceMasterView())
        self.add_view(TicketClose())
        self.add_view(TicketView())
        self.add_view(Giveaway())

    async def bump_cycle(self, guild_id: int):
        if result := await self.db.fetchrow(
            "SELECT * FROM bumpreminder WHERE guild_id = $1", guild_id
        ):
            time = (result.bump_next - utcnow()).total_seconds()
            await asyncio.sleep(time)

            if guild := self.get_guild(guild_id):
                member = guild.get_member(result.bumper_id) or guild.owner
                code = await self.embed.convert(member, result.remind)
                code.pop("delete_after", None)

                if channel := guild.get_channel(result.channel_id):
                    await channel.send(**code)

    def replace_hex_chars(self, text: str):
        def hex_to_char(match):
            hex_value = match.group(0)
            return bytes.fromhex(hex_value[2:]).decode("utf-8")

        return re.sub(r"\\x[0-9a-fA-F]{2}", hex_to_char, text)

    def get_proxy(self) -> Proxy:
        args = self.flatten([p.split(":") for p in self.proxy[7:].split("@")])

        values = ["username", "password", "host", "port"]
        return Proxy(**dict(zip(values, args)))

    async def screenshot(self: "Scare", url: str, wait: int) -> File:
        path = f"./screenshots/{url.replace('https://', '').replace('http://', '').replace('/', '')}.{wait}.png"

        if os.path.exists(path):
            return File(path)

        async with self.sslock[path]:
            if not re.match(r"^https?://", url):
                url = f"https://{url}"

            viewport = {"width": 1980, "height": 1080}

            proxy = self.get_proxy()

            if not self.browser:
                self.browser = await launch(
                    headless=True,
                    args=[
                        "--no-sandbox", 
                        f"--proxy-server={proxy.host}:{proxy.port}"
                    ],
                    defaultViewport=viewport,
                )

            page = await self.browser.newPage()
            await page.authenticate(
                {"username": proxy.username, "password": proxy.password}
            )

            keywords = ["pussy", "tits", "porn", "cock", "dick"]
            try:
                r = await page.goto(url, load=True, timeout=10000)
            except:
                await page.close()
                raise BadArgument("Unable to screenshot page")

            if not r:
                await page.close()
                raise BadArgument("This page returned no response")

            if content_type := r.headers.get("content-type"):
                if not any(
                    (i in content_type for i in ("text/html", "application/json"))
                ):
                    await page.close()
                    raise BadArgument("This kind of page cannot be screenshotted")

                content = await page.content()
                if any(
                    re.search(r"\b{}\b".format(keyword), content, re.IGNORECASE)
                    for keyword in keywords
                ):
                    await page.close()
                    raise BadArgument(
                        "This websites is most likely to contain explicit content"
                    )

                await asyncio.sleep(wait)
                await page.screenshot(path=path)

                bad_filters = [
                    "BUTTOCKS_EXPOSED",
                    "FEMALE_BREAST_EXPOSED",
                    "ANUS_EXPOSED",
                    "FEMALE_GENITALIA_EXPOSED",
                    "MALE_GENITALIA_EXPOSED",
                ]
                detections = NudeDetector().detect(path)
                if any(
                    [prediction["class"] in bad_filters for prediction in detections]
                ):
                    raise BadArgument(
                        "This websites is most likely to contain explicit content"
                    )

                await page.close()
                return File(path)

    async def has_cooldown(self, interaction: Interaction) -> bool:
        ratelimit = ratelimiter(
            bucket=f"{interaction.channel.id}", key="globalratelimit", rate=3, per=3
        )

        if ratelimit:
            await interaction.response.defer(ephemeral=True)
        return bool(ratelimit)

    async def check_blacklisted(self, interaction: Interaction):
        objects = (interaction.user.id, getattr(interaction.guild, "id", 0))
        result = await self.db.fetchrow(
            f"SELECT * FROM blacklist WHERE target_id IN {objects}"
        )
        if result:
            message = (
                "You have been blacklisted from using scare."
                if result.target_type == "user"
                else f"{interaction.guild} is blacklisted from using scare's commands."
            )
            await interaction.alert(
                f"{message} Please join our [**support server**](https://discord.gg/scarebot) and create a ticket for more information"
            )

        cooldown = await self.has_cooldown(interaction)
        return result is None and not cooldown

    async def leave_unauthorized(self):
        whitelisted = list(
            map(
                lambda r: r["guild_id"],
                await self.db.fetch("SELECT guild_id FROM authorize"),
            )
        )

        results = [g.id for g in self.guilds if not g.id in whitelisted]

        for guild_id in results:
            if server := self.get_guild(guild_id):
                await asyncio.sleep(0.1)
                await server.leave()

    async def status_switch(self):
        names = [
            #'🔗 scare.life/discord',
            # f'{len(self.guilds):,} guilds',
            # f'{len(self.users):,} users',
            #   f'🔗 discord.gg/juno'
        ]

        while True:
            for name in names:
                await self.change_presence(
                    activity=Activity(
                        type=ActivityType.custom,
                        name=name,
                        state=name,
                        url="https://twitch.tv/scarebot",
                    )
                )
                await asyncio.sleep(70)

    @property
    def invite_url(self: "Scare"):
        return oauth_url(self.user.id, permissions=Permissions(8))

    def parse_date(self: "Scare", date: str) -> datetime:
        cal = pdt.Calendar()
        return cal.parseDT(date, datetime.now())[0]

    async def giveaway_task(
        self: "Scare", message_id: int, channel_id: int, end_at: datetime
    ):
        now = datetime.now(tz=date_timezone.utc)
        if end_at > now:
            wait = (end_at - now).total_seconds()
            await asyncio.sleep(wait)

        del self.giveaways[message_id]
        gw = await self.db.fetchrow(
            "SELECT * FROM giveaway WHERE message_id = $1", message_id
        )

        if gw:
            try:
                winners = random.sample(gw.members, gw.winners)
                embed = (
                    Embed(
                        title=gw.reward,
                        color=self.color,
                        description=f"Ended: {format_dt(now, style='R')}",
                    )
                    .add_field(
                        name=f"Winners ({gw.winners})",
                        value=", ".join(list(map(lambda m: f"<@{m}>", winners))),
                    )
                    .set_footer(text="scare.life")
                )
            except ValueError:
                embed = Embed(
                    title=gw.reward,
                    color=self.color,
                    description=f"Not enough participants in the giveaway ({gw.members} entries)",
                ).set_footer(text="scare.life")
            finally:
                await self.db.execute(
                    "UPDATE giveaway SET ended = $1 WHERE message_id = $2",
                    True,
                    message_id,
                )
                with suppress(Exception):
                    message = await self.get_channel(channel_id).fetch_message(
                        message_id
                    )
                    await message.edit(embed=embed, view=None)

    async def reminder_task(
        self: "Scare",
        user_id: int,
        reminder: str,
        remind_at: datetime,
        invoked_at: datetime,
        task_number: int,
    ):
        remind_at = remind_at.replace(tzinfo=date_timezone.utc)
        invoked_at = invoked_at.replace(tzinfo=date_timezone.utc)

        async def send_reminder():
            del self.reminder_tasks[str(user_id)][str(task_number)]
            if user := self.get_user(user_id):
                embed = Embed(
                    color=self.color, description=f"â° {reminder}"
                ).set_footer(
                    text=f"You told me to remind you that {humanize.naturaltime(invoked_at)}"
                )
                with suppress(Exception):
                    await user.send(embed=embed)
                    await self.db.execute(
                        "DELETE FROM reminders WHERE user_id = $1 AND remind_at = $2 AND invoked_at = $3",
                        user_id,
                        remind_at,
                        invoked_at,
                    )

        if remind_at.timestamp() < datetime.now().timestamp():
            return await send_reminder()

        wait_for = (remind_at - datetime.now(date_timezone.utc)).total_seconds()
        await asyncio.sleep(wait_for)
        return await send_reminder()

    @property
    def files(self) -> List[str]:
        return [
            f"{root}/{f}"
            for root, _, file in os.walk("./")
            for f in file
            if f.endswith((".py", ".html", ".js", ".css"))
        ]

    @property
    def lines(self) -> int:
        return sum(len(open(f).read().splitlines()) for f in self.files)

    def size_to_bytes(self: "Scare", size: str):
        size_name = ["B", "KB", "MB", "GB", "TB"]
        return int(
            math.pow(1024, size_name.index(size.split(" ")[1]))
            * float(size.split(" ")[0])
        )

    def flatten(self: "Scare", data: list) -> list:

        return [i for y in data for i in y]

    async def on_shard_connect(self: "Scare", shard_id: int):
        if not self.isinstance:
            self.shard_connected[shard_id] = datetime.now()

    async def on_shard_disconnect(self: "Scare", shard_id: int):
        if not self.isinstance:
            self.shard_connected[shard_id] = datetime.now()

    async def on_shard_ready(self: "Scare", shard_id: int):
        if not self.isinstance:
            self.shard_channel = self.get_channel(1242370657149259847)
            now = datetime.now(timezone("US/Eastern")).strftime("%B %d %Y %I:%M %p")
            ready_in = humanize.naturaldelta(
                datetime.now() - self.shard_connected[shard_id]
            )
            embed = Embed(
                color=self.shard_status.ok,
                description=f">>> [**UPTIME STATUS**] :: {now} EST :: Bot is back **online** on shard **{shard_id}** for {len(self.guilds):,} servers after **{ready_in}**.",
            )
            return await self.shard_channel.send(embed=embed)

    async def toggle_instances(self):
        if not self.toggled:
            instances = await self.db.fetch("SELECT * FROM instances")
            for instance in instances:
                b = Scare(
                    instance_owner_id=instance.owner_id,
                    color=instance.color,
                    instance=True,
                    dbname=instance.dbname,
                    status=getattr(Status, instance.status),
                    node=self.node,
                    activity=CustomActivity(name=instance.activity),
                )
                self.bots[instance.dbname] = {"owner_id": instance.owner_id, "bot": b}
                asyncio.ensure_future(b.start(instance.token))

            self.toggled = True

    async def on_ready(self: "Scare"):
        if not self.isinstance:
            await self.build_cache()
            # asyncio.ensure_future(self.leave_unauthorized())
            youtube_notifications.start(self)
            await self.toggle_instances()

        self.logger.info(
            f"Logged in as {self.user.name} with {len(set(self.walk_commands()))} commands and {len(self.cogs)} cogs loaded!"
        )

    def build_methods(self):
        guild = self.get_guild(1153678095564410891)

        User.is_developer = Member.is_developer = property(
            fget=lambda m: guild.get_role(1247143291275710495)
            in getattr(guild.get_member(m.id), "roles", []),
        )
        User.is_manager = Member.is_manager = property(
            fget=lambda m: guild.get_role(1208937866424750141)
            in getattr(guild.get_member(m.id), "roles", [])
        )
        User.is_staff = Member.is_staff = property(
            fget=lambda m: guild.get_role(1153679566167085136)
            in getattr(guild.get_member(m.id), "roles", [])
        )

        User.web_status = property(
            fget=lambda m: (
                m.mutual_guilds[0].get_member(m.id).web_status
                if m.mutual_guilds
                else Status.offline
            )
        )

        User.mobile_status = property(
            fget=lambda m: (
                m.mutual_guilds[0].get_member(m.id).mobile_status
                if m.mutual_guilds
                else Status.offline
            )
        )

        User.desktop_status = property(
            fget=lambda m: (
                m.mutual_guilds[0].get_member(m.id).desktop_status
                if m.mutual_guilds
                else Status.offline
            )
        )

        User.activity = property(
            fget=lambda m: (
                m.mutual_guilds[0].get_member(m.id).activity
                if m.mutual_guilds
                else None
            )
        )

    async def fetch_application(self, user: Union[Member, User]) -> ApplicationInfo:
        if cache := self.cache.get(f"appinfo-{user.id}"):
            return cache

        x = await self.session.get(
            f"https://discord.com/api/v10/oauth2/applications/{user.id}/rpc",
            headers={"Authorization": self.http.token},
        )

        flags = {
            1 << 12: "Presence",
            1 << 13: "Presence",
            1 << 14: "Guild Members",
            1 << 15: "Guild Members",
            1 << 18: "Message Content",
            1 << 19: "Message Content",
        }

        if x.terms_of_service_url:
            legal = ApplicationLegal(
                terms=x.terms_of_service_url or "https://none.none",
                privacy=x.privacy_policy_url or "https://none.none",
            )
        else:
            legal = None

        info = ApplicationInfo(
            bio=x.description,
            flags=[name for bit, name in flags.items() if x["flags"] & bit],
            tags=x.tags,
            legal=legal,
        )
        await self.cache.add(f"appinfo-{user.id}", info, 3600)
        return info

    async def build_cache(self):
        self.build_methods()
        reminders = await self.db.fetch(
            "SELECT * FROM reminders ORDER BY remind_at ASC"
        )
        giveaways = await self.db.fetch("SELECT * FROM giveaway WHERE NOT ended")
        bumpreminder_guilds = await self.db.fetch(
            "SELECT guild_id FROM bumpreminder WHERE bump_next IS NOT NULL"
        )
        sorted_reminders = defaultdict(list)

        for result in bumpreminder_guilds:
            asyncio.ensure_future(self.bump_cycle(result["guild_id"]))

        for reminder in reminders:
            sorted_reminders[reminder.user_id].append(reminder)

        for giveaway in giveaways:
            self.giveaways[giveaway.message_id] = asyncio.ensure_future(
                self.giveaway_task(
                    giveaway.message_id, giveaway.channel_id, giveaway.ending
                )
            )

        for k, v in sorted_reminders.items():
            for idx, reminder in enumerate(v, start=1):
                await asyncio.sleep(0.1)

                if not self.reminder_tasks.get(k):
                    self.reminder_tasks[k] = {}

                r = dict(reminder)
                r["task_number"] = idx
                self.reminder_tasks[k][str(idx)] = asyncio.ensure_future(
                    self.reminder_task(**r)
                )

        sorted_reminders.clear()

    async def process_commands(self: "Scare", message: Message):
        if message.guild:
            if message.content.startswith(tuple(await bot_prefix(self, message))):
                if not ratelimiter(
                    bucket=f"{message.channel.id}", key="globalratelimit", rate=3, per=3
                ):
                    return await super().process_commands(message)

    async def on_guild_join(self, guild: Guild):
        if await self.db.fetchrow(
            "SELECT * FROM blacklist WHERE target_id = $1", guild.id
        ):
            return await guild.leave()

        if self.isinstance:
            if not await self.db.fetchrow(
                "SELECT * FROM authorize WHERE guild_id = $1", guild.id
            ):
                channel = guild.system_channel or (
                    next(
                        (
                            c
                            for c in guild.text_channels
                            if c.permissions_for(guild.me).send_messages
                        ),
                        None,
                    )
                )

                if channel:
                    await channel.send(
                        "<a:sw_wavecatboy:1279915075414786191> this server is not authorized join [here](<https://discord.gg/scarebot>) to get your server authorized"
                    )

                return await guild.leave()

    async def on_message_edit(self: "Scare", before: Message, after: Message):
        if before.content != after.content:
            await self.on_message(after)

    async def get_context(self: "Scare", message: Message, *, cls=Context) -> Context:
        return await super().get_context(message, cls=cls)

    async def on_command(self: "Scare", ctx: Context):
        await self.db.execute(
            """
            INSERT INTO topcmds 
            VALUES ($1,$2)
            ON CONFLICT (name)
            DO UPDATE SET count = topcmds.count + $2 
            """,
            ctx.command.qualified_name,
            1,
        )

        if ctx.guild:
            self.logger.info(
                f"{ctx.author} ({ctx.author.id}) executed {ctx.command} in {ctx.guild} ({ctx.guild.id})."
            )

    def naive_grouper(self: "Scare", data: list, group_by: int) -> list:
        if len(data) <= group_by:
            return [data]

        groups = len(data) // group_by
        return [list(data[i * group_by : (i + 1) * group_by]) for i in range(groups)]

    async def on_command_error(
        self: "Scare", ctx: Context, exception: CommandError
    ) -> Optional[Message]:
        exception = getattr(exception, "original", exception)
        self.logger.error(f"Command error for {ctx.command}: {type(exception)}")
        if type(exception) in (NotOwner, CommandOnCooldown, UserInputError):
            return

        if isinstance(exception, CommandInvokeError):
            exception = exception.original

        if isinstance(
            exception,
            (
                MissingRequiredArgument,
                MissingRequiredFlag,
                BadLiteralArgument,
                MissingRequiredAttachment,
            ),
        ):
            return await ctx.send_help(ctx.command)

        elif isinstance(exception, CommandNotFound):
            alias = ctx.message.content[len(ctx.clean_prefix) :].split(" ")[0]
            cmd = await self.db.fetchval(
                "SELECT command FROM aliases WHERE alias = $1 AND guild_id = $2",
                alias,
                ctx.guild.id,
            )

            if cmd:
                msg = copy(ctx.message)
                msg.content = msg.content.replace(alias, cmd, 1)
                return await self.process_commands(msg)

        elif isinstance(exception, BadArgument):
            return await ctx.alert(exception.args[0])

        elif isinstance(exception, CheckFailure):
            if isinstance(exception, MissingPermissions):
                return await ctx.alert(
                    f"You don't have permissions to invoke `{ctx.command}`!"
                )

        elif isinstance(exception, Error):
            return await ctx.alert(exception.message)

        elif isinstance(exception, ClientConnectorError):
            return await ctx.alert("The API has timed out!")

        elif isinstance(exception, ClientResponseError):
            return await ctx.send(
                file=File(
                    BytesIO(
                        await self.session.get(f"https://http.cat/{exception.status}")
                    ),
                    filename="status.png",
                )
            )
        else:
            return await ctx.alert(f"{exception}")

    async def check_command(self, ctx: Context):
        if not ctx.guild:
            return True

        if r := await self.db.fetchrow(
            """
            SELECT * FROM disabledcmds 
            WHERE guild_id = $1 
            AND command_name = $2
            """,
            ctx.guild.id,
            ctx.command.qualified_name,
        ):
            await ctx.alert(
                f"**{ctx.command.qualified_name}** is disabled in this server"
            )

        return not r

    def check_message(self: "Scare", message: Message) -> bool:
        return not (
            not self.is_ready()
            or message.author.bot
            or not message.guild
            or message.author.id in self.blacklisted
        )

    async def on_channel_delete(self, channel):
        if not self.isinstance:
            await self.db.execute(
                "DELETE FROM opened_tickets WHERE channel_id = $1", channel.id
            )

    async def on_message(self: "Scare", message: Message) -> None:
        if self.check_message(message):
            if message.content == self.user.mention:
                prefix = await self.get_prefix(message)
                if not ratelimiter(
                    bucket=f"{message.channel.id}", key="globalratelimit", rate=2, per=3
                ):
                    return await message.reply(f"guild prefix: `{prefix[-1]}`")

            await self.process_commands(message)


async def bot_prefix(bot: Scare, message: Message):
    if not (prefix := bot.prefixes.get(message.guild.id)):
        prefix: str = (
            await bot.db.fetchval(
                "SELECT prefix FROM prefix WHERE guild_id = $1", message.guild.id
            )
            or ","
        )
        bot.prefixes[message.guild.id] = prefix

    return when_mentioned_or(prefix)(bot, message)


@tasks.loop(minutes=10)
async def youtube_notifications(bot: Scare):
    results = [
        r
        for r in await bot.db.fetch("SELECT * FROM notifications.youtube")
        if r.channel_ids
    ]
    for result in results:
        html = await bot.session.get(
            f"https://youtube.com/@{result.youtuber}/streams",
            headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
            },
        )
        soup = BeautifulSoup(html, "html.parser")
        s = re.search(r"var ytInitialData = (.*)", soup.prettify()).group(1)
        payload = json.loads(
            json.loads(json.dumps(bot.replace_hex_chars(s)[1:-2])).replace('\\\\"', "'")
        )
        stream = payload["contents"]["singleColumnBrowseResultsRenderer"]["tabs"][3][
            "tabRenderer"
        ]["content"]["richGridRenderer"]["contents"][0]["richItemRenderer"]["content"][
            "compactVideoRenderer"
        ]
        status = stream["thumbnailOverlays"][0]["thumbnailOverlayTimeStatusRenderer"][
            "text"
        ]["runs"][0]["text"]
        if status == "LIVE":
            last_stream = result.last_stream or ""
            if last_stream != stream["videoId"]:
                await bot.db.execute(
                    "UPDATE notifications.youtube SET last_stream = $1 WHERE youtuber = $2",
                    stream["videoId"],
                    result.youtuber,
                )

                url = f"https://youtube.com/watch?v={stream['videoId']}"
                thumbnail = stream["thumbnail"]["thumbnails"][-1]["url"]
                title = stream["title"]["runs"][0]["text"]
                name = soup.find("meta", property="og:title")["content"]
                image = soup.find("meta", property="og:image")["content"]
                youtuber_url = soup.find("meta", property="og:url")["content"]
                embed = (
                    Embed(color=0xFF0000, title=title, url=url, timestamp=utcnow())
                    .set_author(name=name, icon_url=image, url=youtuber_url)
                    .set_image(url=thumbnail)
                )
                content = f"**{name} is LIVE RIGHT NOW**"

                for channel_id in result.channel_ids:
                    if channel := bot.get_channel(channel_id):
                        with suppress(Exception):
                            await channel.send(content=content, embed=embed)
                        await asyncio.sleep(5)
        await asyncio.sleep(10)
