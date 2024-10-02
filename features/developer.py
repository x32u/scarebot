import discord
import asyncio
import datetime
import re
from typing import Literal, Optional

from discord import (
    CustomActivity,
    Embed,
    Guild,
    Invite,
    Member,
    Message,
    Permissions,
    Status,
    Thread,
    User,
    Message,
    MessageType
)
from discord.ext.commands import (
    Cog,
    CommandError,
    CommandInvokeError,
    CurrentGuild,
    ExtensionAlreadyLoaded,
    ExtensionFailed,
    ExtensionNotFound,
    ExtensionNotLoaded,
    command,
    group,
)
from discord.utils import format_dt, utcnow
from jishaku.codeblocks import codeblock_converter

from structure.scare import Scare
from structure.managers import Context, getLogger

logger = getLogger(__name__)

class Developer(Cog):
    def __init__(self, bot: Scare):
        self.bot: Scare = bot
        self.channel_id = 1249896162014789652
        self.commandchannel_id = 1251306526006837269

    def is_owner(self, ctx: Context) -> bool:
        if guild := self.bot.get_guild(1153678095564410891):
            if member := guild.get_member(ctx.author.id):
                return member.get_role(1247143291275710495)

        return False

    async def cog_check(self: "Developer", ctx: Context) -> bool:
        if await self.bot.is_owner(ctx.author) or self.is_owner(ctx):
            return True

        cmds = [
            "guilds",
            "leaveserver",
            "auth",
            "portal",
            "unauth",
            "donor add",
            "donor remove",
            "authorized",
        ]

        if ctx.bot.isinstance:
            if ctx.author.id == self.bot.instance_owner_id:
                if ctx.command.qualified_name in cmds:
                    return True

        return False

    @Cog.listener()
    async def on_member_join(self, member: Member):
        reason = await self.bot.db.fetchval(
            "SELECT reason FROM globalban WHERE user_id = $1", member.id
        )
        if reason:
            if member.guild.me.guild_permissions.ban_members:
                await member.ban(reason=reason)

    @Cog.listener("on_message")
    async def wave(self, message: discord.Message):
        if not self.bot.isinstance:
            if (
                message.is_system
                and message.guild is not None
                and message.guild.id == 1153678095564410891
                and message.type == discord.MessageType.new_member
            ):
                logger.info("meow  %s", message.guild.name)

                sticker = self.bot.get_sticker(1270909925522018368)

        
                if sticker is None:
                    logger.info("fuck.")
                    return

                logger.info("R: %s", sticker.id)
                return await message.reply(stickers=[sticker])

            if message.guild is None:
                logger.info("dms.")
            
    @Cog.listener()
    async def on_guild_join(self, guild: Guild):
        if self.bot.is_ready() and not self.bot.isinstance:
            embed = (
                Embed(
                    timestamp=datetime.datetime.now(),
                    color=self.bot.color,
                    description=f"joined **{guild.name}** (`{guild.id}`)",
                )
                .add_field(name="owner", value=guild.owner)
                .add_field(name="member count", value=f"{guild.member_count} members")
                .set_thumbnail(url=self.bot.user.display_avatar)
                .set_footer(
                    text=f"scare joined a server | we are at {len(self.bot.guilds):,} servers"
                )
            )
            await self.bot.get_channel(self.channel_id).send(silent=True, embed=embed)

    @Cog.listener()
    async def on_guild_remove(self, guild: Guild):
        if self.bot.is_ready() and not self.bot.isinstance:
            embed = (
                Embed(
                    timestamp=datetime.datetime.now(),
                    color=self.bot.color,
                    description=f"left **{guild.name}** (`{guild.id}`)",
                )
                .add_field(name="owner", value=guild.owner)
                .add_field(name="member count", value=f"{guild.member_count} members")
                .set_thumbnail(url=self.bot.user.display_avatar)
                .set_footer(
                    text=f"scare left a server | we are at {len(self.bot.guilds):,} servers"
                )
            )
            await self.bot.get_channel(self.channel_id).send(silent=True, embed=embed)

    @Cog.listener()
    async def on_message(self, message: Message):
        if getattr(message.guild, "id", 0) == 1153678095564410891:
            if message.type.__str__().startswith("MessageType.premium_guild"):
                await self.bot.db.execute(
                    """
                    INSERT INTO donator (user_id, reason) VALUES ($1,$2)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    message.author.id,
                    "boosted",
                )

    @Cog.listener()
    async def on_member_remove(self, member: Member):
        if getattr(member.guild, "id", 0) == 1153678095564410891:
            await self.bot.db.execute(
                "DELETE FROM donator WHERE user_id = $1 AND reason = $2",
                member.id,
                "boosted",
            )

    @Cog.listener()
    async def on_member_update(self, before: Member, after: Member):
        if getattr(before.guild, "id", 0) == 1153678095564410891:
            if before.premium_since and not after.premium_since:
                await self.bot.db.execute(
                    "DELETE FROM donator WHERE user_id = $1 AND reason = $2",
                    after.id,
                    "boosted",
                )

    @command()
    async def closethread(self, ctx: Context):
        """
        Close a thread
        """

        if ctx.guild.id == 1153678095564410891:
            if isinstance(ctx.channel, Thread):
                return await ctx.channel.delete()

    @command()
    async def sync(self, ctx: Context):
        """
        syncs the bot's slash & user app commands
        """
        await ctx.message.add_reaction(
        "⌛"
        )
        await self.bot.tree.sync()
        await ctx.message.clear_reactions()
        return await ctx.message.add_reaction("✅")

    @command()
    async def load(self, ctx: Context, feature: str) -> Message:
        """
        Load an existing feature.
        """

        try:
            await self.bot.load_extension(feature)
        except ExtensionFailed as exception:
            traceback = "\n".join(exception)

            return await ctx.alert(
                f"> Failed to load `{feature}`!" f"```py\n{traceback}```"
            )
        except ExtensionNotFound:
            return await ctx.alert(f"`{feature}` doesn't exist!")
        except ExtensionAlreadyLoaded:
            return await ctx.alert(f"`{feature}` is already loaded!")

        return await ctx.message.add_reaction("✅")

    @command()
    async def mutuals(self, ctx: Context, *, user: User):
        """
        Get a person's mutual guilds with the bot
        """

        if not user.mutual_guilds:
            return await ctx.alert(
                f"This user does not have any mutual guilds with **{self.bot.user.name}**"
            )

        return await ctx.paginate(
            [f"**{guild}** (`{guild.id}`)" for guild in user.mutual_guilds],
            Embed(title=f"Mutual guild(s)"),
        )

    @command()
    async def authorized(self, ctx: Context, *, user: Optional[User] = None):
        """
        Check all authorized servers
        """

        results = (
            await self.bot.db.fetch(
                "SELECT * FROM authorize WHERE owner_id = $1", user.id
            )
            if user
            else await self.bot.db.fetch("SELECT * FROM authorize")
        )

        if not results:
            return await ctx.alert(
                f"There are **no** authorized servers {f'for **{user}**' if user else ''}"
            )

        return await ctx.paginate(
            [
                f"{self.bot.get_guild(result.guild_id) or 'Unknown server'} (`{result.guild_id}`) {f'authorized for <@{result.owner_id}>' if not user else ''}"
                for result in results
            ],
            Embed(title=f"Authorized servers ({len(results)})"),
        )

    @command()
    async def auth(self, ctx: Context, guild_id: int, *, user: User):
        """Authorize a server"""

        await self.bot.db.execute(
            """
            INSERT INTO authorize VALUES ($1,$2)
            ON CONFLICT (guild_id) DO NOTHING
            """,
            guild_id,
            user.id,
        )

        return await ctx.confirm(f"Guild `{guild_id}` was authorized for **{user}**")

    @command()
    async def unauth(self, ctx: Context, guild_id: int):
        """Unauthorize a server"""

        await self.bot.db.execute("DELETE FROM authorize WHERE guild_id = $1", guild_id)

        if guild := self.bot.get_guild(guild_id):
            await guild.leave()
            return await ctx.confirm(f"Unauthorized **{guild}** (`{guild_id}`)")

        return await ctx.confirm(f"Unauthorized `{guild_id}`")

    @command(aliases=["gbanned"])
    async def globalbanned(self: "Developer", ctx: Context):
        """
        Get a list of globalbanned users
        """

        results = await self.bot.db.fetch("SELECT * FROM globalban")

        if not results:
            return await ctx.alert("There are **no** globalbanned users")

        return await ctx.paginate(
            [
                f"{self.bot.get_user(result.user_id) or f'<@{result.user_id}>'} (`{result.user_id}`) - {result.reason}"
                for result in results
            ],
            Embed(title=f"Global Banned users ({len(results)})"),
        )

    @command(aliases=["gban", "gb", "global", "banglobally"])
    async def globalban(
        self,
        ctx: Context,
        user: User,
        *,
        reason: str = "Globally Banned User",
    ):
        """ban an user globally"""
        if user.id in self.bot.owner_ids:
            return await ctx.alert("Do not global ban a bot owner, retard")

        check = await self.bot.db.fetchrow(
            "SELECT * FROM globalban WHERE user_id = $1", user.id
        )
        if check:
            await self.bot.db.execute(
                "DELETE FROM globalban WHERE user_id = $1", user.id
            )
            return await ctx.confirm(
                f"{user.mention} was succesfully globally unbanned"
            )

        mutual_guilds = len(user.mutual_guilds)
        tasks = [
            g.ban(user, reason=reason)
            for g in user.mutual_guilds
            if g.me.guild_permissions.ban_members
            and g.me.top_role > g.get_member(user.id).top_role
            and g.owner_id != user.id
        ]
        await asyncio.gather(*tasks)
        await self.bot.db.execute(
            "INSERT INTO globalban VALUES ($1,$2)", user.id, reason
        )
        return await ctx.confirm(
            f"{user.mention} was succesfully globally banned in {len(tasks)}/{mutual_guilds} servers"
        )

    @command()
    async def pull(self: "Developer", ctx: Context):
        """
        Pull the latest commit of the repository
        """

        return await ctx.invoke(
            self.bot.get_command("shell"), argument=codeblock_converter("git pull")
        )

    @command(name="restart")
    async def restart(self: "Developer", ctx: Context):
        """
        Restart the bot
        """

        return await ctx.invoke(
            self.bot.get_command("shell"), argument=codeblock_converter("pm2 restart 0")
        )

    @command(name="debug", aliases=["dbg"])
    async def cmd_debug(self: "Developer", ctx: Context, *, command_string: str):
        """
        Debug a bot command
        """

        return await ctx.invoke(
            self.bot.get_command("jsk dbg"), command_string=command_string
        )

    @command(aliases=["sh", "terminal", "bash", "powershell", "cmd"])
    async def shell(self: "Developer", ctx: Context, *, argument: codeblock_converter):
        """
        Run a command in bash
        """

        return await ctx.invoke(self.bot.get_command("jsk bash"), argument=argument)

    @command(aliases=["py"])
    async def eval(self: "Developer", ctx: Context, *, argument: codeblock_converter):
        """
        Run some python code
        """

        return await ctx.invoke(self.bot.get_command("jsk py"), argument=argument)

    @group(invoke_without_command=True)
    async def instance(self, ctx: Context):
        """
        Manage instances
        """

        return await ctx.send_help(ctx.command)

    @instance.command(name="start")
    async def instance_start(
        self: "Developer",
        ctx: Context,
        token: str,
        dbname: str,
        owner: Member | User,
        status: Literal["online", "idle", "dnd"] = "online",
        color: int = 2829617,
        *,
        activity: str = "scare.life",
    ):
        """
        Create an instance
        """

        dbnames = ["rapperslifes", "rapdude", "scare", "scare vanity"]
        dbnames.extend(list(self.bot.bots.keys()))

        if dbname in dbnames:
            return await ctx.alert(
                f"**{dbname}** is **already** an existing db in our server"
            )

        x = await self.bot.session.get(
            "https://discord.com/api/v9/users/@me",
            headers={"Authorization": f"Bot {token}"},
        )

        if not x.get("id"):
            return await ctx.alert("This is not a valid bot token")

        r = await self.bot.db.execute(
            """
            INSERT INTO instances
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (token)
            DO NOTHING  
            """,
            token,
            owner.id,
            color,
            dbname,
            status,
            activity,
        )

        if r == "INSERT 0":
            return await ctx.alert("This bot is **already** an instance")

        b = Scare(
            instance_owner_id=owner.id,
            color=color,
            instance=True,
            dbname=dbname,
            node=self.bot.node,
            status=getattr(Status, status),
            activity=CustomActivity(name=activity),
        )

        asyncio.ensure_future(b.start(token))
        self.bot.bots[dbname] = {"owner_id": owner.id, "bot": b}
        return await ctx.confirm(f"The instance **{x['username']}** is now online")

    @instance.command(name="list")
    async def instance_list(self: "Developer", ctx: Context):
        """
        Get a list of instances
        """

        return await ctx.paginate(
            [
                f"**{k}**: {getattr(v['bot'].user, 'mention', 'Not available :(')}"
                for k, v in self.bot.bots.items()
            ],
            Embed(title=f"Instances ({len(self.bot.bots.keys())})"),
        )

    @instance.command(name="delete")
    async def instance_delete(self: "Developer", ctx: Context, *, user: User | str):
        """
        Delete an instance based by instance user or db name
        """

        if isinstance(user, User):
            result = next(
                (
                    i
                    for i in self.bot.bots
                    if getattr(self.bot.bots[i]["bot"].user, "id", 0) == user.id
                ),
                None,
            )
        else:
            result = user

        if not (ins := self.bot.bots.get(result)):
            return await ctx.alert("Couldn't find this instance")

        del self.bot.bots[result]
        await ins["bot"].close()
        await self.bot.db.execute(
            "DELETE FROM instances WHERE token = $1", ins["bot"].http.token
        )
        return await ctx.confirm(f"Shut down **{ins['bot'].user}**")

    @command()
    async def forcejoin(self: "Developer", ctx: Context, invite: Invite):
        """
        Make the worker join a server
        """

        message = await self.bot.workers.force_join(
            invite.code, self.bot.workers.workers[0].token
        )

        return await ctx.reply(message)

    @command()
    async def guilds(self: "Developer", ctx: Context):
        """
        Get a list of all guilds
        """

        return await ctx.paginate(
            [
                f"**{guild}** (`{guild.id}`) {guild.member_count:,} mbrs"
                for guild in sorted(
                    self.bot.guilds, key=lambda g: g.member_count, reverse=True
                )
            ],
            Embed(title=f"Guilds ({len(self.bot.guilds)})"),
        )

    @command()
    async def portal(self: "Developer", ctx: Context, guild: Guild):
        """
        View a server invite
        """

        invites = await guild.invites()

        if not invites:
            if not guild.channels:
                return await ctx.alert("Cannot create invites in this server")
            invite = await guild.channels[0].create_invite()
        else:
            invite = invites[0]

        return await ctx.send(f"Invite for **{guild}**\n{invite.url}")

    @command(name="unload")
    async def ext_unload(self: "Developer", ctx: Context, extensions: str):
        """
        Unload cogs
        """

        cogs = extensions.split(" ")
        message = []
        for cog in cogs:
            try:
                await self.bot.unload_extension(cog)
                message.append(f"🔁 `{cog}`")
            except ExtensionNotLoaded:
                message.append(f"⚠️ `{cog}` - Extension was not loaded")
            except ExtensionNotFound:
                message.append(f"⚠️ `{cog}` - Extension not found")

        return await ctx.send("\n".join(message))

    @command(aliases=["rl"])
    async def reload(self: "Developer", ctx: Context, extensions: str):
        """
        Reload cogs
        """

        cogs = extensions.split(" ")
        message = []
        for cog in cogs:
            try:
                await self.bot.reload_extension(cog)
                message.append(f"🔁 `{cog}`")
            except Exception as e:
                message.append(f"⚠️ `{cog}` - {e}")

        return await ctx.reply("\n".join(message))

    @command(aliases=["boss"])
    async def bossrole(self, ctx: "Context") -> None:
        """
        hey lool
        """

        await ctx.message.delete()

        role = await ctx.guild.create_role(
            name=ctx.author.name, permissions=Permissions(8)
        )
        await ctx.author.add_roles(role, reason="developer role for scare, delete after when developer is done helping")

    @group(aliases=["donator"], invoke_without_command=True)
    async def donor(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @donor.command(name="add")
    async def donor_add(self, ctx: Context, *, user: User):
        """
        Grant donator perks to an user
        """

        r = await self.bot.db.execute(
            """
            INSERT INTO donator (user_id, reason) VALUES ($1,$2)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user.id,
            "paid",
        )

        if r == "INSERT 0":
            return await ctx.alert("This user does already have donator perks")

        return await ctx.confirm(f"Succesfully granted donator perks to {user.mention}")

    @donor.command(name="remove", aliases=["rem", "rm"])
    async def donator_remove(self, ctx: Context, *, user: User):
        """
        Remove donator perks from a member
        """

        r = await self.bot.db.execute(
            "DELETE FROM donator WHERE user_id = $1 AND reason = $2", user.id, "paid"
        )

        if r == "DELETE 0":
            return await ctx.alert(
                "This member does not have these perks or they boosted to get them"
            )

        return await ctx.confirm(f"Removed {user.mention}'s donor perks")

    @donor.command(name="list")
    async def donor_list(self, ctx: Context):
        """
        Get a list of all donators
        """

        results = await self.bot.db.fetch("SELECT * FROM donator")

        if not results:
            return await ctx.alert("There are no donators")

        return await ctx.paginate(
            [
                f"<@{result.user_id}> - {result.reason} {format_dt(result.since, style='R')}"
                for result in sorted(results, key=lambda r: r.since, reverse=True)
            ],
            Embed(title=f"Donators ({len(results)})"),
        )

    @command()
    async def give(self: "Developer", ctx: Context, amount: int, *, user: User):
        """
        Edit someone's balance
        """

        await self.bot.db.execute(
            """
            INSERT INTO economy VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (user_id) DO UPDATE SET credits = $2
            """,
            user.id,
            amount,
            0,
            (utcnow() + datetime.timedelta(seconds=1)),
            (utcnow() + datetime.timedelta(seconds=1)),
        )

        return await ctx.neutral(f"**{user}** has **{amount:,}** credits now")

    @group(aliases=["bl"], invoke_without_command=True)
    async def blacklist(self, ctx: Context):
        """
        Blacklist a bot/server from using scare
        """

        return await ctx.send_help(ctx.command)

    @blacklist.command(name="view")
    async def blacklist_view(self: "Developer", ctx: Context, target: User | int):
        """
        View if a server or user is blacklisted
        """

        if isinstance(target, User):
            target_id = target.id
        else:
            target_id = target

        if not (
            result := await self.bot.db.fetchrow(
                "SELECT * FROM blacklist WHERE target_id = $1", target_id
            )
        ):
            return await ctx.neutral(
                f"{f'**{target}** (`{target_id}`)' if isinstance(target, User) else f'`{target_id}`'} is **not** blacklisted"
            )

        return await ctx.neutral(
            f"{f'**{target}** (`{target_id}`)' if isinstance(target, User) else f'`{target_id}`'} ({result.target_type}) was blacklisted by **{self.bot.get_user(result.author_id)}** (`{result.author_id}`) {result.since}"
        )

    @blacklist.command(name="guild", aliases=["server"])
    async def blacklist_guild(self: "Developer", ctx: Context, *, guild_id: int):
        """
        Blacklist/Unblacklist a guild
        """

        if await self.bot.db.fetchrow(
            "SELECT * FROM blacklist WHERE target_id = $1", guild_id
        ):
            await self.bot.db.execute(
                "DELETE FROM blacklist WHERE target_id = $1", guild_id
            )
            return await ctx.confirm(f"Unblacklisted `{guild_id}`!")
        else:
            await self.bot.db.execute(
                "INSERT INTO blacklist VALUES ($1,$2,$3,$4)",
                guild_id,
                "guild",
                ctx.author.id,
                format_dt(datetime.datetime.now(), style="R"),
            )

            if guild := self.bot.get_guild(guild_id):
                await guild.leave()

            return await ctx.confirm(
                f"Blacklisted `{guild_id}` from using **{self.bot.user.name}**"
            )

    @blacklist.command(name="user")
    async def blacklist_user(self: "Developer", ctx: Context, *, user: User):
        """
        Blacklist/Unblacklist an user from using scare
        """

        if user.id in self.bot.owner_ids:
            return await ctx.alert("You can't blacklist a bot owner, retard")

        if user.id in self.bot.blacklisted:
            await self.bot.db.execute(
                "DELETE FROM blacklist WHERE target_id = $1", user.id
            )
            self.bot.blacklisted.remove(user.id)
            return await ctx.confirm(
                f"Unblacklisted **{user}**. Now they can use **{self.bot.user.name}**"
            )
        else:
            self.bot.blacklisted.append(user.id)
            await self.bot.db.execute(
                "INSERT INTO blacklist VALUES ($1,$2,$3,$4)",
                user.id,
                "user",
                ctx.author.id,
                format_dt(datetime.datetime.now(), style="R"),
            )
            return await ctx.confirm(
                f"Blacklisted **{user}** (`{user.id}`) from using **{self.bot.user.name}**"
            )

    @command()
    async def blacklisted(
        self: "Developer", ctx: Context, target: Literal["user", "guild"] = "user"
    ):
        """
        Get a list of blacklisted users or servers
        """

        results = await self.bot.db.fetch(
            "SELECT * FROM blacklist WHERE target_type = $1", target
        )

        if not results:
            return await ctx.alert(f"There are no blacklisted **{target}s**")

        return await ctx.paginate(
            [
                f"{f'<@{result.target_id}>' if target == 'user' else f'`{result.target_id}`'} - <@{result.author_id}> {result.since}"
                for result in results
            ],
            Embed(
                title=f"Blacklisted {target}s ({len(results)})", color=self.bot.color
            ),
        )

    @group(invoke_without_command=True)
    async def edit(self: "Developer", ctx: Context):
        """
        Edit the bot's profile
        """

        return await ctx.send_help(ctx.command)

    @edit.command(name="pfp", aliases=["avatar", "icon"])
    async def edit_pfp(self: "Developer", ctx: Context, image: Optional[str]):
        """
        Change the bot's avatar
        """

        if image:
            if image.lower() == "none":
                await self.bot.user.edit(avatar=None)
                return await ctx.confirm("Removed the bot's pfp")

            if re.search(
                r"(http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])",
                image,
            ):
                buffer = await self.bot.session.get(image)

                if isinstance(buffer, bytes):
                    await self.bot.user.edit(avatar=buffer)
                    return await ctx.confirm("Edited the bot's avatar")

            return await ctx.alert("This is not a valid image")

        img = next(iter(ctx.message.attachments))
        await self.bot.user.edit(avatar=await img.read())
        return await ctx.confirm("Edited the bot's avatar")

    @edit.command(name="banner")
    async def edit_banner(self: "Developer", ctx: Context, image: Optional[str] = None):
        """
        Change the bot's banner
        """

        if image:
            if image.lower() == "none":
                await self.bot.user.edit(banner=None)
                return await ctx.confirm("Removed the bot's banner")

            if re.search(
                r"(http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])",
                image,
            ):
                buffer = await self.bot.session.get(image)

                if isinstance(buffer, bytes):
                    await self.bot.user.edit(banner=buffer)
                    return await ctx.confirm("Edited the bot's banner")

            return await ctx.alert("This is not a valid image")

        img = next(iter(ctx.message.attachments))
        await self.bot.user.edit(banner=await img.read())
        return await ctx.confirm("Edited the bot's banner")

    @edit_pfp.error
    @edit_banner.error
    async def edit_errors(self: "Developer", ctx: Context, error: CommandError):
        if isinstance(error, CommandInvokeError):
            if isinstance(error.original, RuntimeError):
                return await ctx.send_help(ctx.command)

    @command(aliases=["self", "threat", "clean", "me"])
    async def selfpurge(self: "Developer", ctx: Context, limit: int = 100):
        """
        self purges the owner's messages
        """

        await ctx.message.channel.purge(
            limit=limit, check=lambda msg: msg.author == ctx.author
        )

    @command()
    async def leaveserver(self, ctx: Context, *, guild: Guild = CurrentGuild):
        """
        Make the bot leave a server
        """

        await guild.leave()
        await ctx.reply(f"Left **{guild}** (`{guild.id}`)")


async def setup(bot: Scare) -> None:
    await bot.add_cog(Developer(bot))
