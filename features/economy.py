import asyncio
import datetime
import secrets
from collections import defaultdict
from typing import Annotated, Optional, Union

import discord
from discord.ext import commands

from structure.scare import Scare
from structure.managers import Context
from structure.utilities import Bank, Value


class Blackjack(discord.ui.View):
    def __init__(self, author_id: int, bet: int):
        self.author_id = author_id
        self.bet = bet
        self.ended = False
        self.win = "🏆"
        self.lose = "😔"
        self.deck = [f"{s} {n}" for s in ["♣", "♦", "♥", "♠"] for n in range(1, 11)]
        super().__init__()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.defer(ephemeral=True)
            return False

        return True

    def stop(self):
        self.ended = True
        for child in self.children:
            child.disabled = True

        return super().stop()

    async def on_timeout(self):
        if not self.ended:
            self.stop()
            embed = self.message.embeds[0]
            embed.description = "The game ended due to inactivity"
            return await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.green)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        card = secrets.choice(self.deck)
        self.deck.remove(card)

        embed = interaction.message.embeds[0]

        cards = list(map(lambda c: c[1:-1], embed.fields[0].value.split(", ")))
        cards.append(card)
        value = sum([int(c.split(" ")[1]) for c in cards])
        embed.set_field_at(
            0,
            name=f"Your cards ({value})",
            value=", ".join(map(lambda c: f"`{c}`", cards)),
            inline=False,
        )

        if value == 21:
            self.stop()
            interaction.client.blackjack_matches.remove(interaction.user.id)
            embed.description = f"{self.win} You just hit the **blackjack** and won **{self.bet:,} credits**"
            await interaction.client.db.execute(
                "UPDATE economy SET credits = credits + $1 WHERE user_id = $2",
                self.bet,
                interaction.user.id,
            )
        elif value > 21:
            self.stop()
            interaction.client.blackjack_matches.remove(interaction.user.id)
            embed.description = (
                f"{self.lose} You just **busted** and lost **{self.bet:,} credits**"
            )
            await interaction.client.db.execute(
                "UPDATE economy SET credits = credits - $1 WHERE user_id = $2",
                self.bet,
                interaction.user.id,
            )

        return await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        player_cards = list(map(lambda c: c[1:-1], embed.fields[0].value.split(", ")))
        player_value = sum([int(c.split(" ")[1]) for c in player_cards])

        dealer_cards = list(map(lambda c: c[1:-1], embed.fields[1].value.split(", ")))
        dealer_value = sum([int(c.split(" ")[1]) for c in dealer_cards])
        target = player_value if player_value < 17 else 17

        while dealer_value < target:
            card = secrets.choice(self.deck)
            self.deck.remove(card)
            dealer_cards.append(card)
            dealer_value += int(card.split(" ")[1])

        embed.set_field_at(
            1,
            name=f"Dealer's cards ({dealer_value})",
            value=", ".join(map(lambda c: f"`{c}`", dealer_cards)),
            inline=False,
        )

        self.stop()
        interaction.client.blackjack_matches.remove(interaction.user.id)
        if dealer_value == 21:
            embed.description = f"{self.lose} The dealer hit the **blackjack** and you lost **{self.bet:,} credits**"
            await interaction.client.db.execute(
                "UPDATE economy SET credits = credits - $1 WHERE user_id = $2",
                self.bet,
                interaction.user.id,
            )
        elif dealer_value > 21:
            embed.description = (
                f"{self.win} The dealer **busted** and you won **{self.bet:,} credits**"
            )
            await interaction.client.db.execute(
                "UPDATE economy SET credits = credits + $1 WHERE user_id = $2",
                self.bet,
                interaction.user.id,
            )
        elif dealer_value > player_value:
            embed.description = f"{self.lose} The dealer got a **{dealer_value}** and you lost **{self.bet:,} credits**"
            await interaction.client.db.execute(
                "UPDATE economy SET credits = credits - $1 WHERE user_id = $2",
                self.bet,
                interaction.user.id,
            )
        elif dealer_value < player_value:
            embed.description = f"{self.win} The dealer got a **{dealer_value}** and you won **{self.bet:,} credits**"
            await interaction.client.db.execute(
                "UPDATE economy SET credits = credits + $1 WHERE user_id = $2",
                self.bet,
                interaction.user.id,
            )
        elif dealer_value == player_value:
            embed.description = f"It's a tie"

        return await interaction.response.edit_message(embed=embed, view=self)


class Transfer(discord.ui.View):
    def __init__(self, author_id: int, member: discord.Member, amount: int):
        self.author_id = author_id
        self.member = member
        self.amount = amount
        self.stopped = False
        super().__init__(timeout=60)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.defer(ephemeral=True)
            return False
        return True

    def stop(self):
        for child in self.children:
            child.disabled = True

        return super().stop()

    async def on_timeout(self):
        if not self.stopped:
            self.stop()
            return await self.message.edit(content="Time's up", view=self)

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def yes_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        credits = await interaction.client.db.fetchval(
            "SELECT credits FROM economy WHERE user_id = $1", interaction.user.id
        )

        embed = interaction.message.embeds[0]
        embed.description = "You do not have enough **credits** to finish this transfer"
        self.stopped = True

        if credits < self.amount:
            return await interaction.response.edit_message(embed=embed, view=None)

        await interaction.client.db.execute(
            "UPDATE economy SET credits = credits - $1 WHERE user_id = $2",
            self.amount,
            interaction.user.id,
        )

        await interaction.client.db.execute(
            """
            INSERT INTO economy (user_id, credits, bank) VALUES ($1,$2,$3)
            ON CONFLICT (user_id) DO UPDATE SET credits = economy.credits + $2
            """,
            self.member.id,
            self.amount,
            0,
        )

        embed.description = f"You have succesfully transfered `{self.amount:,}` credits to {self.member.mention}"

        return await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="No", style=discord.ButtonStyle.red)
    async def no_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.stopped = True
        embed = interaction.message.embeds[0]
        embed.description = "The transfer was cancelled"
        return await interaction.response.edit_message(embed=embed, view=None)


class Economy(commands.Cog):
    def __init__(self, bot: Scare):
        self.bot = bot
        self.locks = defaultdict(asyncio.Lock)
        self.roll_numbers = list(range(51))
        self.roll_numbers.extend(range(101))
        self.jobs = []

    async def cog_check(self, ctx: Context):
        await self.bot.db.execute(
            """
            INSERT INTO economy VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT (user_id) DO NOTHING  
            """,
            ctx.author.id,
            36200,
            0,
            (discord.utils.utcnow() + datetime.timedelta(days=1)),
            (discord.utils.utcnow() + datetime.timedelta(days=30)),
        )

        if (
            ctx.author.id in self.bot.blackjack_matches
            and not ctx.command.qualified_name in ["balance", "daily"]
        ):
            raise commands.BadArgument(
                "You cannot execute this command while playing **blackjack**"
            )

        return True

    @commands.hybrid_command(aliases=["bj"])
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def blackjack(self: "Economy", ctx: Context, bet: Annotated[int, Value]):
        """
        Play a game of blackjack
        """

        self.bot.blackjack_matches.append(ctx.author.id)
        if bet > 5000:
            bet = 5000

        view = Blackjack(ctx.author.id, bet)

        player_cards = []
        player_value = 0

        dealer_cards = []
        dealer_value = 0

        for _ in range(2):
            player_card = secrets.choice(view.deck)
            view.deck.remove(player_card)
            player_cards.append(player_card)
            player_value += int(player_card.split(" ")[1])

            dealer_card = secrets.choice(view.deck)
            view.deck.remove(dealer_card)
            dealer_cards.append(dealer_card)
            dealer_value += int(dealer_card.split(" ")[1])

        embed = discord.Embed(title="Blackjack")
        embed.set_thumbnail(url="https://scare.life/static/cards.png")
        embed.add_field(
            name=f"Your cards ({player_value})",
            value=", ".join(map(lambda c: f"`{c}`", player_cards)),
            inline=False,
        )
        embed.add_field(
            name=f"Dealer's cards ({dealer_value})",
            value=", ".join(map(lambda c: f"`{c}`", dealer_cards)),
            inline=False,
        )

        view.message = await ctx.reply(embed=embed, view=view)

    @commands.hybrid_command()
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def roll(self: "Economy", ctx: Context, bet: Annotated[int, Value]):
        """
        Roll a dice
        """

        async with self.locks[ctx.author.id]:
            if bet > 5000:
                bet = 5000

            number = secrets.choice(self.roll_numbers)
            sign = "+" if number > 50 else "-"

            await self.bot.db.execute(
                f"UPDATE economy SET credits = credits {sign} $1 WHERE user_id = $2",
                bet,
                ctx.author.id,
            )

            return await ctx.confirm(
                f"You rolled a **{number}**/100 and {'won' if sign == '+' else 'lost'} `{bet:,}` credits"
            )

    @commands.hybrid_command(aliases=["pay"])
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def transfer(
        self: "Economy",
        ctx: Context,
        amount: Annotated[int, Value],
        *,
        member: Union[discord.Member, discord.User],
    ):
        """
        Transfer credits to a member
        """

        if member.bot:
            return await ctx.alert("You cannot transfer credits to a bot")

        view = Transfer(ctx.author.id, member, amount)

        embed = discord.Embed(
            description=f"Are you sure you want to send **{amount:,}** credits to {member.mention}?"
        )
        view.message = await ctx.reply(embed=embed, view=view)

    @commands.hybrid_command(aliases=["dep"])
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def deposit(self: "Economy", ctx: Context, amount: Annotated[int, Value]):
        """
        Deposit credits to your bank
        """

        await self.bot.db.execute(
            """
            UPDATE economy SET credits = credits - $1,
            bank = bank + $1 WHERE user_id = $2   
            """,
            amount,
            ctx.author.id,
        )

        return await ctx.confirm(f"Transfered `{amount:,}` credits to bank")

    @commands.hybrid_command()
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def withdraw(self: "Economy", ctx: Context, amount: Annotated[int, Bank]):
        """
        Withdraw credits from your bank
        """

        await self.bot.db.execute(
            """
            UPDATE economy SET credits = credits + $1,
            bank = bank - $1 WHERE user_id = $2   
            """,
            amount,
            ctx.author.id,
        )

        return await ctx.confirm(f"Withdrawn `{amount:,}` credits from the bank")

    @commands.hybrid_command()
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def monthly(self: "Economy", ctx: Context):
        """
        Collect your monthly amount of credits
        """

        async with self.locks[ctx.author.id]:
            monthly_datetime = await self.bot.db.fetchval(
                "SELECT monthly FROM economy WHERE user_id = $1", ctx.author.id
            )

            if monthly_datetime:
                if monthly_datetime > discord.utils.utcnow():
                    return await ctx.alert(
                        f"You can claim your monthly credits {discord.utils.format_dt(monthly_datetime, style='R')}"
                    )

            await self.bot.db.execute(
                """
                UPDATE economy SET credits = credits + $1,
                monthly = $2 WHERE user_id = $3 
                """,
                35000,
                (discord.utils.utcnow() + datetime.timedelta(days=30)),
                ctx.author.id,
            )

            return await ctx.confirm(
                f"You have collected `35,000` credits. Come back next month"
            )

    @commands.hybrid_command()
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def daily(self: "Economy", ctx: Context):
        """
        Collect your daily amount of credits
        """

        async with self.locks[ctx.author.id]:
            daily_datetime = await self.bot.db.fetchval(
                "SELECT daily FROM economy WHERE user_id = $1", ctx.author.id
            )

            if daily_datetime:
                if daily_datetime > discord.utils.utcnow():
                    return await ctx.alert(
                        f"You can claim your daily credits {discord.utils.format_dt(daily_datetime, style='R')}"
                    )

            await self.bot.db.execute(
                """
                UPDATE economy SET credits = credits + $1,
                daily = $2 WHERE user_id = $3 
                """,
                1000,
                (discord.utils.utcnow() + datetime.timedelta(days=1)),
                ctx.author.id,
            )

            return await ctx.confirm(
                f"You have collected `1,000` credits. Come back tomorrow"
            )

    @commands.hybrid_command()
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def work(self: "Economy", ctx: Context):
        """
        Work and get paid
        """

        job = secrets.choice(self.jobs)
        amount = secrets.choice(list(range(1, 300)))

        await self.bot.db.execute(
            """
            UPDATE economy SET credits = credits + $1
            WHERE user_id = $2
            """,
            amount,
            ctx.author.id,
        )

        return await ctx.neutral(
            (
                "You worked as "
                f"a{'n' if job.lower().startswith(('a', 'e', 'i', 'o', 'u')) else ''} "
                f"**{job}** and earned **{amount:,}** credits"
            )
        )

    @work.before_invoke
    async def work_invoke(self, _):
        if not self.jobs:
            x = await self.bot.session.get("https://www.randomlists.com/data/jobs.json")
            self.jobs = x["data"]

    @work.error
    async def on_work_error(self, ctx: Context, error: commands.CommandError):
        original = getattr(error, "original", error)

        if isinstance(original, commands.CommandOnCooldown):
            date = discord.utils.utcnow() + datetime.timedelta(
                seconds=original.retry_after
            )
            return await ctx.alert(
                f"You can work again {discord.utils.format_dt(date, style='R')}"
            )

    @commands.hybrid_command()
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def rob(self: "Economy", ctx: Context, *, member: discord.Member):
        """
        Rob a member
        """

        if member == ctx.author:
            return await ctx.alert("You cannot rob yourself")

        if member.bot:
            return await ctx.alert("You cannot rob a bot")

        member_credits: Optional[int] = await self.bot.db.fetchval(
            "SELECT credits FROM economy WHERE user_id = $1", member.id
        )

        if not member_credits or member_credits == 0:
            return await ctx.alert("This member has no money")

        points = secrets.choice(range(1, int(member_credits / 4)))

        m = await ctx.neutral(
            f"Waiting **10 seconds** for {member.mention} to respond. If failure to do so, `{points:,}` credits will be stolen from them"
        )
        e = m.embeds[0]
        try:
            await self.bot.wait_for(
                "message",
                check=lambda msg: msg.author.id == member.id
                and msg.channel.id == ctx.channel.id,
                timeout=10,
            )

            e.description = f"{member.mention} replied so they cannot be robbed"
        except asyncio.TimeoutError:
            e.description = f"`{points:,}` credits were stolen from {member.mention}"

            for member_id, sign in zip([ctx.author.id, member.id], ["+", "-"]):
                await self.bot.db.execute(
                    f"UPDATE economy SET credits = credits {sign} $1 WHERE user_id = $2",
                    points,
                    member_id,
                )
        finally:
            return await m.edit(embed=e)

    @rob.error
    async def on_rob_error(self, ctx: Context, error: commands.CommandError):
        original = getattr(error, "original", error)

        if isinstance(original, commands.CommandOnCooldown):
            date = discord.utils.utcnow() + datetime.timedelta(
                seconds=original.retry_after
            )
            return await ctx.alert(
                f"You can rob again {discord.utils.format_dt(date, style='R')}"
            )

    @commands.hybrid_command(aliases=["lb"])
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def leaderboard(self: "Economy", ctx: Context):
        """
        Get the top members with most credits
        """

        results = list(
            filter(
                lambda m: self.bot.get_user(m.user_id),
                await self.bot.db.fetch(
                    "SELECT * FROM economy ORDER BY economy.credits + economy.bank DESC"
                ),
            )
        )

        if not results:
            return await ctx.alert("There are no members to display on the leaderboard")

        return await ctx.paginate(
            [
                f"{self.bot.get_user(r.user_id)} (`{r.user_id}`) has **{(r.credits + r.bank):,} total credits**"
                for r in results
            ],
            discord.Embed(title=f"Economy leaderboard ({len(results)})"),
        )

    @commands.hybrid_command(aliases=["bal"])
    @discord.app_commands.allowed_installs(guilds=True, users=True)
    @discord.app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def balance(
        self: "Economy",
        ctx: Context,
        *,
        member: Union[discord.Member, discord.User] = commands.Author,
    ):
        """
        Check a member's balance
        """

        result = await self.bot.db.fetchrow(
            "SELECT * FROM economy WHERE user_id = $1", member.id
        )

        if not result:
            return await ctx.alert("This member doesn't have an account open")

        monthly = "Available"
        daily = "Available"

        if result.monthly:
            if result.monthly > discord.utils.utcnow():
                monthly = discord.utils.format_dt(result.monthly, style="R")

        if result.daily:
            if result.daily > discord.utils.utcnow():
                daily = discord.utils.format_dt(result.daily, style="R")

        embed = (
            discord.Embed(title=f"{member.display_name}'s balance")
            .set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
            .add_field(
                name="Value",
                value=f"**Cash**: {result.credits:,}\n**Bank**: {result.bank:,}",
                inline=True,
            )
            .add_field(
                name="Claim", value=f"**Daily**: {daily}\n**Monthly**: {monthly}"
            )
        )

        return await ctx.reply(embed=embed)


async def setup(bot: Scare) -> None:
    return await bot.add_cog(Economy(bot))
