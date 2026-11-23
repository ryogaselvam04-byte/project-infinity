import os, io, base64, sqlite3
from functools import wraps
from flask import Flask, request, jsonify, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from pypdf import PdfReader

if os.path.exists(".env"):
    for l in open(".env"):
        if "=" in l and not l.startswith("#"):
            k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.getenv("SECRET_KEY", "change-me")
DB, MODEL = "infinity.db", os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
client = None
if os.getenv("ANTHROPIC_API_KEY"):
    import anthropic
    client = anthropic.Anthropic()

SCHEMA = """
create table if not exists users(user_id integer primary key autoincrement, name text not null,
  email text unique not null, password text not null, created_at datetime default current_timestamp);
create table if not exists chat_history(chat_id integer primary key autoincrement, user_id int not null,
  user_message text not null, ai_response text not null, created_at datetime default current_timestamp);
create table if not exists notes(note_id integer primary key autoincrement, user_id int not null,
  title text not null, content text, created_at datetime default current_timestamp, updated_at datetime);
create table if not exists activity_log(log_id integer primary key autoincrement, user_id int not null,
  tool_name text not null, action text, created_at datetime default current_timestamp);
"""
with sqlite3.connect(DB) as c: c.executescript(SCHEMA)

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

def need_login(f):
    @wraps(f)
    def w(*a, **k):
        if "uid" not in session: return jsonify(error="Please login first"), 401
        return f(*a, **k)
    return w

def log(tool, action=""):
    db().execute("insert into activity_log(user_id,tool_name,action) values(?,?,?)", (session["uid"], tool, action[:80]))
    db().commit()

def ask_ai(system, content, history=None):
    if not client:
        return "(Demo mode: add ANTHROPIC_API_KEY in .env for real AI replies.) The workflow is working end to end."
    msgs = (history or []) + [{"role": "user", "content": content}]
    r = client.messages.create(model=MODEL, max_tokens=1000, system=system, messages=msgs)
    return "".join(b.text for b in r.content if b.type == "text")

# ---------- auth ----------
@app.post("/api/register")
def register():
    d = request.json or {}
    n, e, p = d.get("name", "").strip(), d.get("email", "").strip().lower(), d.get("password", "")
    if not (n and e and len(p) >= 4): return jsonify(error="Fill all fields (password min 4 chars)"), 400
    try:
        cur = db().execute("insert into users(name,email,password) values(?,?,?)", (n, e, generate_password_hash(p)))
        db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error="Email already registered"), 400
    session["uid"] = cur.lastrowid
    return jsonify(name=n)

@app.post("/api/login")
def login():
    d = request.json or {}
    u = db().execute("select * from users where email=?", (d.get("email", "").strip().lower(),)).fetchone()
    if not u or not check_password_hash(u["password"], d.get("password", "")):
        return jsonify(error="Wrong email or password"), 400
    session["uid"] = u["user_id"]
    return jsonify(name=u["name"])

@app.post("/api/logout")
def logout():
    session.clear(); return jsonify(ok=True)

@app.get("/api/me")
@need_login
def me():
    u = db().execute("select name from users where user_id=?", (session["uid"],)).fetchone()
    return jsonify(name=u["name"])

# ---------- chat ----------
@app.post("/api/chat")
@need_login
def chat():
    msg = (request.json or {}).get("message", "").strip()
    if not msg: return jsonify(error="Empty message"), 400
    rows = db().execute("select user_message,ai_response from chat_history where user_id=? order by chat_id desc limit 6",
                        (session["uid"],)).fetchall()[::-1]
    hist = [m for r in rows for m in ({"role": "user", "content": r[0]}, {"role": "assistant", "content": r[1]})]
    try: reply = ask_ai("You are Infinity, a helpful, concise AI assistant.", msg, hist)
    except Exception as ex: return jsonify(error=f"AI error: {ex}"), 500
    db().execute("insert into chat_history(user_id,user_message,ai_response) values(?,?,?)", (session["uid"], msg, reply))
    log("Chat", msg); return jsonify(reply=reply)

@app.get("/api/chat/history")
@need_login
def chat_history():
    rows = db().execute("select user_message,ai_response from chat_history where user_id=? order by chat_id desc limit 20",
                        (session["uid"],)).fetchall()[::-1]
    return jsonify([dict(r) for r in rows])

# ---------- PDF / image analyzer ----------
@app.post("/api/analyze")
@need_login
def analyze():
    f = request.files.get("file")
    if not f: return jsonify(error="No file uploaded"), 400
    name, ext = f.filename, f.filename.lower().rsplit(".", 1)[-1]
    sys = "Analyze the content. Give a short summary, then 3-5 key points as bullets."
    try:
        if ext == "pdf":
            text = "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(f.read())).pages)[:15000]
            if not text.strip(): return jsonify(error="No readable text found in this PDF"), 400
            out = ask_ai(sys, "Document text:\n" + text)
        elif ext in ("png", "jpg", "jpeg", "gif", "webp"):
            mt = {"jpg": "image/jpeg"}.get(ext, f"image/{ext}")
            blk = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": base64.b64encode(f.read()).decode()}},
                   {"type": "text", "text": "Describe and analyze this image."}]
            out = ask_ai(sys, blk)
        else: return jsonify(error="Upload a PDF or image (png/jpg/webp/gif)"), 400
    except Exception as ex: return jsonify(error=f"Analysis failed: {ex}"), 500
    log("Analyzer", name); return jsonify(result=out)

# ---------- code checker ----------
@app.post("/api/code")
@need_login
def code():
    d = request.json or {}
    src = d.get("code", "").strip()
    if not src: return jsonify(error="Paste some code first"), 400
    try:
        out = ask_ai("You are a code reviewer. List errors found, explain each briefly, then give the corrected code and improvement tips.",
                     f"Language: {d.get('language', 'auto')}\n\n{src[:8000]}")
    except Exception as ex: return jsonify(error=f"Review failed: {ex}"), 500
    log("Code Checker", d.get("language", "auto")); return jsonify(result=out)

# ---------- notes ----------
@app.get("/api/notes")
@need_login
def notes_list():
    rows = db().execute("select note_id,title,content,created_at from notes where user_id=? order by note_id desc", (session["uid"],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/notes")
@need_login
def notes_add():
    d = request.json or {}
    if not d.get("title", "").strip(): return jsonify(error="Title required"), 400
    db().execute("insert into notes(user_id,title,content) values(?,?,?)", (session["uid"], d["title"], d.get("content", "")))
    db().commit(); log("Notes", "created: " + d["title"]); return jsonify(ok=True)

@app.put("/api/notes/<int:nid>")
@need_login
def notes_edit(nid):
    d = request.json or {}
    db().execute("update notes set title=?,content=?,updated_at=current_timestamp where note_id=? and user_id=?",
                 (d.get("title", ""), d.get("content", ""), nid, session["uid"]))
    db().commit(); log("Notes", "edited: " + d.get("title", "")); return jsonify(ok=True)

@app.delete("/api/notes/<int:nid>")
@need_login
def notes_del(nid):
    db().execute("delete from notes where note_id=? and user_id=?", (nid, session["uid"]))
    db().commit(); log("Notes", "deleted"); return jsonify(ok=True)

# ---------- dashboard ----------
@app.get("/api/dashboard")
@need_login
def dashboard():
    u = session["uid"]
    by = db().execute("select tool_name,count(*) c from activity_log where user_id=? group by tool_name", (u,)).fetchall()
    rec = db().execute("select tool_name,action,created_at from activity_log where user_id=? order by log_id desc limit 8", (u,)).fetchall()
    return jsonify(total=sum(r["c"] for r in by), tools={r["tool_name"]: r["c"] for r in by}, recent=[dict(r) for r in rec])

@app.get("/")
def home(): return app.send_static_file("index.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
