# VaultByBot

Telegram support and information bot for Dawn of the Dead.

## Running

Install `requirements.txt` and run `python bot.py`. Required variables:

- `BOT_TOKEN`: Telegram bot token. Never commit it.
- `SUPPORT_CHAT_ID`: private administration group's numeric chat ID.
- `DB_PATH` (optional): database file path, inside the mounted volume on Railway.

On Railway, attach a volume at `/data`. The bot uses
`RAILWAY_VOLUME_MOUNT_PATH/support_messages.db` and refuses to run without a
volume. Keep one replica. An exclusive database lock also prevents two bot
processes from using the same volume. The process checks database integrity at
startup, preserves existing data during schema migration, and never replaces a
missing or damaged established database with an empty one.

An existing database alongside the script is migrated if the destination does
not yet exist. Historical data already removed from an ephemeral Railway
container cannot be recovered by attaching a new volume.

## Backups and recovery

Consistent SQLite backups run every six hours and on startup/shutdown, with up
to 28 snapshots retained in `/data/backups`. These snapshots survive redeploys,
but share the volume: they do not protect against deletion of the entire
volume. For an independent copy, use `/backupdb` in the admin group and save the
returned file separately. Railway's native volume backup schedules can also
be enabled in the dashboard.

If the database is missing or damaged, the bot restores the newest valid local
snapshot and logs the snapshot name. Damaged database files are preserved for
investigation. Data written after that snapshot may be absent. Without a valid
snapshot, startup fails instead of quietly creating an empty established base.

## Administration

Each incoming message is one card, including author and action buttons. Long
text/captions are kept in full; when adding an author header would exceed a
Telegram limit, author information is on the keyboard instead. Manual replies
and template responses update the source card's delivery status, without
duplicating the response in the group. Errors remain visible.

- Reply to a card with text or a supported attachment to answer its author.
- `/reply ID text`: answer a specific Telegram user ID.
- `/block` or `/unblock`: reply to a card, or append a user ID.
- `/blocked`: complete blocked-user list.
- `/recover`: reply to an old bot card with an ID to rebuild its route.
  Routes are also recovered automatically when replying or pressing its buttons.
- `/dbstats`: storage and record counts.
- `/backupdb`: download a consistent database snapshot (admin group only).

Old cards with neither a saved route nor embedded recipient ID cannot be
matched automatically. Use their original author card or `/reply ID text`.

## Checks

`python -m unittest discover -s tests -v`

Tests use a synthetic bot token and a recording Telegram session. They do not
send messages or poll the real bot.
