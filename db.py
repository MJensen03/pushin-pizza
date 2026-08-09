import sqlite3

import click
from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def query_one(sql, args=()):
    rows = get_db().execute(sql, args).fetchmany(1)
    return rows[0] if rows else None


def execute(sql, args=()):
    """Run a write statement and commit. Returns the last inserted row id."""
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


@click.command("init-db")
def init_db_command():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))
    click.echo("Initialized the database.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
