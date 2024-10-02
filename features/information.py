import datetime
from contextlib import suppress
from io import BytesIO
from typing import Union
from discord.utils import oauth_url
import humanize
import psutil
from discord import (
    ButtonStyle,
    Embed,
    utils,
    File,
    Interaction,
    Member,
    Message,
    Permissions,
    Role,
    User,
    Invite,
    Object,
    __version__,
    app_commands,
)
from discord.abc import GuildChannel

from discord.ext.commands import Author, Cog, command, has_permissions, hybrid_command
from discord.ui import Button, View
from discord.utils import format_dt, oauth_url, utcnow
from jishaku.math import natural_size
from psutil import Process

from structure.scare import Scare
from structure.managers import Context
from structure.managers.discordstatus import DiscordStatus


class DefaultBanner(Button):
    def __init__(self):
        super().__init__(label="View default banner")

    async def callback(self, interaction: Interaction):
        self.view.clear_items()
        self.view.add_item(UserBanner())
        await interaction.response.edit_message(embed=self.view.embed, view=self.view)


class UserBanner(Button):
    def __init__(self):
        super().__init__(label="View guild banner")

    async def callback(self, interaction: Interaction):
        embed = interaction.message.embeds[0]
        embed.title = f"{self.view.member}'s guild banner"
        embed.set_image(url=self.view.member.display_banner.url)
        self.view.clear_items()
        self.view.add_item(DefaultBanner())
        return await interaction.response.edit_message(embed=embed, view=self.view)


class Banners(View):
    def __init__(self, embed: Embed, author: int, member: Member):
        self.embed = embed
        self.member = member
        self.author = author
        super().__init__()

    async def interaction_check(self, interaction: Interaction):
        if interaction.user.id != self.author:
            await interaction.response.defer(ephemeral=True)

        return interaction.user.id == self.author

    def stop(self):
        self.children[0].disabled = True
        return super().stop()

    async def on_timeout(self):
        self.stop()
        return await self.message.edit(view=self)


class Information(Cog):
    def __init__(self, bot: Scare):
        self.bot: Scare = bot
        self.psutil = Process()

    @hybrid_command()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def status(self: "Information", ctx: Context):
        """
        Get discord statuses
        """
        data = await DiscordStatus.from_response()
        embed = data.to_embed(self.bot, False)
        return await ctx.send(embed=embed)

    @hybrid_command(aliases=["creds", "devs", "developers" "dev"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def credits(self: "Information", ctx: Context):
        """
        Get credits on the bot's contributor's team
        """

        embed = (
            Embed(
                color=self.bot.color,
            )
            .set_footer(text="scare credits | scare.life")
            .set_thumbnail(url=self.bot.user.avatar)
        )
        embed.add_field(
            name=f"Credits",
            value=f"`1` **{await self.bot.fetch_user(596752300756697098)}** - Founder & Developer (`596752300756697098`)\n`2` **{await self.bot.fetch_user(1188955485462872226)}** - Owner & Developer (`1188955485462872226`)\n`3` **{await self.bot.fetch_user(1280856653230505994)}** - Owner & Developer (`1280856653230505994`)\n`4` **{await self.bot.fetch_user(1083131355984044082)}** - Owner & Developer (`1083131355984044082`)\n`5` **{await self.bot.fetch_user(809975522867412994)}** - scare's cat (`809975522867412994`)\n`6` **{await self.bot.fetch_user(1137846765576540171)}** - Creator of scare (`1137846765576540171`)"
        )
        view = View().add_item(
        Button(style=ButtonStyle.grey, label="owners", disabled=True)
        )
        await ctx.reply(embed=embed, view=view)

    @hybrid_command(aliases=["bi", "bot", "info", "about"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def botinfo(self: "Information", ctx: Context):
        """
        Get info on bot
        """

        summary = [
            f"commands: `{len(set(self.bot.walk_commands()))}`",
            f"started: {format_dt(self.bot.uptime, style='R')}",
            f"created: {format_dt(self.bot.user.created_at, style='d')}",
            f"latency: `{round(self.bot.latency * 1000)}ms`",
            f"lines: `{self.bot.lines:,}`",
        ]

        embed = (
            Embed(
                color=self.bot.color,
                description=f"{self.bot.user.name} is serving `{len(self.bot.guilds):,}` guilds & `{len(self.bot.users):,}` users\nJoin the support server [**here**](https://scare.life/discord)",
            )
            .set_author(
                name=self.bot.user.name, icon_url=self.bot.user.display_avatar.url
            )
            .add_field(name="Statistics", value="\n".join(summary))
        )

        if psutil:
            with suppress(psutil.AccessDenied):
                proc = psutil.Process()

                with proc.oneshot():
                    mem = proc.memory_full_info()
                    proc.cpu_percent()
                    embed.set_footer(
                        text=f"Memory: {natural_size(mem.rss)} {psutil.virtual_memory().percent}%"
                    )

        return await ctx.reply(embed=embed)
    
    @command()
    @has_permissions(view_audit_log=True)
    async def audit(self, ctx: Context):
        """
        View the audit log
        """
        
        def format_action(action: str):
            if action == "kick":
                return "kicked"
            
            arr = action.split('_')
            if arr[-1].endswith('e'):
                return f"{arr[-1]}d {' '.join(arr[:-1])}"
            elif arr[-1].endswith('n'):
                if len(arr) == 1:
                    return f"{arr[0]}ned"
                else:
                    return f"{arr[-1]}ned {' '.join(arr[:-1])}"
            else: 
                return f"{arr[-1]} {' '.join(arr[:-1])}"
        
        def format_object(target):
            if isinstance(target, (Member, User)):
                return f"[@{target.name}]({target.url})"
            
            elif isinstance(target, GuildChannel):
                return f"[#{target.name}]({target.jump_url})"
            
            elif isinstance(target, Role):
                return f"@{target.name}"
            
            elif isinstance(target, Invite):
                return f"[{target.code}]({target.url})"
            
            elif isinstance(target, Object):
                if target.type == Role:
                    return f"{f'@{ctx.guild.get_role(target.id).name}' if ctx.guild.get_role(target.id) else f'**{target.id}**'}"
                else:
                    return f"**{target.id}**"

        logs = [
            entry async for entry in ctx.guild.audit_logs() 
            if not 'automod' in entry.action.name
        ]
        return await ctx.paginate(
            [
                f"[@{entry.user.name}]({entry.user.url}) {format_action(entry.action.name)} {format_object(entry.target)}"
                for entry in logs
            ],
            Embed(title="Audit Log")
        )

    @hybrid_command()
    @has_permissions(ban_members=True)
    async def bans(self: "Information", ctx: Context) -> Message:
        """
        View all bans
        """

        bans = [entry async for entry in ctx.guild.bans()]

        if not bans:
            return await ctx.alert("No bans found in this server")

        return await ctx.paginate(
            [
                f"{entry.user} ({entry.user.id}) - {entry.reason or 'No reason provided'}"
                for entry in bans
            ],
            Embed(title=f"Bans in {ctx.guild} ({len(bans)})"),
        )
    
    @hybrid_command()
    async def boosters(
        self: "Information",
        ctx: Context
    ):
        """
        View all boosters
        """

        if not (
            boosters := [
                member for member in ctx.guild.members 
                if member.premium_since
            ]
        ):
            return await ctx.alert("There are no boosters in this server")
        
        return await ctx.paginate(
            [
                f"{member.mention} {format_dt(member.premium_since, style='R')}"
                for member in boosters
            ],
            Embed(title="Server boosters")
        )

    @hybrid_command()
    async def bots(
        self: "Information",
        ctx: Context,
    ) -> Message:
        """
        View all bots
        """

        if not (
            bots := filter(
                lambda member: member.bot,
                ctx.guild.members,
            )
        ):
            return await ctx.alert(f"No bots have been found in {ctx.guild.name}!")

        return await ctx.paginate(
            [f"{bot.mention}" for bot in bots], Embed(title=f"Bots in {ctx.guild.name}")
        )

    @hybrid_command(name="members", aliases=["inrole"])
    async def members(
        self: "Information", ctx: Context, *, role: Role = None
    ) -> Message:
        """
        View all members in a role
        """

        role = role or ctx.author.top_role

        if not role.members:
            return await ctx.alert(f"No members in the role {role.mention}!")

        return await ctx.paginate(
            [f"{user.mention}" for user in role.members],
            Embed(title=f"Members in {role.name}"),
        )

    @hybrid_command(
        name="roles",
    )
    async def roles(
        self: "Information",
        ctx: Context,
    ) -> Message:
        """
        View all roles
        """

        if not (roles := reversed(ctx.guild.roles[1:])):
            return await ctx.alert(f"No roles have been found in {ctx.guild.name}!")

        return await ctx.paginate(
            [f"{role.mention}" for role in roles],
            Embed(title=f"Roles in {ctx.guild.name}"),
        )

    @hybrid_command(name="emojis", aliases=["emotes"])
    async def emojis(
        self: "Information",
        ctx: Context,
    ) -> Message:
        """
        View all emojis
        """

        if not ctx.guild.emojis:
            return await ctx.alert(f"No emojis have been found in {ctx.guild.name}!")

        return await ctx.paginate(
            [f"{emoji} [`{emoji.name}`]({emoji.url})" for emoji in ctx.guild.emojis],
            Embed(title=f"Emojis in {ctx.guild.name}"),
        )

    @command(
        name="stickers",
    )
    async def stickers(
        self: "Information",
        ctx: Context,
    ) -> Message:
        """
        View all stickers
        """

        if not ctx.guild.stickers:
            return await ctx.alert(f"No stickers have been found in {ctx.guild.name}!")

        return await ctx.paginate(
            [f"[`{sticker.name}`]({sticker.url})" for sticker in ctx.guild.stickers],
            Embed(title=f"Stickers in {ctx.guild.name}"),
        )

    @command(
        name="invites",
    )
    async def invites(
        self: "Information",
        ctx: Context,
    ) -> Message:
        """
        View all invites
        """

        if not (
            invites := sorted(
                [invite for invite in await ctx.guild.invites() if invite.expires_at],
                key=lambda invite: invite.expires_at,
                reverse=True,
            )
        ):
            return await ctx.alert(f"No invites have been found in {ctx.guild.name}!")

        return await ctx.paginate(
            [
                (
                    f"[`{invite.code}`]({invite.url}) expires "
                    + format_dt(
                        invite.expires_at,
                        style="R",
                    )
                )
                for invite in invites
            ],
            Embed(title=f"Invite in {ctx.guild.name}"),
        )

    @hybrid_command(
        name="avatar",
        aliases=[
            "av",
        ],
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def avatar(
        self: "Information", 
        ctx: Context, 
        *, 
        user: Union[Member, User] = Author
    ) -> Message:
        """
        View a users avatar
        """

        view = View()

        view.add_item(
            Button(
                style=ButtonStyle.link,
                label="PNG",
                url=str(user.display_avatar.replace(size=4096, format="png")),
            )
        )
        view.add_item(
            Button(
                style=ButtonStyle.link,
                label="JPG",
                url=str(user.display_avatar.replace(size=4096, format="jpg")),
            )
        )
        view.add_item(
            Button(
                style=ButtonStyle.link,
                label="WEBP",
                url=str(user.display_avatar.replace(size=4096, format="webp")),
            )
        )

        return await ctx.send(
            embed=Embed(title=f"{user.name}'s avatar", url=user.display_avatar)
            #   .set_author(name=f"{user.name}'s avatar")
            .set_image(url=user.display_avatar.url),
            #   view=view
        )

    @command(name="banner", aliases=["ub", "userbanner"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def banner(
        self: "Information", 
        ctx: Context, 
        *, 
        member: Union[Member, User] = Author
    ) -> Message:
        """
        View a users banner
        """

        user = await self.bot.fetch_user(member.id)

        if not user.banner:
            return await ctx.alert(
                "You don't have a banner set!"
                if user == ctx.author
                else f"{user} does not have a banner set!"
            )

        embed = Embed(title=f"{user.name}'s banner").set_image(url=user.banner)

        view = Banners(embed=embed, author=ctx.author.id, member=member)

        if isinstance(member, Member):
            if member.display_banner:
                view.add_item(UserBanner())

        return await ctx.send(embed=embed, view=view)

    @hybrid_command()
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def getbotinvite(self: "Information", ctx: Context, *, user: User):
        """
        Get an invite of a bot
        """

        if not user.bot:
            return await ctx.alert("This is not a bot")

        invite_url = oauth_url(user.id, permissions=Permissions(8))
        return await ctx.reply(f"Invite [{user}]({invite_url})")

    @hybrid_command(name="invite", aliases=["inv"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def invite(self: "Information", ctx: Context):
        """
        Get the invite for scare
        """
        button = Button(label="invite", style=ButtonStyle.url, url=utils.oauth_url(client_id=self.bot.user.id, permissions=Permissions.all()), emoji="<:bots:1288748751086813245>")
        button2 = Button(label="support", style=ButtonStyle.url, url="https://discord.gg/scarebot", emoji="<:home:1288749488596586549>")
        button3 = Button(label="vote", style=ButtonStyle.url, url="https://top.gg/bot/912268358416756816", emoji="<:link:1288748791553593355>")
        view = View()
        view.add_item(button)
        view.add_item(button2)
        view.add_item(button3)
        await ctx.reply(view=view)
        
    @hybrid_command(
        name="uptime",
        aliases=["ut", "up"],
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def uptime(self: "Information", ctx: Context) -> Message:
        """
        View the bot's uptime
        """

        return await ctx.reply(
            embed=Embed(
                description=f"⏰ **{self.bot.user.display_name}** has been up for: {humanize.precisedelta(utcnow() - self.bot.uptime, format='%0.0f')}"
            )
        )

    @command(name="itemshop", aliases=["fnshop"])
    async def fortnite_shop(self: "Information", ctx: Context) -> Message:
        """
        View the Fortnite item shop
        """

        buffer = await self.bot.session.get(
            f"https://bot.fnbr.co/shop-image/fnbr-shop-{utcnow().strftime('%-d-%-m-%Y')}.png"
        )

        return await ctx.send(file=File(BytesIO(buffer), filename=f"shop.png"))

    @hybrid_command(aliases=["mc"])
    async def membercount(self, ctx: Context):
        """
        Get the amount of members in this server
        """
        users = [m for m in ctx.guild.members if not m.bot]
        bots = [m for m in ctx.guild.members if m.bot]

        percentage = lambda a: round((a / ctx.guild.member_count) * 100, 2)

        embed = Embed(
            description="\n".join(
                (
                    f"**members:** `{ctx.guild.member_count:,}`",
                    f"**users:**: `{len(users):,}` ({percentage(len(users))}%)",
                    f"**bots:** `{len(bots):,}` ({percentage(len(bots))}%)",
                )
            )
        )

        new_joined = sorted(
            filter(
                lambda m: (utcnow() - m.joined_at).total_seconds() < 600,
                ctx.guild.members,
            ),
            key=lambda m: m.joined_at,
            reverse=True,
        )

        if new_joined:
            embed.add_field(
                name=f"New members ({len(new_joined)})",
                value=(
                    f", ".join(map(str, new_joined[:5]))
                    + f" + {len(new_joined)-5} more"
                    if len(new_joined) > 5
                    else ""
                ),
                inline=False,
            )

        return await ctx.reply(embed=embed)


async def setup(bot: Scare) -> None:
    await bot.add_cog(Information(bot))
