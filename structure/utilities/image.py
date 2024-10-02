import re
from io import BytesIO

from typing_extensions import Type

from structure.managers import Context

from . import Error

DISCORD_FILE_PATTERN = r"(https://|http://)?(cdn\.|media\.)discord(app)?\.(com|net)/(attachments|avatars|icons|banners|splashes)/[0-9]{17,22}/([0-9]{17,22}/(?P<filename>.{1,256})|(?P<hash>.{32}))\.(?P<mime>[0-9a-zA-Z]{2,4})?"


class Image:
    def __init__(self: "Image", fp: bytes, url: str, filename: str):
        self.fp = fp
        self.url = url
        self.filename = filename

    @property
    def buffer(self: "Image") -> BytesIO:
        buffer = BytesIO(self.fp)
        buffer.name = self.filename

        return buffer

    @classmethod
    async def fallback(cls: Type["Image"], ctx: Context) -> "Image":
        message = ctx.message
        if not message.attachments:
            return Error("You need to provide an image!")

        attachment = message.attachments[0]
        if not attachment.content_type:
            return Error(f"The [`attachment`]({attachment.url}) is invalid!")

        elif not attachment.content_type.startswith("image"):
            return Error(f"The [`attachment`]({attachment.url}) has to be an image!")

        buffer = await attachment.read()
        return cls(
            fp=buffer,
            url=attachment.url,
            filename=attachment.filename,
        )

    @classmethod
    async def convert(cls: Type["Image"], ctx: Context, argument: str) -> "Image":
        if argument.lower() in ("remove", "reset", "clear", "default", "none"):
            return None

        elif not (match := re.match(DISCORD_FILE_PATTERN, argument)):
            return Error("The attachment is invalid!")

        response = await ctx.bot.session.get(match.group())
        if not response.content_type.startswith("image"):
            return Error(f"The attachment provided must be an image file.")

        buffer = await response.read()
        return cls(
            fp=buffer,
            url=match.group(),
            filename=match.group("filename") or match.group("hash"),
        )
