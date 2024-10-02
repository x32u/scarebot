import argparse
import asyncio
import datetime
import json
import re
from contextlib import suppress
from typing import Dict, Optional

import aiohttp
from bs4 import BeautifulSoup
from discord import Colour
from discord import Member as DefaultMember
from discord import PartialEmoji, Role
from discord.ext.commands import (
    BadArgument,
    ColorConverter,
    Converter,
    MemberConverter,
    RoleConverter,
    RoleNotFound,
    TextChannelConverter,
)
from discord.ext.commands.context import Context
from humanfriendly import parse_timespan
from pytz import timezone
from timezonefinder import TimezoneFinder

from structure.managers import Context

from .models import (
    CashAppProfile,
    Error,
    RobloxUser,
    SnapchatUser,
    TikTokUser,
    WeatherCondition,
    WeatherFeelsLike,
    WeatherModel,
    WeatherTemperature,
    WeatherWind,
)


class RobloxTool:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36"
        }
        self.session = aiohttp.ClientSession(
            headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)
        )

    async def get_user_id(self, username: str) -> Optional[str]:
        """
        Get the roblox user id by username
        """

        params = {"username": username}
        r = await self.session.get(
            "https://www.roblox.com/users/profile", params=params
        )
        if r.ok:
            return str(r.url)[len("https://www.roblox.com/users/") :].split("/")[0]

        return None

    async def get_user_stats(self, user_id: str) -> Dict[str, int]:
        payload = {}

        for statistic in ["friends", "followers", "followings"]:
            r = await self.session.get(
                f"https://friends.roblox.com/v1/users/{user_id}/{statistic}/count"
            )
            if r.status == 200:
                data = await r.json()
                payload.update({statistic: data["count"]})
            else:
                payload.update({statistic: 0})

        return payload

    async def get_user_avatar(self, user_id: str):
        """
        Get the user's avatar
        """

        r = await self.session.get(f"https://www.roblox.com/users/{user_id}/profile")
        html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        return soup.find("meta", property="og:image")["content"]

    async def get_user_profile(self, user_id: str) -> dict:
        """
        Get the user's profile by id
        """

        r = await self.session.get(f"https://users.roblox.com/v1/users/{user_id}")
        return await r.json()

    async def scrape(self, username: str) -> dict:
        """
        Get details about a roblox profile by username
        """

        if user_id := await self.get_user_id(username):
            profile_data = await self.get_user_profile(user_id)
            profile_stats = await self.get_user_stats(user_id)
            user_avatar = await self.get_user_avatar(user_id)
            await self.session.close()
            return {
                "username": profile_data["name"],
                "display_name": profile_data["displayName"],
                "bio": profile_data["description"],
                "id": user_id,
                "created_at": datetime.datetime.strptime(
                    profile_data["created"].split(".")[0] + "Z", "%Y-%m-%dT%H:%M:%SZ"
                ),
                "banned": profile_data["isBanned"],
                "avatar_url": user_avatar,
                "url": f"https://www.roblox.com/users/{user_id}/profile",
                **profile_stats,
            }

        return None


class Roblox(Converter):
    def __init__(self):
        self.roblox = RobloxTool()
        super().__init__()

    async def convert(self, ctx: Context, argument: str) -> RobloxUser:
        result = await self.roblox.scrape(argument)

        if not result:
            raise Error(f"Roblox user `{argument}` not found")

        return RobloxUser(**result)


class Snapchat(Converter):
    async def convert(self, ctx: Context, argument: str) -> SnapchatUser:
        html = await ctx.bot.session.get(f"https://www.snapchat.com/add/{argument}")
        soup = BeautifulSoup(html, "html.parser")
        h = soup.find("h5")

        if not (pfp := soup.find("img", alt="Profile Picture")):
            images = soup.find_all("img")
            bitmoji = images[0]["srcset"]
            snapcode = images[-1]["src"].replace("SVG", "PNG")
        else:
            bitmoji = pfp
            snapcode = None

        display = soup.find(
            "span",
            attrs={
                "class": "PublicProfileDetailsCard_displayNameText__naDQ0 PublicProfileDetailsCard_textColor__HkkEs PublicProfileDetailsCard_oneLineTruncation__VOhsx"
            },
        ) or soup.find("h4")
        user = h.find("span") or h

        return SnapchatUser(
            display_name=display.text,
            username=user.text,
            bitmoji=bitmoji,
            snapcode=snapcode,
        )


class Tiktok(Converter):
    async def convert(self, ctx: Context, argument: str):
        result = await ctx.bot.session.get(f"https://tiktok.com/@{argument}")
        soup = BeautifulSoup(result, "html.parser")
        script = soup.find("script", id="__UNIVERSAL_DATA_FOR_REHYDRATION__")
        x = json.loads(script.text)["__DEFAULT_SCOPE__"]["webapp.user-detail"]

        if x["statusCode"] == 10221:
            raise Error(f"Tiktok User `@{argument}` not found")

        payload = {
            "username": x["userInfo"]["user"]["uniqueId"],
            "nickname": x["userInfo"]["user"]["nickname"],
            "avatar": x["userInfo"]["user"]["avatarMedium"],
            "bio": x["userInfo"]["user"]["signature"],
            "verified": x["userInfo"]["user"]["verified"],
            "private": x["userInfo"]["user"]["privateAccount"],
            "followers": x["userInfo"]["stats"]["followerCount"],
            "following": x["userInfo"]["stats"]["followingCount"],
            "hearts": x["userInfo"]["stats"]["heart"],
            "url": f"https://tiktok.com/@{x['userInfo']['user']['uniqueId']}",
        }

        return TikTokUser(**payload)


class CashApp(Converter):
    async def convert(self, ctx: Context, argument: str):
        html = await ctx.bot.session.get(f"https://cash.app/{argument}")
        soup = BeautifulSoup(html, "html.parser")
        qr = "https://cash.app" + soup.find("img")["src"]
        info = json.loads(re.search("var profile = ([^;]*)", soup.prettify()).group(1))
        payload = {
            "display_name": info["display_name"],
            "tag": info["formatted_cashtag"],
            "avatar_url": info["avatar"]["image_url"],
            "accent_color": info["avatar"]["accent_color"],
            "qr_url": qr,
        }
        return CashAppProfile(**payload)


class Weather(Converter):
    async def convert(self, ctx: Context, argument: str) -> WeatherModel:
        x = await ctx.bot.session.get(
            "https://api.weatherapi.com/v1/current.json",
            params={"q": argument, "key": ctx.bot.weather},
        )

        return WeatherModel(
            city=x["location"]["name"],
            country=x["location"]["country"],
            last_updated=datetime.datetime.fromtimestamp(
                x["current"]["last_updated_epoch"]
            ),
            localtime=datetime.datetime.now(tz=timezone(x["location"]["tz_id"])),
            temperature=WeatherTemperature(
                celsius=x["current"]["temp_c"], fahrenheit=x["current"]["temp_f"]
            ),
            feelslike=WeatherFeelsLike(
                celsius=x["current"]["feelslike_c"],
                fahrenheit=x["current"]["feelslike_f"],
            ),
            wind=WeatherWind(
                mph=x["current"]["wind_mph"], kph=x["current"]["wind_kph"]
            ),
            condition=WeatherCondition(
                text=x["current"]["condition"]["text"],
                icon=f"http:{x['current']['condition']['icon']}",
            ),
            humidity=x["current"]["humidity"],
        )


class Bank(Converter):
    async def convert(self: "Bank", ctx: Context, argument: str):
        if not argument.isdigit() and argument.lower() != "all":
            raise BadArgument("This is not a number")

        bank = await ctx.bot.db.fetchval(
            "SELECT bank FROM economy WHERE user_id = $1", ctx.author.id
        )
        points = bank if argument.lower() == "all" else int(argument)

        if points == 0:
            raise BadArgument("The value cannot be 0")

        if points > bank:
            raise BadArgument(
                f"You do not have `{int(argument):,}` credits in your bank"
            )

        return points


class GiveawayCreate(Converter):
    def __init__(self):
        self.parser = argparse.ArgumentParser(description="Giveaway")
        self.parser.add_argument("reward", nargs="+")
        self.parser.add_argument("--time", "-t", default="1h", required=False)
        self.parser.add_argument(
            "--winners", "-w", default=1, type=int, required=False, choices=range(1, 6)
        )

    async def convert(
        self: "GiveawayCreate", ctx: Context, argument: str
    ) -> argparse.Namespace:
        try:
            args = self.parser.parse_args(argument.split())
        except:
            raise BadArgument("Arguments were given incorrectly")

        args.reward = " ".join(args.reward)
        return args


class YouTuber(Converter):
    async def convert(self: "YouTuber", ctx: Context, argument: str):
        try:
            await ctx.bot.session.get(
                f"https://youtube.com/@{argument}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
                },
            )
            return argument
        except:
            raise BadArgument("This youtuber was not found")


class Channel(TextChannelConverter):
    async def convert(self, ctx: Context, argument: str):
        if argument == "all":
            return argument

        return await super().convert(ctx, argument)


class Value(Converter):
    async def convert(self: "Value", ctx: Context, argument: str):
        if not argument.isdigit() and argument.lower() != "all":
            raise BadArgument("This is not a number")

        credits = await ctx.bot.db.fetchval(
            "SELECT credits FROM economy WHERE user_id = $1", ctx.author.id
        )
        points = credits if argument.lower() == "all" else int(argument)

        if points == 0:
            raise BadArgument("The value cannot be 0")

        if points > credits:
            raise BadArgument(f"You do not have `{int(argument):,}` credits")

        return points


class ValidPermission(Converter):
    async def convert(self: "ValidPermission", ctx: Context, argument: str):

        perms = [
            p
            for p in dir(ctx.author.guild_permissions)
            if type(getattr(ctx.author.guild_permissions, p)) == bool
        ]

        if not argument in perms:
            raise BadArgument("This is **not** a valid permission")

        return argument


class ValidAlias(Converter):
    async def convert(self: "ValidAlias", ctx: Context, argument: str):
        all_aliases = ctx.bot.flatten(
            [
                list(map(lambda cm: cm.lower(), c.aliases))
                for c in set(ctx.bot.walk_commands())
                if c.aliases
            ]
        )
        if argument.lower() in all_aliases:
            raise BadArgument("This is **already** an existing alias for a command")

        return argument


class Time(Converter):
    async def convert(self, ctx: Context, argument: str):
        try:
            return parse_timespan(argument)
        except:
            raise BadArgument("This is not a valid timestamp")


class ValidCommand(Converter):
    async def convert(self: "ValidCommand", ctx: Context, argument: str):
        if not ctx.bot.get_command(argument) or getattr(
            ctx.bot.get_command(argument), "cog_name", ""
        ).lower() in ["developer", "jishaku"]:
            raise BadArgument("This is **not** a valid command")

        return ctx.bot.get_command(argument).qualified_name


class AssignableRole(RoleConverter):
    async def convert(self, ctx: Context, argument: str) -> Role:
        try:
            role = await super().convert(ctx, argument)
        except:
            role = ctx.find_role(argument)
            if not role:
                raise RoleNotFound(argument)
        finally:
            if not role.is_assignable():
                raise Error("This role cannot be assigned by me")

            if ctx.author.id != ctx.guild.owner_id:
                if role >= ctx.author.top_role:
                    raise Error("You cannot manage this role")

            return role


class Location(Converter):
    async def convert(self, ctx: Context, argument: str):
        params = {"q": argument, "format": "json"}

        result = await ctx.bot.session.get(
            "https://nominatim.openstreetmap.org/search", params=params
        )

        if not result:
            raise BadArgument("This location was not found")

        kwargs = {"lat": float(result[0]["lat"]), "lng": float(result[0]["lon"])}

        return await asyncio.to_thread(TimezoneFinder().timezone_at, **kwargs)


class DiscordEmoji(Converter):
    async def convert(self, ctx: Context, argument: str):
        custom_regex = re.compile(r"(<a?)?:\w+:(\d{18}>)?")
        unicode_regex = re.compile(
            r"["
            "\U0001F1E0-\U0001F1FF"
            "\U0001F300-\U0001F5FF"
            "\U0001F600-\U0001F64F"
            "\U0001F680-\U0001F6FF"
            "\U0001F700-\U0001F77F"
            "\U0001F780-\U0001F7FF"
            "\U0001F800-\U0001F8FF"
            "\U0001F900-\U0001F9FF"
            "\U0001FA00-\U0001FA6F"
            "\U0001FA70-\U0001FAFF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+"
        )

        if not custom_regex.match(argument) and not unicode_regex.match(argument):
            raise BadArgument("This is not an emoji")

        return PartialEmoji.from_str(argument)


class ImageData:
    async def convert(self, ctx: Context, argument: str) -> bytes:
        pinterest = re.compile(
            r"https://i.pinimg.com/564x/([^/]{2})/([^/]{2})/([^/]{2})/([^.]*).jpg"
        )
        discord_cdn = re.compile(
            r"https://cdn.discordapp.com/attachments/([^/][0-9]+)/([^/][0-9]+)/([^.]*).(jpg|png|gif)(.*)"
        )
        catbox = re.compile(r"https://files.catbox.moe/([^.]*).(jpg|png|gif)")
        if (
            not pinterest.match(argument)
            and not discord_cdn.match(argument)
            and not catbox.match(argument)
        ):
            raise BadArgument(
                "Bad URL was given. It must be a **pinterest**, **discord** or **catbox** image URL"
            )

        return await ctx.bot.session.get(argument)


class Color(ColorConverter):
    async def convert(self, ctx: Context, argument: str):
        try:
            return await super().convert(ctx, argument)
        except:
            try:
                return getattr(Colour, "_".join(argument.split(" ")))()
            except:
                raise Error("This color is not available")


class ChartSize(Converter):
    async def convert(self, ctx: Context, argument: str):
        if not re.match(r"[0-9]x[0-9]", argument):
            raise Error("Wrong size format. Example: 3x3")

        return argument


class ValidDate(Converter):
    async def convert(self, ctx: Context, argument: str):
        now = datetime.datetime.now()
        argument += f" {now.year}"
        formats = [
            "%d %B %Y",
            "%d %b %Y",
            "%B %d %Y",
            "%b %d %Y",
            "%d %m %y",
            "%m %d %y",
        ]

        date = None

        for form in formats:
            with suppress(ValueError):
                date = datetime.datetime.strptime(argument, form)
                break

        if not date:
            raise BadArgument("Date is not valid")

        if date < now:
            date = date.replace(year=date.year + 1)

        return date


class Member(MemberConverter):
    async def convert(self, ctx: Context, argument: str) -> DefaultMember:
        member = await super().convert(ctx, argument)

        if member.top_role >= ctx.me.top_role:
            raise Error(
                f"I am unable to invoke `{ctx.command.qualified_name}` on {member.mention}!"
            )

        elif ctx.author == ctx.guild.owner:
            return member

        elif member == ctx.guild.owner:
            raise Error(
                f"You are unable to invoke `{ctx.command.qualified_name}` on {member.mention}!"
            )

        elif member.top_role >= ctx.author.top_role:
            raise Error(
                f"You are unable to invoke `{ctx.command.qualified_name}` on {member.mention}!"
            )

        elif member == ctx.author:
            raise Error(
                f"You are unable to invoke `{ctx.command.qualified_name}` on yourself!"
            )

        return member


class Percentage(Converter):
    async def convert(self, ctx: Context, argument: str) -> int:
        if argument.isdigit():
            argument = int(argument)

        elif match := re.compile(r"(?P<percentage>\d+)%").match(argument):
            argument = int(match.group(1))

        else:
            argument = 0

        if argument < 0 or argument > 100:
            raise Error("Please provide a valid percentage!")

        return argument


class Position(Converter):
    async def convert(self, ctx: Context, argument: str) -> int:
        argument = argument.lower()
        player = ctx.voice_client
        ms: int = 0

        if ctx.invoked_with == "ff" and not argument.startswith("+"):
            argument = f"+{argument}"

        elif ctx.invoked_with == "rw" and not argument.startswith("-"):
            argument = f"-{argument}"

        if match := re.compile(
            r"(?P<h>\d{1,2}):(?P<m>\d{1,2}):(?P<s>\d{1,2})"
        ).fullmatch(argument):
            ms += (
                int(match.group("h")) * 3600000
                + int(match.group("m")) * 60000
                + int(match.group("s")) * 1000
            )

        elif match := re.compile(r"(?P<m>\d{1,2}):(?P<s>\d{1,2})").fullmatch(argument):
            ms += int(match.group("m")) * 60000 + int(match.group("s")) * 1000

        elif (
            match := re.compile(r"(?P<s>(?:\-|\+)\d+)\s*s").fullmatch(argument)
        ) and player:
            ms += player.position + int(match.group("s")) * 1000

        elif match := re.compile(r"(?:(?P<m>\d+)\s*m\s*)?(?P<s>\d+)\s*[sm]").fullmatch(
            argument
        ):
            if m := match.group("m"):
                if match.group("s") and argument.endswith("m"):
                    return Error(f"Invalid position provided!")

                ms += int(m) * 60000

            elif s := match.group("s"):
                if argument.endswith("m"):
                    ms += int(s) * 60000
                else:
                    ms += int(s) * 1000

        else:
            return Error(f"Invalid position provided!")

        return ms
