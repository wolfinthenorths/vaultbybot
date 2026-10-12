"""Durable SQLite storage and consistent, rotating online backups."""

import fcntl
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def resolve_database_path(environ=None):
    env = os.environ if environ is None else environ
    mount = env.get("RAILWAY_VOLUME_MOUNT_PATH")
    if env.get("RAILWAY_ENVIRONMENT_ID") and not mount:
        raise RuntimeError("Attach a Railway volume before starting VaultByBot")
    root = Path(mount).resolve() if mount else Path(__file__).resolve().parent
    if mount and not root.is_dir():
        raise RuntimeError("The persistent volume is not mounted")
    path = Path(env.get("DB_PATH") or root / "support_messages.db").resolve()
    if mount and not path.is_relative_to(root):
        raise RuntimeError("DB_PATH must be inside the persistent volume")
    return path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path, support_chat_id, legacy_path=None):
        self.path = Path(path).resolve()
        self.support_chat_id = support_chat_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir = self.path.parent / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        self.marker = self.path.with_suffix(".initialized")
        self._mutex = threading.RLock()
        self._process_lock = open(str(self.path) + ".lock", "a")
        try:
            fcntl.flock(self._process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._process_lock.close()
            raise RuntimeError("Another VaultByBot process already uses this database")
        try:
            if not self.path.exists() and legacy_path:
                legacy = Path(legacy_path).resolve()
                if legacy != self.path and legacy.is_file():
                    self._copy_database(legacy, self.path)
                    logging.info("Migrated the existing SQLite database to persistent storage")
            self._recover_if_needed()
            existed = self.path.exists()
            self.conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.execute("PRAGMA busy_timeout=30000")
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS message_routes (
                    support_chat_id INTEGER NOT NULL,
                    support_message_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (support_chat_id, support_message_id)
                );
                CREATE TABLE IF NOT EXISTS first_reply_sent (
                    user_id INTEGER PRIMARY KEY, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS blocked_users (
                    user_id INTEGER PRIMARY KEY, user_info TEXT, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INTEGER PRIMARY KEY, user_info TEXT, updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS incoming_deliveries (
                    user_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                    support_message_id INTEGER NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, message_id)
                );
            """)
            if self.support_chat_id and self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_map'"
            ).fetchone():
                self.conn.execute("""
                    INSERT OR IGNORE INTO message_routes
                    SELECT ?, support_message_id, user_id, COALESCE(created_at, ?)
                    FROM message_map
                """, (self.support_chat_id, utc_now()))
            self.conn.commit()
            self.marker.touch()
            logging.info("SQLite opened (%s): %s", "existing" if existed else "new", self.path)
        except Exception:
            if hasattr(self, "conn"):
                self.conn.close()
            self._process_lock.close()
            raise

    @staticmethod
    def _valid_database(path):
        try:
            conn = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
            try:
                return (conn.execute("PRAGMA quick_check").fetchone() == ("ok",)
                        and bool(conn.execute("""
                            SELECT 1 FROM sqlite_master WHERE type='table'
                            AND name IN ('message_map', 'message_routes')
                        """).fetchone()))
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return False

    @staticmethod
    def _copy_database(source, destination):
        temp = Path(str(destination) + ".tmp")
        src = sqlite3.connect(Path(source).as_uri() + "?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(temp)
            try:
                src.backup(dst)
                dst.commit()
            finally:
                dst.close()
            os.replace(temp, destination)
        finally:
            src.close()
            temp.unlink(missing_ok=True)

    def _recover_if_needed(self):
        if self.path.exists() and self._valid_database(self.path):
            return
        backups = sorted(self.backup_dir.glob("support-*.db"), reverse=True)
        source = next((p for p in backups if self._valid_database(p)), None)
        if source:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            for suffix in ("", "-wal", "-shm"):
                damaged = Path(str(self.path) + suffix)
                if damaged.exists():
                    damaged.rename(str(damaged) + ".damaged-" + stamp)
            self._copy_database(source, self.path)
            logging.error("Restored the database from backup %s; preserved damaged files", source.name)
        elif self.path.exists() or self.marker.exists():
            raise RuntimeError("Database missing or damaged and no valid backup is available")

    def execute(self, sql, params=()):
        with self._mutex, self.conn:
            self.conn.execute(sql, params)

    def fetchone(self, sql, params=()):
        with self._mutex:
            return self.conn.execute(sql, params).fetchone()

    def save_message_map(self, message_id, user_id, chat_id=None):
        self.execute("""
            INSERT OR REPLACE INTO message_routes VALUES (?, ?, ?, ?)
        """, (chat_id if chat_id is not None else self.support_chat_id,
              message_id, user_id, utc_now()))

    def get_user_id(self, message_id, chat_id=None):
        row = self.fetchone("""
            SELECT user_id FROM message_routes
            WHERE support_chat_id=? AND support_message_id=?
        """, (chat_id if chat_id is not None else self.support_chat_id, message_id))
        return row[0] if row else None

    def save_user_profile(self, user_id, user_info):
        self.execute("INSERT OR REPLACE INTO user_profiles VALUES (?, ?, ?)",
                     (user_id, user_info, utc_now()))

    def get_user_info(self, user_id):
        row = self.fetchone("SELECT user_info FROM user_profiles WHERE user_id=?", (user_id,))
        return row[0] if row else f"ID пользователя: {user_id}"

    def first_reply_sent(self, user_id):
        return bool(self.fetchone("SELECT 1 FROM first_reply_sent WHERE user_id=?", (user_id,)))

    def mark_first_reply_sent(self, user_id):
        self.execute("INSERT OR IGNORE INTO first_reply_sent VALUES (?, ?)", (user_id, utc_now()))

    def is_blocked(self, user_id):
        return bool(self.fetchone("SELECT 1 FROM blocked_users WHERE user_id=?", (user_id,)))

    def block(self, user_id):
        self.execute("INSERT OR REPLACE INTO blocked_users VALUES (?, ?, ?)",
                     (user_id, self.get_user_info(user_id), utc_now()))

    def unblock(self, user_id):
        self.execute("DELETE FROM blocked_users WHERE user_id=?", (user_id,))

    def blocked_users(self):
        with self._mutex:
            return self.conn.execute("""
                SELECT user_id, user_info, created_at FROM blocked_users
                ORDER BY created_at DESC
            """).fetchall()

    def incoming_delivered(self, user_id, message_id):
        return bool(self.fetchone("""
            SELECT 1 FROM incoming_deliveries WHERE user_id=? AND message_id=?
        """, (user_id, message_id)))

    def mark_incoming_delivered(self, user_id, message_id, support_message_id):
        self.execute("INSERT OR REPLACE INTO incoming_deliveries VALUES (?, ?, ?, ?)",
                     (user_id, message_id, support_message_id, utc_now()))

    def backup(self, keep=28):
        with self._mutex:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            target = self.backup_dir / f"support-{stamp}.db"
            temp = target.with_suffix(".tmp")
            dst = sqlite3.connect(temp)
            try:
                self.conn.backup(dst)
                dst.commit()
                if dst.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise RuntimeError("Backup integrity check failed")
            finally:
                dst.close()
            os.replace(temp, target)
            for old in sorted(self.backup_dir.glob("support-*.db"), reverse=True)[keep:]:
                old.unlink()
            logging.info("Database backup created: %s", target.name)
            return target

    def stats(self):
        with self._mutex:
            return {table: self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("message_routes", "user_profiles", "blocked_users", "first_reply_sent")}

    def close(self):
        with self._mutex:
            self.conn.close()
            self._process_lock.close()
