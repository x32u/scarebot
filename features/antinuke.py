import asyncio
import json
from collections import defaultdict
from typing import List, Literal, Optional, Union

import discord
import humanize
from discord.ext import commands

from structure.scare import Scare
from structure.managers import Context


class Antinuke(commands.Cog):
    def __init__(self, bot: Scare):
        self.bot = bot
        self.locks = defaultdict(asyncio.Lock)

    def dangerous_role(self, target: Union[discord.AuditLogDiff, discord.Role]) -> bool:
        if not hasattr(target, "permissions"):
            return False

        return any(
            [
                target.permissions.administrator,
                target.permissions.manage_guild,
                target.permissions.manage_channels,
                target.permissions.manage_events,
                target.permissions.manage_messages,
                target.permissions.manage_nicknames,
                target.permissions.manage_threads,
                target.permissions.manage_webhooks,
                target.permissions.manage_expressions,
                target.permissions.create_expressions,
                target.permissions.kick_members,
                target.permissions.ban_members,
                target.permissions.mention_everyone,
                target.permissions.move_members,
                target.permissions.mute_members,
                target.permissions.deafen_members,
            ]
        )

    async def punish(self, entry: discord.AuditLogEntry):
        reason = f"Antinuke: {entry.action.name.replace('_', ' ').title()}"
        if entry.user.bot:
            await entry.user.kick(reason=reason)

        match entry.punishment:
            case "ban":
                await entry.user.ban(reason=reason)
            case "kick":
                await entry.user.kick(reason=reason)
            case "strip":
                await entry.user.edit(
                    roles=[r for r in entry.user.roles if not r.is_assignable()],
                    reason=reason,
                )
            case _:
                pass

    async def send_report(self: "Antinuke", entry: discord.AuditLogEntry, reason: str):
        embed = (
            discord.Embed(
                color=self.bot.color,
                title=entry.action.name.replace("_", " ").title(),
                timestamp=entry.created_at,
            )
            .set_author(name=entry.guild.name, icon_url=entry.guild.icon)
            .add_field(
                name="User", value=f"**{entry.user}** (`{entry.user.id}`)", inline=False
            )
            .add_field(name="Reason", value=reason, inline=False)
            .set_footer(
                text=f"User was punished in {humanize.precisedelta(entry.punished_at)}"
            )
        )
        if channel := entry.logs:
            return await channel.send(embed=embed)
        else:
            try:
                await entry.guild.owner.send(embed=embed)
            except:
                pass

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        actions = [
            "ban",
            "kick",
            "role_delete",
            "role_create",
            "channel_delete",
            "channel_create",
            "webhook_create",
            "webhook_delete",
            "sticker_create",
            "sticker_delete",
            "emoji_create",
            "emoji_delete",
            "member_role_update",
            "role_update",
        ]

        if (
            entry.action.name not in actions
            or not isinstance(entry.user, discord.Member)
            or entry.user_id == self.bot.user.id
            or not entry.user.is_punishable()
            or not entry.guild.has_antinuke_permissions()
        ):
            return

        result = await self.bot.db.fetchrow(
            "SELECT * FROM antinuke WHERE guild_id = $1", entry.guild.id
        )
        if not result or not (
            modules := json.loads(result["modules"]).get(entry.action.name)
        ):
            return

        owners, whitelist = result["owners"], result["whitelisted"]
        if entry.user.id in owners or entry.user.id in whitelist:
            return

        if entry.action.name.endswith("create"):
            await entry.target.delete()

        async with self.locks[f"{entry.guild.id}-{entry.user.id}"]:
            member = entry.guild.get_member(entry.user.id)
            if not member or not member.is_dangerous():
                return

            entry.punishment = modules["punishment"]
            entry.logs = entry.guild.get_channel(result["logs"])
            entry.punished_at = discord.utils.utcnow() - entry.created_at

            if not entry.action.name.endswith("update"):
                await self.punish(entry=entry)
                return await self.send_report(
                    entry=entry, reason=entry.action.name.replace("_", " ").title()
                )

            self.bot.dispatch(entry.action.name, entry=entry)

    @commands.Cog.listener()
    async def on_member_role_update(self, entry: discord.AuditLogEntry):
        if hasattr(entry.changes.after, "roles"):
            roles = [
                r
                for r in entry.changes.after.roles
                if self.dangerous_role(r) and r.is_assignable()
            ]
            if roles:
                await self.punish(entry=entry)
                await entry.target.remove_roles(*roles, reason="Restoring given roles")
                return await self.send_report(
                    entry=entry, reason="Gave malicious roles to a member"
                )

    @commands.Cog.listener()
    async def on_role_update(self, entry: discord.AuditLogEntry):
        if not self.dangerous_role(entry.changes.before) and self.dangerous_role(
            entry.changes.after
        ):
            await entry.target.edit(
                permissions=entry.changes.before.permissions, reason="Restoring role"
            )

        elif hasattr(entry.changes.after, "mentionable"):
            if not entry.changes.before.mentionable and entry.changes.after.mentionable:
                await entry.target.edit(
                    mentionable=entry.changes.before.mentionable,
                    reason="Restoring role",
                )

        await self.punish(entry)
        return await self.send_report(entry=entry, reason="Maliciously edited a role")

    @commands.group(aliases=["an"], invoke_without_command=True)
    async def antinuke(self, ctx: Context):
        """
        Protect your server against nuking
        """

        return await ctx.send_help(ctx.command)

    @antinuke.command(name="setup")
    @commands.server_owner()
    async def antinuke_setup(self, ctx: Context):
        """
        Configure the antinuke
        """

        await self.bot.db.execute(
            """
      INSERT INTO antinuke (guild_id) VALUES ($1) 
      ON CONFLICT (guild_id) DO NOTHING
      """,
            ctx.guild.id,
        )

        return await ctx.confirm("Antinuke has been configured succesfully")

    @antinuke.command(name="disable")
    @commands.server_owner()
    async def antinuke_disable(self, ctx: Context):
        """
        Disable the antinuke feature
        """

        await self.bot.db.execute(
            "DELETE FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )
        return await ctx.confirm("Antinuke has been disabled succesfully")

    @antinuke.command(name="logs")
    @commands.antinuke_owner()
    async def antinuke_logs(
        self, ctx: Context, channel: Union[discord.TextChannel, str]
    ):
        """
        Configure your antinuke logs
        """

        if isinstance(channel, str):
            if channel.lower() == "none":
                await self.bot.db.execute(
                    "UPDATE antinuke SET logs = $1 WHERE guild_id = $2",
                    None,
                    ctx.guild.id,
                )
                return await ctx.confirm("Removed antinuke logs")
            else:
                raise commands.ChannelNotFound(channel)
        else:
            await self.bot.db.execute(
                "UPDATE antinuke SET logs = $1 WHERE guild_id = $2",
                channel.id,
                ctx.guild.id,
            )
            await ctx.confirm(
                f"Antinuke log channel was configured succesfully to {channel.mention}"
            )

    @antinuke.command(name="whitelisted")
    @commands.antinuke_owner()
    async def antinuke_whitelisted(self: "Antinuke", ctx: Context):
        """
        Get a list of all whitelisted people
        """

        whitelisted = await self.bot.db.fetchval(
            "SELECT whitelisted FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if not whitelisted:
            return await ctx.alert("There are no whitelisted members!")

        return await ctx.paginate(
            [
                f"<@{i}> (`{i}`)"
                for i in sorted(
                    whitelisted, key=lambda m: ctx.guild.get_member(m) is not None
                )
            ],
            discord.Embed(title=f"Antinuke whitelisted ({len(whitelisted)})"),
        )

    @antinuke.command(name="owners")
    @commands.antinuke_owner()
    async def antinuke_owners(self: "Antinuke", ctx: Context):
        """
        Get a list of all antinuke owners
        """

        owners = (
            await self.bot.db.fetchval(
                "SELECT owners FROM antinuke WHERE guild_id = $1", ctx.guild.id
            )
            or []
        )
        owners.append(ctx.guild.owner_id)

        return await ctx.paginate(
            [
                f"<@{i}> (`{i}`)"
                for i in sorted(
                    owners[::-1], key=lambda m: ctx.guild.get_member(m) is not None
                )
            ],
            discord.Embed(title=f"Antinuke owners ({len(owners)})").set_footer(
                text="These members are also immune against the antinuke punishments"
            ),
        )

    @antinuke.command(name="owner")
    @commands.server_owner()
    async def antinuke_owner(self, ctx: Context, member: discord.Member):
        """
        Add someone as an antinuke owner (they can manage all antinuke commands)
        """

        owners = await self.bot.db.fetchval(
            "SELECT owners FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if owners is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        if member.id in owners:
            owners.remove(member.id)
            m = f"**{member}** is **not** an antinuke owner anymore"
        else:
            owners.append(member.id)
            m = f"**{member}** became an antinuke owner"

        await self.bot.db.execute(
            "UPDATE antinuke SET owners = $1 WHERE guild_id = $2", owners, ctx.guild.id
        )
        return await ctx.confirm(m)

    @antinuke.command(name="whitelist")
    @commands.antinuke_owner()
    async def antinuke_whitelist(
        self, ctx: Context, member: Union[discord.Member, discord.User]
    ):
        """
        Whitelist someone from the antinuke
        """

        whitelisted: Optional[List[int]] = await self.bot.db.fetchval(
            "SELECT whitelisted FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if whitelisted is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        if member.id in whitelisted:
            whitelisted.remove(member.id)
            m = f"**{member}** is **not** antinuke whitelisted anymore"
        else:
            whitelisted.append(member.id)
            m = f"**{member}** is whitelisted from antinuke"

        await self.bot.db.execute(
            "UPDATE antinuke SET whitelisted = $1 WHERE guild_id = $2",
            whitelisted,
            ctx.guild.id,
        )
        return await ctx.confirm(m)

    @antinuke.command(name="settings")
    @commands.antinuke_owner()
    async def antinuke_settings(self, ctx: Context):
        """
        Check the antinuke feature settings
        """

        result = await self.bot.db.fetchrow(
            "SELECT * FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if not result:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules: dict = json.loads(result["modules"])
        channel = ctx.guild.get_channel(result["logs"])

        if len(list(modules.keys())) == 0 and not channel:
            return await ctx.alert("There are no antinuke settings that are enabled")

        embed = discord.Embed(
            color=self.bot.color,
            title="Antinuke Settings",
            description="\n".join(
                [
                    f"<:check:1238173217760219250> {a.replace('_', ' ').title()} - {p.get('punishment')}"
                    for a, p in modules.items()
                ]
            ),
        ).set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

        if channel:
            embed.add_field(
                name="Logs channel", value=f"{channel.mention} (`{channel.id}`)"
            )

        return await ctx.send(embed=embed)

    @antinuke.group(name="botadd", invoke_without_command=True)
    async def antinuke_botadd(self, ctx: Context):
        """
        Protect your server against unknown bots
        """

        return await ctx.send_help(ctx.command)

    @antinuke_botadd.command(name="enable", aliases=["e"])
    @commands.antinuke_owner()
    async def antinuke_botadd_enable(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip"]
    ):
        """
        Enable the protection against bots
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        modules[ctx.command.parent.name] = {"punishment": punishment}

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

        return await ctx.confirm(
            f"Antinuke **{ctx.command.parent.name}** is now enabled - `{punishment}`"
        )

    @antinuke_botadd.command(name="disable", aliases=["dis"])
    @commands.antinuke_owner()
    async def antinuke_botadd_disable(self, ctx: Context):
        """
        Disable the protection against kicks
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)

        if modules.get(ctx.command.parent.name):
            modules.pop(ctx.command.parent.name)

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

        return await ctx.confirm(
            f"Antinuke **{ctx.command.parent.name}** is now disabled"
        )

    @antinuke.group(name="kick", invoke_without_command=True)
    async def antinuke_kick(self, ctx: Context):
        """
        Protect your server against kicks
        """

        return await ctx.send_help(ctx.command)

    @antinuke_kick.command(name="enable", aliases=["e"])
    @commands.antinuke_owner()
    async def antinuke_kick_enable(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip"]
    ):
        """
        Enable the protection against kicks
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        modules[ctx.command.parent.name] = {"punishment": punishment}

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

        return await ctx.confirm(
            f"Antinuke **{ctx.command.parent.name}** is now enabled - `{punishment}`"
        )

    @antinuke_kick.command(name="disable", aliases=["dis"])
    @commands.antinuke_owner()
    async def antinuke_kick_disable(self, ctx: Context):
        """
        Disable the protection against kicks
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)

        if modules.get(ctx.command.parent.name):
            modules.pop(ctx.command.parent.name)

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

        return await ctx.confirm(
            f"Antinuke **{ctx.command.parent.name}** is now disabled"
        )

    @antinuke.group(name="ban", invoke_without_command=True)
    async def antinuke_ban(self, ctx: Context):
        """
        Protect your server against bans
        """

        return await ctx.send_help(ctx.command)

    @antinuke_ban.command(name="enable", aliases=["e"])
    @commands.antinuke_owner()
    async def antinuke_ban_enable(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip"]
    ):
        """
        Enable the protection against bans
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        modules[ctx.command.parent.name] = {"punishment": punishment}

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

        return await ctx.confirm(
            f"Antinuke **{ctx.command.parent.name}** is now enabled - `{punishment}`"
        )

    @antinuke_ban.command(name="disable", aliases=["dis"])
    @commands.antinuke_owner()
    async def antinuke_ban_disable(self, ctx: Context):
        """
        Disable the protection against bans
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)

        if modules.get(ctx.command.parent.name):
            modules.pop(ctx.command.parent.name)

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

        return await ctx.confirm(
            f"Antinuke **{ctx.command.parent.name}** is now disabled"
        )

    @antinuke.group(name="channel", invoke_without_command=True)
    async def antinuke_channel(self, ctx: Context):
        """
        Protect your server against channel deletions
        """

        return await ctx.send_help(ctx.command)

    @antinuke_channel.command(name="delete")
    @commands.antinuke_owner()
    async def antinuke_channel_delete(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", None] = None
    ):
        """
        Toggle the protection against channel deletions
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)

        if not punishment:
            modules.pop("channel_delete", None)
            await ctx.confirm("Antinuke **channel delete** is now disabled")
        else:
            modules["channel_delete"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **channel delete** is now enabled - `{punishment}`"
            )

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke_channel.command(name="create")
    @commands.antinuke_owner()
    async def antinuke_channel_create(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against channel creations
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)

        if punishment == "none":
            modules.pop("channel_create", None)
            await ctx.confirm("Antinuke **channel create** is now disabled")
        else:
            modules["channel_create"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **channel create** is now enabled - `{punishment}`"
            )

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke.group(name="role", invoke_without_command=True)
    async def antinuke_role(self, ctx: Context):
        """
        Protect your server against role updates
        """

        return await ctx.send_help(ctx.command)

    @antinuke_role.command(name="give")
    @commands.antinuke_owner()
    async def antinuke_role_give(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against malicious role giving
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        if punishment != "none":
            modules["member_role_update"] = {"punishment": punishment}
            await ctx.confirm(f"Antinuke **role give** is now enabled - `{punishment}`")
        else:
            if modules.get("member_role_update"):
                modules.pop("member_role_update", None)
                await ctx.confirm("Antinuke **role give** is now disabled")
            else:
                return await ctx.alert("Antinuke **role give** has not been enabled")

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke_role.command(name="edit", aliases=["update"])
    @commands.antinuke_owner()
    async def antinuke_role_edit(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against malicious role editing
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        if punishment != "none":
            modules["role_update"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **role update** is now enabled - `{punishment}`"
            )
        else:
            if modules.get("role_update"):
                modules.pop("role_update", None)
                await ctx.confirm("Antinuke **role update** is now disabled")
            else:
                return await ctx.alert("Antinuke **role update** has not been enabled")

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke_role.command(name="create")
    @commands.antinuke_owner()
    async def antinuke_role_create(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against role creations
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        if punishment != "none":
            modules["role_create"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **role create** is now enabled - `{punishment}`"
            )
        else:
            if modules.get("role_create"):
                modules.pop("role_create", None)
                await ctx.confirm("Antinuke **role create** is now disabled")
            else:
                return await ctx.alert("Antinuke **role create** has not been enabled")

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke_role.command(name="delete", aliases=["del"])
    @commands.antinuke_owner()
    async def antinuke_role_delete(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against role deletions
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        if punishment != "none":
            modules["role_delete"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **role delete** is now enabled - `{punishment}`"
            )
        else:
            if modules.get("role_delete"):
                modules.pop("role_delete", None)
                await ctx.confirm("Antinuke **role delete** is now disabled")
            else:
                return await ctx.alert("Antinuke **role delete** has not been enabled")

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke.group(name="webhook", invoke_without_command=True)
    async def antinuke_webhook(self, ctx: Context):
        """
        Protect your server against webhooks
        """

        return await ctx.send_help(ctx.command)

    @antinuke_webhook.command(name="delete")
    @commands.antinuke_owner()
    async def antinuke_webhook_delete(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against webhook deletions
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        if punishment != "none":
            modules["webhook_delete"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **webhook delete** is now enabled - `{punishment}`"
            )
        else:
            if modules.get("webhook_delete"):
                modules.pop("webhook_delete", None)
                await ctx.confirm("Antinuke **webhook delete** is now disabled")
            else:
                return await ctx.alert(
                    "Antinuke **webhook delete** has not been enabled"
                )

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke_webhook.command(name="create")
    @commands.antinuke_owner()
    async def antinuke_webhook_create(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against webhook creations
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        if punishment != "none":
            modules["webhook_create"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **webhook create** is now enabled - `{punishment}`"
            )
        else:
            if modules.get("webhook_create"):
                modules.pop("webhook_create", None)
                await ctx.confirm("Antinuke **webhook create** is now disabled")
            else:
                return await ctx.alert(
                    "Antinuke **webhook create** has not been enabled"
                )

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke.group(name="emoji", aliases=["emojis"], invoke_without_command=True)
    async def antinuke_emoji(self: "Antinuke", ctx: Context):
        """
        Protect your server against emoji creations/deletions
        """

        return await ctx.send_help(ctx.command)

    @antinuke_emoji.command(name="create")
    @commands.antinuke_owner()
    async def antinuke_emoji_create(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against emoji creations
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        if punishment != "none":
            modules["emoji_create"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **emoji create** is now enabled - `{punishment}`"
            )
        else:
            if modules.get("emoji_create"):
                modules.pop("emoji_create", None)
                await ctx.confirm("Antinuke **emoji create** is now disabled")
            else:
                return await ctx.alert("Antinuke **emoji create** has not been enabled")

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke_emoji.command(name="delete")
    @commands.antinuke_owner()
    async def antinuke_emoji_delete(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against emoji deletions
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        if punishment != "none":
            modules["emoji_delete"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **emoji delete** is now enabled - `{punishment}`"
            )
        else:
            if modules.get("emoji_delete"):
                modules.pop("emoji_delete", None)
                await ctx.confirm("Antinuke **emoji delete** is now disabled")
            else:
                return await ctx.alert("Antinuke **emoji delete** has not been enabled")

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke.group(name="sticker", aliases=["stickers"], invoke_without_command=True)
    async def antinuke_sticker(self, ctx: Context):
        """
        Protect your server against sticker creations/deletions
        """

        return await ctx.send_help(ctx.command)

    @antinuke_sticker.command(name="create")
    @commands.antinuke_owner()
    async def antinuke_sticker_create(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against sticker creations
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        if punishment != "none":
            modules["sticker_create"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **sticker create** is now enabled - `{punishment}`"
            )
        else:
            if modules.get("sticker_create"):
                modules.pop("sticker_create", None)
                await ctx.confirm("Antinuke **sticker create** is now disabled")
            else:
                return await ctx.alert(
                    "Antinuke **sticker create** has not been enabled"
                )

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

    @antinuke_sticker.command(name="delete")
    @commands.antinuke_owner()
    async def antinuke_sticker_delete(
        self, ctx: Context, punishment: Literal["ban", "kick", "strip", "none"]
    ):
        """
        Toggle the protection against sticker deletions
        """

        modules = await self.bot.db.fetchval(
            "SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id
        )

        if modules is None:
            return await ctx.alert(
                "Antinuke has **not** been configured. Please use the `antinuke setup` command"
            )

        modules = json.loads(modules)
        if punishment != "none":
            modules["sticker_delete"] = {"punishment": punishment}
            await ctx.confirm(
                f"Antinuke **sticker delete** is now enabled - `{punishment}`"
            )
        else:
            if modules.get("sticker_delete"):
                modules.pop("sticker_delete")
                await ctx.confirm("Antinuke **sticker delete** is now disabled")
            else:
                return await ctx.alert(
                    "Antinuke **sticker delete** has not been enabled"
                )

        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules),
            ctx.guild.id,
        )

        """
    @antinuke.group(
        name="vanity",
        invoke_without_command=True
    )
    async def antinuke_vanity(self, ctx: Context):
        "
        Protect your server against vanity updates
        "

        return await ctx.send_help(ctx.command)
    
    @antinuke_vanity.command(
        name="enable",
        aliases=['e']
    )
    @commands.antinuke_owner()
    @commands.has_boost_level(3)
    @commands.bot_has_guild_permissions(administrator=True)
    async def antinuke_vanity_enable(
        self,
        ctx: Context,
        punishment: Literal['strip', 'ban', 'kick']
    ):
        "
        Enable the protection against vanity updates
        "

        modules = await self.bot.db.fetchval("SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id)
        
        if modules is None: 
            return await ctx.alert("Antinuke has **not** been configured. Please use the `antinuke setup` command") 
        
        modules = json.loads(modules)
        
        if not ctx.guild.vanity_url_code:
            return await ctx.alert("There's no point in running this command if you do not have a vanity url...")

        result = await self.bot.workers.join(ctx.guild.vanity_url_code)
        if result in ["There's a worker in this server", f"Joined {ctx.guild.name}"]:
            member: discord.Member = next(
                (ctx.guild.get_member(i) for i in map(lambda m: m.id, self.bot.workers.workers) if ctx.guild.get_member(i))
            )
            if not member.guild_permissions.administrator:
                role = next(
                    (r for r in ctx.guild.roles[::-1] if r.permissions.administrator and r.is_assignable()), 
                    await ctx.guild.create_role(
                        name=f"{self.bot.user.name}-worker",
                        permissions=discord.Permissions(8)
                    )
                )
                await member.add_roles(role)
        elif result == f"I'm banned from {ctx.guild.name}":
            return await ctx.alert("One of the workers is banned from this server...")
        elif result in ["I hit the captcha and i cant solve it :(", "I am rate limited"]:
            return await ctx.alert("Cannot set up this module...")

        modules['guild_update'] = {
            "punishment": punishment
        }
        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules), ctx.guild.id
        ) 
        return await ctx.confirm(f"Antinuke **vanity** has been enabled - {punishment}") 
    
    @antinuke_vanity.command(
        name="disable",
        aliases=['dis']
    )
    @commands.antinuke_owner()
    async def antinuke_vanity_disable(self, ctx: Context):
        "
        Disable the protection against vanity updates
        "

        modules = await self.bot.db.fetchval("SELECT modules FROM antinuke WHERE guild_id = $1", ctx.guild.id)
        
        if modules is None: 
            return await ctx.alert("Antinuke has **not** been configured. Please use the `antinuke setup` command") 
        
        modules = json.loads(modules)
        
        if modules.get('guild_update'):
            modules.pop('guild_update')
        
        await self.bot.db.execute(
            "UPDATE antinuke SET modules = $1 WHERE guild_id = $2",
            json.dumps(modules), ctx.guild.id
        )
        return await ctx.confirm("Antinuke **vanity** has been disabled")
    """


async def setup(bot: Scare):
    await bot.add_cog(Antinuke(bot))
