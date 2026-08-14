import logging
import os
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for

import db
from extensions import csrf, limiter
from helpers import fmt_date, fmt_deadline, usd
from shop import now_iso
from views.admin import admin as admin_bp
from views.public import main as main_bp

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set. Add it to .env (a random hex string).")
app.config["SECRET_KEY"] = SECRET_KEY
app.config["DATABASE"] = os.path.join(app.root_path, "pizza.db")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Secure defaults OFF so local HTTP testing keeps working; set
    # SESSION_COOKIE_SECURE=1 (or true) in the deployment .env to require HTTPS.
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "").lower()
    in ("1", "true", "yes"),
)
csrf.init_app(app)
limiter.init_app(app)
db.init_app(app)

app.register_blueprint(main_bp)
app.register_blueprint(admin_bp)

app.jinja_env.filters["usd"] = usd
app.jinja_env.filters["fmt_date"] = fmt_date
app.jinja_env.filters["fmt_deadline"] = fmt_deadline


def configure_logging(app):
    """Send app logs to a rotating file (logs/pushin-pizza.log) as well as the
    console, so errors persist across restarts and after the terminal closes.
    Level is INFO by default; override with LOG_LEVEL=DEBUG/WARNING/etc. in .env.
    Unhandled exceptions (HTTP 500s) are logged here automatically by Flask.
    """
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    app.logger.setLevel(level)  # accessing app.logger wires up Flask's console handler

    # Guard against adding a second file handler (e.g. under the debug reloader).
    if any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        return

    logs_dir = os.path.join(app.root_path, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(logs_dir, "pushin-pizza.log"),
        maxBytes=1_000_000,  # ~1 MB per file
        backupCount=5,       # keep 5 rotated files
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    file_handler.setLevel(level)
    app.logger.addHandler(file_handler)
    app.logger.info("Logging started (level=%s)", logging.getLevelName(level))


configure_logging(app)


def close_passed_events():
    """Close pickup events whose order deadline has passed.

    This function is intended to be scheduled to run once a day.  It finds all
    pickup events that are still ``open`` and whose ``order_deadline`` is in the
    past (in the shop's local time — see ``now_iso``) and sets their status to
    ``closed``.  The function needs an application context to access the
    database, so we explicitly push one here.
    """
    with app.app_context():
        conn = db.get_db()
        try:
            cur = conn.execute(
                "UPDATE pickup_events SET status = 'closed' WHERE status = 'open' AND order_deadline <= ?",
                (now_iso(),),
            )
            conn.commit()
            app.logger.info("Closed %d pickup events whose deadline passed.", cur.rowcount)
        except Exception as exc:  # pragma: no cover - defensive but unlikely to hit
            app.logger.error("Failed to close pickup events: %s", exc)


# Skip the scheduler in debug mode: the reloader runs two processes, which would
# double-schedule the job (and the deadline checks in current_event/order paths
# cover dev anyway).
if os.environ.get("FLASK_DEBUG", "").lower() not in ("1", "true", "yes"):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        close_passed_events,
        trigger="interval",
        days=1,
        next_run_time=datetime.now(timezone.utc),  # first run immediately, then daily
        name="close_passed_events_job",
    )
    scheduler.start()
    app.logger.info("Scheduled daily 'close_passed_events' job; first run is immediate.")


@limiter.request_filter
def _exempt_static():
    # CSS/JS load on every page view — don't count them against the limits.
    return (request.endpoint or "") == "static"


@app.after_request
def set_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "base-uri 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    # HSTS only over HTTPS (browsers ignore it on HTTP; gating avoids surprises).
    if request.is_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # L2: don't advertise exact Werkzeug/Python versions.
    resp.headers["Server"] = "pushin-pizza"
    return resp


@app.errorhandler(429)
def ratelimit_handler(e):
    # The order form posts, so a flash + redirect is friendlier than an error page.
    if request.endpoint == "main.place_order":
        flash("You're placing orders very quickly — please wait a moment and try again.", "error")
        return redirect(url_for("main.index"))
    return (
        render_template(
            "error.html",
            title="Slow down a moment",
            message="You've made a lot of requests in a short time. Please wait a minute and try again.",
        ),
        429,
    )


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug)
