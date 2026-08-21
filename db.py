"""
Trip-share database layer (PostgreSQL — psycopg 3).

Connection: reads DATABASE_URL from env (auto-injected by Render for Postgres).
On Render: `render.yaml` provisions a free Postgres instance and passes
DATABASE_URL to the web service automatically.

Schema: psycopg 3 with `%s` parameter style (same as psycopg2). Rows come back
as dicts via `dict_row` so callers can do `row["col"]` exactly as before.

Why psycopg 3 instead of psycopg2-binary 2.9.9?
- psycopg2 2.9.x tops out at Python 3.13; does NOT install on Python 3.14.
- Render's default runtime is Python 3.14+ unless pinned via runtime.txt.
- psycopg 3 is the actively maintained, Python 3.13/3.14-friendly replacement.
- API differences are tiny — we keep an alias `psycopg2 = psycopg` so the
  call sites below read exactly like the old psycopg2 code.
"""
import os
import secrets
import string
from datetime import datetime, date
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

# Backwards-compat alias so old `cur.fetchone()["id"]` style keeps working.
psycopg2 = psycopg


# --- JSON helpers ---------------------------------------------------------

def to_jsonable(obj):
    """Convert datetime/date to ISO strings for JSON serialization."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


# --- Connection -----------------------------------------------------------

def _connect(max_retries=12, base_delay=1.5, max_delay=20.0):
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. On Render it's auto-injected when "
            "you deploy via render.yaml with a Postgres service attached. "
            "For local dev, set DATABASE_URL to your own Postgres URL."
        )
    # Render sometimes uses the legacy `postgres://` scheme.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    last_exc = None
    import time
    for attempt in range(max_retries):
        try:
            conn = psycopg.connect(url, row_factory=dict_row)
            if attempt > 0:
                print(f"[db] Connected to database after {attempt + 1} attempts.")
            return conn
        except psycopg.OperationalError as e:
            last_exc = e
            if attempt < max_retries - 1:
                wait = min(base_delay * (2 ** attempt), max_delay)
                print(f"[db] DB connection attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"[db] DB connection failed after {max_retries} attempts: {e}")
    raise last_exc


@contextmanager
def get_db():
    """
    Usage:
        with db.get_db() as conn:
            db.create_user(conn, ...)
    `conn` is a psycopg connection with dict cursors. All writes are committed
    on context exit; rolled back on exception.
    """
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Schema ---------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trips (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    start_date TEXT,
    end_date TEXT,
    cover_image TEXT,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    invite_code TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trip_members (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT DEFAULT 'member',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(trip_id, user_id)
);

CREATE TABLE IF NOT EXISTS expense_groups (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS expense_group_members (
    group_id INTEGER NOT NULL REFERENCES expense_groups(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY(group_id, user_id)
);

CREATE TABLE IF NOT EXISTS wishlist (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    url TEXT,
    image_url TEXT,
    description TEXT,
    category TEXT,
    added_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS itinerary (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    day_date TEXT,
    start_time TEXT,
    end_time TEXT,
    title TEXT NOT NULL,
    location TEXT,
    address TEXT,
    description TEXT,
    url TEXT,
    image_url TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hotels (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    address TEXT,
    check_in TEXT,
    check_out TEXT,
    room_numbers TEXT,
    booked_by INTEGER REFERENCES users(id),
    contact_phone TEXT,
    notes TEXT,
    url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meeting_points (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    meet_time TEXT,
    location TEXT NOT NULL,
    address TEXT,
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS expenses (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES expense_groups(id) ON DELETE CASCADE,
    paid_by INTEGER NOT NULL REFERENCES users(id),
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'CNY',
    description TEXT,
    expense_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trips_owner ON trips(owner_id);
CREATE INDEX IF NOT EXISTS idx_trip_members_trip ON trip_members(trip_id);
CREATE INDEX IF NOT EXISTS idx_expenses_trip ON expenses(trip_id);
CREATE INDEX IF NOT EXISTS idx_itinerary_trip ON itinerary(trip_id);

-- ===== Travel guides (个人 + trip 内协作 双模式) =====
-- trip_id NULL = 纯个人攻略，只 owner 能改；
-- trip_id 非空 = 归在某个 trip 下，该 trip 的成员都可读写。

CREATE TABLE IF NOT EXISTS travel_guides (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    trip_id INTEGER REFERENCES trips(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    destination TEXT,
    cover_image TEXT,
    summary TEXT,
    start_date TEXT,
    end_date TEXT,
    tags TEXT,
    share_token TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 已建表后加 share_token 列（仅 Postgres / 9.6+）
ALTER TABLE travel_guides ADD COLUMN IF NOT EXISTS share_token TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_guides_share_token_unique
    ON travel_guides(share_token)
    WHERE share_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS travel_guide_days (
    id SERIAL PRIMARY KEY,
    guide_id INTEGER NOT NULL REFERENCES travel_guides(id) ON DELETE CASCADE,
    day_index INTEGER NOT NULL,
    day_date TEXT,
    title TEXT,
    notes TEXT,
    UNIQUE(guide_id, day_index)
);

CREATE TABLE IF NOT EXISTS travel_guide_items (
    id SERIAL PRIMARY KEY,
    day_id INTEGER NOT NULL REFERENCES travel_guide_days(id) ON DELETE CASCADE,
    sort_index INTEGER DEFAULT 0,
    time TEXT,
    title TEXT NOT NULL,
    location TEXT,
    address TEXT,
    description TEXT,
    image_url TEXT,
    url TEXT,
    category TEXT
);

CREATE INDEX IF NOT EXISTS idx_guides_user ON travel_guides(user_id);
CREATE INDEX IF NOT EXISTS idx_guides_trip ON travel_guides(trip_id);
CREATE INDEX IF NOT EXISTS idx_guide_items_day ON travel_guide_items(day_id);
"""

# SERIAL / REAL / TIMESTAMP are used so `%s` placeholder fixes are minimal.


def init_db():
    """Apply schema. Safe to call repeatedly."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
    print("[db] schema applied.")


# --- User helpers ---------------------------------------------------------

def create_user(conn, username, password_hash, display_name=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, display_name) "
            "VALUES (%s, %s, %s) RETURNING id",
            (username, password_hash, display_name or username),
        )
        return cur.fetchone()["id"]


def get_user_by_username(conn, username):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        return cur.fetchone()


def get_user_by_id(conn, user_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        return cur.fetchone()


# --- Trip helpers ---------------------------------------------------------

def generate_invite_code():
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))


def create_trip(conn, name, description, start_date, end_date, owner_id, cover_image=None):
    invite = generate_invite_code()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO trips (name, description, start_date, end_date, cover_image, owner_id, invite_code) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (name, description, start_date, end_date, cover_image, owner_id, invite),
        )
        trip_id = cur.fetchone()["id"]
        # owner 自动加入成员
        cur.execute(
            "INSERT INTO trip_members (trip_id, user_id, role) VALUES (%s, %s, %s)",
            (trip_id, owner_id, 'owner'),
        )
        # 同时建一个默认的全员费用群组,并把 owner 加进去
        cur.execute(
            "INSERT INTO expense_groups (trip_id, name) VALUES (%s, %s) RETURNING id",
            (trip_id, "全员"),
        )
        group_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO expense_group_members (group_id, user_id) VALUES (%s, %s)",
            (group_id, owner_id),
        )
    return trip_id, invite


def get_trip_by_id(conn, trip_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM trips WHERE id=%s", (trip_id,))
        return cur.fetchone()


def get_trip_by_invite(conn, invite_code):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM trips WHERE invite_code=%s", (invite_code.upper(),))
        return cur.fetchone()


def list_user_trips(conn, user_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t.*, tm.role
            FROM trips t
            JOIN trip_members tm ON tm.trip_id = t.id
            WHERE tm.user_id = %s
            ORDER BY t.created_at DESC
        """, (user_id,))
        return cur.fetchall()


def add_trip_member(conn, trip_id, user_id, role='member'):
    """把用户加入旅行；如果已是成员则返回 False。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO trip_members (trip_id, user_id, role) VALUES (%s, %s, %s) "
            "ON CONFLICT (trip_id, user_id) DO NOTHING RETURNING id",
            (trip_id, user_id, role),
        )
        inserted = cur.fetchone() is not None
        if not inserted:
            return False
        # 把新成员自动加入旅行的"全员"费用群组（如果有的话，且不在组里）
        cur.execute(
            "SELECT id FROM expense_groups WHERE trip_id=%s AND name='全员' LIMIT 1",
            (trip_id,)
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "SELECT 1 FROM expense_group_members WHERE group_id=%s AND user_id=%s",
                (row["id"], user_id)
            )
            already = cur.fetchone()
            if not already:
                cur.execute(
                    "INSERT INTO expense_group_members (group_id, user_id) VALUES (%s, %s)",
                    (row["id"], user_id)
                )
    return True


def is_trip_member(conn, trip_id, user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM trip_members WHERE trip_id=%s AND user_id=%s",
            (trip_id, user_id)
        )
        return cur.fetchone() is not None


def list_trip_members(conn, trip_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT u.id, u.username, u.display_name, tm.role, tm.joined_at
            FROM trip_members tm
            JOIN users u ON u.id = tm.user_id
            WHERE tm.trip_id = %s
            ORDER BY tm.joined_at ASC
        """, (trip_id,))
        return cur.fetchall()


# --- Expense group helpers ------------------------------------------------

def create_expense_group(conn, trip_id, name):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO expense_groups (trip_id, name) VALUES (%s, %s) RETURNING id",
            (trip_id, name),
        )
        return cur.fetchone()["id"]


def list_expense_groups(conn, trip_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT eg.*, COUNT(egm.user_id) AS member_count
            FROM expense_groups eg
            LEFT JOIN expense_group_members egm ON egm.group_id = eg.id
            WHERE eg.trip_id = %s
            GROUP BY eg.id
            ORDER BY eg.created_at ASC
        """, (trip_id,))
        return cur.fetchall()


def get_expense_group(conn, group_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM expense_groups WHERE id=%s", (group_id,))
        return cur.fetchone()


def set_group_members(conn, group_id, user_ids):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM expense_group_members WHERE group_id=%s", (group_id,))
        for uid in user_ids:
            cur.execute(
                "INSERT INTO expense_group_members (group_id, user_id) VALUES (%s, %s)",
                (group_id, uid),
            )


def list_group_members(conn, group_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT u.id, u.username, u.display_name
            FROM expense_group_members egm
            JOIN users u ON u.id = egm.user_id
            WHERE egm.group_id = %s
            ORDER BY u.display_name
        """, (group_id,))
        return cur.fetchall()


# --- Wishlist helpers -----------------------------------------------------

def add_wishlist(conn, trip_id, title, url, image_url, description, category, added_by):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO wishlist (trip_id, title, url, image_url, description, category, added_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (trip_id, title, url, image_url, description, category, added_by),
        )
        return cur.fetchone()["id"]


def list_wishlist(conn, trip_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT w.*, u.display_name AS added_by_name
            FROM wishlist w
            LEFT JOIN users u ON u.id = w.added_by
            WHERE w.trip_id = %s
            ORDER BY w.created_at ASC
        """, (trip_id,))
        return cur.fetchall()


def delete_wishlist(conn, item_id, user_id=None, role=None):
    conn.cursor().execute("DELETE FROM wishlist WHERE id=%s", (item_id,))


# --- Itinerary helpers ----------------------------------------------------

def add_itinerary(conn, trip_id, day_date, start_time, end_time, title, location, address, description, url, image_url, created_by):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO itinerary (trip_id, day_date, start_time, end_time, title, location, address, description, url, image_url, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (trip_id, day_date, start_time, end_time, title, location, address, description, url, image_url, created_by))
        return cur.fetchone()["id"]


def list_itinerary(conn, trip_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT i.*, u.display_name AS created_by_name
            FROM itinerary i
            LEFT JOIN users u ON u.id = i.created_by
            WHERE i.trip_id = %s
            ORDER BY i.day_date ASC, i.start_time ASC
        """, (trip_id,))
        return cur.fetchall()


def delete_itinerary(conn, item_id):
    conn.cursor().execute("DELETE FROM itinerary WHERE id=%s", (item_id,))


# --- Hotel helpers --------------------------------------------------------

def add_hotel(conn, trip_id, name, address, check_in, check_out, room_numbers, booked_by, contact_phone, notes, url):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO hotels (trip_id, name, address, check_in, check_out, room_numbers, booked_by, contact_phone, notes, url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (trip_id, name, address, check_in, check_out, room_numbers, booked_by, contact_phone, notes, url))
        return cur.fetchone()["id"]


def list_hotels(conn, trip_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT h.*, u.display_name AS booked_by_name
            FROM hotels h
            LEFT JOIN users u ON u.id = h.booked_by
            WHERE h.trip_id = %s
            ORDER BY h.check_in ASC
        """, (trip_id,))
        return cur.fetchall()


def delete_hotel(conn, hotel_id):
    conn.cursor().execute("DELETE FROM hotels WHERE id=%s", (hotel_id,))


# --- Meeting point helpers ------------------------------------------------

def add_meeting(conn, trip_id, meet_time, location, address, notes, created_by):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO meeting_points (trip_id, meet_time, location, address, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (trip_id, meet_time, location, address, notes, created_by))
        return cur.fetchone()["id"]


def list_meetings(conn, trip_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.*, u.display_name AS created_by_name
            FROM meeting_points m
            LEFT JOIN users u ON u.id = m.created_by
            WHERE m.trip_id = %s
            ORDER BY m.meet_time ASC
        """, (trip_id,))
        return cur.fetchall()


def delete_meeting(conn, meeting_id):
    conn.cursor().execute("DELETE FROM meeting_points WHERE id=%s", (meeting_id,))


# --- Expense helpers ------------------------------------------------------

def add_expense(conn, trip_id, group_id, paid_by, amount, currency, description, expense_date):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO expenses (trip_id, group_id, paid_by, amount, currency, description, expense_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (trip_id, group_id, paid_by, float(amount), currency, description, expense_date))
        return cur.fetchone()["id"]


def list_expenses(conn, trip_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.*,
                   eg.name AS group_name,
                   u.display_name AS paid_by_name
            FROM expenses e
            JOIN expense_groups eg ON eg.id = e.group_id
            JOIN users u ON u.id = e.paid_by
            WHERE e.trip_id = %s
            ORDER BY e.expense_date DESC, e.created_at DESC
        """, (trip_id,))
        return cur.fetchall()


def delete_expense(conn, expense_id):
    conn.cursor().execute("DELETE FROM expenses WHERE id=%s", (expense_id,))


def compute_balances(conn, trip_id):
    """
    计算每个用户的余额（正数=应收，负数=应付）。
    对每笔费用：分摊 = amount / group_members_count；
    paid_by 账户 += amount；每个成员账户 -= 分摊。
    """
    expenses = list_expenses(conn, trip_id)
    members = list_trip_members(conn, trip_id)
    balance = {m['id']: 0.0 for m in members}

    for e in expenses:
        group_members = list_group_members(conn, e['group_id'])
        n = len(group_members)
        if n == 0:
            continue
        share = e['amount'] / n
        balance[e['paid_by']] = balance.get(e['paid_by'], 0) + e['amount']
        for gm in group_members:
            balance[gm['id']] = balance.get(gm['id'], 0) - share

    result = []
    name_map = {m['id']: m['display_name'] for m in members}
    for uid, b in balance.items():
        result.append({
            "user_id": uid,
            "display_name": name_map.get(uid, f"User#{uid}"),
            "balance": round(b, 2)
        })
    result.sort(key=lambda x: -x['balance'])
    return result


# --- Travel guide helpers -------------------------------------------------

def create_guide(conn, user_id, trip_id, title, destination, cover_image,
                  summary, start_date, end_date, tags):
    """trip_id 为 None = 个人攻略；否则挂在 trip 下，trip 成员可编辑。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO travel_guides (user_id, trip_id, title, destination, cover_image, summary, start_date, end_date, tags) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (user_id, trip_id, title, destination, cover_image, summary,
             start_date, end_date, tags),
        )
        return cur.fetchone()["id"]


def get_guide(conn, guide_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT g.*, u.display_name AS created_by_name, t.name AS trip_name
            FROM travel_guides g
            JOIN users u ON u.id = g.user_id
            LEFT JOIN trips t ON t.id = g.trip_id
            WHERE g.id = %s
        """, (guide_id,))
        return cur.fetchone()


def list_my_personal_guides(conn, user_id):
    """只列个人攻略 (trip_id IS NULL)"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT g.*, u.display_name AS created_by_name
            FROM travel_guides g
            JOIN users u ON u.id = g.user_id
            WHERE g.user_id = %s AND g.trip_id IS NULL
            ORDER BY g.updated_at DESC
        """, (user_id,))
        return cur.fetchall()


def list_my_all_guides(conn, user_id):
    """列我跟攻略的关系：个人 + trip 内的（前提是我是该 trip 成员）"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT g.*, u.display_name AS created_by_name, t.name AS trip_name
            FROM travel_guides g
            JOIN users u ON u.id = g.user_id
            LEFT JOIN trips t ON t.id = g.trip_id
            WHERE g.user_id = %s
               OR (g.trip_id IS NOT NULL
                   AND g.trip_id IN (SELECT trip_id FROM trip_members WHERE user_id = %s))
            ORDER BY g.updated_at DESC
        """, (user_id, user_id))
        return cur.fetchall()


def list_trip_guides(conn, trip_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT g.*, u.display_name AS created_by_name
            FROM travel_guides g
            JOIN users u ON u.id = g.user_id
            WHERE g.trip_id = %s
            ORDER BY g.updated_at DESC
        """, (trip_id,))
        return cur.fetchall()


def update_guide(conn, guide_id, **kwargs):
    """只更新提供的字段，并自动维护 updated_at。"""
    allowed = ["title", "destination", "cover_image", "summary",
               "start_date", "end_date", "tags"]
    sets, vals = [], []
    for k in allowed:
        if k in kwargs:
            sets.append(f"{k}=%s")
            vals.append(kwargs[k])
    if not sets:
        return
    sets.append("updated_at=CURRENT_TIMESTAMP")
    vals.append(guide_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE travel_guides SET {', '.join(sets)} WHERE id=%s", vals)


def delete_guide(conn, guide_id):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM travel_guides WHERE id=%s", (guide_id,))


def is_guide_editor(conn, guide_id, user_id):
    """
    谁能编辑攻略：
    - 个人攻略：creator 本人
    - trip 攻略：creator 本人 + 该 trip 所有 member
    """
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, trip_id FROM travel_guides WHERE id=%s", (guide_id,))
        g = cur.fetchone()
        if not g:
            return False
        if g["user_id"] == user_id:
            return True
        if g["trip_id"] is not None:
            cur.execute(
                "SELECT 1 FROM trip_members WHERE trip_id=%s AND user_id=%s",
                (g["trip_id"], user_id)
            )
            return cur.fetchone() is not None
        return False


def get_guide_viewer(conn, guide_id, user_id):
    """谁能查看攻略：editor 或公开 trip 中所有人的指南都可见。
    个人攻略只 owner 可见。"""
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, trip_id FROM travel_guides WHERE id=%s", (guide_id,))
        g = cur.fetchone()
        if not g:
            return False
        if g["user_id"] == user_id:
            return True
        if g["trip_id"] is not None:
            cur.execute(
                "SELECT 1 FROM trip_members WHERE trip_id=%s AND user_id=%s",
                (g["trip_id"], user_id)
            )
            return cur.fetchone() is not None
        return False


# --- Days ---

def create_guide_day(conn, guide_id, day_index, day_date, title, notes):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO travel_guide_days (guide_id, day_index, day_date, title, notes) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (guide_id, day_index) DO UPDATE SET day_date=EXCLUDED.day_date, title=EXCLUDED.title, notes=EXCLUDED.notes "
            "RETURNING id",
            (guide_id, day_index, day_date, title, notes)
        )
        new_id = cur.fetchone()["id"]
        cur.execute(
            "UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP WHERE id=%s",
            (guide_id,)
        )
        return new_id


def list_guide_days(conn, guide_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM travel_guide_days WHERE guide_id=%s ORDER BY day_index ASC",
            (guide_id,),
        )
        return cur.fetchall()


def get_guide_day(conn, day_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM travel_guide_days WHERE id=%s", (day_id,))
        return cur.fetchone()


def update_guide_day(conn, day_id, guide_id=None, **kwargs):
    allowed = ["day_index", "day_date", "title", "notes"]
    sets, vals = [], []
    for k in allowed:
        if k in kwargs:
            sets.append(f"{k}=%s")
            vals.append(kwargs[k])
    if not sets:
        return
    vals.append(day_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE travel_guide_days SET {', '.join(sets)} WHERE id=%s", vals)
        if guide_id is not None:
            cur.execute("UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP WHERE id=%s", (guide_id,))


def delete_guide_day(conn, day_id, guide_id=None):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM travel_guide_days WHERE id=%s", (day_id,))
        if guide_id is not None:
            cur.execute("UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP WHERE id=%s", (guide_id,))


# --- Items ---

def create_guide_item(conn, day_id, time, title, location, address,
                       description, image_url, url, category, sort_index=0):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO travel_guide_items
              (day_id, sort_index, time, title, location, address, description, image_url, url, category)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (day_id, sort_index, time, title, location, address,
              description, image_url, url, category))
        new_id = cur.fetchone()["id"]
        # 触发 guide updated_at
        cur.execute("""
            UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP
            WHERE id = (SELECT guide_id FROM travel_guide_days WHERE id=%s)
        """, (day_id,))
        return new_id


def list_guide_items(conn, day_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM travel_guide_items WHERE day_id=%s ORDER BY sort_index ASC, time ASC",
            (day_id,),
        )
        return cur.fetchall()


def get_guide_item(conn, item_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM travel_guide_items WHERE id=%s", (item_id,))
        return cur.fetchone()


def update_guide_item(conn, item_id, **kwargs):
    allowed = ["sort_index", "time", "title", "location", "address",
               "description", "image_url", "url", "category"]
    sets, vals = [], []
    for k in allowed:
        if k in kwargs:
            sets.append(f"{k}=%s")
            vals.append(kwargs[k])
    if not sets:
        return
    vals.append(item_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE travel_guide_items SET {', '.join(sets)} WHERE id=%s", vals)
        cur.execute("""
            UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP
            WHERE id = (SELECT d.guide_id FROM travel_guide_items i
                        JOIN travel_guide_days d ON d.id=i.day_id
                        WHERE i.id=%s)
        """, (item_id,))


def delete_guide_item(conn, item_id):
    with conn.cursor() as cur:
        cur.execute("SELECT day_id FROM travel_guide_items WHERE id=%s", (item_id,))
        row = cur.fetchone()
        cur.execute("DELETE FROM travel_guide_items WHERE id=%s", (item_id,))
        if row:
            cur.execute("""
                UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP
                WHERE id = (SELECT guide_id FROM travel_guide_days WHERE id=%s)
            """, (row["day_id"],))


def get_guide_full(conn, guide_id):
    """一次性拉取攻略 + 所有 days + 所有 items，给前端用。"""
    guide = get_guide(conn, guide_id)
    if not guide:
        return None
    days = list_guide_days(conn, guide_id)
    # 每个 day 拿一次 items (N+1 风险由天数控制，可接受)
    days_full = []
    for d in days:
        items = list_guide_items(conn, d["id"])
        days_full.append({
            **dict(d),
            "items": [dict(i) for i in items]
        })
    guide["days"] = days_full
    return guide


# --- Share token helpers (公开分享链接用) -------------------------------

def enable_share_token(conn, guide_id):
    """生成一个 token，写回并返回。已存在则直接复用。"""
    with conn.cursor() as cur:
        cur.execute("SELECT share_token FROM travel_guides WHERE id=%s", (guide_id,))
        row = cur.fetchone()
        if not row:
            return None
        token = row["share_token"] or ''.join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
        )
        cur.execute("UPDATE travel_guides SET share_token=%s WHERE id=%s", (token, guide_id))
        cur.execute("UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP WHERE id=%s", (guide_id,))
        return token


def disable_share_token(conn, guide_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE travel_guides SET share_token=NULL WHERE id=%s", (guide_id,))
        cur.execute("UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP WHERE id=%s", (guide_id,))


def get_guide_by_share_token(conn, token):
    """用公开 token 拿攻略（不需要登录）。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT g.*, u.display_name AS created_by_name, t.name AS trip_name
            FROM travel_guides g
            JOIN users u ON u.id = g.user_id
            LEFT JOIN trips t ON t.id = g.trip_id
            WHERE g.share_token = %s
        """, (token,))
        guide = cur.fetchone()
        if not guide:
            return None
        days = list_guide_days(conn, guide["id"])
        days_full = []
        for d in days:
            items = list_guide_items(conn, d["id"])
            days_full.append({
                **dict(d),
                "items": [dict(i) for i in items]
            })
        guide["days"] = days_full
        return guide


if __name__ == "__main__":
    init_db()
    print("[db] schema applied.")
