"""图书馆管理系统 —— Flask 主程序。"""
import datetime
import functools

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, abort)
from werkzeug.security import generate_password_hash, check_password_hash

import db
import base64
import io
import qrcode   # 放到文件顶部的 import 区


app = Flask(__name__)
app.config["SECRET_KEY"] = "改成你自己的随机字符串abc123xyz"

# ---------- 业务参数 ----------
CHECKIN_WINDOW_MINUTES = 60   # 预约后 1 小时内须签到
BAN_HOURS = 24                # 违约封禁 1 天
POINTS_PER_CHECKIN = 1        # 签到 +1 分
WEEK_TITLE = "每周自习之星"
MONTH_TITLE = "每月自习之星"
YEAR_TITLE = "年度自习之星"


# ============ 通用工具 ============

def current_user():
    """从 session 取当前登录用户。"""
    uid = session.get("uid")
    if not uid:
        return None
    return db.query_one("SELECT * FROM users WHERE id=%s", (uid,))


def login_required(view):
    """没登录就跳登录页。"""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            flash("请先登录", "warn")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    """非管理员直接 403。保护图书增删改。"""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def reader_required(view):
    """只有读者能借阅/归还；管理员只管书。"""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            flash("请先登录后再借阅", "warn")
            return redirect(url_for("login"))
        user = current_user()
        if user["role"] != "reader":
            flash("仅读者账号可借阅图书，管理员请使用图书管理功能", "warn")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_user():
    """让所有模板都能用 me 变量。"""
    return {"me": current_user()}


# ============ 认证 ============

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        if not username or not password:
            flash("用户名和密码不能为空", "error")
        elif len(username) > 50 or len(password) < 6:
            flash("用户名最长50字符，密码至少6位", "error")
        elif password != password2:
            flash("两次输入的密码不一致", "error")
        elif db.query_one("SELECT id FROM users WHERE username=%s", (username,)):
            flash("该用户名已被注册", "error")
        else:
            uid = db.execute(
                "INSERT INTO users (username, password_hash, role) "
                "VALUES (%s, %s, 'reader')",
                (username, generate_password_hash(password)),
            )
            session["uid"] = uid
            flash("注册成功，欢迎！", "ok")
            return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.query_one("SELECT * FROM users WHERE username=%s", (username,))
        if user and check_password_hash(user["password_hash"], password):
            session["uid"] = user["id"]
            flash(f"欢迎回来，{user['username']}！", "ok")
            return redirect(url_for("index"))
        flash("用户名或密码错误", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("已退出登录", "ok")
    return redirect(url_for("login"))

# ============ 图书：浏览 / 搜索 / 借阅 / 归还 ============

@app.route("/")
def index():
    kw = request.args.get("kw", "").strip()
    if kw:
        like = f"%{kw}%"
        books = db.query_all(
            "SELECT * FROM books WHERE title LIKE %s OR author LIKE %s "
            "OR publisher LIKE %s ORDER BY id DESC", (like, like, like))
    else:
        books = db.query_all("SELECT * FROM books ORDER BY id DESC")
    my_borrowed_ids = set()
    if session.get("uid"):
        rows = db.query_all(
            "SELECT book_id FROM borrows WHERE user_id=%s AND status='borrowed'",
            (session["uid"],))
        my_borrowed_ids = {r["book_id"] for r in rows}
    return render_template("index.html", books=books, kw=kw,
                           my_borrowed_ids=my_borrowed_ids)


@app.route("/borrow/<int:book_id>", methods=["POST"])
@reader_required
def borrow(book_id):
    book = db.query_one("SELECT * FROM books WHERE id=%s", (book_id,))
    if not book:
        abort(404)
    if book["remaining"] <= 0:
        flash("该书已无可借余量", "error")
        return redirect(url_for("index"))
    already = db.query_one(
        "SELECT id FROM borrows WHERE user_id=%s AND book_id=%s AND status='borrowed'",
        (session["uid"], book_id))
    if already:
        flash("你已借阅此书，请先归还", "warn")
        return redirect(url_for("index"))
    # 原子扣减：WHERE 带 remaining>0，并发下也不会超借
    db.execute(
        "UPDATE books SET remaining = remaining - 1 WHERE id=%s AND remaining > 0",
        (book_id,))
    db.execute("INSERT INTO borrows (user_id, book_id) VALUES (%s, %s)",
               (session["uid"], book_id))
    flash(f"借阅成功：《{book['title']}》", "ok")
    return redirect(url_for("index"))


@app.route("/return/<int:borrow_id>", methods=["POST"])
@reader_required
def return_book(borrow_id):
    rec = db.query_one(
        "SELECT b.*, bk.title FROM borrows b JOIN books bk ON bk.id=b.book_id "
        "WHERE b.id=%s AND b.user_id=%s AND b.status='borrowed'",
        (borrow_id, session["uid"]))
    if not rec:
        flash("借阅记录不存在", "error")
        return redirect(url_for("my_borrows"))
    db.execute("UPDATE borrows SET status='returned', return_time=NOW() WHERE id=%s",
               (borrow_id,))
    db.execute("UPDATE books SET remaining = remaining + 1 WHERE id=%s",
               (rec["book_id"],))
    flash(f"已归还：《{rec['title']}》", "ok")
    return redirect(url_for("my_borrows"))


@app.route("/my/borrows")
@login_required
def my_borrows():
    rows = db.query_all(
        "SELECT b.*, bk.title, bk.author, bk.location FROM borrows b "
        "JOIN books bk ON bk.id = b.book_id WHERE b.user_id=%s ORDER BY b.id DESC",
        (session["uid"],))
    return render_template("my_borrows.html", rows=rows)


# ============ 图书管理（仅管理员） ============

@app.route("/admin/books")
@admin_required
def admin_books():
    books = db.query_all("SELECT * FROM books ORDER BY id DESC")
    return render_template("admin_books.html", books=books)


@app.route("/admin/books/new", methods=["GET", "POST"])
@admin_required
def admin_book_new():
    if request.method == "POST":
        return save_book(None)
    return render_template("book_form.html", book=None)


@app.route("/admin/books/<int:book_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_book_edit(book_id):
    book = db.query_one("SELECT * FROM books WHERE id=%s", (book_id,))
    if not book:
        abort(404)
    if request.method == "POST":
        return save_book(book)
    return render_template("book_form.html", book=book)


def save_book(book):
    """新增(book=None)或更新图书，含表单校验。"""
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    publisher = request.form.get("publisher", "").strip()
    location = request.form.get("location", "").strip()
    try:
        total = int(request.form.get("total", "1"))
        remaining = int(request.form.get("remaining", str(total)))
    except ValueError:
        flash("数量和余量必须是整数", "error")
        return render_template("book_form.html", book=book), 400
    if not all([title, author, publisher, location]):
        flash("请填写完整信息", "error")
        return render_template("book_form.html", book=book), 400
    if total < 0 or remaining < 0 or remaining > total:
        flash("余量必须在 0 与总数量之间", "error")
        return render_template("book_form.html", book=book), 400

    if book is None:
        db.execute(
            "INSERT INTO books (title, author, publisher, total, remaining, location) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (title, author, publisher, total, remaining, location))
        flash("图书录入成功", "ok")
    else:
        db.execute(
            "UPDATE books SET title=%s, author=%s, publisher=%s, total=%s, "
            "remaining=%s, location=%s WHERE id=%s",
            (title, author, publisher, total, remaining, location, book["id"]))
        flash("图书信息已更新", "ok")
    return redirect(url_for("admin_books"))


@app.route("/admin/books/<int:book_id>/delete", methods=["POST"])
@admin_required
def admin_book_delete(book_id):
    borrowed = db.query_one(
        "SELECT COUNT(*) c FROM borrows WHERE book_id=%s AND status='borrowed'",
        (book_id,))
    if borrowed["c"] > 0:
        flash("该书仍有未归还的借阅记录，不能删除", "error")
    else:
        db.execute("DELETE FROM borrows WHERE book_id=%s", (book_id,))
        db.execute("DELETE FROM books WHERE id=%s", (book_id,))
        flash("图书已删除", "ok")
    return redirect(url_for("admin_books"))

# ============ 座位预约 ============

@app.before_request
def sweep_expired_reservations():
    """每次请求前：把超时未签到的预约标记违约，并封禁用户1天。

    等价于定时任务，不需要额外开线程。
    """
    expired = db.query_all(
        "SELECT id, user_id, expire_time FROM seat_reservations "
        "WHERE status='reserved' AND expire_time < NOW()")
    for r in expired:
        db.execute("UPDATE seat_reservations SET status='expired' WHERE id=%s",
                   (r["id"],))
        db.execute(
            "UPDATE users SET banned_until = "
            "GREATEST(COALESCE(banned_until, %s), DATE_ADD(%s, INTERVAL %s HOUR)) "
            "WHERE id=%s",
            (r["expire_time"], r["expire_time"], BAN_HOURS, r["user_id"]))


def active_reservation_of(user_id):
    """用户进行中的预约（待签到 或 已签到未离开）。"""
    return db.query_one(
        "SELECT sr.*, s.seat_no, s.area, s.seat_code FROM seat_reservations sr "
        "JOIN seats s ON s.id = sr.seat_id "
        "WHERE sr.user_id=%s AND (sr.status='checked_in' OR "
        "      (sr.status='reserved' AND sr.expire_time > NOW())) "
        "ORDER BY sr.id DESC LIMIT 1", (user_id,))


@app.route("/seats")
@login_required
def seats():
    user = current_user()
    my_active = active_reservation_of(user["id"])
    rows = db.query_all(
        "SELECT s.*, "
        "  (SELECT sr.status FROM seat_reservations sr WHERE sr.seat_id=s.id AND "
        "   (sr.status='checked_in' OR (sr.status='reserved' AND sr.expire_time > NOW())) "
        "   ORDER BY sr.id DESC LIMIT 1) AS cur_status "
        "FROM seats s ORDER BY s.area, s.seat_no")
    areas = {}
    for s in rows:
        areas.setdefault(s["area"], []).append(s)
    banned = user["banned_until"] and user["banned_until"] > datetime.datetime.now()
    return render_template("seats.html", areas=areas, my_active=my_active,
                           banned=banned, banned_until=user["banned_until"],
                           now=datetime.datetime.now())


@app.route("/seats/reserve/<int:seat_id>", methods=["POST"])
@login_required
def reserve_seat(seat_id):
    user = current_user()
    now = datetime.datetime.now()

    if user["banned_until"] and user["banned_until"] > now:
        flash(f"你因超时未签到被封禁，{user['banned_until']:%Y-%m-%d %H:%M} 后才能预约",
              "error")
        return redirect(url_for("seats"))

    if active_reservation_of(user["id"]):
        flash("你已有进行中的座位预约，请先签到、签退或取消", "warn")
        return redirect(url_for("seats"))

    seat = db.query_one("SELECT * FROM seats WHERE id=%s", (seat_id,))
    if not seat:
        abort(404)
    occupied = db.query_one(
        "SELECT id FROM seat_reservations WHERE seat_id=%s AND "
        "(status='checked_in' OR (status='reserved' AND expire_time > NOW())) LIMIT 1",
        (seat_id,))
    if occupied:
        flash("该座位已被预约或占用", "error")
        return redirect(url_for("seats"))

    db.execute(
        "INSERT INTO seat_reservations (user_id, seat_id, start_time, expire_time) "
        "VALUES (%s, %s, NOW(), DATE_ADD(NOW(), INTERVAL %s MINUTE))",
        (user["id"], seat_id, CHECKIN_WINDOW_MINUTES))
    flash(f"预约成功：{seat['area']} {seat['seat_no']}，请在 1 小时内签到", "ok")
    return redirect(url_for("seats"))


@app.route("/seats/checkin/<int:res_id>/<seat_code>", methods=["POST"])
@login_required
def checkin(res_id, seat_code):
    r = db.query_one(
        "SELECT * FROM seat_reservations WHERE id=%s AND user_id=%s AND status='reserved'",
        (res_id, session["uid"]))
    if not r:
        flash("预约记录不存在或已失效", "error")
        return redirect(url_for("seats"))
    seat = db.query_one("SELECT * FROM seats WHERE seat_code=%s", (seat_code,))
    if not seat or seat["id"] != r["seat_id"]:
        flash("签到失败：请到你预约的座位前扫码签到", "error")
        return redirect(url_for("seats"))

    if r["expire_time"] < datetime.datetime.now():
        flash("已超过签到时间，本次预约记为违约", "error")
        return redirect(url_for("seats"))
    db.execute(
        "UPDATE seat_reservations SET status='checked_in', checkin_time=NOW() "
        "WHERE id=%s", (res_id,))
    db.execute("INSERT INTO points_log (user_id, points, reason) VALUES (%s, %s, %s)",
               (session["uid"], POINTS_PER_CHECKIN, "座位按时签到"))
    db.execute("UPDATE users SET points = points + %s WHERE id=%s",
               (POINTS_PER_CHECKIN, session["uid"]))
    flash(f"签到成功，积分 +{POINTS_PER_CHECKIN}！", "ok")
    return redirect(url_for("seats"))


@app.route("/seats/leave/<int:res_id>", methods=["POST"])
@login_required
def leave_seat(res_id):
    r = db.query_one(
        "SELECT * FROM seat_reservations WHERE id=%s AND user_id=%s "
        "AND status='checked_in'", (res_id, session["uid"]))
    if not r:
        flash("当前没有可签退的座位", "error")
        return redirect(url_for("seats"))
    db.execute("UPDATE seat_reservations SET status='left', leave_time=NOW() "
               "WHERE id=%s", (res_id,))
    flash("已签退，座位已释放", "ok")
    return redirect(url_for("seats"))


@app.route("/seats/cancel/<int:res_id>", methods=["POST"])
@login_required
def cancel_reservation(res_id):
    r = db.query_one(
        "SELECT * FROM seat_reservations WHERE id=%s AND user_id=%s "
        "AND status='reserved'", (res_id, session["uid"]))
    if not r:
        flash("预约记录不存在或已失效", "error")
        return redirect(url_for("seats"))
    db.execute("UPDATE seat_reservations SET status='cancelled' WHERE id=%s",
               (res_id,))
    flash("预约已取消", "ok")
    return redirect(url_for("seats"))

@app.route("/seat/<seat_code>")
@login_required
def seat_scan(seat_code):
    """扫码落地页：二维码里就是这个地址。人到了座位前才能扫到。"""
    seat = db.query_one("SELECT * FROM seats WHERE seat_code=%s", (seat_code,))
    if not seat:
        abort(404)
    res = db.query_one(
        "SELECT * FROM seat_reservations WHERE seat_id=%s AND user_id=%s "
        "AND status IN ('reserved', 'checked_in') ORDER BY id DESC LIMIT 1",
        (seat["id"], session["uid"]))
    return render_template("seat_scan.html", seat=seat, res=res)

@app.route("/my/reservations")
@login_required
def my_reservations():
    rows = db.query_all(
        "SELECT sr.*, s.seat_no, s.area FROM seat_reservations sr "
        "JOIN seats s ON s.id=sr.seat_id WHERE sr.user_id=%s "
        "ORDER BY sr.id DESC LIMIT 50", (session["uid"],))
    return render_template("my_reservations.html", rows=rows)

# ============ 积分排行榜与荣誉称号 ============

def period_start_sql(period_type, ref_sql="CURDATE()"):
    """周期起始日的 SQL 表达式：week=周一 / month=每月1号 / year=每年1月1日。"""
    if period_type == "week":
        return f"DATE_SUB({ref_sql}, INTERVAL WEEKDAY({ref_sql}) DAY)"
    if period_type == "month":
        # 注意：pymysql 里 % 要写成 %% 转义！
        return f"DATE_FORMAT({ref_sql}, '%%Y-%%m-01')"
    return f"MAKEDATE(YEAR({ref_sql}), 1)"


def period_bounds(period_type, prev=False):
    """返回 (周期起始日, 下一周期起始日)。prev=True 取上一个完整周期。"""
    ref = f"DATE_SUB(CURDATE(), INTERVAL 1 {period_type.upper()})" if prev else "CURDATE()"
    s = period_start_sql(period_type, ref)
    e = period_start_sql(period_type, f"DATE_ADD({ref}, INTERVAL 1 {period_type.upper()})")
    row = db.query_one(f"SELECT {s} AS s, {e} AS e")
    return row["s"], row["e"]


def leaderboard_between(start, end=None, limit=10):
    """[start, end) 期间的积分榜。end=None 表示至今。"""
    if end is None:
        cond, params = "p.created_at >= %s", (start,)
    else:
        cond, params = "p.created_at >= %s AND p.created_at < %s", (start, end)
    return db.query_all(
        "SELECT u.id, u.username, COALESCE(SUM(p.points),0) AS period_points "
        "FROM users u LEFT JOIN points_log p ON p.user_id=u.id AND " + cond + " "
        "WHERE u.role='reader' "
        "GROUP BY u.id, u.username ORDER BY period_points DESC, u.id LIMIT %s",
        params + (limit,))


def period_leaderboard(period_type):
    start, _ = period_bounds(period_type)
    return start, leaderboard_between(start)


def grant_honor(period_type, title, start=None, end=None, board=None):
    """结算周期冠军并授予称号。INSERT IGNORE 天然幂等（不会重复授予）。"""
    if board is None:
        if start is None:
            start, end = period_bounds(period_type)
        board = leaderboard_between(start, end)
    if board and board[0]["period_points"] > 0:
        db.execute(
            "INSERT IGNORE INTO honors (user_id, period_type, period_start, title) "
            "VALUES (%s, %s, %s, %s)",
            (board[0]["id"], period_type, start, title))
        return board[0]
    return None


def settle_past_periods():
    """跨期后自动补发上一周/上一月/上一年的冠军称号。"""
    for ptype, title in (("week", WEEK_TITLE), ("month", MONTH_TITLE),
                         ("year", YEAR_TITLE)):
        start, end = period_bounds(ptype, prev=True)
        grant_honor(ptype, title, start=start, end=end,
                    board=leaderboard_between(start, end))


def monthly_matrix():
    """本年度每用户逐月积分，用于页面上的明细表。"""
    year_start = period_bounds("year")[0]
    rows = db.query_all(
        "SELECT u.id, u.username, MONTH(p.created_at) AS m, "
        "COALESCE(SUM(p.points),0) AS s FROM users u "
        "LEFT JOIN points_log p ON p.user_id=u.id AND p.created_at >= %s "
        "WHERE u.role='reader' GROUP BY u.id, u.username, MONTH(p.created_at) "
        "ORDER BY u.id", (year_start,))
    matrix = {}
    for r in rows:
        matrix.setdefault((r["id"], r["username"]), {})[r["m"]] = r["s"]
    return sorted(matrix.items(), key=lambda kv: sum(kv[1].values()), reverse=True)


@app.route("/leaderboard")
@login_required
def leaderboard():
    settle_past_periods()  # 先补发历史冠军
    week_start, week_board = period_leaderboard("week")
    month_start, month_board = period_leaderboard("month")
    year_start, year_board = period_leaderboard("year")
    week_champion = grant_honor("week", WEEK_TITLE, start=week_start, board=week_board)
    month_champion = grant_honor("month", MONTH_TITLE, start=month_start, board=month_board)
    honors = db.query_all(
        "SELECT h.*, u.username FROM honors h JOIN users u ON u.id=h.user_id "
        "ORDER BY h.period_start DESC, h.period_type LIMIT 50")
    my_logs = db.query_all(
        "SELECT * FROM points_log WHERE user_id=%s ORDER BY id DESC LIMIT 20",
        (session["uid"],))
    return render_template(
        "leaderboard.html",
        week_start=week_start, week_board=week_board, week_champion=week_champion,
        month_start=month_start, month_board=month_board, month_champion=month_champion,
        year_start=year_start, year_board=year_board, month_matrix=monthly_matrix(),
        honors=honors, my_logs=my_logs,
        week_title=WEEK_TITLE, month_title=MONTH_TITLE, year_title=YEAR_TITLE)


# ============ 管理员总览 ============

@app.route("/admin/overview")
@admin_required
def admin_overview():
    users = db.query_all(
        "SELECT id, username, role, points, banned_until, created_at FROM users "
        "ORDER BY id")
    active = db.query_all(
        "SELECT sr.*, u.username, s.seat_no, s.area FROM seat_reservations sr "
        "JOIN users u ON u.id=sr.user_id JOIN seats s ON s.id=sr.seat_id "
        "WHERE sr.status IN ('reserved','checked_in') AND "
        "      (sr.status='checked_in' OR sr.expire_time > NOW()) ORDER BY sr.id DESC")
    return render_template("admin_overview.html", users=users, active=active,
                           now=datetime.datetime.now())
@app.route("/admin/seat-codes")
@admin_required
def seat_codes():
    """生成全部座位的签到二维码，可打印后贴到座位上。"""
    seats = db.query_all("SELECT * FROM seats ORDER BY id")
    items = []
    for s in seats:
        url = request.host_url.rstrip('/') + url_for("seat_scan", seat_code=s["seat_code"])
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        items.append({
            "seat": s,
            "url": url,
            "b64": base64.b64encode(buf.getvalue()).decode(),
        })
    return render_template("seat_codes.html", items=items)


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, msg="没有权限访问该页面"), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, msg="页面不存在"), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)