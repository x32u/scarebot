import datetime

from .paginator import Paginator

from discord import Embed, Message, Role, Interaction, SelectOption, ButtonStyle
from discord.ui import View, Select, Button
from discord.embeds import EmbedProxy
from discord.utils import as_chunks, utcnow
from discord.ext import commands
from discord.ext.commands import (
    Context as DefaultContext,
    HelpCommand,
    Group,
    HybridGroup,
)

from typing import Union, List, TYPE_CHECKING, Optional
from pydantic import BaseModel
from math import ceil

if TYPE_CHECKING:
    from structure.scare import Scare


class Reskin(BaseModel):
    username: str
    avatar_url: str
    color: int

class ConfirmView(View):
    def __init__(
        self, 
        author_id: int, 
        yes, 
        no
    ):
        super().__init__()
        self.agree = Button(
            label="Yes",
            style=ButtonStyle.green
        )
        self.disagree = Button(
            label="No",
            style=ButtonStyle.red
        )
        self.agree.callback = yes
        self.disagree.callback = no
        self.author_id = author_id
        self.add_item(self.agree)
        self.add_item(self.disagree)
    
    async def interaction_check(self, interaction: Interaction):
        exp = (interaction.user.id == self.author_id)
        if not exp: 
            await interaction.response.defer(ephemeral=True)
        
        return exp
    
    def stop(self):
        for child in self.children:
            child.disabled = True
        
        return super().stop()

    async def on_timeout(self):
        self.stop()
        embed = self.message.embeds[0]
        embed.description = "Time's up!"
        return await self.message.edit(
            embed=embed,
            view=self
        )

class GroupSelect(Select):
    def __init__(self, group: Group):
        super().__init__(
            placeholder="Select a command",
            options=[
                SelectOption(label=g.qualified_name, description=g.help)
                for g in group.commands
            ],
        )

    async def callback(self, interaction: Interaction):
        color = interaction.message.embeds[0].color
        cmd = interaction.client.get_command(self.values[0])

        params = " ".join(
            (
                f"<{p}>"
                if param.required
                else (
                    f"[{p}]"
                    if not param.displayed_default
                    else f"[{p}={param.displayed_default}]"
                )
            )
            for p, param in cmd.clean_params.items()
        )

        al = (
            list(
                map(
                    lambda r: r.alias,
                    await interaction.client.db.fetch(
                        "SELECT alias FROM aliases WHERE guild_id = $1 AND command = $2",
                        interaction.guild.id,
                        cmd.qualified_name,
                    ),
                )
            )
            or []
        )

        al.extend(cmd.aliases)

        embed = Embed(
            color=color,
            title=f"{'Group' if isinstance(cmd, (Group, HybridGroup)) else 'Command'}: {cmd.qualified_name}",
            description=cmd.help,
            timestamp=utcnow(),
        ).set_footer(text=f"Module: {cmd.cog.qualified_name}")

        if al:
            embed.add_field(
                name=f"Aliases ({len(al)})",
                value=", ".join(map(lambda a: f"`{a}`", al)),
                inline=False,
            )

        embed.add_field(
            name="Usage", value=f"> **{cmd.qualified_name} {params}**", inline=False
        )

        if example := cmd.__original_kwargs__.get("example"):
            embed.add_field(
                name="Example",
                value=f"> **{cmd.qualified_name} {example}**",
                inline=False,
            )

        return await interaction.response.edit_message(embed=embed)


class GroupHelp(View):
    def __init__(self, author_id: int, group: Group):
        super().__init__()
        self.author_id = author_id
        self.add_item(GroupSelect(group))

    async def interaction_check(self, interaction: Interaction):
        if self.author_id != interaction.user.id:
            await interaction.response.defer(ephemeral=True)

        return self.author_id == interaction.user.id

    async def on_timeout(self):
        self.children[0].disabled = True
        self.stop()
        return await self.message.edit(view=self)

class Context(DefaultContext):
    bot: "Scare"

    def find_role(self: "Context", name: str) -> Optional[Role]:
        return next((r for r in self.guild.roles[1:] if name in r.name), None)

    async def get_reskin(self) -> Optional[Reskin]:
        if not self.guild:
            return None

        result = await self.bot.db.fetchrow(
            "SELECT * FROM reskin WHERE user_id = $1", self.author.id
        )

        if not result:
            return None

        r = {
            "username": result.username or self.guild.me.name,
            "avatar_url": result.avatar_url or self.guild.me.display_avatar.url,
            "color": result.color or self.bot.color,
        }

        return Reskin(**r)
    
    async def confirmation(
        self,
        message: str,
        yes,
        no = None
    ):
        async def default_no(interaction: Interaction):
            embed = interaction.message.embeds[0]
            embed.description = "Aborting this action!"
            return await interaction.response.edit_message(
                embed=embed, 
                view=None
            )

        if not no:
            no = default_no
        
        view = ConfirmView(self.author.id, yes, no)
        view.message = await self.neutral(message, view=view)

    async def send(self: "Context", *args, **kwargs) -> Message:
        embeds: List[Embed] = kwargs.get("embeds", [])
        if embed := kwargs.get("embed"):
            embeds.append(embed)

        if self.interaction:
            for embed in embeds:
                self.style(embed, self.bot.color)

            try:
                await self.interaction.response.send_message(*args, **kwargs)
                return await self.interaction.original_response()
            except:
                return await self.interaction.followup.send(*args, **kwargs)

        if patch := kwargs.pop("patch", None):
            kwargs.pop("reference", None)

            if args:
                kwargs["content"] = args[0]

            return await patch.edit(**kwargs)
        else:
            reskin = await self.get_reskin()
            color = reskin.color if reskin else None

            for embed in embeds:
                self.style(embed, color)

            if not reskin:
                return await super().send(*args, **kwargs)
            else:
                try:
                    webhook = next(
                        (
                            w
                            for w in await self.channel.webhooks()
                            if w.user.id == self.bot.user.id
                        ),
                    )
                except StopIteration:
                    webhook = await self.channel.create_webhook(
                        name=f"{self.bot.user.name} - reskin"
                    )

                kwargs["username"] = reskin.username
                kwargs["avatar_url"] = reskin.avatar_url
                kwargs["wait"] = True
                kwargs.pop("delete_after", None)
                return await webhook.send(*args, **kwargs)

    async def reply(self, *args, **kwargs):
        if await self.get_reskin():
            return await self.send(*args, **kwargs)
        else:
            return await super().reply(*args, **kwargs)

    async def confirm(self: "Context", value: str, *args, **kwargs) -> Message:
        embed = Embed(
            description=(
                f"> {self.author.mention}: "
                if not ">" in value
                else ""
            )
            + value,
            color=0x83FF4F,
        )

        return await self.send(
            embed=embed,
            *args,
            **kwargs,
        )

    async def alert(self: "Context", value: str, *args, **kwargs) -> Message:
        embed = Embed(
            description=(
                f"> {self.author.mention}: "
                if not ">" in value
                else ""
            )
            + value,
            color=0xFFD04F,
        )

        return await self.send(
            embed=embed,
            *args,
            **kwargs,
        )

    async def neutral(self: "Context", value: str, **kwargs) -> Message:
        embed = Embed(
            description=(f"> {self.author.mention}: " if not ">" in value else "")
            + value,
            color=0x2B2D31,
        )
        kwargs['embed'] = embed 
        return await self.send(**kwargs)

    async def paginate(
        self: "Context",
        data: List[Union[Embed, EmbedProxy, str]],
        embed: Optional[Embed] = None,
        max_results: int = 10,
        counter: bool = True,
    ) -> Message:
        compiled: List[Union[Embed, str]] = []

        # Initialize total line count
        total_lines = 0
        reskin = await self.get_reskin()
        color = (
            getattr(reskin, "color", None)
            or getattr(getattr(embed or data[0], "color"), "value", None)
            or self.bot.color
        )

        if isinstance(data[0], Embed):
            for index, page in enumerate(data):
                if not isinstance(page, Embed):
                    continue

                self.style(page, color)
                if len(data) > 1:
                    if footer := page.footer:
                        page.set_footer(
                            text=f"{footer.text} ∙ Page {index + 1} / {len(data)}",
                            icon_url=footer.icon_url,
                        )
                    else:
                        page.set_footer(
                            text=f"Page {index + 1} / {len(data)} ({len(data)} entries)",
                        )

                compiled.append(page)

        elif isinstance(data[0], str) and embed:
            pages = ceil(len(data) / max_results)
            self.style(embed, color)

            for chunk in as_chunks(data, max_results):
                page = embed.copy()
                page.description = f"{embed.description or ''}\n\n"

                for line_num, line in enumerate(chunk, start=1 + total_lines):
                    formatted_line_num = (
                        f"{line_num:02}"  # Add leading zero if necessary
                    )
                    page.description += (
                        f"`{formatted_line_num}` {line}\n" if counter else f"{line}\n"
                    )

                # Increment total lines by the number of lines in the current chunk
                total_lines += len(chunk)

                if pages > 1:
                    if footer := page.footer:
                        page.set_footer(
                            text=f"{footer.text} ∙ Page {len(compiled) + 1} / {pages}",
                            icon_url=footer.icon_url,
                        )
                    else:
                        page.set_footer(
                            text=f"Page {len(compiled) + 1} / {pages} ({pages} entries)",
                        )

                compiled.append(page)

        elif isinstance(data[0], str) and not embed:
            for index, page in enumerate(data):
                compiled.append(f"{index + 1}/{len(data)} {page} ({pages} entries)")

        paginator = Paginator(self, compiled)
        return await paginator.begin()

    def style(self: "Context", embed: Embed, color: Optional[int] = None) -> Embed:
        if not embed.color or embed.color.value == self.bot.color:
            embed.color = color or self.bot.color

        return embed


class Help(HelpCommand):
    context: Context

    def __init__(self, **options):
        super().__init__(
            command_attrs={"aliases": ["h", "cmds", "commands"], "hidden": True},
            **options,
        )

    # async def send_bot_help(self, _):
    # return await self.context.neutral(
    # f"Click [**here**](https://scare.life/commands) to view **{len(set(self.context.bot.walk_commands()))}** commands"
    # )

    async def send_bot_help(self, _):
        cogs = tuple(
            cog
            for cog in self.context.bot.cogs.values()
            if cog.get_commands() and not cog.qualified_name in ["Jishaku", "Developer"]
        )
        embeds = []
        embeds.append(
            Embed(
                color=self.context.bot.color,
                description="Subcommands have an asterisk `(*)`",
            )
            .set_author(
                name=self.context.author.name,
                icon_url=self.context.author.display_avatar.url,
            )
            .set_thumbnail(url=self.context.bot.user.display_avatar.url)
            .add_field(
                name="Links",
                value=f"[**website**](https://scare.life)\n[**invite**]({self.context.bot.invite_url})",
            )
        )
        for idx, cog in enumerate(cogs, start=1):
            embeds.append(
                Embed(
                    color=self.context.bot.color,
                    # title=cog.qualified_name,
                    url="https://scare.life/commands",
                    description=f"```{', '.join(cmd.name + ('*' if isinstance(cmd, commands.Group) else '') for cmd in cog.get_commands())}```",
                )
                .set_author(
                    name=self.context.author.name,
                    icon_url=self.context.author.display_avatar.url,
                )
                .set_thumbnail(url=self.context.bot.user.display_avatar.url)
                .set_footer(
                    text=f"Module: {cog.qualified_name} | {len(tuple(cog.walk_commands()))} commands"
                )
            )
        await self.context.paginate(embeds)

    async def send_command_help(self, command: commands.Command):
        params = " ".join(
            (
                f"<{p}>"
                if param.required
                else (
                    f"[{p}]"
                    if not param.displayed_default
                    else f"[{p}={param.displayed_default}]"
                )
            )
            for p, param in command.clean_params.items()
        )

        al = (
            list(
                map(
                    lambda r: r.alias,
                    await self.context.bot.db.fetch(
                        "SELECT alias FROM aliases WHERE guild_id = $1 AND command = $2",
                        self.context.guild.id,
                        command.qualified_name,
                    ),
                )
            )
            or []
        )

        al.extend(command.aliases)

        embed = Embed(
            title=f"Command: {command.qualified_name}",
            timestamp=datetime.datetime.now(),
            description=command.help,
        ).set_author(
            name=self.context.author.name,
            icon_url=self.context.author.display_avatar.url,
        )

        if cog := command.cog:
            embed.set_footer(text=f"Module: {cog.qualified_name}")

        if al:
            embed.add_field(
                name=f"Aliases ({len(al)})",
                value=", ".join(map(lambda a: f"`{a}`", al)),
                inline=False,
            )

        embed.add_field(
            name="Usage", value=f"> **{command.qualified_name} {params}**", inline=False
        )

        if example := command.__original_kwargs__.get("example"):
            embed.add_field(
                name="Example",
                value=f"> **{command.qualified_name} {example}**",
                inline=False,
            )

        return await self.context.reply(embed=embed)

    async def send_group_help(self, group: Group) -> None:
        embed = Embed(
            description=f"Use the **dropdown** below to view **{len(group.commands)} commands** for **{group.qualified_name}**"
        )

        view = GroupHelp(self.context.author.id, group)
        view.message = await self.context.reply(embed=embed, view=view)

        """          
        aliases = f"**Aliases:** `{', '.join(group.aliases)}`" if group.aliases else ""

        embed = Embed(
          timestamp=datetime.datetime.now(),
          color=self.context.bot.color, 
          description=f"{self.context.clean_prefix}{group.qualified_name}\n\n`{group.help}`\n{aliases}"
        )\
        .add_field(
          name="Commands",
          value="\n".join(
              f"{self.context.clean_prefix}{cmd.qualified_name} - `{cmd.help}`" for cmd in group.commands
        ))\
        .set_footer(
          text=f"Module: {group.cog.qualified_name}"
        )
        return await self.context.send(embed=embed)
        """
