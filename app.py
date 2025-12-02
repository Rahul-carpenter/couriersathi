# app.py (Railway-ready with MYSQL_URL parsing + debug endpoints)
import os
import time
import urllib.parse
from datetime import datetime
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
import mysql.connector
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET", "please_change_this_secret")

# -------------------------
# DB config: support MYSQL_URL or individual vars
# -------------------------
DB_HOST = None
DB_PORT = None
DB_USER = None
DB_PASS = None
DB_NAME = None

# Railway recommended single URL (plugin provides this if you map it)
DB_URL = os.environ.get("MYSQL_URL") or os.environ.get("MYSQL_PUBLIC_URL") or os.environ.get("MYSQLDATABASE_URL")

if DB_URL:
    # parse mysql://user:pass@host:port/db
    try:
        p = urlparse(DB_URL)
        DB_HOST = p.hostname
        DB_PORT = p.port
        DB_USER = p.username
        DB_PASS = p.password
        DB_NAME = p.path.lstrip("/") if p.path else None
    except Exception:
        # fallback to env vars if parsing fails
        DB_HOST = os.environ.get("MYSQLHOST")
        DB_PORT = os.environ.get("MYSQLPORT")
        DB_USER = os.environ.get("MYSQLUSER")
        DB_PASS = os.environ.get("MYSQLPASSWORD")
        DB_NAME = os.environ.get("MYSQLDATABASE")
else:
    # fallback for local testing or explicit envs
    DB_HOST = os.environ.get("MYSQLHOST")
    DB_PORT = os.environ.get("MYSQLPORT")
    DB_USER = os.environ.get("MYSQLUSER")
    DB_PASS = os.environ.get("MYSQLPASSWORD")
    DB_NAME = os.environ.get("MYSQLDATABASE")

# ensure port is int when available
try:
    DB_PORT = int(DB_PORT) if DB_PORT is not None else None
except (ValueError, TypeError):
    DB_PORT = None

# Owner whatsapp number (no plus)
OWNER_WHATSAPP = os.environ.get("OWNER_WHATSAPP", "918290105891")

# Admin credentials (basic auth)
ADMIN_USER = os.environ.get("ADMIN_USER")
ADMIN_PASS = os.environ.get("ADMIN_PASS")

auth = HTTPBasicAuth()
users = {ADMIN_USER: generate_password_hash(ADMIN_PASS)}

@auth.verify_password
def verify(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username

# expose datetime to templates
app.jinja_env.globals['datetime'] = datetime

# DB connection helper with retries
def get_db_conn(retry=True, retries=8, delay=2):
    last_exc = None
    for i in range(retries if retry else 1):
        try:
            conn_kwargs = {
                "host": DB_HOST,
                "user": DB_USER,
                "password": DB_PASS,
                "database": DB_NAME,
            }
            if DB_PORT:
                conn_kwargs["port"] = DB_PORT
            conn = mysql.connector.connect(**conn_kwargs, autocommit=True)
            return conn
        except Exception as e:
            last_exc = e
            app.logger.debug("DB connect attempt %s failed: %s", i+1, e)
            if retry:
                time.sleep(delay)
    raise Exception(f"Could not connect to DB: {last_exc}")

# Backwards-compatible alias
def get_db():
    return get_db_conn()

# -------------------------
# Routes
# -------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    item_description = request.form.get("item_description","").strip()
    sender_name = request.form.get("sender_name","").strip()
    sender_phone = request.form.get("sender_phone","").strip()
    sender_pincode = request.form.get("sender_pincode","").strip()
    receiver_pincode = request.form.get("receiver_pincode","").strip()

    errs = []
    if not item_description:
        errs.append("Item description required.")
    if not sender_name:
        errs.append("Sender name required.")
    if not sender_phone or len(sender_phone) < 6:
        errs.append("Valid sender phone required.")
    if not sender_pincode:
        errs.append("Sender pincode required.")
    if not receiver_pincode:
        errs.append("Receiver pincode required.")

    if errs:
        for e in errs:
            flash(e, "danger")
        return redirect(url_for("index"))

    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
           """
           INSERT INTO bookings (item_description, sender_name, sender_phone, sender_pincode, receiver_pincode, created_at)
           VALUES (%s,%s,%s,%s,%s,%s)
           """,
           (item_description, sender_name, sender_phone, sender_pincode, receiver_pincode, datetime.utcnow())
        )
        cur.close()
        conn.close()
    except Exception as e:
        app.logger.error("DB insert error: %s", e)
        flash("Server error saving booking. Try again later.", "danger")
        return redirect(url_for("index"))

    msg_plain = (
        f"CourierSathi booking:\n"
        f"Item: {item_description}\n"
        f"Sender: {sender_name} ({sender_phone})\n"
        f"From Pincode: {sender_pincode}\n"
        f"To Pincode: {receiver_pincode}\n"
    )
    wa_url = f"https://wa.me/{OWNER_WHATSAPP}?text={urllib.parse.quote(msg_plain)}"
    flash("Booking saved. Click WhatsApp link to notify manually.", "info")
    return render_template("success.html", message_text=msg_plain, wa_url=wa_url, provider_sent=False)

@app.route("/api/submit-json", methods=["POST"])
def submit_json():
    data = request.get_json(silent=True) or {}
    item_description = (data.get("item_description") or "").strip()
    sender_name = (data.get("sender_name") or "").strip()
    sender_phone = (data.get("sender_phone") or "").strip()
    sender_pincode = (data.get("sender_pincode") or "").strip()
    receiver_pincode = (data.get("receiver_pincode") or "").strip()

    errs = []
    if not item_description:
        errs.append("Item description required.")
    if not sender_name:
        errs.append("Sender name required.")
    if not sender_phone or len(sender_phone) < 6:
        errs.append("Valid sender phone required.")
    if not sender_pincode:
        errs.append("Sender pincode required.")
    if not receiver_pincode:
        errs.append("Receiver pincode required.")
    if errs:
        return jsonify({"ok": False, "errors": errs}), 400

    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
           """
           INSERT INTO bookings (item_description, sender_name, sender_phone, sender_pincode, receiver_pincode, created_at)
           VALUES (%s,%s,%s,%s,%s,%s)
           """,
           (item_description, sender_name, sender_phone, sender_pincode, receiver_pincode, datetime.utcnow())
        )
        cur.close()
        conn.close()
    except Exception as e:
        app.logger.error("DB insert error (json): %s", e)
        return jsonify({"ok": False, "errors": ["Server DB error"]}), 500

    msg_plain = (
        f"CourierSathi booking:\n"
        f"Item: {item_description}\n"
        f"Sender: {sender_name} ({sender_phone})\n"
        f"From Pincode: {sender_pincode}\n"
        f"To Pincode: {receiver_pincode}\n"
    )
    wa_url = f"https://wa.me/{OWNER_WHATSAPP}?text={urllib.parse.quote(msg_plain)}"
    return jsonify({"ok": True, "wa_url": wa_url, "message_text": msg_plain})

@app.route("/admin")
@auth.login_required
def admin():
    try:
        conn = get_db_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, item_description, sender_name, sender_phone, sender_pincode, receiver_pincode, created_at FROM bookings ORDER BY created_at DESC LIMIT 200")
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        rows = []
        app.logger.error("Admin DB read error: %s", e)
        flash("Could not load bookings.", "danger")
    return render_template("admin.html", bookings=rows)

@app.route("/sitemap.xml")
def sitemap():
    host = request.url_root.strip('/')
    pages = [url_for('index', _external=True)]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in pages:
        xml.append("<url><loc>{}</loc></url>".format(p))
    xml.append("</urlset>")
    return Response("\n".join(xml), mimetype="application/xml")

@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {}/sitemap.xml".format(request.url_root.strip('/')), mimetype="text/plain")


if __name__ == "__main__":
    # optional debug log at startup (remove or lower level in production)

    # wait-for-db attempts (helps on first deploy)
    app.run(host="0.0.0.0", port=5000)
