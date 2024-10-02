import asyncio
import re
from collections import defaultdict
from contextlib import suppress
from typing import Annotated, List, Optional, Union

from discord import (
    Color,
    Embed,
    File,
    Member,
    Message,
    NotFound,
    RawReactionActionEvent,
    TextChannel,
)
from discord.ext.commands import (
    ChannelNotFound,
    Cog,
    group,
    has_permissions,
    hybrid_group,
)
from discord.ui import Button, View

from structure.scare import Scare, ratelimiter
from structure.managers import Context
from structure.utilities import DiscordEmoji, YouTuber


class Joindm(View):
    def __init__(self, guild: str):
        self.guild = guild
        super().__init__()
        self.add_item(Button(label=f"sent from {self.guild}", disabled=True))


class Notifications(Cog):
    def __init__(self, bot: Scare):
        self.bot = bot
        self.locks = defaultdict(asyncio.Lock)

    @Cog.listener()
    async def on_raw_reaction_remove(self, payload: RawReactionActionEvent):
        if panel_message_id := await self.bot.db.fetchval(
            """
            SELECT panel_message_id FROM skullboard_message 
            WHERE guild_id = $1 AND channel_id = $2 
            AND message_id = $3 
            """,
            payload.guild_id,
            payload.channel_id,
            payload.message_id,
        ):
            if res := await self.bot.db.fetchrow(
                "SELECT * FROM skullboard WHERE guild_id = $1", payload.guild_id
            ):
                if channel := self.bot.get_channel(res["channel_id"]):
                    if res["emoji"] == str(payload.emoji):
                        message = await self.bot.get_channel(
                            payload.channel_id
                        ).fetch_message(payload.message_id)
                        reaction = next(
                            r
                            for r in message.reactions
                            if str(r.emoji) == str(payload.emoji)
                        )
                        m = await channel.fetch_message(panel_message_id)
                        return await m.edit(
                            content=f"**#{reaction.count}** {payload.emoji}"
                        )

    @Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        if not (
            result := await self.bot.db.fetchrow(
                "SELECT * FROM skullboard WHERE guild_id = $1", payload.guild_id
            )
        ):
            return

        channel = self.bot.get_channel(result.channel_id)
        if not channel:
            return

        payload_channel = self.bot.get_channel(payload.channel_id)

        emoji = result.emoji
        count = result.count

        if str(payload.emoji) != emoji:
            return

        if await self.bot.db.fetchrow(
            "SELECT * FROM skullboard_message WHERE panel_message_id = $1",
            payload.message_id,
        ):
            return

        async with self.locks[f"{payload.emoji}-{payload.message_id}"]:
            message = await payload_channel.fetch_message(payload.message_id)
            if not (message.content or message.attachments):
                return

            reaction = next(
                r for r in message.reactions if str(r.emoji) == str(payload.emoji)
            )
            if reaction.count < count:
                return

            author = self.bot.get_guild(payload.guild_id).get_member(
                payload.message_author_id
            )
            content = f"**#{reaction.count}** {reaction.emoji}"

            if re := await self.bot.db.fetchrow(
                """
                SELECT * FROM skullboard_message WHERE
                guild_id = $1 AND channel_id = $2
                AND message_id = $3 
                """,
                payload.guild_id,
                payload.channel_id,
                payload.message_id,
            ):
                with suppress(NotFound):
                    m = await channel.fetch_message(re.panel_message_id)
                    return await m.edit(content=content)

            desc = message.content
            if ref := getattr(message.reference, "resolved", None):
                desc += f"\nReplying to [{ref.author}]({ref.jump_url})"

            embed = Embed(
                color=self.bot.color,
                description=desc,
                title=f"#{message.channel}",
                url=message.jump_url,
                timestamp=message.created_at,
            )

            file: Optional[File] = None
            if len(message.attachments) > 0:
                attachment = message.attachments[0]
                if attachment.filename.endswith(("png", "gif", "jpeg", "jpg")):
                    embed.set_image(url=attachment.url)
                elif attachment.filename.endswith(("mp4", "mov")):
                    file = File(
                        await self.bot.urltobyte(attachment.url),
                        filename=attachment.filename,
                    )

            embed.set_author(name=str(author), icon_url=author.display_avatar.url)

            mes = await channel.send(content=content, embed=embed, file=file)

            await self.bot.db.execute(
                """
                INSERT INTO skullboard_message VALUES ($1,$2,$3,$4)
                ON CONFLICT (guild_id, channel_id, message_id)
                DO UPDATE SET panel_message_id = $4   
                """,
                payload.guild_id,
                payload.channel_id,
                payload.message_id,
                mes.id,
            )

    @Cog.listener("on_message")
    async def on_sticky_message(self, message: Message):
        if message.guild:
            if result := await self.bot.db.fetchval(
                """
                SELECT (message_id, message) FROM sticky_message
                WHERE guild_id = $1 AND channel_id = $2 
                """,
                message.guild.id,
                message.channel.id,
            ):
                if not ratelimiter(
                    bucket=f"stickymessage-{message.channel.id}",
                    key="stickymessage",
                    rate=3,
                    per=10,
                ):
                    message_id, msg = result
                    with suppress(Exception):
                        m = await message.channel.fetch_message(message_id)
                        await m.delete()
                        code = await self.bot.embed.convert(message.author, msg)
                        code.pop("delete_after", None)
                        ms = await message.channel.send(**code)
                        await self.bot.db.execute(
                            """
                            UPDATE sticky_message SET message_id = $1
                            WHERE guild_id = $2 AND channel_id = $3 
                            """,
                            ms.id,
                            ms.guild.id,
                            ms.channel.id,
                        )

    @Cog.listener("on_message")
    async def on_autoreaction(self, message: Message):
        if message.guild:
            if isinstance(message.author, Member):
                if not message.author.bot:
                    result: str = (
                        await self.bot.db.fetchval(
                            """
                        SELECT reactions FROM autoreact 
                        WHERE guild_id = $1 AND trigger = $2 
                        AND strict = $3
                        """,
                            message.guild.id,
                            message.content,
                            True,
                        )
                        or next(
                            (
                                r.reactions
                                for r in await self.bot.db.fetch(
                                    "SELECT reactions, trigger FROM autoreact WHERE guild_id = $1 AND strict = $2",
                                    message.guild.id,
                                    False,
                                )
                                if r.trigger in message.content
                            ),
                            None,
                        )
                    )

                    if result:
                        if not ratelimiter(
                            bucket=f"autoreact-{message.channel.id}",
                            key="autoreact",
                            rate=3,
                            per=5,
                        ):
                            for reaction in result:
                                await asyncio.sleep(0.1)
                                with suppress(Exception):
                                    await message.add_reaction(reaction)

    @Cog.listener("on_message")
    async def on_autoresponder(self, message: Message):
        if message.guild:
            if isinstance(message.author, Member):
                if not message.author.bot:
                    result: str = (
                        await self.bot.db.fetchval(
                            """
                        SELECT response FROM autoresponder 
                        WHERE guild_id = $1 AND trigger = $2 
                        AND strict = $3
                        """,
                            message.guild.id,
                            message.content,
                            True,
                        )
                        or next(
                            (
                                r.response
                                for r in await self.bot.db.fetch(
                                    "SELECT response, trigger FROM autoresponder WHERE guild_id = $1 AND strict = $2",
                                    message.guild.id,
                                    False,
                                )
                                if r.trigger in message.content
                            ),
                            None,
                        )
                    )

                    if result:
                        if not ratelimiter(
                            bucket=f"ar-{message.channel.id}", key="ar", rate=3, per=5
                        ):
                            code = await self.bot.embed.convert(message.author, result)
                            if delete_after := code.pop("delete_after", None):
                                await message.delete(delay=delete_after)

                            return await message.channel.send(**code)

    @Cog.listener("on_member_update")
    async def on_boost_role(self: "Notifications", before: Member, after: Member):
        if not after.guild.system_channel:
            if not before.premium_since and after.premium_since:
                for record in await self.bot.db.fetch(
                    """
                    SELECT channel_id, message
                    FROM boost
                    WHERE guild_id = $1
                    """,
                    before.guild.id,
                ):
                    if channel := self.bot.get_channel(record["channel_id"]):
                        code = await self.bot.embed.convert(
                            after.author, record["message"]
                        )
                        code.pop("delete_after", None)
                        await channel.send(**code)

    @Cog.listener("on_message")
    async def on_boost_receive(self: "Notifications", message: Message):
        if str(message.type).startswith("MessageType.premium_guild"):
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, message
                FROM boost
                WHERE guild_id = $1
                """,
                message.guild.id,
            ):
                if channel := self.bot.get_channel(record["channel_id"]):
                    code = await self.bot.embed.convert(
                        message.author, record["message"]
                    )
                    code.pop("delete_after", None)
                    await channel.send(**code)

    @Cog.listener("on_member_join")
    async def on_join_dm(self: "Notifications", member: Member):
        if message := await self.bot.db.fetchval(
            "SELECT message FROM joindm WHERE guild_id = $1", member.guild.id
        ):
            async with asyncio.Lock():
                await asyncio.sleep(30)
                with suppress(Exception):
                    code = await self.bot.embed.convert(member, message)
                    code.pop("delete_after", None)
                    code["view"] = Joindm(member.guild.name)
                    await member.send(**code)

    @Cog.listener("on_member_join")
    async def welcome_send(self: "Notifications", member: Member):
        for record in await self.bot.db.fetch(
            """
                SELECT channel_id, message
                FROM welcome
                WHERE guild_id = $1
                """,
            member.guild.id,
        ):
            if channel := self.bot.get_channel(record["channel_id"]):
                code = await self.bot.embed.convert(member, record["message"])
                await channel.send(**code)

    @Cog.listener("on_member_remove")
    async def goodbye_send(self: "Notifications", member: Member):
        for record in await self.bot.db.fetch(
            """
                SELECT channel_id, message
                FROM goodbye
                WHERE guild_id = $1
                """,
            member.guild.id,
        ):
            if channel := self.bot.get_channel(record["channel_id"]):
                code = await self.bot.embed.convert(member, record["message"])
                code.pop("delete_after", None)
                await channel.send(**code)

    @group(name="welcome", aliases=["welc", "wlc"], invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def welcome(self: "Notifications", ctx: Context) -> Message:
        return await ctx.send_help(ctx.command)

    @welcome.command(
        name="set",
        aliases=["add", "create"],
    )
    @has_permissions(manage_guild=True)
    async def welcome_set(
        self: "Notifications", ctx: Context, channel: TextChannel, *, message: str
    ) -> Message:
        """
        Set a welcome channel
        """

        await self.bot.db.execute(
            """
            INSERT INTO welcome VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, channel_id)
            DO UPDATE SET message = $3
            """,
            ctx.guild.id,
            channel.id,
            message,
        )

        return await ctx.confirm(
            f"Successfully set a welcome message to {channel.mention}!"
        )

    @welcome.command(name="remove", aliases=["delete"])
    @has_permissions(manage_guild=True)
    async def welcome_remove(
        self: "Notifications",
        ctx: Context,
        channel: TextChannel,
    ) -> Message:
        """
        Remove a welcome channel
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM welcome
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if result == "DELETE 0":
            return await ctx.alert(f"You haven't setup welcome in {channel.mention}!")

        return await ctx.confirm(
            f"Successfully removed welcome channel from {channel.mention}!"
        )

    @welcome.command(name="list", aliases=["all"])
    @has_permissions(manage_guild=True)
    async def welcome_list(
        self: "Notifications",
        ctx: Context,
    ) -> Message:
        """
        List all welcome channels
        """

        results = await self.bot.db.fetch(
            """
            SELECT *
            FROM welcome
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if not results:
            return await ctx.alert("No welcome channels found!")

        return await ctx.paginate(
            [
                f"{channel.mention}"
                for result in results
                if (channel := ctx.guild.get_channel(result["channel_id"]))
            ],
            Embed(title=f"Welcome Channels in {ctx.guild.name}"),
        )

    @welcome.command(name="test", aliases=["try", "view"])
    @has_permissions(manage_guild=True)
    async def welcome_test(
        self: "Notifications",
        ctx: Context,
        channel: TextChannel,
    ) -> Message:
        """
        Test a welcome channel
        """

        result = await self.bot.db.fetchrow(
            """
            SELECT message
            FROM welcome
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if not result:
            return await ctx.alert(f"You haven't setup welcome in {channel.mention}!")

        code = await self.bot.embed.convert(ctx.author, result["message"])
        await channel.send(**code)

    @welcome.command(name="clear", aliases=["reset"])
    @has_permissions(manage_guild=True)
    async def welcome_clear(
        self: "Notifications",
        ctx: Context,
    ) -> Message:
        """
        Clear all welcome channels
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM welcome
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.alert("You haven't setup any welcome channels!")

        return await ctx.confirm("Successfully removed all welcome channels!")

    @group(
        name="goodbye",
        aliases=[
            "leave",
        ],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def goodbye(self: "Notifications", ctx: Context) -> Message:
        return await ctx.send_help(ctx.command)

    @goodbye.command(
        name="set",
        aliases=["add", "create"],
    )
    @has_permissions(manage_guild=True)
    async def goodbye_set(
        self: "Notifications", ctx: Context, channel: TextChannel, *, message: str
    ) -> Message:
        """
        Set a goodbye channel
        """

        await self.bot.db.execute(
            """
            INSERT INTO goodbye VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, channel_id) DO
            UPDATE SET message = $3
            """,
            ctx.guild.id,
            channel.id,
            message,
        )

        return await ctx.confirm(
            f"Successfully set goodbye channel to {channel.mention}!"
        )

    @goodbye.command(name="remove", aliases=["delete"])
    @has_permissions(manage_guild=True)
    async def goodbye_remove(
        self: "Notifications",
        ctx: Context,
        channel: TextChannel,
    ) -> Message:
        """
        Remove a goodbye channel
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM goodbye
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if result == "DELETE 0":
            return await ctx.alert(f"You haven't setup goodbye in {channel.mention}!")

        return await ctx.confirm(
            f"Successfully removed goodbye channel from {channel.mention}!"
        )

    @goodbye.command(name="list", aliases=["all"])
    @has_permissions(manage_guild=True)
    async def goodbye_list(
        self: "Notifications",
        ctx: Context,
    ) -> Message:
        """
        List all goodbye channels
        """

        results = await self.bot.db.fetch(
            """
            SELECT *
            FROM goodbye
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if not results:
            return await ctx.alert("No goodbye channels found!")

        return await ctx.paginate(
            [
                f"{channel.mention}"
                for result in results
                if (channel := ctx.guild.get_channel(result["channel_id"]))
            ],
            Embed(title=f"Goodbye Channels in {ctx.guild.name}"),
        )

    @goodbye.command(name="test", aliases=["try", "view"])
    @has_permissions(manage_guild=True)
    async def goodbye_test(
        self: "Notifications",
        ctx: Context,
        channel: TextChannel,
    ) -> Message:
        """
        Test a goodbye channel
        """

        result = await self.bot.db.fetchrow(
            """
            SELECT message
            FROM goodbye
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if not result:
            return await ctx.alert(f"You haven't setup goodbye in {channel.mention}!")

        code = await self.bot.embed.convert(ctx.author, result["message"])
        code.pop("delete_after", None)
        await channel.send(**code)

    @goodbye.command(name="clear", aliases=["reset"])
    @has_permissions(manage_guild=True)
    async def goodbye_clear(
        self: "Notifications",
        ctx: Context,
    ) -> Message:
        """
        Clear all goodbye channels
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM goodbye
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.alert("You haven't setup any goodbye channels!")

        return await ctx.confirm("Successfully removed all goodbye channels!")

    @group(name="stickymessage", invoke_without_command=True)
    async def sticky_message(self, ctx: Context):
        """
        Stick a message to a channel
        """

        return await ctx.send_help(ctx.command)

    @sticky_message.command(name="clear")
    @has_permissions(administrator=True)
    async def stickymessage_clear(self, ctx: Context):
        """
        Clear all sticky messages from this server
        """

        r = await self.bot.db.execute(
            "DELETE FROM sticky_message WHERE guild_id = $1", ctx.guild.id
        )

        if r == "DELETE 0":
            return await ctx.alert("There are no sticky messages in this server")

        return await ctx.confirm("Cleared all sticky messages from this server")

    @sticky_message.command(name="list", aliases=["all"])
    @has_permissions(manage_guild=True)
    async def stickymessage_list(self, ctx: Context):
        """
        Get a list of all channels that have a sticky message
        """

        results: List[TextChannel] = list(
            filter(
                lambda c: c,
                map(
                    lambda ch: ctx.guild.get_channel(ch["channel_id"]),
                    await self.bot.db.fetch(
                        "SELECT channel_id FROM sticky_message WHERE guild_id = $1",
                        ctx.guild.id,
                    ),
                ),
            )
        )

        if not results:
            return await ctx.alert("There are no sticky messages in this channel")

        return await ctx.paginate(
            list(map(lambda c: c.mention, results)),
            Embed(title=f"Sticky messages in {ctx.guild} ({len(results)})"),
        )

    @sticky_message.command(name="remove", aliases=["rem", "rm"])
    @has_permissions(manage_guild=True)
    async def sticky_message_remove(self, ctx: Context, *, channel: TextChannel):
        """
        Remove a sticky message from a channel
        """

        message_id = await self.bot.db.fetchval(
            """
            SELECT message_id FROM sticky_message
            WHERE guild_id = $1 AND channel_id = $2 
            """,
            ctx.guild.id,
            channel.id,
        )

        if not message_id:
            return await ctx.alert("There's no sticky message for this channel")

        message = await channel.fetch_message(message_id)
        await message.delete()
        await self.bot.db.execute(
            "DELETE FROM sticky_message WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        )

        return await ctx.confirm("Removed the sticky message from this channel")

    @sticky_message.command(name="add", aliases=["set"])
    @has_permissions(manage_guild=True)
    async def sticky_message_add(
        self, ctx: Context, channel: TextChannel, *, message: str
    ):
        """
        Add a sticky message to a channel
        """

        if message_id := await self.bot.db.fetchval(
            """
            SELECT message_id FROM sticky_message
            WHERE guild_id = $1 AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        ):
            m = await channel.fetch_message(message_id)
            await m.delete()

        try:
            code = await self.bot.embed.convert(ctx.author, message)
            code.pop("delete_after", None)
            m = await channel.send(**code)
        except:
            return await ctx.alert(
                "Couldn't set that message as your sticky message. Are you sure it's a valid embed code?"
            )

        await self.bot.db.execute(
            """
            INSERT INTO sticky_message VALUES ($1,$2,$3,$4)
            ON CONFLICT (guild_id, channel_id) DO UPDATE SET 
            message_id = $3, message = $4 
            """,
            ctx.guild.id,
            channel.id,
            m.id,
            message,
        )

        return await ctx.confirm(
            f"Added a sticky message in {channel.mention} -> {m.jump_url}"
        )

    @group(invoke_without_command=True)
    async def joindm(self: "Notifications", ctx: Context) -> Message:
        """
        Send a greet message to members in dms
        """

        return await ctx.send_help(ctx.command)

    @joindm.command(name="set")
    @has_permissions(manage_guild=True)
    async def joindm_set(self: "Notifications", ctx: Context, *, message: str):
        """
        Set a message as joindm
        """

        await self.bot.db.execute(
            """
            INSERT INTO joindm VALUES ($1,$2)
            ON CONFLICT (guild_id) DO UPDATE SET
            message = $2 
            """,
            ctx.guild.id,
            message,
        )

        return await ctx.confirm(
            "Updated the joindm message. Please test it by using `joindm test`"
        )

    @joindm.command(name="disable", aliases=["remove", "dis", "rem", "rm"])
    @has_permissions(manage_guild=True)
    async def joindm_disable(self: "Notifications", ctx: Context):
        """
        Disable the joindm feature
        """

        r = await self.bot.db.execute(
            "DELETE FROM joindm WHERE guild_id = $1", ctx.guild.id
        )

        if r == "DELETE 0":
            return await ctx.alert("This feature wasn't enabled")

        return await ctx.confirm("Disabled the joindm feature")

    @joindm.command(name="test")
    @has_permissions(manage_guild=True)
    async def joindm_test(self: "Notifications", ctx: Context):
        """
        Test your joindm message
        """

        message = await self.bot.db.fetchval(
            "SELECT message FROM joindm WHERE guild_id = $1", ctx.guild.id
        )

        if not message:
            return await ctx.alert("Joidm feature wasn't enabled")

        member = ctx.author

        try:
            code = await self.bot.embed.convert(member, message)
        except:
            return await ctx.alert("There's something wrong with your embed code")

        code.pop("delete_after", None)
        code["view"] = Joindm(member.guild.name)
        await member.send(**code)

        return await ctx.confirm("Sent the joindm message")

    @hybrid_group(invoke_without_command=True)
    async def autoreact(self, ctx: Context):
        """
        Make the bot react to certain messages
        """

        return await ctx.send_help(ctx.command)

    @autoreact.command(name="add", example="skull, 💀 ☠️")
    @has_permissions(manage_guild=True)
    async def autoreact_add(self, ctx: Context, *, responder: str):
        """
        Add an autoreaction trigger to this server
        """

        match = re.match(r"([^,]*), (.*)", responder)

        if not match:
            return await ctx.alert(
                f"The trigger and reactions weren't given correctly. Please run `{ctx.clean_prefix}help autoreact add` for more information"
            )

        trigger, response = match.groups()
        reactions = [
            str(await DiscordEmoji().convert(ctx, a)) for a in response.split(" ")
        ]

        if len(reactions) == 0:
            return await ctx.alert("Response wasn't given for this autoreact")

        r = await self.bot.db.execute(
            """
            INSERT INTO autoreact VALUES ($1,$2,$3,$4)
            ON CONFLICT (guild_id, trigger) DO UPDATE SET
            reactions = $4  
            """,
            ctx.guild.id,
            trigger,
            True,
            reactions,
        )

        if r == "INSERT 1":
            return await ctx.confirm(
                f"Added autoreact with the following trigger: `{trigger}`\nStrict: `True`"
            )
        else:
            return await ctx.confirm(
                f"Updated autoreact with the following trigger: `{trigger}`"
            )

    @autoreact.command(name="list", aliases=["search"])
    @has_permissions(manage_guild=True)
    async def autoreact_list(self, ctx: Context, *, trigger: Optional[str] = None):
        """
        Look for an autoreaction or all of them
        """

        if trigger:
            result = await self.bot.db.fetchrow(
                "SELECT * FROM autoreact WHERE trigger = $1 AND guild_id = $2",
                trigger,
                ctx.guild.id,
            )

            if not result:
                return await ctx.alert("There's no autoreaction with this trigger")

            embed = Embed(
                title=f"Autoresponder: {trigger}",
                description=f"Strict: `{result.strict}`\n{', '.join(result.reactions)}",
            ).set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

            return await ctx.reply(embed=embed)
        else:
            results = await self.bot.db.fetch(
                "SELECT * FROM autoreact WHERE guild_id = $1", ctx.guild.id
            )

            if not results:
                return await ctx.alert("There are no autoreactions in this server")

            return await ctx.paginate(
                [
                    Embed(
                        title=f"Autoresponder: {r.trigger}",
                        description=f"Strict: `{r.strict}`\n{', '.join(r.reactions)}",
                    ).set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
                    for r in results
                ]
            )

    @autoreact.command(name="strict")
    @has_permissions(manage_guild=True)
    async def autoreact_strict(self, ctx: Context, *, trigger: str):
        """
        Toggle an autoreaction's strictness
        """

        strictness = await self.bot.db.fetchval(
            "SELECT strict FROM autoreact WHERE guild_id = $1 AND trigger = $2",
            ctx.guild.id,
            trigger,
        )

        if strictness is None:
            return await ctx.alert(
                "There's no autoreaction in this server that has this trigger"
            )

        args = [bool(not strictness), ctx.guild.id, trigger]

        await self.bot.db.execute(
            """
            UPDATE autoreact SET strict = $1
            WHERE guild_id = $2 AND trigger = $3
            """,
            *args,
        )

        return await ctx.confirm(
            f"Updated autoreaction's strictness to `{not strictness}`"
        )

    @autoreact.command(name="remove", aliases=["rm"])
    @has_permissions(manage_guild=True)
    async def autoreact_remove(self, ctx: Context, *, trigger: str):
        """
        Remove an existing autoreaction
        """

        r = await self.bot.db.execute(
            "DELETE FROM autoreact WHERE guild_id = $1 AND trigger = $2",
            ctx.guild.id,
            trigger,
        )

        if r == "DELETE 0":
            return await ctx.alert("There's no autoreact with this trigger")

        return await ctx.confirm(
            f"Removed the autoreact with the following trigger: `{trigger}`"
        )

    @group(aliases=["ar"], invoke_without_command=True)
    async def autoresponder(self, ctx: Context):
        """
        Make the bot reply to certain messages
        """

        return await ctx.send_help(ctx.command)

    @autoresponder.command(name="list", aliases=["search"])
    @has_permissions(manage_guild=True)
    async def autoresponder_list(self, ctx: Context, *, trigger: Optional[str] = None):
        """
        Look for an autoresponder or all of them
        """

        if trigger:
            result = await self.bot.db.fetchrow(
                "SELECT * FROM autoresponder WHERE trigger = $1 AND guild_id = $2",
                trigger,
                ctx.guild.id,
            )

            if not result:
                return await ctx.alert("There's no autoresponder with this trigger")

            embed = Embed(
                title=f"Autoresponder: {trigger}",
                description=f"Strict: `{result.strict}`\n```{result.response}```",
            ).set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

            return await ctx.reply(embed=embed)
        else:
            results = await self.bot.db.fetch(
                "SELECT * FROM autoresponder WHERE guild_id = $1", ctx.guild.id
            )

            if not results:
                return await ctx.alert("There are no autoresponders in this server")

            return await ctx.paginate(
                [
                    Embed(
                        title=f"Autoresponder: {r.trigger}",
                        description=f"Strict: `{r.strict}`\n```{r.response}```",
                    ).set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
                    for r in results
                ]
            )

    @autoresponder.command(name="add", example="hello world, hi there {user.mention}")
    @has_permissions(manage_guild=True)
    async def autoresponder_add(self, ctx: Context, *, responder: str):
        """
        Add an autoresponder to the server
        """

        try:
            trigger, response = responder.split(", ", maxsplit=1)
        except:
            return await ctx.alert(
                f"The trigger and response weren't given correctly. Please run `{ctx.clean_prefix}help ar add` for more information"
            )

        if len(response) == 0:
            return await ctx.alert("Response wasn't given for this autoresponder")

        r = await self.bot.db.execute(
            """
            INSERT INTO autoresponder VALUES ($1,$2,$3,$4)
            ON CONFLICT (guild_id, trigger) DO UPDATE SET
            response = $3 
            """,
            ctx.guild.id,
            trigger,
            response,
            True,
        )

        if r.startswith("INSERT"):
            return await ctx.confirm(
                f"Added new autoresponder with the following trigger: `{trigger}`\nStrict: `True`"
            )
        else:
            return await ctx.confirm(
                f"Updated autoresponder with the following trigger: `{trigger}`"
            )

    @autoresponder.command(name="remove", aliases=["rm"])
    @has_permissions(manage_guild=True)
    async def autoresponder_remove(self, ctx: Context, *, trigger: str):
        """
        Remove an existing autoresponder
        """

        r = await self.bot.db.execute(
            "DELETE FROM autoresponder WHERE guild_id = $1 AND trigger = $2",
            ctx.guild.id,
            trigger,
        )

        if r == "DELETE 0":
            return await ctx.alert("There's no autoresponder with this trigger")

        return await ctx.confirm(
            f"Removed the autoresponder with the following trigger: `{trigger}`"
        )

    @autoresponder.command(name="strict")
    @has_permissions(manage_guild=True)
    async def autoresponder_strict(self, ctx: Context, *, trigger: str):
        """
        Toggle an autoresponder's strictness
        """

        strictness = await self.bot.db.fetchval(
            "SELECT strict FROM autoresponder WHERE guild_id = $1 AND trigger = $2",
            ctx.guild.id,
            trigger,
        )

        if strictness is None:
            return await ctx.alert(
                "There's no autoresponder in this server that has this trigger"
            )

        args = [bool(not strictness), ctx.guild.id, trigger]

        await self.bot.db.execute(
            """
            UPDATE autoresponder SET strict = $1
            WHERE guild_id = $2 AND trigger = $3
            """,
            *args,
        )

        return await ctx.confirm(
            f"Updated autoresponder's strictness to `{not strictness}`"
        )

    @group(invoke_without_command=True)
    @has_permissions(manage_guild=True)
    async def boost(self: "Notifications", ctx: Context) -> Message:
        """
        Send a message whenever someone boosts the server
        """

        return await ctx.send_help(ctx.command)

    @boost.command(
        name="set",
        aliases=["add", "create"],
    )
    @has_permissions(manage_guild=True)
    async def boost_set(
        self: "Notifications", ctx: Context, channel: TextChannel, *, message: str
    ) -> Message:
        """
        Set a boost channel
        """

        await self.bot.db.execute(
            """
            INSERT INTO boost VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, channel_id)
            DO UPDATE SET message = $3
            """,
            ctx.guild.id,
            channel.id,
            message,
        )

        return await ctx.confirm(
            f"Successfully set a boost message to {channel.mention}!"
        )

    @boost.command(name="remove", aliases=["delete"])
    @has_permissions(manage_guild=True)
    async def boost_remove(
        self: "Notifications",
        ctx: Context,
        channel: TextChannel,
    ) -> Message:
        """
        Remove a boost channel
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM boost
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if result == "DELETE 0":
            return await ctx.alert(f"You haven't setup boost in {channel.mention}!")

        return await ctx.confirm(
            f"Successfully removed boost channel from {channel.mention}!"
        )

    @boost.command(name="list", aliases=["all"])
    @has_permissions(manage_guild=True)
    async def boost_list(
        self: "Notifications",
        ctx: Context,
    ) -> Message:
        """
        List all boost channels
        """

        results = await self.bot.db.fetch(
            """
            SELECT *
            FROM boost
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if not results:
            return await ctx.alert("No boost channels found!")

        return await ctx.paginate(
            [
                f"{channel.mention}"
                for result in results
                if (channel := ctx.guild.get_channel(result["channel_id"]))
            ],
            Embed(title=f"Boost Channels in {ctx.guild.name}"),
        )

    @boost.command(name="test", aliases=["try", "view"])
    @has_permissions(manage_guild=True)
    async def boost_test(
        self: "Notifications",
        ctx: Context,
        channel: TextChannel,
    ) -> Message:
        """
        Test a boost channel
        """

        result = await self.bot.db.fetchrow(
            """
            SELECT message
            FROM boost
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if not result:
            return await ctx.alert(f"You haven't setup boost in {channel.mention}!")

        code = await self.bot.embed.convert(ctx.author, result["message"])
        await channel.send(**code)

    @boost.command(name="clear", aliases=["reset"])
    @has_permissions(manage_guild=True)
    async def boost_clear(
        self: "Notifications",
        ctx: Context,
    ) -> Message:
        """
        Clear all boost channels
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM boost
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.alert("You haven't setup any boost channels!")

        return await ctx.confirm("Successfully removed all boost channels!")

    @group(invoke_without_command=True)
    async def notifications(self, ctx: Context):
        """
        Get notified from certain social media platforms
        """

        return await ctx.send_help(ctx.command)

    @notifications.command(name="youtube", aliases=["yt"])
    @has_permissions(manage_guild=True)
    async def notifications_youtube(
        self,
        ctx: Context,
        youtuber: Annotated[str, YouTuber],
        *,
        channel: Union[TextChannel, str],
    ):
        """
        Notify whenever someone on youtube goes live
        """

        channels = (
            await self.bot.db.fetchval(
                "SELECT channel_ids FROM notifications.youtube WHERE youtuber = $1",
                youtuber,
            )
            or []
        )

        if isinstance(channel, str):
            if channel.lower() == "none":
                await self.bot.db.execute(
                    "UPDATE notifications.youtube SET channel_ids = $1 WHERE youtuber = $2",
                    [c for c in channels if not ctx.guild.get_channel(c)],
                    youtuber,
                )
                return await ctx.confirm(
                    f"You'll stop receiving notifications from **{youtuber}** in this server"
                )
            else:
                raise ChannelNotFound(channel)

        if ch := next(
            (ctx.guild.get_channel(c) for c in channels if ctx.guild.get_channel(c)),
            None,
        ):
            return await ctx.alert(
                f"You are already receiving notifications from **{youtuber}** in {ch.mention}"
            )

        channels.append(channel.id)
        await self.bot.db.execute(
            """
            INSERT INTO notifications.youtube (youtuber, channel_ids) VALUES ($1,$2)
            ON CONFLICT (youtuber) DO UPDATE SET channel_ids = $2
            """,
            youtuber,
            channels,
        )
        return await ctx.confirm(
            f"You'll receive notifications in {channel.mention} every time **{youtuber}** goes **LIVE** on **YouTube**"
        )

    @group(invoke_without_command=True)
    async def skullboard(self, ctx: Context):
        """
        Highlight messages using reactions
        """

        return await ctx.send_help(ctx.command)

    @skullboard.command(name="enable", aliases=["e"])
    @has_permissions(manage_guild=True)
    async def skullboard_enable(self: "Notifications", ctx: Context):
        """
        Enable the skullboard feature
        """

        r = await self.bot.db.execute(
            "INSERT INTO skullboard (guild_id, emoji) VALUES ($1,$2) ON CONFLICT (guild_id) DO NOTHING",
            ctx.guild.id,
            "💀",
        )

        if r == "INSERT 0":
            return await ctx.alert("Skullboard is **already** enabled")

        return await ctx.confirm("Enabled skullboard")

    @skullboard.command(name="disable", aliases=["dis", "remove", "rem", "rm"])
    @has_permissions(manage_guild=True)
    async def skullboard_disable(self: "Notifications", ctx: Context):
        """
        Disable the skullboard feature
        """

        r = await self.bot.db.execute(
            "DELETE FROM skullboard WHERE guild_id = $1", ctx.guild.id
        )

        if r == "DELETE 0":
            return await ctx.alert("Skullboard is not enabled...")

        await self.bot.db.execute(
            "DELETE FROM skullboard_message WHERE guild_id = $1", ctx.guild.id
        )

        return await ctx.confirm("Disabled skullboard")

    @skullboard.command(name="channel")
    @has_permissions(manage_guild=True)
    async def skullboard_channel(
        self: "Notifications", ctx: Context, *, channel: TextChannel
    ):
        """
        Assign the skullboard panel channel
        """

        r = await self.bot.db.execute(
            "UPDATE skullboard SET channel_id = $1 WHERE guild_id = $2",
            channel.id,
            ctx.guild.id,
        )

        if r == "UPDATE 0":
            return await ctx.alert("Skullboard is not enabled...")

        return await ctx.confirm(f"Updated the skullboard channel to {channel.mention}")

    @skullboard.command(name="count")
    @has_permissions(manage_guild=True)
    async def skullboard_count(self: "Notifications", ctx: Context, count: int):
        """
        Assign the skullboard reaction count
        """

        if count < 1:
            return await ctx.alert("Number cannot be less than `1`")

        r = await self.bot.db.execute(
            "UPDATE skullboard SET count = $1 WHERE guild_id = $2", count, ctx.guild.id
        )

        if r == "UPDATE 0":
            return await ctx.alert("Skullboard is not enabled...")

        return await ctx.confirm(f"Updated the skullboard count to `{count}`")

    @skullboard.command(name="emoji")
    @has_permissions(manage_guild=True)
    async def skullboard_emoji(
        self: "Notifications", ctx: Context, emoji: Annotated[str, DiscordEmoji]
    ):
        """
        Assign the skullboard's required reaction
        """

        r = await self.bot.db.execute(
            "UPDATE skullboard SET emoji = $1 WHERE guild_id = $2",
            str(emoji),
            ctx.guild.id,
        )

        if r == "UPDATE 0":
            return await ctx.alert("Skullboard is not enabled...")

        return await ctx.confirm("Updated the skullboard emoji")

    @skullboard.command(name="settings")
    @has_permissions(manage_guild=True)
    async def skullboard_settings(self: "Notifications", ctx: Context):
        """
        Check the skullboard's configuration
        """

        result = await self.bot.db.fetchrow(
            "SELECT * FROM skullboard WHERE guild_id = $1", ctx.guild.id
        )

        if not result:
            return await ctx.alert("Skullboard is **not** enabled")

        condition: bool = all([result["channel_id"], result["count"], result["emoji"]])
        embed = (
            Embed(
                color=getattr(Color, "green" if condition else "red")(),
                description="Functional" if condition else "Not Functional",
            )
            .set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
            .add_field(
                name="Channel",
                value=(
                    ctx.guild.get_channel(result["channel_id"]).mention
                    if ctx.guild.get_channel(result["channel_id"])
                    else "N/A"
                ),
            )
            .add_field(name="Emoji", value=result["emoji"])
            .add_field(name="Count", value=result["count"] or "N/A")
        )

        return await ctx.reply(embed=embed)


async def setup(bot: Scare) -> None:
    return await bot.add_cog(Notifications(bot))
