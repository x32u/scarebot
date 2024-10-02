import asyncio
import datetime
import json
import re
from collections import defaultdict
from contextlib import suppress
from io import BytesIO
from typing import Annotated, List, Literal, Optional, Union, Dict
from zipfile import ZipFile

import discord
import humanize
import matplotlib.pyplot as plt
from aiogtts import aiogTTS
from bs4 import BeautifulSoup
from discord import (
    Attachment,
    Embed,
    FFmpegPCMAudio,
    File,
    Guild,
    HTTPException,
    Invite,
    Member,
    Message,
    PartialEmoji,
    Role,
    Spotify,
    TextChannel,
    User,
    app_commands,
    Reaction
)
from discord.ext.commands import (
    Author,
    Cog,
    CurrentChannel,
    CurrentGuild,
    PartialEmojiConverter,
    check,
    command,
    group,
    has_permissions,
    hybrid_command,
    hybrid_group,
)
from discord.utils import format_dt
from pytz import timezone
from shazamio import Shazam

from structure.scare import Afk, Scare, ratelimiter
from structure.managers import Context
from structure.utilities import CashApp, Location
from structure.utilities import Member as AssignableMember
from structure.utilities import (
    Roblox,
    RobloxUser,
    Script,
    Snapchat,
    SnapchatUser,
    Tiktok,
    TikTokUser,
    ValidDate,
    Weather,
    WeatherModel,
    plural,
)


class Miscellaneous(Cog):
    def __init__(self, bot: Scare):
        self.bot: Scare = bot
        self.locks = defaultdict(asyncio.Lock)
        self.shazamio = Shazam()
        self.regex = {
            "pinterest": r"https://((ro|ru|es|uk|fr|de|in|gr|www).pinterest.com/pin|pin.it)/([0-9a-zA-Z]+)",
            "youtube": r"((http(s)?:\/\/)?)(www\.)?((youtube\.com\/)|(youtu.be\/)(watch|shorts))[\S]+",
            "tiktok download": r"^.*https:\/\/(?:m|www|vm|vt)?\.?tiktok\.com\/((?:.*\b(?:(?:v|video|t)\/|\?shareId=|\&item_id=)(\d+))|\w+)",
        }

    @Cog.listener("on_message")
    async def on_repost(self: "Miscellaneous", message: Message):
        if self.bot.is_ready():
            if message.content.startswith(self.bot.user.name):
                if not ratelimiter(
                    bucket=f"reposter-{message.channel.id}",
                    key="reposter",
                    rate=2,
                    per=4,
                ):
                    async with self.locks[message.guild.id]:
                        ctx = await self.bot.get_context(message)
                        url = message.content[len(self.bot.user.name) + 1 :]
                        cmd = None

                        for name, regex in self.regex.items():
                            if re.match(regex, url):
                                cmd = self.bot.get_command(name)
                                break

                        if cmd:
                            return await ctx.invoke(cmd, url=url)

    @Cog.listener("on_message")
    async def on_afk(self: "Miscellaneous", message: Message):
        if self.bot.is_ready() and message.guild:
            if model := self.bot.afk.get(f"{message.author.id}-{message.guild.id}"):
                self.bot.afk.pop(f"{message.author.id}-{message.guild.id}")
                await self.bot.db.execute(
                    "DELETE FROM afk WHERE user_id = $1 AND guild_id = $2",
                    message.author.id,
                    message.guild.id,
                )
                embed = Embed(
                    color=self.bot.color,
                    description=f":wave: {message.author.mention}: **Welcome back**, you were last seen {format_dt(model.since, style='R')}",
                )
                return await message.reply(embed=embed)
            else:
                if message.mentions:
                    if not ratelimiter(
                        bucket=f"afk-{message.channel.id}", key="afk", rate=3, per=2
                    ):
                        mentions: List[Afk] = list(
                            filter(
                                lambda a: a is not None,
                                list(
                                    map(
                                        lambda b: self.bot.afk.get(
                                            f"{b.id}-{message.guild.id}"
                                        ),
                                        message.mentions,
                                    )
                                ),
                            )
                        )

                        if mentions:
                            embeds = [
                                Embed(
                                    color=self.bot.color,
                                    description=f"> <@{result.user_id}> is **AFK** since {format_dt(result.since, style='R')} - {result.reason}",
                                )
                                for result in mentions
                            ]

                            groups = self.bot.naive_grouper(embeds, 10)
                            print(groups)
                            for group in groups:
                                await asyncio.sleep(0.01)
                                await message.channel.send(embeds=group)
    
    @Cog.listener()
    async def on_reaction_remove(
        self: "Miscellaneous", 
        reaction: Reaction, 
        user: Union[Member, User]
    ):
        if not user.bot: 
            if message := reaction.message:
                await self.bot.cache.append(
                    f"reaction-{message.channel.id}", {
                        'reaction': reaction,
                        'user': user,
                        'reacted': datetime.datetime.now()
                    },
                    3600*2
                )

    @Cog.listener()
    async def on_message_delete(self: "Miscellaneous", message: Message):
        if not message.author.bot:
            await self.bot.cache.append(
                f"snipe-{message.channel.id}", message, 3600 * 2
            )

    @Cog.listener()
    async def on_message_edit(self: "Miscellaneous", before: Message, after: Message):
        if not before.author.bot:
            await self.bot.cache.append(
                f"editsnipe-{before.channel.id}", (before, after), 3600 * 2
            )

    @Cog.listener("on_user_update")
    async def on_avatar_change(self: "Miscellaneous", before: User, after: User):
        if before.display_avatar.url != after.display_avatar.url:
            async with self.locks[after.id]:
                with suppress(Exception):
                    avatar_url = await self.bot.session.post(
                        "https://catbox.moe/user/api.php",
                        data={
                            "reqtype": "urlupload",
                            "userhash": "",
                            "url": after.display_avatar.url,
                        },
                    )

                    avatars = (
                        await self.bot.db.fetchval(
                            "SELECT avatars FROM avatarhistory WHERE user_id = $1",
                            before.id,
                        )
                        or []
                    )
                    if not avatar_url in avatars:
                        avatars.append(avatar_url)
                        await self.bot.db.execute(
                            """
                            INSERT INTO avatarhistory VALUES ($1,$2)
                            ON CONFLICT (user_id) DO UPDATE SET avatars = $2  
                            """,
                            after.id,
                            avatars,
                        )

    @Cog.listener()
    async def on_guild_update(self: "Miscellaneous", before: Guild, after: Guild):
        if before.name != after.name:
            await self.bot.db.execute(
                "INSERT INTO gnames (guild_id, gname) VALUES ($1,$2)",
                before.id,
                before.name,
            )

    @Cog.listener("on_user_update")
    async def on_name_change(self: "Miscellaneous", before: User, after: User):
        if str(before) != str(after):
            await self.bot.db.execute(
                "INSERT INTO names (user_id, username) VALUES ($1,$2)",
                before.id,
                str(before),
            )

    @group(aliases=["reminder"], invoke_without_command=True)
    async def remind(self: "Miscellaneous", ctx: Context):
        """
        Manage your reminders
        """

        return await ctx.send_help(ctx.command)

    @remind.command(
        name="add",
        example="in 2 days/on monday evening/on 26 june, finish my assignments",
    )
    async def remind_add(self: "Miscellaneous", ctx: Context, *, reminder: str):
        """
        Add a reminder
        """

        return await ctx.invoke(self.bot.get_command("remindme"), reminder=reminder)

    @remind.command(name="remove", aliases=["rm", "rem"])
    async def remind_remove(self: "Miscellaneous", ctx: Context, number: int):
        """
        Remove a reminder
        """

        if number < 1:
            return await ctx.alert("The number must be higher than 0")

        results = list(
            sorted(
                await self.bot.db.fetch(
                    "SELECT * FROM reminders WHERE user_id = $1", ctx.author.id
                ),
                key=lambda r: r.remind_at,
            )
        )

        if not results:
            return await ctx.alert("You do not have any upcoming reminders")

        try:
            reminder = results[number - 1]
        except IndexError:
            return await ctx.alert(f"You do not have `{number}` reminders")

        async with self.locks[ctx.author.id]:
            task: asyncio.Task = self.bot.reminder_tasks[str(ctx.author.id)][
                str(number)
            ]
            del self.bot.reminder_tasks[str(ctx.author.id)][str(number)]
            task.cancel()
            custom = {}

            for idx, v in enumerate(
                self.bot.reminder_tasks[str(ctx.author.id)].values(), start=1
            ):
                custom[str(idx)] = v

            self.bot.reminder_tasks[str(ctx.author.id)] = custom

            await self.bot.db.execute(
                "DELETE FROM reminders WHERE user_id = $1 AND remind_at = $2",
                ctx.author.id,
                reminder.remind_at,
            )

            return await ctx.confirm(
                f"Removed your {humanize.ordinal(number)} reminder"
            )

    @remind.command(name="list")
    async def remind_list(self: "Miscellaneous", ctx: Context):
        """
        Get a list of your reminders
        """

        reminders = await self.bot.db.fetch(
            "SELECT * FROM reminders WHERE user_id = $1", ctx.author.id
        )

        if not reminders:
            return await ctx.alert("You do not have any upcoming reminders")

        return await ctx.paginate(
            [
                f"**{r.reminder}** {discord.utils.format_dt(r.remind_at, style='R')}"
                for r in sorted(reminders, key=lambda re: re.remind_at)
            ],
            Embed(title="Your reminders").set_footer(
                text=f"To remove a reminder use remind remove [index] where index is the remind number shown on this embed"
            ),
        )

    @command()
    async def reminders(self: "Miscellaneous", ctx: Context):
        """
        Check your reminders
        """

        return await ctx.invoke(self.bot.get_command("remind list"))

    @command(example="in 2 days/on monday evening/on 26 june, finish my assignments")
    async def remindme(self: "Miscellaneous", ctx: Context, *, reminder: str):
        """
        Add a reminder
        """

        try:
            timespan, reason = reminder.split(", ", maxsplit=1)
        except:
            return await ctx.send_help(ctx.command)

        reminders = await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM reminders WHERE user_id = $1", ctx.author.id
        )

        if reminders == 5:
            return await ctx.alert("You cannot have more than 5 reminders")

        async with self.locks[ctx.author.id]:
            date = self.bot.parse_date(timespan)
            now = datetime.datetime.now()
            if (date - now).total_seconds() < 600:
                return await ctx.alert(
                    "Reminders must be at least **10 minutes** later"
                )

            args = [ctx.author.id, reason, date, now]

            await self.bot.db.execute(
                "INSERT INTO reminders VALUES ($1,$2,$3,$4)", *args
            )

            if not self.bot.reminder_tasks.get(str(ctx.author.id)):
                self.bot.reminder_tasks[str(ctx.author.id)] = {}

            idx = str(len(list(self.bot.reminder_tasks[str(ctx.author.id)].keys())) + 1)
            args.append(idx)
            self.bot.reminder_tasks[str(ctx.author.id)][idx] = asyncio.ensure_future(
                self.bot.reminder_task(*args)
            )
            return await ctx.confirm(
                f"I'll remind you about **{reason}** on {date.strftime('%A %d %B %Y, %I:%M %p')} UTC"
            )

    @command(aliases=["topcmds"])
    async def topcommands(self, ctx: Context):
        """
        Get the top 10 most used commands of scare
        """

        results = await self.bot.db.fetch(
            """
            SELECT * FROM topcmds
            ORDER BY count DESC  
            """
        )

        if not results:
            return await ctx.alert("There are no results to show")

        return await ctx.paginate(
            [
                f"**{result.name}** was used `{result.count:,}` times"
                for result in results[:10]
            ],
            Embed(title=f"Top 10 most used commands"),
        )

    @command()
    async def tts(self, ctx: Context, *, phrase: str):
        """
        Convert text to audio
        """

        aiogtts = aiogTTS()
        buffer = BytesIO()
        await aiogtts.write_to_fp(phrase, buffer)
        buffer.seek(0)

        if ctx.author.voice and not ctx.guild.voice_client:
            vc = await ctx.author.voice.channel.connect(self_deaf=True)
            audio = FFmpegPCMAudio(buffer, pipe=True)
            await ctx.send("🗣️")
            vc.play(audio)

            while vc.is_playing():
                await asyncio.sleep(1)

            return await vc.disconnect()

        return await ctx.reply(file=File(buffer, filename="tts.mp3"))

    @hybrid_command()
    async def topavatars(self, ctx: Context):
        """
        Get a leaderboard with the users that have the most avatar changes
        """

        avatars = sorted(
            list(
                filter(
                    lambda r: self.bot.get_user(r.user_id),
                    await self.bot.db.fetch("SELECT * FROM avatarhistory"),
                )
            ),
            key=lambda re: len(re["avatars"]),
            reverse=True,
        )

        if not avatars:
            return await ctx.alert(
                f"Nobody saved their avatars thru **{self.bot.user.name}**"
            )

        embed = Embed(
            title=f"Top 10 avatars",
            description="\n".join(
                [
                    f"`{i}.` {self.bot.get_user(r.user_id)} (`{r.user_id}`) - ({plural(len(r.avatars)):avatar})"
                    for i, r in enumerate(avatars[:10], start=1)
                ]
            ),
        ).set_footer(text=f"{len(avatars):,} total unique users with an avatar history")

        return await ctx.reply(embed=embed)

    @hybrid_command(aliases=["avatars", "avh"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def avatarhistory(
        self: "Miscellaneous", ctx: Context, *, member: User = Author
    ):
        """
        Get a member's avatars
        """

        return await ctx.send(
            f"[{member}'s avatars](https://scare.life/avatars/{member.id})"
        )

    @hybrid_command()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def clearavatars(self: "Miscellaneous", ctx: Context):
        """
        Clear your avatars from our database
        """

        r = await self.bot.db.execute(
            "DELETE FROM avatarhistory WHERE user_id = $1", ctx.author.id
        )

        if r == "DELETE 0":
            return await ctx.alert("You do not have any avatars saved")

        return await ctx.confirm(
            f"Deleted your avatars. You had `{r.split(' ')[-1]}` avatars recorded"
        )

    @hybrid_command(aliases=["gnames"])
    async def guildnames(self: "Miscellaneous", ctx: Context):
        """
        Check the previous names this server had
        """

        names = await self.bot.db.fetch(
            """
            SELECT * FROM gnames
            WHERE guild_id = $1 
            """,
            ctx.guild.id,
        )

        if not names:
            return await ctx.alert("This guild has **no** previous names")

        return await ctx.paginate(
            [f"{r.gname} {format_dt(r.since, style='R')}" for r in names[::-1]],
            Embed(title=f"{ctx.guild.name}'s previous names"),
        )

    @hybrid_command(aliases=["usernames", "pastnames", "pastusernames"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def names(self: "Miscellaneous", ctx: Context, *, member: User = Author):
        """
        Check the previous names that someone had
        """

        usernames = await self.bot.db.fetch(
            "SELECT * FROM names WHERE user_id = $1", member.id
        )

        if not usernames:
            return await ctx.alert("This member has **no** usernames")

        return await ctx.paginate(
            [f"{r.username} {format_dt(r.since, style='R')}" for r in usernames[::-1]],
            Embed(title=f"{member.name}'s usernames"),
        )

    @hybrid_command()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def clearnames(self: "Miscellaneous", ctx: Context):
        """
        Clear your usernames from our database
        """

        r = await self.bot.db.execute(
            "DELETE FROM names WHERE user_id = $1", ctx.author.id
        )

        if r == "DELETE 0":
            return await ctx.alert("You do not have any username saved")

        return await ctx.confirm(
            f"Deleted your usernames. You had `{r.split(' ')[-1]}` unique usernames recorded"
        )

    @hybrid_command(aliases=["firstmsg"])
    async def firstmessage(
        self, ctx: Context, *, channel: TextChannel = CurrentChannel
    ):
        """
        Get the first message of the channel
        """

        message = [
            message async for message in channel.history(limit=1, oldest_first=True)
        ][0]
        embed = Embed(
            title=f"First message in #{channel}",
            url=message.jump_url,
            description=(
                message.content
                if message.content != ""
                else "This message contains only an attachment, embed or sticker"
            ),
            timestamp=message.created_at,
        ).set_author(
            name=str(ctx.author),
            icon_url=ctx.author.display_avatar.url,
            url=ctx.author.url,
        )

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Jump to message", url=message.jump_url))

        return await ctx.reply(embed=embed, view=view)

    @command()
    async def crypto(self, ctx: Context, *, coin: str):
        """
        Get the price of a cryptocurrency
        """

        coins = await self.bot.session.get("https://api.alternative.me/v2/ticker/")

        currency = next(
            (
                i
                for i in coins.data.values()
                if i.website_slug == coin.lower() or i.symbol.lower() == coin.lower()
            ),
            None,
        )

        if not currency:
            return await ctx.alert("We couldn't find information about this coin")

        x = await self.bot.session.get(
            f"https://api.gemini.com/v2/ticker/{currency.symbol.lower()}usd"
        )
        changes = list(reversed(x.changes))
        y = list(map(float, changes))
        plt.plot(y)
        plt.xlabel(f"Prices of {currency.name} in the last 24 hours")
        plt.title(f"{currency.symbol} Price chart")
        buffer = BytesIO()
        plt.savefig(buffer, format="png")
        buffer.seek(0)
        plt.clf()
        embed = (
            discord.Embed(
                title=f"{currency.name} in USD",
            )
            .set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
            .add_field(name="Symbol", value=currency.symbol)
            .add_field(name="Rank", value=f"#{currency.rank}")
            .add_field(name="Price", value=f"${currency.quotes.USD.price:,}")
            .add_field(name="Market Cap", value=f"${currency.quotes.USD.market_cap:,}")
            .add_field(name="Volume", value=f"{currency.quotes.USD.volume_24h:,}")
            .set_image(url="attachment://chart.png")
        )

        return await ctx.reply(embed=embed, file=File(buffer, filename="chart.png"))

    @hybrid_command(aliases=["urban"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def define(self, ctx: Context, *, term: str):
        """
        Find the definition of a word on urban dictionary
        """

        data = await self.bot.session.get(
            "http://api.urbandictionary.com/v0/define", params={"term": term}
        )

        if not data.get("list"):
            return await ctx.alert(f"There's **no** definition for `{term}`")

        return await ctx.paginate(
            [
                Embed(
                    title=definition["word"],
                    url=definition["permalink"],
                    description=f"{definition['definition']}\n{definition['thumbs_up']:,} Likes\n{definition['thumbs_down']:,} Dislikes",
                )
                .set_author(name=definition["author"])
                .add_field(name="example", value=definition["example"])
                for definition in data["list"]
            ]
        )

    @group(invoke_without_command=True)
    async def emoji(self: "Miscellaneous", ctx: Context):
        """
        Manage emojis in your server
        """

        return await ctx.send_help(ctx.command)

    @emoji.command(name="enlarge", aliases=["e"])
    async def emoji_enlarge(
        self: "Miscellaneous", ctx: Context, emoji: Union[discord.PartialEmoji, str]
    ):
        """
        Returns an emoji as an image
        """

        if isinstance(emoji, discord.PartialEmoji):
            file = discord.File(
                BytesIO(await emoji.read()),
                filename=f"{emoji.name}.{'gif' if emoji.animated else 'png'}",
            )
        else:
            unicode_regex = re.compile(
                r"["
                "\U0001F1E0-\U0001F1FF"
                "\U0001F300-\U0001F5FF"
                "\U0001F600-\U0001F64F"
                "\U0001F680-\U0001F6FF"
                "\U0001F700-\U0001F77F"
                "\U0001F780-\U0001F7FF"
                "\U0001F800-\U0001F8FF"
                "\U0001F900-\U0001F9FF"
                "\U0001FA00-\U0001FA6F"
                "\U0001FA70-\U0001FAFF"
                "\U00002702-\U000027B0"
                "\U000024C2-\U0001F251"
                "]+"
            )

            if not re.match(unicode_regex, emoji):
                return await ctx.alert("This is not an emoji")

            data = await self.bot.session.get(
                f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{hex(ord(emoji[0]))[2:]}.png"
            )

            file = discord.File(BytesIO(data), filename="emoji.png")

        return await ctx.reply(file=file)

    @emoji.command(name="zip")
    @has_permissions(manage_expressions=True)
    async def emoji_zip(self: "Miscellaneous", ctx: Context):
        """
        Get a zip file containing all the emojis in this server
        """

        if not ctx.guild.emojis:
            return await ctx.alert("There are **no** emojis in this server")

        async with self.locks[ctx.guild.id]:
            started = datetime.datetime.now()

            async with ctx.typing():
                buffer = BytesIO()

                with ZipFile(buffer, "w") as myzip:
                    for emoji in ctx.guild.emojis:
                        myzip.writestr(
                            f"{emoji.name}.{'gif' if emoji.animated else 'png'}",
                            data=await emoji.read(),
                        )

                buffer.seek(0)
                await ctx.reply(
                    f"Zipped server's emojis in **{humanize.naturaldelta(datetime.datetime.now() - started)}**",
                    file=discord.File(buffer, filename=f"emojis-{ctx.guild}.zip"),
                )

    @emoji.command(name="add", aliases=["steal"])
    @has_permissions(manage_expressions=True)
    async def emoji_steal(
        self: "Context",
        ctx: Context,
        emoji: PartialEmoji,
        *,
        name: Optional[str] = None,
    ):
        """
        Steal an emoji from another server
        """

        name = name or emoji.name
        buffer: bytes = await emoji.read()

        e = await ctx.guild.create_custom_emoji(
            name=name.replace(" ", "_"),
            image=buffer,
            reason=f"Emoji stolen by {ctx.author}",
        )

        return await ctx.confirm(f"Added {e} as `{e.name}`")

    @emoji.command(
        name="addmultiple",
        aliases=["stealmultiple", "am", "sm"],
        example="emoji addmultiple [emojis]/emoji addmultiple [message link]",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_steal_multiple(
        self: "Miscellaneous", ctx: Context, *, emojis: Union[Message, str]
    ):
        """
        Steal multiple emojis
        """

        async def convert(e):
            with suppress(Exception):
                return await PartialEmojiConverter().convert(ctx, e)

            return None

        async with self.locks[ctx.guild.id]:
            if isinstance(emojis, Message):
                em = [await convert(e) for e in emojis.content.split(" ")][:30]
            else:
                em = [await convert(e) for e in emojis.split(" ")][:30]

            em = list(filter(lambda e: e, em))

            if not em:
                return await ctx.alert("No available emojis given to steal")

            added_emojis = []

            await ctx.typing()
            with suppress(HTTPException):
                for emoji in em:
                    await asyncio.sleep(0.1)
                    added_emojis.append(
                        await ctx.guild.create_custom_emoji(
                            name=emoji.name,
                            image=await emoji.read(),
                            reason=f"Emoji stolen by {ctx.author}",
                        )
                    )

            return await ctx.confirm(
                f"Added `{len(added_emojis)}` emojis: {', '.join(map(str, added_emojis))}"
            )

    @emoji.command(name="list")
    async def emoji_list(self: "Miscellaneous", ctx: Context):
        """
        Get a list of all emojis in this server
        """

        if not ctx.guild.emojis:
            return await ctx.alert("There are **no** emojis in this server")

        return await ctx.paginate(
            [f"{e} - `{e.name}`" for e in ctx.guild.emojis],
            Embed(title=f"Emojis in {ctx.guild} ({len(ctx.guild.emojis)})"),
        )

    @group(invoke_without_command=True)
    async def sticker(self: "Miscellaneous", ctx: Context):
        """
        Manage stickers in the server
        """

        return await ctx.send_help(ctx.command)
    
    @sticker.command(name="tag")
    @has_permissions(manage_expressions=True)
    async def sticker_tag(self: "Miscellaneous", ctx: Context):
        """
        Add your server vanity to the server's stickers
        """

        if not ctx.guild.vanity_url_code:
            return await ctx.alert("This server has no vanity")

        if not ctx.guild.stickers:
            return await ctx.alert("There are no stickers in this server")
        
        await ctx.typing()
        for sticker in ctx.guild.stickers:
            pattern = r"(/)([\S]+)"
            if re.search(pattern, sticker.name):
                name = re.sub(
                    pattern, 
                    lambda m: f"{m.group(1)}{ctx.guild.vanity_url_code}", 
                    sticker.name
                )
            else:
                name = sticker.name + f" /{ctx.guild.vanity_url_code}"
            
            if len(name) < 32:
                await sticker.edit(name=name)

        return await ctx.confirm("Tagged all stickers") 

    @sticker.command(name="zip")
    @has_permissions(manage_expressions=True)
    async def sticker_zip(self: "Miscellaneous", ctx: Context):
        """
        Get a zip file of all stickers in this server
        """

        if not ctx.guild.stickers:
            return await ctx.alert("There are **no** stickers in this server")

        async with self.locks[ctx.guild.id]:
            started = datetime.datetime.now()

            async with ctx.typing():
                buffer = BytesIO()

                with ZipFile(buffer, "w") as myzip:
                    for sticker in ctx.guild.stickers:
                        myzip.writestr(f"{sticker.name}.png", data=await sticker.read())

                buffer.seek(0)
                return await ctx.reply(
                    f"Zipped all server's stickers in **{humanize.naturaldelta(datetime.datetime.now() - started)}**",
                    file=discord.File(buffer, filename=f"stickers-{ctx.guild}.zip"),
                )

    @sticker.command(name="add", aliases=["steal"])
    @has_permissions(manage_expressions=True)
    async def sticker_steal(
        self: "Miscellaneous", ctx: Context, message: Optional[Message] = None
    ):
        """
        Steal a sticker from a message
        """

        message = message or ctx.message
        sticker = next(iter(message.stickers), None)

        if not sticker:
            return await ctx.send_help(ctx.command)

        await ctx.guild.create_sticker(
            name=sticker.name,
            description=f"Added with {self.bot.user.name}",
            emoji="skull",
            file=discord.File(BytesIO(await sticker.read())),
            reason=f"Added by {ctx.author}",
        )

        return await ctx.confirm(f"Added sticker as `{sticker.name}`")

    @sticker.command(name="enlarge", aliases=["e"])
    async def sticker_enlarge(
        self: "Miscellaneous", ctx: Context, message: Optional[Message] = None
    ):
        """
        Enlarge a sticker from a message
        """

        message = message or ctx.message
        sticker = next(iter(message.stickers), None)

        if not sticker:
            return await ctx.send_help(ctx.command)

        return await ctx.reply(
            file=discord.File(
                BytesIO(await sticker.read()), filename=f"{sticker.name}.png"
            )
        )

    @hybrid_command()
    @check(lambda ctx: not ctx.bot.afk.get(f"{ctx.author.id}-{ctx.guild.id}"))
    async def afk(self: "Miscellaneous", ctx: Context, *, reason: str = "AFK"):
        """
        Let other people know you are away
        """

        date = datetime.datetime.now()
        await self.bot.db.execute(
            """
            INSERT INTO afk VALUES ($1,$2,$3,$4) 
            ON CONFLICT (user_id, guild_id) DO NOTHING 
            """,
            ctx.author.id,
            ctx.guild.id,
            reason,
            date,
        )

        model = Afk(
            user_id=ctx.author.id, guild_id=ctx.guild.id, reason=reason, since=date
        )

        self.bot.afk[str(model)] = model
        return await ctx.confirm(f"You are now **AFK** - {reason}")

    @command(aliases=["ce"])
    @has_permissions(send_messages=True)
    async def createembed(self: "Miscellaneous", ctx: Context, *, script: Script):
        """
        Create an embed based by a script
        """

        return await ctx.send(**script)

    @command()
    async def variables(self: "Miscellaneous", ctx: Context):
        """
        Get the available embed variables
        """

        models = self.bot.embed.init_models(ctx.author)
        return await ctx.paginate(
            self.bot.flatten(
                [
                    [
                        "{" + f"{k}.{i}" + "}"
                        for i in json.loads(v.schema_json())["properties"].keys()
                    ]
                    for k, v in models.items()
                ]
            ),
            Embed(title="Embed Variables"),
        )

    @command(
        name="serverinfo",
        aliases=["sinfo", "guildinfo", "ginfo", "si", "gi"],
    )
    async def serverinfo(
        self,
        ctx: Context,
        *,
        server: Union[Guild, Invite] = CurrentGuild,
    ):
        """View information about a server"""

        if isinstance(server, discord.Invite):
            _invite = server
            server = server.guild
            if not self.bot.get_guild(server.id):
                return await self.bot.get_command("inviteinfo")(ctx, server=_invite)

        server = self.bot.get_guild(server.id) if server else ctx.guild

        embed = discord.Embed(
            description=(
                discord.utils.format_dt(server.created_at, "f")
                + " ("
                + discord.utils.format_dt(server.created_at, "R")
                + ")"
            )
        )

        embed.set_author(
            icon_url=server.icon,
            name=f"{server} ({server.id})",
        )

        embed.set_thumbnail(
            url=server.icon,
        )

        embed.add_field(
            name="Information",
            value=(
                f">>> **Owner:** {server.owner or server.owner_id}"
                + f"\n**Verification:** {server.verification_level.name.title()}"
                + f"\n**Notifications:** {'Mentions' if server.default_notifications == discord.NotificationLevel.only_mentions else 'All Messages'}"
                # + f"\n**Vanity:** N/A"
            ),
            inline=True,
        )

        embed.add_field(
            name="Statistics",
            value=(
                f">>> **Roles:** {len(server.roles)}/250"
                + f"\n**Emojis:** {len(server.emojis)}/{server.emoji_limit}"
                + f"\n**Text Channels:** {len(server.text_channels):,}"
                + f"\n**Voice Channels:** {len(server.voice_channels):,}"
            ),
            inline=False,
        )

        embed.add_field(
            name="Members",
            value=(
                f">>> **Total:** {server.member_count:,}"
                f"\n**Humans:** {len([m for m in server.members if not m.bot]):,}"
                f"\n**Bots:** {len([m for m in server.members if m.bot]):,}"
            ),
            inline=True,
        )

        await ctx.send(embed=embed)

    @hybrid_command()
    @has_permissions(manage_channels=True)
    async def picperms(
        self, ctx: Context, *, member: Annotated[Member, AssignableMember]
    ):
        """
        Grant or remove a member's permissions to post pictures in a channel
        """

        overwrites = ctx.channel.overwrites_for(member)
        permissions = ctx.channel.permissions_for(member)

        if not permissions.embed_links or not permissions.attach_files:
            overwrites.embed_links = True
            overwrites.attach_files = True
            await ctx.channel.set_permissions(
                member,
                overwrite=overwrites,
                reason=f"Pic perms granted by {ctx.author}",
            )

            return await ctx.confirm(
                f"Granted pic perms for {member.mention} in this channel"
            )
        else:
            overwrites.embed_links = False
            overwrites.attach_files = False
            await ctx.channel.set_permissions(
                member,
                overwrite=overwrites,
                reason=f"Pic perms removed by {ctx.author}",
            )

            return await ctx.confirm(
                f"Removed pic perms from {member.mention} in this channel"
            )

    @command()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def shazam(self, ctx: Context, attachment: Attachment):
        """
        Get the song name from a video
        """

        if not attachment.content_type or not attachment.content_type.startswith(
            "video"
        ):
            return await ctx.alert("This is **not** a video")

        async with ctx.typing():
            try:
                track = await self.shazamio.recognize_song(await attachment.read())
                return await ctx.confirm(
                    f"Track: [**{track['track']['share']['subject']}**]({track['track']['share']['href']})"
                )
            except KeyError:
                return await ctx.alert("Unable to find track")

    @command(example="not like us")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def lyrics(self, ctx: Context, *, song: str):
        """
        Get the lyrics of a song
        """

        x = await self.bot.session.get(f"https://lyrist.vercel.app/api/{song}")
        x.url = f"https://genius.com/{'-'.join(x.artist.split(' '))}-{'-'.join(x.title.split(' '))}-lyrics"
        buffer = BytesIO(bytes(x.lyrics, "utf-8"))
        embed = Embed(title=f"{x.title} by {x.artist}", url=x.url).set_author(
            name=x.artist, icon_url=x.image
        )
        return await ctx.reply(
            embed=embed, file=File(buffer, filename=f"{x.title} lyrics.txt")
        )

    @hybrid_command(aliases=["sp"])
    async def spotify(self, ctx: Context, *, member: Member = None):
        """
        Show what an user is listening on spotify
        """

        if not member:
            member = ctx.author
        a = next((a for a in member.activities if isinstance(a, Spotify)), None)
        if not a:
            return await ctx.alert("You are not listening to **spotify**")
        await ctx.reply(
            f"||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||||​||https://open.spotify.com/track/{a.track_id}"
        )

    @hybrid_command()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def weather(
        self: "Miscellaneous",
        ctx: Context,
        *,
        location: Annotated[WeatherModel, Weather],
    ):
        """
        Get the weather from a location
        """

        embed = (
            discord.Embed(
                title=f"{location.city}, {location.country}",
                description="".join(
                    [
                        f">>> **{location.condition.text}** in **{location.city}** on ",
                        location.localtime.strftime("%A, %d %b %Y %I:%M %p"),
                        f"\nHumidity: **{location.humidity}%**",
                    ]
                ),
                timestamp=location.last_updated,
            )
            .set_thumbnail(url=location.condition.icon)
            .add_field(
                name="Temp (°F)",
                value=f">>> {location.temperature.fahrenheit}°F\nFeels like {location.feelslike.fahrenheit}°F",
            )
            .add_field(name="Wind (mph)", value=f">>> {location.wind.mph} mph")
        )

        view = discord.ui.View(timeout=None)
        button = discord.ui.Button(label="°C / kph")

        async def interaction_check(interaction: discord.Interaction):
            expression = ctx.author.id == interaction.user.id

            if not expression:
                await interaction.response.defer(ephemeral=True)

            return expression

        async def callback(interaction: discord.Interaction):
            embed = interaction.message.embeds[0]
            if button.label == "°C / kph":
                embed.set_field_at(
                    0,
                    name="Temp (°C)",
                    value=f">>> {location.temperature.celsius}°C\nFeels like {location.feelslike.celsius}°C",
                )
                embed.set_field_at(
                    1, name="Wind (kph)", value=f">>> {location.wind.kph} kph"
                )
                button.label = "°F / mph"
            else:
                embed.set_field_at(
                    0,
                    name="Temp (°F)",
                    value=f">>> {location.temperature.fahrenheit}°F\nFeels like {location.feelslike.fahrenheit}°F",
                )
                embed.set_field_at(
                    1, name="Wind (mph)", value=f">>> {location.wind.mph} mph"
                )
                button.label = "°C / kph"

            return await interaction.response.edit_message(embed=embed, view=view)

        button.callback = callback
        view.interaction_check = interaction_check
        view.add_item(button)
        return await ctx.reply(embed=embed, view=view)

    @hybrid_command(aliases=["ca"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def cashapp(self, ctx: Context, user: CashApp):
        """
        Get an user's cashapp profile
        """

        embed = (
            Embed(
                color=discord.Color.from_str(user.accent_color),
                title=f"{user.display_name} (@{user.tag})",
                description=f"Donate [${user.tag}]({user.url}) some cash",
                url=user.url,
            )
            .set_thumbnail(url=user.avatar_url)
            .set_image(url=user.qr_url)
        )

        return await ctx.reply(embed=embed)

    @hybrid_command()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def roblox(self, ctx: Context, user: Annotated[RobloxUser, Roblox]):
        """
        Get information about a roblox user
        """

        embed = (
            Embed(
                color=self.bot.color,
                title=f"@{user.username}",
                url=user.url,
                description=user.bio,
                timestamp=user.created_at,
            )
            .set_thumbnail(url=user.avatar_url)
            .add_field(name="Followers", value=f"{user.followers:,}")
            .add_field(name="Following", value=f"{user.followings:,}")
            .add_field(name="Friends", value=f"{user.friends:,}")
            .set_footer(text=user.id)
        )

        if user.banned:
            embed.add_field(name="banned user")

        return await ctx.reply(embed=embed)

    @hybrid_command(aliases=["yt"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def youtube(self: "Miscellaneous", ctx: Context, url: str):
        """
        Repost an youtube video
        """

        yt = re.compile(self.regex["youtube"])

        if not yt.match(url):
            return await ctx.alert("This is **not** an YouTube post url")

        await ctx.typing()
        x = await self.bot.session.post(
            "https://yt5s.io/api/ajaxSearch", data={"q": url, "vt": "mp4"}
        )

        size = next(
            (
                i
                for i in x.links.mp4.values()
                if self.bot.size_to_bytes(i.size)
                < getattr(ctx.guild, "filesize_limit", 26214400)
            ),
            None,
        )

        if not size:
            return await ctx.alert("This video cannot be reposted here")

        async def download():
            z = await self.bot.session.post(
                "https://cv176.ytcdn.app/api/json/convert",
                data={
                    "v_id": x["vid"],
                    "ftype": size["f"],
                    "fquality": size["q"],
                    "fname": x["fn"],
                    "token": x["token"],
                    "timeExpire": x["timeExpires"],
                },
            )
            if z.result == "Converting":
                await asyncio.sleep(1)
                return await download()
            return z.result

        clip = await download()
        buffer = BytesIO(await self.bot.session.get(clip))
        file = File(buffer, filename="youtube.mp4")
        embed = Embed(title=x.title, url=url).set_author(name=x.a)
        return await ctx.reply(embed=embed, file=file)

    @hybrid_command(aliases=["pin"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def pinterest(self: "Miscellaneous", ctx: Context, url: str):
        """
        Repost a pinterest image
        """

        pin = re.compile(self.regex["pinterest"])

        if not pin.match(url):
            return await ctx.alert("This is **not** a pinterest post url")

        html = await self.bot.session.get(url)
        soup = BeautifulSoup(html, "html.parser")

        if not (img := soup.find("img")):
            return await ctx.alert("Image reposting is supported from now")

        data = await self.bot.session.get(img["src"])
        buffer = BytesIO(data)
        return await ctx.reply(
            content=img["alt"], file=File(buffer, filename="pin.jpg")
        )

    @hybrid_command(aliases=["snap"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def snapchat(
        self: "Miscellaneous", ctx: Context, user: Annotated[SnapchatUser, Snapchat]
    ):
        """
        Get information about a snapchat user
        """

        embed = discord.Embed(
            title=f"{user.display_name} ({user.username})", url=user.url
        ).set_thumbnail(url=user.bitmoji)

        kwargs = {"embed": embed}

        if user.snapcode:
            view = discord.ui.View(timeout=None)
            button = discord.ui.Button(
                label=f"Add {user.username}", custom_id="snapchat_user"
            )

            async def callback(interaction: discord.Interaction):
                e = discord.Embed(color=self.bot.color)
                e.set_image(url=user.snapcode)
                return await interaction.response.send_message(embed=e, ephemeral=True)

            button.callback = callback
            view.add_item(button)
            kwargs.update({"view": view})

        return await ctx.reply(**kwargs)

    @hybrid_group(aliases=["tt"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def tiktok(
        self: "Miscellaneous",
        ctx: Context,
        user: Optional[Annotated[TikTokUser, Tiktok]] = None,
    ):
        """
        Get information from tiktok
        """

        if not user:
            return await ctx.send_help(ctx.command)
        else:
            return await ctx.invoke(self.bot.get_command("tiktok user"), user=user)

    @tiktok.command(name="user")
    async def tiktok_user(
        self: "Miscellaneous", 
        ctx: Context, 
        user: Annotated[TikTokUser, Tiktok]
    ):
        """
        Get information about a tiktok user
        """

        embed = (
            Embed(
                color=self.bot.color,
                title=f"@{user.username}",
                url=user.url,
                description=user.bio,
            )
            .set_thumbnail(url=user.avatar)
            .add_field(name="Followers", value=f"{user.followers:,}")
            .add_field(name="Following", value=f"{user.following:,}")
            .add_field(name="Hearts", value=f"{user.hearts:,}")
        )

        return await ctx.reply(embed=embed)

    @tiktok.command(name="download", aliases=["dl"])
    async def tiktok_download(self: "Miscellaneous", ctx: Context, url: str):
        """
        Repost a tiktok video
        """

        tt = re.compile(self.regex["tiktok download"])

        if not tt.match(url):
            return await ctx.alert("This is not a **TikTok** post url")

        await ctx.typing()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0"
        }

        html = await self.bot.session.get(url, headers=headers)

        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", attrs={"id": "__UNIVERSAL_DATA_FOR_REHYDRATION__"})
        payload = json.loads(script.text)

        if not payload["__DEFAULT_SCOPE__"].get("webapp.video-detail"):
            return await ctx.alert("This tiktok cannot be downloaded now")

        video_info = payload["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"][
            "itemStruct"
        ]

        video_url = video_info["video"]["playAddr"]
        b = await self.bot.session.get(video_url, headers=headers)

        if len(b) > getattr(ctx.guild, "filesize_limit", 26214400):
            return await ctx.alert("Cannot download this video here")

        file = discord.File(BytesIO(b), filename="tiktok.mp4")

        desc = video_info["desc"]
        created_at = datetime.datetime.fromtimestamp(int(video_info["createTime"]))

        author = {
            "name": video_info["author"]["uniqueId"],
            "icon_url": video_info["author"]["avatarLarger"],
        }

        likes = video_info["stats"]["diggCount"]
        embed = (
            Embed(
                description=f"[{desc}]({url})" if desc != "" else None,
                timestamp=created_at,
            )
            .set_author(**author)
            .set_footer(text=f"{likes:,} ❤️")
        )
        return await ctx.reply(embed=embed, file=file)

    @hybrid_command(aliases=["ig"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def instagram(self, ctx: Context, user: str):
        """
        Look up for an instagram profile
        """

        data = await self.bot.session.get(
            "https://api.scare.life/instagram",
            headers=self.bot.luma_headers,
            params={"username": user},
        )

        if data.get("detail"):
            return await ctx.alert(f"**@{user}** on Instagram was not found")

        badges = []
        biolinks = []

        if data["is_private"]:
            badges.append("🔒")

        if data["is_verified"]:
            badges.append("<:verified:1271547192485871717>")
        for link in data["biolinks"]:
            biolinks.append(f"{link['name']} - {link['url']}")

        embed = (
            discord.Embed(
                title=f"@{data['username']} {''.join(badges)}",
                url=data["url"],
                description=data["bio"],
            )
            .set_thumbnail(url=data["avatar_url"])
            .set_author(name=", ".join(data["pronouns"]))
            .add_field(name="Posts", value=f"{data['posts']:,}")
            .add_field(name="Followers", value=f"{data['followers']:,}")
            .add_field(name="Following", value=f"{data['following']:,}")
        )

        view = discord.ui.View()
        if data["biolinks"]:
            button = discord.ui.Button(label="Biolinks")

            async def callback(interaction: discord.Interaction):
                e = Embed(
                    color=self.bot.color,
                    title=f"@{data['username']} biolinks",
                    description="\n".join(biolinks),
                    url=data["url"],
                ).set_thumbnail(url=data["avatar_url"])

                return await interaction.response.send_message(embed=e, ephemeral=True)

            button.callback = callback
            view.add_item(button)

        return await ctx.reply(embed=embed, view=view)

    @hybrid_command(aliases=["img"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def image(self, ctx: Context, *, query: str):
        """
        Search for an image on the web
        """
        data = await self.bot.session.get(
            f"https://api.scare.life/images",
            headers=self.bot.luma_headers,
            params={"query": query, "safe": "True"},
        )

        if not data["images"]:
            return await ctx.alert("No images found")

        embeds = []
        for image in data["images"]:
            embeds.append(
                discord.Embed(
                    color=self.bot.color, title=f"Result for {query}"
                ).set_image(url=image)
            )
        await ctx.paginate(embeds)

    @hybrid_command(aliases=["gh"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def github(self, ctx: Context, user: str):
        """
        Get info about a github account
        """

        data = await self.bot.session.get(f"https://api.github.com/users/{user}")
        avatar = data["avatar_url"]
        url = data["html_url"]
        name = data["name"]
        company = data["company"]
        location = data["location"]
        biotext = data["bio"]
        followers = data["followers"]
        following = data["following"]
        repos = data["public_repos"]

        descr = f"""
{f'> {biotext}' if biotext else ''}
"""
        embed = discord.Embed(
            title=f"{name} (@{user})",
            url=url,
            description=f"> {biotext}" if biotext else "",
            color=0x31333B,
        )
        embed.set_thumbnail(url=avatar if avatar else "https://none.none")
        embed.add_field(name="company", value=company, inline=True)
        embed.add_field(name="location", value=location, inline=True)
        embed.add_field(name="repo count", value=repos, inline=True)
        embed.set_footer(text=f"followers: {followers} | following: {following}")

        await ctx.send(embed=embed)

    @hybrid_command(
        name="ping",
        aliases=["latency"],
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def ping(self: "Miscellaneous", ctx: Context) -> Message:
        """
        Get the bot's latency
        """
        start = discord.utils.utcnow()
        embed = discord.Embed(
            description=f"{ctx.author.mention}: {round(self.bot.latency * 1000, 2)}ms",
            color=self.bot.color,
        )

        result = await self.bot.db.fetch("EXPLAIN ANALYZE SELECT 100")
        time = result[-1]["QUERY PLAN"].split(":")[-1].replace(" ms", "")

        try:
            msg = await ctx.reply(
                f"... `WS: {round(self.bot.latency * 1000, 1)}ms`, `DB:{time}ms`", mention_author=False
            )
        except:
            msg = await ctx.send(
                f"... `WS: {round(self.bot.latency * 1000, 1)}ms`, `DB:{time}ms`",
            )

        end = discord.utils.utcnow()
        await msg.edit(
            content=msg.content
            + f" (edit: `REST: {round((end - start).total_seconds() * 1000, 1)}ms`)"
        )

    @command(example="how to get a cat")
    async def wikihow(self: "Miscellaneous", ctx: Context, *, question: str):
        """
        Get answers to your question from wikihow
        """

        html = await self.bot.session.get(
            "https://www.wikihow.com/wikiHowTo", params={"search": question}
        )

        soup = BeautifulSoup(html, "html.parser")
        searchlist = soup.find("div", attrs={"id": "searchresults_list"})
        contents = searchlist.find_all("a", attrs={"class": "result_link"})

        for content in contents:
            url = content["href"]
            if not "Category:" in url:
                title = content.find("div", attrs={"class": "result_title"})
                x = await self.bot.session.get(url)
                s = BeautifulSoup(x, "html.parser")
                steps = s.find_all("b", attrs={"class": "whb"})
                embed = discord.Embed(
                    title=title.text,
                    url=url,
                    description="\n".join(
                        [
                            f"`{i}.` {step.text}"
                            for i, step in enumerate(steps[:10], start=1)
                        ]
                    ),
                ).set_footer(text="wikihow.com")
                return await ctx.reply(embed=embed)

        return await ctx.alert("Unfortunately i found nothing")

    @hybrid_command(name="editsnipe", aliases=["es"])
    async def editsnipe(self: "Miscellaneous", ctx: Context, index: int = 1) -> Message:
        """
        Snipe a recently edited message
        """

        messages = self.bot.cache.get(f"editsnipe-{ctx.channel.id}")

        try:
            before, after = messages[::-1][index - 1]
        except IndexError:
            return await ctx.alert("That is out of my range!")
        except TypeError:
            return await ctx.alert("There are no sniped messages in this channel")

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        seconds = (now - after.edited_at).total_seconds()
        edited = humanize.naturaltime(now - datetime.timedelta(seconds=seconds))

        embed = Embed()
        embed.set_author(
            name=after.author.name, icon_url=after.author.display_avatar.url
        ).add_field(name="Before", value=before.content).add_field(
            name="After", value=after.content
        ).set_footer(
            text=f"Edited {edited} \u2022 {index:,}/{len(messages)} messages",
        )

        return await ctx.send(embed=embed)
    
    @hybrid_command(name="reactionsnipe", aliases=['rs'])
    async def reactionsnipe(self: "Miscellaneous", ctx: Context, index: int = 1):
        """
        Snipe a recently removed reaction
        """

        reactions = self.bot.cache.get(f"reaction-{ctx.channel.id}")
        
        try:
            reaction, user, reacted = reactions[::-1][index-1].values()
        except IndexError:
            return await ctx.alert("That is out of my range!")
        except TypeError:
            return await ctx.alert("There are no sniped reactions in this channel")
        
        await ctx.neutral(
            f"{user.mention} removed {reaction.emoji} from {reaction.message.jump_url} {format_dt(reacted, style='R')}"
        ) 

    @hybrid_command(name="snipe", aliases=["s"])
    async def snipe(self: "Miscellaneous", ctx: Context, index: int = 1) -> Message:
        """
        Snipe a recently deleted message
        """

        messages = self.bot.cache.get(f"snipe-{ctx.channel.id}")

        try:
            message: discord.Message = messages[::-1][index - 1]
        except IndexError:
            return await ctx.alert("That is out of my range!")
        except TypeError:
            return await ctx.alert("There are no sniped messages in this channel")

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        seconds = (now - message.created_at).total_seconds()
        deleted = humanize.naturaltime(now - datetime.timedelta(seconds=seconds))

        if re.search(self.bot.invite_regex, message.content):
            mes = (
                "This message cannot be displayed because it contains a discord invite"
            )
        else:
            mes = message.content

        embed = (
            Embed(
                description=(
                    mes if mes != "" else "Message has embed or attachment only!!"
                )
            )
            .set_author(
                name=message.author.name, icon_url=message.author.display_avatar.url
            )
            .set_footer(
                text=f"Deleted {deleted} \u2022 {index:,}/{len(messages)} messages",
            )
        )

        if message.attachments:
            attachment = message.attachments[0]
            if attachment.content_type:
                if attachment.content_type.startswith("image"):
                    embed.set_image(url=attachment.url)
                else:
                    file = discord.File(
                        BytesIO(await attachment.read()), filename=attachment.filename
                    )
                    return await ctx.send(embed=embed, file=file)

        elif message.stickers:
            embed.set_image(url=message.stickers[0].url)

        return await ctx.send(
            embeds=[
                embed,
                *[embed for embed in message.embeds[:-1]],
            ],
        )

    @hybrid_command(name="clearsnipes", aliases=["cs"])
    @has_permissions(manage_messages=True)
    async def clearsnipes(self: "Miscellaneous", ctx: Context) -> Message:
        """
        Clear the snipe cache
        """

        self.bot.cache.remove(f"snipe-{ctx.channel.id}")
        self.bot.cache.remove(f"editsnipe-{ctx.channel.id}")
        return await ctx.message.add_reaction("👍")

    @command(
        name="inviteinfo",
        aliases=["ii"],
    )
    async def inviteinfo(
        self,
        ctx: Context,
        *,
        server: Union[Invite, Guild] = CurrentGuild,
    ):
        """
        View information about an server
        """

        if isinstance(server, discord.Guild):
            return await self.bot.get_command("serverinfo")(ctx, server=server)
        else:
            if self.bot.get_guild(server.guild.id):
                return await self.bot.get_command("serverinfo")(
                    ctx, server=server.guild
                )

        invite = server
        server = invite.guild

        embed = discord.Embed(description=(discord.utils.format_dt(server.created_at)))
        embed.set_author(
            name=f"{server} ({server.id})",
            icon_url=server.icon,
        )
        embed.set_image(
            url=server.banner.with_size(1024).url if server.banner else None
        )

        embed.add_field(
            name="Invite",
            value=(
                f"**Channel:** {('#' + invite.channel.name) if invite.channel else 'N/A'}"
                + f"\n**Inviter:** {invite.inviter or 'N/A'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Server",
            value=(
                f"**Members:** {invite.approximate_member_count:,}"
                + f"\n**Members Online:** {invite.approximate_presence_count:,}"
            ),
            inline=True,
        )

        await ctx.send(embed=embed)

    @command(
        name="servericon",
        aliases=[
            "icon",
            "guildicon",
            "sicon",
        ],
    )
    async def icon(
        self: "Miscellaneous", 
        ctx: Context, 
        *, 
        guild: Union[Guild, Invite] = CurrentGuild
    ) -> Message:
        """
        Returns guild icon
        """

        if isinstance(guild, Invite):
            guild = guild.guild

        if not guild.icon:
            return await ctx.send("No **server icon** is set")

        return await ctx.send(
            embed=Embed(
                url=guild.icon,
                title=f"{guild.name}'s icon",
            ).set_image(url=guild.icon),
        )

    @command(
        name="guildbanner",
        aliases=[
            "serverbanner",
            "gbanner",
        ],
    )
    async def guildbanner(
        self: "Miscellaneous", 
        ctx: Context, 
        *, 
        guild: Union[Guild, Invite] = CurrentGuild
    ) -> Message:
        """
        Returns guild banner
        """

        if isinstance(guild, Invite):
            guild = guild.guild

        if not guild.banner:
            return await ctx.send("No server banner is set")

        return await ctx.send(
            embed=Embed(
                url=guild.banner,
                title=f"{guild.name}'s guild banner",
            ).set_image(url=guild.banner)
        )

    @command(
        name="splash",
    )
    async def splash(
        self: "Miscellaneous", 
        ctx: Context, 
        *, 
        guild: Union[Guild, Invite] = CurrentGuild
    ) -> Message:
        """
        Returns splash background
        """

        if isinstance(guild, Invite):
            guild = guild.guild

        if not guild.splash:
            return await ctx.alert("No server splash is set")

        return await ctx.send(
            embed=Embed(
                url=guild.splash,
                title=f"{guild.name}'s guild splash",
            ).set_image(url=guild.splash)
        )

    @command(
        name="roleinfo",
        aliases=["rinfo", "ri"],
    )
    async def roleinfo(
        self: "Miscellaneous", ctx: Context, *, role: Role = None
    ) -> Message:
        """
        View information about a role
        """

        role = role or ctx.author.top_role

        embed = Embed(
            color=role.color,
            title=role.name,
        )
        if isinstance(role.display_icon, discord.Asset):
            embed.set_thumbnail(url=role.display_icon)

        embed.add_field(
            name="Role ID",
            value=f"`{role.id}`",
            inline=True,
        )
        embed.add_field(
            name="Color",
            value=f"`{str(role.color).upper()}`",
            inline=False,
        )
        embed.add_field(
            name=f"{len(role.members):,} Member(s)",
            value=(
                "No members in this role"
                if not role.members
                else ", ".join([user.name for user in role.members][:7])
                + ("..." if len(role.members) > 7 else "")
            ),
            inline=False,
        )

        return await ctx.send(embed=embed)

    @hybrid_command(aliases=["ss"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def screenshot(
        self: "Miscellaneous",
        ctx: Context,
        url: str,
        wait: Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] = 0,
    ):
        """
        Screenshot a website
        """

        async with self.locks[ctx.channel.id]:
            async with ctx.typing():
                file = await self.bot.screenshot(url, wait)
                return await ctx.send(file=file)

    @hybrid_group(invoke_without_command=True)
    async def prefix(self, ctx: Context):
        """
        Check the server's prefix
        """

        prefix = await self.bot.get_prefix(ctx.message)
        return await ctx.send(f"my current prefix is `{prefix[-1]}`")

    @prefix.command(name="set", aliases=["edit"])
    @has_permissions(manage_guild=True)
    async def edit_prefix(self, ctx: Context, prefix: str):
        """
        Change your server's prefix
        """

        if len(prefix) > 5:
            return await ctx.alert("Prefix is too long")

        await self.bot.db.execute(
            """
            INSERT INTO prefix VALUES ($1,$2)
            ON CONFLICT (guild_id) DO UPDATE SET
            prefix = $2
            """,
            ctx.guild.id,
            prefix,
        )

        self.bot.prefixes[ctx.guild.id] = prefix
        await ctx.confirm(f"Updated the server's prefix to `{prefix}`")

    @group(aliases=["bday"], invoke_without_command=True)
    async def birthday(self: "Miscellaneous", ctx: Context, *, member: User = Author):
        """
        Check when is someone's birthday
        """

        date = await self.bot.db.fetchval(
            "SELECT birthdate FROM birthday WHERE user_id = $1", member.id
        )

        if not date:
            return await ctx.alert("This member doesn't have their birthday set")

        precise = humanize.naturaldelta(
            date - datetime.datetime.now(tz=datetime.timezone.utc)
        )

        natural = humanize.naturaldate(date)

        if member == ctx.author:
            embed = Embed(
                color=0xFFC0CB,
                description=f"🎂 Your birthday is **{f'on {natural}' if len(natural.split()) > 1 else natural}**. {f'Happy birthday!' if natural == 'today' else f'That is in **{precise}**'}",
            )
        else:
            embed = Embed(
                color=0xFFC0CB,
                description=f"🎂 {member.name}'s birthday is **{f'on {natural}' if len(natural.split()) > 1 else natural}**. {f'That is in **{precise}**' if natural != 'today' else ''}",
            )

        return await ctx.reply(embed=embed)

    @birthday.command(name="remove", aliases=["unset", "rem", "rm"])
    async def birthday_remove(self: "Miscellaneous", ctx: Context):
        """
        Remove your birthday
        """

        r = await self.bot.db.execute(
            "DELETE FROM birthday WHERE user_id = $1", ctx.author.id
        )

        if r == "DELETE 0":
            return await ctx.alert("Your birthday wasn't set")

        return await ctx.confirm("Removed your birthday")

    @birthday.command(name="set")
    async def birthday_set(
        self: "Miscellaneous",
        ctx: Context,
        *,
        date: Annotated[datetime.datetime, ValidDate],
    ):
        """
        Set your birthday
        """

        await self.bot.db.execute(
            """
            INSERT INTO birthday VALUES ($1,$2)
            ON CONFLICT (user_id) DO UPDATE SET
            birthdate = $2  
            """,
            ctx.author.id,
            date,
        )

        natural = humanize.naturaldelta(date - datetime.datetime.now())

        embed = Embed(
            color=0xFFC0CB,
            description=f"🎂 Your birthday is on **{humanize.naturaldate(date)}**. That's **{natural if natural == 'today' else f'in {natural}'}**",
        )

        return await ctx.reply(embed=embed)

    @birthday.command(name="list")
    async def birthday_list(self: "Miscellaneous", ctx: Context):
        """
        Get a list of everyone's birthday in the server
        """

        users = tuple(
            map(lambda m: m.id, filter(lambda m: not m.bot, ctx.guild.members))
        )
        results = await self.bot.db.fetch(
            f"SELECT * FROM birthday WHERE user_id IN {users}"
        )

        if not results:
            return await ctx.alert(
                "There's no member in this server that has their birthday set"
            )

        return await ctx.paginate(
            [
                f"{ctx.guild.get_member(r.user_id)} **{r.birthdate.strftime('%b %d')}**"
                for r in sorted(results, key=lambda r: r.birthdate)
            ],
            Embed(title=f"Birth dates in {ctx.guild}"),
        )

    @group(aliases=["tz"], invoke_without_command=True)
    async def timezone(
        self: "Miscellaneous", ctx: Context, *, member: discord.User = Author
    ):
        """
        Get someone's timezone
        """

        tz = await self.bot.db.fetchval(
            "SELECT tz FROM timezone WHERE user_id = $1", member.id
        )

        if not tz:
            return await ctx.alert(
                f"{'You do not' if member == ctx.author else f'{member.mention} does not'} have the **timezone** set"
            )

        date = datetime.datetime.now(tz=timezone(tz))

        embed = Embed(
            color=self.bot.color,
            description=f"**{member if member != ctx.author else 'Your'}** date: **{date.strftime('%A, %b %-d %Y %-I:%M %p %Z')}**",
        )

        return await ctx.reply(embed=embed)

    @timezone.command(name="remove")
    async def timezone_remove(self: "Miscellaneous", ctx: Context):
        """
        Remove your timezone
        """

        r = await self.bot.db.execute(
            "DELETE FROM timezone WHERE user_id = $1", ctx.author.id
        )

        if r == "DELETE 0":
            return await ctx.alert("You do not have a **timezone** set")

        return await ctx.confirm("Your timezone has been removed")

    @timezone.command(name="set")
    async def timezone_set(
        self: "Miscellaneous", ctx: Context, *, location: Annotated[str, Location]
    ):
        """
        Set your timezone
        """

        await ctx.bot.db.execute(
            """
            INSERT INTO timezone VALUES ($1,$2)
            ON CONFLICT (user_id) DO UPDATE SET 
            tz = $2
            """,
            ctx.author.id,
            location,
        )

        date = datetime.datetime.now(tz=timezone(location))

        embed = Embed(
            color=self.bot.color,
            description=f"Configured your timezone as `{location}`\nYour date **{date.strftime('%A, %b %-d %Y %-I:%M %p %Z')}**",
        )

        return await ctx.reply(embed=embed)

    @timezone.command(name="list")
    async def timezone_list(self: "Miscellaneous", ctx: Context):
        """
        Get a list of members' timezones in the server
        """

        users = tuple(
            map(lambda m: m.id, filter(lambda m: not m.bot, ctx.guild.members))
        )
        results = await self.bot.db.fetch(
            f"SELECT * FROM timezone WHERE user_id IN {users}"
        )

        if not results:
            return await ctx.alert(
                "There are no members with a timezone set in this server"
            )

        cac = list(
            map(
                lambda m: (m.user_id, datetime.datetime.now(tz=timezone(m.tz))), results
            )
        )

        return await ctx.paginate(
            [
                f"{ctx.guild.get_member(r[0])} - **{r[1].strftime('%A, %b %-d %-I:%M %p')}**"
                for r in sorted(
                    cac,
                    key=lambda r: (
                        r[1].year,
                        r[1].month,
                        r[1].day,
                        r[1].hour,
                        r[1].minute,
                        r[1].second,
                    ),
                )
            ],
            Embed(title=f"Timezones in {ctx.guild}"),
        )

    @hybrid_command(aliases=("ui", "whois"))
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def userinfo(
        self, ctx: "Context", *, user: Union[Member, User] = Author
    ) -> Message:
        """
        View information about a user.
        """

        badges = []
        application = None
        desc = ""
        if not self.bot.isinstance:
            badges = list(
                filter(
                    lambda b: b,
                    [
                        (
                            "<a:owner:1276226057833549824>"
                            if getattr(ctx.guild, "owner_id", None) == user.id
                            else None
                        ),
                        (
                            "<:verifiedowner:1280522003757142048>"
                            if user.id in self.bot.owner_ids
                            else None
                        ),
                        (
                            "<:app:1276220418113409044>"
                            if user.public_flags.verified_bot
                            else None
                        ),
                        (
                            "<:verifiedowner:1280522003757142048>"
                            if user.id == 1083131355984044082
                            else None
                        ),
                        (
                            "<a:dance4:1281731220329463871>"
                            if user.id == 1083131355984044082
                            else None
                        ),
                        (
                            "<a:aw_dance:1281686087072354358>"
                            if user.id == 1083131355984044082
                            else None
                        ),
                        (
                            "<:developer:1275976880826224710>"
                            if user.is_developer
                            else None
                        ),
                        "<:staff:1275976867584671837>" if user.is_manager else None,
                        "<:moderator:1275976853483421788>" if user.is_staff else None,
                        (
                            "<:donor:1276224585435578400>"
                            if await self.bot.db.fetchrow(
                                "SELECT * FROM donator WHERE user_id = $1", user.id
                            )
                            or user.id in self.bot.owner_ids
                            else None
                        ),
                    ],
                )
            )

            application = await self.bot.fetch_application(user) if user.bot else None
            desc = application.bio + "\n" if application else ""
            if user.activity:
                if isinstance(user.activity, Spotify):
                    desc += f"<:spotify:1277335951722680460> Listening to **{user.activity.title}** by **{user.activity.artist}**\n"
                else:
                    desc += f"{user.activity.type.name.capitalize() + ' ' if user.activity.type.name != 'custom' else ''}**{user.activity.name}**\n"

            if user.web_status != discord.Status.offline:
                badges.append("<:web:1275976965785915463>")
            if user.mobile_status != discord.Status.offline:
                badges.append("<:mobile:1275977031355728004>")
            if user.desktop_status != discord.Status.offline:
                badges.append("<:desktop:1275977004029706303>")

        tz = await self.bot.db.fetchval(
            "SELECT tz FROM timezone WHERE user_id = $1", user.id
        )
        birthday = await self.bot.db.fetchval(
            "SELECT birthdate FROM birthday WHERE user_id = $1", user.id
        )

        addons = ""

        if tz:
            addons += f"🕐 **{datetime.datetime.now(tz=timezone(tz)).strftime('%A, %b %-d  %Y %-I:%M %p %Z')}**\n"

        if birthday:
            addons += f"🎂 **{birthday.strftime('%b %-d')}**"

        desc += f"Created: {format_dt(user.created_at, 'D')} ({discord.utils.format_dt(user.created_at, style='R')})\n"

        if isinstance(user, Member):
            desc += f"Joined: {format_dt(user.joined_at, 'D')} ({discord.utils.format_dt(user.joined_at, style='R')})\n"

            if user.premium_since:
                desc += (
                    f"Boosted: {discord.utils.format_dt(user.premium_since, style='R')}"
                )

        embed = (
            Embed(title=f"{user} {' '.join(badges)}", description=desc)
            .set_author(
                name=f"{user} ({user.id})", icon_url=user.display_avatar, url=user.url
            )
            .set_thumbnail(url=user.display_avatar)
            .set_footer(
                text=(
                    f"{len(user.mutual_guilds)} server(s)"
                    if user.id != self.bot.user.id
                    else ""
                )
            )
        )

        if application:
            if legal := application.legal:
                embed.add_field(
                    name="Legal",
                    value=f"[Terms of Service]({legal.terms})\n[Privacy Policy]({legal.privacy})",
                    inline=False,
                )

            if flags := application.flags:
                embed.add_field(
                    name="Intents",
                    value="\n".join(map(lambda f: f"**{f}**", set(flags))),
                    inline=False,
                )

            if tags := application.tags:
                embed.add_field(name="Tags", value=", ".join(tags), inline=False)

        if isinstance(user, discord.Member):
            if roles := user.roles[1:]:
                embed.add_field(
                    name="Roles",
                    value=", ".join(role.mention for role in list(reversed(roles))[:5])
                    + (f" (+{len(roles) - 5})" if len(roles) > 5 else ""),
                    inline=False,
                )

        view = discord.ui.View()
        if len(addons) > 0:
            button = discord.ui.Button(label="misc")

            async def callback(interaction: discord.Interaction):
                e = (
                    discord.Embed(color=self.bot.color)
                    .set_author(
                        name=f"{user} ({user.id})",
                        icon_url=user.display_avatar,
                        url=user.url,
                    )
                    .set_thumbnail(url=user.display_avatar)
                )

                if len(addons) > 0:
                    e.add_field(name="Miscellaneous", value=addons, inline=False)

                return await interaction.response.send_message(embed=e, ephemeral=True)

            button.callback = callback
            view.add_item(button)

        return await ctx.send(embed=embed, view=view)


async def setup(bot: Scare) -> None:
    await bot.add_cog(Miscellaneous(bot))
