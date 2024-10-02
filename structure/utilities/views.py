import json
from io import BytesIO
from typing import Any, List, Optional, Union

import discord


class VoiceRename(discord.ui.Modal, title="Rename your voice channel"):
    name = discord.ui.TextInput(
        label="Name",
        style=discord.TextStyle.short,
        placeholder="The voice channel's new name",
        max_length=32,
        min_length=2,
        custom_id="vm:modal",
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.user.voice.channel.edit(name=self.name.value)
        return await interaction.response.send_message(
            f"Renamed your voice channel to **{self.name.value}**", ephemeral=True
        )

    async def on_error(self, interaction: discord.Interaction, _):
        return await interaction.response.send_message(
            "An error occured while trying to edit your voice channel's name",
            ephemeral=True,
        )


class VoiceMasterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction):
        channel = getattr(interaction.user.voice, "channel", None)

        if not channel:
            await interaction.response.send_message(
                "You are not in a voice channel", ephemeral=True
            )
            return False

        results = await interaction.client.db.fetchval(
            "SELECT voice_channels FROM voicemaster WHERE guild_id = $1",
            interaction.guild.id,
        )

        if not results:
            await interaction.response.send_message(
                "The voicemaster feature is not configured in this server",
                ephemeral=True,
            )
            return False

        voice_channels: dict = json.loads(results)

        if not str(channel.id) in voice_channels.keys():
            await interaction.response.send_message(
                "You are **not** in a voice channel created by me", ephemeral=True
            )
            return False

        if voice_channels[str(channel.id)] != interaction.user.id:
            await interaction.response.send_message(
                "You do **not** own this voice channel", ephemeral=True
            )
            return False

        return True

    @discord.ui.button(emoji="<:lock:1280900500572864565>", custom_id="vm:lock")
    async def voicemaster_lock(self, interaction: discord.Interaction, _):
        if (
            interaction.user.voice.channel.permissions_for(
                interaction.guild.default_role
            ).connect
            != False
        ):
            await interaction.user.voice.channel.set_permissions(
                interaction.guild.default_role, connect=False
            )
            return await interaction.response.send_message(
                f"Locked {interaction.user.voice.channel.mention}", ephemeral=True
            )

        return await interaction.response.send_message(
            f"{interaction.user.voice.channel.mention} is **already** locked",
            ephemeral=True,
        )

    @discord.ui.button(emoji="<:unlock:1280900508638515240>", custom_id="vm:unlock")
    async def voicemaster_unlock(self, interaction: discord.Interaction, _):
        if (
            interaction.user.voice.channel.permissions_for(
                interaction.guild.default_role
            ).connect
            == False
        ):
            await interaction.user.voice.channel.set_permissions(
                interaction.guild.default_role, connect=True
            )
            return await interaction.response.send_message(
                f"Unlocked {interaction.user.voice.channel.mention}", ephemeral=True
            )
        return await interaction.response.send_message(
            f"{interaction.user.voice.channel.mention} is **already** unlocked",
            ephemeral=True,
        )

    @discord.ui.button(emoji="<:ghost:1280900494914617416>", custom_id="vm:hide")
    async def voicemaster_hide(self, interaction: discord.Interaction, _):
        if (
            interaction.user.voice.channel.permissions_for(
                interaction.guild.default_role
            ).view_channel
            != False
        ):
            await interaction.user.voice.channel.set_permissions(
                interaction.guild.default_role, view_channel=False
            )

            return await interaction.response.send_message(
                f"Hidden {interaction.user.voice.channel.mention}", ephemeral=True
            )

        return await interaction.response.send_message(
            f"{interaction.user.voice.channel.mention} is **already** hidden",
            ephemeral=True,
        )

    @discord.ui.button(emoji="<:unghost:1280900506361008131>", custom_id="vm:reveal")
    async def voicemaster_reveal(self, interaction: discord.Interaction, _):
        if (
            interaction.user.voice.channel.permissions_for(
                interaction.guild.default_role
            ).view_channel
            == False
        ):
            await interaction.user.voice.channel.set_permissions(
                interaction.guild.default_role, view_channel=True
            )

            return await interaction.response.send_message(
                f"Revealed {interaction.user.voice.channel.mention}", ephemeral=True
            )

        return await interaction.response.send_message(
            f"{interaction.user.voice.channel.mention} is **not** hidden",
            ephemeral=True,
        )

    @discord.ui.button(emoji="<:info:1280900496852516936>", custom_id="vm:rename")
    async def voice_rename(self, interaction: discord.Interaction, _):
        return await interaction.response.send_modal(VoiceRename())


class Giveaway(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="(0)", emoji="🎉", custom_id="gw", style=discord.ButtonStyle.blurple
    )
    async def giveaway_join(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        members = (
            await interaction.client.db.fetchval(
                """
            SELECT members FROM giveaway
            WHERE guild_id = $1
            AND channel_id = $2
            AND message_id = $3 
            """,
                interaction.guild.id,
                interaction.channel.id,
                interaction.message.id,
            )
            or []
        )

        if interaction.user.id in members:
            members.remove(interaction.user.id)
        else:
            members.append(interaction.user.id)

        await interaction.client.db.execute(
            """
            UPDATE giveaway SET members = $1
            WHERE guild_id = $2 AND channel_id = $3
            AND message_id = $4
            """,
            members,
            interaction.guild.id,
            interaction.channel.id,
            interaction.message.id,
        )
        button.label = f"({len(members)})"
        return await interaction.response.edit_message(view=self)


class TicketClose(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction):
        support = (
            await interaction.client.db.fetchval(
                "SELECT support FROM tickets WHERE guild_id = $1", interaction.guild.id
            )
            or []
        )

        if (
            not interaction.user.id in support
            and not interaction.user.guild_permissions.administrator
        ):
            await interaction.neutral(
                "Only a support or administrator can close the ticket"
            )
            return False

        return True

    @discord.ui.button(
        label="Close", style=discord.ButtonStyle.red, custom_id="ticket:close"
    )
    async def closeticket(self, interaction: discord.Interaction, _):
        if logs_id := await interaction.client.db.fetchval(
            "SELECT logs_id FROM tickets WHERE guild_id = $1", interaction.guild.id
        ):
            if logs := interaction.guild.get_channel(logs_id):
                messages = [
                    message
                    async for message in interaction.channel.history(oldest_first=True)
                ]
                buffer = BytesIO(
                    bytes(
                        "\n".join(
                            [
                                (
                                    f"[{message.created_at.strftime('%a %d %Y %I:%M:%S %p UTC')}]"
                                    f" @{message.author} - {message.clean_content}"
                                )
                                for message in messages
                            ]
                        ),
                        "utf-8",
                    )
                )
                file = discord.File(
                    buffer, filename=f"logs-{interaction.channel.id}.txt"
                )
                embed = discord.Embed(
                    color=interaction.client.color,
                    description=f"Logs of **{interaction.channel}** (`{interaction.channel.id}`)",
                )
                await logs.send(embed=embed, file=file)

        return await interaction.channel.delete()


class TicketView(discord.ui.View):
    def __init__(self):
        self.topic = "General"
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction):
        channel_id = await interaction.client.db.fetchval(
            """
            SELECT channel_id FROM opened_tickets 
            WHERE user_id = $1 AND guild_id = $2
            """,
            interaction.user.id,
            interaction.guild.id,
        )

        channel = interaction.guild.get_channel(channel_id)

        if channel:
            await interaction.alert(
                f"You already have a ticket opened -> {channel.mention}"
            )

        return channel is None

    async def open_ticket(
        self,
        interaction: discord.Interaction,
        category: Optional[discord.CategoryChannel],
        support: List[int],
        res: dict,
    ):
        permissions = getattr(category, "overwrites", {})
        permissions[interaction.user] = discord.PermissionOverwrite(
            send_messages=True, view_channel=True, attach_files=True, embed_links=True
        )

        permissions.update(
            {
                discord.Object(s): discord.PermissionOverwrite(
                    send_messages=True,
                    view_channel=True,
                    attach_files=True,
                    embed_links=True,
                )
                for s in support
            }
        )

        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            overwrites=permissions,
            category=category,
            reason="Creating a ticket channel",
            topic=f"Ticket opened for {interaction.user} (`{interaction.user.id}`)",
        )

        await interaction.client.db.execute(
            """
            INSERT INTO opened_tickets VALUES ($1,$2,$3)
            ON CONFLICT (guild_id, user_id) DO UPDATE 
            SET channel_id = $3
            """,
            interaction.guild.id,
            interaction.user.id,
            channel.id,
        )

        try:
            await channel.send(**res)
        except:
            res = await interaction.client.embed.convert(
                interaction.user,
                "{content: Hey {user.mention}} {color: #2b2d31} {title: Ticket - {topic}} {description: Please state your problem in this channel and support will get to you shortly!} {author: {guild.name} && {guild.icon}}",
                {"topic": self.topic},
            )
            res["view"] = TicketClose()
            await channel.send(**res)

        return await interaction.followup.send(
            f"Opened a ticket for you -> {channel.mention}", ephemeral=True
        )

    async def get_open_embed(
        self, interaction: discord.Interaction, result, topic: Optional[str] = "General"
    ):
        res = await interaction.client.embed.convert(
            interaction.user, result.open_message, {"topic": topic}
        )
        res.pop("delete_after", None)
        res["view"] = TicketClose()
        return res

    @discord.ui.button(label="Open", custom_id="ticket:open")
    async def ticket(self, interaction: discord.Interaction, _):
        result = await interaction.client.db.fetchrow(
            "SELECT * FROM tickets WHERE guild_id = $1", interaction.guild.id
        )

        if not result:
            return await interaction.response.send_message(
                "The tickets feature is **not** configured", ephemeral=True
            )

        if topics := result.topics:
            select = discord.ui.Select(
                placeholder="Select a topic",
                options=[discord.SelectOption(**topic) for topic in topics],
            )

            async def callback(inter: discord.Interaction):
                if await self.interaction_check(inter):
                    topic = select.values[0]
                    self.topic = topic
                    await inter.response.defer(ephemeral=True)
                    return await self.open_ticket(
                        inter,
                        inter.guild.get_channel(result.category_id),
                        result.support or [],
                        await self.get_open_embed(inter, result, topic),
                    )

            select.callback = callback
            view = discord.ui.View(timeout=None)
            view.add_item(select)
            return await interaction.response.send_message(
                "Select a topic", view=view, ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        return await self.open_ticket(
            interaction,
            interaction.guild.get_channel(result.category_id),
            result.support or [],
            await self.get_open_embed(interaction, result),
        )


# tanks guys for da plural class :3
class plural:
    def __init__(
        self: "plural",
        value: Union[int, str, List[Any]],
        number: bool = True,
        md: str = "",
    ):
        self.value: int = (
            len(value)
            if isinstance(value, list)
            else (
                (
                    int(value.split(" ", 1)[-1])
                    if value.startswith(("CREATE", "DELETE"))
                    else int(value)
                )
                if isinstance(value, str)
                else value
            )
        )
        self.number: bool = number
        self.md: str = md

    def __format__(self: "plural", format_spec: str) -> str:
        v = self.value
        singular, sep, plural = format_spec.partition("|")
        plural = plural or f"{singular}s"
        result = f"{self.md}{v:,}{self.md} " if self.number else ""

        result += plural if abs(v) != 1 else singular
        return result


def shorten(value: str, length: int = 24) -> str:
    if len(value) > length:
        value = value[: length - 2] + (".." if len(value) > length else "").strip()

    return value


def format_duration(value: int, ms: bool = True) -> str:
    h = int((value / (1000 * 60 * 60)) % 24) if ms else int((value / (60 * 60)) % 24)
    m = int((value / (1000 * 60)) % 60) if ms else int((value / 60) % 60)
    s = int((value / 1000) % 60) if ms else int(value % 60)

    result = ""
    if h:
        result += f"{h}:"

    result += "00:" if not m else f"{m}:"
    result += "00" if not s else f"{str(s).zfill(2)}"

    return result
