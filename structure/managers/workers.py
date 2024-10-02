import asyncio
import base64
import json
import uuid
from typing import Optional

import tls_client
from pydantic import BaseModel

from . import logger as logging

logger = logging.getLogger(__name__)


class Guild(BaseModel):
    name: str
    member_count: int
    description: Optional[str]
    id: int

    def __repr__(self) -> str:
        return (
            f"<Guild name={self.name} id={self.id} member_count={self.member_count:,}>"
        )

    def __str__(self) -> str:
        return self.name


class User(BaseModel):
    username: str
    discriminator: str
    id: int
    token: str

    def __str__(self):
        if self.discriminator == "0":
            return self.username

        return f"{self.username}#{self.discriminator}"


class Workers:
    def __init__(self, workers: list, captcha_key: str):
        self.workers = workers
        self.captcha_key = captcha_key
        self.useragent = "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9024 Chrome/108.0.5359.215 Electron/22.3.26 Safari/537.36"
        self.session = tls_client.Session(
            client_identifier="firefox_120", random_tls_extension_order=False
        )
        self.cache = {}
        self.guild_count = 0

    @property
    def properties(self) -> str:
        payload = {
            "os": "Windows",
            "browser": "Discord Client",
            "release_channel": "stable",
            "client_version": "1.0.9024",
            "os_version": "10.0.19045",
            "os_arch": "x64",
            "app_arch": "ia32",
            "system_locale": "en",
            "browser_user_agent": self.useragent,
            "browser_version": "22.3.26",
            "client_build_number": 247929,
            "native_build_number": 40010,
            "client_event_source": None,
            "design_id": 0,
        }

        return base64.b64encode(json.dumps(payload).encode()).decode()

    def get_cookies(self) -> str:
        req = self.session.get("https://discord.com")
        if req.status_code == 200:
            return (
                "; ".join([f"{cookie.name}={cookie.value}" for cookie in req.cookies])
                + "; locale=en-US"
            )
        else:
            return "__dcfduid=4e0a8d504a4411eeb88f7f88fbb5d20a; __sdcfduid=4e0a8d514a4411eeb88f7f88fbb5d20ac488cd4896dae6574aaa7fbfb35f5b22b405bbd931fdcb72c21f85b263f61400; __cfruid=f6965e2d30c244553ff3d4203a1bfdabfcf351bd-1699536665; _cfuvid=rNaPQ7x_qcBwEhO_jNgXapOMoUIV2N8FA_8lzPV89oM-1699536665234-0-604800000; locale=en-US"

    def get_headers(self, token: str) -> dict:
        return {
            "Accept-Language": "en-US,en;q=0.9",
            "Authorization": token,
            "Cookie": self.get_cookies(),
            "Content-Type": "application/json",
            "User-Agent": self.useragent,
            "X-Discord-Locale": "en-US",
            "X-Debug-Options": "bugReporterEnabled",
            "X-Super-Properties": self.properties,
        }

    def chunk(self, token: str):
        r = self.session.get(
            "https://discord.com/api/v9/users/@me/guilds",
            headers=self.get_headers(token),
        )

        if r.status_code == 200:
            self.cache[token] = [int(result["id"]) for result in r.json()]
            logger.info(f"Chunked {len(self.cache[token])} servers for {token[:7]}")
        else:
            logger.info(f"{r.status_code} Unable to chunk guilds for {token[:7]}")

    def __get_guild_from_invite(self, invite: str) -> Optional[Guild]:
        r = self.session.get(
            f"https://discord.com/api/invites/{invite}?with_counts=True"
        )
        if r.status_code == 200:
            data = r.json()
            data["guild"]["member_count"] = data["approximate_member_count"]
            return Guild(**data["guild"])
        return None

    async def get_captcha_token(self, task_id: str):
        data = self.session.post(
            "https://api.capsolver.com/getTaskResult",
            headers={"Content-Type": "application/json"},
            json={"clientKey": self.captcha_key, "taskId": task_id},
        )

        result = data.json()
        logger.info(f"Captcha status: {result.get('status')}")

        if result.get("status") == "ready":
            return result["solution"]["gRecaptchaResponse"]
        elif result.get("status") == "processing":
            await asyncio.sleep(1.5)
            return await self.get_captcha_token(task_id)
        else:
            logger.info("Unable to solve captcha")
            return None

    async def solve(self, sitekey: str, rqdata: str):
        data = self.session.post(
            "https://api.capsolver.com/createTask",
            headers={"Content-Type": "application/json"},
            json={
                "clientKey": self.captcha_key,
                "task": {
                    "type": "HCaptchaTaskProxyLess",
                    "websiteURL": "https://discord.com",
                    "websiteKey": sitekey,
                    "enterprisePayload": {"rqdata": rqdata},
                    "userAgent": self.useragent,
                },
            },
        )

        payload = data.json()
        logger.info(payload)
        task_id = payload["taskId"]
        return await self.get_captcha_token(task_id)

    async def __join_guild(
        self, invite: str, token: str, guild: Guild, h: Optional[dict] = None
    ):
        payload = {"session_id": uuid.uuid4().hex}

        headers = self.get_headers(token)

        if h:
            headers.update(**h)

        r = self.session.post(
            f"https://discord.com/api/v9/invites/{invite}",
            headers=headers,
            json=payload,
        )

        if r.status_code == 200:
            return f"Joined {guild.name}"
        elif r.status_code == 403:
            return f"I'm banned from {guild.name}"
        elif r.status_code == 400:
            data = r.json()
            if data.get("captcha_key"):
                logger.info(data)
                return await self.__join_guild(
                    invite,
                    token,
                    guild,
                    {
                        "X-Captcha-Key": await self.solve(
                            data["captcha_sitekey"], data["captcha_rqdata"]
                        ),
                        "X-Captcha-Rqtoken": data["captcha_rqtoken"],
                    },
                )

        elif r.status_code == 429:
            return "I am rate limited"
        else:
            return f"{r.status_code} - Unable to join {guild.name}"

    async def force_join(self, invite: str, token: str):
        if guild := self.__get_guild_from_invite(invite):
            return await self.__join_guild(invite, token, guild)

    async def join(self, invite: str):
        if guild := self.__get_guild_from_invite(invite):
            if any(
                [
                    guild.id in self.cache[t]
                    for t in map(lambda l: l.token, self.workers)
                ]
            ):
                return "There's a worker in this server"

            if token := next(
                (
                    t
                    for t in map(lambda l: l.token, self.workers)
                    if len(self.cache[t]) < 100
                ),
                None,
            ):
                return await self.__join_guild(invite, token, guild)
            else:
                return "Can't use any of the workers"
        else:
            return "This is not a server.."

    async def check_tokens(self):
        for idx, token in enumerate(self.workers):
            await asyncio.sleep(0.5)
            r = self.session.get(
                "https://discord.com/api/v9/users/@me", headers=self.get_headers(token)
            )

            if r.status_code != 200:
                logger.info(f"token {token[:7]} is not available")
                self.workers.remove(token)
            else:
                data = r.json()
                payload = {
                    "username": data["username"],
                    "discriminator": data["discriminator"],
                    "id": int(data["id"]),
                    "token": token,
                }
                self.workers[idx] = User(**payload)
                self.chunk(token)

        guilds = []
        for chunked in self.cache.values():
            guilds.extend(chunked)

        self.guild_count = len(set(guilds))

    def get(self, user_id: int) -> Optional[User]:
        return next((u for u in self.workers if u.id == user_id), None)

    async def start(self):
        logger.info("Setting up workers...")
        await self.check_tokens()
        worker_count = len(self.workers)

        if worker_count == 0:
            logger.info("There are no workers available")
            return

        logger.info(
            f"Worker configured with {worker_count} worker{'s' if worker_count > 0 else ''} sharing {self.guild_count:,} servers"
        )
