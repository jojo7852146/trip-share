"""
Local-only SQLite fallback for development.

If `DATABASE_URL` is NOT set, server.py will use this module instead of db.py.
Production (Render) always sets DATABASE_URL, so this file is ignored there.

Mirror of db.py API; schema mirrors the Postgres version (best-effort compatibility).
"""
import os
import sqlite3
import secrets
import string
from contextlib import contextmanager

DB_PATH = os.environ.get("TRIP_SQLITE_PATH", "data/trip_local.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    start_date TEXT,
    end_date TEXT,
    cover_image TEXT,
    owner_id INTEGER NOT NULL,
    invite_code TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(owner_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS trip_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT DEFAULT 'member',
    joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(trip_id, user_id),
    FOREIGN KEY(trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS expense_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trip_id) REFERENCES trips(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS expense_group_members (
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY(group_id, user_id),
    FOREIGN KEY(group_id) REFERENCES expense_groups(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    image_url TEXT,
    description TEXT,
    category TEXT,
    added_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    FOREIGN KEY(added_by) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS itinerary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    day_date TEXT,
    start_time TEXT,
    end_time TEXT,
    title TEXT NOT NULL,
    location TEXT,
    address TEXT,
    description TEXT,
    url TEXT,
    image_url TEXT,
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    FOREIGN KEY(created_by) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS hotels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    address TEXT,
    check_in TEXT,
    check_out TEXT,
    room_numbers TEXT,
    booked_by INTEGER,
    contact_phone TEXT,
    notes TEXT,
    url TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    FOREIGN KEY(booked_by) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS meeting_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    meet_time TEXT,
    location TEXT NOT NULL,
    address TEXT,
    notes TEXT,
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    FOREIGN KEY(created_by) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    paid_by INTEGER NOT NULL,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'CNY',
    description TEXT,
    expense_date TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trip_id) REFERENCES trips(id) ON DELETE CASCADE,
    FOREIGN KEY(group_id) REFERENCES expense_groups(id) ON DELETE CASCADE,
    FOREIGN KEY(paid_by) REFERENCES users(id)
);

-- ===== Travel guides =====
CREATE TABLE IF NOT EXISTS travel_guides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    trip_id INTEGER,
    title TEXT NOT NULL,
    destination TEXT,
    cover_image TEXT,
    summary TEXT,
    start_date TEXT,
    end_date TEXT,
    tags TEXT,
    share_token TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(trip_id) REFERENCES trips(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS travel_guide_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guide_id INTEGER NOT NULL,
    day_index INTEGER NOT NULL,
    day_date TEXT,
    title TEXT,
    notes TEXT,
    UNIQUE(guide_id, day_index),
    FOREIGN KEY(guide_id) REFERENCES travel_guides(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS travel_guide_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id INTEGER NOT NULL,
    sort_index INTEGER DEFAULT 0,
    time TEXT,
    title TEXT NOT NULL,
    location TEXT,
    address TEXT,
    description TEXT,
    image_url TEXT,
    url TEXT,
    category TEXT,
    FOREIGN KEY(day_id) REFERENCES travel_guide_days(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_guides_user ON travel_guides(user_id);
CREATE INDEX IF NOT EXISTS idx_guides_trip ON travel_guides(trip_id);
CREATE INDEX IF NOT EXISTS idx_guide_items_day ON travel_guide_items(day_id);
"""


def _connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        # SQLite 不支持 ADD COLUMN IF NOT EXISTS，给老库做轻量升级
        cur = conn.execute("PRAGMA table_info(travel_guides)")
        cols = {row[1] for row in cur.fetchall()}
        if "share_token" not in cols:
            conn.execute("ALTER TABLE travel_guides ADD COLUMN share_token TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_guides_share_token_unique "
                "ON travel_guides(share_token) WHERE share_token IS NOT NULL"
            )


def generate_invite_code():
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))


def create_user(conn, username, password_hash, display_name=None):
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, display_name) VALUES (?,?,?)",
        (username, password_hash, display_name or username),
    )
    return cur.lastrowid


def get_user_by_username(conn, username):
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(conn, user_id):
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_trip(conn, name, description, start_date, end_date, owner_id, cover_image=None):
    invite = generate_invite_code()
    cur = conn.execute(
        "INSERT INTO trips (name, description, start_date, end_date, cover_image, owner_id, invite_code) VALUES (?,?,?,?,?,?,?)",
        (name, description, start_date, end_date, cover_image, owner_id, invite),
    )
    trip_id = cur.lastrowid
    conn.execute(
        "INSERT INTO trip_members (trip_id, user_id, role) VALUES (?,?,?)",
        (trip_id, owner_id, 'owner'),
    )
    g_cur = conn.execute(
        "INSERT INTO expense_groups (trip_id, name) VALUES (?,?)",
        (trip_id, "全员"),
    )
    group_id = g_cur.lastrowid
    conn.execute(
        "INSERT INTO expense_group_members (group_id, user_id) VALUES (?,?)",
        (group_id, owner_id),
    )
    return trip_id, invite


def get_trip_by_id(conn, trip_id):
    row = conn.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
    return dict(row) if row else None


def get_trip_by_invite(conn, invite_code):
    row = conn.execute("SELECT * FROM trips WHERE invite_code=?", (invite_code.upper(),)).fetchone()
    return dict(row) if row else None


def list_user_trips(conn, user_id):
    rows = conn.execute("""
        SELECT t.*, tm.role
        FROM trips t
        JOIN trip_members tm ON tm.trip_id = t.id
        WHERE tm.user_id = ?
        ORDER BY t.created_at DESC
    """, (user_id,)).fetchall()
    return [dict(r) for r in rows]


def add_trip_member(conn, trip_id, user_id, role='member'):
    try:
        conn.execute(
            "INSERT INTO trip_members (trip_id, user_id, role) VALUES (?,?,?)",
            (trip_id, user_id, role),
        )
    except sqlite3.IntegrityError:
        return False
    row = conn.execute(
        "SELECT id FROM expense_groups WHERE trip_id=? AND name='全员' LIMIT 1",
        (trip_id,),
    ).fetchone()
    if row:
        already = conn.execute(
            "SELECT 1 FROM expense_group_members WHERE group_id=? AND user_id=?",
            (row["id"], user_id),
        ).fetchone()
        if not already:
            conn.execute(
                "INSERT INTO expense_group_members (group_id, user_id) VALUES (?,?)",
                (row["id"], user_id),
            )
    return True


def is_trip_member(conn, trip_id, user_id):
    row = conn.execute(
        "SELECT 1 FROM trip_members WHERE trip_id=? AND user_id=?",
        (trip_id, user_id),
    ).fetchone()
    return row is not None


def list_trip_members(conn, trip_id):
    rows = conn.execute("""
        SELECT u.id, u.username, u.display_name, tm.role, tm.joined_at
        FROM trip_members tm
        JOIN users u ON u.id = tm.user_id
        WHERE tm.trip_id = ?
        ORDER BY tm.joined_at ASC
    """, (trip_id,)).fetchall()
    return [dict(r) for r in rows]


def create_expense_group(conn, trip_id, name):
    cur = conn.execute(
        "INSERT INTO expense_groups (trip_id, name) VALUES (?,?)",
        (trip_id, name),
    )
    return cur.lastrowid


def list_expense_groups(conn, trip_id):
    rows = conn.execute("""
        SELECT eg.*, COUNT(egm.user_id) AS member_count
        FROM expense_groups eg
        LEFT JOIN expense_group_members egm ON egm.group_id = eg.id
        WHERE eg.trip_id = ?
        GROUP BY eg.id
        ORDER BY eg.created_at ASC
    """, (trip_id,)).fetchall()
    return [dict(r) for r in rows]


def get_expense_group(conn, group_id):
    row = conn.execute("SELECT * FROM expense_groups WHERE id=?", (group_id,)).fetchone()
    return dict(row) if row else None


def set_group_members(conn, group_id, user_ids):
    conn.execute("DELETE FROM expense_group_members WHERE group_id=?", (group_id,))
    for uid in user_ids:
        conn.execute(
            "INSERT INTO expense_group_members (group_id, user_id) VALUES (?,?)",
            (group_id, uid),
        )


def list_group_members(conn, group_id):
    rows = conn.execute("""
        SELECT u.id, u.username, u.display_name
        FROM expense_group_members egm
        JOIN users u ON u.id = egm.user_id
        WHERE egm.group_id = ?
        ORDER BY u.display_name
    """, (group_id,)).fetchall()
    return [dict(r) for r in rows]


def add_wishlist(conn, trip_id, title, url, image_url, description, category, added_by):
    cur = conn.execute(
        "INSERT INTO wishlist (trip_id, title, url, image_url, description, category, added_by) VALUES (?,?,?,?,?,?,?)",
        (trip_id, title, url, image_url, description, category, added_by),
    )
    return cur.lastrowid


def list_wishlist(conn, trip_id):
    rows = conn.execute("""
        SELECT w.*, u.display_name AS added_by_name
        FROM wishlist w
        LEFT JOIN users u ON u.id = w.added_by
        WHERE w.trip_id = ?
        ORDER BY w.created_at ASC
    """, (trip_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_wishlist(conn, item_id, user_id=None, role=None):
    conn.execute("DELETE FROM wishlist WHERE id=?", (item_id,))


def add_itinerary(conn, trip_id, day_date, start_time, end_time, title, location, address, description, url, image_url, created_by):
    cur = conn.execute("""
        INSERT INTO itinerary (trip_id, day_date, start_time, end_time, title, location, address, description, url, image_url, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (trip_id, day_date, start_time, end_time, title, location, address, description, url, image_url, created_by))
    return cur.lastrowid


def list_itinerary(conn, trip_id):
    rows = conn.execute("""
        SELECT i.*, u.display_name AS created_by_name
        FROM itinerary i
        LEFT JOIN users u ON u.id = i.created_by
        WHERE i.trip_id = ?
        ORDER BY i.day_date ASC, i.start_time ASC
    """, (trip_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_itinerary(conn, item_id):
    conn.execute("DELETE FROM itinerary WHERE id=?", (item_id,))


def add_hotel(conn, trip_id, name, address, check_in, check_out, room_numbers, booked_by, contact_phone, notes, url):
    cur = conn.execute("""
        INSERT INTO hotels (trip_id, name, address, check_in, check_out, room_numbers, booked_by, contact_phone, notes, url)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (trip_id, name, address, check_in, check_out, room_numbers, booked_by, contact_phone, notes, url))
    return cur.lastrowid


def list_hotels(conn, trip_id):
    rows = conn.execute("""
        SELECT h.*, u.display_name AS booked_by_name
        FROM hotels h
        LEFT JOIN users u ON u.id = h.booked_by
        WHERE h.trip_id = ?
        ORDER BY h.check_in ASC
    """, (trip_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_hotel(conn, hotel_id):
    conn.execute("DELETE FROM hotels WHERE id=?", (hotel_id,))


def add_meeting(conn, trip_id, meet_time, location, address, notes, created_by):
    cur = conn.execute("""
        INSERT INTO meeting_points (trip_id, meet_time, location, address, notes, created_by)
        VALUES (?,?,?,?,?,?)
    """, (trip_id, meet_time, location, address, notes, created_by))
    return cur.lastrowid


def list_meetings(conn, trip_id):
    rows = conn.execute("""
        SELECT m.*, u.display_name AS created_by_name
        FROM meeting_points m
        LEFT JOIN users u ON u.id = m.created_by
        WHERE m.trip_id = ?
        ORDER BY m.meet_time ASC
    """, (trip_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_meeting(conn, meeting_id):
    conn.execute("DELETE FROM meeting_points WHERE id=?", (meeting_id,))


def add_expense(conn, trip_id, group_id, paid_by, amount, currency, description, expense_date):
    cur = conn.execute("""
        INSERT INTO expenses (trip_id, group_id, paid_by, amount, currency, description, expense_date)
        VALUES (?,?,?,?,?,?,?)
    """, (trip_id, group_id, paid_by, amount, currency, description, expense_date))
    return cur.lastrowid


def list_expenses(conn, trip_id):
    rows = conn.execute("""
        SELECT e.*,
               eg.name AS group_name,
               u.display_name AS paid_by_name
        FROM expenses e
        JOIN expense_groups eg ON eg.id = e.group_id
        JOIN users u ON u.id = e.paid_by
        WHERE e.trip_id = ?
        ORDER BY e.expense_date DESC, e.created_at DESC
    """, (trip_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_expense(conn, expense_id):
    conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))


def compute_balances(conn, trip_id):
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


# --- Travel guide helpers (SQLite) ---------------------------------------

def create_guide(conn, user_id, trip_id, title, destination, cover_image,
                  summary, start_date, end_date, tags):
    cur = conn.execute(
        "INSERT INTO travel_guides (user_id, trip_id, title, destination, cover_image, summary, start_date, end_date, tags) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, trip_id, title, destination, cover_image, summary,
         start_date, end_date, tags),
    )
    return cur.lastrowid


def get_guide(conn, guide_id):
    row = conn.execute("""
        SELECT g.*, u.display_name AS created_by_name, t.name AS trip_name
        FROM travel_guides g
        JOIN users u ON u.id = g.user_id
        LEFT JOIN trips t ON t.id = g.trip_id
        WHERE g.id=?
    """, (guide_id,)).fetchone()
    return dict(row) if row else None


def list_my_personal_guides(conn, user_id):
    rows = conn.execute("""
        SELECT g.*, u.display_name AS created_by_name
        FROM travel_guides g
        JOIN users u ON u.id = g.user_id
        WHERE g.user_id=? AND g.trip_id IS NULL
        ORDER BY g.updated_at DESC
    """, (user_id,)).fetchall()
    return [dict(r) for r in rows]


def list_my_all_guides(conn, user_id):
    rows = conn.execute("""
        SELECT g.*, u.display_name AS created_by_name, t.name AS trip_name
        FROM travel_guides g
        JOIN users u ON u.id = g.user_id
        LEFT JOIN trips t ON t.id = g.trip_id
        WHERE g.user_id=?
           OR (g.trip_id IS NOT NULL
               AND g.trip_id IN (SELECT trip_id FROM trip_members WHERE user_id=?))
        ORDER BY g.updated_at DESC
    """, (user_id, user_id)).fetchall()
    return [dict(r) for r in rows]


def list_trip_guides(conn, trip_id):
    rows = conn.execute("""
        SELECT g.*, u.display_name AS created_by_name
        FROM travel_guides g
        JOIN users u ON u.id = g.user_id
        WHERE g.trip_id=?
        ORDER BY g.updated_at DESC
    """, (trip_id,)).fetchall()
    return [dict(r) for r in rows]


def update_guide(conn, guide_id, **kwargs):
    allowed = ["title", "destination", "cover_image", "summary",
               "start_date", "end_date", "tags"]
    sets, vals = [], []
    for k in allowed:
        if k in kwargs:
            sets.append(f"{k}=?")
            vals.append(kwargs[k])
    if not sets:
        return
    sets.append("updated_at=CURRENT_TIMESTAMP")
    vals.append(guide_id)
    conn.execute(f"UPDATE travel_guides SET {', '.join(sets)} WHERE id=?", vals)


def delete_guide(conn, guide_id):
    conn.execute("DELETE FROM travel_guides WHERE id=?", (guide_id,))


def is_guide_editor(conn, guide_id, user_id):
    row = conn.execute(
        "SELECT user_id, trip_id FROM travel_guides WHERE id=?",
        (guide_id,),
    ).fetchone()
    if not row:
        return False
    if row["user_id"] == user_id:
        return True
    if row["trip_id"] is not None:
        m = conn.execute(
            "SELECT 1 FROM trip_members WHERE trip_id=? AND user_id=?",
            (row["trip_id"], user_id),
        ).fetchone()
        return m is not None
    return False


def get_guide_viewer(conn, guide_id, user_id):
    row = conn.execute(
        "SELECT user_id, trip_id FROM travel_guides WHERE id=?",
        (guide_id,),
    ).fetchone()
    if not row:
        return False
    if row["user_id"] == user_id:
        return True
    if row["trip_id"] is not None:
        m = conn.execute(
            "SELECT 1 FROM trip_members WHERE trip_id=? AND user_id=?",
            (row["trip_id"], user_id),
        ).fetchone()
        return m is not None
    return False


# --- Days ---

def create_guide_day(conn, guide_id, day_index, day_date, title, notes):
    """SQLite 没有 ON CONFLICT UPDATE，简化成 insert 即可（前端负责 day_index 唯一）。"""
    cur = conn.execute(
        "INSERT INTO travel_guide_days (guide_id, day_index, day_date, title, notes) "
        "VALUES (?,?,?,?,?)",
        (guide_id, day_index, day_date, title, notes),
    )
    conn.execute("UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                 (guide_id,))
    return cur.lastrowid


def list_guide_days(conn, guide_id):
    rows = conn.execute(
        "SELECT * FROM travel_guide_days WHERE guide_id=? ORDER BY day_index ASC",
        (guide_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_guide_day(conn, day_id):
    row = conn.execute("SELECT * FROM travel_guide_days WHERE id=?", (day_id,)).fetchone()
    return dict(row) if row else None


def update_guide_day(conn, day_id, guide_id=None, **kwargs):
    allowed = ["day_index", "day_date", "title", "notes"]
    sets, vals = [], []
    for k in allowed:
        if k in kwargs:
            sets.append(f"{k}=?")
            vals.append(kwargs[k])
    if not sets:
        return
    vals.append(day_id)
    conn.execute(f"UPDATE travel_guide_days SET {', '.join(sets)} WHERE id=?", vals)
    if guide_id is not None:
        conn.execute("UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (guide_id,))


def delete_guide_day(conn, day_id, guide_id=None):
    conn.execute("DELETE FROM travel_guide_days WHERE id=?", (day_id,))
    if guide_id is not None:
        conn.execute("UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (guide_id,))


# --- Items ---

def create_guide_item(conn, day_id, time, title, location, address,
                       description, image_url, url, category, sort_index=0):
    cur = conn.execute("""
        INSERT INTO travel_guide_items
          (day_id, sort_index, time, title, location, address, description, image_url, url, category)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (day_id, sort_index, time, title, location, address,
          description, image_url, url, category))
    conn.execute("""
        UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP
        WHERE id = (SELECT guide_id FROM travel_guide_days WHERE id=?)
    """, (day_id,))
    return cur.lastrowid


def list_guide_items(conn, day_id):
    rows = conn.execute(
        "SELECT * FROM travel_guide_items WHERE day_id=? ORDER BY sort_index ASC, time ASC",
        (day_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_guide_item(conn, item_id):
    row = conn.execute("SELECT * FROM travel_guide_items WHERE id=?", (item_id,)).fetchone()
    return dict(row) if row else None


def update_guide_item(conn, item_id, **kwargs):
    allowed = ["sort_index", "time", "title", "location", "address",
               "description", "image_url", "url", "category"]
    sets, vals = [], []
    for k in allowed:
        if k in kwargs:
            sets.append(f"{k}=?")
            vals.append(kwargs[k])
    if not sets:
        return
    vals.append(item_id)
    conn.execute(f"UPDATE travel_guide_items SET {', '.join(sets)} WHERE id=?", vals)
    conn.execute("""
        UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP
        WHERE id = (SELECT d.guide_id FROM travel_guide_items i
                    JOIN travel_guide_days d ON d.id=i.day_id
                    WHERE i.id=?)
    """, (item_id,))


def delete_guide_item(conn, item_id):
    row = conn.execute(
        "SELECT day_id FROM travel_guide_items WHERE id=?", (item_id,)
    ).fetchone()
    conn.execute("DELETE FROM travel_guide_items WHERE id=?", (item_id,))
    if row:
        conn.execute("""
            UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP
            WHERE id = (SELECT guide_id FROM travel_guide_days WHERE id=?)
        """, (row["day_id"],))


def get_guide_full(conn, guide_id):
    """一次性拉取攻略 + 所有 days + 所有 items，给前端用。"""
    guide = get_guide(conn, guide_id)
    if not guide:
        return None
    days = list_guide_days(conn, guide_id)
    days_full = []
    for d in days:
        items = list_guide_items(conn, d["id"])
        days_full.append({
            **d,
            "items": items,
        })
    guide["days"] = days_full
    return guide


# --- Share token helpers (SQLite) -----------------------------------------

def enable_share_token(conn, guide_id):
    row = conn.execute(
        "SELECT share_token FROM travel_guides WHERE id=?", (guide_id,)
    ).fetchone()
    if not row:
        return None
    token = row["share_token"] or ''.join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
    )
    conn.execute("UPDATE travel_guides SET share_token=? WHERE id=?", (token, guide_id))
    conn.execute("UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (guide_id,))
    return token


def disable_share_token(conn, guide_id):
    conn.execute("UPDATE travel_guides SET share_token=NULL WHERE id=?", (guide_id,))
    conn.execute("UPDATE travel_guides SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (guide_id,))


def get_guide_by_share_token(conn, token):
    row = conn.execute("""
        SELECT g.*, u.display_name AS created_by_name, t.name AS trip_name
        FROM travel_guides g
        JOIN users u ON u.id = g.user_id
        LEFT JOIN trips t ON t.id = g.trip_id
        WHERE g.share_token=?
    """, (token,)).fetchone()
    if not row:
        return None
    guide = dict(row)
    days = list_guide_days(conn, guide["id"])
    days_full = []
    for d in days:
        items = list_guide_items(conn, d["id"])
        days_full.append({**d, "items": items})
    guide["days"] = days_full
    return guide


if __name__ == "__main__":
    init_db()
    print(f"[db_sqlite] schema applied at {DB_PATH}")
