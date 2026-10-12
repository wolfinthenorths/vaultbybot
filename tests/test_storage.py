import sqlite3
import tempfile
import unittest
from pathlib import Path

from storage import Database, resolve_database_path


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "support.db"
        self.db = Database(self.path, -1001)
        self.addCleanup(lambda: self.db.close() if self.db else None)

    def reopen(self):
        self.db.close()
        self.db = None
        self.db = Database(self.path, -1001)

    def test_all_user_data_survives_restart(self):
        self.db.save_user_profile(42, "A user's profile")
        self.db.save_message_map(8, 42)
        self.db.block(42)
        self.db.mark_first_reply_sent(42)
        self.db.mark_incoming_delivered(42, 9, 8)
        self.reopen()
        self.assertEqual(self.db.get_user_id(8), 42)
        self.assertEqual(self.db.get_user_info(42), "A user's profile")
        self.assertTrue(self.db.is_blocked(42))
        self.assertTrue(self.db.first_reply_sent(42))
        self.assertTrue(self.db.incoming_delivered(42, 9))

    def test_routes_are_scoped_to_support_chat(self):
        self.db.save_message_map(8, 42, chat_id=-1001)
        self.db.save_message_map(8, 43, chat_id=-1002)
        self.assertEqual(self.db.get_user_id(8, -1001), 42)
        self.assertEqual(self.db.get_user_id(8, -1002), 43)

    def test_consistent_backup_restores_corruption(self):
        self.db.save_message_map(8, 42)
        self.db.save_user_profile(42, "Recovery test")
        self.db.block(42)
        snapshot = self.db.backup()
        self.db.close()
        self.db = None
        self.path.write_bytes(b"broken sqlite database")
        self.db = Database(self.path, -1001)
        self.assertEqual(self.db.get_user_id(8), 42)
        self.assertTrue(self.db.is_blocked(42))
        self.assertTrue(snapshot.exists())
        self.assertEqual(len(list(self.path.parent.glob("*.damaged-*"))), 1)

    def test_missing_database_restores_latest_valid_snapshot(self):
        self.db.save_message_map(8, 42)
        self.db.backup()
        self.db.save_message_map(9, 43)
        self.db.backup()
        self.db.close()
        self.db = None
        self.path.unlink()
        self.db = Database(self.path, -1001)
        self.assertEqual(self.db.get_user_id(9), 43)

    def test_missing_established_database_fails_without_backup(self):
        self.db.close()
        self.db = None
        self.path.unlink()
        with self.assertRaisesRegex(RuntimeError, "no valid backup"):
            Database(self.path, -1001)
        self.assertFalse(self.path.exists())

    def test_empty_database_fails_instead_of_resetting(self):
        self.db.close()
        self.db = None
        self.path.write_bytes(b"")
        with self.assertRaisesRegex(RuntimeError, "no valid backup"):
            Database(self.path, -1001)

    def test_second_process_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Another VaultByBot"):
            Database(self.path, -1001)

    def test_backup_retention(self):
        for _ in range(4):
            self.db.backup(keep=2)
        self.assertEqual(len(list(self.db.backup_dir.glob("support-*.db"))), 2)

    def test_legacy_schema_and_file_are_migrated_without_losing_records(self):
        self.db.close()
        self.db = None
        self.path.unlink()
        self.path.with_suffix(".initialized").unlink()
        legacy = Path(self.temp.name) / "legacy.db"
        conn = sqlite3.connect(legacy)
        conn.executescript("""
            CREATE TABLE message_map (support_message_id INTEGER PRIMARY KEY,
                                      user_id INTEGER NOT NULL, created_at TEXT);
            INSERT INTO message_map VALUES (8, 42, '2026-10-12');
            CREATE TABLE blocked_users (user_id INTEGER PRIMARY KEY,
                                        user_info TEXT, created_at TEXT);
            INSERT INTO blocked_users VALUES (42, 'Old profile', '2026-10-12');
        """)
        conn.close()
        self.db = Database(self.path, -1001, legacy_path=legacy)
        self.assertEqual(self.db.get_user_id(8), 42)
        self.assertTrue(self.db.is_blocked(42))
        self.assertTrue(legacy.exists())

    def test_existing_target_is_never_replaced_by_legacy(self):
        self.db.save_message_map(8, 42)
        self.db.close()
        self.db = None
        legacy = Path(self.temp.name) / "legacy.db"
        legacy.write_bytes(b"old invalid database")
        self.db = Database(self.path, -1001, legacy_path=legacy)
        self.assertEqual(self.db.get_user_id(8), 42)


class PathTests(unittest.TestCase):
    def test_railway_without_volume_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "Attach a Railway volume"):
            resolve_database_path({"RAILWAY_ENVIRONMENT_ID": "production"})

    def test_database_outside_volume_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "inside the persistent volume"):
                resolve_database_path({"RAILWAY_VOLUME_MOUNT_PATH": directory,
                                       "DB_PATH": "/tmp/outside-volume.db"})

    def test_volume_is_used_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(resolve_database_path({"RAILWAY_VOLUME_MOUNT_PATH": directory}),
                             Path(directory) / "support_messages.db")


if __name__ == "__main__":
    unittest.main()
