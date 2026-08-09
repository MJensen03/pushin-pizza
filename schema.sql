CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pickup_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    pickup_date TEXT NOT NULL,        -- 'YYYY-MM-DD'
    pickup_window TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL,
    order_deadline TEXT NOT NULL,     -- 'YYYY-MM-DDTHH:MM'
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed'))
);

CREATE TABLE IF NOT EXISTS event_items (
    event_id INTEGER NOT NULL REFERENCES pickup_events(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    PRIMARY KEY (event_id, item_id)
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_code TEXT NOT NULL UNIQUE, -- short code shown to the customer, e.g. PZ-4F7K2
    event_id INTEGER NOT NULL REFERENCES pickup_events(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'picked_up', 'canceled')),
    notes TEXT NOT NULL DEFAULT '',
    total_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    order_id INTEGER NOT NULL REFERENCES orders(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL, -- price snapshot at order time
    PRIMARY KEY (order_id, item_id)
);
