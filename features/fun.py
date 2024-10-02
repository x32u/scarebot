import asyncio
import datetime
import random
from contextlib import suppress
from io import BytesIO
from typing import Optional

import discord
from discord.ext import commands

from structure.managers import Context
from structure.scare import Scare


class BlackteaButton(discord.ui.Button):
    def __init__(self):
        self.users = []
        super().__init__(emoji="☕", label="(0)")

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id in self.users:
            self.users.remove(interaction.user.id)
        else:
            self.users.append(interaction.user.id)

        self.label = f"({len(self.users)})"
        return await interaction.response.edit_message(view=self.view)


class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int, label: str):
        self.x = x
        self.y = y
        super().__init__(label=label, row=self.x)

    async def callback(self, interaction: discord.Interaction):
        assert self.view is not None
        self.disabled = True

        match self.view.turn:
            case "X":
                self.style = discord.ButtonStyle.red
                self.label = self.view.turn
                self.view.turn = "O"
                self.view.player = self.view.player2
                self.view.board[self.x][self.y] = self.view.X
            case _:
                self.style = discord.ButtonStyle.green
                self.label = self.view.turn
                self.view.turn = "X"
                self.view.player = self.view.player1
                self.view.board[self.x][self.y] = self.view.O

        if winner := self.view.check_winner():
            self.view.stop()
            match winner:
                case self.view.X:
                    return await interaction.response.edit_message(
                        content=f"{self.view.player1.mention} Won the game!",
                        view=self.view,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )

                case self.view.O:
                    return await interaction.response.edit_message(
                        content=f"{self.view.player2.mention} Won the game!",
                        view=self.view,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                case _:
                    return await interaction.response.edit_message(
                        content=f"It's a tie", view=self.view
                    )

        content = (
            f"It's {self.view.player1.mention}'s turn"
            if self.view.turn == "X"
            else f"It's {self.view.player2.mention}'s turn"
        )
        return await interaction.response.edit_message(
            content=content,
            view=self.view,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class TicTacToe(discord.ui.View):
    def __init__(
        self,
        player1: discord.Member,
        player2: discord.Member,
    ):
        self.player1 = player1
        self.player2 = player2
        self.board = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        self.turn = "X"
        self.player = player1
        self.X = 1
        self.O = -1
        self.tie = 2
        self.stopped = False
        super().__init__()

        for x in range(3):
            for y in range(3):
                self.add_item(TicTacToeButton(x, y, label="ㅤ"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                "It's not your turn", ephemeral=True
            )

        return interaction.user.id == self.player.id

    def check_winner(self) -> Optional[int]:
        if any([sum(s) == 3 for s in self.board]):  # checking if X won on a line
            return self.X

        if any([sum(s) == -3 for s in self.board]):  # checking if O won on a line
            return self.O

        value = sum([self.board[i][i] for i in range(3)])  # checking diagonals
        if value == 3:
            return self.X
        elif value == -3:
            return self.O

        value = sum(
            [self.board[i][2 - i] for i in range(3)]
        )  # checking the secondary diagonal
        if value == 3:
            return self.X
        elif value == -3:
            return self.O

        for i in range(3):  # checking columns
            val = 0
            for j in range(3):
                val += self.board[j][i]

            if val == 3:
                return self.X
            elif val == -3:
                return self.O

        if all([i != 0 for s in self.board for i in s]):  # checking for a tie
            return self.tie

        return None  # the game didn't end

    def stop(self):
        for child in filter(lambda c: not c.disabled, self.children):
            child.disabled = True

        self.stopped = True
        return super().stop()

    async def on_timeout(self):
        if not self.stopped:
            self.stop()
            await self.message.edit(content=f"Time's up", view=self)

class Fun(commands.Cog):
    def __init__(self, bot: Scare):
        self.bot = bot
        self.wyr_questions = []

    async def cog_unload(self):
        self.bot.blacktea_matches.clear()
        return await super().cog_unload()

    @commands.command()
    async def choose(self: "Fun", ctx: Context, *, choices: str):
        """
        Pick a choice out of all choices separated by ,
        """

        choice = random.choice(choices.split(", "))
        return await ctx.neutral(f"**Choice**: {choice}")

    @commands.command(example="do you like me?, yes, no")
    async def poll(self: "Fun", ctx: Context, *, text: str):
        """
        Create a poll
        """

        try:
            question, answers = text.split(", ", maxsplit=1)
        except:
            return await ctx.send_help(ctx.command)

        answers = answers.split(", ")
        if len(answers) < 2:
            return await ctx.send_help(ctx.command)

        poll = discord.Poll(question=question, duration=datetime.timedelta(days=1))

        for answer in answers:
            poll.add_answer(text=answer)

        await ctx.message.delete()
        return await ctx.send(poll=poll)

    @commands.command(aliases=["wyr"])
    async def wouldyourather(self: "Fun", ctx: Context):
        """
        Ask an wouldyourather question
        """

        question = random.choice(self.wyr_questions)[len("Would you rather ") :]
        x, y = question.split(" or ")
        await ctx.send(
            "\n".join(
                [
                    f"# Would you rather:",
                    f"1️⃣ {x.capitalize()}",
                    "**OR**",
                    f"2️⃣ {y[:-1].capitalize()}",
                ]
            )
        )

    @wouldyourather.before_invoke
    async def wyr_invoke(self, _):
        if not self.wyr_questions:
            x = await self.bot.session.get(
                "https://randomwordgenerator.com/json/question-would-you-rather.json"
            )
            self.wyr_questions = list(
                map(lambda m: m["question_would_you_rather"], x.data.all)
            )

    @commands.hybrid_command()
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def randomhex(self: "Fun", ctx: Context):
        """
        Get a random hex code
        """

        r = lambda: random.randint(0, 255)
        hex_code = "#%02X%02X%02X" % (r(), r(), r())
        color = discord.Color.from_str(hex_code)
        embed = (
            discord.Embed(color=color, title=f"Showing hex code: {hex_code}")
            .set_thumbnail(
                url=f"https://singlecolorimage.com/get/{hex_code[1:]}/400x400"
            )
            .add_field(name="RGB value", value=", ".join(map(str, color.to_rgb())))
        )

        return await ctx.reply(embed=embed)

    @commands.hybrid_command()
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def gayrate(
        self: "Fun", ctx: Context, *, member: discord.Member = commands.Author
    ):
        """
        Gayrate a member
        """

        rate = random.randint(0, 100)
        return await ctx.neutral(f"{member.mention} is **{rate}%** gay")
    
    @commands.hybrid_command(aliases=["insult"])
    async def pack(self: "Fun", ctx: Context, *, member: discord.Member):
        """
        Insult a member
        """

        if member == ctx.author:
            return await ctx.reply("Why do you want to pack yourself ://")

        if member == ctx.guild.me:
            return await ctx.reply("Why do you want to pack me :((((")

        result = await self.bot.session.get(
            "https://evilinsult.com/generate_insult.php?lang=en&type=json"
        )
        await ctx.send(
            f"{member.mention} {result.insult}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command()
    @commands.bot_has_permissions(attach_files=True)
    async def cat(self: "Fun", ctx: Context):
        """
        Send a random cat image
        """

        buffer = BytesIO(await self.bot.session.get("https://cataas.com/cat"))
        return await ctx.reply(file=discord.File(buffer, filename="cat.png"))

    @commands.hybrid_command()
    async def dadjoke(self: "Fun", ctx: Context):
        """
        Get a random dad joke
        """

        x = await self.bot.session.get(
            "https://icanhazdadjoke.com/", headers={"Accept": "application/json"}
        )
        return await ctx.neutral(x.joke)

    @commands.hybrid_command(aliases=["ttt"])
    async def tictactoe(self: "Fun", ctx: Context, *, member: discord.Member):
        """
        Play a tictactoe game with a member
        """

        if member.bot:
            return await ctx.alert("You cannot play with a bot")

        view = TicTacToe(ctx.author, member)
        view.message = await ctx.send(
            f"It's {ctx.author.mention}'s turn",
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command()
    @commands.blacktea_round()
    async def blacktea(self: "Fun", ctx: Context):
        """
        Play a match of blacktea
        """

        self.bot.blacktea_matches[ctx.guild.id] = {}

        embed = (
            discord.Embed(
                color=self.bot.color,
                title="BlackTea Matchmaking",
                description=f"The game will begin in **15** seconds. Please click the :coffee: to join the game.",
            )
            .set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
            .add_field(
                name="Goal",
                value=". ".join(
                    [
                        "You have **10** seconds to find a word containing the given set of letters",
                        "Failure to do so, will take away a life",
                        "Each player has **3** lifes",
                        "The last one standing wins",
                    ]
                ),
            )
        )

        view = discord.ui.View(timeout=18)

        async def on_timeout():
            view.children[0].disabled = True
            await view.message.edit(view=view)

        view.on_timeout = on_timeout
        button = BlackteaButton()
        view.add_item(button)

        view.message = await ctx.reply(embed=embed, view=view)
        await asyncio.sleep(15)

        if len(button.users) < 2:
            self.bot.blacktea_matches.pop(ctx.guild.id, None)
            return await ctx.alert("There are not enough players")

        self.bot.blacktea_matches[ctx.guild.id] = {user: 3 for user in button.users}
        words = list(
            filter(
                lambda w: len(w) > 2,
                open("./structure/wordlist.txt").read().splitlines(),
            )
        )

        async def clock(message: discord.Message):
            with suppress(Exception):
                await asyncio.sleep(6)
                await message.add_reaction("3️⃣")
                await asyncio.sleep(1)
                await message.add_reaction("2️⃣")
                await asyncio.sleep(1)
                await message.add_reaction("1️⃣")
                await asyncio.sleep(1)

        while len(self.bot.blacktea_matches[ctx.guild.id].keys()) > 1:
            for user in button.users:
                word = random.choice(words)
                e = discord.Embed(
                    description=f":coffee: <@{user}> Say a word containing **{word[:3].upper()}**"
                )
                m = await ctx.send(embed=e)
                task = asyncio.ensure_future(clock(m))

                try:
                    message = await self.bot.wait_for(
                        "message",
                        timeout=10,
                        check=lambda msg: (
                            msg.author.id == user
                            and msg.channel == ctx.channel
                            and word[:3] in msg.content.lower()
                            and msg.content.lower() in words
                        ),
                    )
                    g = task.cancel()

                    if g is False:
                        print(f"task: {g}")

                    await message.add_reaction("✅")
                except asyncio.TimeoutError:
                    lifes = self.bot.blacktea_matches[ctx.guild.id].get(user)
                    if lifes - 1 == 0:
                        e = discord.Embed(description=f"☠️ <@{user}> You're eliminated")
                        await ctx.send(embed=e)
                        self.bot.blacktea_matches[ctx.guild.id].pop(user)
                        button.users.remove(user)

                        if len(self.bot.blacktea_matches[ctx.guild.id].keys()) == 1:
                            break
                    else:
                        self.bot.blacktea_matches[ctx.guild.id][user] = lifes - 1
                        e = discord.Embed(
                            description=f"🕰️ <@{user}> Time's up. **{lifes-1}** life(s) remaining"
                        )
                        await ctx.send(embed=e)

        user = button.users[0]
        embed = discord.Embed(description=f"👑 <@{user}> Won the game")
        self.bot.blacktea_matches.pop(ctx.guild.id, None)
        return await ctx.send(embed=embed)


async def setup(bot: Scare) -> None:
    return await bot.add_cog(Fun(bot))
