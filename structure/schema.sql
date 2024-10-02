CREATE SCHEMA IF NOT EXISTS lastfm;
CREATE SCHEMA IF NOT EXISTS tracker; 
CREATE SCHEMA IF NOT EXISTS boosterrole; 
CREATE SCHEMA IF NOT EXISTS notifications;

CREATE TABLE IF NOT EXISTS notifications.youtube (
    youtuber TEXT, 
    last_stream TEXT,
    channel_ids BIGINT[],
    PRIMARY KEY (youtuber)
);

CREATE TABLE IF NOT EXISTS boosterrole.config (
    guild_id BIGINT NOT NULL,
    base BIGINT,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS boosterrole.roles (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS tracker.vanity (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL, 
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS tracker.username (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL, 
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS lastfm.user (
    user_id BIGINT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    embed TEXT,
    command TEXT,
    reactions JSONB[] NOT NULL DEFAULT ARRAY[]::JSONB[],
    friends BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[]
);

CREATE TABLE IF NOT EXISTS lastfm.crowns (
    artist TEXT NOT NULL, 
    user_id BIGINT NOT NULL, 
    PRIMARY KEY (artist)
);

CREATE TABLE IF NOT EXISTS afk (
    user_id BIGINT NOT NULL, 
    guild_id BIGINT NOT NULL, 
    reason TEXT NOT NULL,
    since TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS avatarhistory (
    user_id BIGINT NOT NULL,
    avatars TEXT[] NOT NULL, 
    PRIMARY KEY(user_id)
);

CREATE TABLE IF NOT EXISTS autoresponder (
    guild_id BIGINT NOT NULL,
    trigger TEXT NOT NULL, 
    response TEXT NOT NULL, 
    strict BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (guild_id, trigger)
);

CREATE TABLE IF NOT EXISTS authorize (
    guild_id BIGINT NOT NULL,
    owner_id BIGINT NOT NULL,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS antispam (
    guild_id BIGINT NOT NULL, 
    duration INTEGER NOT NULL, 
    whitelisted BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS autorole (
    guild_id BIGINT NOT NULL, 
    roles BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS blacklist (
    target_id BIGINT NOT NULL,
    target_type TEXT NOT NULL,
    author_id BIGINT NOT NULL,
    since TEXT NOT NULL 
);

 CREATE TABLE IF NOT EXISTS globalban (
    user_id BIGINT NOT NULL, 
    reason TEXT
);

CREATE TABLE IF NOT EXISTS prefix (
    guild_id BIGINT NOT NULL,
    prefix TEXT NOT NULL,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS antinuke (
    guild_id BIGINT NOT NULL,
    modules JSON NOT NULL DEFAULT '{}'::JSON,
    owners BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    whitelisted BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    logs BIGINT, 
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS moderation (
    guild_id BIGINT UNIQUE NOT NULL,
    role_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    jail_id BIGINT NOT NULL,
    category_id BIGINT NOT NULL,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS jail (
    guild_id BIGINT NOT NULL, 
    user_id BIGINT NOT NULL,
    roles BIGINT[] NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS cases (
    guild_id BIGINT NOT NULL,
    count INT NOT NULL,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS warns (
    user_id BIGINT NOT NULL, 
    guild_id BIGINT NOT NULL, 
    reason TEXT NOT NULL,
    date TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS topcmds (
    name TEXT NOT NULL, 
    count INTEGER NOT NULL,
    PRIMARY KEY (name)
);

CREATE TABLE IF NOT EXISTS disabledcmds (
    guild_id BIGINT NOT NULL, 
    command_name TEXT NOT NULL,
    PRIMARY KEY (guild_id, command_name)
);

CREATE TABLE IF NOT EXISTS gnames (
    guild_id BIGINT NOT NULL, 
    gname TEXT NOT NULL,
    since TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS names (
    user_id BIGINT NOT NULL, 
    username TEXT NOT NULL,
    since TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS welcome (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS goodbye (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS boost (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS bumpreminder (
    guild_id BIGINT NOT NULL, 
    channel_id BIGINT, 
    bumper_id BIGINT,
    bump_next TIMESTAMPTZ,
    thank TEXT NOT NULL DEFAULT '{title: Thank you for bumping!}{description: You can bump again **in 2 hours**}',
    remind TEXT NOT NULL DEFAULT '{title: Time to bump!}{description: Please use the `/bump` command on **Disboard** to bump this server}{content: {user.mention}}',
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS voicemaster (
    guild_id BIGINT NOT NULL, 
    channel_id BIGINT NOT NULL, 
    voice_channels JSON NOT NULL DEFAULT '{}'::JSON, 
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS whitelist (
    guild_id BIGINT NOT NULL,
    whitelisted BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    msg TEXT,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS fakeperms (
    guild_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    permissions TEXT[] NOT NULL,
    PRIMARY KEY(guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS aliases (
    guild_id BIGINT NOT NULL, 
    alias TEXT NOT NULL, 
    command TEXT NOT NULL, 
    PRIMARY KEY (guild_id, alias)
);

CREATE TABLE IF NOT EXISTS economy (
    user_id BIGINT NOT NULL, 
    credits INTEGER NOT NULL, 
    bank INTEGER NOT NULL,
    daily TIMESTAMPTZ,
    monthly TIMESTAMPTZ,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS joindm (
    guild_id BIGINT NOT NULL, 
    message TEXT NOT NULL,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS logs (
    guild_id BIGINT,
    log_type TEXT,
    channel_id BIGINT,
    PRIMARY KEY (guild_id, log_type)
);

CREATE TABLE IF NOT EXISTS reminders (
    user_id BIGINT NOT NULL, 
    reminder TEXT NOT NULL, 
    remind_at TIMESTAMPTZ NOT NULL,
    invoked_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS birthday (
    user_id BIGINT NOT NULL,
    birthdate TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS timezone (
    user_id BIGINT NOT NULL,
    tz TEXT NOT NULL,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS skullboard (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT,
    emoji TEXT,
    count INTEGER, 
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS skullboard_message (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL, 
    message_id BIGINT NOT NULL, 
    panel_message_id BIGINT NOT NULL, 
    PRIMARY KEY (guild_id, channel_id, message_id)
);

CREATE TABLE IF NOT EXISTS forcenick (
    guild_id BIGINT NOT NULL, 
    user_id BIGINT NOT NULL, 
    nickname TEXT NOT NULL, 
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS reskin (
    user_id BIGINT NOT NULL, 
    username TEXT,
    avatar_url TEXT, 
    color INTEGER,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS donator (
    user_id BIGINT NOT NULL,
    reason TEXT NOT NULL,
    since TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS server_settings (
    guild_id BIGINT NOT NULL,
    heximage BOOLEAN NOT NULL DEFAULT FALSE, 
    voicetranscript BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    guild_id BIGINT NOT NULL, 
    category_id BIGINT, 
    logs_id BIGINT,
    support BIGINT[],
    topics JSONB[] NOT NULL DEFAULT ARRAY[]::JSONB[],
    open_message TEXT NOT NULL DEFAULT '{content: Hey {user.mention}} {color: #2b2d31} {title: Ticket - {topic}} {description: Please state your problem in this channel and support will get to you shortly!} {author: {guild.name} && {guild.icon}}',
    panel_message TEXT NOT NULL DEFAULT '{title: Open a ticket} {color: #2b2d31} {description: Please use the button below to open a ticket} {footer: scare.life} {author: {guild.name} && {guild.icon}}',
    PRIMARY KEY(guild_id)
);

CREATE TABLE IF NOT EXISTS opened_tickets (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL, 
    channel_id BIGINT NOT NULL, 
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS reactionroles (
    message_id BIGINT NOT NULL, 
    emoji TEXT NOT NULL,
    guild_id BIGINT NOT NULL, 
    channel_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    PRIMARY KEY (message_id, emoji)
);

CREATE TABLE IF NOT EXISTS giveaway (
    guild_id BIGINT NOT NULL, 
    channel_id BIGINT NOT NULL, 
    message_id BIGINT NOT NULL, 
    members BIGINT[],
    reward TEXT NOT NULL, 
    winners INTEGER NOT NULL,
    ending TIMESTAMPTZ NOT NULL,
    ended BOOLEAN
);

CREATE TABLE IF NOT EXISTS role_restore (
    guild_id BIGINT NOT NULL, 
    user_id BIGINT NOT NULL, 
    roles BIGINT[] NOT NULL, 
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS sticky_message (
    guild_id BIGINT NOT NULL, 
    channel_id BIGINT NOT NULL, 
    message_id BIGINT NOT NULL, 
    message TEXT NOT NULL, 
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS autoreact (
    guild_id BIGINT NOT NULL, 
    trigger TEXT NOT NULL, 
    strict BOOLEAN NOT NULL,
    reactions TEXT[] NOT NULL, 
    PRIMARY KEY (guild_id, trigger)
);

CREATE TABLE IF NOT EXISTS instances (
    token TEXT NOT NULL, 
    owner_id BIGINT NOT NULL, 
    color INTEGER,
    dbname TEXT NOT NULL,
    status TEXT,
    activity TEXT,
    PRIMARY KEY (token)
);