from __future__ import annotations

import math
from asyncio import Queue, TimeoutError
from random import shuffle
from typing import TYPE_CHECKING, Dict, List, Literal, Union

from async_timeout import timeout
from discord import (
    Attachment,
    Embed,
    File,
    Guild,
    Member,
    Message,
    TextChannel,
    VoiceState,
)
from discord.ext import commands
from discord.ext.commands import BucketType, Cog, command, cooldown, has_permissions
from pomice import Equalizer, Node, NodePool, Player, Playlist, Timescale, Track
from pomice.exceptions import FilterTagAlreadyInUse, NoNodesAvailable, TrackLoadError

from structure.managers import Context
from structure.scare import Error, Scare
from structure.utilities import Percentage, Position, format_duration, shorten

if TYPE_CHECKING:
    from discord.abc import MessageableChannel


class _Player(Player):
    bot: "Scare"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._queue: Queue[Track] = Queue()
        self._track: Track = None

        self._invoke: MessageableChannel = None
        self._votes = set()

        self._wait: bool = None
        self._person: Member = None

        self._loop: Literal["track", "queue"] = False

    async def add(self: "_Player", track: Track, _push: bool = False) -> Track:
        self._queue._queue.insert(0, track) if _push else await self._queue.put(track)
        return track

    async def destroy(self):
        await self.bot.session.put(
            f"https://discord.com/api/v9/channels/{self.channel.id}/voice-status",
            headers={"Authorization": f"Bot {self.bot.http.token}"},
            json={"status": None},
        )
        return await super().destroy()

    async def next(self: "_Player") -> Track:
        if self.is_playing or self._wait:
            return

        self._wait = True
        if self._loop == "track" and self._track:
            pass
        else:
            try:
                async with timeout(60):
                    self._track = await self._queue.get()
                    await self.bot.session.put(
                        f"https://discord.com/api/v9/channels/{self.channel.id}/voice-status",
                        headers={"Authorization": f"Bot {self.bot.http.token}"},
                        json={"status": f"Playing {self._track.title}"},
                    )
            except TimeoutError:
                if self.bot.get_channel(self._invoke):
                    e = Embed(
                        color=self.bot.color,
                        description=f"> Left {self.channel.mention} due to 1 minute of inactivity",
                    )
                    await self.bot.get_channel(self._invoke).send(embed=e)

                return await self.destroy()

        self._wait = False

        if self._loop == "queue":
            await self._queue.put(self._track)

        try:
            await self.play(self._track)
            if self.bot.get_channel(self._invoke) and self._loop != "track":
                print(self._invoke)
                e = Embed(
                    color=self.bot.color,
                    description=f"> Now playing [**{self._track.title}**]({self._track.uri}) in {self.channel.mention} - {self._track.requester.mention}",
                )
                return await self.bot.get_channel(self._invoke).send(embed=e)

        except TrackLoadError:
            e = Embed(description=f"> I was unable to find that track!")
            return await self.bot.get_channel(self._invoke).send(embed=e)

    async def skip(self: "_Player") -> Track:
        if self.is_paused:
            await self.set_pause(False)
        return await self.stop()


class Music(Cog):
    def __init__(self, bot: Scare) -> None:
        self.bot: Scare = bot
        if not self.bot.isinstance:
            self.bot.loop.create_task(self.auth())

        self._emoji: Dict[str, str] = {
            "spotify": "<:spotify:1205347152189202452>",
            "youtube": "<:youtube:1205349586986602597>",
            "apple": "<:apple:1205348422568120331>",
            "soundcloud": "<:soundcloud:1205348161187487764>",
            "discord": "📁",
        }  # Mapping for emojis, useful for filtering.

    async def auth(self: "Music"):
        if not self.bot.node:
            self.bot.node = await NodePool().create_node(
                bot=self.bot,
                host="v4.lavalink.rocks",
                port=443,
                password="horizxon.tech",
                secure=True,
                identifier="MAIN",
                spotify_client_id="a3dbb60004c04ab78e434b2e5f13aa0d",
                spotify_client_secret="7ee6c0b22a2c47b5812c77d848329e17",
            )

        print(f"Made connection to the node {self.bot.node}")

    async def _votes(self: "Music", ctx: Context) -> int:
        player: _Player = await self.get_player(ctx)
        channel: TextChannel = self.bot.get_channel(int(player.channel.id))
        required = math.ceil((len(channel.members) - 1) / 2.5)

        required = 2 if len(channel.members) == 3 else required
        return required

    async def is_person(self: "Music", ctx: Context) -> bool:
        player: _Player = await self.get_player(ctx)
        return (
            ctx.author == player.current.requester
            or ctx.author.guild_permissions.kick_members
            or ctx.author.guild_permissions.administrator
            or ctx.author.id == self.bot.owner_id
        )

    @Cog.listener("on_guild_remove")
    async def guild_remove(self: "Music", guild: Guild):
        if hasattr(self.bot, "node") and (
            player := getattr(self.bot.node, "get_player", None)(guild.id)
        ):
            await player.destroy()

    @Cog.listener("on_pomice_track_exception")
    async def pomice_error(
        self: "Music", player: _Player, track: Track, reason: str
    ) -> None:
        if not reason:
            return

        server = self._info(player)
        error = (
            "Oh no, an error occurred while loading the track!\n"
            f"```py\n{reason}\n```"
        )
        user = "<@985235488262725732>"
        invite = await self._get_invite(server)

        await self._send_error(error, user, server["channel"], invite)

    async def _info(
        self: "Music", player: _Player
    ) -> Dict[str, Union[Guild, TextChannel, str]]:
        return {
            "name": player.guild.name,
            "id": player.guild.id,
            "channel": player.guild.get_channel(player._invoke),
            "invite": await self._get_invite(player.guild),
        }

    async def _get_invite(self: "Music", guild: Guild) -> str:
        invite = await guild.text_channels[0].create_invite(
            max_age=300, max_uses=1, unique=True
        )
        return invite.url

    async def _send_error(
        self: "Music", error: str, user: str, channel: str, invite: str
    ) -> None:
        channel = self.bot.get_channel(1219617239981101056)
        message = (
            f"{user}\n\nOh no, an error occurred while loading the track!\n"
            f"```py\n{error}\n```\n"
            f"Server: {channel} ({invite})\n"
        )
        return await channel.send(message)

    @Cog.listener("on_pomice_track_end")
    async def track_end(
        self: "Music", player: _Player, track: Track, reason: str
    ) -> None:
        await player.next()

    @Cog.listener("on_voice_state_update")
    async def track_state(
        self: "Music", member: Member, before: VoiceState, after: VoiceState
    ) -> None:
        if member.id == self.bot.user.id:
            player: _Player = getattr(self.bot.node, "get_player", None)(
                member.guild.id
            )
            if not player:
                return

            if member in before.channel.members and len(before.channel.members) == 1:
                return (
                    await player.destroy()
                )  # leaving if nobody is in the voice channel anymore

            if before.channel and not after.channel:
                voice = self.bot.get_channel(before.channel.id)
                if not voice:
                    await player.destroy()
                else:
                    channel = self.bot.get_channel(player._invoke)
                    await channel.send(
                        "I've been kicked or removed from the voice channel!"
                    )

            elif before.mute != after.mute:
                await self._handle_mute(player, after.mute)

    async def _handle_mute(self: "Music", player: _Player, muted: bool) -> None:
        await player.set_pause(muted)
        channel = player.guild.get_channel(player._invoke)
        message = (
            f"{'Awesome, I was' if not muted else 'Aww, I have been'} {'muted' if muted else 'unmuted'}. "
            f"I have {'resumed' if not muted else 'paused'} the {'current ' if not muted else ''}song!"
        )
        return await channel.alert(message) if muted else await channel.confirm(message)

    async def get_player(
        self: "Music", ctx: Context, *, connect: bool = False
    ) -> _Player:
        if not hasattr(self.bot, "node"):
            return Error("No connection to the node created!")

        if not (voice := ctx.author.voice):
            return Error("You're not in a voice channel!")

        elif (bot := ctx.guild.me.voice) and (voice.channel.id != bot.channel.id):
            return Error("You're not in my voice channel!")

        if not ctx.guild.me.voice or not (
            player := getattr(self.bot.node, "get_player", None)(ctx.guild.id)
        ):
            if not connect:
                return Error("I'm not connected to a voice channel!")
            else:
                try:
                    await ctx.author.voice.channel.connect(
                        cls=_Player, self_deaf=True, reconnect=True
                    )
                except NoNodesAvailable:
                    return Error("No connection to the node created!")

                player = getattr(self.bot.node, "get_player", None)(ctx.guild.id)
                player._invoke = ctx.channel.id
                player._person = ctx.author
                await player.set_volume(70)

        return player

    @command(
        name="play",
        usage="(query or URL)",
        example="Hospital better off stalking you",
        aliases=["p"],
    )
    @cooldown(1, 3.5, BucketType.user)
    async def play(
        self: "Music", ctx: Context, *, query: Union[str, Attachment, File]
    ) -> None:
        """
        Play a song in your voice channel
        """

        player: _Player = await self.get_player(ctx, connect=True)

        # Check if the player is an Error instance before proceeding
        if isinstance(player, Error):
            return await ctx.alert(str(player))  # Display the error message to the user

        query = (
            " ".join(attachment.url for attachment in ctx.message.attachments)
            if ctx.message.attachments
            else query
        )
        try:
            _result = await player.get_tracks(query=query, ctx=ctx)
        except TrackLoadError as e:
            print(e)
            return await ctx.alert("I was unable to find that track!")

        if isinstance(_result, Playlist):
            for track in _result.tracks:
                await player.add(track)

            await ctx.neutral(
                f"Added **{_result.track_count} tracks** from [**{_result.name}**]({_result.uri}) - {_result.tracks[0].requester.mention}!"
            )
        else:
            track = _result[0]
            await player.add(track)
            if player.is_playing:
                await ctx.neutral(
                    f"Added [**{track.title}**]({track.uri}) - {track.requester.mention}",
                )

        if not player.is_playing:
            await player.next()
            await ctx.message.add_reaction("✅")

        def format_duration(self, milliseconds: int) -> str:
            units = [
                ("day", 24 * 60 * 60 * 1000),
                ("hour", 60 * 60 * 1000),
                ("minute", 60 * 1000),
                ("second", 1000),
            ]

            time_format: List[str] = []

            for unit, divisor in units:
                value, milliseconds = divmod(milliseconds, divisor)
                if value > 0:
                    time_format.append(f"{value} {unit + 's' if value != 1 else unit}")

            return " and ".join(time_format) or "0 seconds"

    @command(
        name="current",
        aliases=["playing"],
        description="Shows the currently playing track.",
    )
    async def current(self: "Music", ctx: Context) -> None:
        """
        Check the current playing song
        """

        player: _Player = await self.get_player(ctx)
        loop_status = "**Looping** - " if player._loop else ""

        if not player.current:
            return await ctx.alert("Nothing is currently playing!")

        await ctx.neutral(
            (
                f"{loop_status}Currently playing [**{player.current.title}**]({player.current.uri}) "
                f"in {player.channel.mention} - {player.current.requester.mention} `"
                f"{format_duration(player.position)}`/`{format_duration(player.current.length)}`"
            )
        )

    @command(
        name="shuffle",
        description="Shuffles the track queue.",
    )
    @has_permissions(manage_messages=True)
    async def shuffle(self: "Music", ctx: Context) -> None:
        """
        Shuffle the song queue
        """

        player: _Player = await self.get_player(ctx)

        if not player.current:
            return await ctx.alert("Nothing is currently playing!")

        if not (queue := player._queue._queue):
            return await ctx.alert("The queue is currently empty!")

        shuffle(queue)
        await ctx.confirm("Queue shuffled successfully!")

    @command(
        name="seek",
        usage="(position)",
        example="+30s",
        aliases=["ff", "forward", "rw", "rewind"],
    )
    async def seek(self: "Music", ctx: Context, position: Position) -> None:
        """
        Seek to a specific position in the track
        """

        player: _Player = await self.get_player(ctx)

        if not player.current:
            return await ctx.alert("Nothing is currently playing!")

        if ctx.author.id != player.current.requester.id:
            return await ctx.alert("You can only seek the track you requested.")

        await player.seek(max(0, min(position, player.current.length)))
        await ctx.message.add_reaction("✅")

    @command(
        name="pause",
        aliases=["stop"],
    )
    async def pause(self: "Music", ctx: Context) -> None:
        """
        Pause the current track
        """

        player: _Player = await self.get_player(ctx)

        if player.is_paused:
            return await ctx.alert("There isn't a track playing!")

        await player.set_pause(True)
        await ctx.message.add_reaction("⏸️")

    @command(name="queue", aliases=["q", "tracks"])
    async def queue(self: "Music", ctx: Context) -> None:
        """
        Get the track queue
        """

        player: _Player = await self.get_player(ctx)

        if not (queue := player._queue._queue):
            return await ctx.alert("The queue is currently empty!")

        await ctx.paginate(
            [
                f"[**{shorten(track.title, length=25).replace('[', '(').replace(']', ')')}**]({track.uri}) - Requested by {track.requester.mention}"
                for track in player._queue._queue
            ],
            Embed(title=f"**Queue for {player.channel.mention}**"),
        )

    @command(name="resume", aliases=["unpause"])
    async def resume(self: "Music", ctx: Context) -> None:
        """
        Resume the current track
        """

        player: _Player = await self.get_player(ctx)

        if not player.is_paused:
            return await ctx.alert("The current track isn't paused!")

        await player.set_pause(False)
        await ctx.message.add_reaction("⏯️")

    @command(
        name="volume",
        usage="(percentage | limit = 200)",
        example="100%",
        aliases=["vol", "v"],
    )
    async def volume(self: "Music", ctx: Context, volume: Percentage = None) -> Message:
        """
        Change the volume of the player
        """

        player: _Player = await self.get_player(ctx)

        if not player.is_playing:
            return await ctx.alert("There isn't a track currently playing!")

        elif not volume:
            return await ctx.neutral(f"Volume: `{player.volume}%`")

        await player.set_volume(volume)
        await ctx.confirm(f"Set the volume to `{volume}%`")

    @command(name="skip", aliases=["sk", "next"])
    async def skip(self: "Music", ctx: Context) -> None:
        """
        Skip the current track
        """

        player: _Player = await self.get_player(ctx)

        if not player.current:
            return await ctx.alert("Nothing is currently playing!")

        if ctx.author.id == player.current.requester.id:
            await player.skip()
            return await ctx.message.add_reaction("👍")

        required = await self._votes(ctx)
        player._votes.add(ctx.author)

        if len(player._votes) >= required:
            await ctx.send(
                "Vote to skip passed, skipping the current song.", delete_after=10
            )

            player._votes.clear()
            await player.skip()
            await ctx.message.add_reaction("👍")
        else:
            return await ctx.send(
                f"{ctx.author.mention} has voted to skip the song, current amount of votes: {len(player._votes)}/{required} ",
                delete_after=10,
            )

    @command()
    @has_permissions(manage_messages=True)
    async def clearqueue(self: "Music", ctx: Context) -> None:
        """
        Clear the current queue
        """

        player: _Player = await self.get_player(ctx)
        if not self.is_person(ctx):
            return await ctx.alert("Only authorized people can use this command!")

        if not (queue := player._queue._queue):
            return await ctx.alert("The queue is empty!")

        queue.clear()
        await ctx.message.add_reaction("🧹")

    @command(name="loop", aliases=["repeat"])
    async def loop(self: "Music", ctx: Context) -> None:
        """
        Toggle loop the current song
        """

        player: _Player = await self.get_player(ctx)

        if not player.is_playing:
            return await ctx.alert("There isn't a track currently playing!")

        player._loop = False if player._loop == "track" else "track"
        status = "disabled" if player._loop == False else "enabled"

        await ctx.confirm(f"Looping is now **{status}** for the current track.")

    @command(name="move", usage="(current index) (new index)", example="2 1")
    @has_permissions(manage_messages=True)
    async def move(self: "Music", ctx: Context, index: int, new: int) -> Message:
        """
        Move a track from the queue in a different position
        """

        player: _Player = await self.get_player(ctx)

        if not (queue := player._queue._queue):
            return await ctx.alert("The queue is empty!")

        if not (1 <= index <= len(queue)):
            return await ctx.alert(
                f"The index has to be between `1` and `{len(queue)}`!"
            )

        if not (1 <= new <= len(queue)):
            return await ctx.alert(
                f"The new index has to be between `1` and `{len(queue)}`!"
            )

        track = queue[index - 1]
        del queue[index - 1]
        queue.insert(new - 1, track)

        return await ctx.confirm(
            f"Moved [**{track.title}**]({track.uri}) to index `{new}`!"
        )

    @command(name="remove", usage="(index)", example="2")
    @has_permissions(manage_messages=True)
    async def remove(self: "Music", ctx: Context, index: int) -> Message:
        """
        Remove a track from the queue
        """

        player: _Player = await self.get_player(ctx)

        if not (queue := player._queue._queue):
            return await ctx.alert("The queue is empty!")

        if not (1 <= index <= len(queue)):
            return await ctx.alert(
                f"The index has to be between `1` and `{len(queue)}`!"
            )

        track = queue[index - 1]
        del queue[index - 1]

        return await ctx.confirm(
            f"Removed [**{track.title}**]({track.uri}) from the queue!"
        )

    @command(
        name="applyfilter", aliases=["af", "ap"], usage="(preset)", example="boost"
    )
    async def apply_filter(self: "Music", ctx: Context, preset: str):
        """
        Apply a filter to the audio
        """

        player: _Player = await self.get_player(ctx)

        if not await self.is_person(ctx):
            return await ctx.alert("You are not authorized to apply filters.")

        valid = {
            "boost": Equalizer.boost(),
            "flat": Equalizer.flat(),
            "metal": Equalizer.metal(),
            "piano": Equalizer.piano(),
            "vaporwave": Timescale.vaporwave(),
            "nightcore": Timescale.nightcore(),
        }
        if preset not in valid:
            return await ctx.alert(
                f"Invalid filter. Available filters: {', '.join([f'`{filter}`' for filter in valid])}"
            )
        try:
            await self.apply_preset(ctx, preset)
            await ctx.confirm(f"Filter `{preset}` applied!")
        except FilterTagAlreadyInUse:
            await ctx.alert(f"Filter `{preset}` already in use!")

    async def apply_preset(self: "Music", ctx: Context, preset: str):
        player: _Player = await self.get_player(ctx)
        mapping = {
            "boost": Equalizer.boost,
            "flat": Equalizer.flat,
            "metal": Equalizer.metal,
            "piano": Equalizer.piano,
            "vaporwave": Timescale.vaporwave,
            "nightcore": Timescale.nightcore,
        }

        method = mapping.get(preset)
        await player.add_filter(method(), fast_apply=True)

    @command(name="resetfilters", aliases=["rf"])
    async def reset_filters(self, ctx: Context):
        """
        Reset the applied filters
        """

        player: _Player = await self.get_player(ctx)
        await player.reset_filters(fast_apply=True)
        await ctx.confirm("All filters reset!")

    @command(name="listfilters", aliases=["filters", "availablefilters"])
    async def list_filters(self: "Music", ctx: Context) -> None:
        """
        List all available filters
        """

        valid = ["boost", "flat", "metal", "piano", "vaporwave", "nightcore"]

        filters = [f"`{filter}`" for filter in valid]

        await ctx.neutral(f"Available filters: {', '.join(filters)}")

    @command(name="disconnect", aliases=["dc"])
    async def disconnect(self: "Music", ctx: Context) -> None:
        """
        Disconenct the bot from the voice channel
        """

        player: _Player = await self.get_player(ctx)

        """
        if not await self.is_person(ctx):
            return await ctx.alert("You are not authorized to disconnect the bot.")
        """

        await player.destroy()
        await ctx.message.add_reaction("👋")


async def setup(bot: Scare):
    await bot.add_cog(Music(bot))
