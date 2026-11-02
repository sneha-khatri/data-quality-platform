import csv, io, os, re, sqlite3
from datetime import datetime
from difflib import SequenceMatcher
from functools import wraps
from flask import (Flask, Response, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
DB = os.path.join(os.path.dirname(__file__), "dq.db")
FIELDS = ["name", "email", "phone", "address", "city"]
DUP_THRESHOLD = 0.82

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, name TEXT, email TEXT, phone TEXT,
  address TEXT, city TEXT, score INTEGER DEFAULT 100, issues TEXT DEFAULT '',
  status TEXT DEFAULT 'active', created_at TEXT);
CREATE TABLE IF NOT EXISTS duplicates(id INTEGER PRIMARY KEY, a INTEGER, b INTEGER,
  similarity REAL, status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, record_id INTEGER, field TEXT,
  old TEXT, new TEXT, action TEXT, by TEXT, at TEXT);
"""

# ---------- DB helpers ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

def init_db():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    for u, p, r in [("admin", "admin123", "admin"), ("reviewer", "review123", "reviewer"),
                    ("viewer", "view123", "viewer")]:
        con.execute("INSERT OR IGNORE INTO users(username,pw,role) VALUES(?,?,?)",
                    (u, generate_password_hash(p), r))
    con.commit(); con.close()

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(rid, field, old, new, action):
    db().execute("INSERT INTO history(record_id,field,old,new,action,by,at) VALUES(?,?,?,?,?,?,?)",
                 (rid, field, old, new, action, session.get("user", "system"), now()))

# ---------- Auth ----------
def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrap(*a, **k):
            if "user" not in session:
                return redirect(url_for("login"))
            if roles and session["role"] not in roles:
                flash("You are not authorized for this action.", "err")
                return redirect(url_for("dashboard"))
            return fn(*a, **k)
        return wrap
    return deco

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE username=?", (request.form["username"],)).fetchone()
        if u and check_password_hash(u["pw"], request.form["password"]):
            session["user"], session["role"] = u["username"], u["role"]
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.", "err")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- Data quality logic ----------
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")

def digits(p):
    return re.sub(r"\D", "", p or "")

def assess(r):
    """Return (score, issues list) for a record dict."""
    score, issues = 100, []
    for f, pen in [("name", 20), ("email", 15), ("phone", 15), ("address", 5), ("city", 5)]:
        if not (r.get(f) or "").strip():
            score -= pen; issues.append(f"missing {f}")
    if r.get("email") and not EMAIL_RE.match(r["email"].strip()):
        score -= 15; issues.append("invalid email")
    d = digits(r.get("phone"))
    if r.get("phone") and len(d[-10:]) != 10:
        score -= 15; issues.append("invalid phone")
    if suggest(r):
        score -= 5; issues.append("inconsistent format")
    return max(score, 0), issues

def suggest(r):
    """Suggested standardisation fixes: {field: new_value}."""
    s = {}
    n = " ".join((r.get("name") or "").split()).title()
    if n and n != r["name"]: s["name"] = n
    e = (r.get("email") or "").strip().lower()
    if e and e != r["email"]: s["email"] = e
    d = digits(r.get("phone"))
    if len(d) >= 10 and d[-10:] != r["phone"] and len(d[-10:]) == 10:
        s["phone"] = d[-10:]
    c = " ".join((r.get("city") or "").split()).title()
    if c and c != r["city"]: s["city"] = c
    return s

def refresh(rid):
    r = dict(db().execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone())
    sc, iss = assess(r)
    db().execute("UPDATE records SET score=?, issues=? WHERE id=?", (sc, ", ".join(iss), rid))

def similarity(a, b):
    nm = SequenceMatcher(None, (a["name"] or "").lower(), (b["name"] or "").lower()).ratio()
    ea, eb = (a["email"] or "").lower().strip(), (b["email"] or "").lower().strip()
    pa, pb = digits(a["phone"])[-10:], digits(b["phone"])[-10:]
    if (ea and ea == eb) or (len(pa) == 10 and pa == pb):
        contact = 1.0
    else:
        contact = SequenceMatcher(None, ea, eb).ratio() * 0.5 if ea and eb else 0
    return round(0.6 * nm + 0.4 * contact, 3)

def detect_duplicates():
    recs = db().execute("SELECT * FROM records WHERE status='active' ORDER BY id").fetchall()
    seen = {(x["a"], x["b"]) for x in db().execute("SELECT a,b FROM duplicates")}
    found = 0
    for i in range(len(recs)):
        for j in range(i + 1, len(recs)):
            a, b = recs[i], recs[j]
            if (a["id"], b["id"]) in seen: continue
            s = similarity(a, b)
            if s >= DUP_THRESHOLD:
                db().execute("INSERT INTO duplicates(a,b,similarity) VALUES(?,?,?)", (a["id"], b["id"], s))
                found += 1
    db().commit()
    return found

# ---------- Pages ----------
@app.route("/")
@login_required()
def dashboard():
    q = db().execute
    stats = {
        "total": q("SELECT COUNT(*) FROM records WHERE status='active'").fetchone()[0],
        "avg": round(q("SELECT AVG(score) FROM records WHERE status='active'").fetchone()[0] or 0, 1),
        "dups": q("SELECT COUNT(*) FROM duplicates WHERE status='pending'").fetchone()[0],
        "low": q("SELECT COUNT(*) FROM records WHERE status='active' AND score<70").fetchone()[0],
        "missing": q("SELECT COUNT(*) FROM records WHERE status='active' AND issues LIKE '%missing%'").fetchone()[0],
        "fixable": sum(1 for r in q("SELECT * FROM records WHERE status='active'") if suggest(dict(r))),
    }
    return render_template("dashboard.html", s=stats)

@app.route("/upload", methods=["GET", "POST"])
@login_required("admin", "reviewer")
def upload():
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith(".csv"):
            flash("Please upload a .csv file.", "err"); return redirect(url_for("upload"))
        rows = csv.DictReader(io.StringIO(f.read().decode("utf-8-sig")))
        n = 0
        for row in rows:
            vals = [(row.get(k) or "").strip() for k in FIELDS]
            cur = db().execute("INSERT INTO records(name,email,phone,address,city,created_at) VALUES(?,?,?,?,?,?)",
                               (*vals, now()))
            log(cur.lastrowid, "*", "", "imported", "import")
            refresh(cur.lastrowid); n += 1
        db().commit()
        d = detect_duplicates()
        flash(f"Imported {n} records. {d} potential duplicate pair(s) found.", "ok")
        return redirect(url_for("records"))
    return render_template("upload.html")

@app.route("/records")
@login_required()
def records():
    rows = db().execute("SELECT * FROM records WHERE status='active' ORDER BY score, id").fetchall()
    return render_template("records.html", rows=rows, suggest=lambda r: suggest(dict(r)))

@app.route("/records/<int:rid>/approve", methods=["POST"])
@login_required("admin", "reviewer")
def approve(rid):
    r = dict(db().execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone())
    for f, new in suggest(r).items():
        db().execute(f"UPDATE records SET {f}=? WHERE id=?", (new, rid))
        log(rid, f, r[f], new, "approved fix")
    refresh(rid); db().commit()
    flash(f"Record #{rid} corrected.", "ok")
    return redirect(url_for("records"))

@app.route("/records/<int:rid>/edit", methods=["POST"])
@login_required("admin", "reviewer")
def edit(rid):
    r = dict(db().execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone())
    for f in FIELDS:
        new = request.form.get(f, "").strip()
        if new != r[f]:
            db().execute(f"UPDATE records SET {f}=? WHERE id=?", (new, rid))
            log(rid, f, r[f], new, "manual edit")
    refresh(rid); db().commit()
    return redirect(url_for("records"))

@app.route("/duplicates")
@login_required()
def duplicates():
    rows = db().execute("""SELECT d.*, a.name an, a.email ae, a.phone ap, a.city ac,
        b.name bn, b.email be, b.phone bp, b.city bc FROM duplicates d
        JOIN records a ON a.id=d.a JOIN records b ON b.id=d.b
        WHERE d.status='pending' ORDER BY d.similarity DESC""").fetchall()
    return render_template("duplicates.html", rows=rows)

@app.route("/duplicates/<int:did>/<action>", methods=["POST"])
@login_required("admin", "reviewer")
def resolve(did, action):
    d = db().execute("SELECT * FROM duplicates WHERE id=?", (did,)).fetchone()
    if action == "merge":
        a = dict(db().execute("SELECT * FROM records WHERE id=?", (d["a"],)).fetchone())
        b = dict(db().execute("SELECT * FROM records WHERE id=?", (d["b"],)).fetchone())
        for f in FIELDS:  # fill gaps in master from duplicate
            if not a[f] and b[f]:
                db().execute(f"UPDATE records SET {f}=? WHERE id=?", (b[f], a["id"]))
                log(a["id"], f, a[f], b[f], "merge fill")
        db().execute("UPDATE records SET status='merged' WHERE id=?", (b["id"],))
        log(b["id"], "status", "active", f"merged into #{a['id']}", "merge")
        refresh(a["id"])
        db().execute("UPDATE duplicates SET status='merged' WHERE id=?", (did,))
        flash("Records merged.", "ok")
    else:
        db().execute("UPDATE duplicates SET status='rejected' WHERE id=?", (did,))
        flash("Marked as not duplicate.", "ok")
    db().commit()
    return redirect(url_for("duplicates"))

@app.route("/history")
@login_required()
def history():
    rows = db().execute("SELECT * FROM history ORDER BY id DESC LIMIT 300").fetchall()
    return render_template("history.html", rows=rows)

@app.route("/export")
@login_required()
def export():
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["id", *FIELDS, "score"])
    for r in db().execute("SELECT * FROM records WHERE status='active'"):
        w.writerow([r["id"], *[r[f] for f in FIELDS], r["score"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=clean_records.csv"})

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
