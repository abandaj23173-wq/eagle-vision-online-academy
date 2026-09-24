import os, sqlite3, secrets
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "academy.db")
CERT_DIR = os.path.join(BASE, "certificates")
os.makedirs(CERT_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION")

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    conn = g.pop("db", None)
    if conn:
        conn.close()

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'student',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS courses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        level TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS lessons(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT,
        video_url TEXT,
        position INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY(course_id) REFERENCES courses(id)
    );
    CREATE TABLE IF NOT EXISTS enrollments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        UNIQUE(user_id, course_id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(course_id) REFERENCES courses(id)
    );
    CREATE TABLE IF NOT EXISTS lesson_progress(
        user_id INTEGER NOT NULL,
        lesson_id INTEGER NOT NULL,
        completed INTEGER NOT NULL DEFAULT 0,
        completed_at TEXT,
        PRIMARY KEY(user_id, lesson_id)
    );
    CREATE TABLE IF NOT EXISTS quizzes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        option_a TEXT NOT NULL,
        option_b TEXT NOT NULL,
        option_c TEXT NOT NULL,
        option_d TEXT NOT NULL,
        answer TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS quiz_attempts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        quiz_id INTEGER NOT NULL,
        score INTEGER NOT NULL,
        attempted_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        method TEXT NOT NULL,
        reference TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL
    );
    """)
    if conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0:
        courses = [
            ("Form 1 Mathematics","Form 1","Build strong foundations in mathematics.",5),
            ("Form 2 Mathematics","Form 2","Master key Form 2 concepts and exam skills.",5),
            ("Form 3 Mathematics","Form 3","Develop problem-solving and examination confidence.",5),
            ("O-Level Mathematics","Form 4 / O-Level","Complete revision, past papers and exam strategy.",10),
            ("O-Level Science","Form 4 / O-Level","Science concepts, practical thinking and exam practice.",10),
            ("O-Level Geography","Form 4 / O-Level","Geography concepts, maps, data and examination practice.",10),
            ("A-Level History","Lower 6 / A-Level","Structured history lessons and essay practice.",10),
        ]
        conn.executemany("INSERT INTO courses(title,level,description,price) VALUES(?,?,?,?)", courses)
        conn.commit()
    if conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 0:
        course_rows = conn.execute("SELECT id,title FROM courses").fetchall()
        for c in course_rows:
            lessons = [
                (c["id"], "Welcome & Study Strategy", f"Welcome to {c['title']}. Set a weekly study timetable, watch the lesson video, read the notes and complete the quiz.", "", 1),
                (c["id"], "Core Concepts", "Learn the core ideas for this module. Add your teacher video URL in the admin area or directly in the database when ready.", "", 2),
                (c["id"], "Exam Practice", "Work through examination-style questions and check each answer carefully.", "", 3),
            ]
            conn.executemany("INSERT INTO lessons(course_id,title,content,video_url,position) VALUES(?,?,?,?,?)", lessons)
        conn.commit()
    if conn.execute("SELECT COUNT(*) FROM quizzes").fetchone()[0] == 0:
        c = conn.execute("SELECT id FROM courses WHERE title='O-Level Mathematics'").fetchone()
        if c:
            conn.execute("""INSERT INTO quizzes(course_id,question,option_a,option_b,option_c,option_d,answer)
                            VALUES(?,?,?,?,?,?,?)""",
                         (c["id"], "What is 12 × 8?", "86", "96", "108", "88", "B"))
            conn.execute("""INSERT INTO quizzes(course_id,question,option_a,option_b,option_c,option_d,answer)
                            VALUES(?,?,?,?,?,?,?)""",
                         (c["id"], "Solve: 2x = 10", "2", "5", "10", "20", "B"))
            conn.commit()
    if not conn.execute("SELECT 1 FROM users WHERE email='admin@eaglevisionacademy.co.zw'").fetchone():
        conn.execute("""INSERT INTO users(full_name,email,phone,password_hash,role,created_at)
                        VALUES(?,?,?,?,?,?)""",
                     ("Eagle Vision Admin","admin@eaglevisionacademy.co.zw","+263 71 741 0018",
                      generate_password_hash("ChangeMe123!"),"admin",datetime.utcnow().isoformat()))
        conn.commit()

@app.before_request
def load_user():
    g.user = None
    if session.get("user_id"):
        g.user = db().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            flash("Please log in to continue.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user or g.user["role"] != "admin":
            flash("Administrator access required.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

@app.route("/")
def index():
    courses = db().execute("SELECT * FROM courses WHERE active=1 ORDER BY id").fetchall()
    return render_template("index.html", courses=courses)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form["full_name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone","").strip()
        password = request.form["password"]
        if len(password) < 8:
            flash("Password must be at least 8 characters.")
            return redirect(url_for("register"))
        try:
            cur = db().execute("""INSERT INTO users(full_name,email,phone,password_hash,created_at)
                                  VALUES(?,?,?,?,?)""",
                               (name,email,phone,generate_password_hash(password),datetime.utcnow().isoformat()))
            db().commit()
            session["user_id"] = cur.lastrowid
            flash("Welcome to the Eagle Family!")
            return redirect(url_for("dashboard"))
        except sqlite3.IntegrityError:
            flash("That email is already registered.")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("admin" if user["role"]=="admin" else "dashboard"))
        flash("Incorrect email or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    courses = db().execute("""SELECT c.*, e.status FROM courses c
                              JOIN enrollments e ON e.course_id=c.id
                              WHERE e.user_id=? ORDER BY c.id""",(g.user["id"],)).fetchall()
    return render_template("dashboard.html", courses=courses)

@app.route("/course/<int:course_id>")
@login_required
def course(course_id):
    c = db().execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    if not c: return "Course not found", 404
    enrollment = db().execute("SELECT * FROM enrollments WHERE user_id=? AND course_id=?",(g.user["id"],course_id)).fetchone()
    lessons = db().execute("""SELECT l.*, COALESCE(p.completed,0) completed
                              FROM lessons l LEFT JOIN lesson_progress p
                              ON p.lesson_id=l.id AND p.user_id=?
                              WHERE l.course_id=? ORDER BY l.position""",(g.user["id"],course_id)).fetchall()
    quizzes = db().execute("SELECT * FROM quizzes WHERE course_id=?", (course_id,)).fetchall()
    return render_template("course.html", course=c, enrollment=enrollment, lessons=lessons, quizzes=quizzes)

@app.route("/enrol/<int:course_id>", methods=["POST"])
@login_required
def enrol(course_id):
    c = db().execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    if not c: return "Course not found", 404
    try:
        db().execute("""INSERT INTO enrollments(user_id,course_id,status,created_at)
                        VALUES(?,?,?,?)""",(g.user["id"],course_id,"pending",datetime.utcnow().isoformat()))
        db().commit()
        flash("Enrolment request created. Submit payment to activate your course.")
    except sqlite3.IntegrityError:
        flash("You already requested this course.")
    return redirect(url_for("course", course_id=course_id))

@app.route("/lesson/<int:lesson_id>")
@login_required
def lesson(lesson_id):
    l = db().execute(
        "SELECT * FROM lessons WHERE id=?",
        (lesson_id,)
    ).fetchone()

    if not l:
        return "Lesson not found", 404

    course = db().execute(
        "SELECT * FROM courses WHERE id=?",
        (l["course_id"],)
    ).fetchone()

    if not course:
        return "Course not found", 404

    enrollment = db().execute(
        "SELECT * FROM enrollments WHERE user_id=? AND course_id=?",
        (g.user["id"], l["course_id"])
    ).fetchone()

    return render_template(
        "lesson.html",
        lesson=l,
        course=course,
        enrollment=enrollment
    )@app.route("/lesson/<int:lesson_id>/complete", methods=["POST"])
@login_required
def complete_lesson(lesson_id):
    l = db().execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    if not l: return "Lesson not found", 404
    if not db().execute("SELECT 1 FROM enrollments WHERE user_id=? AND course_id=? AND status='active'",
                         (g.user["id"],l["course_id"])).fetchone():
        flash("Your course must be activated before completing lessons.")
        return redirect(url_for("course", course_id=l["course_id"]))
    db().execute("""INSERT INTO lesson_progress(user_id,lesson_id,completed,completed_at)
                    VALUES(?,?,1,?) ON CONFLICT(user_id,lesson_id)
                    DO UPDATE SET completed=1, completed_at=excluded.completed_at""",
                 (g.user["id"],lesson_id,datetime.utcnow().isoformat()))
    db().commit()
    flash("Lesson marked complete.")
    return redirect(url_for("course", course_id=l["course_id"]))

@app.route("/quiz/<int:course_id>", methods=["GET","POST"])
@login_required
def quiz(course_id):
    if not db().execute("SELECT 1 FROM enrollments WHERE user_id=? AND course_id=? AND status='active'",
                         (g.user["id"],course_id)).fetchone():
        flash("Activate the course to take its quiz.")
        return redirect(url_for("course",course_id=course_id))
    questions = db().execute("SELECT * FROM quizzes WHERE course_id=? ORDER BY id",(course_id,)).fetchall()
    if request.method=="POST":
        score=0
        for q in questions:
            if request.form.get(f"q{q['id']}")==q["answer"]:
                score += 1
        db().execute("INSERT INTO quiz_attempts(user_id,quiz_id,score,attempted_at) VALUES(?,?,?,?)",
                     (g.user["id"], questions[0]["id"] if questions else 0, score, datetime.utcnow().isoformat()))
        db().commit()
        flash(f"Quiz submitted: {score}/{len(questions)}")
        return redirect(url_for("course",course_id=course_id))
    return render_template("quiz.html", questions=questions, course_id=course_id)

@app.route("/pay/<int:course_id>", methods=["GET","POST"])
@login_required
def pay(course_id):
    c=db().execute("SELECT * FROM courses WHERE id=?",(course_id,)).fetchone()
    if not c: return "Course not found",404
    if request.method=="POST":
        method=request.form["method"]
        ref=request.form["reference"].strip()
        db().execute("""INSERT INTO payments(user_id,course_id,method,reference,status,created_at)
                        VALUES(?,?,?,?,?,?)""",(g.user["id"],course_id,method,ref,"pending",datetime.utcnow().isoformat()))
        db().commit()
        flash("Payment details submitted. Your course will be activated after verification.")
        return redirect(url_for("dashboard"))
    return render_template("payment.html",course=c)

@app.route("/certificate/<int:course_id>")
@login_required
def certificate(course_id):
    c=db().execute("SELECT * FROM courses WHERE id=?",(course_id,)).fetchone()
    if not c: return "Course not found",404
    total=db().execute("SELECT COUNT(*) FROM lessons WHERE course_id=?",(course_id,)).fetchone()[0]
    done=db().execute("""SELECT COUNT(*) FROM lesson_progress p JOIN lessons l ON l.id=p.lesson_id
                         WHERE p.user_id=? AND l.course_id=? AND p.completed=1""",(g.user["id"],course_id)).fetchone()[0]
    if not total or done < total:
        flash("Complete all lessons to unlock your certificate.")
        return redirect(url_for("course",course_id=course_id))
    filename=os.path.join(CERT_DIR,f"certificate_{g.user['id']}_{course_id}.pdf")
    cpdf=canvas.Canvas(filename,pagesize=A4)
    w,h=A4
    cpdf.setStrokeColorRGB(0.04,0.14,0.30); cpdf.rect(35,35,w-70,h-70)
    cpdf.setFont("Helvetica-Bold",25); cpdf.drawCentredString(w/2,h-120,"EAGLE VISION ONLINE ACADEMY")
    cpdf.setFont("Helvetica",13); cpdf.drawCentredString(w/2,h-150,"Learn. Revise. Achieve.")
    cpdf.setFont("Helvetica-Bold",18); cpdf.drawCentredString(w/2,h-230,"CERTIFICATE OF COMPLETION")
    cpdf.setFont("Helvetica",14); cpdf.drawCentredString(w/2,h-290,"This certificate is proudly presented to")
    cpdf.setFont("Helvetica-Bold",22); cpdf.drawCentredString(w/2,h-335,g.user["full_name"])
    cpdf.setFont("Helvetica",14); cpdf.drawCentredString(w/2,h-390,"for successfully completing")
    cpdf.setFont("Helvetica-Bold",18); cpdf.drawCentredString(w/2,h-430,c["title"])
    cpdf.setFont("Helvetica",11); cpdf.drawCentredString(w/2,h-500,f"Date: {datetime.utcnow().date().isoformat()}")
    cpdf.drawCentredString(w/2,h-525,f"Certificate ID: EVA-{g.user['id']:04d}-{course_id:04d}")
    cpdf.save()
    return send_file(filename,as_attachment=True,download_name=os.path.basename(filename))

@app.route("/admin")
@admin_required
def admin():
    pending = db().execute("""SELECT p.*, u.full_name, u.email, c.title
                              FROM payments p JOIN users u ON u.id=p.user_id
                              JOIN courses c ON c.id=p.course_id
                              WHERE p.status='pending' ORDER BY p.id DESC""").fetchall()
    users=db().execute("SELECT id,full_name,email,phone,role,created_at FROM users ORDER BY id DESC").fetchall()
    courses=db().execute("SELECT * FROM courses ORDER BY id").fetchall()
    return render_template("admin.html",pending=pending,users=users,courses=courses)

@app.route("/admin/payment/<int:payment_id>/approve", methods=["POST"])
@admin_required
def approve_payment(payment_id):
    p=db().execute("SELECT * FROM payments WHERE id=?",(payment_id,)).fetchone()
    if p:
        db().execute("UPDATE payments SET status='approved' WHERE id=?",(payment_id,))
        db().execute("""UPDATE enrollments SET status='active' WHERE user_id=? AND course_id=?""",
                     (p["user_id"],p["course_id"]))
        db().commit()
        flash("Payment approved and course activated.")
    return redirect(url_for("admin"))

@app.route("/admin/course/<int:course_id>/toggle", methods=["POST"])
@admin_required
def toggle_course(course_id):
    db().execute("UPDATE courses SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(course_id,))
    db().commit()
    return redirect(url_for("admin"))

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True)
