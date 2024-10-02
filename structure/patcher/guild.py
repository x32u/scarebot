import discord


def has_antinuke_permissions(self: "discord.Guild") -> bool:
    return all(
        [
            self.me.guild_permissions.kick_members,
            self.me.guild_permissions.ban_members,
            self.me.guild_permissions.manage_roles,
        ]
    )


discord.Guild.has_antinuke_permissions = has_antinuke_permissions
