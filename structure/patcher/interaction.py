from contextlib import suppress

from discord import Embed, InteractionResponded, WebhookMessage
from discord.interactions import Interaction


async def neutral(self, value: str, **kwargs) -> WebhookMessage:
    with suppress(InteractionResponded):
        await self.response.defer(ephemeral=True)

    return await self.followup.send(
        embed=Embed(
            description=(f"> {self.user.mention}: " if not ">" in value else "")
            + value,
            color=0x2B2D31,
        ),
        ephemeral=True,
        **kwargs,
    )


async def alert(self, value: str, **kwargs) -> WebhookMessage:
    with suppress(InteractionResponded):
        await self.response.defer(
            ephemeral=True,
        )

    return await self.followup.send(
        embed=Embed(
            description=(f"> {self.user.mention}: " if not ">" in value else "")
            + value,
            color=0xFFD04F,
        ),
        ephemeral=True,
        **kwargs,
    )


Interaction.neutral = neutral
Interaction.alert = alert
