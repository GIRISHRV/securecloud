from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

from argon2 import PasswordHasher


EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,63}$")
APPLICATION_EVENT_RETENTION_SECONDS = 7 * 24 * 60 * 60
APPLICATION_EVENT_LIMIT = 10_000
SAMPLE_DOMAIN = "sample.northstar.test"
SAMPLE_CUSTOMERS = [
    ("Ananya Rao", "Bengaluru", "Karnataka", "560034"),
    ("Rohan Iyer", "Chennai", "Tamil Nadu", "600020"),
    ("Meera Pillai", "Kochi", "Kerala", "682016"),
    ("Arjun Shetty", "Mangaluru", "Karnataka", "575001"),
    ("Kavya Nair", "Thiruvananthapuram", "Kerala", "695010"),
    ("Vikram Desai", "Pune", "Maharashtra", "411004"),
    ("Sneha Kulkarni", "Mumbai", "Maharashtra", "400050"),
    ("Aditya Menon", "Hyderabad", "Telangana", "500033"),
    ("Priya Sharma", "New Delhi", "Delhi", "110017"),
    ("Karthik Reddy", "Hyderabad", "Telangana", "500081"),
    ("Divya Hegde", "Mysuru", "Karnataka", "570009"),
    ("Nikhil Jain", "Jaipur", "Rajasthan", "302017"),
    ("Ishita Bose", "Kolkata", "West Bengal", "700019"),
    ("Siddharth Gupta", "Ahmedabad", "Gujarat", "380015"),
]
SAMPLE_STREETS = ["MG Road", "Residency Road", "Church Street", "Indiranagar 2nd Stage",
                  "Koramangala 5th Block", "Anna Salai", "Linking Road", "Park Street"]

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS retail_schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS retail_users(
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_digest TEXT NOT NULL, display_name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
 role TEXT NOT NULL CHECK(role IN('customer','owner')), status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS retail_sessions(
 token_digest TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL REFERENCES retail_users(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, last_seen_at REAL NOT NULL,
 revoked_at REAL, client_summary TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS retail_sessions_user_idx ON retail_sessions(user_id,expires_at);
CREATE TABLE IF NOT EXISTS customer_addresses(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES retail_users(id), recipient TEXT NOT NULL,
 line1 TEXT NOT NULL, line2 TEXT NOT NULL, city TEXT NOT NULL, state TEXT NOT NULL,
 postal_code TEXT NOT NULL, phone TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS products(
 id TEXT PRIMARY KEY, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL, description TEXT NOT NULL,
 price_minor INTEGER NOT NULL CHECK(price_minor>=0), currency TEXT NOT NULL DEFAULT 'INR',
 stock_quantity INTEGER NOT NULL CHECK(stock_quantity>=0), published INTEGER NOT NULL DEFAULT 1,
 image_path TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS carts(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES retail_users(id), status TEXT NOT NULL DEFAULT 'active', updated_at REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS carts_active_user_idx ON carts(user_id) WHERE status='active';
CREATE TABLE IF NOT EXISTS cart_items(
 cart_id TEXT NOT NULL REFERENCES carts(id) ON DELETE CASCADE, product_id TEXT NOT NULL REFERENCES products(id),
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 20), unit_price_minor INTEGER NOT NULL,
 PRIMARY KEY(cart_id,product_id));
CREATE TABLE IF NOT EXISTS orders(
 id TEXT PRIMARY KEY, order_number TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL REFERENCES retail_users(id), tenant_id TEXT NOT NULL,
 status TEXT NOT NULL, payment_status TEXT NOT NULL, subtotal_minor INTEGER NOT NULL, total_minor INTEGER NOT NULL,
 currency TEXT NOT NULL, customer_snapshot TEXT NOT NULL, address_snapshot TEXT NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS order_items(
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE, product_id TEXT NOT NULL,
 sku_snapshot TEXT NOT NULL, name_snapshot TEXT NOT NULL, unit_price_minor INTEGER NOT NULL, quantity INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS payments(
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
 provider TEXT NOT NULL, reference TEXT NOT NULL UNIQUE, amount_minor INTEGER NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS retail_idempotency(
 user_id TEXT NOT NULL REFERENCES retail_users(id), idempotency_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 order_id TEXT NOT NULL REFERENCES orders(id), created_at REAL NOT NULL, PRIMARY KEY(user_id,idempotency_key));
CREATE TABLE IF NOT EXISTS application_events(
 id TEXT PRIMARY KEY, occurred_at REAL NOT NULL, request_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
 actor_id TEXT, session_id TEXT, source_workload TEXT NOT NULL, destination_workload TEXT NOT NULL,
 action TEXT NOT NULL, route_template TEXT NOT NULL, result TEXT NOT NULL,
 protocol TEXT NOT NULL DEFAULT 'TCP', destination_port INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS app_event_dedupe_idx ON application_events(request_id,action,result);
"""


class RetailError(ValueError):
    pass


class RetailStore:
    """Transactional local adapter shaped for a later PostgreSQL implementation."""

    def __init__(self, path: Path, *, order_prefix: str = "NS", tenant_id: str = "retailco"):
        self.path = Path(path)
        self.order_prefix, self.tenant_id = order_prefix, tenant_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.hasher = PasswordHasher()
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO retail_schema_migrations VALUES(1,?)", (time.time(),))
            columns = {row[1] for row in db.execute("PRAGMA table_info(application_events)")}
            if "protocol" not in columns:
                db.execute("ALTER TABLE application_events ADD COLUMN protocol TEXT NOT NULL DEFAULT 'TCP'")
            if "destination_port" not in columns:
                db.execute("ALTER TABLE application_events ADD COLUMN destination_port INTEGER")
            db.execute("INSERT OR IGNORE INTO retail_schema_migrations VALUES(2,?)", (time.time(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def normalize_email(email: str) -> str:
        value = email.strip().lower()
        if len(value) > 254 or not EMAIL.fullmatch(value):
            raise RetailError("Enter a valid email address")
        return value

    def create_user(self, email, password, display_name, *, role="customer", phone="", tenant_id="retailco", min_password=14):
        email, display_name = self.normalize_email(email), display_name.strip()
        if not 2 <= len(display_name) <= 100:
            raise RetailError("Display name must be 2-100 characters")
        if not min_password <= len(password) <= 256:
            raise RetailError(f"Password must be {min_password}-256 characters")
        if role not in {"customer", "owner"}:
            raise RetailError("Invalid retail role")
        user_id, now = str(uuid.uuid4()), time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO retail_users VALUES(?,?,?,?,?,?,?,'active',?)",
                (user_id, tenant_id, email, self.hasher.hash(password), display_name, phone.strip(), role, now),
            )
        return self.user(user_id)

    def upsert_lab_account(self, email, password, display_name, *, role):
        """Create or reset a local demo account. Lab seeding only: allows passwords from 8 characters."""
        email = self.normalize_email(email)
        with self.connect() as db:
            row = db.execute("SELECT id FROM retail_users WHERE email=?", (email,)).fetchone()
            if row:
                if not 8 <= len(password) <= 256:
                    raise RetailError("Password must be 8-256 characters")
                db.execute(
                    "UPDATE retail_users SET password_digest=?,display_name=?,role=?,status='active' WHERE id=?",
                    (self.hasher.hash(password), display_name.strip(), role, row["id"]),
                )
                db.execute("UPDATE retail_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (time.time(), row["id"]))
                return self.user(row["id"]), False
        return self.create_user(email, password, display_name, role=role, min_password=8), True

    def user(self, user_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT id,tenant_id,email,display_name,phone,role,status,created_at FROM retail_users WHERE id=?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def authentication_record(self, email):
        try:
            email = self.normalize_email(email)
        except RetailError:
            return None
        with self.connect() as db:
            row = db.execute("SELECT * FROM retail_users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None

    def create_session(self, user_id, seconds, client_summary):
        token, csrf, session_id, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), str(uuid.uuid4()), time.time()
        with self.connect() as db:
            db.execute("DELETE FROM retail_sessions WHERE expires_at<=? OR revoked_at IS NOT NULL", (now,))
            db.execute(
                "INSERT INTO retail_sessions VALUES(?,?,?,?,?,?,?,NULL,?)",
                (sha256(token.encode()).hexdigest(), session_id, user_id, csrf, now, now + seconds, now, client_summary[:160]),
            )
        return token, csrf, session_id

    def resolve_session(self, token):
        digest, now = sha256(token.encode()).hexdigest(), time.time()
        with self.connect() as db:
            row = db.execute(
                """SELECT s.*,u.tenant_id,u.email,u.display_name,u.phone,u.role,u.status
                   FROM retail_sessions s JOIN retail_users u ON u.id=s.user_id
                   WHERE s.token_digest=? AND s.expires_at>? AND s.revoked_at IS NULL AND u.status='active'""",
                (digest, now),
            ).fetchone()
            if row:
                db.execute("UPDATE retail_sessions SET last_seen_at=? WHERE token_digest=?", (now, digest))
        return dict(row) if row else None

    def revoke_session(self, token_digest):
        with self.connect() as db:
            db.execute("UPDATE retail_sessions SET revoked_at=? WHERE token_digest=?", (time.time(), token_digest))

    def seed_catalog(self, rows=None):
        now = time.time()
        rows = rows or [
            ("prod-backpack", "NS-BAG-014", "Everyday Backpack", "Durable backpack with a padded laptop sleeve.", 149900, 32, "/products/backpack.webp"),
            ("prod-bottle", "NS-ACC-031", "Stainless Water Bottle", "Insulated 750 ml stainless-steel bottle.", 65000, 58, "/products/bottle.webp"),
            ("prod-sunglasses", "NS-ACC-008", "Classic Sunglasses", "UV-protected everyday sunglasses.", 70000, 17, "/products/sunglasses.webp"),
            ("prod-lamp", "NS-HOM-022", "Desk Lamp", "Adjustable LED desk lamp.", 99900, 21, "/products/lamp.webp"),
        ]
        with self.connect() as db:
            for row in rows:
                db.execute(
                    """INSERT INTO products(id,sku,name,description,price_minor,currency,stock_quantity,published,image_path,created_at,updated_at)
                       VALUES(?,?,?,?,?,'INR',?,1,?,?,?) ON CONFLICT(id) DO UPDATE SET
                       sku=excluded.sku,name=excluded.name,description=excluded.description,price_minor=excluded.price_minor,
                       stock_quantity=excluded.stock_quantity,published=1,image_path=excluded.image_path,updated_at=excluded.updated_at""",
                    (*row, now, now),
                )
        return self.products(True)

    def seed_sample_history(self, *, days=60, customers=14, seed=29):
        """Create clearly labelled sample customers and backdated orders for dashboards.

        Sample shoppers use the reserved ``sample.northstar.test`` domain and random,
        never-disclosed passwords, so they cannot sign in. This writes business data
        only; it never writes application or security events, because those must come
        from real requests and real network telemetry.
        """
        import random

        rng = random.Random(seed)
        now = time.time()
        with self.connect() as db:
            if db.execute(
                "SELECT 1 FROM retail_users WHERE email LIKE ?", (f"%@{SAMPLE_DOMAIN}",)
            ).fetchone():
                return 0
            products = [dict(x) for x in db.execute("SELECT * FROM products WHERE published=1")]
            if not products:
                return 0
            people = []
            for index, (name, city, state, postal) in enumerate(SAMPLE_CUSTOMERS[:customers]):
                user_id = str(uuid.uuid4())
                email = f"{name.split()[0].lower()}.{index + 1}@{SAMPLE_DOMAIN}"
                phone = f"+91 9{rng.randint(100000000, 999999999)}"
                joined = now - rng.uniform(days + 5, days + 60) * 86400
                db.execute(
                    "INSERT INTO retail_users VALUES(?,?,?,?,?,?,'customer','active',?)",
                    (user_id, "retailco", email, self.hasher.hash(secrets.token_urlsafe(32)), name, phone, joined),
                )
                people.append({"id": user_id, "name": name, "email": email, "phone": phone,
                               "city": city, "state": state, "postal": postal})
            created = 0
            for day in range(days, -1, -1):
                weekday_boost = 1.4 if time.localtime(now - day * 86400).tm_wday in (5, 6) else 1.0
                for _ in range(max(0, round(rng.gauss(2.2 + (days - day) * 0.06, 1.0) * weekday_boost))):
                    created_at = now - day * 86400 - rng.uniform(0, 86400 if day else 6 * 3600)
                    age_days = (now - created_at) / 86400
                    if age_days > 6:
                        status = "cancelled" if rng.random() < 0.07 else "delivered"
                    elif age_days > 3:
                        status = rng.choice(["shipped", "delivered", "delivered"])
                    elif age_days > 1:
                        status = rng.choice(["packing", "shipped"])
                    else:
                        status = rng.choice(["placed", "placed", "processing"])
                    person = rng.choice(people)
                    lines = rng.sample(products, k=min(len(products), rng.choice([1, 1, 1, 2, 2, 3])))
                    items = [(p, rng.choice([1, 1, 1, 2])) for p in lines]
                    subtotal = sum(p["price_minor"] * q for p, q in items)
                    order_id = str(uuid.uuid4())
                    address = {"recipient": person["name"], "line1": f"{rng.randint(4, 220)}, {rng.choice(SAMPLE_STREETS)}",
                               "line2": "", "city": person["city"], "state": person["state"],
                               "postal_code": person["postal"], "phone": person["phone"]}
                    customer = {"id": person["id"], "name": person["name"], "email": person["email"], "phone": person["phone"]}
                    updated_at = min(now, created_at + rng.uniform(0.2, 2.5) * 86400) if status != "placed" else created_at
                    db.execute(
                        "INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (order_id, f"{self.order_prefix}-" + secrets.token_hex(4).upper(), person["id"], self.tenant_id, status,
                         "refunded" if status == "cancelled" else "paid", subtotal, subtotal, "INR",
                         json.dumps(customer), json.dumps(address), created_at, updated_at),
                    )
                    for product, quantity in items:
                        db.execute(
                            "INSERT INTO order_items VALUES(?,?,?,?,?,?,?)",
                            (str(uuid.uuid4()), order_id, product["id"], product["sku"], product["name"],
                             product["price_minor"], quantity),
                        )
                    db.execute(
                        "INSERT INTO payments VALUES(?,?,'simulator',?,?,?,?)",
                        (str(uuid.uuid4()), order_id, "PAY-" + secrets.token_hex(4).upper(), subtotal,
                         "refunded" if status == "cancelled" else "paid", created_at),
                    )
                    created += 1
        return created

    @staticmethod
    def _product(row):
        data = dict(row)
        data["published"] = bool(data["published"])
        return data

    def products(self, include_unpublished=False):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM products" + ("" if include_unpublished else " WHERE published=1") + " ORDER BY name").fetchall()
        return [self._product(row) for row in rows]

    def product(self, product_id, include_unpublished=False):
        with self.connect() as db:
            row = db.execute("SELECT * FROM products WHERE id=?" + ("" if include_unpublished else " AND published=1"), (product_id,)).fetchone()
        return self._product(row) if row else None

    def save_product(self, values, product_id=None):
        now = time.time()
        with self.connect() as db:
            if product_id:
                if not db.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
                    return None
                db.execute(
                    """UPDATE products SET sku=?,name=?,description=?,price_minor=?,currency=?,stock_quantity=?,published=?,image_path=?,updated_at=? WHERE id=?""",
                    (values["sku"], values["name"], values["description"], values["price_minor"], values["currency"],
                     values["stock_quantity"], int(values["published"]), values["image_path"], now, product_id),
                )
            else:
                product_id = str(uuid.uuid4())
                db.execute(
                    "INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (product_id, values["sku"], values["name"], values["description"], values["price_minor"], values["currency"],
                     values["stock_quantity"], int(values["published"]), values["image_path"], now, now),
                )
        return self.product(product_id, True)

    @staticmethod
    def _active_cart(db, user_id):
        row = db.execute("SELECT id FROM carts WHERE user_id=? AND status='active'", (user_id,)).fetchone()
        if row:
            return row["id"]
        cart_id = str(uuid.uuid4())
        db.execute("INSERT INTO carts VALUES(?,?,'active',?)", (cart_id, user_id, time.time()))
        return cart_id

    def cart(self, user_id):
        with self.connect() as db:
            cart_id = self._active_cart(db, user_id)
            rows = db.execute(
                """SELECT ci.product_id,ci.quantity,ci.unit_price_minor,p.sku,p.name,p.stock_quantity,p.published,p.image_path
                   FROM cart_items ci JOIN products p ON p.id=ci.product_id WHERE ci.cart_id=? ORDER BY p.name""", (cart_id,)
            ).fetchall()
        items = [dict(row, line_total_minor=row["unit_price_minor"] * row["quantity"]) for row in rows]
        return {"id": cart_id, "items": items, "subtotal_minor": sum(x["line_total_minor"] for x in items), "currency": "INR"}

    def set_cart_item(self, user_id, product_id, quantity):
        with self.connect() as db:
            product = db.execute("SELECT * FROM products WHERE id=? AND published=1", (product_id,)).fetchone()
            if not product:
                raise RetailError("Product not found")
            if quantity > product["stock_quantity"]:
                raise RetailError("Requested quantity is not available")
            cart_id = self._active_cart(db, user_id)
            db.execute(
                """INSERT INTO cart_items VALUES(?,?,?,?) ON CONFLICT(cart_id,product_id)
                   DO UPDATE SET quantity=excluded.quantity,unit_price_minor=excluded.unit_price_minor""",
                (cart_id, product_id, quantity, product["price_minor"]),
            )
            db.execute("UPDATE carts SET updated_at=? WHERE id=?", (time.time(), cart_id))
        return self.cart(user_id)

    def remove_cart_item(self, user_id, product_id):
        with self.connect() as db:
            cart_id = self._active_cart(db, user_id)
            db.execute("DELETE FROM cart_items WHERE cart_id=? AND product_id=?", (cart_id, product_id))
        return self.cart(user_id)

    @staticmethod
    def _event(
        db, request_id, tenant, actor, session_id, source, destination,
        action, route, result, *, protocol="TCP", destination_port=None,
    ):
        now = time.time()
        db.execute(
            """INSERT OR IGNORE INTO application_events
               (id,occurred_at,request_id,tenant_id,actor_id,session_id,source_workload,
                destination_workload,action,route_template,result,protocol,destination_port)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), now, request_id, tenant, actor, session_id, source,
             destination, action, route, result, protocol, destination_port),
        )
        db.execute(
            "DELETE FROM application_events WHERE occurred_at<?",
            (now - APPLICATION_EVENT_RETENTION_SECONDS,),
        )
        db.execute(
            """DELETE FROM application_events WHERE id IN (
                 SELECT id FROM application_events ORDER BY occurred_at DESC,id DESC
                 LIMIT -1 OFFSET ?
               )""",
            (APPLICATION_EVENT_LIMIT,),
        )

    @staticmethod
    def _order_from_db(db, order_id):
        row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["customer"] = json.loads(result.pop("customer_snapshot"))
        result["delivery_address"] = json.loads(result.pop("address_snapshot"))
        result["items"] = [dict(x) for x in db.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY name_snapshot", (order_id,))]
        payment = db.execute("SELECT provider,reference,amount_minor,status,created_at FROM payments WHERE order_id=?", (order_id,)).fetchone()
        result["payment"] = dict(payment) if payment else None
        return result

    def checkout(self, user, address, key, request_id, session_id):
        fingerprint = sha256(json.dumps(address, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT fingerprint,order_id FROM retail_idempotency WHERE user_id=? AND idempotency_key=?", (user["user_id"], key)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise RetailError("Idempotency key was used for another checkout")
                return self._order_from_db(db, prior["order_id"])
            cart_id = self._active_cart(db, user["user_id"])
            items = db.execute(
                """SELECT ci.*,p.sku,p.name,p.stock_quantity,p.published,p.price_minor FROM cart_items ci
                   JOIN products p ON p.id=ci.product_id WHERE ci.cart_id=?""", (cart_id,)
            ).fetchall()
            if not items:
                raise RetailError("Cart is empty")
            for item in items:
                if not item["published"] or item["quantity"] > item["stock_quantity"]:
                    raise RetailError(f"{item['name']} is no longer available in that quantity")
            subtotal, order_id = sum(x["price_minor"] * x["quantity"] for x in items), str(uuid.uuid4())
            order_number = f"{self.order_prefix}-" + secrets.token_hex(4).upper()
            customer = {"id": user["user_id"], "name": user["display_name"], "email": user["email"], "phone": user["phone"]}
            db.execute(
                "INSERT INTO customer_addresses VALUES(?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), user["user_id"], address["recipient"], address["line1"], address["line2"],
                 address["city"], address["state"], address["postal_code"], address["phone"], now),
            )
            db.execute(
                "INSERT INTO orders VALUES(?,?,?,?,'placed','paid',?,?,?,?,?,?,?)",
                (order_id, order_number, user["user_id"], user["tenant_id"], subtotal, subtotal, "INR",
                 json.dumps(customer), json.dumps(address), now, now),
            )
            for item in items:
                db.execute("INSERT INTO order_items VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), order_id, item["product_id"], item["sku"], item["name"], item["price_minor"], item["quantity"]))
                if db.execute("UPDATE products SET stock_quantity=stock_quantity-?,updated_at=? WHERE id=? AND stock_quantity>=?", (item["quantity"], now, item["product_id"], item["quantity"])).rowcount != 1:
                    raise RetailError("Stock changed during checkout; try again")
            db.execute("INSERT INTO payments VALUES(?,?,'simulator',?,?,'paid',?)", (str(uuid.uuid4()), order_id, "PAY-" + secrets.token_hex(4).upper(), subtotal, now))
            db.execute("UPDATE carts SET status='checked_out',updated_at=? WHERE id=?", (now, cart_id))
            db.execute("INSERT INTO retail_idempotency VALUES(?,?,?,?,?)", (user["user_id"], key, fingerprint, order_id, now))
            self._event(
                db, request_id, user["tenant_id"], user["user_id"], session_id,
                "frontend", "checkoutservice", "order.checkout",
                "/api/retail/checkout", "paid", destination_port=8080,
            )
            return self._order_from_db(db, order_id)

    def orders(self, user_id=None):
        with self.connect() as db:
            rows = db.execute("SELECT id FROM orders" + (" WHERE user_id=?" if user_id else "") + " ORDER BY created_at DESC", ((user_id,) if user_id else ())).fetchall()
            return [self._order_from_db(db, row["id"]) for row in rows]

    def order(self, order_id, user_id=None):
        with self.connect() as db:
            row = db.execute("SELECT user_id FROM orders WHERE id=?", (order_id,)).fetchone()
            return None if not row or (user_id and row["user_id"] != user_id) else self._order_from_db(db, order_id)

    def update_order_status(self, order_id, status, actor, request_id, session_id):
        transitions = {"placed": {"processing", "cancelled"}, "processing": {"packing", "cancelled"}, "packing": {"shipped"}, "shipped": {"delivered"}}
        with self.connect() as db:
            row = db.execute("SELECT status,tenant_id FROM orders WHERE id=?", (order_id,)).fetchone()
            if not row:
                return None
            if status != row["status"] and status not in transitions.get(row["status"], set()):
                raise RetailError(f"Order cannot move from {row['status']} to {status}")
            db.execute("UPDATE orders SET status=?,updated_at=? WHERE id=?", (status, time.time(), order_id))
            self._event(
                db, request_id, row["tenant_id"], actor["user_id"], session_id,
                "retail-admin", "order-api", "order.status_changed",
                "/api/retail/admin/orders/{id}/status", status,
                destination_port=8080,
            )
            return self._order_from_db(db, order_id)

    def customers(self):
        with self.connect() as db:
            rows = db.execute(
                """SELECT u.id,u.email,u.display_name,u.phone,u.status,u.created_at,COUNT(DISTINCT o.id) order_count,
                   COALESCE(SUM(o.total_minor),0) total_spent_minor,MAX(s.last_seen_at) last_seen_at FROM retail_users u
                   LEFT JOIN orders o ON o.user_id=u.id LEFT JOIN retail_sessions s ON s.user_id=u.id AND s.revoked_at IS NULL
                   WHERE u.role='customer' GROUP BY u.id ORDER BY u.created_at DESC"""
            ).fetchall()
        return [dict(x) for x in rows]

    def sessions(self):
        now = time.time()
        with self.connect() as db:
            rows = db.execute(
                """SELECT s.id,s.created_at,s.expires_at,s.last_seen_at,s.client_summary,u.id user_id,u.email,u.display_name,u.role
                   FROM retail_sessions s JOIN retail_users u ON u.id=s.user_id
                   WHERE s.revoked_at IS NULL AND s.expires_at>? ORDER BY s.last_seen_at DESC""", (now,)
            ).fetchall()
        return [dict(x, active=x["last_seen_at"] >= now - 300) for x in rows]

    def overview(self):
        cutoff, now = time.time() - 86400, time.time()
        with self.connect() as db:
            row = db.execute(
                """SELECT COUNT(*) orders_today,COALESCE(SUM(total_minor),0) revenue_today_minor,
                   COALESCE(SUM(CASE WHEN status NOT IN('delivered','cancelled') THEN 1 ELSE 0 END),0) open_orders
                   FROM orders WHERE created_at>=?""", (cutoff,)
            ).fetchone()
            active = db.execute(
                """SELECT COUNT(DISTINCT s.user_id) n FROM retail_sessions s
                   JOIN retail_users u ON u.id=s.user_id
                   WHERE u.role='customer' AND s.revoked_at IS NULL AND s.expires_at>? AND s.last_seen_at>=?""",
                (now, now - 300),
            ).fetchone()["n"]
        return dict(row, active_customers=active, currency="INR")

    def events(self, limit=100, *, tenant_id=None, start=None, end=None):
        if not 1 <= limit <= 1_000:
            raise ValueError("Invalid application-event query limit")
        clauses, parameters = [], []
        if tenant_id is not None:
            clauses.append("tenant_id=?")
            parameters.append(tenant_id)
        if start is not None:
            clauses.append("occurred_at>=?")
            parameters.append(start)
        if end is not None:
            clauses.append("occurred_at<?")
            parameters.append(end)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM application_events{where} ORDER BY occurred_at DESC,id DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [dict(x) for x in rows]
