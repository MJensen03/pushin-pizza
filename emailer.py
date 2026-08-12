"""Order confirmation emails via the Brevo API.

If BREVO_API_KEY is not set, emails are skipped (logged) so the site
works fine without email configured. Email failures never fail an order.
"""

import os

import requests
from flask import current_app
from markupsafe import escape

from helpers import fmt_date, usd

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def _send(to_email, to_name, subject, html):
    api_key = os.environ.get("BREVO_API_KEY")
    if not api_key:
        current_app.logger.info("BREVO_API_KEY not set; skipping email to %s", to_email)
        return
    payload = {
        "sender": {
            "name": os.environ.get("FROM_NAME", "Pushin' Pizza"),
            "email": os.environ.get("FROM_EMAIL", ""),
        },
        "to": [{"email": to_email, "name": to_name}],
        "subject": subject,
        "htmlContent": html,
    }
    try:
        resp = requests.post(
            BREVO_URL,
            json=payload,
            headers={"api-key": api_key, "content-type": "application/json"},
            timeout=10,
        )
        if resp.status_code >= 400:
            current_app.logger.error(
                "Email to %s failed: %s %s", to_email, resp.status_code, resp.text
            )
        else:
            # NOTE: a 2xx only means Brevo *accepted* the request. Invalid-sender
            # and other rejections happen asynchronously and are NOT visible here —
            # check Brevo's dashboard (Transactional -> Logs) or the events API for
            # true delivery status. The messageId below is the handle to look it up.
            try:
                message_id = resp.json().get("messageId", "")
            except ValueError:
                message_id = ""
            current_app.logger.info(
                "Email accepted by Brevo for %s (messageId=%s)", to_email, message_id
            )
    except requests.RequestException:
        current_app.logger.exception("Email to %s failed", to_email)


def _lines_html(lines, total_cents):
    rows = "".join(
        f"<tr><td>{l['quantity']}&times; {escape(l['name'])}</td>"
        f"<td align='right'>{usd(l['quantity'] * l['unit_price_cents'])}</td></tr>"
        for l in lines
    )
    return (
        f"<table cellpadding='4'>{rows}"
        f"<tr><td><strong>Total (due at pickup)</strong></td>"
        f"<td align='right'><strong>{usd(total_cents)}</strong></td></tr></table>"
    )


def send_order_emails(order_code, customer, event, lines, total_cents, notes):
    """Send the customer confirmation and the owner notification."""
    pickup = f"{fmt_date(event['pickup_date'])}"
    if event["pickup_window"]:
        pickup += f", {event['pickup_window']}"
    details = (
        f"<p><strong>Order {order_code}</strong></p>"
        + _lines_html(lines, total_cents)
        + f"<p><strong>Pickup:</strong> {pickup}<br>"
        f"<strong>Where:</strong> {escape(event['location'])}</p>"
    )
    if notes:
        details += f"<p><strong>Notes:</strong> {escape(notes)}</p>"

    _send(
        customer["email"],
        customer["name"],
        f"Pushin' Pizza order {order_code} confirmed",
        f"<p>Thanks, {escape(customer['name'])}! Your order is in.</p>"
        + details
        + "<p>Payment is due at pickup (cash, card, or Venmo). See you there!</p>",
    )

    owner_email = os.environ.get("OWNER_EMAIL")
    if owner_email:
        _send(
            owner_email,
            "Pushin' Pizza",
            f"New order {order_code} — {customer['name']} ({usd(total_cents)})",
            f"<p>New order from {escape(customer['name'])} "
            f"({escape(customer['email'])}, {escape(customer['phone'])})</p>" + details,
        )
