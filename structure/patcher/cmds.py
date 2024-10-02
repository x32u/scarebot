from discord.ext import commands

from structure.managers import Context


def ticket_moderator():
    async def predicate(ctx: Context):
        if not await ctx.bot.db.fetchrow(
            "SELECT * FROM opened_tickets WHERE channel_id = $1", ctx.channel.id
        ):
            await ctx.alert("You can use this command in a ticket only")
            return False

        support = (
            await ctx.bot.db.fetchval(
                "SELECT support FROM tickets WHERE guild_id = $1", ctx.guild.id
            )
            or []
        )

        if (
            not ctx.author.id in support
            and not ctx.author.guild_permissions.administrator
        ):
            await ctx.alert(
                "You must be a **support** or a **server administrator** to use this command"
            )
            return False

        return True

    return commands.check(predicate)


def antinuke_owner():
    async def predicate(ctx: Context):
        if ctx.guild.owner_id == ctx.author.id:
            return True

        if owners := await ctx.bot.db.fetchval(
            "SELECT owners FROM antinuke WHERE guild_id = $1", ctx.guild.id
        ):
            if ctx.author.id in owners:
                return True

        await ctx.alert("You are not an antinuke owner")
        return False

    return commands.check(predicate)


def has_boost_level(level: int):
    async def predicate(ctx: Context):
        if ctx.guild.premium_tier < level:
            await ctx.alert(f"Your server isn't boosted to level `{level}`")

        return ctx.guild.premium_tier >= level

    return commands.check(predicate)


def server_owner():
    async def predicate(ctx: Context):
        own = bool(ctx.guild.owner_id == ctx.author.id)

        if not own:
            await ctx.alert("You have to **own** this server to use this command")

        return own

    return commands.check(predicate)


def is_donator():
    async def predicate(ctx: Context):
        result = await ctx.bot.db.fetchrow(
            "SELECT * FROM donator WHERE user_id = $1", ctx.author.id
        )

        if not result and not ctx.author.id in ctx.bot.owner_ids:
            raise commands.BadArgument(
                "This command is for donators only! Please join our [**support server**](https://discord.gg/juno) for more information"
            )

        return True

    return commands.check(predicate)


def is_booster():
    async def predicate(ctx: Context):
        if not ctx.author.premium_since:
            await ctx.alert(
                f"You need to **boost** this server to use **{ctx.command.qualified_name}**"
            )

        return ctx.author.premium_since

    return commands.check(predicate)


def has_permissions(**perms: bool):
    async def predicate(ctx: Context):
        if ctx.author.guild_permissions.administrator:
            return True

        p = [x for x, y in perms.items() if y]

        if any((getattr(ctx.author.guild_permissions, m) for m in p)):
            return True

        roles = ", ".join(map(lambda g: str(g.id), ctx.author.roles[1:]))

        if not roles:
            raise commands.MissingPermissions(perms)

        results = await ctx.bot.db.fetch(
            f"SELECT permissions FROM fakeperms WHERE guild_id = $1 AND role_id IN ({roles})",
            ctx.guild.id,
        )

        flattened = list(
            set(ctx.bot.flatten(list(map(lambda r: r.permissions, results))))
        )
        if any((g in flattened for g in p)):
            return True

        raise commands.MissingPermissions(perms)

    return commands.check(predicate)


def blacktea_round():
    async def predicate(ctx: Context):
        if ctx.bot.blacktea_matches.get(ctx.guild.id):
            await ctx.alert("There's a match of blacktea in progress")

        return not ctx.guild.id in ctx.bot.blacktea_matches.keys()

    return commands.check(predicate)


commands.blacktea_round = blacktea_round
commands.has_permissions = has_permissions
commands.server_owner = server_owner
commands.antinuke_owner = antinuke_owner
commands.has_boost_level = has_boost_level
commands.is_donator = is_donator
commands.is_booster = is_booster
commands.ticket_moderator = ticket_moderator
