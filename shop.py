"""Shop domain helpers shared by the view modules and the scheduled job.

Kept out of app.py so views can import them without a circular import, and out
of helpers.py, which holds framework/display utilities with no database access.
"""

import os
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import db

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O, 1/I/L

# All deadlines/timestamps are naive shop-local wall-clock strings
# ('YYYY-MM-DDTHH:MM'), matching the admin's datetime-local input and what's
# stored in SQLite. Set BUSINESS_TZ (an IANA name, e.g. America/Chicago) in .env
# when the server clock isn't the shop's timezone — e.g. a cloud host on UTC.
_BUSINESS_TZ_NAME = os.environ.get("BUSINESS_TZ")
BUSINESS_TZ = ZoneInfo(_BUSINESS_TZ_NAME) if _BUSINESS_TZ_NAME else None


def now_iso():
    return datetime.now(BUSINESS_TZ).replace(tzinfo=None).isoformat(timespec="minutes")


def new_order_code(conn):
    while True:
        code = "PZ-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
        if conn.execute("SELECT 1 FROM orders WHERE public_code = ?", (code,)).fetchone() is None:
            return code


def current_event():
    """The soonest open pickup event whose order deadline hasn't passed."""
    return db.query_one(
        "SELECT * FROM pickup_events WHERE status = 'open' AND order_deadline > ? "
        "ORDER BY pickup_date, order_deadline LIMIT 1",
        (now_iso(),),
    )


def event_menu(event_id):
    return db.query(
        "SELECT items.* FROM items JOIN event_items ON items.id = event_items.item_id "
        "WHERE event_items.event_id = ? AND items.active = 1 "
        "ORDER BY items.sort_order, items.name",
        (event_id,),
    )
