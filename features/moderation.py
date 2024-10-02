import asyncio
import datetime
import re
from asyncio import Lock, gather
from collections import defaultdict
from copy import copy
from typing import Annotated, List, Literal, Optional, Union

import humanize
from discord import ButtonStyle, Color, Embed, Forbidden, Interaction
from discord import Member as DefaultMember
from discord import (
    Message,
    NotFound,
    PartialEmoji,
    PermissionOverwrite,
    Role,
    TextChannel,
    User,
)
from discord.ext.commands import (
    Cog,
    CurrentChannel,
    antinuke_owner,
    bot_has_permissions,
    command,
    group,
    has_permissions,
    param,
)
from discord.ui import Button, View, button
from discord.utils import utcnow

from structure.scare import Scare
from structure.managers import Context
from structure.utilities import AssignableRole, Channel
from structure.utilities import Color as ValidColor
from structure.utilities import DiscordEmoji, Member, Time


class Confirm(View):

    def __init__(
        self: "Confirm",
        author: Member,
        victim: Member,
        command: Literal["ban", "kick"],
        reason: str,
    ):
        self.author = author
        self.victim = victim
        self.command_name = command
        self.reason = reason
        super().__init__()

    async def notify(self: "Confirm"):
        action = (
            f"{self.command_name}ned"
            if self.command_name == "ban"
            else f"{self.command_name}ed"
        )
        embed = (
            Embed(
                color=Color.red(),
                title=action.capitalize(),
                description=f"You have been {action} by **{self.author}** in **{self.author.guild}**",
                timestamp=datetime.datetime.now(),
            )
            .add_field(name="Reason", value=self.reason.split(" - ")[1])
            .set_thumbnail(url=self.author.guild.icon)
            .set_footer(
                text="for more about this punishment, please contact a staff member"
            )
        )

        try:
            await self.victim.send(embed=embed)
            return None
        except:
            return "Couldn't DM member"

    async def interaction_check(self: "Confirm", interaction: Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "You cannot interact with this message", ephemeral=True
            )

        return interaction.user.id == self.author.id

    @button(label="Yes", style=ButtonStyle.green)
    async def positive(self: "Confirm", interaction: Interaction, button: Button):
        if self.command_name == "ban":
            await self.victim.ban(reason=self.reason)
        else:
            await self.victim.kick(reason=self.reason)

        notify = await self.notify()
        return await interaction.response.edit_message(
            content=f"👍 {f' - {notify}' if notify else ''}", view=None, embed=None
        )

    @button(label="No", style=ButtonStyle.red)
    async def negative(self: "Confirm", interaction: Interaction, button: Button):
        return await interaction.response.edit_message(
            content=f"Cancelled the ban for {self.victim.mention}",
            embed=None,
            view=None,
        )


class Moderation(Cog):
    def __init__(self, bot: Scare):
        self.bot: Scare = bot
        self.lock: Lock = Lock()
        self.locks = defaultdict(Lock)

    @Cog.listener("on_member_update")
    async def on_role_restore(self, before: DefaultMember, after: DefaultMember):
        if before.roles != after.roles:
            await self.bot.db.execute(
                """
                INSERT INTO role_restore VALUES ($1,$2,$3)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                roles = $3
                """,
                before.guild.id,
                before.id,
                list(map(lambda r: r.id, before.roles)),
            )

    @Cog.listener()
    async def on_member_join(self, member: DefaultMember):
        if await self.bot.db.fetchrow(
            "SELECT * FROM jail WHERE user_id = $1 AND guild_id = $2",
            member.id,
            member.guild.id,
        ):
            if role_id := self.bot.db.fetchval(
                "SELECT role_id FROM moderation WHERE guild_id = $1", member.guild.id
            ):
                if role := member.guild.get_role(role_id):
                    await member.add_roles(role, reason="Jailed member")

    @Cog.listener()
    async def on_member_remove(self, member: DefaultMember):
        await self.bot.db.execute(
            """
            INSERT INTO role_restore VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, user_id) DO UPDATE SET
            roles = $3
            """,
            member.guild.id,
            member.id,
            list(map(lambda r: r.id, member.roles)),
        )

    @Cog.listener("on_member_update")
    async def on_forcenick(self, before: DefaultMember, after: DefaultMember):
        if before.guild.me.guild_permissions.manage_nicknames:
            if str(before.nick) != str(after.nick):
                if nickname := await self.bot.db.fetchval(
                    "SELECT nickname FROM forcenick WHERE guild_id = $1 AND user_id = $2",
                    before.guild.id,
                    before.id,
                ):
                    if str(after.nick) != nickname:
                        if (
                            after.top_role < after.guild.me.top_role
                            and after.id != after.guild.owner_id
                        ):
                            await after.edit(nick=nickname, reason="Force nickname")

    async def notify(
        self: "Moderation",
        author: DefaultMember,
        command: Literal["ban", "kick", "jail"],
        victim: DefaultMember,
        reason: str,
    ):
        action = f"{command}ned" if command == "ban" else f"{command}ed"
        embed = (
            Embed(
                color=Color.red(),
                title=action.capitalize(),
                description=f"You have been {action} by **{author}** in **{author.guild}**",
                timestamp=datetime.datetime.now(),
            )
            .add_field(name="Reason", value=reason.split(" - ")[1])
            .set_thumbnail(url=author.guild.icon)
            .set_footer(
                text="for more about this punishment, please contact a staff member"
            )
        )

        try:
            await victim.send(embed=embed)
            return None
        except:
            return "Couldn't DM member"

    async def entry(
        self: "Moderation",
        ctx: Union[Context, Interaction],
        target: Union[DefaultMember, User, Role, TextChannel],
        action: str,
        reason: str = "N/A",
    ):
        try:
            result = await self.bot.db.fetchval(
                """
                SELECT channel_id FROM moderation
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )

            if not (channel := self.bot.get_channel(result)):
                return

            async with self.lock:
                case = (
                    await self.bot.db.fetchval(
                        "SELECT count FROM cases WHERE guild_id = $1", ctx.guild.id
                    )
                    or 1
                )

                e = Embed(
                    description=(
                        f"## Case #{case:,} - {action.title()}\n"
                        f"### Target: {target} `( {target.id} )`\n"
                        f"### Moderator: {ctx.author.name} `( {ctx.author.id} )`"
                    ),
                    timestamp=utcnow(),
                )

                e.set_author(name="Logged Entry", icon_url=ctx.author.avatar)

                e.set_footer(text=f"Reason: {reason}")
                await channel.send(embed=e)

                await self.bot.db.execute(
                    """
                    INSERT INTO cases (
                        guild_id,
                        count
                    ) VALUES ($1, $2)
                    ON CONFLICT (guild_id) 
                    DO UPDATE SET count = $2
                    """,
                    ctx.guild.id,
                    case + 1,
                )

        except Exception as e:
            print(e)

    @command(name="botpurge", aliases=["bc", "botclear", "botclean"])
    @has_permissions(manage_messages=True)
    async def botpurge(self: "Moderation", ctx: Context, amount: int = 15) -> Message:
        """
        Clear messages from bots
        """
        await ctx.channel.purge(limit=amount, check=lambda msg: msg.author.bot)
        await ctx.message.delete()
        await ctx.send("purged {} messages from bots".format(amount), delete_after=1)

    @command()
    @has_permissions(manage_channels=True)
    async def lock(self, ctx: Context, channel: TextChannel = CurrentChannel):
        """
        lock a channel
        """

        overwrite = channel.overwrites_for(ctx.guild.default_role)

        if overwrite.send_messages == False:
            return await ctx.alert("Channel is already locked")

        overwrite.send_messages = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        return await ctx.send(f"👍")

    @command()
    @has_permissions(manage_channels=True)
    async def unlock(
        self: "Moderation", ctx: Context, channel: TextChannel = CurrentChannel
    ):
        """
        unlock a channel
        """

        overwrite = channel.overwrites_for(ctx.guild.default_role)

        if overwrite.send_messages != False:
            return await ctx.alert("This channel is not locked")

        overwrite.send_messages = True
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        return await ctx.send(f"👍")

    @command()
    @has_permissions(manage_messages=True)
    async def warn(
        self: "Moderation",
        ctx: Context,
        member: Annotated[DefaultMember, Member],
        *,
        reason: Optional[str] = "N/A",
    ):
        """
        Warn a member
        """

        await self.bot.db.execute(
            "INSERT INTO warns VALUES ($1,$2,$3,$4)",
            member.id,
            ctx.guild.id,
            reason,
            utcnow(),
        )

        return await ctx.confirm(f"{member.mention} has been warned - **{reason}**")

    @command()
    @has_permissions(manage_messages=True)
    async def clearwarns(
        self: "Moderation", ctx: Context, *, member: Annotated[DefaultMember, Member]
    ):
        """
        Clear someone's warns
        """

        r = await self.bot.db.execute(
            """
            DELETE FROM warns
            WHERE user_id = $1
            AND guild_id = $2
            """,
            member.id,
            ctx.guild.id,
        )

        if r == "DELETE 0":
            return await ctx.alert("This member has no warns")

        return await ctx.confirm("Cleared all warns")

    @command()
    @has_permissions(manage_messages=True)
    async def warns(self: "Moderation", ctx: Context, *, member: DefaultMember):
        """
        Check a member's warns
        """

        results = await self.bot.db.fetch(
            """
            SELECT * FROM warns
            WHERE user_id = $1
            AND guild_id = $2
            ORDER BY date ASC
            """,
            member.id,
            ctx.guild.id,
        )

        if not results:
            return await ctx.alert("This member has no warns")

        return await ctx.paginate(
            [
                f"{result.date.strftime('%Y-%m-%d')} - {result.reason}"
                for result in results
            ],
            Embed(title=f"{member.display_name}'s warns"),
        )

    @group(aliases=["c", "clear"], invoke_without_command=True)
    @has_permissions(manage_messages=True)
    async def purge(self: "Moderation", ctx: Context, amount: int = 15) -> Message:
        """
        Clear a certain amount of messages
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                check=lambda m: not m.pinned,
                reason=f"Purged by {ctx.author.name}",
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="user", aliases=["member"])
    @has_permissions(manage_messages=True)
    async def purge_user(
        self: "Moderation", ctx: Context, member: Member, amount: int = 15
    ) -> Message:
        """
        Clear messages from a specific user
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=lambda m: m.author == member and not m.pinned,
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="bot", aliases=["bots"])
    @has_permissions(manage_messages=True)
    async def purge_bot(self: "Moderation", ctx: Context, amount: int = 15) -> Message:
        """
        Clear messages from bots
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=lambda m: m.author.bot and not m.pinned,
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="links", aliases=["embeds"])
    @has_permissions(manage_messages=True)
    async def purge_embeds(
        self: "Moderation", ctx: Context, amount: int = 15
    ) -> Message:
        """
        Clear messages containing links or embeds
        """
        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        def check(m: Message):
            match = re.search(
                r"(http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])",
                m.content,
            )

            return m.embeds or match

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=check,
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="attachments", aliases=["files", "images"])
    @has_permissions(manage_messages=True)
    async def purge_attachments(
        self: "Moderation", ctx: Context, amount: int = 15
    ) -> Message:
        """
        Clear messages containing attachments
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=lambda m: m.attachments,
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="humans", aliases=["members"])
    @has_permissions(manage_messages=True)
    async def purge_humans(
        self: "Moderation", ctx: Context, amount: int = 15
    ) -> Message:
        """
        Clear messages from humans
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=lambda m: not m.author.bot,
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="invites", aliases=["inv", "invite"])
    @has_permissions(manage_messages=True)
    async def purge_invites(
        self: "Moderation", ctx: Context, amount: int = 15
    ) -> Message:
        """
        Clear messages containing invites
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=lambda m: re.search(self.bot.invite_regex, m.content),
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="reactions", aliases=["reacts", "emoji"])
    @has_permissions(manage_messages=True)
    async def purge_reactions(
        self: "Moderation", ctx: Context, amount: int = 15
    ) -> Message:
        """
        Clear messages containing reactions
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=ctx.author.name,
                check=lambda m: m.emojis,
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="stickers", aliases=["sticker"])
    @has_permissions(manage_messages=True)
    async def purge_stickers(
        self: "Moderation", ctx: Context, amount: int = 15
    ) -> Message:
        """
        Clear messages containing stickers
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=lambda m: m.stickers,
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="mentions", aliases=["mention"])
    @has_permissions(manage_messages=True)
    async def purge_mentions(
        self: "Moderation", ctx: Context, amount: int = 15
    ) -> Message:
        """
        Clear messages containing mentions
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=lambda m: m.mentions,
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="after", aliases=["since"])
    @has_permissions(manage_messages=True)
    async def purge_after(
        self: "Moderation", ctx: Context, message: Message
    ) -> Message:
        """
        Clear messages after a specific message
        """

        if message.channel != ctx.channel:
            return await ctx.send("The message must be in this channel!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=300,
                after=message,
                before=ctx.message,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=lambda m: m.mentions,
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="between", aliases=["range"])
    @has_permissions(manage_messages=True)
    async def purge_between(
        self: "Moderation", ctx: Context, start: Message, end: Message
    ) -> Message:
        """
        Clear messages between two specific messages
        """

        if start.channel != ctx.channel or end.channel != ctx.channel:
            return await ctx.send("The messages must be in this channel!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=300,
                after=start,
                before=end,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=lambda m: m.mentions,
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="startswith", aliases=["start"])
    @has_permissions(manage_messages=True)
    async def purge_startswith(
        self: "Moderation", ctx: Context, string: str, amount: int = 15
    ) -> Message:
        """
        Clear messages starting with a specific string
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=ctx.author.name,
                check=lambda m: m.content
                and m.content.lower().startswith(string.lower()),
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="endswith", aliases=["end"])
    @has_permissions(manage_messages=True)
    async def purge_endswith(
        self: "Moderation", ctx: Context, string: str, amount: int = 15
    ) -> Message:
        """
        Clear messages ending with a specific string
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=ctx.author.name,
                check=lambda m: m.content
                and m.content.lower().endswith(string.lower()),
            )
            await ctx.send("👍", delete_after=2)

    @purge.command(name="contains", aliases=["contain"])
    @has_permissions(manage_messages=True)
    async def purge_contains(
        self: "Moderation", ctx: Context, string: str, amount: int = 15
    ) -> Message:
        """
        Clear messages containing a specific string
        """

        if amount > 1000:
            return await ctx.alert("You can only delete 1000 messages at a time!")

        async with self.locks[ctx.channel.id]:
            await ctx.channel.purge(
                limit=amount,
                bulk=True,
                reason=f"Purged by {ctx.author.name}",
                check=lambda m: m.content and string.lower() in m.content.lower(),
            )
            await ctx.send("👍", delete_after=2)

    @purge.before_invoke
    async def before_purge(self, ctx: Context):
        await ctx.message.delete()

    @command()
    @has_permissions(ban_members=True)
    @bot_has_permissions(ban_members=True)
    async def banreason(self: "Moderation", ctx: Context, *, member: User):
        """
        Check the reason why this member was banned
        """

        bans = [entry async for entry in ctx.guild.bans()]
        entry = next((b for b in bans if b.user.id == member.id), None)

        if not entry:
            return await ctx.alert("This member is **not** banned from this server")

        embed = Embed(
            color=self.bot.color,
            description=f"> **{member}** was banned - {entry.reason}",
        )
        return await ctx.reply(embed=embed)

    @command()
    @has_permissions(ban_members=True)
    @bot_has_permissions(ban_members=True)
    async def unban(self: "Moderation", ctx: Context, *, member: User):
        """
        Unban a member from the guild
        """

        try:
            await ctx.guild.unban(member)
            return await ctx.send("👍")
        except NotFound:
            return await ctx.alert("This member is **not** banned")

    @command(aliases=["massunban"])
    @antinuke_owner()
    @bot_has_permissions(ban_members=True)
    async def unbanall(self: "Moderation", ctx: Context):
        """
        Unban all members in the server
        """

        async with self.locks[f"unban-{ctx.guild.id}"]:
            users = [entry.user async for entry in ctx.guild.bans()]
            m = await ctx.neutral(f"Unbanning `{len(users):,}` members...")
            await asyncio.gather(
                *[
                    ctx.guild.unban(m, reason=f"Massunban by {ctx.author}")
                    for m in users
                ]
            )
            embed = m.embeds[0]
            embed.description = f"Unbanned `{len(users):,}`** members in **{humanize.precisedelta(utcnow() - m.created_at, format='%0.0f')}"
            return await m.edit(embed=embed)

    @command(aliases=["forcenick", "fn"])
    @has_permissions(manage_guild=True)
    async def forcenickname(
        self: "Moderation",
        ctx: Context,
        member: Annotated[DefaultMember, Member],
        *,
        nick: str,
    ):
        """
        Force nickname a member
        """

        if nick.lower() == "none":
            r = await self.bot.db.execute(
                "DELETE FROM forcenick WHERE user_id = $1 AND guild_id = $2",
                member.id,
                ctx.guild.id,
            )

            if r == "DELETE 0":
                return await ctx.alert(
                    "This member does not have a force nickname assigned"
                )

            await member.edit(nick=None)
            return await ctx.confirm(f"Removed {member.mention}'s nickname")
        else:
            await self.bot.db.execute(
                """
                INSERT INTO forcenick VALUES ($1,$2,$3)
                ON CONFLICT (guild_id, user_id) 
                DO UPDATE SET nickname = $3 
                """,
                ctx.guild.id,
                member.id,
                nick,
            )
            await member.edit(nick=nick, reason="Forcenickname")
            return await ctx.confirm(f"Force nicknamed {member.mention} to `{nick}`")

    @command(aliases=["nick"])
    @has_permissions(manage_nicknames=True)
    async def nickname(
        self: "Moderation",
        ctx: Context,
        member: Annotated[DefaultMember, Member],
        *,
        nickname: str,
    ):
        """
        Change a member's nickname
        """

        if nickname == "none":
            await member.edit(nick=None)
            return await ctx.confirm(f"Removed **{member.name}'s** nickname")
        else:
            await member.edit(nick=nickname)
            return await ctx.confirm(
                f"Changed **{member.name}'s** nickname to {nickname}"
            )

    @command(aliases=["banish"])
    @has_permissions(ban_members=True)
    async def ban(
        self: "Moderation",
        ctx: Context,
        member: Union[DefaultMember, User],
        *,
        reason: str = "N/A",
    ):
        """
        Ban a member from your guild
        """

        reason = ctx.author.name + f" - {reason}"
        notify = None

        if isinstance(member, DefaultMember):
            member = await Member().convert(ctx, str(member.id))

            if member.premium_since:
                embed = Embed(
                    color=self.bot.color,
                    description=f"This member is a **server booster?** Are you sure you want to **ban** them?",
                )
                view = Confirm(ctx.author, member, "ban", reason)

                return await ctx.reply(embed=embed, view=view)

            else:
                notify = await self.notify(ctx.author, ctx.command.name, member, reason)

        await ctx.guild.ban(member, reason=reason)

        await self.entry(ctx, member, "Ban", reason)
        return await ctx.send(f"👍 {f'- {notify}' if notify else ''}")

    @command(aliases=["untimeout", "unt"])
    @has_permissions(moderate_members=True)
    async def unmute(
        self: "Moderation",
        ctx: Context,
        member: Annotated[DefaultMember, Member],
        *,
        reason: Optional[str] = "N/A",
    ):
        """
        Remove a member's timeout
        """

        if not member.is_timed_out():
            return await ctx.alert("This member not timed out")

        await member.timeout(None, reason=f"Untimed out by {ctx.author} - {reason}")

        await self.entry(ctx, member, "Untimeout", reason)
        return await ctx.reply("👍")

    @command(aliases=["timeout", "tm"])
    @has_permissions(moderate_members=True)
    async def mute(
        self: "Moderation",
        ctx: Context,
        member: Annotated[DefaultMember, Member],
        time: Time = "5m",
        *,
        reason: Optional[str] = "N/A",
    ):
        """
        Timeout a member
        """

        if member.is_timed_out():
            return await ctx.alert("This member is timed out")

        await member.timeout(
            datetime.timedelta(seconds=time),
            reason=f"Timed out by {ctx.author} - {reason}",
        )

        await self.entry(ctx, member, "Timeout", reason)
        return await ctx.reply("👍")

    @command(name="kick")
    @has_permissions(kick_members=True)
    async def kick(
        self: "Moderation",
        ctx: Context,
        member: Annotated[DefaultMember, Member],
        *,
        reason: str = "N/A",
    ):
        """
        Kick a member from your guild
        """

        reason = ctx.author.name + f" - {reason}"

        if member.premium_since:
            embed = Embed(
                color=self.bot.color,
                description=f"This member is a **server booster?** Are you sure you want to **kick** them?",
            )
            view = Confirm(ctx.author, member, "kick", reason)

            return await ctx.reply(embed=embed, view=view)

        await ctx.guild.kick(member, reason=reason)

        notify = await self.notify(ctx.author, ctx.command.name, member, reason)

        await self.entry(ctx, member, "Kick", reason)
        return await ctx.send(f"👍 {f'- {notify}' if notify else ''}")

    @command(
        name="nuke",
    )
    @antinuke_owner()
    async def nuke(
        self: "Moderation", 
        ctx: Context,
    ):
        """
        Clone the channel and delete old channel
        """

        async def channel_nuke(interaction: Interaction):
            try:
                await interaction.channel.delete()
            except:
                return await interaction.alert(
                    f"Unable to nuke {interaction.channel.mention}!"
                )
    
            chnl = await interaction.channel.clone()
            await chnl.edit(position=interaction.channel.position)
            args = [chnl.id, interaction.channel.id]
            await self.bot.db.execute(
                "UPDATE welcome SET channel_id = $1 WHERE channel_id = $2", *args
            )
            await self.bot.db.execute(
                "UPDATE goodbye SET channel_id = $1 WHERE channel_id = $2", *args
            )
            await self.bot.db.execute(
                "UPDATE boost SET channel_id = $1 WHERE channel_id = $2", *args
            )
            await self.entry(interaction, interaction.channel, "Nuke", "N/A")
            return await chnl.send("first")
        
        return await ctx.confirmation(
            "Are you sure you want to **nuke** this channel?",
            channel_nuke
        )

    @group(name="role", aliases=["r"], invoke_without_command=True)
    @has_permissions(manage_roles=True)
    async def role(self: "Moderation", ctx: Context, user: Member, *, role: str):
        """
        Manage roles
        """

        roles = [await AssignableRole().convert(ctx, r) for r in role.split(", ")][:7]
        managed = []

        async def do_role(r: AssignableRole):
            if r in user.roles:
                await user.remove_roles(r)
                managed.append(f"-{r.mention}")
            else:
                await user.add_roles(r)
                managed.append(f"+{r.mention}")

        tasks = [do_role(r) for r in roles]
        await gather(*tasks)
        if len(managed) == 1:
            return await ctx.confirm(
                f">>> {ctx.author.mention}: {'Added' if managed[0].startswith('+') else 'Removed'} {managed[0][1:]} {'to' if managed[0].startswith('+') else 'from'} {user.mention}"
            )

        return await ctx.confirm(
            f">>> {ctx.author.mention}:  Modified **{user}**'s roles: {' '.join(managed)}"
        )

    @role.command(name="restore")
    @has_permissions(manage_roles=True)
    async def role_restore(
        self, ctx: Context, *, member: Annotated[DefaultMember, Member]
    ):
        """
        Restore a member's roles
        """

        role_ids: List[int] = await self.bot.db.fetchval(
            """
            SELECT roles FROM role_restore 
            WHERE guild_id = $1 AND user_id = $2
            """,
            ctx.guild.id,
            member.id,
        )

        roles: List[Role] = list(
            filter(
                lambda r: r and r.is_assignable() and not r in member.roles,
                map(lambda x: ctx.guild.get_role(x), role_ids),
            )
        )

        if not roles:
            return await ctx.alert("There are no roles to restore")

        roles.extend(member.roles)
        await member.edit(roles=roles, reason=f"Roles restored by {ctx.author}")

        return await ctx.confirm(f"Restored {member.mention}'s roles")

    @role.command(name="all")
    @has_permissions(manage_roles=True)
    async def role_all(self, ctx: Context, *, role: Annotated[Role, AssignableRole]):
        """
        Add a role to all members
        """

        users = [
            m
            for m in ctx.guild.members
            if m.is_punishable() and not m.bot and not role in m.roles
        ]

        if not users:
            return await ctx.alert("All members have this role")

        message = await ctx.neutral(f"Giving {role.mention} to `{len(users)}` users")
        await asyncio.gather(*[m.add_roles(role) for m in users])
        reskin = await ctx.get_reskin()
        return await message.edit(
            embed=Embed(
                color=reskin.color if reskin else self.bot.color,
                description=f"> {ctx.author.mention}: Finished this task in **{humanize.precisedelta(utcnow() - message.created_at, format='%0.0f')}**",
            )
        )

    @role.command(name="create", aliases=["make"])
    @has_permissions(manage_roles=True)
    async def role_create(self: "Moderation", ctx: Context, *, name: str):
        """
        Creates a role
        """

        if len(name) < 2:
            return await ctx.alert("The role name must be at least 2 characters long!")

        role = await ctx.guild.create_role(name=name, reason=ctx.author.name)
        return await ctx.confirm(f"Successfully created {role.mention}!")

    @role.command(
        name="delete",
    )
    @has_permissions(manage_roles=True)
    async def role_delete(
        self: "Moderation", ctx: Context, *, role: Annotated[Role, AssignableRole]
    ):
        """
        Deletes a role
        """

        if role == ctx.guild.default_role:
            return await ctx.alert("Unable to delete the default role")

        await role.delete(reason=ctx.author.name)

        return await ctx.confirm(f"Successfully deleted {role.mention}!")

    @role.command(name="rename", aliases=["edit"])
    @has_permissions(manage_roles=True)
    async def role_rename(
        self: "Moderation",
        ctx: Context,
        role: Annotated[Role, AssignableRole],
        *,
        name: str,
    ):
        """
        Renames a role
        """

        if len(name) < 2:
            return await ctx.alert("The role name must be at least 2 characters long!")

        await role.edit(name=name, reason=ctx.author.name)
        return await ctx.confirm(f"Successfully renamed {role.mention} to `{name}`!")

    @role.command(name="color", aliases=["colour"])
    @has_permissions(manage_roles=True)
    async def role_color(
        self: "Moderation",
        ctx: Context,
        role: Annotated[Role, AssignableRole],
        color: Annotated[Color, ValidColor],
    ):
        """
        Changes the color of a role
        """

        await role.edit(color=color, reason=ctx.author.name)
        return await ctx.confirm(
            f"Successfully edited {role.mention} color to `{color}`!"
        )

    @role.command(name="position", aliases=["pos"])
    @has_permissions(manage_roles=True)
    async def role_position(
        self: "Moderation",
        ctx: Context,
        role: Annotated[Role, AssignableRole],
        position: int,
    ):
        """
        Changes the position of a role
        """

        await role.edit(position=position, reason=ctx.author.name)

        return await ctx.confirm(
            f"Successfully edited {role.mention} position to `{position}`!"
        )

    @role.command(name="hoist", aliases=["display"])
    @has_permissions(manage_roles=True)
    async def role_hoist(
        self: "Moderation",
        ctx: Context,
        role: Annotated[Role, AssignableRole],
        hoist: bool,
    ):
        """
        Changes the display of a role
        """

        await role.edit(hoist=hoist, reason=ctx.author.name)
        return await ctx.confirm(
            f"Successfully edited {role.mention} hoist to `{hoist}`!"
        )

    @role.command(name="mentionable", aliases=["mention"])
    @has_permissions(manage_roles=True)
    async def role_mentionable(
        self: "Moderation",
        ctx: Context,
        role: Annotated[Role, AssignableRole],
        mentionable: bool,
    ):
        """
        Changes the mentionability of a role
        """

        await role.edit(mentionable=mentionable, reason=ctx.author.name)

        return await ctx.confirm(
            f"Successfully edited {role.mention} mentionability to `{mentionable}`!"
        )

    @role.command(name="icon", aliases=["image"])
    @has_permissions(manage_roles=True)
    async def role_icon(
        self: "Moderation",
        ctx: Context,
        role: Annotated[Role, AssignableRole],
        icon: Union[DiscordEmoji, Literal["remove", "clear", "reset", "off"]],
    ):
        """
        Changes the icon of a role
        """

        if isinstance(icon, PartialEmoji):
            if icon.url:
                buffer = await self.bot.session.get(icon.url)
            else:
                buffer = str(icon)
        else:
            buffer = None

        try:
            await role.edit(display_icon=buffer, reason=ctx.author.name)
        except Forbidden:
            return await ctx.alert(
                f"{ctx.guild.name} needs more boosts to perform this action!"
            )

        return await ctx.confirm(f"Successfully edited {role.mention} icon!")

    @command(name="setup", aliases=["setmod", "setme"])
    @has_permissions(administrator=True)
    async def setup(self: "Moderation", ctx: Context):
        """
        Setup moderation
        """

        if await self.bot.db.fetch(
            """
            SELECT * FROM moderation
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        ):
            return await ctx.alert("You already have moderation setup!")

        role = await ctx.guild.create_role(name="jail", reason="mod setup")

        for channel in ctx.guild.channels:
            await channel.set_permissions(role, view_channel=False)

        category = await ctx.guild.create_category(
            name="moderation", reason="mod setup"
        )

        channel = await category.create_text_channel(
            name="jail",
            reason="mod setup",
            overwrites={
                role: PermissionOverwrite(view_channel=True),
                ctx.guild.default_role: PermissionOverwrite(view_channel=False),
            },
        )

        logs = await category.create_text_channel(
            name="logs",
            reason="mod setup",
            overwrites={
                role: PermissionOverwrite(view_channel=False),
                ctx.guild.default_role: PermissionOverwrite(view_channel=False),
            },
        )

        await self.bot.db.execute(
            """
            INSERT INTO moderation (
                guild_id,
                role_id,
                channel_id,
                jail_id,
                category_id
            ) VALUES ($1, $2, $3, $4, $5)
            """,
            ctx.guild.id,
            role.id,
            logs.id,
            channel.id,
            category.id,
        )

        return await ctx.send("👍")

    @command(name="reset", aliases=["unsetup"])
    @has_permissions(administrator=True)
    async def reset(self: "Moderation", ctx: Context):
        """
        Reset moderation
        """

        if channel_ids := await self.bot.db.fetchrow(
            """
            DELETE FROM moderation
            WHERE guild_id = $1
            RETURNING channel_id, role_id, jail_id, category_id
            """,
            ctx.guild.id,
        ):
            for channel in (
                channel
                for channel_id in channel_ids
                if (channel := ctx.guild.get_channel(channel_id))
            ):
                await channel.delete()

            return await ctx.send("👍")
        else:
            return await ctx.alert("Moderation hasn't been setup yet!")

    @command(name="jail")
    @has_permissions(moderate_members=True)
    async def jail(
        self: "Moderation", ctx: Context, member: Member, *, reason: str = "N/A"
    ):
        """
        Jail a member
        """

        if not (
            data := await self.bot.db.fetchrow(
                """
                SELECT * FROM moderation
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
        ):
            return await ctx.alert("You don't have moderation configured yet!")

        reason = ctx.author.name + f" - {reason}"
        try:
            role = ctx.guild.get_role(data["role_id"])
            member_roles = [r for r in member.roles[1:] if r.is_assignable()]
            r = await self.bot.db.execute(
                """
                INSERT INTO jail VALUES ($1,$2,$3)
                ON CONFLICT (guild_id, user_id)
                DO NOTHING 
                """,
                ctx.guild.id,
                member.id,
                list(map(lambda r: r.id, member_roles)),
            )

            if r == "INSERT 0":
                return await ctx.alert("This member is **already** jailed")

            roles = [r for r in member.roles if not r in member.roles]
            roles.append(role)
            await member.edit(roles=roles, reason=ctx.author.name + f" - {reason}")
        except:
            await self.bot.db.execute(
                "DELETE FROM jail WHERE user_id = $1 AND guild_id = $2",
                member.id,
                ctx.guild.id,
            )
            return await ctx.alert(f"Unable to jail {member.mention}!")

        notify = await self.notify(ctx.author, ctx.command.name, member, reason)
        await self.entry(ctx, "Jail", "N/A")

        if channel := ctx.guild.get_channel(data["jail_id"]):
            await channel.send(
                f"{member.mention} you have been jailed by {ctx.author.mention}. Contact the staff members for any disputes about the punishment"
            )

        return await ctx.send(f"👍 {f'- {notify}' if notify else ''}")

    @command(name="unjail")
    @has_permissions(moderate_members=True)
    async def unjail(
        self: "Moderation", ctx: Context, member: Member, *, reason: str = "N/A"
    ):
        """
        Unjail a member
        """

        if not (
            data := await self.bot.db.fetchrow(
                """
                SELECT * FROM moderation
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
        ):
            return await ctx.alert("You don't have moderation configured yet!")

        try:
            roles = await self.bot.db.fetchval(
                """
                SELECT roles FROM jail
                WHERE guild_id = $1
                AND user_id = $2
                """,
                ctx.guild.id,
                member.id,
            )

            if not roles:
                return await ctx.alert("This member is **not** jailed")

            member_roles = [r for r in member.roles if not r.is_assignable()]
            member_roles.extend(
                list(
                    filter(
                        lambda ro: ro and ro.is_assignable(),
                        map(lambda r: ctx.guild.get_role(r), roles),
                    )
                )
            )

            await member.edit(
                roles=member_roles, reason=ctx.author.name + f" - {reason}"
            )

            await self.bot.db.execute(
                """
                DELETE FROM jail 
                WHERE guild_id = $1 
                AND user_id = $2
                """,
                ctx.guild.id,
                member.id,
            )
        except:
            return await ctx.alert(f"Unable to unjail {member.mention}!")

        await self.entry(ctx, "Jail", "N/A")
        return await ctx.send("👍")

    @command(aliases=["imute"])
    @has_permissions(moderate_members=True)
    async def imagemute(
        self, ctx: Context, member: Member, channel: Optional[Channel] = CurrentChannel
    ):
        """
        image mute someone from the channel
        """

        if channel == "all":
            for c in ctx.guild.text_channels:
                perms = c.overwrites_for(member)
                perms.attach_files = False
                await c.set_permissions(member, overwrite=perms)
            return await ctx.send(f":thumbsup:")
        else:
            perms = channel.overwrites_for(member)
            perms.attach_files = False
            await channel.set_permissions(member, overwrite=perms)
            await ctx.send(f":thumbsup:")

    @command(aliases=["iunmute"])
    @has_permissions(moderate_members=True)
    async def imageunmute(
        self, ctx: Context, member: Member, channel: Optional[Channel] = CurrentChannel
    ):
        """
        image unmute someone from the channel
        """

        if channel == "all":
            for c in ctx.guild.text_channels:
                perms = c.overwrites_for(member)
                perms.attach_files = None
                await c.set_permissions(member, overwrite=perms)

            return await ctx.send(f":thumbsup:")
        else:
            perms = channel.overwrites_for(member)
            perms.attach_files = None
            await channel.set_permissions(member, overwrite=perms)
            return await ctx.send(f":thumbsup:")


async def setup(bot: Scare) -> None:
    await bot.add_cog(Moderation(bot))
