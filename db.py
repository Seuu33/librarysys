"""数据库访问层：连接管理、建库建表、初始化管理员。"""
import os
import pymysql
from pymysql.cursors import DictCursor
from werkzeug.security import generate_password_hash

# ---------- 连接配置（改成你自己的密码！） ----------
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "123456"
DB_NAME = "library"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


def get_conn(db=True):
    """获取数据库连接。db=False 时不指定库（用于建库）。"""
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME if db else None,
        charset="utf8mb4",          # 支持中文，必须有
        cursorclass=DictCursor,     # 查询结果按字段名取值，必须有
        autocommit=False,           # 手动 commit，写操作更安全
    )


def init_db():
    """执行 schema.sql：建库、建表、插入初始座位。"""
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = get_conn(db=False)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS {DB_NAME} "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute(f"USE {DB_NAME}")
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                # 跳过空语句和纯注释
                if not stmt or all(line.strip().startswith("--") or not line.strip()
                                   for line in stmt.splitlines()):
                    continue
                upper = stmt.upper()
                if upper.startswith("CREATE DATABASE") or upper.startswith("USE "):
                    continue  # 文件头部的建库/USE已执行过
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()
    ensure_admin()


def ensure_admin():
    """首次运行时创建管理员账号。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO users (username, password_hash, role) "
                    "VALUES (%s, %s, 'admin')",
                    (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)),
                )
                conn.commit()
                print(f"[init] 已创建管理员: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    finally:
        conn.close()


# ---------- 通用查询助手（app.py 全靠这三个函数） ----------

def query_all(sql, params=None):
    """查多条，返回字典列表。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()


def query_one(sql, params=None):
    """查一条，返回字典或 None。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
    finally:
        conn.close()


def execute(sql, params=None):
    """增/删/改，返回 lastrowid。出错自动回滚。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            last_id = cur.lastrowid
        conn.commit()
        return last_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print("数据库初始化完成！")
    print("表：", [list(r.values())[0] for r in query_all("SHOW TABLES")])
    print("座位数：", query_one("SELECT COUNT(*) c FROM seats")["c"])