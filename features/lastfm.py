import json
import asyncio
from collections import defaultdict
from io import BytesIO
from typing import Annotated, List, Literal, Optional, Union

import numpy as np
import pandas as pd
from discord import Embed, File, Member, Message, User, app_commands
from discord.ext.commands import (
    Author, 
    Cog, 
    hybrid_command, 
    hybrid_group, 
    is_donator
)

from structure.scare import Scare
from structure.managers import Context, ratelimiter
from structure.utilities import ChartSize, FMHandler, Playing, plural

class LastFM(Cog):
    def __init__(self, bot: Scare):
        self.bot: Scare = bot
        self.handler = FMHandler()
        self.locks = defaultdict(asyncio.Lock)

    @Cog.listener()
    async def on_message(self, message: Message):
        if cmd := await self.bot.db.fetchval(
            "SELECT command FROM lastfm.user WHERE user_id = $1", message.author.id
        ):
            if message.content == cmd:
                if not ratelimiter(
                    bucket=f"lf-{message.channel.id}", key="lf", rate=3, per=2
                ):
                    ctx = await self.bot.get_context(message)
                    return await ctx.invoke(
                        self.bot.get_command("np"), member=message.author
                    )

    @hybrid_command(name="nowplaying", aliases=["fm", "np"])
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def nowplaying(
        self: "LastFM", 
        ctx: Context, 
        *, 
        member: Member = Author
    ):
        """
        View a users currently playing track
        """

        if not (
            result := await self.bot.db.fetchrow(
                """
                SELECT * FROM lastfm.user
                WHERE user_id = $1
                """,
                member.id,
            )
        ):
            return await ctx.alert(
                f"You don't have a LastFM username set!"
                if member == ctx.author
                else f"{member.mention} doesn't have a LastFM username set!"
            )

        data: Playing = await self.handler.playing(result["username"])
        
        if result['embed']:
            kwargs = await self.bot.embed.convert(
                member, 
                result['embed'], 
                {'lastfm': data}
            )
        else:
            e = Embed(
                description=(
                    f"### **{data.track.hyper}** \n"
                    f"by **{data.artist.name}**\n"
                    f"on **{data.album.name}**"
                ),
            )
    
            e.set_author(name=data.user.username, icon_url=data.user.avatar)
    
            e.set_thumbnail(url=data.track.image)
            kwargs = {'embed': e}

        msg = await ctx.send(**kwargs)

        if ctx.guild:
            await msg.add_reaction("🔥")
            return await msg.add_reaction("🗑️")

    @hybrid_group(name="lastfm", aliases=["lf", "lfm"], invoke_without_command=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def lastfm(self: "LastFM", ctx: Context) -> Message:
        """
        Interact with LastFM through our bot
        """

        return await ctx.send_help(ctx.command)

    @lastfm.command(name="link", aliases=["set", "connect"])
    async def lastfm_link(self: "LastFM", ctx: Context, username: str) -> Message:
        """
        Connect your LastFM account
        """
        data = await self.handler.profile(username)

        if not data:
            return await ctx.alert(
                f"The LastFM profile [`@{username}`](https://last.fm/user/{username}) is invalid!"
            )

        await self.bot.db.execute(
            """
            INSERT INTO lastfm.user (
                user_id,
                username
            ) VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET username = $2
            """,
            ctx.author.id,
            data.username,
        )

        await self.bot.db.execute(
            "DELETE FROM lastfm.crowns WHERE user_id = $1", ctx.author.id
        )
        return await ctx.confirm(
            f"Successfully connected your LastFM [`@{data.username}`](https://last.fm/user/{data.username}) with {self.bot.user.name}!"
        )

    @lastfm.command(name="unlink", aliases=["disconnect"])
    async def lastfm_unlink(
        self: "LastFM",
        ctx: Context,
    ):
        """
        Disconnect your LastFM from our bot
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM lastfm.user 
            WHERE user_id = $1
            """,
            ctx.author.id,
        )
        if result == "DELETE 0":
            return await ctx.alert(
                f"Your LastFM isn't connected with {self.bot.user.name}!"
            )

        await self.bot.db.execute(
            "DELETE FROM lastfm.crowns WHERE user_id = $1", ctx.author.id
        )
        return await ctx.confirm(
            f"Successfully disconnected your LastFM account from {self.bot.user.name}!"
        )

    @lastfm.command(name="crowns")
    async def lf_crowns(self, ctx: Context, *, member: Optional[User] = Author):
        """
        Get the amount of crowns a person has
        """

        count = await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM lastfm.crowns WHERE user_id = $1", member.id
        )
        return await ctx.confirm(
            f"{'You have' if member == ctx.author else f'{member.mention} has'} `{count}` crowns"
        )

    @lastfm.command(name="topcrowns", aliases=["tc"])
    async def lf_topcrowns(self, ctx: Context):
        """
        Get the list of people with most crowns claimed
        """

        results: List[int] = list(
            filter(
                lambda m: self.bot.get_user(m),
                map(
                    lambda r: r["user_id"],
                    await self.bot.db.fetch("SELECT user_id FROM lastfm.crowns"),
                ),
            )
        )

        if not results:
            return await ctx.alert("Nobody claimed a crown")

        panda = pd.Series(results)
        user_ids, counts = np.unique(panda, return_counts=True)
        values = zip(user_ids, counts)

        return await ctx.paginate(
            [
                f"**{self.bot.get_user(k)}** ({plural(v):crown})"
                for k, v in sorted(values, key=lambda m: m[1], reverse=True)
            ],
            Embed(title="Top Crowns"),
        )

    @lastfm.group(name="friends", aliases=["friend"], invoke_without_command=True)
    async def lastfm_friend(self, ctx: Context):
        """
        Add friends on LastFM
        """

        return await ctx.send_help(ctx.command)

    @lastfm_friend.command(name="add")
    async def lastfm_friend_add(self, ctx: Context, *, member: User):
        """
        Add a friend on lastfm
        """

        friends = (
            await self.bot.db.fetchval(
                "SELECT friends FROM lastfm.user WHERE user_id = $1", ctx.author.id
            )
            or []
        )

        if member.id in friends:
            return await ctx.alert("This member is **already** your lastfm friend")

        if not await self.bot.db.fetchrow(
            "SELECT * FROM lastfm.user WHERE user_id = $1", member.id
        ):
            return await ctx.alert(
                f"This member does not have a LastFM account linked with {self.bot.user.name}"
            )

        friends.append(member.id)

        r = await self.bot.db.execute(
            "UPDATE lastfm.user SET friends = $1 WHERE user_id = $2",
            friends,
            ctx.author.id,
        )

        if r == "UPDATE 0":
            return await ctx.alert(
                f"Your LastFM isn't connected with {self.bot.user.name}!"
            )

        return await ctx.confirm(f"Added {member.mention} as a LastFM friend")

    @lastfm_friend.command(name="remove", aliases=["rem", "rm"])
    async def lastfm_friend_remove(self, ctx: Context, *, member: User):
        """
        Remove a LastFM friend
        """

        friends = (
            await self.bot.db.fetchval(
                "SELECT friends FROM lastfm.user WHERE user_id = $1", ctx.author.id
            )
            or []
        )

        if not member.id in friends:
            return await ctx.alert("This member is **not** your lastfm friend")

        friends.remove(member.id)

        r = await self.bot.db.execute(
            "UPDATE lastfm.user SET friends = $1 WHERE user_id = $2",
            friends,
            ctx.author.id,
        )

        if r == "UPDATE 0":
            return await ctx.alert(
                f"Your LastFM isn't connected with {self.bot.user.name}!"
            )

        return await ctx.confirm(
            f"Removed {member.mention} from your LastFM friends list"
        )

    @lastfm_friend.command(name="list")
    async def lastfm_friend_list(self, ctx: Context):
        """
        Get a list of all your LastFm friends
        """

        friends = await self.bot.db.fetchval(
            "SELECT friends FROM lastfm.user WHERE user_id = $1", ctx.author.id
        )

        if not friends:
            return await ctx.alert("You do not have any LastFM friend")

        return await ctx.paginate(
            [f"<@{fr}>" for fr in friends],
            Embed(title=f"LastFM friends ({len(friends)})"),
        )

    @lastfm.command(name="friendswhoknows", aliases=["fwk"])
    async def lastfm_friendswhoknows(
        self, ctx: Context, *, artist: Optional[str] = None
    ):
        """
        Get the top listeners of a specific artist from all ur friends
        """

        if not (
            result := await self.bot.db.fetchrow(
                """
                SELECT username, friends FROM lastfm.user
                WHERE user_id = $1
                """,
                ctx.author.id,
            )
        ):
            return await ctx.alert("You don't have a LastFM username set!")

        if not result.friends:
            return await ctx.alert("You do not have LastFM friends")

        if not artist:
            recent: Playing = await self.handler.playing(result.username)
            artist = recent.artist.name

        async with self.locks[ctx.channel.id]:
            async with ctx.typing():
                result.friends.append(ctx.author.id)
                friends = ", ".join(map(str, result.friends))
                results = await self.bot.db.fetch(
                    f"SELECT user_id, username FROM lastfm.user WHERE user_id IN ({friends})"
                )
                whoknows = await self.handler.whoknows(artist, results)

                return await ctx.paginate(
                    [
                        f"[`@{self.bot.get_user(r.user_id)}`](https://last.fm/user/{r.username}) ({plural(r.plays):play})"
                        for r in whoknows
                        if self.bot.get_user(r.user_id)
                    ],
                    Embed(title=f"Who knows {artist}?"),
                )

    @lastfm.command(name="globalwhoknows", aliases=["gwk"])
    async def lastfm_globalwhoknows(
        self, ctx: Context, *, artist: Optional[str] = None
    ):
        """
        Get the top listeners of a specific artist from all servers that have scare
        """

        if not (
            username := await self.bot.db.fetchval(
                """
                SELECT username FROM lastfm.user
                WHERE user_id = $1
                """,
                ctx.author.id,
            )
        ):
            return await ctx.alert("You don't have a LastFM username set!")

        if not artist:
            recent: Playing = await self.handler.playing(username)
            artist = recent.artist.name

        async with self.locks[ctx.channel.id]:
            async with ctx.typing():
                results = await self.bot.db.fetch(
                    "SELECT user_id, username FROM lastfm.user"
                )
                whoknows = list(
                    filter(
                        lambda r: self.bot.get_user(r.user_id),
                        await self.handler.whoknows(artist, results),
                    )
                )

                ids = list(map(lambda r: r.user_id, whoknows))

                try:
                    position = ids.index(ctx.author.id)
                    footer = f"\u2022 Your position: #{position+1}"
                except ValueError:
                    position = -1
                    footer = None

                embeds = [
                    Embed(
                        title=f"Who knows {artist}?",
                        description="\n".join(
                            f"`{idx}.` [`@{self.bot.get_user(r.user_id)}`](https://last.fm/user/{r.username}) ({plural(r.plays):play})"
                            for idx, r in enumerate(whoknows[:10], start=1)
                        ),
                    ).set_footer(
                        text=f"Total listeners of this artist: {len(whoknows)} {footer or ''}"
                    )
                ]

                r = await self.bot.db.execute(
                    """
                    INSERT INTO lastfm.crowns VALUES ($1,$2)
                    ON CONFLICT (artist) DO UPDATE SET
                    user_id = $2
                    """,
                    artist.lower(),
                    whoknows[0].user_id,
                )

                if r.endswith("1"):
                    embeds.append(
                        Embed(
                            description=f"> 👑 **{self.bot.get_user(whoknows[0].user_id)}** has claimed the crown for **{artist.lower()}**"
                        )
                    )

                return await ctx.reply(embeds=embeds)

    @lastfm.command(name="whoknows", aliases=["wk"])
    async def lastfm_whoknows(self, ctx: Context, *, artist: Optional[str] = None):
        """
        Get the top listeners in this server of a specific artist
        """

        if not (
            username := await self.bot.db.fetchval(
                """
                SELECT username FROM lastfm.user
                WHERE user_id = $1
                """,
                ctx.author.id,
            )
        ):
            return await ctx.alert("You don't have a LastFM username set!")

        if not artist:
            recent: Playing = await self.handler.playing(username)
            artist = recent.artist.name

        async with self.locks[ctx.channel.id]:
            async with ctx.typing():
                members = tuple(map(lambda m: m.id, ctx.guild.members))
                results = await self.bot.db.fetch(
                    f"SELECT user_id, username FROM lastfm.user WHERE user_id IN {members}"
                )
                whoknows = await self.handler.whoknows(artist, results)

                return await ctx.paginate(
                    [
                        f"[`@{ctx.guild.get_member(r.user_id)}`](https://last.fm/user/{r.username}) ({plural(r.plays):play})"
                        for r in whoknows
                    ],
                    Embed(title=f"Who knows {artist} in {ctx.guild}?"),
                )

    @lastfm.command(name="toptracks", aliases=["tracks", "tt"])
    async def lastfm_toptracks(
        self: "LastFM",
        ctx: Context,
        member: Union[Member, User] = Author,
        timeframe: Literal["weekly", "monthly", "yearly"] = "overall",
    ):
        """
        View a users top tracks from a certain timeframe
        """

        if not (
            username := await self.bot.db.fetchval(
                """
                SELECT username FROM lastfm.user
                WHERE user_id = $1
                """,
                member.id,
            )
        ):
            return await ctx.alert(
                f"You don't have a LastFM username set!"
                if member == ctx.author
                else f"{member.mention} doesn't have a LastFM username set!"
            )

        await ctx.typing()
        results = await self.handler.top(
            username=username, type_="tracks", period=timeframe, limit=100
        )

        return await ctx.paginate(
            [
                f"{result.track.hyper} by {result.artist.hyper} ({plural(result.track.plays):play})"
                for result in results
            ],
            Embed().set_author(
                name=f"{username}'s top tracks [{timeframe}]",
                icon_url=ctx.author.display_avatar,
            ),
        )

    @lastfm.command(name="topartists", aliases=["artists", "ta"])
    async def lastfm_topartists(
        self: "LastFM",
        ctx: Context,
        member: Union[Member, User] = Author,
        timeframe: Literal["weekly", "monthly", "yearly"] = "overall",
    ):
        """
        View a users top artists from a certain timeframe
        """

        if not (
            username := await self.bot.db.fetchval(
                """
                SELECT username FROM lastfm.user
                WHERE user_id = $1
                """,
                member.id,
            )
        ):
            return await ctx.alert(
                f"You don't have a LastFM username set!"
                if member == ctx.author
                else f"{member.mention} doesn't have a LastFM username set!"
            )

        await ctx.typing()
        results = await self.handler.top(
            username=username, type_="artists", period=timeframe, limit=100
        )

        return await ctx.paginate(
            [
                f"{result.artist.hyper} ({plural(result.artist.plays):play})"
                for result in results
            ],
            Embed().set_author(
                name=f"{username}'s top artists [{timeframe}]",
                icon_url=ctx.author.display_avatar,
            ),
        )

    @lastfm.command(name="topalbums", aliases=["albums", "tal"])
    async def lastfm_topalbums(
        self: "LastFM",
        ctx: Context,
        member: Union[Member, User] = Author,
        timeframe: Literal["weekly", "monthly", "yearly"] = "overall",
    ):
        """
        View a users top albums from a certain timeframe
        """

        if not (
            username := await self.bot.db.fetchval(
                """
                SELECT username FROM lastfm.user
                WHERE user_id = $1
                """,
                member.id,
            )
        ):
            return await ctx.alert(
                f"You don't have a LastFM username set!"
                if member == ctx.author
                else f"{member.mention} doesn't have a LastFM username set!"
            )

        await ctx.typing()
        results = await self.handler.top(
            username=username, type_="albums", period=timeframe, limit=100
        )

        return await ctx.paginate(
            [
                f"{result.album.hyper} ({plural(result.album.plays):play})"
                for result in results
            ],
            Embed().set_author(
                name=f"{username}'s top albums [{timeframe}]",
                icon_url=ctx.author.display_avatar,
            ),
        )

    @lastfm.command(name="command", aliases=["cmd"])
    @is_donator()
    async def lastfm_command(self, ctx: Context, *, cmd: str):
        """
        Assign a custom command name for nowplaying
        """

        if cmd.lower() == "none":
            cmd = None

        r = await self.bot.db.execute(
            "UPDATE lastfm.user SET command = $1 WHERE user_id = $2", cmd, ctx.author.id
        )

        if r == "UPDATE 0":
            return await ctx.alert("You don't have a LastFM user set")

        if not cmd:
            return await ctx.confirm("Removed your LastFM custom command")

        return await ctx.confirm(f"Updated your LastFM custom command to **{cmd}**")
    
    @lastfm.group(name="embed", invoke_without_command=True)
    async def lf_embed(self, ctx: Context):
        return await ctx.send_help(ctx.command)
    
    @lf_embed.command(name="variables")
    async def embed_variables(self, ctx: Context):
        """
        Check all the variables available for building custom lastfm embeds
        """

        model = await self.handler.playing("caniush")
        return await ctx.paginate(
            self.bot.flatten(
                [
                    [
                        "{lastfm." + f"{m}.{h}" + "}"
                        for h in json.loads(getattr(model, m).schema_json())['properties'].keys() 
                    ]
                    for m in json.loads(model.schema_json())['properties'].keys()
                ]
            ),
            Embed(title="Last.Fm embeds")
        )
    
    @lf_embed.command(name="steal", aliases=['copy'])
    @is_donator()
    async def embed_steal(self, ctx: Context, *, member: User):
        """
        Steal someone else's lastfm custom embed
        """
        
        if member == ctx.author:
            return await ctx.alert("Stealing your own embed is absurd")

        if not (
            em := await self.bot.db.fetchval(
                "SELECT embed FROM lastfm.user WHERE user_id = $1",
                member.id
            )
        ):
            return await ctx.alert("This user has no custom lastfm embed")

        await self.bot.db.execute(
            """
            INSERT INTO lastfm VALUES ($1,$2) 
            ON CONFLICT (user_id) DO UPDATE SET embed = $2
            """,
            ctx.author.id, em
        ) 

    @lf_embed.command(name="view") 
    async def embed_view(self, ctx: Context, *, member: Member | User = Author):
        """
        View your or someone else's lastfm custom embed
        """

        if not (
            em := await self.bot.db.fetchval(
                "SELECT embed FROM lastfm.user WHERE user_id = $1",
                member.id
            )
        ):
            return await ctx.alert("There's no embed to show")
        
        embed = Embed(
            title=f"{member.display_name}'s custom embed",
            description=f"```{em}```"
        )
        return await ctx.reply(embed=embed)
    
    @lf_embed.command(name="remove", aliases=['del', 'rm', 'delete'])
    async def embed_delete(self, ctx: Context):
        """
        Delete your lastfm custom embed
        """

        await self.bot.db.execute(
            """
            UPDATE lastfm.user 
            SET embed = $1
            WHERE user_id = $2
            """,
            None, ctx.author.id
        )

        return await ctx.confirm("Removed your lastfm custom embed")

    @lf_embed.command(name="set", aliases=['configure'])
    @is_donator()
    async def embed_set(self, ctx: Context, *, code: str):
        """
        Assign your custom lastfm embed
        """

        await self.bot.db.execute(
            """
            INSERT INTO lastfm.user VALUES ($1,$2)
            ON CONFLICT (user_id) DO UPDATE SET embed = $2  
            """,
            ctx.author.id, code
        )

        return await ctx.confirm("Assigned your new lastfm embed")

    @lastfm.group(
        name="collage", 
        aliases=["chart", "collages", "c"], 
        invoke_without_command=True
    )
    async def lastfm_collage(self, ctx: Context):
        return await ctx.send_help(ctx.command)

    @lastfm_collage.command(name="artist", aliases=["artists", "ar"])
    async def lastfm_collage_artists(
        self: "LastFM",
        ctx: Context,
        member: Union[Member, User] = Author,
        size: Annotated[str, ChartSize] = "3x3",
        timeframe: Literal["weekly", "monthly", "yearly", "overall"] = "overall",
    ) -> Message:
        """
        Get a lastfm collage of your top artists
        """

        if not (
            username := await self.bot.db.fetchval(
                """
                SELECT username FROM lastfm.user
                WHERE user_id = $1
                """,
                member.id,
            )
        ):
            return await ctx.alert(
                f"You don't have a LastFM username set!"
                if member == ctx.author
                else f"{member.mention} doesn't have a LastFM username set!"
            )

        await ctx.typing()

        buffer = await self.handler.artist_collage(
            username=username, size=size, period=timeframe
        )

        return await ctx.send(
            f"{username}'s artist collage `[{timeframe}]` `({size})`",
            file=File(buffer, filename=f"{username}.png"),
        )

    @lastfm_collage.command(name="track", aliases=["tracks", "tr"])
    async def lastfm_collage_track(
        self: "LastFM",
        ctx: Context,
        member: Union[Member, User] = Author,
        size: Annotated[str, ChartSize] = "3x3",
        timeframe: Literal["weekly", "monthly", "yearly", "overall"] = "overall",
    ) -> Message:
        """
        Get a lastfm collage of your top tracks
        """

        if not (
            username := await self.bot.db.fetchval(
                """
                SELECT username FROM lastfm.user
                WHERE user_id = $1
                """,
                member.id,
            )
        ):
            return await ctx.alert(
                f"You don't have a LastFM username set!"
                if member == ctx.author
                else f"{member.mention} doesn't have a LastFM username set!"
            )

        await ctx.typing()

        buffer: bytes = await self.bot.session.get(
            "https://api.rival.rocks/lastfm/chart",
            params={"username": username, "period": timeframe, "size": size},
        )

        return await ctx.send(
            f"{username}'s track collage `[{timeframe}]` `({size})`",
            file=File(BytesIO(buffer), filename=f"{username}.png"),
        )


async def setup(bot: Scare) -> None:
    await bot.add_cog(LastFM(bot))
