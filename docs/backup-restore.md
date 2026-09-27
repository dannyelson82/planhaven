# Backup and restore

Planhaven keeps your data in two places inside the container, and both need backing up:

| What | Where (container) | Backed up by |
|---|---|---|
| Database: projects, tasks, accounts | `/config/pgdata` | Planhaven, nightly, into `/config/backups` |
| Keys (master key, session key) | `/config/secrets` | **You**: copy this folder somewhere safe once |
| Attachments (from phase 0.2) | `/data` | Your usual Unraid backup |

**Why the keys matter:** authenticator-app secrets and other stored secrets are encrypted with
the master key in `/config/secrets` (SECURITY.md §7.9). A database backup restored without the
matching keys still works, but everyone has to set up their second factor again.

## Automatic database backups

- Every night at 03:00 (the container's `TZ`), Planhaven writes
  `/config/backups/planhaven-<date>-<time>.dump`.
- It keeps the 7 newest backups, plus the newest from each of the last 4 weeks.
- The files are readable only by the database user inside the container. On Unraid they are in
  your appdata folder (e.g. `/mnt/user/appdata/planhaven/backups`), which your normal appdata
  backup (e.g. the Appdata Backup plugin) will copy too.
- To make a backup right now: `docker exec planhaven /etc/s6-overlay/scripts/backup-now`

## Restoring a backup

This replaces the current database with the backup. Anything changed since then is lost.

1. Put the backup file in the container's `/config/backups` folder, if it isn't already there.
2. Run (replace the file name):
   `docker exec planhaven /etc/s6-overlay/scripts/restore-db /config/backups/planhaven-20261001-030000.dump`
   Planhaven pauses the app, restores, and starts it again. It prints "restore complete" when
   done.
3. If you're restoring onto a new server, also copy your saved `/config/secrets` folder back
   before starting the container.

The round trip (backup → fresh container → restore → data present) is tested automatically on
every change.
