import time
from collections import OrderedDict
import json
import os
from sqlite3 import connect, Connection, Cursor

class TTLCache:
    def __init__(self, max_bytes=None, db_path=None):
        self.items = OrderedDict()
        self.max_bytes = max_bytes
        self.bytes = 0

        if db_path is None:
             db_path = os.path.join(
                 os.path.dirname(__file__),
                 "db",
                 "cache.db",
             )

        self.db_path = db_path

        if self.db_path:
            db_directory = os.path.dirname(
                os.path.abspath(self.db_path),
            )
            os.makedirs(db_directory, exist_ok=True)
            self.db_init()

    def get(self, key):
        item = self.items.get(key)

        if item is not None:
            
            if item["expires_at"] < time.time():
                self.delete(key)
                return None
            
            self.items.move_to_end(key)

            return item["value"]

        conn = connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT value, expires_at, bytes
            FROM cache
            WHERE key = ?

        """,(key,)
        )

        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if row is None:
            return None

        value, expires_at, size_bytes = row

        if expires_at < time.time():
            conn = connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""

            DELETE FROM cache WHERE key = ?

            """, (key,))

            conn.commit()
            cursor.close()
            conn.close()

            return None

        value = json.loads(value)

        self.items[key] = {
            "value": value,
            "expires_at": expires_at,
            "bytes": size_bytes,
        }

        self.bytes += size_bytes
        self.items.move_to_end(key)

        return value

        

    def set(self, key, value, ttl, size_bytes=0):
        self.delete(key)

        self.items[key] = {
            "value": value,
            "expires_at": time.time() + ttl,
            "bytes": size_bytes,
        }

        self.bytes += size_bytes

        if self.max_bytes is not None:
            while self.bytes > self.max_bytes:
                oldest_key = next(iter(self.items))

                self.delete(oldest_key)

        if self.db_path:
            self.db_set(
                key,
                json.dumps(value),
                ttl,
                size_bytes,
            )

    def delete(self, key):
        item = self.items.pop(key, None)

        if item is not None:
            self.bytes -= item.get("bytes", 0)

        if self.db_path:
            conn = connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                DELETE FROM cache
                WHERE key = ?
                """,
                (key,),
            )

            conn.commit()
            cursor.close()
            conn.close()

    def clear(self):
        self.items.clear()
        self.bytes = 0

        if self.db_path:
            conn = connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM cache")

            conn.commit()
            cursor.close()
            conn.close()

    def __len__(self):
        return len(self.items)
    
    def db_init(self):
        conn = connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value BLOB NOT NULL,
                expires_at REAL NOT NULL,
                bytes INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        conn.commit()
        cursor.close()
        conn.close()

    def db_set(self, key, value, ttl, size_bytes=0):
        expires_at = time.time() + ttl

        conn = connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO cache (key, value, expires_at, bytes)
            VALUES (?, ?, ?, ?)
            """,
            (key, value, expires_at, size_bytes),
        )
        conn.commit()
        cursor.close()
        conn.close()
