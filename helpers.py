from datetime import datetime
from functools import wraps

from flask import jsonify, redirect, request, session, url_for


def wants_json():
    """True when the caller is our fetch() code rather than a plain form post."""
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            # A redirect to the login page is HTML; fetch() callers need JSON.
            if wants_json():
                return jsonify(success=False, error="Your admin session expired."), 401
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped


def usd(cents):
    return f"${cents / 100:,.2f}"


def parse_cents(text):
    """Parse a price like '12', '12.5', or '$12.50' into integer cents. None if invalid."""
    try:
        value = round(float(text.strip().lstrip("$")) * 100)
    except (ValueError, AttributeError):
        return None
    return value if value >= 0 else None


def fmt_date(iso_date):
    """'2026-08-22' -> 'Saturday, August 22'"""
    dt = datetime.fromisoformat(iso_date)
    return f"{dt.strftime('%A, %B')} {dt.day}"


def fmt_deadline(iso_dt):
    """'2026-08-19T21:00' -> 'Wed, Aug 19 at 9:00 PM'"""
    dt = datetime.fromisoformat(iso_dt)
    time = dt.strftime("%I:%M %p").lstrip("0")
    return f"{dt.strftime('%a, %b')} {dt.day} at {time}"
