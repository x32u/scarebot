import asyncio
import datetime
import json
import os
import random
import re
import secrets
from collections import defaultdict
from contextlib import suppress
from typing import Annotated, Literal, Optional, Union

import discord
import humanfriendly
import speech_recognition as sr
from asyncpg import UniqueViolationError
from discord import (
    Attachment,
    CategoryChannel,
    Colour,
    Embed,
    Guild,
    Message,
    PartialEmoji,
    PermissionOverwrite,
    RawReactionActionEvent,
    Role,
    TextChannel,
    User,
)
from discord.ext.commands import (
    ChannelNotFound,
    Cog,
    CurrentChannel,
    RoleNotFound,
    antinuke_owner,
    group,
    has_boost_level,
    has_permissions,
    hybrid_group,
    is_booster,
    param,
    ticket_moderator,
)
from discord.ui import Button, View

from structure.scare import Scare, ratelimiter
from structure.managers import Context
from structure.utilities import (
    AssignableRole,
    Color,
    DiscordEmoji,
    Giveaway,
    GiveawayCreate,
    ImageData,
    Member,
    TicketView,
    Time,
    ValidAlias,
    ValidCommand,
    ValidPermission,
)


class Joindm(View):
    def __init__(self, guild: str):
        self.guild = guild
        super().__init__()
        self.add_item(Button(label=f"sent from {self.guild}", disabled=True))


class Configuration(Cog):
    def __init__(self, bot: Scare):
        self.bot: Scare = bot
        self.locks = defaultdict(asyncio.Lock)
        self.link_regex = r"(http|ftp|https):\/\/([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])"
        self.hex_regex = re.compile("^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
        self.whitelist_cache = {}
        self.antispam_cache = {}

    async def remove_element(self, user_id, guild_id, element):
        await asyncio.sleep(1)
        if element in self.antispam_cache[f"{user_id}-{guild_id}"]:
            self.antispam_cache[f"{user_id}-{guild_id}"].remove(element)

    async def transcribe(self, attachment: Attachment):
        r = sr.Recognizer()
        await attachment.save(attachment.filename)
        audio = f"{attachment.filename[:-3]}wav"
        with suppress(Exception):
            os.system(f"ffmpeg -i {attachment.filename} {audio} -y")
            with sr.AudioFile(audio) as source:
                r.adjust_for_ambient_noise(source, duration=0.2)
                a = r.record(source)
                return r.recognize_google(a)

        return None

    """
    @Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild:
            if interaction := message.interaction:
                if message.author.id == 302050872383242240 and interaction.name == "bump":
                    if message.embeds:
                        content = message.embeds[0].description 
                    else:
                        content = message.content
                    
                    if "Bump done! :thumbsup:" in content: 
                        if result := await self.bot.db.fetchrow(
                            "SELECT * FROM bumpreminder WHERE guild_id = $1",
                            message.guild.id
                        ):
                            code = await self.bot.embed.convert(
                                message.author, 
                                result['thank']
                            )
                            code.pop('delete_after', None)
                            await message.channel.send(**code)
                            await self.bot.db.execute(
                                "
                                UPDATE bumpreminder SET 
                                channel_id = $1,
                                bumper_id = $2, 
                                bump_next = $3
                                WHERE guild_id = $4  
                                ",
                                message.channel.id, 
                                message.author.id, 
                                (discord.utils.utcnow() + datetime.timedelta(hours=2)),
                                message.guild.id
                            )
                            return await self.bot.bump_cycle(message.guild.id)
    """

    @Cog.listener()
    async def on_raw_reaction_remove(self, payload: RawReactionActionEvent):
        if guild := self.bot.get_guild(payload.guild_id):
            if role_id := await self.bot.db.fetchval(
                """
                SELECT role_id FROM reactionroles
                WHERE guild_id = $1 AND
                channel_id = $2 AND message_id = $3
                AND emoji = $4   
                """,
                payload.guild_id,
                payload.channel_id,
                payload.message_id,
                str(payload.emoji),
            ):
                async with self.locks[guild.id]:
                    if role := guild.get_role(role_id):
                        if member := guild.get_member(payload.user_id):
                            if not member.bot:
                                if role in member.roles:
                                    await member.remove_roles(
                                        role, reason="Reactionrole"
                                    )

    @Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        if guild := self.bot.get_guild(payload.guild_id):
            if role_id := await self.bot.db.fetchval(
                """
                SELECT role_id FROM reactionroles
                WHERE guild_id = $1 AND
                channel_id = $2 AND message_id = $3
                AND emoji = $4   
                """,
                payload.guild_id,
                payload.channel_id,
                payload.message_id,
                str(payload.emoji),
            ):
                async with self.locks[guild.id]:
                    if role := guild.get_role(role_id):
                        if member := guild.get_member(payload.user_id):
                            if not member.bot:
                                if not role in member.roles:
                                    await member.add_roles(role, reason="Reactionrole")

    @Cog.listener("on_message")
    async def on_settings(self, message: Message):
        if not message.author.bot:
            if message.guild:
                if settings := await self.bot.db.fetchrow(
                    "SELECT * FROM server_settings WHERE guild_id = $1",
                    message.guild.id,
                ):
                    if settings.heximage:
                        if match := re.search(self.hex_regex, message.content):
                            if not ratelimiter(
                                bucket=f"hex-{message.channel.id}",
                                key="hex",
                                rate=3,
                                per=2,
                            ):
                                hex_code = match.group(0)
                                color = discord.Color.from_str(hex_code)
                                embed = (
                                    Embed(
                                        color=color,
                                        title=f"Showing hex code: {hex_code}",
                                    )
                                    .set_thumbnail(
                                        url=f"https://singlecolorimage.com/get/{hex_code[1:]}/400x400"
                                    )
                                    .add_field(
                                        name="RGB value",
                                        value=", ".join(color.to_rgb()),
                                    )
                                )

                                return await message.reply(embed=embed)

                    elif settings.voicetranscript:
                        if message.attachments:
                            attachment = message.attachments[0]
                            if attachment.is_voice_message():
                                if not ratelimiter(
                                    bucket=f"vt-{message.channel.id}",
                                    key="vt",
                                    rate=1,
                                    per=3,
                                ):
                                    async with self.locks[message.channel.id]:
                                        task = await asyncio.to_thread(
                                            self.transcribe, attachment
                                        )
                                        text = await task

                                        if text:
                                            embed = Embed(description=text)
                                            embed.set_author(
                                                name=message.author.name,
                                                icon_url=message.author.display_avatar.url,
                                            )
                                            await message.channel.send(embed=embed)

                                            with suppress(FileNotFoundError):
                                                os.remove(attachment.filename)
                                                os.remove(
                                                    attachment.filename[:-3] + "wav"
                                                )

    @Cog.listener("on_message")
    async def on_spam(self, message: discord.Message):
        if message.guild:
            if isinstance(message.author, discord.Member):
                if (
                    not message.author.guild_permissions.administrator
                    and not message.author.bot
                ):
                    if result := await self.bot.db.fetchrow(
                        "SELECT * FROM antispam WHERE guild_id = $1", message.guild.id
                    ):
                        if not message.author.id in result.whitelisted:
                            async with self.locks[message.guild.id]:
                                if not message.author.is_timed_out():
                                    if m := message.content.split("\n"):
                                        if len(m) > 5:
                                            avg = sum(len(g) for g in m) / len(m)
                                            if avg < 10:
                                                await message.delete()
                                                await message.author.timeout(
                                                    datetime.timedelta(
                                                        seconds=result.duration
                                                    ),
                                                    reason="Timed out for ladder typing",
                                                )

                                                embed = discord.Embed(
                                                    color=discord.Color.yellow(),
                                                    title="Ladder typing",
                                                    description=f"{message.author.mention} has been muted for **{humanfriendly.format_timespan(result.duration)}**",
                                                )

                                                return await message.channel.send(
                                                    embed=embed
                                                )

                                    if not self.antispam_cache.get(
                                        f"{message.author.id}-{message.guild.id}"
                                    ):
                                        self.antispam_cache[
                                            f"{message.author.id}-{message.guild.id}"
                                        ] = []

                                    self.antispam_cache[
                                        f"{message.author.id}-{message.guild.id}"
                                    ].append(message)
                                    asyncio.ensure_future(
                                        self.remove_element(
                                            message.author.id, message.guild.id, message
                                        )
                                    )

                                    if (
                                        len(
                                            self.antispam_cache[
                                                f"{message.author.id}-{message.guild.id}"
                                            ]
                                        )
                                        == 4
                                    ):
                                        await message.author.timeout(
                                            datetime.timedelta(seconds=result.duration),
                                            reason="Timed out for spamming",
                                        )

                                        embed = discord.Embed(
                                            color=discord.Color.yellow(),
                                            title="Antispam",
                                            description=f">>> {message.author.mention} has been muted for **{humanfriendly.format_timespan(result.duration)}**",
                                        )

                                        await message.channel.send(embed=embed)
                                        await message.channel.delete_messages(
                                            self.antispam_cache[
                                                f"{message.author.id}-{message.guild.id}"
                                            ]
                                        )
                                        del self.antispam_cache[
                                            f"{message.author.id}-{message.guild.id}"
                                        ]

    @Cog.listener("on_member_join")
    async def whitelist_protect(self: "Configuration", member: Member):
        result = await self.bot.db.fetchrow(
            "SELECT * FROM whitelist WHERE guild_id = $1", member.guild.id
        )
        if result:
            if not self.whitelist_cache.get(member.guild.id):
                self.whitelist_cache[member.guild.id] = {}

            if not member.id in result.whitelisted:
                async with self.locks[member.guild.id]:
                    c = self.whitelist_cache[member.guild.id].get(member.id, 0)
                    self.whitelist_cache[member.guild.id][member.id] = c + 1

                    try:
                        await member.send(result.msg)
                    except:
                        pass

                    if self.whitelist_cache[member.guild.id][member.id] == 3:
                        del self.whitelist_cache[member.guild.id][member.id]
                        return await member.ban(
                            reason="Member tried to join multiple times while being unwhitelisted"
                        )
                    else:
                        await member.kick(reason="Unwhitelisted member")

    @Cog.listener("on_member_join")
    async def on_autorole_receive(self: "Configuration", member: Member):
        if roles := await self.bot.db.fetchval(
            "SELECT roles FROM autorole WHERE guild_id = $1", member.guild.id
        ):
            roles = list(
                filter(
                    lambda r: r and r.is_assignable(),
                    [member.guild.get_role(r) for r in roles],
                )
            )

            roles.extend(member.roles[1:])
            await member.edit(roles=set(roles), reason="Autorole")

    @Cog.listener("on_member_remove")
    async def on_boosterrole_left(self, member: discord.Member):
        if role_id := await self.bot.db.fetchval(
            """
            SELECT role_id FROM boosterrole.roles
            WHERE user_id = $1 AND guild_id = $2  
            """,
            member.id,
            member.guild.id,
        ):
            if role := member.guild.get_role(role_id):
                await role.delete(reason="Booster left the server")

    @Cog.listener("on_member_update")
    async def on_boosterrole_update(
        self, before: discord.Member, after: discord.Member
    ):
        if before.premium_since and not after.premium_since:
            if role_id := await self.bot.db.fetchval(
                """
                SELECT role_id FROM boosterrole.roles
                WHERE user_id = $1 AND guild_id = $2  
                """,
                before.id,
                before.guild.id,
            ):
                if role := before.guild.get_role(role_id):
                    await role.delete(reason="Booster transfered their boosts")

    @Cog.listener()
    async def on_user_update(self, before: User, after: User):
        if not before.bot:
            if str(before) != str(after):
                channel_ids = list(
                    map(
                        lambda c: c["channel_id"],
                        await self.bot.db.fetch(
                            "SELECT channel_id FROM tracker.username"
                        ),
                    )
                )

                for channel_id in channel_ids:
                    if channel := self.bot.get_channel(channel_id):
                        await asyncio.sleep(0.1)
                        await channel.send(f"Username available: **{before}**")

    @Cog.listener()
    async def on_guild_update(self, before: Guild, after: Guild):
        if before.vanity_url_code:
            if before.vanity_url_code != after.vanity_url_code:
                channel_ids = list(
                    map(
                        lambda c: c["channel_id"],
                        await self.bot.db.fetch(
                            "SELECT channel_id FROM tracker.vanity"
                        ),
                    )
                )

                for channel_id in channel_ids:
                    if channel := self.bot.get_channel(channel_id):
                        await asyncio.sleep(0.1)
                        await channel.send(
                            f"Vanity URL available: **/{before.vanity_url_code}**"
                        )

    @group(aliases=["gw"], invoke_without_command=True)
    async def giveaway(self, ctx: Context):
        """
        Manage the server's giveaways
        """

        return await ctx.send_help(ctx.command)

    @giveaway.command(name="list")
    async def giveaway_list(self, ctx: Context):
        """
        Get a list of available giveaways in this server
        """

        return await ctx.send(
            f"[**{ctx.guild} giveaways**](https://scare.life/giveaways/{ctx.guild.id})"
        )

    @giveaway.command(name="end", aliases=["stop"])
    @has_permissions(manage_guild=True)
    async def giveaway_end(self, ctx: Context, message_id: int):
        """
        End a giveaway
        """

        if not (task := self.bot.giveaways.get(message_id)):
            return await ctx.alert("Could not find giveaway")

        task.cancel()
        del self.bot.giveaways[message_id]
        gw = await self.bot.db.fetchrow(
            "SELECT * FROM giveaway WHERE message_id = $1", message_id
        )

        try:
            winners = random.sample(gw.members, gw.winners)
            embed = (
                Embed(
                    title=gw.reward,
                    color=self.bot.color,
                    description=f"Ended: {discord.utils.format_dt(discord.utils.utcnow(), style='R')}",
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
            await self.bot.db.execute(
                "UPDATE giveaway SET ended = $1 WHERE message_id = $2", True, message_id
            )
            try:
                message = await self.bot.get_channel(gw.channel_id).fetch_message(
                    message_id
                )
                await message.edit(embed=embed, view=None)
            except:
                return await ctx.alert("Giveaway message was not found")
            finally:
                return await ctx.confirm(f"Ended giveaway")

    @giveaway.command(name="reroll")
    @has_permissions(manage_guild=True)
    async def giveaway_reroll(self, ctx: Context, message_id: int):
        """
        Reroll a giveaway and get a new winner
        """

        users = await self.bot.db.fetchval(
            """
            SELECT members FROM giveaway 
            WHERE message_id = $1 
            AND guild_id = $2 
            AND ended = $3
            """,
            message_id,
            ctx.guild.id,
            True,
        )

        if not users:
            return await ctx.alert(
                "Could not found a giveaway associated with this message id or it didn't end"
            )

        winner = secrets.choice(users)
        return await ctx.reply(f"**New winner:** <@{winner}>")

    @giveaway.command(
        name="create",
        aliases=["setup", "start"],
        example="#giveaways discord nitro --time 7h --winners 2",
    )
    @has_permissions(manage_guild=True)
    async def giveaway_create(
        self, ctx: Context, channel: discord.TextChannel, *, options: GiveawayCreate
    ):
        """
        Create giveaways to engage server members
        """

        giveaways = await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM giveaway WHERE guild_id = $1", ctx.guild.id
        )

        if giveaways == 5:
            return await ctx.alert(
                "You cannot host more than **5** giveaways simuntaneously in this server"
            )

        seconds = humanfriendly.parse_timespan(options.time)

        if seconds < 600:
            return await ctx.alert("Giveaways cannot last less than **10 minutes**")

        end_at = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        embed = discord.Embed(
            color=self.bot.color,
            title=options.reward,
            description="\n".join(
                [
                    f"Hosted by: {ctx.author.mention}",
                    f"Ending: {discord.utils.format_dt(end_at, style='R')}",
                    f"Winners: **{options.winners}**",
                ]
            ),
        ).set_footer(text="scare.life")

        message = await channel.send(embed=embed, view=Giveaway())

        await self.bot.db.execute(
            """
            INSERT INTO giveaway
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)     
            """,
            ctx.guild.id,
            channel.id,
            message.id,
            [],
            options.reward,
            options.winners,
            end_at,
            False,
        )

        self.bot.giveaways[message.id] = asyncio.ensure_future(
            self.bot.giveaway_task(
                message.id, channel.id, end_at.replace(tzinfo=datetime.timezone.utc)
            )
        )
        return await ctx.confirm(f"Started giveaway -> {message.jump_url}")

    @group(aliases=["br"], invoke_without_command=True)
    async def boosterrole(self, ctx: Context):
        """
        Create a custom role (only if you are a booster)
        """

        return await ctx.send_help(ctx.command)

    @boosterrole.command(name="setup")
    @has_permissions(manage_guild=True)
    async def boosterrole_setup(self, ctx: Context):
        """
        Setup the booster role feature
        """

        r = await self.bot.db.execute(
            "INSERT INTO boosterrole.config VALUES ($1,$2)",
            ctx.guild.id,
            ctx.guild.default_role.id,
        )

        if r == "INSERT 0":
            return await ctx.alert("This feature is **already** configured")
        return await ctx.confirm("Configured the booster role feature")

    @boosterrole.command(name="disable")
    @has_permissions(manage_guild=True)
    async def boosterrole_disable(self, ctx: Context):
        """
        Disable the booster role feature
        """

        r = await self.bot.db.execute(
            "DELETE FROM boosterrole.config WHERE guild_id = $1", ctx.guild.id
        )

        if r == "DELETE 0":
            return await ctx.alert("This feature is **not** configured")
        return await ctx.confirm("Disabled the booster role feature")

    @boosterrole.command(name="base")
    @has_permissions(manage_guild=True)
    async def boosterrole_base(
        self, ctx: Context, *, role: Annotated[Role, AssignableRole] | str
    ):
        """
        Configure the boosterrole's base
        """

        if isinstance(role, str):
            if role.lower() in ["none", "remove"]:
                await self.bot.db.execute(
                    "UPDATE boosterrole.config SET base = $1 WHERE guild_id = $2",
                    None,
                    ctx.guild.id,
                )
                return await ctx.confirm("Removed the base role")
            raise RoleNotFound(role)

        await self.bot.db.execute(
            "UPDATE boosterrole.config SET base = $1 WHERE guild_id = $2",
            role.id,
            ctx.guild.id,
        )
        return await ctx.confirm(
            f"Updated the boosterrole's base role to {role.mention}"
        )

    @boosterrole.command(name="create")
    @is_booster()
    async def boosterrole_create(self, ctx: Context, *, name: Optional[str] = None):
        """
        Create a custom role
        """

        if not (
            base_id := await self.bot.db.fetchval(
                "SELECT base FROM boosterrole.config WHERE guild_id = $1", ctx.guild.id
            )
        ):
            return await ctx.alert("This feature is **not** enabled")

        if await self.bot.db.fetchrow(
            "SELECT * FROM boosterrole.roles WHERE user_id = $1 AND guild_id = $2",
            ctx.author.id,
            ctx.guild.id,
        ):
            return await ctx.alert("You already have a booster role")

        role = await ctx.guild.create_role(
            name=name or f"{ctx.author.name}'s role", reason="Booster role created"
        )

        await ctx.author.add_roles(role)
        await self.bot.db.execute(
            """
            INSERT INTO boosterrole.roles
            VALUES ($1,$2,$3) 
            """,
            ctx.guild.id,
            ctx.author.id,
            role.id,
        )
        base = ctx.guild.get_role(base_id)

        if base and base < ctx.guild.me.top_role and base != ctx.guild.default_role:
            await role.edit(position=base.position)

        return await ctx.confirm(
            f"Succesfully created a booster role named **{role.name}**"
        )

    @boosterrole.command(name="icon")
    @is_booster()
    async def boosterrole_icon(
        self: "Configuration",
        ctx: Context,
        icon: DiscordEmoji | Literal["remove", "clear", "reset", "off"],
    ):
        """
        Edit your booster role's icon
        """

        if not (
            role_id := await self.bot.db.fetchval(
                """
                SELECT role_id FROM boosterrole.roles
                WHERE guild_id = $1 AND user_id = $2 
                """,
                ctx.guild.id,
                ctx.author.id,
            )
        ):
            return await ctx.alert("There's no booster role created for you")

        if not (role := ctx.guild.get_role(role_id)):
            return await ctx.alert("The booster role does not exist anymore")

        if isinstance(icon, PartialEmoji):
            if icon.url:
                buffer = await self.bot.session.get(icon.url)
            else:
                buffer = str(icon)
        else:
            buffer = None

        try:
            await role.edit(display_icon=buffer)
        except discord.Forbidden:
            return await ctx.alert(
                f"{ctx.guild.name} needs more boosts to perform this action!"
            )

        return await ctx.confirm(f"Successfully edited {role.mention} icon!")

    @boosterrole.command(name="name", aliases=["rename"])
    @is_booster()
    async def boosterrole_name(self, ctx: Context, *, name: str):
        """
        Edit your role's name
        """

        if not (
            role_id := await self.bot.db.fetchval(
                """
                SELECT role_id FROM boosterrole.roles
                WHERE guild_id = $1 AND user_id = $2 
                """,
                ctx.guild.id,
                ctx.author.id,
            )
        ):
            return await ctx.alert("There's no booster role created for you")

        if not (role := ctx.guild.get_role(role_id)):
            return await ctx.alert("The booster role does not exist anymore")

        await role.edit(name=name, reason="Edited the booster role's name")

        return await ctx.confirm(f"Edited your role's name to **{name}**")

    @boosterrole.command(name="color", aliases=["colour"])
    @is_booster()
    async def boosterrole_color(self, ctx: Context, *, color: Annotated[Colour, Color]):
        """
        Edit your booster role's color
        """

        if not (
            role_id := await self.bot.db.fetchval(
                """
                SELECT role_id FROM boosterrole.roles
                WHERE guild_id = $1 AND user_id = $2 
                """,
                ctx.guild.id,
                ctx.author.id,
            )
        ):
            return await ctx.alert("There's no booster role created for you")

        if not (role := ctx.guild.get_role(role_id)):
            return await ctx.alert("The booster role does not exist anymore")

        await role.edit(color=color, reason="Edited the role's color")

        return await ctx.confirm(f"Edited the role's color to `{color}`")

    @boosterrole.command(name="delete", aliases=["del"])
    async def boosterrole_delete(self, ctx: Context):
        """
        Delete your custom role
        """

        if not (
            role_id := await self.bot.db.fetchval(
                """
                SELECT role_id FROM boosterrole.roles
                WHERE guild_id = $1 AND user_id = $2 
                """,
                ctx.guild.id,
                ctx.author.id,
            )
        ):
            return await ctx.alert("There's no booster role created for you")

        if role := ctx.guild.get_role(role_id):
            await role.delete(reason="Booster role deleted")

        await self.bot.db.execute(
            "DELETE FROM boosterrole.roles WHERE role_id = $1", role_id
        )

        return await ctx.confirm("Deleted your custom role")

    @group(invoke_without_command=True)
    async def tracker(self, ctx: Context):
        """
        Track username or vanity changes
        """

        return await ctx.send_help(ctx.command)

    @tracker.command(name="vanity")
    @has_permissions(manage_guild=True)
    async def tracker_vanity(self, ctx: Context, *, channel: TextChannel | str):
        """
        Track vanity updates
        """

        if isinstance(channel, str):
            if channel.lower() == "none":
                r = await self.bot.db.execute(
                    "DELETE FROM tracker.vanity WHERE guild_id = $1", ctx.guild.id
                )

                if r == "DELETE 0":
                    return await ctx.alert(
                        "There's no vanity tracker channel in your server"
                    )

                return await ctx.confirm("Stopped tracking vanities")
            else:
                raise ChannelNotFound(channel)
        else:
            await self.bot.db.execute(
                """
                INSERT INTO tracker.vanity VALUES ($1,$2)
                ON CONFLICT (guild_id) DO UPDATE SET 
                channel_id = $2    
                """,
                ctx.guild.id,
                channel.id,
            )

            return await ctx.confirm(f"Tracking vanity updates in {channel.mention}")

    @tracker.command(name="usernames")
    @has_permissions(manage_guild=True)
    async def tracker_usernames(self, ctx: Context, *, channel: TextChannel | str):
        """
        Track username updates
        """

        if isinstance(channel, str):
            if channel.lower() == "none":
                r = await self.bot.db.execute(
                    "DELETE FROM tracker.username WHERE guild_id = $1", ctx.guild.id
                )

                if r == "DELETE 0":
                    return await ctx.alert(
                        "There's no username tracker channel in your server"
                    )

                return await ctx.confirm("Stopped tracking usernames")
            else:
                raise ChannelNotFound(channel)
        else:
            await self.bot.db.execute(
                """
                INSERT INTO tracker.username VALUES ($1,$2)
                ON CONFLICT (guild_id) DO UPDATE SET 
                channel_id = $2    
                """,
                ctx.guild.id,
                channel.id,
            )

            return await ctx.confirm(f"Tracking username updates in {channel.mention}")

    @group(invoke_without_command=True)
    async def settings(self, ctx: Context):
        """
        Manage miscellaneous configuration settings
        """

        return await ctx.send_help(ctx.command)

    @settings.command(name="enablecommand", aliases=["enablecmd"])
    @has_permissions(administrator=True)
    async def settings_enablecmd(
        self, ctx: Context, *, command: Annotated[str, ValidCommand]
    ):
        """
        Enable a disabled command
        """

        r = await self.bot.db.execute(
            """
            DELETE FROM disabledcmds WHERE
            guild_id = $1 AND command_name = $2  
            """,
            ctx.guild.id,
            command,
        )

        if r == "DELETE 0":
            return await ctx.alert("This command was **not** disabled")

        return await ctx.confirm(f"Enabled **{command}**")

    @settings.command(name="disablecommand", aliases=["disablecmd"])
    @has_permissions(administrator=True)
    async def settings_disablecmd(
        self, ctx: Context, *, command: Annotated[str, ValidCommand]
    ):
        """
        Disable a command in this server
        """

        if command in ["help", "botinfo", "ping"]:
            return await ctx.alert("You cannot disable this command")

        r = await self.bot.db.execute(
            """
            INSERT INTO disabledcmds
            VALUES ($1,$2) ON CONFLICT
            (guild_id, command_name) 
            DO NOTHING     
            """,
            ctx.guild.id,
            command,
        )

        if r == "INSERT 0":
            return await ctx.alert(f"**{command}** is **already** disabled")

        return await ctx.confirm(f"Disabled **{command}**")

    @settings.command(name="heximage")
    @has_permissions(manage_guild=True)
    async def settings_heximage(
        self, ctx: Context, value: Literal["enable", "disable"]
    ):
        """
        Enable/Disable hex image displaying when hex code is sent
        """

        r = await self.bot.db.execute(
            """
            INSERT INTO server_settings (guild_id, heximage) VALUES ($1,$2)
            ON CONFLICT (guild_id) DO UPDATE SET heximage = $2   
            """,
            ctx.guild.id,
            bool(value == "enable"),
        )

        if r.endswith("0"):
            return await ctx.alert(f"Heximage is **already** {value}d")

        return await ctx.confirm(f"{value.capitalize()}d heximage")

    @settings.command(
        name="voicetranscript", aliases=["voicetranscripts", "vt", "speechtotext"]
    )
    @has_permissions(manage_guild=True)
    async def settings_voicetranscript(
        self, ctx: Context, value: Literal["enable", "disable"]
    ):
        """
        Enable/Disable voice message transcribing in this server
        """

        r = await self.bot.db.execute(
            """
            INSERT INTO server_settings (guild_id, voicetranscript) VALUES ($1,$2)
            ON CONFLICT (guild_id) DO UPDATE SET voicetranscript = $2  
            """,
            ctx.guild.id,
            bool(value == "enable"),
        )

        if r.endswith("0"):
            return await ctx.alert(f"Voice transcriptions are **already** {value}d")

        return await ctx.confirm(f"{value.capitalize()}d voice transcripts")

    @hybrid_group(invoke_without_command=True)
    async def autorole(self: "Configuration", ctx: Context) -> Message:
        """
        Grant new members roles on join
        """

        return await ctx.send_help(ctx.command)

    @autorole.command(name="add")
    @has_permissions(manage_guild=True)
    async def autorole_add(
        self: "Configuration", ctx: Context, *, role: AssignableRole
    ):
        """
        Make a role be granted by new members on join
        """

        roles = (
            await self.bot.db.fetchval(
                "SELECT roles FROM autorole WHERE guild_id = $1", ctx.guild.id
            )
            or []
        )

        if role.id in roles:
            return await ctx.alert("This role is already an autorole")

        roles.append(role.id)

        await self.bot.db.execute(
            """
            INSERT INTO autorole VALUES ($1,$2)
            ON CONFLICT (guild_id) DO UPDATE SET
            roles = $2
            """,
            ctx.guild.id,
            roles,
        )

        return await ctx.confirm(f"Added {role.mention} as an autorole")

    @autorole.command(name="remove", aliases=["rem", "rm"])
    @has_permissions(manage_guild=True)
    async def autorole_remove(
        self: "Configuration", ctx: Context, *, role: AssignableRole
    ):
        """
        Remove a role from the autorole list
        """

        roles = (
            await self.bot.db.fetchval(
                "SELECT roles FROM autorole WHERE guild_id = $1", ctx.guild.id
            )
            or []
        )

        if not role.id in roles:
            return await ctx.alert("This role is not an autorole")

        roles.remove(role.id)

        await self.bot.db.execute(
            """
            INSERT INTO autorole VALUES ($1,$2)
            ON CONFLICT (guild_id) DO UPDATE SET
            roles = $2
            """,
            ctx.guild.id,
            roles,
        )

        return await ctx.confirm(f"Removed {role.mention} from the autoroles")

    @autorole.command(name="list")
    @has_permissions(manage_guild=True)
    async def autorole_list(self: "Configuration", ctx: Context):
        """
        List all available autoroles of this server
        """

        roles = await self.bot.db.fetchval(
            "SELECT roles FROM autorole WHERE guild_id = $1", ctx.guild.id
        )

        if not roles:
            return await ctx.alert("There are **no** autoroles in this server")

        return await ctx.paginate(
            [
                f"{getattr(ctx.guild.get_role(r), 'mention', None)} (`{r}`)"
                for r in roles
                if ctx.guild.get_role(r)
            ],
            Embed(title=f"Autoroles in {ctx.guild} ({len(roles)})"),
        )

    @group(aliases=["wl"], invoke_without_command=True)
    @antinuke_owner()
    async def whitelist(
        self: "Configuration", ctx: Context, *, user: User = None
    ) -> Message:
        """
        Keep your server private
        """

        if not user:
            return await ctx.send_help(ctx.command)
        else:
            whitelisted: list = await self.bot.db.fetchval(
                "SELECT whitelisted FROM whitelist WHERE guild_id = $1", ctx.guild.id
            )
            if user.id in whitelisted:
                whitelisted.remove(user.id)
                await ctx.confirm(f"{user} is not permitted anymore")
            else:
                whitelisted.append(user.id)
                await ctx.confirm(f"{user} is now permitted")

            await self.bot.db.execute(
                "UPDATE whitelist SET whitelisted = $1 WHERE guild_id = $2",
                whitelisted,
                ctx.guild.id,
            )

    @whitelist.command(name="dm", aliases=["message", "msg"])
    @antinuke_owner()
    async def whitelist_dm(self: "Configuration", ctx: Context, *, message: str):
        """
        Assign a message to be sent to the unwhitelisted members
        """

        r = await self.bot.db.execute(
            "UPDATE whitelist SET msg = $1 WHERE guild_id = $2", message, ctx.guild.id
        )

        if r == "UPDATE 0":
            return await ctx.alert(
                "The whitelist feature isn't enabled. Please run `whitelist toggle`"
            )
        else:
            return await ctx.confirm(
                f"The whitelist message has been updated to\n{message}"
            )

    @whitelist.command(name="toggle")
    @antinuke_owner()
    async def whitelist_toggle(self: "Configuration", ctx: Context):
        """
        Enable/Disable whitelist in your server
        """

        try:
            await self.bot.db.execute(
                "INSERT INTO whitelist (guild_id) VALUES ($1)", ctx.guild.id
            )
            return await ctx.confirm(
                "Whitelist feature was enable. Any non whitelisted member will be kicked on join"
            )
        except UniqueViolationError:
            await self.bot.db.execute(
                "DELETE FROM whitelist WHERE guild_id = $1", ctx.guild.id
            )
            return await ctx.confirm("Whitelist feature was disabled")

    @group(invoke_without_command=True)
    async def antispam(self, ctx: Context):
        """
        Feature against message spamming
        """

        return await ctx.send_help(ctx.command)

    @antispam.command(name="enable", aliases=["e"])
    @has_permissions(manage_guild=True)
    async def antispam_enable(self, ctx: Context):
        """
        Enable the protection against message spamming
        """

        seconds = int(humanfriendly.parse_timespan("5m"))
        r = await self.bot.db.execute(
            """
            INSERT INTO antispam (guild_id, duration) VALUES ($1,$2)
            ON CONFLICT (guild_id) DO NOTHING  
            """,
            ctx.guild.id,
            seconds,
        )

        if r == "INSERT 0":
            return await ctx.alert("The antispam was **already** enabled")

        return await ctx.confirm(
            f"The antispam was enabled\nPunishment: mute **{humanfriendly.format_timespan(seconds)}**"
        )

    @antispam.command(name="disable", aliases=["dis", "remove", "rem", "rm"])
    @has_permissions(manage_guild=True)
    async def antispam_disable(self, ctx: Context):
        """
        Disable the protection against message spamming
        """

        r = await self.bot.db.execute(
            "DELETE FROM antispam WHERE guild_id = $1", ctx.guild.id
        )

        if r == "DELETE 0":
            return await ctx.alert("The antispam is **not** enabled in this server")

        return await ctx.confirm("The antispam was succesfully disabled")

    @antispam.command(name="duration")
    @has_permissions(manage_guild=True)
    async def antispam_duration(self: "Configuration", ctx: Context, time: Time):
        """
        Edit the mute duration of the antispam
        """

        if time > humanfriendly.parse_timespan("28d"):
            return await ctx.alert(
                "Discord API is limiting the time out to 28 days max"
            )

        await self.bot.db.execute(
            "UPDATE antispam SET duration = $1 WHERE guild_id = $2", time, ctx.guild.id
        )
        return await ctx.confirm(
            f"The antispam mute duration has been updated to **{humanfriendly.format_timespan(time)}**"
        )

    @antispam.command(name="whitelist", aliases=["wl"])
    @has_permissions(manage_guild=True)
    async def antispam_whitelist(
        self: "Configuration", ctx: Context, *, member: Member
    ):
        """
        Whitelist a member from the antispam
        """

        if member.guild_permissions.administrator:
            return await ctx.alert("Administrators are whitelisted by default")

        whitelisted = await self.bot.db.fetchval(
            "SELECT whitelisted FROM antispam WHERE guild_id = $1", ctx.guild.id
        )

        if whitelisted is None:
            return await ctx.alert(
                "The antispam feature is **not** enabled in this server"
            )

        if member.id in whitelisted:
            return await ctx.alert("This member is **already** whitelisted")

        whitelisted.append(member.id)
        await self.bot.db.execute(
            "UPDATE antispam SET whitelisted = $1 WHERE guild_id = $2",
            whitelisted,
            ctx.guild.id,
        )

        return await ctx.confirm(f"Whitelisted {member.mention} from the antispam")

    @antispam.command(name="unwhitelist", aliases=["uwl"])
    @has_permissions(manage_guild=True)
    async def antispam_unwhitelist(
        self: "Configuration", ctx: Context, *, member: Member
    ):
        """
        Unwhitelist a member from the antispam feature
        """

        whitelisted = await self.bot.db.fetchval(
            "SELECT whitelisted FROM antispam WHERE guild_id = $1", ctx.guild.id
        )

        if whitelisted is None:
            return await ctx.alert(
                "The antispam feature is **not** enabled in this server"
            )

        if not member.id in whitelisted:
            return await ctx.alert("This member is **not** whitelisted")

        whitelisted.remove(member.id)
        await self.bot.db.execute(
            "UPDATE antispam SET whitelisted = $1 WHERE guild_id = $2",
            whitelisted,
            ctx.guild.id,
        )

        return await ctx.confirm(f"Unwhitelisted {member.mention} from the antispam")

    @antispam.command(name="whitelisted")
    @has_permissions(manage_guild=True)
    async def antispam_whitelisted(self, ctx: Context):
        """
        Get a list of whitelisted members against the antispam
        """

        whitelisted = await self.bot.db.fetchval(
            "SELECT whitelisted FROM antispam WHERE guild_id = $1", ctx.guild.id
        )

        if not whitelisted:
            return await ctx.alert("There are no whitelisted members from the antispam")

        return await ctx.paginate(
            [f"<@{w}>" for w in whitelisted],
            Embed(title=f"Whitelisted members {len(whitelisted)}").set_footer(
                text="administrators are whitelisted by default"
            ),
        )

    @group(name="filter", invoke_without_command=True)
    async def automod_filter(self: "Configuration", ctx: Context) -> Message:
        """
        Protect your discord server using automod
        """

        return await ctx.send_help(ctx.command)

    @automod_filter.group(name="words", invoke_without_command=True)
    async def filter_words(self: "Configuration", ctx: Context):
        """
        Protect the server against unwanted words
        """

        return await ctx.send_help(ctx.command)

    @filter_words.command(name="remove", aliases=["rm"])
    @has_permissions(manage_guild=True)
    async def filter_words_remove(self: "Configuration", ctx: Context, *, word: str):
        """
        Unblacklist a word from the server
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.creator_id == self.bot.user.id and not a.trigger.regex_patterns
            ),
            None,
        )

        if not automod:
            return await ctx.alert("There's no words automod rule found")

        keyword_filter = automod.trigger.keyword_filter
        keyword = f"*{word}*"

        if not keyword in keyword_filter:
            return await ctx.alert(f"**{word}** is not blacklisted from this server")

        keyword_filter.remove(keyword)
        await automod.edit(
            trigger=discord.AutoModTrigger(
                type=discord.AutoModRuleTriggerType.keyword,
                keyword_filter=keyword_filter,
            ),
            reason=f"Automod rule edited by {ctx.author}",
        )

        return await ctx.confirm(f"Removed **{word}** from the blacklisted words")

    @filter_words.command(name="add")
    @has_permissions(manage_guild=True)
    async def filter_words_add(self: "Configuration", ctx: Context, *, word: str):
        """
        Blacklist a word from the server's channels
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.creator_id == self.bot.user.id and not a.trigger.regex_patterns
            ),
            None,
        )

        if not automod:
            actions = [
                discord.AutoModRuleAction(
                    custom_message=f"Message blocked by {self.bot.user.name} for containing a blacklisted word"
                )
            ]

            automod = await ctx.guild.create_automod_rule(
                name=f"{self.bot.user.name} - words",
                event_type=discord.AutoModRuleEventType.message_send,
                trigger=discord.AutoModTrigger(
                    type=discord.AutoModRuleTriggerType.keyword,
                    keyword_filter=[f"*{word}*"],
                ),
                enabled=True,
                actions=actions,
                reason=f"Automod rule enabled by {ctx.author}",
            )
        else:
            keyword_filter = automod.trigger.keyword_filter
            keyword_filter.append(f"*{word}*")
            await automod.edit(
                trigger=discord.AutoModTrigger(
                    type=discord.AutoModRuleTriggerType.keyword,
                    keyword_filter=keyword_filter,
                ),
                reason=f"Automod rule edited by {ctx.author}",
            )

        return await ctx.confirm(f"Added **{word}** as a blacklisted word")

    @filter_words.command(name="unwhitelist", aliases=["uwl"])
    @has_permissions(manage_guild=True)
    async def filter_words_uwl(
        self: "Configuration",
        ctx: Context,
        *,
        target: Union[AssignableRole, TextChannel],
    ):
        """
        Unwhitelist a role or a channel against the blacklist word punishment
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.creator_id == self.bot.user.id and not a.trigger.regex_patterns
            ),
            None,
        )

        if not automod:
            return await ctx.alert("The word automod rule was not enabled")

        if isinstance(target, discord.Role):
            roles = automod.exempt_roles
            if not target in roles:
                return await ctx.alert("This role is **not** whitelisted")
            else:
                roles.remove(target)

            await automod.edit(exempt_roles=roles)
        else:
            channels = automod.exempt_channels
            if not target in channels:
                return await ctx.alert("This channel is **not** whitelisted")
            else:
                channels.remove(target)

            await automod.edit(exempt_channels=channels)

        return await ctx.confirm(
            f"Unwhitelisted {target.mention} against blacklist words punishment"
        )

    @filter_words.command(name="whitelist", aliases=["wl"])
    @has_permissions(manage_guild=True)
    async def filter_words_wl(
        self: "Configuration",
        ctx: Context,
        *,
        target: Union[AssignableRole, TextChannel],
    ):
        """
        Whitelist a role or a channel against the blacklisted words punishment
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.creator_id == self.bot.user.id and not a.trigger.regex_patterns
            ),
            None,
        )

        if not automod:
            return await ctx.alert("The words automod rule was not enabled")

        if isinstance(target, discord.Role):
            roles = automod.exempt_roles
            if target in roles:
                return await ctx.alert("This role is **already** whitelisted")
            else:
                roles.append(target)

            await automod.edit(exempt_roles=roles)
        else:
            channels = automod.exempt_channels
            if target in channels:
                return await ctx.alert("This channel is **already** whitelisted")
            else:
                channels.append(target)

            await automod.edit(exempt_channels=channels)

        return await ctx.confirm(
            f"Whitelisted {target.mention} against blacklisted words punishment"
        )

    @filter_words.command(name="view", aliases=["list"])
    @has_permissions(manage_guild=True)
    async def filter_words_view(self: "Configuration", ctx: Context):
        """
        View the blacklisted words in this server
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.creator_id == self.bot.user.id and not a.trigger.regex_patterns
            ),
            None,
        )

        if not automod:
            return await ctx.alert("The blacklist words automod rule is not enabled")

        words = list(map(lambda m: m[1:-1], automod.trigger.keyword_filter))
        return await ctx.paginate(
            words, Embed(title=f"Blacklisted words ({len(words)})")
        )

    @automod_filter.group(name="links", invoke_without_command=True)
    async def filter_links(self: "Configuration", ctx: Context) -> Message:
        """
        Protect your server against regular links
        """

        return await ctx.send_help(ctx.command)

    @filter_links.command(
        name="remove", aliases=["rm", "delete", "del", "disable", "dis"]
    )
    @has_permissions(manage_guild=True)
    async def filter_links_disable(self: "Configuration", ctx: Context):
        """
        Disable the protection against regular links
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.trigger.regex_patterns == [self.link_regex]
            ),
            None,
        )

        if not automod:
            return await ctx.alert("The regular links automod rule was not enabled")

        await automod.delete(reason=f"Disabled by {ctx.author}")

        return await ctx.confirm("The regular links automod rule was deleted")

    @filter_links.command(name="enable", aliases=["e"])
    @has_permissions(manage_guild=True)
    async def filter_links_enable(
        self: "Configuration",
        ctx: Context,
        punishment: Literal["mute", "block"] = "block",
    ):
        """
        Enable the protection against regular links
        """

        automod = next(
            (
                e
                for e in await ctx.guild.fetch_automod_rules()
                if e.trigger.regex_patterns == [self.link_regex]
            ),
            None,
        )

        if automod:
            return await ctx.alert("There's such an automod rule **already** enabled")

        actions = [
            discord.AutoModRuleAction(
                custom_message=f"Message blocked by {self.bot.user.name}"
            )
        ]

        if punishment == "mute":
            actions.append(
                discord.AutoModRuleAction(duration=datetime.timedelta(minutes=5))
            )

        await ctx.guild.create_automod_rule(
            name=f"{self.bot.user.name} - links",
            event_type=discord.AutoModRuleEventType.message_send,
            trigger=discord.AutoModTrigger(
                type=discord.AutoModRuleTriggerType.keyword,
                regex_patterns=[self.link_regex],
            ),
            actions=actions,
            enabled=True,
            reason=f"Automod rule enabled by {ctx.author}",
        )

        return await ctx.confirm(
            f"Regular link automod rule enabled\npunishment: {'**block**' if punishment == 'block' else 'mute **5 minutes**'}"
        )

    @filter_links.command(name="unwhitelist", aliases=["uwl"])
    @has_permissions(manage_guild=True)
    async def filter_links_uwl(
        self: "Configuration",
        ctx: Context,
        *,
        target: Union[AssignableRole, TextChannel],
    ):
        """
        Unwhitelist a role or a channel agains the regular link punishment
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.trigger.regex_patterns == [self.link_regex]
            ),
            None,
        )

        if not automod:
            return await ctx.alert("The regular link automod rule was not enabled")

        if isinstance(target, discord.Role):
            roles = automod.exempt_roles
            if not target in roles:
                return await ctx.alert("This role is **not** whitelisted")
            else:
                roles.remove(target)

            await automod.edit(exempt_roles=roles)
        else:
            channels = automod.exempt_channels
            if not target in channels:
                return await ctx.alert("This channel is **not** whitelisted")
            else:
                channels.remove(target)

            await automod.edit(exempt_channels=channels)

        return await ctx.confirm(
            f"Unwhitelisted {target.mention} against regular link punishment"
        )

    @filter_links.command(name="whitelist", aliases=["wl"])
    @has_permissions(manage_guild=True)
    async def filter_links_wl(
        self: "Configuration",
        ctx: Context,
        *,
        target: Union[AssignableRole, TextChannel],
    ):
        """
        Whitelist a role or a channel against the regular link punishment
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.trigger.regex_patterns == [self.link_regex]
            ),
            None,
        )

        if not automod:
            return await ctx.alert("The regular link automod rule was not enabled")

        if isinstance(target, discord.Role):
            roles = automod.exempt_roles
            if target in roles:
                return await ctx.alert("This role is **already** whitelisted")
            else:
                roles.append(target)

            await automod.edit(exempt_roles=roles)
        else:
            channels = automod.exempt_channels
            if target in channels:
                return await ctx.alert("This channel is **already** whitelisted")
            else:
                channels.append(target)

            await automod.edit(exempt_channels=channels)

        return await ctx.confirm(
            f"Whitelisted {target.mention} against regular link punishment"
        )

    @automod_filter.group(name="invites", invoke_without_command=True)
    async def filter_invites(self: "Configuration", ctx: Context) -> Message:
        """
        Protect your discord server against discord invites
        """

        return await ctx.send_help(ctx.command)

    @filter_invites.command(name="unwhitelist", aliases=["uwl"])
    @has_permissions(manage_guild=True)
    async def filter_invites_uwl(
        self: "Configuration",
        ctx: Context,
        *,
        target: Union[AssignableRole, TextChannel],
    ):
        """
        Unwhitelist a role or a channel agains the anti invite punishment
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.trigger.regex_patterns == [self.bot.invite_regex]
            ),
            None,
        )

        if not automod:
            return await ctx.alert("The anti invite automod rule was not enabled")

        if isinstance(target, discord.Role):
            roles = automod.exempt_roles
            if not target in roles:
                return await ctx.alert("This role is **not** whitelisted")
            else:
                roles.remove(target)

            await automod.edit(exempt_roles=roles)
        else:
            channels = automod.exempt_channels
            if not target in channels:
                return await ctx.alert("This channel is **not** whitelisted")
            else:
                channels.remove(target)

            await automod.edit(exempt_channels=channels)

        return await ctx.confirm(
            f"Unwhitelisted {target.mention} against anti invite punishment"
        )

    @filter_invites.command(name="whitelist", aliases=["wl"])
    @has_permissions(manage_guild=True)
    async def fitler_invites_wl(
        self: "Configuration",
        ctx: Context,
        *,
        target: Union[AssignableRole, TextChannel],
    ):
        """
        Whitelist a role or a channel against the anti invite punishment
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.trigger.regex_patterns == [self.bot.invite_regex]
            ),
            None,
        )

        if not automod:
            return await ctx.alert("The anti invite automod rule was not enabled")

        if isinstance(target, discord.Role):
            roles = automod.exempt_roles
            if target in roles:
                return await ctx.alert("This role is **already** whitelisted")
            else:
                roles.append(target)

            await automod.edit(exempt_roles=roles)
        else:
            channels = automod.exempt_channels
            if target in channels:
                return await ctx.alert("This channel is **already** whitelisted")
            else:
                channels.append(target)

            await automod.edit(exempt_channels=channels)

        return await ctx.confirm(
            f"Whitelisted {target.mention} against anti invite punishment"
        )

    @filter_invites.command(
        name="remove", aliases=["rm", "delete", "del", "disable", "dis"]
    )
    @has_permissions(manage_guild=True)
    async def filter_invites_disable(self: "Configuration", ctx: Context):
        """
        Disable the protection against discord invites
        """

        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.trigger.regex_patterns == [self.bot.invite_regex]
            ),
            None,
        )

        if not automod:
            return await ctx.alert("The anti invite automod rule was not enabled")

        await automod.delete(reason=f"Disabled by {ctx.author}")

        return await ctx.confirm("The anti invite automod rule was deleted")

    @filter_invites.command(name="enable", aliases=["e"])
    @has_permissions(manage_guild=True)
    async def filter_invites_enable(
        self: "Configuration",
        ctx: Context,
        punishment: Literal["mute", "block"] = "block",
    ):
        """
        Block discord invites from getting sent in your discord server
        """
        automod = next(
            (
                a
                for a in await ctx.guild.fetch_automod_rules()
                if a.trigger.regex_patterns == [self.bot.invite_regex]
            ),
            None,
        )

        if automod:
            return await ctx.alert("Such a rule is **already** enabled")

        actions = [
            discord.AutoModRuleAction(
                custom_message=f"This message has been blocked by {self.bot.user.name}"
            )
        ]

        if punishment == "mute":
            actions.append(
                discord.AutoModRuleAction(duration=datetime.timedelta(minutes=5))
            )

        await ctx.guild.create_automod_rule(
            name=f"{self.bot.user.name} - invites",
            event_type=discord.AutoModRuleEventType.message_send,
            trigger=discord.AutoModTrigger(
                type=discord.AutoModRuleTriggerType.keyword,
                regex_patterns=[self.bot.invite_regex],
            ),
            actions=actions,
            enabled=True,
            reason=f"Automod rule configured by {ctx.author}",
        )

        return await ctx.confirm(
            f"Configured anti invite automod rule\npunishment: {'block' if punishment == '**block**' else 'mute **5 minutes**'}"
        )

    @group(invoke_without_command=True)
    async def guildedit(self: "Configuration", ctx: Context):
        """
        Edit the server using scare
        """

        return await ctx.send_help(ctx.command)

    @guildedit.command(name="name")
    @has_permissions(administrator=True)
    async def guildedit_name(self: "Configuration", ctx: Context, *, name: str):
        """
        Edit the server's name
        """

        await ctx.guild.edit(
            name=name, reason=f"Guild {ctx.command.name} edited by {ctx.author.name}"
        )
        return await ctx.confirm(
            f"Edited the guild's **{ctx.command.name}** to **{name}**"
        )

    @guildedit.command(name="description")
    @has_permissions(administrator=True)
    async def guildedit_description(
        self: "Configuration", ctx: Context, *, description: str
    ):
        """
        Edit the server's description
        """

        await ctx.guild.edit(
            description=description,
            reason=f"Guild {ctx.command.name} edited by {ctx.author.name}",
        )
        return await ctx.confirm(
            f"Edited the guild's **{ctx.command.name}** to\n```{description}```"
        )

    @guildedit.command(name="icon")
    @has_permissions(administrator=True)
    async def guildedit_icon(
        self: "Configuration",
        ctx: Context,
        *,
        image: Optional[Annotated[bytes, ImageData]] = None,
    ):
        """
        Edit the guild's image
        """

        if not image:
            if attachment := next(
                (a for a in ctx.message.attachments if "image" in a.content_type or ""),
                None,
            ):
                image = await attachment.read()
            else:
                return await ctx.send_help(ctx.command)

        await ctx.guild.edit(
            icon=image, reason=f"Guild {ctx.command.name} edited by {ctx.author.name}"
        )
        return await ctx.confirm(f"Edited the guild's **{ctx.command.name}**")

    @guildedit.command(name="banner")
    @has_permissions(administrator=True)
    @has_boost_level(3)
    async def guildedit_banner(
        self: "Configuration",
        ctx: Context,
        *,
        image: Optional[Annotated[bytes, ImageData]] = None,
    ):
        """
        Edit the guild's image
        """

        if not image:
            if attachment := next(
                (a for a in ctx.message.attachments if "image" in a.content_type or ""),
                None,
            ):
                image = await attachment.read()
            else:
                return await ctx.send_help(ctx.command)

        await ctx.guild.edit(
            banner=image, reason=f"Guild {ctx.command.name} edited by {ctx.author.name}"
        )
        return await ctx.confirm(f"Edited the guild's **{ctx.command.name}**")

    @group(invoke_without_command=True, aliases=["fakeperms", "fp"])
    async def fakepermissions(self: "Configuration", ctx: Context):
        """
        Allow members to have permissions strictly on the bot
        """

        return await ctx.send_help(ctx.command)

    @fakepermissions.command(name="remove")
    @has_permissions(administrator=True)
    async def fakeperms_remove(
        self: "Configuration",
        ctx: Context,
        permission: ValidPermission,
        *,
        role: AssignableRole,
    ):
        """
        Remove a permission from a role
        """

        permissions = (
            await self.bot.db.fetchval(
                "SELECT permissions FROM fakeperms WHERE guild_id = $1 AND role_id = $2",
                ctx.guild.id,
                role.id,
            )
            or []
        )

        if not permission in permissions:
            return await ctx.alert(
                "This permission is **not** in this role's permissions list"
            )

        permissions.remove(permission)
        await self.bot.db.execute(
            "UPDATE fakeperms SET permissions = $1 WHERE guild_id = $2 AND role_id = $3",
            permissions,
            ctx.guild.id,
            role.id,
        )
        return await ctx.confirm(
            f"Removed `{permission}` from {role.mention}'s permissions"
        )

    @fakepermissions.command(name="add")
    @has_permissions(administrator=True)
    async def fakeperms_add(
        self: "Configuration",
        ctx: Context,
        permission: ValidPermission,
        *,
        role: AssignableRole,
    ):
        """
        Add a permission to a role
        """

        permissions = (
            await self.bot.db.fetchval(
                "SELECT permissions FROM fakeperms WHERE guild_id = $1 AND role_id = $2",
                ctx.guild.id,
                role.id,
            )
            or []
        )

        if permission in permissions:
            return await ctx.alert("This permission is **already** added to this role")

        permissions.append(permission)
        await self.bot.db.execute(
            """
        INSERT INTO fakeperms VALUES ($1,$2,$3)
        ON CONFLICT (guild_id, role_id) DO UPDATE SET 
        permissions = $3 
        """,
            ctx.guild.id,
            role.id,
            permissions,
        )

        return await ctx.confirm(
            f"Added `{permission}` to the {role.mention}'s fake permissions"
        )

    @fakepermissions.command(name="valid")
    async def fakeperms_valid(self: "Configuration", ctx: Context):
        """
        Get all valid permissions that can be used for fakepermissions
        """

        return await ctx.paginate(
            [
                p
                for p in dir(ctx.author.guild_permissions)
                if type(getattr(ctx.author.guild_permissions, p)) == bool
            ],
            Embed(title="Available permissions"),
        )

    @fakepermissions.command(name="list")
    @has_permissions(manage_guild=True)
    async def fakeperms_list(self: "Configuration", ctx: Context, *, role: Role):
        """
        Get a list of all fake permissions added to a role
        """

        perms = await self.bot.db.fetchval(
            "SELECT permissions FROM fakeperms WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )

        if not perms:
            return await ctx.alert("There are **no** fake permissions for this role")

        return await ctx.paginate(
            [perm for perm in perms], Embed(title=f"Fake permissions for {role}")
        )

    @group(aliases=["alias"], invoke_without_command=True)
    async def aliases(self: "Configuration", ctx: Context) -> Message:
        """
        Add custom aliases to commands
        """

        return await ctx.send_help(ctx.command)

    @aliases.command(name="list")
    @has_permissions(manage_guild=True)
    async def aliases_list(self: "Configuration", ctx: Context):
        """
        Get a list of all added aliases in this server
        """

        aliases = await self.bot.db.fetch(
            "SELECT * FROM aliases WHERE guild_id = $1", ctx.guild.id
        )

        if not aliases:
            return await ctx.alert("No custom aliases were added in this server")

        return await ctx.paginate(
            [f"{r.alias} for {r.command}" for r in aliases],
            Embed(title=f"Aliases in {ctx.guild} ({len(aliases)})"),
        )

    @aliases.command(name="remove")
    @has_permissions(manage_guild=True)
    async def aliases_remove(self: "Configuration", ctx: Context, alias: str):
        """
        Remove an alias
        """

        r = await self.bot.db.execute(
            "DELETE FROM aliases WHERE guild_id = $1 AND alias = $2",
            ctx.guild.id,
            alias,
        )

        if r == "DELETE 0":
            return await ctx.alert(f"This is **not** a valid alias")

        return await ctx.confirm(f"Removed `{alias}` as an alias")

    @aliases.command(name="add")
    @has_permissions(manage_guild=True)
    async def aliases_add(
        self: "Configuration",
        ctx: Context,
        alias: Annotated[str, ValidAlias],
        command: Annotated[str, ValidCommand],
    ):
        """
        Add an alias to a command
        """

        r = await self.bot.db.execute(
            """
            INSERT INTO aliases VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, alias) DO NOTHING 
            """,
            ctx.guild.id,
            alias,
            command,
        )

        if r == "INSERT 0 0":
            return await ctx.alert(
                f"`{alias}` is already an alias for another command in this server"
            )

        return await ctx.confirm(f"Added `{alias}` as an alias for `{command}`")

    @group(invoke_without_command=True)
    async def ticket(self, ctx: Context):
        """
        Create a ticket panel for this server
        """

        return await ctx.send_help(ctx.command)

    @ticket.command(name="disable", aliases=["dis"])
    @has_permissions(administrator=True)
    async def ticket_disable(self: "Configuration", ctx: Context):
        """
        Disable the tickets feature
        """

        r = await self.bot.db.execute(
            "DELETE FROM tickets WHERE guild_id = $1", ctx.guild.id
        )

        if r == "DELETE 0":
            return await ctx.alert("The tickets feature was **not** configured")

        return await ctx.confirm("Disabled the tickets module")

    @ticket.command(name="add")
    @ticket_moderator()
    async def ticket_add(self: "Configuration", ctx: Context, *, member: Member):
        """
        Add a member to a ticket
        """

        overwrites = ctx.channel.overwrites
        overwrites[member] = PermissionOverwrite(
            send_messages=True, view_channel=True, attach_files=True, embed_links=True
        )
        return await ctx.confirm(f"Added {member.mention} to the ticket")

    @ticket.command(name="remove", aliases=["rm"])
    @ticket_moderator()
    async def ticket_remove(self: "Configuration", ctx: Context, *, member: Member):
        """
        Remove a member from the ticket
        """

        overwrites = ctx.channel.overwrites
        overwrites[member] = PermissionOverwrite(
            send_messages=False,
            view_channel=False,
            attach_files=False,
            embed_links=False,
        )
        return await ctx.confirm(f"Removed {member.mention} from the ticket")

    @ticket.command(name="settings")
    @has_permissions(manage_guild=True)
    async def ticket_settings(self: "Configuration", ctx: Context):
        """
        Check the ticket feature's settings
        """

        if not (
            result := await self.bot.db.fetchrow(
                "SELECT * FROM tickets WHERE guild_id = $1", ctx.guild.id
            )
        ):
            return await ctx.alert("The ticket feature is **not** enabled")

        embed = (
            discord.Embed(title="Ticket settings")
            .set_author(name=str(ctx.guild), icon_url=ctx.guild.icon)
            .add_field(
                name="Category",
                value=getattr(
                    ctx.guild.get_channel(result.category_id), "mention", "N/A"
                ),
            )
            .add_field(
                name="Logs",
                value=getattr(ctx.guild.get_channel(result.logs_id), "mention", "N/A"),
            )
            .add_field(
                name="Panel message",
                value=f"```{result.panel_message}```",
                inline=False,
            )
            .add_field(
                name="Open message", value=f"```{result.open_message}```", inline=False
            )
            .set_footer(text="scare.life", icon_url=self.bot.user.display_avatar.url)
        )

        return await ctx.reply(embed=embed)

    @ticket.command(name="send")
    @has_permissions(manage_guild=True)
    async def ticket_send(
        self: "Configuration",
        ctx: Context,
        *,
        channel: discord.TextChannel = CurrentChannel,
    ):
        """
        Send the ticket panel
        """

        if not (
            panel := await self.bot.db.fetchval(
                "SELECT panel_message FROM tickets WHERE guild_id = $1", ctx.guild.id
            )
        ):
            return await ctx.alert("The panel feature is **not** enabled")

        script = await self.bot.embed.convert(ctx.author, panel)
        script.pop("delete_after", None)
        script["view"] = TicketView()
        await channel.send(**script)
        return await ctx.confirm(f"Sent ticket panel message to {channel}")

    @ticket.command(name="open")
    @has_permissions(manage_guild=True)
    async def ticket_open(self: "Configuration", ctx: Context, *, message: str):
        """
        Configure your ticket open message through embed scripting
        """

        script = await self.bot.embed.convert(ctx.author, message, {"topic": "Test"})

        script.pop("delete_after", None)
        script.pop("view", None)

        try:
            m = await ctx.send(**script)
            await self.bot.db.execute(
                """
                INSERT INTO tickets (guild_id, open_message)
                VALUES ($1,$2) ON CONFLICT (guild_id)
                DO UPDATE SET open_message = $2
                """,
                ctx.guild.id,
                message,
            )
            return await m.add_reaction("✅")
        except:
            return await ctx.alert("The ticket message was incorrectly scripted")

    @ticket.command(name="panel")
    @has_permissions(manage_guild=True)
    async def ticket_panel(self: "Configuration", ctx: Context, *, message: str):
        """
        Configure your ticket panel message through embed scripting
        """

        script = await self.bot.embed.convert(ctx.author, message)

        script.pop("delete_after", None)
        script.pop("view", None)

        try:
            m = await ctx.send(**script)
            await self.bot.db.execute(
                """
                INSERT INTO tickets (guild_id, panel_message)
                VALUES ($1,$2) ON CONFLICT (guild_id)
                DO UPDATE SET panel_message = $2
                """,
                ctx.guild.id,
                message,
            )
            return await m.add_reaction("✅")
        except:
            return await ctx.alert("The ticket message was incorrectly scripted")

    @ticket.command(name="support")
    @has_permissions(manage_guild=True)
    async def ticket_support(
        self: "Configuration", ctx: Context, *, target: Optional[Member] = None
    ):
        """
        Add or View the ticket support members
        """

        objects = (
            await self.bot.db.fetchval(
                """
            SELECT support FROM tickets
            WHERE guild_id = $1
            """,
                ctx.guild.id,
            )
            or []
        )

        if not target:
            if not objects:
                return await ctx.send_help(ctx.command)

            sup = [
                f"{ctx.guild.get_member(i).mention} (`{i}`)"
                for i in objects
                if ctx.guild.get_member(i)
            ]

            return await ctx.paginate(sup, Embed(title=f"Ticket support ({len(sup)})"))

        if target.id in objects:
            objects.remove(target.id)
            message = f"Removed {target.mention} as a ticket support"
        else:
            objects.append(target.id)
            message = f"Added {target.mention} as a ticket support"

        await self.bot.db.execute(
            """
            INSERT INTO tickets (guild_id, support)
            VALUES ($1,$2) ON CONFLICT (guild_id)
            DO UPDATE SET support = $2 
            """,
            ctx.guild.id,
            objects,
        )

        return await ctx.confirm(message)

    @ticket.command(name="logs")
    @has_permissions(manage_guild=True)
    async def ticket_logs(
        self: "Configuration",
        ctx: Context,
        *,
        channel: Union[TextChannel, Literal["none"]],
    ):
        """
        Configure the ticket logs channel
        """

        channel_id = getattr(channel, "id", None)

        await self.bot.db.execute(
            """
            INSERT INTO tickets (guild_id, logs_id) VALUES ($1,$2)
            ON CONFLICT (guild_id) DO UPDATE SET logs_id = $2  
            """,
            ctx.guild.id,
            channel_id,
        )

        return await ctx.confirm(
            f"Assigned your logs to {channel.mention}"
            if channel_id
            else "Removed the ticket logs"
        )

    @ticket.command(name="category")
    @has_permissions(manage_guild=True)
    async def ticket_category(
        self: "Configuration",
        ctx: Context,
        *,
        channel: Union[CategoryChannel, Literal["none"]],
    ):
        """
        Configure the ticket category
        """

        channel_id = getattr(channel, "id", None)

        await self.bot.db.execute(
            """
            INSERT INTO tickets (guild_id, category_id) VALUES ($1,$2)
            ON CONFLICT (guild_id) DO UPDATE SET category_id = $2  
            """,
            ctx.guild.id,
            channel_id,
        )

        return await ctx.confirm(
            f"Assigned your category to #{channel}"
            if channel_id
            else "Removed the ticket category"
        )

    @ticket.group(name="topic", aliases=["topics"], invoke_without_command=True)
    async def ticket_topic(self: "Configuration", ctx: Context):
        """
        Manage the ticket topics
        """

        return await ctx.send_help(ctx.command)

    @ticket_topic.command(name="clear")
    @has_permissions(administrator=True)
    async def ticket_topic_clear(self: "Configuration", ctx: Context):
        """
        Clear all the ticket topics
        """

        await self.bot.db.execute(
            """
            INSERT INTO tickets (guild_id, topics)
            VALUES ($1,$2) ON CONFLICT (guild_id)
            DO UPDATE SET topics = $2
            """,
            ctx.guild.id,
            [],
        )

        return await ctx.confirm("Cleared the ticket topics")

    @ticket_topic.command(name="add", example="reports, report a member in the server")
    @has_permissions(manage_guild=True)
    async def ticket_topic_add(self: "Configuration", ctx: Context, *, topic: str):
        """
        Add a ticket topic
        """

        topics = await self.bot.db.fetchval(
            "SELECT topics FROM tickets WHERE guild_id = $1", ctx.guild.id
        )

        if topics is None:
            topics = []

        match = re.match(r"([^,]*), (.*)", topic)

        if not match:
            return await ctx.alert(
                f"The topic name and description were given incorrectly. Please run `{ctx.clean_prefix}help ticket topic add` for more information"
            )

        label, description = match.groups()

        if item := next((m for m in topics if m["label"] == label), None):
            topics.remove(item)

        topics.append({"label": label, "description": description})
        await self.bot.db.execute(
            """
            INSERT INTO tickets (guild_id, topics)
            VALUES ($1,$2) ON CONFLICT (guild_id)
            DO UPDATE SET topics = $2
            """,
            ctx.guild.id,
            topics,
        )

        return await ctx.confirm(f"Added **{label}** as a ticket topic")

    @ticket_topic.command(name="remove", aliases=["rm"])
    @has_permissions(manage_guild=True)
    async def ticket_topic_remove(self: "Configuration", ctx: Context, *, topic: str):
        """
        Remove a ticket topic
        """

        topics = await self.bot.db.fetchval(
            "SELECT topics FROM tickets WHERE guild_id = $1", ctx.guild.id
        )

        if not topics:
            return await ctx.alert("There are **no** topics")

        if item := next((m for m in topics if m["label"] == topic), None):
            topics.remove(item)
        else:
            return await ctx.alert("This is **not** an available topic")

        await self.bot.db.execute(
            """
            INSERT INTO tickets (guild_id, topics)
            VALUES ($1,$2) ON CONFLICT (guild_id)
            DO UPDATE SET topics = $2
            """,
            ctx.guild.id,
            topics,
        )

        return await ctx.confirm(f"Removed **{topic}** from the ticket topic")

    @ticket_topic.command(name="view", aliases=["list"])
    async def ticket_topic_view(self: "Configuration", ctx: Context):
        """
        View the available ticket topics
        """

        topics = await self.bot.db.fetchval(
            "SELECT topics FROM tickets WHERE guild_id = $1", ctx.guild.id
        )

        if not topics:
            return await ctx.alert("There are **no** topics")

        topics = json.loads(topics)
        return await ctx.paginate(
            [f"**{k['label']}**: {k['description']}" for k in topics],
            Embed(title=f"Ticket topics ({len(topics)})"),
        )

    @group(aliases=["rr"], invoke_without_command=True)
    async def reactionrole(self: "Configuration", ctx: Context):
        """
        Manage self roles in the server
        """

        return await ctx.send_help(ctx.command)

    @reactionrole.command(name="clear")
    @has_permissions(administrator=True)
    async def rr_clear(self: "Configuration", ctx: Context, message: Optional[Message]):
        """
        Clear reaction roles from a message
        """

        r = await self.bot.db.execute(
            """
            DELETE FROM reactionroles 
            WHERE guild_id = $1 AND message_id = $2
            """,
            ctx.guild.id,
            message.id,
        )

        if r == "DELETE 0":
            return await ctx.alert(
                "There's no reactionrole associated with this message"
            )

        return await ctx.confirm(f"Cleared all reactionroles from {message.jump_url}")

    @reactionrole.command(name="remove", aliases=["rm"])
    @has_permissions(manage_guild=True)
    async def rr_remove(
        self: "Configuration",
        ctx: Context,
        message: discord.Message,
        emoji: DiscordEmoji,
    ):
        """
        Remove a reactionrole from a message
        """

        r = await self.bot.db.execute(
            """
            DELETE FROM reactionroles
            WHERE message_id = $1
            AND emoji = $2
            AND guild_id = $3 
            """,
            message.id,
            str(emoji),
            ctx.guild.id,
        )

        if r == "DELETE 0":
            return await ctx.alert(
                "There's no reactionrole associated with this message & emoji"
            )

        with suppress(Exception):
            await message.remove_reaction(emoji)

        return await ctx.confirm(
            f"Removed reactionrole {emoji} from {message.jump_url}"
        )

    @reactionrole.command(name="add")
    @has_permissions(manage_guild=True)
    async def rr_add(
        self: "Configuration",
        ctx: Context,
        message: discord.Message,
        emoji: DiscordEmoji,
        *,
        role: Annotated[Role, AssignableRole],
    ):
        """
        Add a reaction role to a message
        """

        if message.guild != ctx.guild:
            return await ctx.alert("This message is not from this server")

        r = await self.bot.db.execute(
            """
            INSERT INTO reactionroles
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (message_id, emoji)
            DO UPDATE SET role_id = $5  
            """,
            message.id,
            str(emoji),
            ctx.guild.id,
            message.channel.id,
            role.id,
        )

        if r.startswith("INSERT"):
            await message.add_reaction(emoji)

        return await ctx.confirm(
            f"Added {role.mention} ({str(emoji)}) as a reactionrole to {message.jump_url}"
        )

    @group(invoke_without_command=True)
    async def bumpreminder(self: "Configuration", ctx: Context):
        """
        Remind members whenever it's time to bump the server via disboard
        """

        return await ctx.send_help(ctx.command)

    @bumpreminder.command(name="enable", aliases=["e"])
    @has_permissions(manage_guild=True)
    async def bumpreminder_enable(self: "Configuration", ctx: Context):
        """
        Enable the Disboard bump reminder feature
        """

        r = await self.bot.db.execute(
            """
            INSERT INTO bumpreminder (guild_id)
            VALUES ($1) ON CONFLICT (guild_id)
            DO NOTHING  
            """,
            ctx.guild.id,
        )

        if r == "INSERT 0":
            return await ctx.alert("Bump reminder feature is **already** enabled")

        return await ctx.confirm("Enabled the bump reminder feature")

    @bumpreminder.command(name="disable", aliases=["dis"])
    @has_permissions(manage_guild=True)
    async def bumpreminder_disable(self: "Configuration", ctx: Context):
        """
        Disable the bump reminder feature
        """

        r = await self.bot.db.execute(
            "DELETE FROM bumpreminder WHERE guild_id = $1", ctx.guild.id
        )

        if r == "DELETE 0":
            return await ctx.alert("Bump reminder isn't enabled in this server")

        return await ctx.confirm("Disabled the bump reminder feature")

    @bumpreminder.command(name="thank")
    @has_permissions(manage_guild=True)
    async def bumpreminder_thank(self: "Configuration", ctx: Context, *, code: str):
        """
        Configure the bump thank you message
        """

        r = await self.bot.db.execute(
            """
            UPDATE bumpreminder SET 
            thank = $1 WHERE guild_id = $2
            """,
            code,
            ctx.guild.id,
        )

        if r == "UPDATE 0":
            return await ctx.alert("The bumpreminder feature is not enabled")

        return await ctx.confirm(
            f"Updated the bumpreminder thank response. To check it use `{ctx.clean_prefix}bumpreminder test thank`"
        )

    @bumpreminder.command(name="remind")
    @has_permissions(manage_guild=True)
    async def bumpreminder_remind(self: "Configuration", ctx: Context, *, code: str):
        """
        Configure the bump remind message
        """

        r = await self.bot.db.execute(
            """
            UPDATE bumpreminder SET 
            remind = $1 WHERE guild_id = $2 
            """,
            code,
            ctx.guild.id,
        )

        if r == "UPDATE 0":
            return await ctx.alert("The bumpreminder feature is not enabled")

        return await ctx.confirm(
            f"Updated the bumpreminder remind response. To check it use `{ctx.clean_prefix}bumpreminder test remind`"
        )

    @bumpreminder.command(name="test")
    @has_permissions(manage_guild=True)
    async def bumpreminder_test(
        self: "Configuration", ctx: Context, message_type: Literal["thank", "remind"]
    ):
        """
        Test a bumpreminder message
        """

        code = await self.bot.db.fetchval(
            f"""
            SELECT {message_type} FROM bumpreminder
            WHERE guild_id = $1   
            """,
            ctx.guild.id,
        )

        if not code:
            return await ctx.alert("The bumpreminder feature is not enabled")

        script = await self.bot.embed.convert(ctx.author, code)
        script.pop("delete_after", None)
        return await ctx.send(**script)


async def setup(bot: Scare) -> None:
    await bot.add_cog(Configuration(bot))
