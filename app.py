# app.py
import os, time, urllib.parse
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
import mysql.connector
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("FLASK_SECRET", "please_change_this_secret")

# DB config
DB_HOST = os.environ.get("DB_HOST", "db")
DB_PORT = int(os.environ.get("DB_PORT", 3306))
DB_USER = os.environ.get("DB_USER", "cs_user")
DB_PASS = os.environ.get("DB_PASS", "cs_pass")
DB_NAME = os.environ.get("DB_NAME", "couriersathi")

OWNER_WHATSAPP = os.environ.get("OWNER_WHATSAPP", "918290105891")  # no plus

# Admin
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "adminpass")

auth = HTTPBasicAuth()
users = { ADMIN_USER: generate_password_hash(ADMIN_PASS) }
@auth.verify_password
def verify(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username

# expose datetime to templates (use {{ datetime.utcnow().year }})
app.jinja_env.globals['datetime'] = datetime

def get_db_conn(retry=True, retries=10, delay=2):
    for _ in range(retries if retry else 1):
        try:
            conn = mysql.connector.connect(
                host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, database=DB_NAME, autocommit=True
            )
            return conn
        except Exception:
            if retry:
                time.sleep(delay)
    raise Exception("Could not connect to DB")

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
        cur.execute("""
           INSERT INTO bookings (item_description, sender_name, sender_phone, sender_pincode, receiver_pincode, created_at)
           VALUES (%s,%s,%s,%s,%s,%s)
        """, (item_description, sender_name, sender_phone, sender_pincode, receiver_pincode, datetime.utcnow()))
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

# JSON API endpoint used by JS "Send via WhatsApp" button
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
        cur.execute("""
           INSERT INTO bookings (item_description, sender_name, sender_phone, sender_pincode, receiver_pincode, created_at)
           VALUES (%s,%s,%s,%s,%s,%s)
        """, (item_description, sender_name, sender_phone, sender_pincode, receiver_pincode, datetime.utcnow()))
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
    # simple wait for DB
    for i in range(12):
        try:
            c = get_db_conn(retry=False)
            c.close()
            break
        except Exception:
            time.sleep(2)
    app.run(host="0.0.0.0", port=5000)
