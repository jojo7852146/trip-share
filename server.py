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

# Deferred DB init: on Render the Postgres DNS may not be ready when
# gunicorn imports wsgi.py, so we initialize tables on the first request.
# /health and /_debug/env must NEVER trigger DB init — the health check
# needs to return instantly or Render keeps the deploy "Deploying".
_db_initialized = False

def _skip_db_path():
    path = request.path
    return path in ("/health", "/_debug/env") or path.startswith("/static") or path == "/"

@app.before_request
def _ensure_db_tables():
    global _db_initialized
    if _db_initialized:
        return
    if _skip_db_path():
        return
    try:
        db.init_db()
        _db_initialized = True
        app.logger.info("Database tables initialized.")
    except Exception:
        # Don't crash the request; next request will retry.
        app.logger.warning("DB init deferred (will retry on next request)", exc_info=True)


# Token persisted in DB so it survives server restarts (Render free plan
# spins down after idle, clearing in-memory state).
def new_token(user_id):
    t = secrets.token_urlsafe(32)
    with db.get_db() as conn:
        db.set_user_token(conn, user_id, t)
    return t

def get_token_user_id():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        with db.get_db() as conn:
            user = db.get_user_by_token(conn, token)
            if user:
                return user["id"]
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


@app.route("/_debug/env")
def debug_env():
    """Debug endpoint to verify env vars and DB connectivity.

    Must return FAST (<=5s): uses a single connection attempt with a short
    connect_timeout and NO retries, otherwise this page spins for minutes
    and the user thinks the site is down.
    """
    url = os.environ.get("DATABASE_URL", "")
    # Parse host correctly (strip port and database name)
    host = "(missing)"
    dbname = "(missing)"
    if url and "@" in url and "://" in url:
        authority = url.split("@")[1]
        # authority = host[:port]/dbname
        host = authority.split(":")[0].split("/")[0]
        if "/" in authority:
            dbname = authority.split("/")[1].split("?")[0]
    result = {
        "app_version": "2026-08-21-6fbe249",
        "database_url_set": bool(url),
        "database_url_prefix": url.split("://")[0] if "://" in url else "(invalid format)",
        "database_url_host": host,
        "database_url_dbname": dbname,
        "secret_key_set": bool(os.environ.get("SECRET_KEY")),
        "python_version": os.sys.version,
    }
    # Test DNS resolution of the host separately from the full connect
    try:
        import socket
        infos = socket.getaddrinfo(host, None)
        result["dns_resolve"] = "OK"
        result["dns_resolved_to"] = [i[4][0] for i in infos][:3]
    except Exception as e:
        result["dns_resolve"] = "FAILED"
        result["dns_error"] = str(e)
    # Fast DB probe: single attempt, 5s connect timeout, no retries.
    # Uses the same sslmode=require as db._connect().
    try:
        import psycopg
        probe_url = url
        if probe_url.startswith("postgres://"):
            probe_url = probe_url.replace("postgres://", "postgresql://", 1)
        conn = psycopg.connect(probe_url, connect_timeout=5, sslmode="require")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
                result["db_connect"] = "OK"
                result["db_query"] = {"ok": row[0]}
        finally:
            conn.close()
    except Exception as e:
        result["db_connect"] = "FAILED"
        result["db_error"] = f"{type(e).__name__}: {e}"
    return jsonify(result)

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

@app.route("/api/trips/<int:trip_id>", methods=["DELETE"])
@require_auth
def delete_trip(trip_id):
    """删除旅行（仅创建者可删）。所有子数据靠 ON DELETE CASCADE 自动清理。"""
    with db.get_db() as conn:
        trip = db.get_trip_by_id(conn, trip_id)
        if not trip:
            return jsonify({"ok": False, "error": "旅行不存在"}), 404
        if trip["owner_id"] != request.user_id:
            return jsonify({"ok": False, "error": "只有创建者才能删除该旅行"}), 403
        with conn.cursor() as cur:
            cur.execute("DELETE FROM trips WHERE id=%s", (trip_id,))
        return jsonify({"ok": True, "message": "旅行已删除"})

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
    # 允许用户只填说明/分类，title 为空时自动兜底
    if not title:
        title = (data.get("description") or "").strip()[:20] or (data.get("category") or "").strip() or "未命名"
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
    # title 兜底：用说明或地点名或"未命名"
    if not title:
        title = (data.get("description") or "").strip()[:20] or (data.get("location") or "").strip() or "未命名"
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

# --- Travel guides (个人 + trip 内协作) ---------------------------------
# 设计要点：
#   - 个人攻略 (trip_id IS NULL) 只 owner 能改能看
#   - trip 攻略   (trip_id 非空)    该 trip 的成员都能改能看
#   - GET /api/guides                  → 我的所有可见攻略（个人 + trip）
#   - GET /api/guides/<id>            → 攻略详情（含 days + items）
#   - POST /api/trips/<tid>/guides    → 在某个 trip 下新建攻略（trip 成员才能）
#   - POST /api/guides                → 新建个人攻略（body 不带 trip_id）

@app.route("/api/guides", methods=["GET"])
@require_auth
def list_my_guides():
    with db.get_db() as conn:
        guides = db.list_my_all_guides(conn, request.user_id)
        # 把每条加上天数 + 条目数
        for g in guides:
            days = db.list_guide_days(conn, g["id"])
            item_count = 0
            for d in days:
                item_count += len(db.list_guide_items(conn, d["id"]))
            g["day_count"] = len(days)
            g["item_count"] = item_count
        return jsonify({"ok": True, "guides": guides})


@app.route("/api/guides/<int:guide_id>", methods=["GET"])
@require_auth
def get_one_guide(guide_id):
    with db.get_db() as conn:
        if not db.get_guide_viewer(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "没有权限查看该攻略"}), 403
        guide = db.get_guide_full(conn, guide_id)
        # 标记当前用户是否能编辑（前端用于隐藏/显示编辑按钮）
        guide["can_edit"] = db.is_guide_editor(conn, guide_id, request.user_id)
        return jsonify({"ok": True, "guide": guide})


@app.route("/api/guides", methods=["POST"])
@require_auth
def create_personal_guide():
    """创建个人攻略 (body 不带 trip_id) — 任何登录用户都能建。"""
    return _create_guide_internal(trip_id=None)


@app.route("/api/trips/<int:trip_id>/guides", methods=["GET"])
@require_trip_member
def list_trip_guides(trip_id):
    with db.get_db() as conn:
        guides = db.list_trip_guides(conn, trip_id)
        for g in guides:
            days = db.list_guide_days(conn, g["id"])
            g["day_count"] = len(days)
        return jsonify({"ok": True, "guides": guides})


@app.route("/api/trips/<int:trip_id>/guides", methods=["POST"])
@require_trip_member
def create_trip_guide(trip_id):
    return _create_guide_internal(trip_id=trip_id)


def _create_guide_internal(trip_id):
    data = request.json or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "攻略标题不能为空"}), 400
    with db.get_db() as conn:
        gid = db.create_guide(
            conn, request.user_id, trip_id, title,
            (data.get("destination") or "").strip(),
            data.get("cover_image") or "",
            data.get("summary") or "",
            data.get("start_date") or "",
            data.get("end_date") or "",
            data.get("tags") or "",
        )
        guide = db.get_guide_full(conn, gid)
        guide["can_edit"] = db.is_guide_editor(conn, gid, request.user_id)
        return jsonify({"ok": True, "guide": guide})


@app.route("/api/guides/<int:guide_id>", methods=["PUT"])
@require_auth
def update_guide_endpoint(guide_id):
    with db.get_db() as conn:
        if not db.is_guide_editor(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "无权编辑该攻略"}), 403
        data = request.json or {}
        kwargs = {}
        for k in ["title", "destination", "cover_image", "summary",
                  "start_date", "end_date", "tags"]:
            if k in data:
                kwargs[k] = data[k] or ""
        # title 不能为空
        if "title" in kwargs and not kwargs["title"].strip():
            return jsonify({"ok": False, "error": "标题不能为空"}), 400
        db.update_guide(conn, guide_id, **kwargs)
        guide = db.get_guide_full(conn, guide_id)
        return jsonify({"ok": True, "guide": guide})


@app.route("/api/guides/<int:guide_id>", methods=["DELETE"])
@require_auth
def delete_guide_endpoint(guide_id):
    with db.get_db() as conn:
        if not db.is_guide_editor(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "无权删除该攻略"}), 403
        db.delete_guide(conn, guide_id)
        return jsonify({"ok": True})


# --- Days ---

@app.route("/api/guides/<int:guide_id>/days", methods=["POST"])
@require_auth
def add_guide_day(guide_id):
    with db.get_db() as conn:
        if not db.is_guide_editor(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "无权编辑该攻略"}), 403
        data = request.json or {}
        day_index = int(data.get("day_index") or 1)
        day = db.create_guide_day(
            conn, guide_id, day_index,
            data.get("day_date") or "",
            data.get("title") or "",
            data.get("notes") or "",
        )
        return jsonify({"ok": True, "day": db.get_guide_day(conn, day)})


@app.route("/api/guides/<int:guide_id>/days/<int:day_id>", methods=["PUT"])
@require_auth
def update_guide_day_endpoint(guide_id, day_id):
    with db.get_db() as conn:
        if not db.is_guide_editor(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "无权编辑该攻略"}), 403
        data = request.json or {}
        kwargs = {}
        for k in ["day_index", "day_date", "title", "notes"]:
            if k in data:
                kwargs[k] = data[k] or ""
        if "day_index" in kwargs:
            kwargs["day_index"] = int(kwargs["day_index"])
        db.update_guide_day(conn, day_id, guide_id=guide_id, **kwargs)
        return jsonify({"ok": True, "day": db.get_guide_day(conn, day_id)})


@app.route("/api/guides/<int:guide_id>/days/<int:day_id>", methods=["DELETE"])
@require_auth
def delete_guide_day_endpoint(guide_id, day_id):
    with db.get_db() as conn:
        if not db.is_guide_editor(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "无权编辑该攻略"}), 403
        db.delete_guide_day(conn, day_id, guide_id=guide_id)
        return jsonify({"ok": True})


# --- Items ---

@app.route("/api/guides/<int:guide_id>/days/<int:day_id>/items", methods=["POST"])
@require_auth
def add_guide_item(guide_id, day_id):
    with db.get_db() as conn:
        if not db.is_guide_editor(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "无权编辑该攻略"}), 403
        data = request.json or {}
        title = (data.get("title") or "").strip()
        # title 兜底：用说明或地点名或分类或"未命名"
        if not title:
            title = (data.get("description") or "").strip()[:20] or (data.get("location") or "").strip() or (data.get("category") or "").strip() or "未命名"
        iid = db.create_guide_item(
            conn, day_id,
            data.get("time") or "",
            title,
            data.get("location") or "",
            data.get("address") or "",
            data.get("description") or "",
            data.get("image_url") or "",
            data.get("url") or "",
            data.get("category") or "",
            int(data.get("sort_index") or 0),
        )
        return jsonify({"ok": True, "item": db.get_guide_item(conn, iid)})


@app.route("/api/guides/<int:guide_id>/days/<int:day_id>/items/<int:item_id>", methods=["PUT"])
@require_auth
def update_guide_item_endpoint(guide_id, day_id, item_id):
    with db.get_db() as conn:
        if not db.is_guide_editor(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "无权编辑该攻略"}), 403
        data = request.json or {}
        kwargs = {}
        for k in ["time", "title", "location", "address", "description",
                  "image_url", "url", "category"]:
            if k in data:
                kwargs[k] = data[k] or ""
        if "sort_index" in data:
            kwargs["sort_index"] = int(data["sort_index"])
        db.update_guide_item(conn, item_id, **kwargs)
        return jsonify({"ok": True, "item": db.get_guide_item(conn, item_id)})


@app.route("/api/guides/<int:guide_id>/days/<int:day_id>/items/<int:item_id>", methods=["DELETE"])
@require_auth
def delete_guide_item_endpoint(guide_id, day_id, item_id):
    with db.get_db() as conn:
        if not db.is_guide_editor(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "无权编辑该攻略"}), 403
        db.delete_guide_item(conn, item_id)
        return jsonify({"ok": True})


# --- Share token (公开链接分享) ------------------------------------------

@app.route("/api/guides/<int:guide_id>/share", methods=["POST"])
@require_auth
def enable_share(guide_id):
    with db.get_db() as conn:
        if not db.is_guide_editor(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "无权分享该攻略"}), 403
        token = db.enable_share_token(conn, guide_id)
        return jsonify({"ok": True, "share_token": token})


@app.route("/api/guides/<int:guide_id>/share", methods=["DELETE"])
@require_auth
def disable_share(guide_id):
    with db.get_db() as conn:
        if not db.is_guide_editor(conn, guide_id, request.user_id):
            return jsonify({"ok": False, "error": "无权操作该攻略"}), 403
        db.disable_share_token(conn, guide_id)
        return jsonify({"ok": True})


# --- Public (no-auth) read-only endpoint for share token -----------------

@app.route("/api/public/guide/<token>", methods=["GET"])
def public_get_guide(token):
    """任何人凭 token 都可以只看，不能改。"""
    if not token or len(token) > 64:
        return jsonify({"ok": False, "error": "无效的分享链接"}), 404
    with db.get_db() as conn:
        guide = db.get_guide_by_share_token(conn, token)
        if not guide:
            return jsonify({"ok": False, "error": "分享链接已失效"}), 404
        # 不返回 user_id 等敏感字段
        guide.pop("user_id", None)
        return jsonify({"ok": True, "guide": guide})


# --- Static: 公开分享页面（独立 HTML，不用登录即可查看） -------------------

@app.route("/p/<token>", methods=["GET"])
def public_share_page(token):
    return send_from_directory("static", "share.html")


# --- Upload: 图片直传 -----------------------------------------------------
# 前端攻略条目（item）的封面/配图可以选 URL 或本地上传
# 上传后存到 static/uploads/，返回 /uploads/xxx.xxx 相对路径
# 上传只需登录（任意用户都可以），不做 owner 校验——图片本身不敏感

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "uploads")
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_BYTES = 10 * 1024 * 1024  # 10MB

@app.route("/api/upload", methods=["POST"])
@require_auth
def upload_image():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "没收到文件，请用 'file' 字段"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "文件名为空"}), 400

    # 安全：扩展名白名单 + 大小限制
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        return jsonify({"ok": False, "error": f"只支持 {', '.join(sorted(ALLOWED_EXTS))}"}), 400
    # 读 bytes 检查大小（避免内存打爆）
    data = f.read()
    if len(data) > MAX_BYTES:
        return jsonify({"ok": False, "error": f"文件太大（>{MAX_BYTES // 1024 // 1024}MB）"}), 400
    if len(data) == 0:
        return jsonify({"ok": False, "error": "空文件"}), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = secrets.token_urlsafe(16) + ext
    with open(os.path.join(UPLOAD_DIR, name), "wb") as fp:
        fp.write(data)
    return jsonify({"ok": True, "url": f"/uploads/{name}", "bytes": len(data)})


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
