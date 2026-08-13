# Pushin' Pizza

Pre-order site for Pushin' Pizza: the admin posts "pickup days" (a pickup
date/time plus an order deadline), customers order by the deadline as guests,
and payment happens at pickup. Flask + SQLite.

## Run it locally

```
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux
source bin activate

flask --app app.py init-db
flask --app app.py run
```

Then open http://localhost:5000. The admin login link is in the page footer;
the password is `ADMIN_PASSWORD` in `.env`. Set `FLASK_DEBUG=1` locally only
if you explicitly need the reloader/debugger (off by default).

## Configuration (`.env`)

| Variable         | Purpose                                        |
|------------------|------------------------------------------------|
| `SECRET_KEY`     | Flask session signing key (random hex)         |
| `ADMIN_PASSWORD` | Password for the admin pages                   |
| `BREVO_API_KEY`  | Optional — enables confirmation emails         |
| `FROM_EMAIL`     | Sender address (must be verified in Brevo)     |
| `FROM_NAME`      | Sender display name                            |
| `OWNER_EMAIL`    | Where new-order notifications are sent         |
| `SESSION_COOKIE_SECURE` | Set to `1` in production (HTTPS) to require the session cookie be sent only over HTTPS |

Without `BREVO_API_KEY`, orders still work — emails are just skipped.
To enable email: create a free account at https://www.brevo.com, verify your
sender address, create an API key (SMTP & API → API Keys), and fill in the
four email variables in `.env`.

## How it works

- `app.py` — all routes (customer ordering + admin pages)
- `db.py` — sqlite3 helpers and the `init-db` CLI command
- `schema.sql` — tables: items, pickup_events, event_items, customers,
  orders, order_items (unit prices are snapshotted onto order lines)
- `emailer.py` — Brevo confirmation emails, failure-tolerant
- `helpers.py` — admin login decorator, money/date formatting

Admin flow: **Menu** (create items with prices) → **Pickups** (create a pickup
day, set the order deadline, choose which items are offered) → **Orders**
(production counts per item, customer contact info, mark picked up).

## Logs

The app writes to **`logs/pushin-pizza.log`** (rotating: ~1 MB per file, 5 kept)
as well as the console. It records order creations, admin logins / lockouts,
email results, and unhandled errors (HTTP 500s with tracebacks). The `logs/`
folder is gitignored. Set `LOG_LEVEL` in `.env` (`DEBUG`, `INFO`, `WARNING`, …)
to change verbosity; the default is `INFO`.

**Email caveat:** a logged "Email accepted by Brevo" means Brevo accepted the
API request, *not* that the message was delivered. Invalid-sender and similar
rejections happen asynchronously — confirm real delivery in Brevo's dashboard
(**Transactional → Logs**). `FROM_EMAIL` must exactly match a verified Brevo
sender or every send is rejected after acceptance.

## Deploying

PythonAnywhere free tier works as-is (persistent disk, so SQLite is fine):
upload the project, create a virtualenv from `requirements.txt`, set the
WSGI entry to `app:app`, add the `.env` values, and run `init-db` once from
a console.
