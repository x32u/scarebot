class ShardStatus:
    ok: int = 8650575
    warning: int = 16765007
    critical: int = 16711680


class SCARE:
    token: str = (
        ""
    )
    verified_scare: str = (
        ""
    )
    owners: list = [
        1,
    ]
    workers: list = [
        ""
    ]
    captcha: str = ""
    proxy: str = ""


class Database:
    host: str = ""
    database: str = ""
    port: str = ""
    user: str = ""
    password: str = ""


class Paginator:
    next: str = "<:emoji_9:1213578749375807498>"
    previous: str = "<:emoji_10:1213578771450560583>"
    cancel: str = "<:emoji_7:1213578698880589844>"
    navigate: str = "<:emoji_8:1213578728450560101>"


class API:
    weather: str = ""
    lastfm: str = ""
    luma: str = ""
