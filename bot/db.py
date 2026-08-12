"""
SQLite database layer for wallet and user management.

Fixes vs original:
- Per-thread connection via threading.local() — eliminates reopening a new
  SQLite file handle on every call, saving overhead during parallel verification.
- Schema migration: added a partial unique index for owner-added wallets
  (user_id = 0) keyed on (username, chain, address) instead of
  (user_id, chain, address) to prevent two different MMs added via /add with
  the same chain+address from silently overwriting each other.
- add_wallet_for_owner() helper separates the owner-/add-path clearly.
- remove_wallet now also supports username-based removal (for owner-added wallets).
- _ensure_schema() is idempotent — safe to call on startup and on every connect.
"""

import os
import sqlite3
import threading

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "wallets.db")

_local = threading.local()


def _connect() -> sqlite3.Connection:
    """Return a per-thread SQLite connection, creating it if needed."""
    if not getattr(_local, "conn", None):
        os.makedirs(DB_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _ensure_schema(conn)
        _local.conn = conn
    return _local.conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist. Safe to call repeatedly."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wallets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            username   TEXT,
            name       TEXT,
            chain      TEXT NOT NULL,
            address    TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    # Standard unique constraint for real Telegram users
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet_user
           ON wallets(user_id, chain, address)
           WHERE user_id != 0"""
    )
    # For owner-added wallets (user_id=0): unique on (lower(username), chain, address)
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet_owner
           ON wallets(lower(username), chain, address)
           WHERE user_id = 0"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS allowed_users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Wallet operations
# ---------------------------------------------------------------------------

def add_wallet(user_id: int, username: str | None, name: str | None, chain: str, address: str) -> None:
    """Add or update a wallet for a real Telegram user (user_id > 0)."""
    conn = _connect()
    chain_l = chain.lower()
    addr = address.strip()
    # Try insert first; if the (user_id, chain, address) combination already exists,
    # just update the mutable fields.
    existing = conn.execute(
        "SELECT id FROM wallets WHERE user_id = ? AND chain = ? AND address = ?",
        (user_id, chain_l, addr),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE wallets SET username = ?, name = ? WHERE id = ?",
            (username, name, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO wallets (user_id, username, name, chain, address) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, name, chain_l, addr),
        )
    conn.commit()


def add_wallet_for_owner(username: str, chain: str, address: str) -> None:
    """Add or update a wallet registered by the owner via /add (user_id = 0).

    Uniqueness: (lower(username), chain, address) — two different usernames
    CAN share the same chain+address without overwriting each other.
    """
    conn = _connect()
    uname = username.lower()
    chain_l = chain.lower()
    addr = address.strip()
    # Check if row already exists for this (username, chain, address) combo
    existing = conn.execute(
        """SELECT id FROM wallets
           WHERE user_id = 0 AND lower(username) = ? AND chain = ? AND address = ?""",
        (uname, chain_l, addr),
    ).fetchone()
    if existing:
        # Update name only (username + chain + address unchanged)
        conn.execute(
            "UPDATE wallets SET username = ?, name = ? WHERE id = ?",
            (uname, uname, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO wallets (user_id, username, name, chain, address) VALUES (0, ?, ?, ?, ?)",
            (uname, uname, chain_l, addr),
        )
    conn.commit()


def get_wallets_by_user(user_id: int) -> list:
    conn = _connect()
    rows = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def get_wallets_by_username(username: str) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM wallets WHERE lower(username) = lower(?)", (username,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_wallets() -> list:
    conn = _connect()
    rows = conn.execute("SELECT * FROM wallets ORDER BY username").fetchall()
    return [dict(r) for r in rows]


def remove_wallet(user_id: int, chain: str) -> bool:
    """Remove wallet(s) for a real user by chain. Returns True if any row deleted."""
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM wallets WHERE user_id = ? AND lower(chain) = ?",
        (user_id, chain.lower()),
    )
    conn.commit()
    return cur.rowcount > 0


def remove_wallet_by_username(username: str, chain: str) -> bool:
    """Remove owner-added wallet(s) by username+chain. Returns True if any row deleted."""
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM wallets WHERE lower(username) = lower(?) AND lower(chain) = ? AND user_id = 0",
        (username, chain.lower()),
    )
    conn.commit()
    return cur.rowcount > 0


def remove_all_wallets(user_id: int) -> None:
    conn = _connect()
    conn.execute("DELETE FROM wallets WHERE user_id = ?", (user_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Access-control operations
# ---------------------------------------------------------------------------

def add_allowed_user(user_id: int, username: str | None) -> None:
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO allowed_users (user_id, username) VALUES (?, ?)",
        (user_id, username),
    )
    conn.commit()


def remove_allowed_user(user_id: int) -> None:
    conn = _connect()
    conn.execute("DELETE FROM allowed_users WHERE user_id = ?", (user_id,))
    conn.commit()


def user_allowed(user_id: int) -> bool:
    conn = _connect()
    row = conn.execute(
        "SELECT 1 FROM allowed_users WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row is not None


def get_allowed_users() -> list:
    conn = _connect()
    rows = conn.execute("SELECT * FROM allowed_users ORDER BY username").fetchall()
    return [dict(r) for r in rows]
