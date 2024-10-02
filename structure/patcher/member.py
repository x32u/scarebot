import discord


def is_dangerous(self: "discord.Member"):
    return any(
        [
            self.guild_permissions.administrator,
            self.guild_permissions.manage_channels,
            self.guild_permissions.manage_roles,
            self.guild_permissions.manage_expressions,
            self.guild_permissions.kick_members,
            self.guild_permissions.ban_members,
            self.guild_permissions.manage_webhooks,
            self.guild_permissions.manage_guild,
        ]
    )


discord.Member.is_dangerous = is_dangerous
discord.Member.is_punishable = (
    lambda self: self.id != self.guild.owner_id
    and self.top_role < self.guild.me.top_role
)
discord.User.url = discord.Member.url = property(
    fget=lambda self: f"https://discord.com/users/{self.id}", doc="The user's url"
)
