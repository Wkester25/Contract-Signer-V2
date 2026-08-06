"""
PostgreSQL storage for signed-contract hash records.

All connection parameters are configurable (see config.py) - either as a
single DATABASE_URL, or as individual POSTGRES_* values. Schema/table name
are configurable too; identifiers are built with psycopg2.sql.Identifier,
which quotes them safely, so any valid Postgres identifier works without
risking SQL injection through config - the query values themselves (account
number, hash, etc.) always go through parameterized placeholders, never
string interpolation.
"""
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2 import sql

from config import Config

log = logging.getLogger("program2.db")


class DatabaseError(Exception):
    """Raised when the hash record can't be read/written to Postgres."""


def _connect():
    try:
        if Config.DATABASE_URL:
            return psycopg2.connect(
                Config.DATABASE_URL,
                connect_timeout=Config.POSTGRES_CONNECT_TIMEOUT_SECONDS,
                application_name=Config.POSTGRES_APPLICATION_NAME,
            )
        return psycopg2.connect(
            host=Config.POSTGRES_HOST,
            port=Config.POSTGRES_PORT,
            dbname=Config.POSTGRES_DB,
            user=Config.POSTGRES_USER,
            password=Config.POSTGRES_PASSWORD,
            sslmode=Config.POSTGRES_SSLMODE,
            connect_timeout=Config.POSTGRES_CONNECT_TIMEOUT_SECONDS,
            application_name=Config.POSTGRES_APPLICATION_NAME,
        )
    except psycopg2.OperationalError as exc:
        raise DatabaseError(f"Could not connect to Postgres: {exc}") from exc


@contextmanager
def get_connection():
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def _table_identifier() -> sql.Composable:
    return sql.Identifier(Config.POSTGRES_SCHEMA, Config.POSTGRES_TABLE)


def ensure_schema(conn) -> None:
    """Create the table and its indexes if they don't already exist. Safe
    to call on every startup."""
    table = _table_identifier()

    create_table = sql.SQL(
        """
        CREATE TABLE IF NOT EXISTS {table} (
            id BIGSERIAL PRIMARY KEY,
            account_number TEXT NOT NULL,
            file_path TEXT NOT NULL,
            sha256_hash CHAR(64) NOT NULL,
            captured_at TIMESTAMPTZ,
            saved_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    ).format(table=table)

    create_account_index = sql.SQL("CREATE INDEX IF NOT EXISTS {name} ON {table} (account_number)").format(
        name=sql.Identifier(f"{Config.POSTGRES_TABLE}_account_number_idx"), table=table
    )
    create_hash_index = sql.SQL("CREATE INDEX IF NOT EXISTS {name} ON {table} (sha256_hash)").format(
        name=sql.Identifier(f"{Config.POSTGRES_TABLE}_sha256_hash_idx"), table=table
    )

    try:
        with conn.cursor() as cur:
            cur.execute(create_table)
            cur.execute(create_account_index)
            cur.execute(create_hash_index)
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        raise DatabaseError(f"Could not ensure schema: {exc}") from exc


def insert_contract_record(
    conn,
    account_number: str,
    file_path: str,
    sha256_hash: str,
    captured_at: Optional[datetime],
    saved_at: datetime,
) -> int:
    """Inserts one row, returns its id."""
    table = _table_identifier()
    insert = sql.SQL(
        """
        INSERT INTO {table} (account_number, file_path, sha256_hash, captured_at, saved_at)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """
    ).format(table=table)

    try:
        with conn.cursor() as cur:
            cur.execute(insert, (account_number, file_path, sha256_hash, captured_at, saved_at))
            row_id = cur.fetchone()[0]
        conn.commit()
        return row_id
    except psycopg2.Error as exc:
        conn.rollback()
        raise DatabaseError(f"Could not insert contract record: {exc}") from exc
