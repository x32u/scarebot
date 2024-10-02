import discord
from discord.ext.commands import Bot, Cog
from nacl.signing import VerifyKey
from quart import Quart, abort, jsonify, redirect, render_template, request


class Web(Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.app = Quart(__name__)
        self.app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

        for module in dir(self):
            route = getattr(self, module)
            if not hasattr(route, "pattern"):
                continue

            self.app.route(route.pattern, methods=[route.method])(route)

        @self.app.errorhandler(404)
        async def not_found_error(error):
            return await render_template(
                "error.html", code=404, message="The requested URL was not found"
            )

        @self.app.errorhandler(405)
        async def not_found_error(error):
            return await render_template(
                "error.html", code=405, message="A wrong request method was used"
            )

        @self.app.errorhandler(500)
        async def not_found_error(error):
            return await render_template(
                "error.html", code=500, message="An issue occured on our webserver"
            )

        @self.app.route("/", methods=["GET"])
        async def root():
            return await render_template(
                "index.html",
                guilds=f"{len(self.bot.guilds):,}",
                members=f"{len(self.bot.users):,}",
                avatar=self.bot.user.display_avatar.url,
            )

        @self.app.route("/commands", methods=["GET"])
        async def bot_commands():
            commands = {
                c: {
                    "count": len(set(cmds.walk_commands())),
                    "commands": [
                        {"name": cmd.qualified_name, "description": cmd.help}
                        for cmd in sorted(
                            set(cmds.walk_commands()), key=lambda r: r.qualified_name
                        )
                    ],
                }
                for c, cmds in self.bot.cogs.items()
                if not c in ["Jishaku", "Web", "Developer"]
                and len(set(cmds.walk_commands())) > 0
            }

            return await render_template(
                "commands.html",
                commands=commands,
                all=len(set(self.bot.walk_commands())),
                avatar=self.bot.user.display_avatar.url,
            )

        @self.app.route("/giveaways/<int:guild_id>")
        async def giveaways(guild_id: int):
            if guild := self.bot.get_guild(guild_id):
                if giveaways := await self.bot.db.fetch(
                    """
                    SELECT * FROM giveaway
                    WHERE guild_id = $1
                    AND NOT ended
                    ORDER BY ending ASC
                    """,
                    guild_id,
                ):
                    return await render_template(
                        "giveaway.html",
                        avatar=self.bot.user.display_avatar.url,
                        guild=str(guild),
                        giveaways=[
                            {
                                "title": result.reward,
                                "winners": result.winners,
                                "entries": len(result.members),
                                "date": result.ending.strftime("%Y-%m-%d %H:%M:%S"),
                            }
                            for result in giveaways
                        ],
                    )
                else:
                    message = "There are no giveaways in this server"
            else:
                message = "Server not found"

            return await render_template("error.html", code=404, message=message)

        @self.app.route("/avatars/<int:user_id>")
        async def avatars(user_id: int):
            if user := self.bot.get_user(user_id):
                if avatars := await self.bot.db.fetchval(
                    "SELECT avatars FROM avatarhistory WHERE user_id = $1", user_id
                ):
                    return await render_template(
                        "avatars.html",
                        id=user_id,
                        display_name=user.display_name,
                        avatars=avatars[::-1],
                    )
                else:
                    message = "The user's avatars were not found"
            else:
                message = "The user was not found"

            return await render_template("error.html", code=404, message=message)

        @self.app.route("/discord", methods=["GET"])
        async def discord_server():
            return redirect("https://discord.gg/scarebot")

        @self.app.route("/invite", methods=["GET"])
        async def discord_invite():
            return redirect(self.bot.invite_url)

        @self.app.route("/terms", methods=["GET"])
        async def terms():
            return await render_template(
                "terms.html", avatar=self.bot.user.display_avatar.url
            )

        @self.app.route("/privacy", methods=["GET"])
        async def privacy():
            return await render_template(
                "privacy.html", avatar=self.bot.user.display_avatar.url
            )

        @self.app.route("/embeds", methods=["GET"])
        async def embeds():
            return await render_template(
                "embed.html", avatar=self.bot.user.display_avatar.url
            )

        @self.app.route("/status", methods=["GET"])
        async def status():
            latencies = {
                "operational": "background-color: rgb(4, 175, 4);",
                "partial outage": "background-color: rgb(211, 226, 13);",
                "outage": "background-color: rgb(227, 10, 10);",
            }

            latency = round(self.bot.latency * 1000)

            def period():
                delta = discord.utils.utcnow() - self.bot.uptime
                d = {"d": delta.days}
                d["h"], rem = divmod(delta.seconds, 3600)
                d["m"], d["s"] = divmod(rem, 60)
                return " ".join(f"{v}{k}" for k, v in d.items() if v != 0)

            uptime = period()
            servers = f"{len(self.bot.guilds):,}"
            users = f"{len(self.bot.users):,}"
            status = (
                "operational"
                if latency < 35
                else "partial outage" if latency < 60 else "outage"
            )

            return await render_template(
                "status.html",
                latency=f"{latency}ms",
                uptime=uptime,
                servers=servers,
                users=users,
                status=status,
                color=latencies.get(status),
                icon=self.bot.user.display_avatar.url,
            )

        @self.app.route("/ip", methods=["GET"])
        async def address():
            ip = request.headers.get("Cf-Connecting-Ip", "Unknown")
            print(ip)
            return ip

        @self.app.route("/interactions", methods=["POST"])
        async def bot_interactions():
            public_key = (
                "7c8f8eaa1b7593a4be1c583100a81c0e9c03b32b2f29a0def7cd159c70eaff43"
            )
            verify_key = VerifyKey(bytes.fromhex(public_key))

            signature = request.headers["X-Signature-Ed25519"]
            timestamp = request.headers["X-Signature-Timestamp"]
            body = (await request.data).decode("utf-8")

            try:
                verify_key.verify(
                    f"{timestamp}{body}".encode(), bytes.fromhex(signature)
                )
                if (await request.json)["type"] == 1:
                    return jsonify({"type": 1})
            except:
                abort(401, "Invalid request signature")

    async def cog_load(self):
        self.bot.loop.create_task(
            self.app.run_task(
                host="0.0.0.0",
                port=1337,
            ),
        )

    async def cog_unload(self):
        await self.app.shutdown()


async def setup(bot):
    await bot.add_cog(Web(bot))
