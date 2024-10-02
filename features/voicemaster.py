import asyncio
import json
from asyncio import Lock
from collections import defaultdict

import discord
from discord.ext import commands

from structure.managers.context import Context
from structure.scare import Scare
from structure.utilities import VoiceMasterView


def is_vc_owner():
    async def predicate(ctx: Context):
        channel = getattr(ctx.author.voice, "channel", None)

        if not channel:
            await ctx.alert("You are **not** in a voice channel")
            return False

        results = await ctx.bot.db.fetchval(
            "SELECT voice_channels FROM voicemaster WHERE guild_id = $1", ctx.guild.id
        )

        if not results:
            await ctx.alert("The voicemaster feature is not configured in this server")
            return False

        voice_channels: dict = json.loads(results)

        if not str(channel.id) in voice_channels.keys():
            await ctx.alert("You are **not** in a voice channel created by me")
            return False

        if voice_channels[str(channel.id)] != ctx.author.id:
            await ctx.alert("You do **not** own this voice channel")
            return False

        return True

    return commands.check(predicate)


class VoiceMaster(commands.Cog):
    def __init__(self, bot: Scare):
        self.bot = bot
        self.locks = defaultdict(Lock)

    async def build_interface(self: "VoiceMaster", ctx: Context):
        channel_id = await self.bot.db.fetchval(
            "SELECT channel_id FROM voicemaster WHERE guild_id = $1", ctx.guild.id
        )

        if not (channel := ctx.guild.get_channel(channel_id)):
            raise commands.BadArgument("The voicemaster feature is **not** configured")

        embed = discord.Embed(
            color=self.bot.color,
            title="Voicemaster Interface",
            description=f"Manage your custom voice channel.\nYou can create one by joining {channel.mention}",
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

        return {"embed": embed, "view": VoiceMasterView()}

    async def create_temporary_channel(
        self: "VoiceMaster",
        member: discord.Member,
        after: discord.VoiceState,
        vcs: dict,
    ):
        channel = await member.guild.create_voice_channel(
            name=f"{member.name}'s channel",
            category=after.channel.category,
            overwrites=after.channel.overwrites,
            rtc_region=after.channel.rtc_region,
            reason="Creating a temporary channel",
        )

        try:
            vcs[channel.id] = member.id
            await self.bot.db.execute(
                "UPDATE voicemaster SET voice_channels = $1 WHERE guild_id = $2",
                json.dumps(vcs),
                member.guild.id,
            )
            return await member.move_to(channel)
        except discord.HTTPException:
            return await channel.delete()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self: "VoiceMaster",
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if result := await self.bot.db.fetchrow(
            "SELECT * FROM voicemaster WHERE guild_id = $1", member.guild.id
        ):
            if after.channel != before.channel:
                async with self.locks[member.guild.id]:
                    if channel := member.guild.get_channel(result.channel_id):
                        vcs = json.loads(result.voice_channels)
                        if len(channel.category.channels) > 50:
                            return await member.move_to(None)

                        if (
                            after.channel == channel
                            and getattr(before.channel, "category", None)
                            != channel.category
                        ):
                            return await self.create_temporary_channel(
                                member, after, vcs
                            )

                        elif (
                            before.channel in channel.category.channels
                            and before.channel != channel
                        ):
                            if (
                                len(before.channel.members) == 0
                                and str(before.channel.id) in vcs.keys()
                            ):
                                if after.channel == channel:
                                    return await member.move_to(before.channel)
                                elif before.channel != channel:
                                    vcs.pop(before.channel.id, None)
                                    await self.bot.db.execute(
                                        "UPDATE voicemaster SET voice_channels = $1 WHERE guild_id = $2",
                                        json.dumps(vcs),
                                        member.guild.id,
                                    )
                                    await before.channel.delete()

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def interface(self, ctx: Context):
        """
        Send the voicemaster interface to a channel
        """

        kwargs = await self.build_interface(ctx)
        await ctx.message.delete()
        return await ctx.send(**kwargs)

    @commands.hybrid_group(invoke_without_command=True, aliases=["vm"])
    async def voicemaster(self: "VoiceMaster", ctx: Context) -> discord.Message:
        """
        Configure custom temporary voice channels in your server
        """

        return await ctx.send_help(ctx.command)

    @voicemaster.command(name="enable", aliases=["e", "set", "setup"])
    @commands.has_permissions(manage_guild=True)
    async def voicemaster_setup(self: "VoiceMaster", ctx: Context):
        """
        Setup the voicemaster feature
        """

        result = await self.bot.db.fetchrow(
            "SELECT * FROM voicemaster WHERE guild_id = $1", ctx.guild.id
        )

        if result:
            return await ctx.alert(f"The VoiceMaster feature is **already** configured")

        category = await ctx.guild.create_category(name="Voice Channels")
        interface = await ctx.guild.create_text_channel(
            name="interface",
            category=category,
            overwrites={
                ctx.guild.default_role: discord.PermissionOverwrite(send_messages=False)
            },
        )
        channel = await ctx.guild.create_voice_channel(
            name="Join To Create", category=category
        )

        await self.bot.db.execute(
            "INSERT INTO voicemaster (guild_id, channel_id) VALUES ($1,$2)",
            ctx.guild.id,
            channel.id,
        )
        kwargs = await self.build_interface(ctx)
        await interface.send(**kwargs)
        return await ctx.confirm("Configured the VoiceMaster feature")

    @voicemaster.command(name="disable", aliases=["delete", "del", "remove", "rem"])
    @commands.has_permissions(manage_guild=True)
    async def voicemaster_disable(self: "VoiceMaster", ctx: Context):
        """
        Disable the voicemaster feature
        """

        result = await self.bot.db.fetchrow(
            "SELECT * FROM voicemaster WHERE guild_id = $1", ctx.guild.id
        )

        if not result:
            return await ctx.alert("VoiceMaster feature is **not** enabled")

        voice_channels = [ctx.guild.get_channel(result.channel_id)]
        vcs = json.loads(result.voice_channels)
        voice_channels.extend([ctx.guild.get_channel(i) for i in vcs.keys()])
        await asyncio.gather(
            *[channel.delete() for channel in voice_channels if channel]
        )
        try:
            await voice_channels[0].category.delete()
        except:
            pass

        await self.bot.db.execute(
            "DELETE FROM voicemaster WHERE guild_id = $1", ctx.guild.id
        )

        return await ctx.confirm("Disabled the VoiceMaster feature")

    @commands.hybrid_group(aliases=["vc"], invoke_without_command=True)
    async def voice(self: "VoiceMaster", ctx: Context) -> discord.Message:
        """
        Control your custom temprary voice channel
        """

        return await ctx.send_help(ctx.command)

    @voice.command(name="rename")
    @is_vc_owner()
    async def vc_rename(self: "VoiceMaster", ctx: Context, *, name: str):
        """
        Rename your temporary custom voice channel
        """

        await ctx.author.voice.channel.edit(name=name)
        return await ctx.confirm(f"Changed the channel's name to: {name}")

    @voice.command(name="hide", aliases=["ghost"])
    @is_vc_owner()
    async def voice_hide(self: "VoiceMaster", ctx: Context):
        """
        Hide your custom temporaray voice channel
        """

        if (
            ctx.author.voice.channel.permissions_for(
                ctx.guild.default_role
            ).view_channel
            != False
        ):
            await ctx.author.voice.channel.set_permissions(
                ctx.guild.default_role, view_channel=False
            )

            return await ctx.confirm(f"Hidden {ctx.author.voice.channel.mention}")

        return await ctx.alert(
            f"{ctx.author.voice.channel.mention} is **already** hidden"
        )

    @voice.command(name="reveal", aliases=["unghost"])
    @is_vc_owner()
    async def voice_reveal(self: "VoiceMaster", ctx: Context):
        """
        Reveal your custom temporary voice channel
        """

        if (
            ctx.author.voice.channel.permissions_for(
                ctx.guild.default_role
            ).view_channel
            == False
        ):
            await ctx.author.voice.channel.set_permissions(
                ctx.guild.default_role, view_channel=True
            )

            return await ctx.confirm(f"Revealed {ctx.author.voice.channel.mention}")

        return await ctx.alert(
            f"{ctx.author.voice.channel.mention} is **already** revealed"
        )

    @voice.command(name="lock")
    @is_vc_owner()
    async def voice_lock(self: "VoiceMaster", ctx: Context):
        """
        Lock your temporary custom voice channel
        """

        if (
            ctx.author.voice.channel.permissions_for(ctx.guild.default_role).connect
            != False
        ):
            await ctx.author.voice.channel.set_permissions(
                ctx.guild.default_role, connect=False
            )

            return await ctx.confirm(f"Locked {ctx.author.voice.channel.mention}")

        return await ctx.alert(
            f"{ctx.author.voice.channel.mention} is **already** locked"
        )

    @voice.command(name="unlock")
    @is_vc_owner()
    async def voice_unlock(self: "VoiceMaster", ctx: Context):
        """
        Unlock your temporary custom voice channel
        """

        if (
            ctx.author.voice.channel.permissions_for(ctx.guild.default_role).connect
            == False
        ):
            await ctx.author.voice.channel.set_permissions(
                ctx.guild.default_role, connect=True
            )

            return await ctx.confirm(f"Unlocked {ctx.author.voice.channel.mention}")

        return await ctx.alert(f"{ctx.author.voice.channel.mention} is **not** locked")

    @voice.command(name="allow", aliases=["permit"])
    @is_vc_owner()
    async def voice_allow(self: "VoiceMaster", ctx: Context, *, member: discord.Member):
        """
        Allow a member to join your temporary custom voice channel
        """

        await ctx.author.voice.channel.set_permissions(
            member, connect=True, view_channel=True
        )

        return await ctx.confirm(
            f"{member.mention} is **allowed** to join {ctx.author.voice.channel.mention}"
        )

    @voice.command(name="restrict", aliases=["ban"])
    @is_vc_owner()
    async def voice_ban(self: "VoiceMaster", ctx: Context, *, member: discord.Member):
        """
        Kick someone from the voice channel and restrict their access
        """

        if member == ctx.author:
            return await ctx.alert("This can't be you")

        await ctx.author.voice.channel.set_permissions(
            member,
            connect=ctx.author.voice.channel.permissions_for(
                ctx.guild.default_role
            ).connect,
            view_channel=ctx.author.voice.channel.permissions_for(
                ctx.guild.default_role
            ).view_channel,
        )

        if member in ctx.author.voice.channel.members:
            await member.move_to(None)

        return await ctx.confirm(
            f"Restricted access for {member.mention} to this voice channel"
        )

    @voice.command(name="disconnect", aliases=["kick"])
    @is_vc_owner()
    async def voice_disconnect(
        self: "VoiceMaster", ctx: Context, *, member: discord.Member
    ):
        """
        Disconnect a member from your custom temporary voice channel
        """

        if member == ctx.author:
            return await ctx.alert("You cannot kick yourself")

        members = [m for m in ctx.author.voice.channel.members if m != ctx.author]

        if not member in members:
            return await ctx.alert("This member is **not** in your voice channel")

        await member.move_to(None)
        return await ctx.confirm(f"Kicked {member.mention} from your voice channel")

    @voice.command(name="claim")
    async def voice_claim(self: "VoiceMaster", ctx: Context):
        """
        Claim the ownership of the voice channel you are in
        """

        channel = getattr(ctx.author.voice, "channel", None)

        if not channel:
            return await ctx.alert("You are **not** in a voice channel")

        voice_channels: dict = json.loads(
            await self.bot.db.fetchval(
                "SELECT voice_channels FROM voicemaster WHERE guild_id = $1",
                ctx.guild.id,
            )
        )

        voice = next(
            ((x, y) for x, y in voice_channels.items() if x == str(channel.id)), None
        )

        if not voice:
            return await ctx.alert("You are **not** in a voice channel created by me")

        if voice[1] in map(lambda m: m.id, channel.members):
            return await ctx.alert("The owner is still in the voice channel")

        voice_channels[str(channel.id)] = ctx.author.id

        await self.bot.db.execute(
            "UPDATE voicemaster SET voice_channels = $1 WHERE guild_id = $2",
            json.dumps(voice_channels),
            ctx.guild.id,
        )

        return await ctx.confirm("You have claimed the ownership of this voice channel")


async def setup(bot: Scare) -> None:
    return await bot.add_cog(VoiceMaster(bot))
