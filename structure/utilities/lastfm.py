import asyncio
from io import BytesIO
from typing import List

from aiohttp import ClientSession as Session
from munch import Munch
from PIL import Image, ImageDraw, ImageFont

from structure.config import API
from structure.managers import ClientSession, Record

from .models import *


class FMHandler(ClientSession):
    def __init__(self: "FMHandler"):
        super().__init__(base_url="https://ws.audioscrobbler.com/2.0/")

    async def request(self: "FMHandler", **p) -> Munch:
        slug = p.pop("slug", None)

        data: Munch = await super().request(
            "GET",
            self.base_url,
            params={
                "api_key": API.lastfm,
                "format": "json",
                **p,
            },
            slug=slug,
        )
        return data

    async def profile(
        self: "FMHandler",
        username: str,
    ) -> Profile:

        data = await self.request(
            slug="user",
            method="user.getinfo",
            username=username,
        )
        if not data.url:
            return None

        return Profile(
            url=data.url,
            username=data.name,
            display_name=data.realname,
            country=data.country if data.country != "None" else "Unknown",
            avatar=data.image[-1]["#text"],
            tracks=int(data.track_count),
            albums=int(data.album_count),
            artists=int(data.artist_count),
            scrobbles=int(data.playcount),
            registered=int(data.registered.unixtime),
            pro=data.subscriber == "1",
        )

    async def playing(self: "FMHandler", username: str, json: bool = False) -> Playing:

        tracks = await self.request(
            method="user.getrecenttracks",
            username=username,
            slug="recenttracks.track",
            limit=1,
        )

        if not tracks:
            return Error(
                f"[`@{username}`](https://last.fm/user/{username}) isn't currently listening to anything!"
            )

        track = tracks[0]

        # Check if 'artist' is a dictionary and has the key "#text"
        if isinstance(track.artist, dict) and "#text" in track.artist:
            artist_info = await self.request(
                method="artist.getinfo",
                artist=track.artist["#text"],
                slug="artist",
            )
        else:
            # Handle the case where it's not a dictionary or doesn't have "#text"
            artist_info = {
                "url": None,
                "name": "Unknown Artist",
                "image": None,
                "plays": 0,
            }

        album_info = await self.request(
            method="album.getinfo",
            artist=(
                track.artist["#text"]
                if isinstance(track.artist, dict) and "#text" in track.artist
                else "Unknown Artist"
            ),
            album=(
                track.album["#text"]
                if isinstance(track.album, dict) and "#text" in track.album
                else "Unknown Album"
            ),
            slug="album",
        )

        track_info = (
            await self.request(
                method="track.getinfo",
                track=track.name,
                artist=(
                    track.artist["#text"]
                    if isinstance(track.artist, dict) and "#text" in track.artist
                    else "Unknown Artist"
                ),
                slug="track",
            )
            or track
        )

        artist = {
            "url": artist_info["url"],
            "name": artist_info["name"],
            "image": (
                artist_info["image"][-1]["#text"] if artist_info["image"] else None
            ),
            "plays": (
                int(artist_info["stats"]["userplaycount"])
                if "stats" in artist_info and "userplaycount" in artist_info["stats"]
                else 0
            ),
        }
        track = {
            "url": track_info["url"],
            "name": track_info["name"],
            "image": track["image"][-1]["#text"] if track["image"] else None,
            "plays": (
                int(track_info["userplaycount"]) if "userplaycount" in track_info else 0
            ),
        }
        if album_info:
            album = {
                "url": album_info["url"],
                "name": album_info["name"],
                "image": (
                    album_info["image"][-1]["#text"] if album_info["image"] else None
                ),
                "plays": (
                    int(album_info["userplaycount"])
                    if "userplaycount" in album_info
                    else 0
                ),
            }
        if json == True:
            return {
                "track": track,
                "artist": artist,
                "album": album,
                "user": await self.profile(username),
            }

        return Playing(
            track=track,
            artist=artist,
            album=album if album else None,
            user=await self.profile(username),
        )

    async def read_image(
        self: "FMHandler", url: str, plays: int, artist: str, font
    ) -> Image:
        try:
            r = await super().request("GET", url)
            img = Image.open(BytesIO(r)).convert("RGB").resize((250, 250))
        except:
            img = Image.new("RGB", (250, 250))
        finally:
            draw = ImageDraw.Draw(img)
            draw.text(
                (5, 200),
                f"{plays} Plays\n{artist}",
                fill="white",
                font=font,
                stroke_width=1,
                stroke_fill=0,
            )
            return img

    async def get_image(self, artist: str, username: str, plays: int, font) -> Image:
        data = await self.request(
            method="artist.getinfo", artist=artist, username=username, slug="artist"
        )

        image_url = data["image"][-1]["#text"]
        return await self.read_image(image_url, plays, artist, font)

    async def artist_collage(
        self: "FMHandler", username: str, size: str, period: str
    ) -> BytesIO:
        a, b = map(int, size.split("x"))
        top_artists = await self.top(
            username=username, period=period, type_="artists", limit=a * b
        )

        if not top_artists:
            return None

        # creating the font
        session = Session()
        r = await session.get(
            "https://github.com/matomo-org/travis-scripts/raw/master/fonts/Arial.ttf"
        )
        font_read = await r.read()
        font = ImageFont.truetype(BytesIO(font_read), 20)
        await session.close()

        # getting the images
        tasks = await asyncio.gather(
            *[
                self.get_image(r.artist.name, username, r.artist.plays, font)
                for r in top_artists
                if getattr(r.artist, "plays", 0) > 0
            ]
        )

        w, h = (250, 250)
        grid = Image.new("RGB", (a * w, b * h))

        # pasting each artist image on the collage
        for i, image in enumerate(tasks):
            grid.paste(image, ((i % a) * w, (i // a) * h))

        buffer = BytesIO()
        grid.save(buffer, format="png")
        buffer.seek(0)
        return buffer

    async def whoknows(
        self: "FMHandler", artist: str, results: List[Record]
    ) -> List[ArtistInfo]:
        plays: List[ArtistInfo] = []

        for result in results:
            artist_info = await self.request(
                method="artist.getinfo",
                artist=artist,
                username=result.username,
                slug="artist",
            )

            if int(artist_info.stats.userplaycount) > 0:
                plays.append(
                    ArtistInfo(
                        name=artist_info.name,
                        url=artist_info.url,
                        plays=artist_info.stats.userplaycount,
                        **result,
                    )
                )

        return sorted(plays, key=lambda b: b.plays, reverse=True)

    async def top(
        self: "FMHandler",
        username: str,
        period: str,
        type_: str,
        limit: int = 5,
    ) -> List[Top]:

        method_map = {
            "tracks": "user.gettoptracks",
            "artists": "user.gettopartists",
            "albums": "user.gettopalbums",
            "tags": "user.gettoptags",
        }

        method = method_map.get(type_)

        data = await self.request(
            method=method,
            username=username,
            period=period,
            limit=limit,
            slug=f"top{type_}.{type_[:-1] if type_.endswith('s') else type_}",
        )

        top_items = []
        for item in data:
            if type_ != "tags":
                track = Track(
                    name=item["name"],
                    url=item["url"],
                    plays=int(item["playcount"]),
                )

                artist = Artist(
                    name=item["artist"]["name"] if type_ == "tracks" else item["name"],
                    url=item["artist"]["url"] if type_ == "tracks" else item["url"],
                    plays=item["playcount"] if type_ == "artists" else None,
                )

                if type_ != "artists":
                    album = Album(
                        name=None if type_ == "tracks" else item["name"],
                        url=None if type_ == "tracks" else item["url"],
                        artist=None if type_ == "tracks" else item["artist"]["name"],
                        plays=None if type_ == "tracks" else item["playcount"],
                    )
                else:
                    album = None

                top_item = Top(track=track, artist=artist, album=album)
                top_items.append(top_item)
            else:
                top_items.append(Genre(**item))

        return top_items
