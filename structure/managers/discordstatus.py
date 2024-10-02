import asyncio
from typing import Any, Dict, List, Optional, Union

from aiohttp import ClientSession
from bs4 import BeautifulSoup
from discord import Embed
from pydantic import BaseModel


class Page(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    url: Optional[str] = None
    time_zone: Optional[str] = None
    updated_at: Optional[str] = None


class Incident(BaseModel):
    name: str
    shortlink: str


class Component(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    position: Optional[int] = None
    description: Optional[str] = None
    showcase: Optional[bool] = None
    start_date: Optional[str] = None
    group_id: Optional[str] = None
    page_id: Optional[str] = None
    group: Optional[bool] = None
    only_show_if_degraded: Optional[bool] = None
    components: Optional[List[str]] = None


class Status(BaseModel):
    indicator: Optional[str] = None
    description: Optional[str] = None


class ScheduledMaintenance(BaseModel):
    name: str
    shortlink: str
    status: str


class DiscordStatus(BaseModel):
    page: Optional[Page] = None
    components: Optional[List[Component]] = None
    incidents: Optional[List[Incident]] = None
    scheduled_maintenances: Optional[List[ScheduledMaintenance]] = None
    status: Optional[Status] = None

    def to_embed(self, bot: Any, incident_locked: Optional[bool] = True):
        embed = Embed(color=bot.color)
        if incident_locked:
            if self.incidents:
                value = ""
                for insident in self.incidents:
                    value += f"[{insident.name}]({insident.shortlink})\n"
                embed.add_field(name="Incidents", value=value, inline=False)
        if self.scheduled_maintenances:
            values = ""
            for _ in self.scheduled_maintenances:
                values += f"[{_.name} - {_.status.upper()}]({_.shortlink})\n"
            embed.add_field(name="Maintenance", value=values, inline=False)
        embed.description = self.status.description
        return embed

    @classmethod
    async def from_response(cls):
        async with ClientSession() as session:
            async with session.get(
                "https://discordstatus.com/api/v2/summary.json"
            ) as response:
                data = await response.read()
        return cls.parse_raw(data)
