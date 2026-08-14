"""Customer-facing routes: the menu page, placing an order, and confirmation."""

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

import db
import emailer
from extensions import limiter
from helpers import usd
from shop import current_event, event_menu, new_order_code, now_iso

main = Blueprint("main", __name__)


@main.route("/")
def index():
    event = current_event()
    menu = event_menu(event["id"]) if event else []
    return render_template("index.html", event=event, menu=menu)


@main.route("/order", methods=["POST"])
@limiter.limit("5 per minute; 30 per hour")
def place_order():
    event_id = request.form.get("event_id", type=int)
    event = db.query_one("SELECT * FROM pickup_events WHERE id = ?", (event_id,))
    if event is None or event["status"] != "open" or event["order_deadline"] <= now_iso():
        flash("Sorry, ordering for that pickup day has closed.", "error")
        return redirect(url_for("main.index"))

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    notes = request.form.get("notes", "").strip()
    if not name or not email or not phone:
        flash("Please fill in your name, email, and phone number.", "error")
        return redirect(url_for("main.index"))
    if "@" not in email or "." not in email.split("@")[-1]:
        flash("That email address doesn't look right.", "error")
        return redirect(url_for("main.index"))

    lines = []
    for item in event_menu(event_id):
        qty = request.form.get(f"qty_{item['id']}", type=int) or 0
        if qty > 0:
            lines.append({"item": item, "quantity": min(qty, 50)})
    if not lines:
        flash("Please choose at least one pizza before ordering.", "error")
        return redirect(url_for("main.index"))

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
    current_app.logger.info(
        "Order %s created: %d line item(s), total %s, customer %s",
        code, len(lines), usd(total_cents), email,
    )

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
    return redirect(url_for("main.confirmation", code=code))


@main.route("/confirmation/<code>")
@limiter.limit("60 per hour")
def confirmation(code):
    order = db.query_one("SELECT * FROM orders WHERE public_code = ?", (code.upper(),))
    if order is None:
        flash("We couldn't find that order.", "error")
        return redirect(url_for("main.index"))
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
