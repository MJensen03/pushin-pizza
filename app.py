import os
import secrets
from datetime import date, datetime

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for

import db
import emailer
from helpers import admin_required, fmt_date, fmt_deadline, parse_cents, usd

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["DATABASE"] = os.path.join(app.root_path, "pizza.db")
db.init_app(app)

app.jinja_env.filters["usd"] = usd
app.jinja_env.filters["fmt_date"] = fmt_date
app.jinja_env.filters["fmt_deadline"] = fmt_deadline

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O, 1/I/L


def now_iso():
    return datetime.now().isoformat(timespec="minutes")


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


# ---------------------------------------------------------------- customer


@app.route("/")
def index():
    event = current_event()
    menu = event_menu(event["id"]) if event else []
    return render_template("index.html", event=event, menu=menu)


@app.route("/order", methods=["POST"])
def place_order():
    event_id = request.form.get("event_id", type=int)
    event = db.query_one("SELECT * FROM pickup_events WHERE id = ?", (event_id,))
    if event is None or event["status"] != "open" or event["order_deadline"] <= now_iso():
        flash("Sorry, ordering for that pickup day has closed.", "error")
        return redirect(url_for("index"))

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    notes = request.form.get("notes", "").strip()
    if not name or not email or not phone:
        flash("Please fill in your name, email, and phone number.", "error")
        return redirect(url_for("index"))
    if "@" not in email or "." not in email.split("@")[-1]:
        flash("That email address doesn't look right.", "error")
        return redirect(url_for("index"))

    lines = []
    for item in event_menu(event_id):
        qty = request.form.get(f"qty_{item['id']}", type=int) or 0
        if qty > 0:
            lines.append({"item": item, "quantity": min(qty, 50)})
    if not lines:
        flash("Please choose at least one pizza before ordering.", "error")
        return redirect(url_for("index"))

    total_cents = sum(l["item"]["price_cents"] * l["quantity"] for l in lines)

    conn = db.get_db()
    customer = db.query_one("SELECT * FROM customers WHERE email = ?", (email,))
    if customer:
        conn.execute(
            "UPDATE customers SET name = ?, phone = ? WHERE id = ?",
            (name, phone, customer["id"]),
        )
        customer_id = customer["id"]
    else:
        customer_id = conn.execute(
            "INSERT INTO customers (name, email, phone) VALUES (?, ?, ?)",
            (name, email, phone),
        ).lastrowid

    code = new_order_code(conn)
    order_id = conn.execute(
        "INSERT INTO orders (public_code, event_id, customer_id, created_at, notes, total_cents) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (code, event_id, customer_id, now_iso(), notes, total_cents),
    ).lastrowid
    for l in lines:
        conn.execute(
            "INSERT INTO order_items (order_id, item_id, quantity, unit_price_cents) "
            "VALUES (?, ?, ?, ?)",
            (order_id, l["item"]["id"], l["quantity"], l["item"]["price_cents"]),
        )
    conn.commit()

    email_lines = [
        {"name": l["item"]["name"], "quantity": l["quantity"], "unit_price_cents": l["item"]["price_cents"]}
        for l in lines
    ]
    emailer.send_order_emails(
        code,
        {"name": name, "email": email, "phone": phone},
        event,
        email_lines,
        total_cents,
        notes,
    )
    return redirect(url_for("confirmation", code=code))


@app.route("/confirmation/<code>")
def confirmation(code):
    order = db.query_one("SELECT * FROM orders WHERE public_code = ?", (code.upper(),))
    if order is None:
        flash("We couldn't find that order.", "error")
        return redirect(url_for("index"))
    event = db.query_one("SELECT * FROM pickup_events WHERE id = ?", (order["event_id"],))
    customer = db.query_one("SELECT * FROM customers WHERE id = ?", (order["customer_id"],))
    lines = db.query(
        "SELECT items.name, order_items.quantity, order_items.unit_price_cents "
        "FROM order_items JOIN items ON items.id = order_items.item_id "
        "WHERE order_items.order_id = ? ORDER BY items.name",
        (order["id"],),
    )
    return render_template(
        "confirm.html", order=order, event=event, customer=customer, lines=lines
    )


# ---------------------------------------------------------------- admin auth


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = os.environ.get("ADMIN_PASSWORD")
        if password and secrets.compare_digest(request.form.get("password", ""), password):
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Wrong password.", "error")
    return render_template("admin/login.html")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------- admin items


@app.route("/admin/items")
@admin_required
def admin_items():
    items = db.query("SELECT * FROM items ORDER BY active DESC, sort_order, name")
    return render_template("admin/items.html", items=items)


@app.route("/admin/items/add", methods=["POST"])
@admin_required
def admin_items_add():
    name = request.form.get("name", "").strip()
    price_cents = parse_cents(request.form.get("price", ""))
    if not name or price_cents is None:
        flash("An item needs a name and a valid price.", "error")
    else:
        db.execute(
            "INSERT INTO items (name, description, price_cents, sort_order) VALUES (?, ?, ?, ?)",
            (
                name,
                request.form.get("description", "").strip(),
                price_cents,
                request.form.get("sort_order", type=int) or 0,
            ),
        )
        flash(f"Added “{name}”.")
    return redirect(url_for("admin_items"))


@app.route("/admin/items/<int:item_id>/edit", methods=["POST"])
@admin_required
def admin_items_edit(item_id):
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
    return redirect(url_for("admin_items"))


@app.route("/admin/items/<int:item_id>/toggle", methods=["POST"])
@admin_required
def admin_items_toggle(item_id):
    db.execute("UPDATE items SET active = 1 - active WHERE id = ?", (item_id,))
    return redirect(url_for("admin_items"))


# ---------------------------------------------------------------- admin events


@app.route("/admin/events")
@admin_required
def admin_events():
    events = db.query("SELECT * FROM pickup_events ORDER BY pickup_date DESC")
    items = db.query("SELECT * FROM items WHERE active = 1 ORDER BY sort_order, name")
    attached = {}
    for row in db.query("SELECT event_id, item_id FROM event_items"):
        attached.setdefault(row["event_id"], set()).add(row["item_id"])
    return render_template(
        "admin/events.html", events=events, items=items, attached=attached, today=date.today().isoformat()
    )


@app.route("/admin/events/add", methods=["POST"])
@admin_required
def admin_events_add():
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
    return redirect(url_for("admin_events"))


@app.route("/admin/events/<int:event_id>/items", methods=["POST"])
@admin_required
def admin_events_items(event_id):
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
    return redirect(url_for("admin_events"))


@app.route("/admin/events/<int:event_id>/toggle", methods=["POST"])
@admin_required
def admin_events_toggle(event_id):
    db.execute(
        "UPDATE pickup_events SET status = CASE status WHEN 'open' THEN 'closed' ELSE 'open' END "
        "WHERE id = ?",
        (event_id,),
    )
    return redirect(url_for("admin_events"))


# ---------------------------------------------------------------- admin dashboard


@app.route("/admin/")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    events = db.query("SELECT * FROM pickup_events ORDER BY pickup_date DESC LIMIT 10")
    boards = []
    for event in events:
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


@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_required
def admin_order_status(order_id):
    status = request.form.get("status")
    if status in ("new", "picked_up", "canceled"):
        db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
