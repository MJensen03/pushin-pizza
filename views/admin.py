"""Admin routes: login, menu items, pickup events, and the order dashboard.

Every URL here is under /admin (see url_prefix below), and every endpoint name
is prefixed with the blueprint name, so url_for("admin.items") builds /admin/items.
"""

import os
import secrets
import time
from datetime import date

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import db
from helpers import parse_cents, usd, wants_json

admin = Blueprint("admin", __name__, url_prefix="/admin")

# In-memory admin-login throttle. State is per-process and resets on restart —
# acceptable for the current single-worker deployment; a shared store (or
# Flask-Limiter) would be needed for multi-worker/production.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 300  # 5 minutes
_login_failures = {}   # ip -> (failure_count, window_start_ts)
_login_lockouts = {}   # ip -> locked_until_ts

# Reachable without an admin session: the login form itself, and logging out
# (which should work even if the session has already gone).
PUBLIC_ENDPOINTS = {"admin.login", "admin.logout"}


@admin.before_request
def require_admin():
    """Guards every route in this blueprint, replacing a per-route decorator."""
    if request.endpoint in PUBLIC_ENDPOINTS or session.get("is_admin"):
        return None
    # A redirect to the login page is HTML; fetch() callers need JSON.
    if wants_json():
        return jsonify(success=False, error="Your admin session expired."), 401
    return redirect(url_for("admin.login"))


# ---------------------------------------------------------------- auth


@admin.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        now = time.time()
        if now < _login_lockouts.get(ip, 0):
            current_app.logger.warning("Admin login attempt from %s while locked out", ip)
            flash("Too many failed attempts. Try again in a few minutes.", "error")
            return render_template("admin/login.html"), 429

        password = os.environ.get("ADMIN_PASSWORD")
        if password and secrets.compare_digest(request.form.get("password", ""), password):
            _login_failures.pop(ip, None)
            _login_lockouts.pop(ip, None)
            session["is_admin"] = True
            current_app.logger.info("Admin logged in from %s", ip)
            return redirect(url_for("admin.dashboard"))

        count, start = _login_failures.get(ip, (0, now))
        if now - start > LOGIN_LOCKOUT_SECONDS:
            count, start = 0, now
        count += 1
        _login_failures[ip] = (count, start)
        if count >= LOGIN_MAX_FAILURES:
            _login_lockouts[ip] = now + LOGIN_LOCKOUT_SECONDS
            _login_failures.pop(ip, None)
            current_app.logger.warning(
                "Admin login locked out for %s after %d failed attempts", ip, LOGIN_MAX_FAILURES
            )
        else:
            current_app.logger.warning("Failed admin login from %s (attempt %d)", ip, count)
        flash("Wrong password.", "error")
    return render_template("admin/login.html")


@admin.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("main.index"))


# ---------------------------------------------------------------- items


@admin.route("/items")
def items():
    rows = db.query("SELECT * FROM items ORDER BY active DESC, sort_order, name")
    return render_template("admin/items.html", items=rows)


@admin.route("/items/add", methods=["POST"])
def items_add():
    """Add a menu item.

    Answers JSON for fetch() callers (the shared _items.html form, used on both
    the Menu and Pickups pages) and falls back to flash + redirect for a plain
    form post so the page still works without JavaScript.
    """
    name = request.form.get("name", "").strip()
    price_cents = parse_cents(request.form.get("price", ""))
    if not name or price_cents is None:
        error = "An item needs a name and a valid price."
        if wants_json():
            return jsonify(success=False, error=error), 400
        flash(error, "error")
        return redirect(url_for("admin.items"))

    description = request.form.get("description", "").strip()
    sort_order = request.form.get("sort_order", type=int) or 0
    item_id = db.execute(
        "INSERT INTO items (name, description, price_cents, sort_order) VALUES (?, ?, ?, ?)",
        (name, description, price_cents, sort_order),
    )
    if wants_json():
        return jsonify(
            success=True,
            item={
                "id": item_id,
                "name": name,
                "description": description,
                "price_cents": price_cents,
                "price": usd(price_cents),
                "sort_order": sort_order,
                "active": 1,
            },
        ), 201
    flash(f"Added “{name}”.")
    return redirect(url_for("admin.items"))


@admin.route("/items/<int:item_id>/edit", methods=["POST"])
def items_edit(item_id):
    name = request.form.get("name", "").strip()
    price_cents = parse_cents(request.form.get("price", ""))
    if not name or price_cents is None:
        flash("An item needs a name and a valid price.", "error")
    else:
        db.execute(
            "UPDATE items SET name = ?, description = ?, price_cents = ?, sort_order = ? "
            "WHERE id = ?",
            (
                name,
                request.form.get("description", "").strip(),
                price_cents,
                request.form.get("sort_order", type=int) or 0,
                item_id,
            ),
        )
        flash(f"Updated “{name}”.")
    return redirect(url_for("admin.items"))


@admin.route("/items/<int:item_id>/toggle", methods=["POST"])
def items_toggle(item_id):
    db.execute("UPDATE items SET active = 1 - active WHERE id = ?", (item_id,))
    return redirect(url_for("admin.items"))


# ---------------------------------------------------------------- events


@admin.route("/events")
def events():
    rows = db.query("SELECT * FROM pickup_events ORDER BY pickup_date DESC")
    items_rows = db.query("SELECT * FROM items WHERE active = 1 ORDER BY sort_order, name")
    attached = {}
    for row in db.query("SELECT event_id, item_id FROM event_items"):
        attached.setdefault(row["event_id"], set()).add(row["item_id"])
    return render_template(
        "admin/events.html",
        events=rows,
        items=items_rows,
        attached=attached,
        today=date.today().isoformat(),
    )


@admin.route("/events/add", methods=["POST"])
def events_add():
    title = request.form.get("title", "").strip()
    pickup_date = request.form.get("pickup_date", "")
    location = request.form.get("location", "").strip()
    deadline = request.form.get("order_deadline", "")
    item_ids = request.form.getlist("item_ids", type=int)
    if not title or not pickup_date or not location or not deadline:
        flash("Events need a title, pickup date, location, and order deadline.", "error")
    elif not item_ids:
        flash("Pick at least one menu item for the event.", "error")
    elif deadline > pickup_date + "T23:59":
        flash("The order deadline must be before the pickup date ends.", "error")
    else:
        conn = db.get_db()
        event_id = conn.execute(
            "INSERT INTO pickup_events (title, pickup_date, pickup_window, location, order_deadline) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, pickup_date, request.form.get("pickup_window", "").strip(), location, deadline),
        ).lastrowid
        for item_id in item_ids:
            conn.execute(
                "INSERT INTO event_items (event_id, item_id) VALUES (?, ?)", (event_id, item_id)
            )
        conn.commit()
        flash(f"Created “{title}”.")
    return redirect(url_for("admin.events"))


@admin.route("/events/<int:event_id>/items", methods=["POST"])
def events_items(event_id):
    item_ids = request.form.getlist("item_ids", type=int)
    if not item_ids:
        flash("An event needs at least one menu item.", "error")
    else:
        conn = db.get_db()
        conn.execute("DELETE FROM event_items WHERE event_id = ?", (event_id,))
        for item_id in item_ids:
            conn.execute(
                "INSERT INTO event_items (event_id, item_id) VALUES (?, ?)", (event_id, item_id)
            )
        conn.commit()
        flash("Updated the event's menu.")
    return redirect(url_for("admin.events"))


@admin.route("/events/<int:event_id>/toggle", methods=["POST"])
def events_toggle(event_id):
    db.execute(
        "UPDATE pickup_events SET status = CASE status WHEN 'open' THEN 'closed' ELSE 'open' END "
        "WHERE id = ?",
        (event_id,),
    )
    return redirect(url_for("admin.events"))


# ---------------------------------------------------------------- dashboard


@admin.route("/")
@admin.route("/dashboard")
def dashboard():
    rows = db.query("SELECT * FROM pickup_events ORDER BY pickup_date DESC LIMIT 10")
    boards = []
    for event in rows:
        summary = db.query(
            "SELECT items.name, SUM(order_items.quantity) AS qty "
            "FROM order_items "
            "JOIN orders ON orders.id = order_items.order_id "
            "JOIN items ON items.id = order_items.item_id "
            "WHERE orders.event_id = ? AND orders.status != 'canceled' "
            "GROUP BY items.id ORDER BY items.name",
            (event["id"],),
        )
        orders = db.query(
            "SELECT orders.*, customers.name AS customer_name, customers.email, customers.phone "
            "FROM orders JOIN customers ON customers.id = orders.customer_id "
            "WHERE orders.event_id = ? ORDER BY orders.created_at DESC",
            (event["id"],),
        )
        order_lines = {
            o["id"]: db.query(
                "SELECT items.name, order_items.quantity, order_items.unit_price_cents "
                "FROM order_items JOIN items ON items.id = order_items.item_id "
                "WHERE order_items.order_id = ? ORDER BY items.name",
                (o["id"],),
            )
            for o in orders
        }
        revenue = sum(o["total_cents"] for o in orders if o["status"] != "canceled")
        boards.append(
            {"event": event, "summary": summary, "orders": orders, "lines": order_lines, "revenue": revenue}
        )
    return render_template("admin/dashboard.html", boards=boards)


@admin.route("/orders/<int:order_id>/status", methods=["POST"])
def order_status(order_id):
    status = request.form.get("status")
    if status in ("new", "picked_up", "canceled"):
        db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    return redirect(url_for("admin.dashboard"))
