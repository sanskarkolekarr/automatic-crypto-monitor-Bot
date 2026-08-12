import os
import sqlite3

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "wallets.db")


def _connect():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            name TEXT,
            chain TEXT NOT NULL,
            address TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, chain, address)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS allowed_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    conn.commit()
    return conn


def add_wallet(user_id, username, name, chain, address):
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO wallets (user_id, username, name, chain, address) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, name, chain.lower(), address.strip()),
        )


def get_wallets_by_user(user_id):
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchall()
        return [dict(r) for r in rows]


def get_wallets_by_username(username):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM wallets WHERE lower(username) = lower(?)", (username,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_wallets():
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM wallets ORDER BY username").fetchall()
        return [dict(r) for r in rows]


def remove_wallet(user_id, chain):
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM wallets WHERE user_id = ? AND lower(chain) = ?",
            (user_id, chain.lower()),
        )
        return cur.rowcount > 0


def remove_all_wallets(user_id):
    with _connect() as conn:
        conn.execute("DELETE FROM wallets WHERE user_id = ?", (user_id,))


def add_allowed_user(user_id, username):
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO allowed_users (user_id, username) VALUES (?, ?)",
            (user_id, username),
        )


def remove_allowed_user(user_id):
    with _connect() as conn:
        conn.execute("DELETE FROM allowed_users WHERE user_id = ?", (user_id,))


def user_allowed(user_id):
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM allowed_users WHERE user_id = ?", (user_id,)).fetchone()
        return row is not None


def get_allowed_users():
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM allowed_users ORDER BY username").fetchall()
        return [dict(r) for r in rows]
