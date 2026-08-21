"""PG 连接与 SQLite 只读连接。"""
import os
import sqlite3
import psycopg2

def get_pg_conn():
    return psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "stock"),
        password=os.getenv("PG_PASSWORD", ""),
        dbname=os.getenv("PG_DB", "stock_warehouse"),
    )

def ro_sqlite(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
