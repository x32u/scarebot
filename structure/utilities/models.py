from datetime import datetime
from typing import Any, List, Optional

from discord.ext.commands import CommandInvokeError
from pydantic import BaseModel, HttpUrl


class ApplicationLegal(BaseModel):
    terms: HttpUrl
    privacy: HttpUrl


class ApplicationInfo(BaseModel):
    bio: str
    flags: List[str]
    tags: Optional[List[str]]
    legal: Optional[ApplicationLegal]


class RobloxUser(BaseModel):
    username: str
    display_name: str
    bio: str
    id: str
    created_at: datetime
    banned: bool
    avatar_url: str
    url: str
    friends: int
    followers: int
    followings: int


class TikTokUser(BaseModel):
    username: str
    nickname: str
    avatar: HttpUrl
    url: HttpUrl
    bio: str
    private: bool
    verified: bool
    followers: int
    following: int
    hearts: int


class SnapchatUser(BaseModel):
    display_name: str
    username: str
    snapcode: Optional[HttpUrl] = None
    bitmoji: HttpUrl

    @property
    def url(self):
        return f"https://www.snapchat.com/add/{self.username}"


class WeatherTemperature(BaseModel):
    celsius: float
    fahrenheit: float


class WeatherFeelsLike(WeatherTemperature):
    celsius: float
    fahrenheit: float


class WeatherWind(BaseModel):
    mph: float
    kph: float


class WeatherCondition(BaseModel):
    text: str
    icon: HttpUrl


class WeatherModel(BaseModel):
    city: str
    country: str
    last_updated: datetime
    localtime: datetime
    temperature: WeatherTemperature
    feelslike: WeatherFeelsLike
    wind: WeatherWind
    condition: WeatherCondition
    humidity: int


class CashAppProfile(BaseModel):
    display_name: str
    tag: str
    avatar_url: HttpUrl
    accent_color: str
    qr_url: HttpUrl

    @property
    def url(self):
        return f"https://cash.app/{self.tag}"


class Proxy(BaseModel):
    username: str
    password: str
    host: str
    port: str

    def __str__(self):
        return f"http://{self.username}:{self.password}@{self.host}:{self.port}"


class Afk(BaseModel):
    user_id: int
    guild_id: int
    reason: str
    since: Any

    def __str__(self):
        return f"{self.user_id}-{self.guild_id}"


class Error(CommandInvokeError):
    def __init__(self, message: str):
        self.message: str = message
        super().__init__(self)


class Field(BaseModel):
    name: Optional[str]
    value: Optional[str]


class Profile(BaseModel):
    url: str
    username: str
    display_name: Optional[str]
    avatar: str
    country: Optional[str] = "Unknown"
    tracks: int
    artists: int
    albums: int
    registered: int
    pro: bool
    scrobbles: int


class Base(BaseModel):
    name: Optional[str]
    url: Optional[str]
    image: Optional[str]
    plays: Optional[int]

    @property
    def hyper(self):
        return f"[{self.name}]({self.url})"


class Playing(BaseModel):
    track: Base
    album: Optional[Base]
    artist: Base
    user: Profile


class Genre(BaseModel):
    name: str
    count: str
    url: str

    @property
    def hyper(self):
        return f"[`{self.name}`]({self.url})"


class Track(BaseModel):
    name: str
    url: str
    plays: int

    @property
    def hyper(self):
        return f"[`{self.name}`]({self.url})"


class Artist(BaseModel):
    name: str
    url: str
    plays: Optional[int]

    @property
    def hyper(self):
        return f"[`{self.name}`]({self.url})"


class ArtistInfo(Artist):
    username: str
    user_id: int


class Album(BaseModel):
    name: Optional[str]
    url: Optional[str]
    plays: Optional[int]
    artist: Optional[str]

    @property
    def hyper(self):
        return f"[`{self.name}`]({self.url})"


class Top(BaseModel):
    track: Track
    artist: Artist
    album: Optional[Album]
