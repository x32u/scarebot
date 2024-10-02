from typing import Any, Dict, Optional

from aiohttp import ClientSession as DefaultClientSession
from aiohttp import ClientTimeout
from munch import DefaultMunch
from yarl import URL


class ClientSession(DefaultClientSession):
    def __init__(self, **kwargs):
        if k := kwargs.get("base_url"):
            self.base_url = k
            kwargs.pop("base_url")
        else:
            self.base_url = None

        super().__init__(
            timeout=ClientTimeout(total=15),
            raise_for_status=True,
            **kwargs,
        )

    async def get(self: "ClientSession", url: Optional[str] = None, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def put(self: "ClientSession", url: Optional[str] = None, **kwargs):
        return await self.request("PUT", url, **kwargs)

    async def post(self: "ClientSession", url: Optional[str] = None, **kwargs):
        return await self.request("POST", url, **kwargs)

    async def patch(self: "ClientSession", url: Optional[str] = None, **kwargs):
        return await self.request("PATCH", url, **kwargs)

    async def request(self: "ClientSession", method: str, url=None, **kwargs) -> Any:

        slug: Optional[str] = kwargs.pop("slug", None)
        response = await super().request(
            method=method,
            url=URL(url or self.base_url),
            **kwargs,
        )

        if response.content_type == "text/plain":
            return await response.text()

        elif response.content_type.startswith(("image/", "video/", "audio/")):
            return await response.read()

        elif response.content_type == "text/html":
            return await response.text()

        elif response.content_type in (
            "application/json",
            "application/octet-stream",
            "text/javascript",
        ):
            try:
                data: Dict = await response.json(content_type=None)
            except Exception:
                return response

            munch = DefaultMunch.fromDict(data)
            if slug:
                for path in slug.split("."):
                    if path.isnumeric() and isinstance(munch, list):
                        try:
                            munch = munch[int(path)]
                        except IndexError:
                            pass

                    munch = getattr(munch, path, munch)

            return munch

        return response
