"""
Trip-share Flask backend.
REST API for multi-user trip planning, hotel/meeting/expense sharing.

Run:
    python server.py
"""
import os
import re
import secrets
import functools
from datetime import datetime, date
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

# Choose backend: Postgres on Render (DATABASE_URL set), SQLite for local dev.
if os.environ.get("DATABASE_URL"):
    import db as _db
else:
    print("[trip-share] DATABASE_URL not set — using local SQLite (db_sqlite.py).")
    print("[trip-share] For production, deploy to Render so DATABASE_URL is auto-injected.")
    import db_sqlite as _db

db = _db  # callers use db.*; alias so the rest of the file is unchanged

# --- App setup ------------------------------------------------------------

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app, supports_credentials=True)

# Simple in-memory token store: {token: user_id}. (Restart = logout everyone)
TOKENS = {}

def new_token(user_id):
    t = secrets.token_urlsafe(32)
    TOKENS[t] = user_id
    return t

def get_token_user_id():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        return TOKENS.get(token)
    return None

def require_auth(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        uid = get_token_user_id()
        if uid is None:
            return jsonify({"ok": False, "error": "未登录"}), 401
        request.user_id = uid
        return f(*args, **kwargs)
    return wrapped

def require_trip_member(f):
    @functools.wraps(f)
    @require_auth
    def wrapped(*args, **kwargs):
        trip_id = kwargs.get("trip_id")
        with db.get_db() as conn:
            if not db.is_trip_member(conn, trip_id, request.user_id):
                return jsonify({"ok": False, "error": "不是该旅行成员"}), 403
            request.trip_id = trip_id
            return f(*args, **kwargs)
    return wrapped

# --- Static / SPA ---------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "trip-share", "ts": datetime.now().isoformat()})

# --- Auth -----------------------------------------------------------------

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip() or username

    if not re.match(r"^[a-z0-9_]{3,20}$", username):
        return jsonify({"ok": False, "error": "用户名 3-20 位，只能用小写字母/数字/下划线"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "密码至少 6 位"}), 400

    with db.get_db() as conn:
        if db.get_user_by_username(conn, username):
            return jsonify({"ok": False, "error": "用户名已存在"}), 409
        uid = db.create_user(conn, username, generate_password_hash(password), display_name)

    token = new_token(uid)
    return jsonify({"ok": True, "token": token, "user": {"id": uid, "username": username, "display_name": display_name}})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""

    with db.get_db() as conn:
        user = db.get_user_by_username(conn, username)
        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"ok": False, "error": "用户名或密码错误"}), 401

    token = new_token(user["id"])
    return jsonify({
        "ok": True,
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"]
        }
    })

@app.route("/api/me", methods=["GET"])
@require_auth
def me():
    with db.get_db() as conn:
        user = db.get_user_by_id(conn, request.user_id)
        if not user:
            return jsonify({"ok": False, "error": "用户不存在"}), 404
        return jsonify({
            "ok": True,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"]
            }
        })

# --- Trips ----------------------------------------------------------------

@app.route("/api/trips", methods=["GET"])
@require_auth
def list_my_trips():
    with db.get_db() as conn:
        trips = db.list_user_trips(conn, request.user_id)
        return jsonify({"ok": True, "trips": trips})

@app.route("/api/trips", methods=["POST"])
@require_auth
def create_trip():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "旅行名称不能为空"}), 400
    description = data.get("description") or ""
    start_date = data.get("start_date") or ""
    end_date = data.get("end_date") or ""
    cover_image = data.get("cover_image") or ""

    with db.get_db() as conn:
        trip_id, invite = db.create_trip(
            conn, name, description, start_date, end_date, request.user_id, cover_image
        )
        trip = db.get_trip_by_id(conn, trip_id)
        return jsonify({
            "ok": True,
            "trip": trip,
            "invite_code": invite,
        })

@app.route("/api/trips/<int:trip_id>", methods=["GET"])
@require_auth
def get_trip(trip_id):
    with db.get_db() as conn:
        if not db.is_trip_member(conn, trip_id, request.user_id):
            return jsonify({"ok": False, "error": "不是该旅行成员"}), 403
        trip = db.get_trip_by_id(conn, trip_id)
        if not trip:
            return jsonify({"ok": False, "error": "旅行不存在"}), 404
        members = db.list_trip_members(conn, trip_id)
        return jsonify({"ok": True, "trip": trip, "members": members})

@app.route("/api/trips/join", methods=["POST"])
@require_auth
def join_trip():
    data = request.json or {}
    invite_code = (data.get("invite_code") or "").strip().upper()
    if not invite_code:
        return jsonify({"ok": False, "error": "邀请码不能为空"}), 400

    with db.get_db() as conn:
        trip = db.get_trip_by_invite(conn, invite_code)
        if not trip:
            return jsonify({"ok": False, "error": "邀请码无效"}), 404
        added = db.add_trip_member(conn, trip["id"], request.user_id)
        if not added:
            return jsonify({"ok": False, "error": "你已经在该旅行中"}), 409
        return jsonify({"ok": True, "trip_id": trip["id"], "trip_name": trip["name"]})

@app.route("/api/trips/<int:trip_id>/invite", methods=["POST"])
@require_auth
def regenerate_invite(trip_id):
    with db.get_db() as conn:
        if not db.is_trip_member(conn, trip_id, request.user_id):
            return jsonify({"ok": False, "error": "无权限"}), 403
        new_code = db.generate_invite_code()
        conn.execute("UPDATE trips SET invite_code=? WHERE id=?", (new_code, trip_id))
        return jsonify({"ok": True, "invite_code": new_code})

# --- Expense groups -------------------------------------------------------

@app.route("/api/trips/<int:trip_id>/expense-groups", methods=["GET"])
@require_trip_member
def list_groups(trip_id):
    with db.get_db() as conn:
        groups = db.list_expense_groups(conn, trip_id)
        # attach members
        for g in groups:
            g["members"] = db.list_group_members(conn, g["id"])
        return jsonify({"ok": True, "groups": groups})

@app.route("/api/trips/<int:trip_id>/expense-groups", methods=["POST"])
@require_trip_member
def add_group(trip_id):
    data = request.json or {}
    name = (data.get("name") or "").strip()
    member_ids = data.get("member_ids") or []
    if not name:
        return jsonify({"ok": False, "error": "群组名不能为空"}), 400

    with db.get_db() as conn:
        gid = db.create_expense_group(conn, trip_id, name)
        # 校验成员都是该旅行成员
        valid_member_ids = []
        for mid in member_ids:
            if db.is_trip_member(conn, trip_id, mid):
                valid_member_ids.append(mid)
        if not valid_member_ids:
            # 默认把 owner 加进去
            trip = db.get_trip_by_id(conn, trip_id)
            valid_member_ids = [trip["owner_id"]]
        db.set_group_members(conn, gid, valid_member_ids)
        group = db.get_expense_group(conn, gid)
        group["members"] = db.list_group_members(conn, gid)
        return jsonify({"ok": True, "group": group})

@app.route("/api/expense-groups/<int:group_id>/members", methods=["PUT"])
@require_auth
def update_group_members(group_id):
    data = request.json or {}
    member_ids = data.get("member_ids") or []
    with db.get_db() as conn:
        group = db.get_expense_group(conn, group_id)
        if not group:
            return jsonify({"ok": False, "error": "群组不存在"}), 404
        if not db.is_trip_member(conn, group["trip_id"], request.user_id):
            return jsonify({"ok": False, "error": "无权限"}), 403
        valid = []
        for mid in member_ids:
            if db.is_trip_member(conn, group["trip_id"], mid):
                valid.append(mid)
        db.set_group_members(conn, group_id, valid)
        members = db.list_group_members(conn, group_id)
        return jsonify({"ok": True, "members": members})

# --- Wishlist -------------------------------------------------------------

@app.route("/api/trips/<int:trip_id>/wishlist", methods=["GET"])
@require_trip_member
def list_wishlist(trip_id):
    with db.get_db() as conn:
        items = db.list_wishlist(conn, trip_id)
        return jsonify({"ok": True, "items": items})

@app.route("/api/trips/<int:trip_id>/wishlist", methods=["POST"])
@require_trip_member
def add_wishlist(trip_id):
    data = request.json or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "标题不能为空"}), 400
    with db.get_db() as conn:
        wid = db.add_wishlist(
            conn, trip_id, title,
            data.get("url") or "",
            data.get("image_url") or "",
            data.get("description") or "",
            data.get("category") or "其他",
            request.user_id
        )
        # 回填
        rows = conn.execute("SELECT * FROM wishlist WHERE id=?", (wid,)).fetchone()
        item = dict(rows)
        return jsonify({"ok": True, "item": item})

@app.route("/api/wishlist/<int:item_id>", methods=["DELETE"])
@require_auth
def delete_wishlist(item_id):
    with db.get_db() as conn:
        # 找到 trip_id 校验权限
        row = conn.execute("SELECT trip_id FROM wishlist WHERE id=?", (item_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "项目不存在"}), 404
        if not db.is_trip_member(conn, row["trip_id"], request.user_id):
            return jsonify({"ok": False, "error": "无权限"}), 403
        db.delete_wishlist(conn, item_id)
        return jsonify({"ok": True})

# --- Itinerary ------------------------------------------------------------

@app.route("/api/trips/<int:trip_id>/itinerary", methods=["GET"])
@require_trip_member
def list_itinerary(trip_id):
    with db.get_db() as conn:
        items = db.list_itinerary(conn, trip_id)
        return jsonify({"ok": True, "items": items})

@app.route("/api/trips/<int:trip_id>/itinerary", methods=["POST"])
@require_trip_member
def add_itinerary(trip_id):
    data = request.json or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "标题不能为空"}), 400
    with db.get_db() as conn:
        iid = db.add_itinerary(
            conn, trip_id,
            data.get("day_date") or "",
            data.get("start_time") or "",
            data.get("end_time") or "",
            title,
            data.get("location") or "",
            data.get("address") or "",
            data.get("description") or "",
            data.get("url") or "",
            data.get("image_url") or "",
            request.user_id
        )
        row = conn.execute("SELECT * FROM itinerary WHERE id=?", (iid,)).fetchone()
        item = dict(row)
        return jsonify({"ok": True, "item": item})

@app.route("/api/itinerary/<int:item_id>", methods=["DELETE"])
@require_auth
def delete_itinerary(item_id):
    with db.get_db() as conn:
        row = conn.execute("SELECT trip_id FROM itinerary WHERE id=?", (item_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "项目不存在"}), 404
        if not db.is_trip_member(conn, row["trip_id"], request.user_id):
            return jsonify({"ok": False, "error": "无权限"}), 403
        db.delete_itinerary(conn, item_id)
        return jsonify({"ok": True})

# --- Hotels ---------------------------------------------------------------

@app.route("/api/trips/<int:trip_id>/hotels", methods=["GET"])
@require_trip_member
def list_hotels(trip_id):
    with db.get_db() as conn:
        items = db.list_hotels(conn, trip_id)
        return jsonify({"ok": True, "items": items})

@app.route("/api/trips/<int:trip_id>/hotels", methods=["POST"])
@require_trip_member
def add_hotel(trip_id):
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "酒店名称不能为空"}), 400
    with db.get_db() as conn:
        hid = db.add_hotel(
            conn, trip_id, name,
            data.get("address") or "",
            data.get("check_in") or "",
            data.get("check_out") or "",
            data.get("room_numbers") or "",
            data.get("booked_by") or None,
            data.get("contact_phone") or "",
            data.get("notes") or "",
            data.get("url") or ""
        )
        row = conn.execute("SELECT * FROM hotels WHERE id=?", (hid,)).fetchone()
        item = dict(row)
        return jsonify({"ok": True, "item": item})

@app.route("/api/hotels/<int:hotel_id>", methods=["DELETE"])
@require_auth
def delete_hotel(hotel_id):
    with db.get_db() as conn:
        row = conn.execute("SELECT trip_id FROM hotels WHERE id=?", (hotel_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "酒店不存在"}), 404
        if not db.is_trip_member(conn, row["trip_id"], request.user_id):
            return jsonify({"ok": False, "error": "无权限"}), 403
        db.delete_hotel(conn, hotel_id)
        return jsonify({"ok": True})

# --- Meeting points -------------------------------------------------------

@app.route("/api/trips/<int:trip_id>/meetings", methods=["GET"])
@require_trip_member
def list_meetings(trip_id):
    with db.get_db() as conn:
        items = db.list_meetings(conn, trip_id)
        return jsonify({"ok": True, "items": items})

@app.route("/api/trips/<int:trip_id>/meetings", methods=["POST"])
@require_trip_member
def add_meeting(trip_id):
    data = request.json or {}
    location = (data.get("location") or "").strip()
    if not location:
        return jsonify({"ok": False, "error": "集合地点不能为空"}), 400
    with db.get_db() as conn:
        mid = db.add_meeting(
            conn, trip_id,
            data.get("meet_time") or "",
            location,
            data.get("address") or "",
            data.get("notes") or "",
            request.user_id
        )
        row = conn.execute("SELECT * FROM meeting_points WHERE id=?", (mid,)).fetchone()
        item = dict(row)
        return jsonify({"ok": True, "item": item})

@app.route("/api/meetings/<int:meeting_id>", methods=["DELETE"])
@require_auth
def delete_meeting(meeting_id):
    with db.get_db() as conn:
        row = conn.execute("SELECT trip_id FROM meeting_points WHERE id=?", (meeting_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "集合点不存在"}), 404
        if not db.is_trip_member(conn, row["trip_id"], request.user_id):
            return jsonify({"ok": False, "error": "无权限"}), 403
        db.delete_meeting(conn, meeting_id)
        return jsonify({"ok": True})

# --- Expenses -------------------------------------------------------------

@app.route("/api/trips/<int:trip_id>/expenses", methods=["GET"])
@require_trip_member
def list_expenses(trip_id):
    with db.get_db() as conn:
        items = db.list_expenses(conn, trip_id)
        balances = db.compute_balances(conn, trip_id)
        return jsonify({"ok": True, "items": items, "balances": balances})

@app.route("/api/trips/<int:trip_id>/expenses", methods=["POST"])
@require_trip_member
def add_expense(trip_id):
    data = request.json or {}
    group_id = data.get("group_id")
    amount = data.get("amount")
    paid_by = data.get("paid_by") or request.user_id

    if not group_id or not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"ok": False, "error": "请填写群组和金额"}), 400

    with db.get_db() as conn:
        # 校验 group 属于 trip
        group = db.get_expense_group(conn, group_id)
        if not group or group["trip_id"] != trip_id:
            return jsonify({"ok": False, "error": "群组无效"}), 400
        # 校验 paid_by 是旅行成员
        if not db.is_trip_member(conn, trip_id, paid_by):
            return jsonify({"ok": False, "error": "付款人不是旅行成员"}), 400

        eid = db.add_expense(
            conn, trip_id, group_id, paid_by,
            float(amount),
            data.get("currency") or "CNY",
            data.get("description") or "",
            data.get("expense_date") or date.today().isoformat()
        )
        row = conn.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone()
        item = dict(row)
        return jsonify({"ok": True, "item": item})

@app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
@require_auth
def delete_expense(expense_id):
    with db.get_db() as conn:
        row = conn.execute("SELECT trip_id FROM expenses WHERE id=?", (expense_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "费用不存在"}), 404
        if not db.is_trip_member(conn, row["trip_id"], request.user_id):
            return jsonify({"ok": False, "error": "无权限"}), 403
        db.delete_expense(conn, expense_id)
        return jsonify({"ok": True})

@app.route("/api/trips/<int:trip_id>/balances", methods=["GET"])
@require_trip_member
def get_balances(trip_id):
    with db.get_db() as conn:
        balances = db.compute_balances(conn, trip_id)
        return jsonify({"ok": True, "balances": balances})

# --- Entry ----------------------------------------------------------------

if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    # Use waitress on Windows (gunicorn needs fcntl which is Unix-only).
    # On Linux/Render, waitress still works fine.
    try:
        from waitress import serve
        print(f"[trip-share] (waitress) starting on {host}:{port}")
        serve(app, host=host, port=port, threads=4)
    except ImportError:
        print(f"[trip-share] (flask dev) starting on {host}:{port}")
        app.run(host=host, port=port, debug=False)
