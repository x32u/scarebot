from io import BytesIO
from typing import List, Optional

import discord
from discord.ext import commands

from structure.scare import Scare
from structure.utilities import Context


class LogsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Copy ID", custom_id="id")
    async def obj_id(self, interaction: discord.Interaction, _):
        return await interaction.response.send_message(
            interaction.message.embeds[0].footer.text, ephemeral=True
        )


class Logs(commands.Cog):
    def __init__(self, bot: Scare):
        self.bot = bot
        self.bot.add_view(LogsView())

    @commands.Cog.listener("on_audit_log_entry_create")
    async def automod_events(self, entry: discord.AuditLogEntry):
        if entry.action.name in ["automod_rule_create", "automod_rule_delete"]:
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "automod",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(
                            color=self.bot.color,
                            title=entry.action.name.replace("_", " ").title(),
                            description=f"Automod Rule **{entry.target.name}** {entry.action.name.split('_')[-1]}d by **{entry.user}** (`{entry.user.id}`)",
                            timestamp=entry.created_at,
                        )
                        .set_author(
                            name=str(entry.user), icon_url=entry.user.display_avatar.url
                        )
                        .set_footer(text=f"Rule id: {entry.target.id}")
                    )
                    return await channel.send(silent=True, embed=embed, view=LogsView())
        elif entry.action.name == "automod_rule_update":
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "automod",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(
                            color=self.bot.color,
                            description=f"**{entry.target.name}** (`{entry.target.id}`)",
                            timestamp=entry.created_at,
                        )
                        .set_author(
                            name=str(entry.user), icon_url=entry.user.display_avatar.url
                        )
                        .set_footer(text=f"Rule id: {entry.target.id}")
                    )

                    if getattr(entry.changes.before, "name", None):
                        if entry.changes.before.name != entry.changes.after.name:
                            embed.title = "Automod Rule name update"
                            embed.add_field(
                                name="Before",
                                value=entry.changes.before.name,
                                inline=False,
                            ).add_field(
                                name="After",
                                value=entry.changes.after.name,
                                inline=False,
                            )
                            return await channel.send(
                                silent=True, embed=embed, view=LogsView()
                            )
                    elif getattr(entry.changes.before, "enabled", None):
                        if entry.changes.before.enabled != entry.changes.after.enabled:
                            embed.title = (
                                "Automod Rule disabled"
                                if entry.changes.before.enabled
                                else "Automod Rule enabled"
                            )
                            return await channel.send(
                                silent=True, embed=embed, view=LogsView()
                            )

    @commands.Cog.listener("on_audit_log_entry_create")
    async def role_events(self, entry: discord.AuditLogEntry):
        if entry.action.name in ["role_create", "role_delete"]:
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "roles",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(
                            color=self.bot.color,
                            title=entry.action.name.replace("_", " ").title(),
                            description=f"<@&{entry.target.id}> (`{entry.target.id}`) {entry.action.name.split('_')[1]}d by **{entry.user}** (`{entry.user.id}`)",
                            timestamp=entry.created_at,
                        )
                        .set_author(
                            name=str(entry.user), icon_url=entry.user.display_avatar.url
                        )
                        .set_footer(text=f"Role id: {entry.target.id}")
                    )
                    return await channel.send(silent=True, embed=embed, view=LogsView())
        elif entry.action.name == "role_update":
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "roles",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(color=self.bot.color, timestamp=entry.created_at)
                        .set_author(
                            name=str(entry.user), icon_url=entry.user.display_avatar.url
                        )
                        .set_footer(text=f"Role id: {entry.target.id}")
                    )

                    if getattr(entry.changes.before, "name", None):
                        if entry.changes.before.name != entry.changes.after.name:
                            embed.title = "Role name update"
                            embed.add_field(
                                name="Before",
                                value=entry.changes.before.name,
                                inline=False,
                            ).add_field(
                                name="After",
                                value=entry.changes.after.name,
                                inline=False,
                            )
                    elif str(getattr(entry.changes.before, "color", "#000000")) != str(
                        getattr(entry.changes.after, "color", "#000000")
                    ):
                        embed.title = "Role color update"
                        embed.add_field(
                            name="Before",
                            value=str(
                                getattr(entry.changes.before, "color", "#000000")
                            ),
                            inline=False,
                        ).add_field(
                            name="After",
                            value=str(getattr(entry.changes.after, "color", "#000000")),
                            inline=False,
                        )

    @commands.Cog.listener("on_audit_log_entry_create")
    async def thread_events(self, entry: discord.AuditLogEntry):
        if entry.action.name in ["thread_create", "thread_delete"]:
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "channels",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(
                            color=self.bot.color,
                            title=entry.action.name.replace("_", " ").title(),
                            description=f"<#{entry.target.id}> (`{entry.target.id}`) {entry.action.name.split('_')[1]}d by **{entry.user}** (`{entry.user.id}`)",
                            timestamp=entry.created_at,
                        )
                        .set_author(
                            name=str(entry.user), icon_url=entry.user.display_avatar.url
                        )
                        .set_footer(text=f"Thread id: {entry.target.id}")
                    )
                    return await channel.send(silent=True, embed=embed, view=LogsView())
            elif entry.action.name == "thread_update":
                if channel_id := await self.bot.db.fetchval(
                    """
                    SELECT channel_id FROM logs
                    WHERE guild_id = $1 
                    AND log_type = $2
                    """,
                    entry.guild.id,
                    "channels",
                ):
                    if channel := entry.guild.get_channel(channel_id):
                        embed = (
                            discord.Embed(
                                color=self.bot.color, timestamp=entry.created_at
                            )
                            .set_author(
                                name=str(entry.user),
                                icon_url=entry.user.display_avatar.url,
                            )
                            .set_footer(text=f"Thread id: {entry.target.id}")
                        )

                        if getattr(entry.changes.before, "name", None):
                            if entry.changes.before.name != entry.changes.after.name:
                                embed.title = "Thread name update"
                                embed.add_field(
                                    name="Before",
                                    value=entry.changes.before.name,
                                    inline=False,
                                ).add_field(
                                    name="After",
                                    value=entry.changes.after.name,
                                    inline=False,
                                )

                                return await channel.send(
                                    silent=True, embed=embed, view=LogsView()
                                )
                        elif hasattr(entry.changes.before, "locked"):
                            if (
                                entry.changes.before.locked
                                != entry.changes.after.locked
                            ):
                                embed.title = "Thread lock update"
                                embed.add_field(
                                    name="Before",
                                    value=entry.changes.before.locked,
                                    inline=False,
                                ).add_field(
                                    name="After",
                                    value=entry.changes.after.locked,
                                    inline=False,
                                )

                                return await channel.send(
                                    silent=True, embed=embed, view=LogsView()
                                )

    @commands.Cog.listener("on_audit_log_entry_create")
    async def channel_events(self, entry: discord.AuditLogEntry):
        if entry.action.name in ["channel_create", "channel_delete"]:
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "channels",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(
                            color=self.bot.color,
                            title=entry.action.name.replace("_", " ").title(),
                            description=f"<#{entry.target.id}> (`{entry.target.id}`) {entry.action.name.split('_')[1]}d by **{entry.user}** (`{entry.user.id}`)",
                            timestamp=entry.created_at,
                        )
                        .set_author(
                            name=str(entry.user), icon_url=entry.user.display_avatar.url
                        )
                        .set_footer(text=f"Channel id: {entry.target.id}")
                    )
                    return await channel.send(silent=True, embed=embed, view=LogsView())
        elif entry.action.name == "channel_update":
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "channels",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(color=self.bot.color, timestamp=entry.created_at)
                        .set_author(
                            name=str(entry.user), icon_url=entry.user.display_avatar.url
                        )
                        .set_footer(text=f"Channel id: {entry.target.id}")
                    )

                    if getattr(entry.changes.before, "name", None):
                        if entry.changes.before.name != entry.changes.after.name:
                            embed.title = "Channel name update"
                            embed.add_field(
                                name="Before",
                                value=entry.changes.before.name,
                                inline=False,
                            ).add_field(
                                name="After",
                                value=entry.changes.after.name,
                                inline=False,
                            )

                            return await channel.send(
                                silent=True, embed=embed, view=LogsView()
                            )

    @commands.Cog.listener("on_audit_log_entry_create")
    async def member_events(self, entry: discord.AuditLogEntry):
        if entry.action.name == "member_update":
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "members",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(
                            color=self.bot.color,
                            description=f"Moderator: **{entry.user}** (`{entry.user.id}`)",
                            timestamp=entry.created_at,
                        )
                        .set_author(
                            name=str(entry.target),
                            icon_url=entry.target.display_avatar.url,
                        )
                        .set_footer(text=f"User id: {entry.target.id}")
                    )
                    if getattr(
                        entry.changes.before, "timed_out_until", None
                    ) != getattr(entry.changes.after, "timed_out_until", None):
                        if not entry.changes.after.timed_out_until:
                            embed.title = "Removed timeout"
                        else:
                            embed.title = "Timed out Member"
                            embed.add_field(
                                name="Timed out until",
                                value=discord.utils.format_dt(
                                    entry.changes.after.timed_out_until
                                ),
                            )

                        return await channel.send(
                            silent=True, embed=embed, view=LogsView()
                        )

                    elif getattr(entry.changes.before, "nick", None) != getattr(
                        entry.changes.after, "nick", None
                    ):
                        if not entry.changes.before.nick:
                            embed.title = "Configured Nickname"
                            embed.add_field(
                                name="Nickname",
                                value=entry.changes.after.nick,
                                inline=False,
                            )
                        elif not entry.changes.after.nick:
                            embed.title = "Removed nickname"
                            embed.add_field(
                                name="Nickname",
                                value=entry.changes.before.nick,
                                inline=False,
                            )
                        else:
                            embed.title = "Nickname Update"
                            embed.add_field(
                                name="Before",
                                value=entry.changes.before.nick,
                                inline=False,
                            ).add_field(
                                name="After",
                                value=entry.changes.after.nick,
                                inline=False,
                            )

                        return await channel.send(
                            silent=True, embed=embed, view=LogsView()
                        )

        elif entry.action.name == "member_role_update":
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "members",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(
                            color=self.bot.color,
                            title=entry.action.name.replace("_", " ").title(),
                            timestamp=entry.created_at,
                        )
                        .set_author(
                            name=entry.target.__str__(),
                            icon_url=entry.target.display_avatar.url,
                        )
                        .add_field(
                            name="Moderator",
                            value=f"**{entry.user}** (`{entry.user.id}`)",
                            inline=False,
                        )
                        .add_field(
                            name="Victim",
                            value=f"**{entry.target}** (`{entry.target.id}`)",
                            inline=False,
                        )
                        .set_footer(text=f"User id: {entry.target.id}")
                    )

                    removed = [
                        role
                        for role in entry.changes.before.roles
                        if not role in entry.changes.after.roles
                    ]

                    added = [
                        role
                        for role in entry.changes.after.roles
                        if not role in entry.changes.before.roles
                    ]

                    rem = f"... +{len(removed)-5}" if len(removed) > 5 else ""
                    add = f"... +{len(added)-5}" if len(added) > 5 else ""

                    if removed:
                        embed.add_field(
                            name=f"Removed roles ({len(removed)})",
                            value=", ".join(list(map(lambda r: r.mention, removed[:5])))
                            + rem,
                            inline=False,
                        )

                    if added:
                        embed.add_field(
                            name=f"Added roles ({len(added)})",
                            value=", ".join(list(map(lambda r: r.mention, added[:5])))
                            + add,
                            inline=False,
                        )

                    return await channel.send(silent=True, embed=embed, view=LogsView())

    @commands.Cog.listener("on_audit_log_entry_create")
    async def ban_kick(self, entry: discord.AuditLogEntry):
        if entry.action.name in ["ban", "kick", "unban"]:
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "members",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(
                            color=self.bot.color,
                            title=f"Member {entry.action.name.capitalize()}",
                            timestamp=entry.created_at,
                        )
                        .set_author(
                            name=entry.target.__str__(),
                            icon_url=entry.target.display_avatar.url,
                        )
                        .add_field(
                            name="Moderator",
                            value=f"**{entry.user}** (`{entry.user.id}`)",
                            inline=False,
                        )
                        .add_field(
                            name="Victim",
                            value=f"**{entry.target}** (`{entry.target.id}`)",
                            inline=False,
                        )
                        .add_field(
                            name="Reason",
                            value=entry.reason or "No reason",
                            inline=False,
                        )
                        .set_footer(text=f"User id: {entry.target.id}")
                    )

                    return await channel.send(silent=True, embed=embed, view=LogsView())
        elif entry.action.name == "bot_add":
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                entry.guild.id,
                "members",
            ):
                if channel := entry.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(
                            color=self.bot.color,
                            title="Bot added to the server",
                            description=f"**{entry.user}** (`{entry.user.id}`) added **{entry.target}** (`{entry.target.id}`) in the server",
                        )
                        .set_author(
                            name=str(entry.user), icon_url=entry.user.display_avatar.url
                        )
                        .set_footer(text=f"Bot id: {entry.target.id}")
                    )
                    return await channel.send(silent=True, embed=embed, view=LogsView())

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if channel_id := await self.bot.db.fetchval(
            """
            SELECT channel_id FROM logs
            WHERE guild_id = $1 
            AND log_type = $2
            """,
            member.guild.id,
            "members",
        ):
            if channel := member.guild.get_channel(channel_id):
                embed = (
                    discord.Embed(
                        color=self.bot.color,
                        title="Member left",
                        description=f"{member} (`{member.id}`) left the server. This server has `{member.guild.member_count:,}` members now!",
                        timestamp=discord.utils.utcnow(),
                    )
                    .set_author(name=str(member), icon_url=member.display_avatar.url)
                    .set_footer(text=f"User id: {member.id}")
                    .add_field(
                        name="Joined At",
                        value=discord.utils.format_dt(member.joined_at),
                        inline=False,
                    )
                    .add_field(
                        name="Created at",
                        value=discord.utils.format_dt(member.created_at),
                        inline=False,
                    )
                )

                return await channel.send(silent=True, embed=embed, view=LogsView())

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if channel_id := await self.bot.db.fetchval(
            """
            SELECT channel_id FROM logs
            WHERE guild_id = $1 
            AND log_type = $2
            """,
            member.guild.id,
            "members",
        ):
            if channel := member.guild.get_channel(channel_id):
                embed = (
                    discord.Embed(
                        color=self.bot.color,
                        title="Member Joined",
                        description=f"{member} (`{member.id}`) joined the server. This server has `{member.guild.member_count:,}` members now!",
                        timestamp=discord.utils.utcnow(),
                    )
                    .set_author(name=str(member), icon_url=member.display_avatar.url)
                    .set_footer(text=f"User id: {member.id}")
                    .add_field(
                        name="Created at",
                        value=discord.utils.format_dt(member.created_at),
                    )
                )

                return await channel.send(silent=True, embed=embed, view=LogsView())

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.guild:
            if before != after:
                if before.content != "" and after.content != "":
                    if channel_id := await self.bot.db.fetchval(
                        """
                        SELECT channel_id FROM logs
                        WHERE guild_id = $1 
                        AND log_type = $2
                        """,
                        after.guild.id,
                        "messages",
                    ):
                        if channel := after.guild.get_channel(channel_id):
                            embed = (
                                discord.Embed(
                                    color=self.bot.color,
                                    title=f"Message edited in #{after.channel}",
                                    timestamp=discord.utils.utcnow(),
                                )
                                .set_author(
                                    name=after.author.__str__(),
                                    icon_url=after.author.display_avatar.url,
                                )
                                .set_footer(text=f"Message id: {after.id}")
                                .add_field(
                                    name="Before", value=before.content, inline=False
                                )
                                .add_field(
                                    name="After", value=after.content, inline=False
                                )
                            )

                            return await channel.send(
                                silent=True, embed=embed, view=LogsView()
                            )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild:
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                message.guild.id,
                "messages",
            ):
                if channel := message.guild.get_channel(channel_id):
                    embed = (
                        discord.Embed(
                            color=self.bot.color,
                            title=f"Message Delete in #{message.channel}",
                            description=(
                                message.content
                                if message.content != ""
                                else "This message doesn't have content"
                            ),
                            timestamp=message.created_at,
                        )
                        .set_author(
                            name=message.author.__str__(),
                            icon_url=message.author.display_avatar.url,
                        )
                        .set_footer(text=f"User id: {message.author.id}")
                    )
                    return await channel.send(silent=True, embed=embed, view=LogsView())

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[discord.Message]):
        message = messages[0]
        if message.guild:
            if channel_id := await self.bot.db.fetchval(
                """
                SELECT channel_id FROM logs
                WHERE guild_id = $1 
                AND log_type = $2
                """,
                message.guild.id,
                "messages",
            ):
                if channel := message.guild.get_channel(channel_id):
                    embed = discord.Embed(
                        color=self.bot.color,
                        title=f"Bulk Message Delete in #{message.channel}",
                        timestamp=discord.utils.utcnow(),
                    ).set_author(name=message.guild.name, icon_url=message.guild.icon)
                    buffer = BytesIO(
                        bytes(
                            "\n".join(
                                f"{m.author} - {m.clean_content if m.clean_content != '' else 'Attachment, Embed or Sticker'}"
                                for m in messages
                            ),
                            "utf-8",
                        )
                    )
                    return await channel.send(
                        silent=True,
                        embed=embed,
                        file=discord.File(buffer, filename=f"{message.channel}.txt"),
                    )

    @commands.hybrid_group(invoke_without_command=True)
    async def logs(self, ctx: Context):
        """
        Track events happening in your server
        """

        return await ctx.send_help(ctx.command)

    @logs.command(name="settings")
    @commands.has_permissions(manage_guild=True)
    async def logs_settings(self, ctx: Context):
        """
        Check the logs feature settings in this server
        """

        results = await self.bot.db.fetch(
            "SELECT * FROM logs WHERE guild_id = $1", ctx.guild.id
        )

        if not results:
            return await ctx.alert("There are no logs configured in this server")

        embed = discord.Embed(
            title=f"Logs settings",
            description="\n".join(
                [f"{result.log_type}: <#{result.channel_id}>" for result in results]
            ),
        ).set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
        return await ctx.reply(embed=embed)

    @logs.command(name="members")
    @commands.has_permissions(manage_guild=True)
    async def logs_members(
        self, ctx: Context, *, channel: Optional[discord.TextChannel] = None
    ):
        """
        Track member related events happening in the server
        """

        if not channel:
            r = await self.bot.db.execute(
                """
                DELETE FROM logs WHERE
                guild_id = $1 AND
                log_type = $2 
                """,
                ctx.guild.id,
                "members",
            )

            if r == "DELETE 0":
                return await ctx.alert("Member logs weren't enabled")

            return await ctx.confirm("Disabled member logging")

        await self.bot.db.execute(
            """
            INSERT INTO logs VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, log_type)
            DO UPDATE SET channel_id = $3   
            """,
            ctx.guild.id,
            "members",
            channel.id,
        )

        return await ctx.confirm(f"Sending member related logs to {channel.mention}")

    @logs.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def logs_channel(
        self, ctx: Context, *, channel: Optional[discord.TextChannel] = None
    ):
        """
        Track channel related events happening in the server
        """

        if not channel:
            r = await self.bot.db.execute(
                """
                DELETE FROM logs WHERE
                guild_id = $1 AND
                log_type = $2 
                """,
                ctx.guild.id,
                "channels",
            )

            if r == "DELETE 0":
                return await ctx.alert("Channel logs weren't enabled")

            return await ctx.confirm("Disabled channel logging")

        await self.bot.db.execute(
            """
            INSERT INTO logs VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, log_type)
            DO UPDATE SET channel_id = $3   
            """,
            ctx.guild.id,
            "channels",
            channel.id,
        )

        return await ctx.confirm(f"Sending channel related logs to {channel.mention}")

    @logs.command(name="role")
    @commands.has_permissions(manage_guild=True)
    async def logs_role(
        self, ctx: Context, *, channel: Optional[discord.TextChannel] = None
    ):
        """
        Track role related events happening in the server
        """

        if not channel:
            r = await self.bot.db.execute(
                """
                DELETE FROM logs WHERE
                guild_id = $1 AND
                log_type = $2 
                """,
                ctx.guild.id,
                "roles",
            )

            if r == "DELETE 0":
                return await ctx.alert("Role logs weren't enabled")

            return await ctx.confirm("Disabled role logging")

        await self.bot.db.execute(
            """
            INSERT INTO logs VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, log_type)
            DO UPDATE SET channel_id = $3   
            """,
            ctx.guild.id,
            "roles",
            channel.id,
        )

        return await ctx.confirm(f"Sending role related logs to {channel.mention}")

    @logs.command(name="automod")
    @commands.has_permissions(manage_guild=True)
    async def logs_automod(
        self, ctx: Context, *, channel: Optional[discord.TextChannel] = None
    ):
        """
        Track automod related events happening in the server
        """

        if not channel:
            r = await self.bot.db.execute(
                """
                DELETE FROM logs WHERE
                guild_id = $1 AND
                log_type = $2 
                """,
                ctx.guild.id,
                "automod",
            )

            if r == "DELETE 0":
                return await ctx.alert("Automod logs weren't enabled")

            return await ctx.confirm("Disabled automod logging")

        await self.bot.db.execute(
            """
            INSERT INTO logs VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, log_type)
            DO UPDATE SET channel_id = $3   
            """,
            ctx.guild.id,
            "automod",
            channel.id,
        )

        return await ctx.confirm(f"Sending automod related logs to {channel.mention}")

    @logs.command(name="message")
    @commands.has_permissions(manage_guild=True)
    async def logs_message(
        self, ctx: Context, *, channel: Optional[discord.TextChannel] = None
    ):
        """
        Track message related events happening in the server
        """

        if not channel:
            r = await self.bot.db.execute(
                """
                DELETE FROM logs WHERE
                guild_id = $1 AND
                log_type = $2 
                """,
                ctx.guild.id,
                "messages",
            )

            if r == "DELETE 0":
                return await ctx.alert("Message logs weren't enabled")

            return await ctx.confirm("Disabled message logging")

        await self.bot.db.execute(
            """
            INSERT INTO logs VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, log_type)
            DO UPDATE SET channel_id = $3   
            """,
            ctx.guild.id,
            "messages",
            channel.id,
        )

        return await ctx.confirm(f"Sending message related logs to {channel.mention}")


async def setup(bot: Scare) -> None:
    return await bot.add_cog(Logs(bot))
