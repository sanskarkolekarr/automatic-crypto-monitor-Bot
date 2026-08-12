import os
import sqlite3

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "wallets.db")


def _connect():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # safer concurrent reads
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
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO wallets (user_id, username, name, chain, address) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, name, chain.lower(), address.strip()),
        )
        conn.commit()
    finally:
        conn.close()


def get_wallets_by_user(user_id):
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_wallets_by_username(username):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM wallets WHERE lower(username) = lower(?)", (username,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_wallets():
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM wallets ORDER BY username").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def remove_wallet(user_id, chain):
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM wallets WHERE user_id = ? AND lower(chain) = ?",
            (user_id, chain.lower()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def remove_all_wallets(user_id):
    conn = _connect()
    try:
        conn.execute("DELETE FROM wallets WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def add_allowed_user(user_id, username):
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO allowed_users (user_id, username) VALUES (?, ?)",
            (user_id, username),
        )
        conn.commit()
    finally:
        conn.close()


def remove_allowed_user(user_id):
    conn = _connect()
    try:
        conn.execute("DELETE FROM allowed_users WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def user_allowed(user_id):
    conn = _connect()
    try:
        row = conn.execute("SELECT 1 FROM allowed_users WHERE user_id = ?", (user_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


def get_allowed_users():
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM allowed_users ORDER BY username").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
