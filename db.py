"""Small PyMySQL connection helpers. Connections are scoped to one Flask request."""
from contextlib import contextmanager
from flask import current_app, g
import pymysql
from pymysql.cursors import DictCursor


class DatabaseUnavailable(RuntimeError):
    """Raised when the local MySQL server or credentials cannot be reached."""


def get_db():
    if "db" not in g:
        cfg = dict(current_app.config["DB_CONFIG"])
        cfg["cursorclass"] = DictCursor
        try:
            g.db = pymysql.connect(**cfg)
        except pymysql.MySQLError as exc:
            raise DatabaseUnavailable(str(exc)) from exc
    return g.db


def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)


def one(sql, params=()):
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def all_rows(sql, params=()):
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def execute(sql, params=()):
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return cur.lastrowid, cur.rowcount


@contextmanager
def transaction():
    conn = get_db()
    conn.begin()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
