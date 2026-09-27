import os
import sqlite3
from functools import wraps
from datetime import datetime, timedelta

from flask import (
    Flask,
    render_template,
    render_template_string,
    request,
    redirect,
    url_for,
    session,
    g,
    flash,
    Response,
)
from werkzeug.security import generate_password_hash, check_password_hash

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4


# ============================================================
# APP CONFIGURATION
# ============================================================

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "academy.db")
CERT_DIR = os.path.join(BASE, "certificates")

os.makedirs(CERT_DIR, exist_ok=True)

app = Flask(__name__)

# IMPORTANT:
# Set SECRET_KEY in Render environment variables for production.
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-in-render"
)


# ============================================================
# DATABASE
# ============================================================

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()


def ensure_column(conn, table, column, definition):
    """
    Safely add a column if an older database does not have it.
    This is important because your Render database may already exist.
    """
    columns = {
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in columns:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


# ============================================================
# DATABASE INITIALISATION
# ============================================================

def init_db():

    conn = get_db()

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            created_at TEXT NOT NULL
        )
        """
    )

    # Parent/guardian phone for existing installations
    ensure_column(
        conn,
        "users",
        "parent_phone",
        "TEXT"
    )

    # --------------------------------------------------------
    # COURSES
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS courses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    # Add price to older academy databases without changing existing data.
    ensure_column(
        conn,
        "courses",
        "price",
        "REAL NOT NULL DEFAULT 0"
    )

    # --------------------------------------------------------
    # LESSONS
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lessons(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(course_id) REFERENCES courses(id)
        )
        """
    )

    # --------------------------------------------------------
    # ENROLLMENTS
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS enrollments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            UNIQUE(user_id, course_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(course_id) REFERENCES courses(id)
        )
        """
    )

    # --------------------------------------------------------
    # LESSON PROGRESS
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lesson_progress(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            lesson_id INTEGER NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            completed_at TEXT,
            UNIQUE(user_id, lesson_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(lesson_id) REFERENCES lessons(id)
        )
        """
    )

    # --------------------------------------------------------
    # QUIZZES
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quizzes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            answer TEXT NOT NULL,
            FOREIGN KEY(course_id) REFERENCES courses(id)
        )
        """
    )

    # --------------------------------------------------------
    # QUIZ ATTEMPTS
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quiz_attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            quiz_id INTEGER NOT NULL,
            answer TEXT NOT NULL,
            correct INTEGER NOT NULL DEFAULT 0,
            attempted_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(quiz_id) REFERENCES quizzes(id)
        )
        """
    )

    # --------------------------------------------------------
    # PAYMENTS
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            reference TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(course_id) REFERENCES courses(id)
        )
        """
    )

    # --------------------------------------------------------
    # TEACHER COURSES
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_courses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            UNIQUE(teacher_id, course_id),
            FOREIGN KEY(teacher_id) REFERENCES users(id),
            FOREIGN KEY(course_id) REFERENCES courses(id)
        )
        """
    )

    # ========================================================
    # NEW STUDENT PARTICIPATION SYSTEM
    # ========================================================

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS student_activity(
            user_id INTEGER PRIMARY KEY,
            last_active TEXT NOT NULL,
            lessons_viewed INTEGER NOT NULL DEFAULT 0,
            lessons_completed INTEGER NOT NULL DEFAULT 0,
            quizzes_attempted INTEGER NOT NULL DEFAULT 0,
            activities_attempted INTEGER NOT NULL DEFAULT 0,
            last_course_id INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    ensure_column(
        conn,
        "student_activity",
        "activities_attempted",
        "INTEGER NOT NULL DEFAULT 0"
    )

    # --------------------------------------------------------
    # NOTIFICATIONS
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            notification_type TEXT NOT NULL DEFAULT 'info',
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    # --------------------------------------------------------
    # STUDENT REPORTS
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS student_reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_reply TEXT,
            created_at TEXT NOT NULL,
            replied_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    # --------------------------------------------------------
    # INTERACTIVE LESSON ACTIVITIES
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lesson_activities(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            answer TEXT NOT NULL,
            FOREIGN KEY(lesson_id) REFERENCES lessons(id)
        )
        """
    )

    # --------------------------------------------------------
    # ACTIVITY ATTEMPTS
    # --------------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            activity_id INTEGER NOT NULL,
            answer TEXT NOT NULL,
            correct INTEGER NOT NULL DEFAULT 0,
            attempted_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(activity_id) REFERENCES lesson_activities(id)
        )
        """
    )

    # ========================================================
    # COURSES
    # ========================================================

    courses = [
        (
            "Form 1 Mathematics",
            "Foundation mathematics for Form 1 students."
        ),
        (
            "Form 2 Mathematics",
            "Mathematics lessons for Form 2 students."
        ),
        (
            "Form 3 Mathematics",
            "Mathematics lessons for Form 3 students."
        ),
        (
            "O-Level Mathematics",
            "O-Level Mathematics revision and examination preparation."
        ),
        (
            "O-Level Science",
            "Science lessons and examination preparation."
        ),
        (
            "O-Level Geography",
            "Geography lessons, revision and examination preparation."
        ),
        (
            "A-Level History",
            "A-Level History lessons and examination preparation."
        ),
    ]

    course_prices = {
        "Form 1 Mathematics": 5,
        "Form 2 Mathematics": 5,
        "Form 3 Mathematics": 5,
        "O-Level Mathematics": 10,
        "O-Level Science": 10,
        "O-Level Geography": 10,
        "A-Level History": 10,
    }

    for title, description in courses:
        existing = conn.execute(
            "SELECT id FROM courses WHERE title=?",
            (title,)
        ).fetchone()

        if not existing:
            conn.execute(
                """
                INSERT INTO courses(title, description, price, active)
                VALUES(?,?,?,1)
                """,
                (title, description, course_prices.get(title, 0))
            )
        else:
            conn.execute(
                """
                UPDATE courses
                SET description=?,
                    price=?
                WHERE id=?
                """,
                (
                    description,
                    course_prices.get(title, 0),
                    existing["id"]
                )
            )

    # ========================================================
    # LESSON DATA
    # ========================================================

    lesson_data = {

        "Form 1 Mathematics": [
            (
                "Number Skills",
                """
                In this lesson students learn about whole numbers,
                place value, factors, multiples and basic operations.

                Remember to work carefully and show your working.
                """
            ),
            (
                "Fractions",
                """
                Fractions represent parts of a whole.

                Students should be able to identify proper fractions,
                improper fractions and mixed numbers and perform basic
                operations involving fractions.
                """
            ),
            (
                "Basic Algebra",
                """
                Algebra uses letters to represent unknown numbers.

                Learn how to simplify simple expressions and solve
                basic equations.
                """
            ),
        ],

        "Form 2 Mathematics": [
            (
                "Directed Numbers",
                """
                Directed numbers include positive and negative numbers.

                Learn how to add, subtract, multiply and divide
                directed numbers.
                """
            ),
            (
                "Algebraic Expressions",
                """
                Learn how to collect like terms, expand brackets and
                simplify algebraic expressions.
                """
            ),
            (
                "Ratio and Proportion",
                """
                Ratio compares quantities.

                Learn how to simplify ratios and solve basic
                proportion problems.
                """
            ),
        ],

        "Form 3 Mathematics": [
            (
                "Linear Equations",
                """
                Linear equations contain unknown quantities.

                Learn different techniques for solving equations.
                """
            ),
            (
                "Graphs",
                """
                Learn how to plot coordinates, draw straight-line
                graphs and interpret information from graphs.
                """
            ),
            (
                "Geometry",
                """
                Geometry deals with shapes, angles and properties
                of figures.

                Learn important angle rules and geometric facts.
                """
            ),
        ],

        "O-Level Mathematics": [
            (
                "Algebra Revision",
                """
                Revise algebraic expressions, equations, factorisation
                and simultaneous equations.
                """
            ),
            (
                "Statistics",
                """
                Revise mean, median, mode, range, frequency tables
                and interpretation of statistical information.
                """
            ),
            (
                "Trigonometry",
                """
                Revise sine, cosine and tangent and learn how to apply
                trigonometric ratios to examination questions.
                """
            ),
        ],

        "O-Level Science": [
            (
                "Cells",
                """
                Learn the structure and functions of plant and animal
                cells and understand the differences between them.
                """
            ),
            (
                "Forces",
                """
                A force is a push or pull.

                Learn about balanced forces, unbalanced forces,
                friction and effects of forces.
                """
            ),
            (
                "Energy",
                """
                Energy exists in different forms.

                Learn about energy transfers and conservation of energy.
                """
            ),
        ],

        "O-Level Geography": [
            (
                "Map Reading",
                """
                Learn grid references, scale, direction, symbols and
                other important map-reading skills.
                """
            ),
            (
                "Weather and Climate",
                """
                Study weather elements, weather instruments and
                factors affecting climate.
                """
            ),
            (
                "Population",
                """
                Study population distribution, density, growth,
                migration and population problems.
                """
            ),
        ],

        "A-Level History": [
            (
                "Nationalism",
                """
                Study the development of nationalism and factors that
                contributed to nationalist movements.
                """
            ),
            (
                "Colonialism",
                """
                Study colonial rule, its effects and the responses
                of African societies.
                """
            ),
            (
                "Independence",
                """
                Study the development of independence movements and
                the transition towards self-government.
                """
            ),
        ],
    }

    # Insert lesson data only where the course has no lessons yet.
    for course_title, lessons in lesson_data.items():

        course = conn.execute(
            "SELECT id FROM courses WHERE title=?",
            (course_title,)
        ).fetchone()

        if not course:
            continue

        course_id = course["id"]

        lesson_count = conn.execute(
            "SELECT COUNT(*) AS count FROM lessons WHERE course_id=?",
            (course_id,)
        ).fetchone()["count"]

        if lesson_count == 0:

            for position, (title, content) in enumerate(
                lessons,
                start=1
            ):
                conn.execute(
                    """
                    INSERT INTO lessons(
                        course_id,
                        title,
                        content,
                        position
                    )
                    VALUES(?,?,?,?)
                    """,
                    (
                        course_id,
                        title,
                        content.strip(),
                        position
                    )
                )

    # ========================================================
    # QUIZ SEED DATA
    # ========================================================

    quiz_data = {

        "Form 1 Mathematics": [
            (
                "What is 12 × 8?",
                "86",
                "96",
                "108",
                "88",
                "B"
            ),
            (
                "What is 45 ÷ 5?",
                "7",
                "8",
                "9",
                "10",
                "C"
            ),
            (
                "Which number is a factor of 24?",
                "5",
                "7",
                "8",
                "11",
                "C"
            ),
        ],

        "Form 2 Mathematics": [
            (
                "What is -5 + 8?",
                "13",
                "3",
                "-3",
                "-13",
                "B"
            ),
            (
                "Simplify: 3x + 2x",
                "5",
                "5x",
                "6x",
                "x",
                "B"
            ),
            (
                "What is the ratio 6:12 in simplest form?",
                "1:2",
                "2:1",
                "3:4",
                "6:2",
                "A"
            ),
        ],

        "Form 3 Mathematics": [
            (
                "Solve: x + 5 = 12",
                "5",
                "6",
                "7",
                "8",
                "C"
            ),
            (
                "Which point lies on the x-axis?",
                "(0,5)",
                "(5,0)",
                "(5,5)",
                "(1,5)",
                "B"
            ),
            (
                "How many degrees are in a straight angle?",
                "90",
                "180",
                "270",
                "360",
                "B"
            ),
        ],

        "O-Level Mathematics": [
            (
                "Solve: 2x = 10",
                "2",
                "5",
                "8",
                "10",
                "B"
            ),
            (
                "What is the mean of 2, 4 and 6?",
                "3",
                "4",
                "5",
                "6",
                "B"
            ),
            (
                "Which trigonometric ratio is opposite/hypotenuse?",
                "Cosine",
                "Tangent",
                "Sine",
                "Secant",
                "C"
            ),
        ],

        "O-Level Science": [
            (
                "Which organelle controls cell activities?",
                "Cell wall",
                "Nucleus",
                "Vacuole",
                "Cytoplasm",
                "B"
            ),
            (
                "What is a force?",
                "A type of energy",
                "A push or pull",
                "A type of matter",
                "A chemical",
                "B"
            ),
            (
                "Which is a form of energy?",
                "Mass",
                "Light",
                "Volume",
                "Density",
                "B"
            ),
        ],

        "O-Level Geography": [
            (
                "What does a map scale show?",
                "The colour of a map",
                "The relationship between map distance and ground distance",
                "The weather",
                "Population only",
                "B"
            ),
            (
                "Which instrument measures rainfall?",
                "Barometer",
                "Rain gauge",
                "Thermometer",
                "Wind vane",
                "B"
            ),
            (
                "What is population density?",
                "Number of births",
                "Number of people per unit area",
                "Number of migrants",
                "Number of houses",
                "B"
            ),
        ],

        "A-Level History": [
            (
                "What is nationalism?",
                "A system of farming",
                "A sense of loyalty to and identification with a nation",
                "A type of trade",
                "A weather pattern",
                "B"
            ),
            (
                "What is colonialism?",
                "Self-government",
                "Control of one territory by another power",
                "A type of election",
                "Industrial production",
                "B"
            ),
            (
                "What does independence mean in a political context?",
                "Foreign rule",
                "Self-government",
                "Migration",
                "Colonial expansion",
                "B"
            ),
        ],
    }

    for course_title, questions in quiz_data.items():

        course = conn.execute(
            "SELECT id FROM courses WHERE title=?",
            (course_title,)
        ).fetchone()

        if not course:
            continue

        course_id = course["id"]

        quiz_count = conn.execute(
            "SELECT COUNT(*) AS count FROM quizzes WHERE course_id=?",
            (course_id,)
        ).fetchone()["count"]

        if quiz_count == 0:

            for (
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                answer
            ) in questions:

                conn.execute(
                    """
                    INSERT INTO quizzes(
                        course_id,
                        question,
                        option_a,
                        option_b,
                        option_c,
                        option_d,
                        answer
                    )
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        course_id,
                        question,
                        option_a,
                        option_b,
                        option_c,
                        option_d,
                        answer
                    )
                )

    # ========================================================
    # ADMIN ACCOUNT
    # ========================================================

    admin_email = "admin@eaglevisionacademy.co.zw"

    admin = conn.execute(
        "SELECT id FROM users WHERE email=?",
        (admin_email,)
    ).fetchone()

    if not admin:

        conn.execute(
            """
            INSERT INTO users(
                full_name,
                email,
                phone,
                password_hash,
                role,
                created_at
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                "Eagle Vision Academy Admin",
                admin_email,
                "+263 71 741 0018",
                generate_password_hash("ChangeMe123!"),
                "admin",
                datetime.utcnow().isoformat()
            )
        )

    conn.commit()


# ============================================================
# INITIALISE DATABASE
# ============================================================

with app.app_context():
    init_db()


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    return get_db().execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,)
    ).fetchone()


def login_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        if not session.get("user_id"):
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped


def admin_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        user = current_user()

        if not user or user["role"] != "admin":
            flash("Administrator access required.", "danger")
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped


def teacher_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        user = current_user()

        if not user or user["role"] not in ("teacher", "admin"):
            flash("Teacher access required.", "danger")
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped


def touch_activity(course_id=None):

    user = current_user()

    if not user:
        return

    db = get_db()

    now = datetime.utcnow().isoformat()

    existing = db.execute(
        """
        SELECT user_id
        FROM student_activity
        WHERE user_id=?
        """,
        (user["id"],)
    ).fetchone()

    if existing:

        if course_id is not None:

            db.execute(
                """
                UPDATE student_activity
                SET last_active=?,
                    last_course_id=?
                WHERE user_id=?
                """,
                (
                    now,
                    course_id,
                    user["id"]
                )
            )

        else:

            db.execute(
                """
                UPDATE student_activity
                SET last_active=?
                WHERE user_id=?
                """,
                (
                    now,
                    user["id"]
                )
            )

    else:

        db.execute(
            """
            INSERT INTO student_activity(
                user_id,
                last_active,
                last_course_id
            )
            VALUES(?,?,?)
            """,
            (
                user["id"],
                now,
                course_id
            )
        )

    db.commit()


def add_notification(
    user_id,
    title,
    message,
    notification_type="info"
):

    db = get_db()

    db.execute(
        """
        INSERT INTO notifications(
            user_id,
            title,
            message,
            notification_type,
            is_read,
            created_at
        )
        VALUES(?,?,?,?,0,?)
        """,
        (
            user_id,
            title,
            message,
            notification_type,
            datetime.utcnow().isoformat()
        )
    )

    db.commit()


# ============================================================
# TEMPLATE CONTEXT
# ============================================================

@app.context_processor
def inject_globals():

    user = current_user()

    unread_notifications = 0

    if user:

        unread_notifications = get_db().execute(
            """
            SELECT COUNT(*)
            FROM notifications
            WHERE user_id=?
              AND is_read=0
            """,
            (user["id"],)
        ).fetchone()[0]

    return {
        "current_user": user,
        "unread_notifications": unread_notifications,
        "now": datetime.utcnow()
    }


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    db = get_db()

    courses = db.execute(
        """
        SELECT *
        FROM courses
        WHERE active=1
        ORDER BY id
        """
    ).fetchall()

    return render_template(
        "index.html",
        courses=courses
    )


# ============================================================
# ROBOTS.TXT
# ============================================================

@app.route("/robots.txt")
def robots():

    return Response(
        "User-agent: *\nAllow: /\nSitemap: "
        + url_for("sitemap", _external=True)
        + "\n",
        mimetype="text/plain"
    )


# ============================================================
# SITEMAP
# ============================================================

@app.route("/sitemap.xml")
def sitemap():

    pages = [
        url_for("index", _external=True),
        url_for("login", _external=True),
        url_for("register", _external=True),
    ]

    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]

    for page in pages:

        xml.append(
            "<url><loc>"
            + page
            + "</loc></url>"
        )

    xml.append("</urlset>")

    return Response(
        "\n".join(xml),
        mimetype="application/xml"
    )

# ============================================================
# REGISTRATION
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        full_name = request.form.get(
            "full_name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        parent_phone = request.form.get(
            "parent_phone",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        # --------------------------------------------
        # VALIDATION
        # --------------------------------------------

        if not full_name or not email or not password:

            flash(
                "Please complete all required fields.",
                "danger"
            )

            return redirect(
                url_for("register")
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "danger"
            )

            return redirect(
                url_for("register")
            )

        if len(password) < 6:

            flash(
                "Password must contain at least 6 characters.",
                "danger"
            )

            return redirect(
                url_for("register")
            )

        db = get_db()

        existing = db.execute(
            """
            SELECT id
            FROM users
            WHERE email=?
            """,
            (email,)
        ).fetchone()

        if existing:

            flash(
                "An account with that email already exists.",
                "warning"
            )

            return redirect(
                url_for("login")
            )

        # --------------------------------------------
        # CREATE STUDENT
        # --------------------------------------------

        db.execute(
            """
            INSERT INTO users(
                full_name,
                email,
                phone,
                parent_phone,
                password_hash,
                role,
                created_at
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                full_name,
                email,
                phone,
                parent_phone,
                generate_password_hash(password),
                "student",
                datetime.utcnow().isoformat()
            )
        )

        db.commit()

        flash(
            "Registration successful. Please log in.",
            "success"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


# ============================================================
# PARENT / GUARDIAN CONTACT
# ============================================================

@app.route(
    "/parent-contact",
    methods=["GET", "POST"]
)
@login_required
def parent_contact():

    user = current_user()

    if request.method == "POST":

        parent_phone = request.form.get(
            "parent_phone",
            ""
        ).strip()

        db = get_db()

        db.execute(
            """
            UPDATE users
            SET parent_phone=?
            WHERE id=?
            """,
            (
                parent_phone,
                user["id"]
            )
        )

        db.commit()

        flash(
            "Parent/guardian contact updated successfully.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "parent_contact.html",
        user=user
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        if not email or not password:

            flash(
                "Please enter your email and password.",
                "danger"
            )

            return redirect(
                url_for("login")
            )

        db = get_db()

        user = db.execute(
            """
            SELECT *
            FROM users
            WHERE email=?
            """,
            (email,)
        ).fetchone()

        if not user:

            flash(
                "Invalid email or password.",
                "danger"
            )

            return redirect(
                url_for("login")
            )

        if not check_password_hash(
            user["password_hash"],
            password
        ):

            flash(
                "Invalid email or password.",
                "danger"
            )

            return redirect(
                url_for("login")
            )

        session.clear()

        session["user_id"] = user["id"]

        touch_activity()

        flash(
            "Welcome back, " + user["full_name"] + "!",
            "success"
        )

        # --------------------------------------------
        # SEND EACH ROLE TO ITS DASHBOARD
        # --------------------------------------------

        if user["role"] == "admin":

            return redirect(
                url_for("admin")
            )

        if user["role"] == "teacher":

            return redirect(
                url_for("teacher_dashboard")
            )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "login.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(
        url_for("index")
    )


# ============================================================
# STUDENT DASHBOARD
# ============================================================

@app.route("/dashboard")
@login_required
def dashboard():

    user = current_user()

    db = get_db()

    touch_activity()

    # --------------------------------------------------------
    # ACTIVE / APPROVED ENROLMENTS
    # --------------------------------------------------------

    enrolled_courses = db.execute(
        """
        SELECT
            c.*,
            e.id AS enrollment_id,
            e.status AS enrollment_status,
            e.created_at AS enrolled_at
        FROM courses c
        JOIN enrollments e
            ON e.course_id = c.id
        WHERE e.user_id=?
          AND e.status='active'
        ORDER BY c.id
        """,
        (user["id"],)
    ).fetchall()

    # --------------------------------------------------------
    # PENDING ENROLMENTS
    # --------------------------------------------------------

    pending_courses = db.execute(
        """
        SELECT
            c.*,
            e.id AS enrollment_id,
            e.status AS enrollment_status,
            e.created_at AS enrolled_at
        FROM courses c
        JOIN enrollments e
            ON e.course_id = c.id
        WHERE e.user_id=?
          AND e.status='pending'
        ORDER BY c.id
        """,
        (user["id"],)
    ).fetchall()

    # --------------------------------------------------------
    # ALL COURSES
    # --------------------------------------------------------

    courses = db.execute(
        """
        SELECT *
        FROM courses
        WHERE active=1
        ORDER BY id
        """
    ).fetchall()

    # --------------------------------------------------------
    # COURSE STATUS MAP
    # --------------------------------------------------------

    statuses = {}

    rows = db.execute(
        """
        SELECT course_id, status
        FROM enrollments
        WHERE user_id=?
        """,
        (user["id"],)
    ).fetchall()

    for row in rows:

        statuses[row["course_id"]] = row["status"]

    # --------------------------------------------------------
    # STUDENT ACTIVITY
    # --------------------------------------------------------

    activity = db.execute(
        """
        SELECT *
        FROM student_activity
        WHERE user_id=?
        """,
        (user["id"],)
    ).fetchone()

    # --------------------------------------------------------
    # NOTIFICATIONS
    # --------------------------------------------------------

    notifications = db.execute(
        """
        SELECT *
        FROM notifications
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 5
        """,
        (user["id"],)
    ).fetchall()

    # --------------------------------------------------------
    # RETURN DASHBOARD
    # --------------------------------------------------------

    return render_template(
        "dashboard.html",
        user=user,
        courses=courses,
        enrolled_courses=enrolled_courses,
        pending_courses=pending_courses,
        statuses=statuses,
        activity=activity,
        notifications=notifications
    )


# ============================================================
# COURSE PAGE
# ============================================================

@app.route("/course/<int:course_id>")
@login_required
def course(course_id):

    user = current_user()

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    # --------------------------------------------------------
    # CHECK ENROLMENT
    # --------------------------------------------------------

    enrollment = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
        """,
        (
            user["id"],
            course_id
        )
    ).fetchone()

    # --------------------------------------------------------
    # LESSONS
    # --------------------------------------------------------

    lessons = db.execute(
        """
        SELECT
            l.*,
            COALESCE(
                lp.completed,
                0
            ) AS completed
        FROM lessons l
        LEFT JOIN lesson_progress lp
            ON lp.lesson_id=l.id
           AND lp.user_id=?
        WHERE l.course_id=?
        ORDER BY l.position, l.id
        """,
        (
            user["id"],
            course_id
        )
    ).fetchall()

    # --------------------------------------------------------
    # PROGRESS
    # --------------------------------------------------------

    total_lessons = len(lessons)

    completed_lessons = sum(
        1
        for lesson in lessons
        if lesson["completed"]
    )

    if total_lessons:

        progress = int(
            completed_lessons
            * 100
            / total_lessons
        )

    else:

        progress = 0

    touch_activity(course_id)

    return render_template(
        "course.html",
        course=course,
        enrollment=enrollment,
        lessons=lessons,
        total_lessons=total_lessons,
        completed_lessons=completed_lessons,
        progress=progress
    )


# ============================================================
# ENROL IN COURSE
# ============================================================

@app.route(
    "/enrol/<int:course_id>",
    methods=["GET", "POST"]
)
@login_required
def enrol(course_id):

    user = current_user()

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
          AND active=1
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found or unavailable.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    existing = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
        """,
        (
            user["id"],
            course_id
        )
    ).fetchone()

    if existing:

        if existing["status"] == "active":

            flash(
                "You are already enrolled in this course.",
                "info"
            )

            return redirect(
                url_for(
                    "course",
                    course_id=course_id
                )
            )

        if existing["status"] == "pending":

            flash(
                "Your enrolment request is already pending.",
                "info"
            )

            return redirect(
                url_for(
                    "course",
                    course_id=course_id
                )
            )

    # --------------------------------------------------------
    # CREATE ENROLMENT REQUEST
    # --------------------------------------------------------

    db.execute(
        """
        INSERT INTO enrollments(
            user_id,
            course_id,
            status,
            created_at
        )
        VALUES(?,?,?,?)
        """,
        (
            user["id"],
            course_id,
            "pending",
            datetime.utcnow().isoformat()
        )
    )

    db.commit()

    # --------------------------------------------------------
    # NOTIFY ADMIN
    # --------------------------------------------------------

    admins = db.execute(
        """
        SELECT id
        FROM users
        WHERE role='admin'
        """
    ).fetchall()

    for admin_user in admins:

        add_notification(
            admin_user["id"],
            "New Enrolment Request",
            (
                user["full_name"]
                + " requested enrolment in "
                + course["title"]
                + "."
            ),
            "enrolment"
        )

    flash(
        "Enrolment request submitted. "
        "Please complete payment and wait for approval.",
        "success"
    )

    return redirect(
        url_for(
            "course",
            course_id=course_id
        )
    )


# ============================================================
# PAYMENT SUBMISSION
# ============================================================

@app.route(
    "/pay/<int:course_id>",
    methods=["GET", "POST"]
)
@login_required
def pay(course_id):

    user = current_user()

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    enrollment = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
        """,
        (
            user["id"],
            course_id
        )
    ).fetchone()

    if not enrollment:

        flash(
            "Please request enrolment before submitting payment.",
            "warning"
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id
            )
        )

    if request.method == "POST":

        amount_raw = request.form.get(
            "amount",
            ""
        ).strip()

        reference = request.form.get(
            "reference",
            ""
        ).strip()

        try:

            amount = float(amount_raw)

        except (TypeError, ValueError):

            flash(
                "Please enter a valid payment amount.",
                "danger"
            )

            return redirect(
                url_for(
                    "pay",
                    course_id=course_id
                )
            )

        if amount <= 0:

            flash(
# ============================================================
# PAYMENT SUBMISSION
# ============================================================

@app.route(
    "/pay/<int:course_id>",
    methods=["GET", "POST"]
)
@login_required
def pay(course_id):

    user = current_user()

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    enrollment = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
        """,
        (
            user["id"],
            course_id
        )
    ).fetchone()

    if not enrollment:

        flash(
            "Please request enrolment before submitting payment.",
            "warning"
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id
            )
        )

    if request.method == "POST":

        reference = request.form.get(
            "reference",
            ""
        ).strip()

        # Automatically use the price of the selected course
        try:
            amount = float(course["price"] or 0)
        except (TypeError, ValueError):
            amount = 0

        if amount <= 0:

            flash(
                "This course does not have a valid price.",
                "danger"
            )

            return redirect(
                url_for(
                    "pay",
                    course_id=course_id
                )
            )

        db.execute(
            """
            INSERT INTO payments(
                user_id,
                course_id,
                amount,
                reference,
                status,
                created_at
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                user["id"],
                course_id,
                amount,
                reference,
                "pending",
                datetime.utcnow().isoformat()
            )
        )

        db.commit()

        flash(
            "Payment submitted successfully. It is waiting for verification.",
            "success"
        )

        return redirect(
            url_for("dashboard")
    )
        # ----------------------------------------------------
        # ADMIN NOTIFICATION
        # ----------------------------------------------------

        admins = db.execute(
            """
            SELECT id
            FROM users
            WHERE role='admin'
            """
        ).fetchall()

        for admin_user in admins:

            add_notification(
                admin_user["id"],
                "New Payment Submitted",
                (
                    user["full_name"]
                    + " submitted a payment for "
                    + course["title"]
                    + "."
                ),
                "payment"
            )

        flash(
            "Payment submitted successfully. "
            "Please wait for administrator approval.",
            "success"
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id
            )
        )

    return render_template(
        "payment.html",
        course=course,
        enrollment=enrollment
    )


# ============================================================
# CERTIFICATE
# ============================================================

@app.route(
    "/certificate/<int:course_id>"
)
@login_required
def certificate(course_id):

    user = current_user()

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    enrollment = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
          AND status='active'
        """,
        (
            user["id"],
            course_id
        )
    ).fetchone()

    if not enrollment:

        flash(
            "You are not actively enrolled in this course.",
            "warning"
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id
            )
        )

    lessons = db.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(
                CASE
                    WHEN lp.completed=1
                    THEN 1
                    ELSE 0
                END
            ) AS completed
        FROM lessons l
        LEFT JOIN lesson_progress lp
            ON lp.lesson_id=l.id
           AND lp.user_id=?
        WHERE l.course_id=?
        """,
        (
            user["id"],
            course_id
        )
    ).fetchone()

    total = lessons["total"] or 0
    completed = lessons["completed"] or 0

    if total == 0 or completed < total:

        flash(
            "Complete all course lessons before generating your certificate.",
            "warning"
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id
            )
        )

    # --------------------------------------------------------
    # GENERATE PDF
    # --------------------------------------------------------

    filename = (
        "certificate_"
        + str(user["id"])
        + "_"
        + str(course_id)
        + ".pdf"
    )

    path = os.path.join(
        CERT_DIR,
        filename
    )

    pdf = canvas.Canvas(
        path,
        pagesize=A4
    )

    width, height = A4

    pdf.setFont(
        "Helvetica-Bold",
        28
    )

    pdf.drawCentredString(
        width / 2,
        height - 150,
        "EAGLE VISION ONLINE ACADEMY"
    )

    pdf.setFont(
        "Helvetica-Bold",
        22
    )

    pdf.drawCentredString(
        width / 2,
        height - 220,
        "CERTIFICATE OF COMPLETION"
    )

    pdf.setFont(
        "Helvetica",
        16
    )

    pdf.drawCentredString(
        width / 2,
        height - 290,
        "This certificate is proudly presented to"
    )

    pdf.setFont(
        "Helvetica-Bold",
        24
    )

    pdf.drawCentredString(
        width / 2,
        height - 340,
        user["full_name"]
    )

    pdf.setFont(
        "Helvetica",
        16
    )

    pdf.drawCentredString(
        width / 2,
        height - 400,
        "for successfully completing"
    )

    pdf.setFont(
        "Helvetica-Bold",
        20
    )

    pdf.drawCentredString(
        width / 2,
        height - 440,
        course["title"]
    )

    pdf.setFont(
        "Helvetica",
        13
    )

    pdf.drawCentredString(
        width / 2,
        height - 500,
        "Learn. Revise. Achieve."
    )

    pdf.drawCentredString(
        width / 2,
        height - 550,
        datetime.utcnow().strftime(
            "%d %B %Y"
        )
    )

    pdf.save()

    return Response(
        open(path, "rb").read(),
        mimetype="application/pdf",
        headers={
            "Content-Disposition":
                "attachment; filename="
                + filename
        }
    )


# ============================================================
# VIEW CERTIFICATE
# ============================================================

@app.route(
    "/my-certificate/<int:course_id>"
)
@login_required
def my_certificate(course_id):

    user = current_user()

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "certificate.html",
        course=course,
        user=user
    )

# ============================================================
# LESSON
# ============================================================

@app.route("/lesson/<int:lesson_id>")
@login_required
def lesson(lesson_id):

    user = current_user()

    db = get_db()

    # --------------------------------------------------------
    # GET LESSON
    # --------------------------------------------------------

    lesson_row = db.execute(
        """
        SELECT
            l.*,
            c.title AS course_title,
            c.id AS course_id
        FROM lessons l
        JOIN courses c
            ON c.id=l.course_id
        WHERE l.id=?
        """,
        (lesson_id,)
    ).fetchone()

    if not lesson_row:

        flash(
            "Lesson not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    # --------------------------------------------------------
    # CHECK ACTIVE ENROLMENT
    # --------------------------------------------------------

    enrollment = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
          AND status='active'
        """,
        (
            user["id"],
            lesson_row["course_id"]
        )
    ).fetchone()

    if not enrollment:

        flash(
            "You must be actively enrolled in this course.",
            "warning"
        )

        return redirect(
            url_for(
                "course",
                course_id=lesson_row["course_id"]
            )
        )

    # --------------------------------------------------------
    # GET PROGRESS
    # --------------------------------------------------------

    progress = db.execute(
        """
        SELECT *
        FROM lesson_progress
        WHERE user_id=?
          AND lesson_id=?
        """,
        (
            user["id"],
            lesson_id
        )
    ).fetchone()

    # --------------------------------------------------------
    # PREVIOUS AND NEXT LESSON
    # --------------------------------------------------------

    previous_lesson = db.execute(
        """
        SELECT id, title
        FROM lessons
        WHERE course_id=?
          AND position < ?
        ORDER BY position DESC
        LIMIT 1
        """,
        (
            lesson_row["course_id"],
            lesson_row["position"]
        )
    ).fetchone()

    next_lesson = db.execute(
        """
        SELECT id, title
        FROM lessons
        WHERE course_id=?
          AND position > ?
        ORDER BY position ASC
        LIMIT 1
        """,
        (
            lesson_row["course_id"],
            lesson_row["position"]
        )
    ).fetchone()

    # --------------------------------------------------------
    # LESSON ACTIVITIES
    # --------------------------------------------------------

    activities = db.execute(
        """
        SELECT *
        FROM lesson_activities
        WHERE lesson_id=?
        ORDER BY id
        """,
        (lesson_id,)
    ).fetchall()

    touch_activity(
        lesson_row["course_id"]
    )

    # Count lesson view
    db.execute(
        """
        UPDATE student_activity
        SET lessons_viewed=lessons_viewed + 1,
            last_active=?
        WHERE user_id=?
        """,
        (
            datetime.utcnow().isoformat(),
            user["id"]
        )
    )

    db.commit()

    return render_template(
        "lesson.html",
        lesson=lesson_row,
        progress=progress,
        previous_lesson=previous_lesson,
        next_lesson=next_lesson,
        activities=activities
    )


# ============================================================
# COMPLETE LESSON
# ============================================================

@app.route(
    "/lesson/<int:lesson_id>/complete",
    methods=["POST", "GET"]
)
@login_required
def complete_lesson(lesson_id):

    user = current_user()

    db = get_db()

    lesson_row = db.execute(
        """
        SELECT *
        FROM lessons
        WHERE id=?
        """,
        (lesson_id,)
    ).fetchone()

    if not lesson_row:

        flash(
            "Lesson not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    # --------------------------------------------------------
    # CHECK ENROLMENT
    # --------------------------------------------------------

    enrollment = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
          AND status='active'
        """,
        (
            user["id"],
            lesson_row["course_id"]
        )
    ).fetchone()

    if not enrollment:

        flash(
            "You are not actively enrolled in this course.",
            "warning"
        )

        return redirect(
            url_for("dashboard")
        )

    # --------------------------------------------------------
    # CHECK EXISTING PROGRESS
    # --------------------------------------------------------

    existing = db.execute(
        """
        SELECT *
        FROM lesson_progress
        WHERE user_id=?
          AND lesson_id=?
        """,
        (
            user["id"],
            lesson_id
        )
    ).fetchone()

    if existing:

        db.execute(
            """
            UPDATE lesson_progress
            SET completed=1,
                completed_at=?
            WHERE user_id=?
              AND lesson_id=?
            """,
            (
                datetime.utcnow().isoformat(),
                user["id"],
                lesson_id
            )
        )

    else:

        db.execute(
            """
            INSERT INTO lesson_progress(
                user_id,
                lesson_id,
                completed,
                completed_at
            )
            VALUES(?,?,1,?)
            """,
            (
                user["id"],
                lesson_id,
                datetime.utcnow().isoformat()
            )
        )

        db.execute(
            """
            UPDATE student_activity
            SET lessons_completed=lessons_completed + 1,
                last_active=?
            WHERE user_id=?
            """,
            (
                datetime.utcnow().isoformat(),
                user["id"]
            )
        )

    db.commit()

    # --------------------------------------------------------
    # CHECK COURSE COMPLETION
    # --------------------------------------------------------

    totals = db.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(
                CASE
                    WHEN lp.completed=1
                    THEN 1
                    ELSE 0
                END
            ) AS completed
        FROM lessons l
        LEFT JOIN lesson_progress lp
            ON lp.lesson_id=l.id
           AND lp.user_id=?
        WHERE l.course_id=?
        """,
        (
            user["id"],
            lesson_row["course_id"]
        )
    ).fetchone()

    total = totals["total"] or 0
    completed = totals["completed"] or 0

    if total > 0 and completed >= total:

        add_notification(
            user["id"],
            "Course Lessons Completed",
            "You have completed all lessons in this course. "
            "You can now take the course quiz.",
            "success"
        )

    flash(
        "Lesson marked as complete.",
        "success"
    )

    return redirect(
        url_for(
            "lesson",
            lesson_id=lesson_id
        )
    )


# ============================================================
# LESSON ACTIVITY
# ============================================================

@app.route(
    "/lesson/<int:lesson_id>/activity",
    methods=["POST"]
)
@login_required
def lesson_activity(lesson_id):

    user = current_user()

    db = get_db()

    lesson_row = db.execute(
        """
        SELECT *
        FROM lessons
        WHERE id=?
        """,
        (lesson_id,)
    ).fetchone()

    if not lesson_row:

        flash(
            "Lesson not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    enrollment = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
          AND status='active'
        """,
        (
            user["id"],
            lesson_row["course_id"]
        )
    ).fetchone()

    if not enrollment:

        flash(
            "You must be enrolled in this course.",
            "warning"
        )

        return redirect(
            url_for("dashboard")
        )

    # --------------------------------------------------------
    # PROCESS EACH ACTIVITY ANSWER
    # --------------------------------------------------------

    activity_ids = request.form.getlist(
        "activity_id"
    )

    score = 0
    total = 0

    for activity_id in activity_ids:

        activity = db.execute(
            """
            SELECT *
            FROM lesson_activities
            WHERE id=?
              AND lesson_id=?
            """,
            (
                activity_id,
                lesson_id
            )
        ).fetchone()

        if not activity:
            continue

        answer = request.form.get(
            "answer_" + str(activity_id),
            ""
        ).strip().upper()

        if not answer:
            continue

        total += 1

        correct = 1 if answer == activity["answer"].upper() else 0

        if correct:
            score += 1

        db.execute(
            """
            INSERT INTO activity_attempts(
                user_id,
                activity_id,
                answer,
                correct,
                attempted_at
            )
            VALUES(?,?,?,?,?)
            """,
            (
                user["id"],
                activity_id,
                answer,
                correct,
                datetime.utcnow().isoformat()
            )
        )

    # --------------------------------------------------------
    # UPDATE PARTICIPATION
    # --------------------------------------------------------

    db.execute(
        """
        UPDATE student_activity
        SET activities_attempted=
                activities_attempted + ?,
            last_active=?
        WHERE user_id=?
        """,
        (
            total,
            datetime.utcnow().isoformat(),
            user["id"]
        )
    )

    db.commit()

    if total > 0:

        flash(
            "Activity result: "
            + str(score)
            + "/"
            + str(total),
            "success"
        )

    else:

        flash(
            "No activity answers were submitted.",
            "warning"
        )

    return redirect(
        url_for(
            "lesson",
            lesson_id=lesson_id
        )
    )


# ============================================================
# QUIZ
# ============================================================

@app.route(
    "/quiz/<int:course_id>",
    methods=["GET", "POST"]
)
@login_required
def quiz(course_id):

    user = current_user()

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    # --------------------------------------------------------
    # CHECK ACTIVE ENROLMENT
    # --------------------------------------------------------

    enrollment = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
          AND status='active'
        """,
        (
            user["id"],
            course_id
        )
    ).fetchone()

    if not enrollment:

        flash(
            "You must be actively enrolled in this course.",
            "warning"
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id
            )
        )

    # --------------------------------------------------------
    # GET QUIZ QUESTIONS
    # --------------------------------------------------------

    questions = db.execute(
        """
        SELECT *
        FROM quizzes
        WHERE course_id=?
        ORDER BY id
        """,
        (course_id,)
    ).fetchall()

    if not questions:

        flash(
            "There are no quiz questions available for this course yet.",
            "info"
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id
            )
        )

    # --------------------------------------------------------
    # SUBMIT QUIZ
    # --------------------------------------------------------

    if request.method == "POST":

        score = 0
        total = len(questions)

        for question in questions:

            answer = request.form.get(
                "question_" + str(question["id"]),
                ""
            ).strip().upper()

            correct = (
                1
                if answer == question["answer"].upper()
                else 0
            )

            if correct:
                score += 1

            db.execute(
                """
                INSERT INTO quiz_attempts(
                    user_id,
                    quiz_id,
                    answer,
                    correct,
                    attempted_at
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    user["id"],
                    question["id"],
                    answer,
                    correct,
                    datetime.utcnow().isoformat()
                )
            )

        # ----------------------------------------------------
        # UPDATE PARTICIPATION
        # ----------------------------------------------------

        db.execute(
            """
            UPDATE student_activity
            SET quizzes_attempted=
                    quizzes_attempted + 1,
                last_active=?
            WHERE user_id=?
            """,
            (
                datetime.utcnow().isoformat(),
                user["id"]
            )
        )

        db.commit()

        percentage = 0

        if total:

            percentage = round(
                (score / total) * 100,
                1
            )

        # ----------------------------------------------------
        # SAVE RESULT IN SESSION
        # ----------------------------------------------------

        session[
            "last_quiz_result"
        ] = {
            "course_id": course_id,
            "course_title": course["title"],
            "score": score,
            "total": total,
            "percentage": percentage
        }

        add_notification(
            user["id"],
            "Quiz Completed",
            (
                "You scored "
                + str(score)
                + "/"
                + str(total)
                + " ("
                + str(percentage)
                + "%) in "
                + course["title"]
                + "."
            ),
            "quiz"
        )

        return redirect(
            url_for(
                "results",
                course_id=course_id
            )
        )

    touch_activity(course_id)

    return render_template(
        "quiz.html",
        course=course,
        questions=questions
    )


# ============================================================
# QUIZ RESULTS
# ============================================================

@app.route(
    "/results/<int:course_id>"
)
@login_required
def results(course_id):

    user = current_user()

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    # --------------------------------------------------------
    # GET LAST QUIZ ATTEMPT
    # --------------------------------------------------------

    latest_attempts = db.execute(
        """
        SELECT
            qa.*,
            q.question
        FROM quiz_attempts qa
        JOIN quizzes q
            ON q.id=qa.quiz_id
        WHERE qa.user_id=?
          AND q.course_id=?
        ORDER BY qa.id DESC
        """,
        (
            user["id"],
            course_id
        )
    ).fetchall()

    # --------------------------------------------------------
    # GET MOST RECENT COMPLETE ATTEMPT
    # --------------------------------------------------------

    questions_count = db.execute(
        """
        SELECT COUNT(*)
        FROM quizzes
        WHERE course_id=?
        """,
        (course_id,)
    ).fetchone()[0]

    score = 0
    total = questions_count

    result = session.get(
        "last_quiz_result"
    )

    if (
        result
        and result.get("course_id") == course_id
    ):

        score = result.get(
            "score",
            0
        )

        total = result.get(
            "total",
            questions_count
        )

        percentage = result.get(
            "percentage",
            0
        )

    else:

        # ----------------------------------------------------
        # FALLBACK: CALCULATE FROM LATEST QUESTIONS
        # ----------------------------------------------------

        if latest_attempts and questions_count:

            # Get the latest answer for every question
            latest_by_question = {}

            for attempt in latest_attempts:

                question_id = attempt["quiz_id"]

                if question_id not in latest_by_question:

                    latest_by_question[
                        question_id
                    ] = attempt

            score = sum(
                1
                for attempt
                in latest_by_question.values()
                if attempt["correct"]
            )

            total = questions_count

            percentage = round(
                (score / total) * 100,
                1
            )

        else:

            percentage = 0

    # --------------------------------------------------------
    # PASS / REVIEW MESSAGE
    # --------------------------------------------------------

    if percentage >= 50:

        result_message = (
            "Well done! You have passed this assessment."
        )

    else:

        result_message = (
            "Keep studying and try the assessment again."
        )

    return render_template(
        "results.html",
        course=course,
        score=score,
        total=total,
        percentage=percentage,
        result_message=result_message,
        attempts=latest_attempts
    )


# ============================================================
# NOTIFICATIONS
# ============================================================

@app.route("/notifications")
@login_required
def notifications():

    user = current_user()

    db = get_db()

    notifications_list = db.execute(
        """
        SELECT *
        FROM notifications
        WHERE user_id=?
        ORDER BY id DESC
        """,
        (user["id"],)
    ).fetchall()

    # Mark notifications as read
    db.execute(
        """
        UPDATE notifications
        SET is_read=1
        WHERE user_id=?
        """,
        (user["id"],)
    )

    db.commit()

    return render_template(
        "notifications.html",
        notifications=notifications_list
    )


# ============================================================
# STUDENT REPORT / CONTACT ADMIN
# ============================================================

@app.route(
    "/report-admin",
    methods=["GET", "POST"]
)
@login_required
def report_admin():

    user = current_user()

    db = get_db()

    if request.method == "POST":

        subject = request.form.get(
            "subject",
            ""
        ).strip()

        message = request.form.get(
            "message",
            ""
        ).strip()

        if not subject or not message:

            flash(
                "Please provide a subject and message.",
                "danger"
            )

            return redirect(
                url_for("report_admin")
            )

        db.execute(
            """
            INSERT INTO student_reports(
                user_id,
                subject,
                message,
                status,
                created_at
            )
            VALUES(?,?,?,?,?)
            """,
            (
                user["id"],
                subject,
                message,
                "pending",
                datetime.utcnow().isoformat()
            )
        )

        db.commit()

        # Notify administrators
        admins = db.execute(
            """
            SELECT id
            FROM users
            WHERE role='admin'
            """
        ).fetchall()

        for admin_user in admins:

            add_notification(
                admin_user["id"],
                "New Student Report",
                (
                    user["full_name"]
                    + " submitted a report: "
                    + subject
                ),
                "report"
            )

        flash(
            "Your report has been sent to the administrator.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    reports = db.execute(
        """
        SELECT *
        FROM student_reports
        WHERE user_id=?
        ORDER BY id DESC
        """,
        (user["id"],)
    ).fetchall()

    return render_template(
        "report_admin.html",
        reports=reports
        )

# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
@admin_required
def admin():

    db = get_db()

    # --------------------------------------------------------
    # COUNTS
    # --------------------------------------------------------

    student_count = db.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE role='student'
        """
    ).fetchone()[0]

    teacher_count = db.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE role='teacher'
        """
    ).fetchone()[0]

    course_count = db.execute(
        """
        SELECT COUNT(*)
        FROM courses
        """
    ).fetchone()[0]

    pending_payments = db.execute(
        """
        SELECT COUNT(*)
        FROM payments
        WHERE status='pending'
        """
    ).fetchone()[0]

    pending_enrolments = db.execute(
        """
        SELECT COUNT(*)
        FROM enrollments
        WHERE status='pending'
        """
    ).fetchone()[0]

    pending_reports = db.execute(
        """
        SELECT COUNT(*)
        FROM student_reports
        WHERE status='pending'
        """
    ).fetchone()[0]

    # --------------------------------------------------------
    # RECENT PAYMENTS
    # --------------------------------------------------------

    payments = db.execute(
        """
        SELECT
            p.*,
            u.full_name,
            u.email,
            c.title AS course_title
        FROM payments p
        JOIN users u
            ON u.id=p.user_id
        JOIN courses c
            ON c.id=p.course_id
        ORDER BY p.id DESC
        LIMIT 20
        """
    ).fetchall()

    # --------------------------------------------------------
    # RECENT ENROLMENTS
    # --------------------------------------------------------

    enrolments = db.execute(
        """
        SELECT
            e.*,
            u.full_name,
            u.email,
            c.title AS course_title
        FROM enrollments e
        JOIN users u
            ON u.id=e.user_id
        JOIN courses c
            ON c.id=e.course_id
        ORDER BY e.id DESC
        LIMIT 20
        """
    ).fetchall()

    return render_template(
        "admin.html",
        student_count=student_count,
        teacher_count=teacher_count,
        course_count=course_count,
        pending_payments=pending_payments,
        pending_enrolments=pending_enrolments,
        pending_reports=pending_reports,
        payments=payments,
        enrolments=enrolments
    )


# ============================================================
# APPROVE PAYMENT
# ============================================================

@app.route(
    "/admin/payment/<int:payment_id>/approve",
    methods=["POST", "GET"]
)
@admin_required
def approve_payment(payment_id):

    db = get_db()

    payment = db.execute(
        """
        SELECT
            p.*,
            u.full_name,
            u.email,
            c.title AS course_title
        FROM payments p
        JOIN users u
            ON u.id=p.user_id
        JOIN courses c
            ON c.id=p.course_id
        WHERE p.id=?
        """,
        (payment_id,)
    ).fetchone()

    if not payment:

        flash(
            "Payment not found.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )

    # --------------------------------------------------------
    # APPROVE PAYMENT
    # --------------------------------------------------------

    db.execute(
        """
        UPDATE payments
        SET status='approved'
        WHERE id=?
        """,
        (payment_id,)
    )

    # --------------------------------------------------------
    # ACTIVATE ENROLMENT
    # --------------------------------------------------------

    enrollment = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
        """,
        (
            payment["user_id"],
            payment["course_id"]
        )
    ).fetchone()

    if enrollment:

        db.execute(
            """
            UPDATE enrollments
            SET status='active'
            WHERE id=?
            """,
            (enrollment["id"],)
        )

    else:

        db.execute(
            """
            INSERT INTO enrollments(
                user_id,
                course_id,
                status,
                created_at
            )
            VALUES(?,?,?,?)
            """,
            (
                payment["user_id"],
                payment["course_id"],
                "active",
                datetime.utcnow().isoformat()
            )
        )

    db.commit()

    # --------------------------------------------------------
    # NOTIFY STUDENT
    # --------------------------------------------------------

    add_notification(
        payment["user_id"],
        "Payment Approved",
        (
            "Your payment for "
            + payment["course_title"]
            + " has been approved. "
            "Your course is now active."
        ),
        "payment"
    )

    flash(
        "Payment approved and course activated.",
        "success"
    )

    return redirect(
        url_for("admin")
    )


# ============================================================
# ADD LESSON
# ============================================================

@app.route(
    "/admin/lesson/add",
    methods=["GET", "POST"]
)
@admin_required
def add_lesson():

    db = get_db()

    courses = db.execute(
        """
        SELECT *
        FROM courses
        ORDER BY title
        """
    ).fetchall()

    if request.method == "POST":

        course_id = request.form.get(
            "course_id",
            ""
        ).strip()

        title = request.form.get(
            "title",
            ""
        ).strip()

        content = request.form.get(
            "content",
            ""
        ).strip()

        position_raw = request.form.get(
            "position",
            "1"
        ).strip()

        try:

            position = int(position_raw)

        except (TypeError, ValueError):

            position = 1

        if not course_id or not title or not content:

            flash(
                "Course, title and content are required.",
                "danger"
            )

            return redirect(
                url_for("add_lesson")
            )

        db.execute(
            """
            INSERT INTO lessons(
                course_id,
                title,
                content,
                position
            )
            VALUES(?,?,?,?)
            """,
            (
                course_id,
                title,
                content,
                position
            )
        )

        db.commit()

        flash(
            "Lesson added successfully.",
            "success"
        )

        return redirect(
            url_for("admin")
        )

    return render_template(
        "admin_lesson_form.html",
        courses=courses,
        lesson=None
    )


# ============================================================
# EDIT LESSON
# ============================================================

@app.route(
    "/admin/lesson/<int:lesson_id>/edit",
    methods=["GET", "POST"]
)
@admin_required
def edit_lesson(lesson_id):

    db = get_db()

    lesson_row = db.execute(
        """
        SELECT *
        FROM lessons
        WHERE id=?
        """,
        (lesson_id,)
    ).fetchone()

    if not lesson_row:

        flash(
            "Lesson not found.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )

    courses = db.execute(
        """
        SELECT *
        FROM courses
        ORDER BY title
        """
    ).fetchall()

    if request.method == "POST":

        course_id = request.form.get(
            "course_id",
            ""
        ).strip()

        title = request.form.get(
            "title",
            ""
        ).strip()

        content = request.form.get(
            "content",
            ""
        ).strip()

        position_raw = request.form.get(
            "position",
            "1"
        ).strip()

        try:

            position = int(position_raw)

        except (TypeError, ValueError):

            position = 1

        db.execute(
            """
            UPDATE lessons
            SET course_id=?,
                title=?,
                content=?,
                position=?
            WHERE id=?
            """,
            (
                course_id,
                title,
                content,
                position,
                lesson_id
            )
        )

        db.commit()

        flash(
            "Lesson updated successfully.",
            "success"
        )

        return redirect(
            url_for("admin")
        )

    return render_template(
        "admin_lesson_form.html",
        courses=courses,
        lesson=lesson_row
    )


# ============================================================
# DELETE LESSON
# ============================================================

@app.route(
    "/admin/lesson/<int:lesson_id>/delete",
    methods=["POST", "GET"]
)
@admin_required
def delete_lesson(lesson_id):

    db = get_db()

    lesson_row = db.execute(
        """
        SELECT *
        FROM lessons
        WHERE id=?
        """,
        (lesson_id,)
    ).fetchone()

    if not lesson_row:

        flash(
            "Lesson not found.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )

    # Delete related activity attempts first
    activity_rows = db.execute(
        """
        SELECT id
        FROM lesson_activities
        WHERE lesson_id=?
        """,
        (lesson_id,)
    ).fetchall()

    for activity in activity_rows:

        db.execute(
            """
            DELETE FROM activity_attempts
            WHERE activity_id=?
            """,
            (activity["id"],)
        )

    db.execute(
        """
        DELETE FROM lesson_activities
        WHERE lesson_id=?
        """,
        (lesson_id,)
    )

    db.execute(
        """
        DELETE FROM lesson_progress
        WHERE lesson_id=?
        """,
        (lesson_id,)
    )

    db.execute(
        """
        DELETE FROM lessons
        WHERE id=?
        """,
        (lesson_id,)
    )

    db.commit()

    flash(
        "Lesson deleted.",
        "success"
    )

    return redirect(
        url_for("admin")
    )


# ============================================================
# TOGGLE COURSE
# ============================================================

@app.route(
    "/admin/course/<int:course_id>/toggle",
    methods=["POST", "GET"]
)
@admin_required
def toggle_course(course_id):

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )

    new_status = 0 if course["active"] else 1

    db.execute(
        """
        UPDATE courses
        SET active=?
        WHERE id=?
        """,
        (
            new_status,
            course_id
        )
    )

    db.commit()

    if new_status:

        flash(
            "Course is now active.",
            "success"
        )

    else:

        flash(
            "Course has been disabled.",
            "success"
        )

    return redirect(
        url_for("admin")
    )


# ============================================================
# QUIZ MANAGEMENT
# ============================================================

@app.route(
    "/admin/quizzes/<int:course_id>"
)
@admin_required
def admin_quizzes(course_id):

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )

    questions = db.execute(
        """
        SELECT *
        FROM quizzes
        WHERE course_id=?
        ORDER BY id
        """,
        (course_id,)
    ).fetchall()

    return render_template(
        "admin_quizzes.html",
        course=course,
        questions=questions
    )


# ============================================================
# ADD QUIZ QUESTION
# ============================================================

@app.route(
    "/admin/quizzes/<int:course_id>/add",
    methods=["GET", "POST"]
)
@admin_required
def add_quiz_question(course_id):

    db = get_db()

    course = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )

    if request.method == "POST":

        question = request.form.get(
            "question",
            ""
        ).strip()

        option_a = request.form.get(
            "option_a",
            ""
        ).strip()

        option_b = request.form.get(
            "option_b",
            ""
        ).strip()

        option_c = request.form.get(
            "option_c",
            ""
        ).strip()

        option_d = request.form.get(
            "option_d",
            ""
        ).strip()

        answer = request.form.get(
            "answer",
            ""
        ).strip().upper()

        if not all(
            [
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                answer
            ]
        ):

            flash(
                "All quiz fields are required.",
                "danger"
            )

            return redirect(
                url_for(
                    "add_quiz_question",
                    course_id=course_id
                )
            )

        if answer not in (
            "A",
            "B",
            "C",
            "D"
        ):

            flash(
                "Correct answer must be A, B, C or D.",
                "danger"
            )

            return redirect(
                url_for(
                    "add_quiz_question",
                    course_id=course_id
                )
            )

        db.execute(
            """
            INSERT INTO quizzes(
                course_id,
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                answer
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                course_id,
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                answer
            )
        )

        db.commit()

        flash(
            "Quiz question added.",
            "success"
        )

        return redirect(
            url_for(
                "admin_quizzes",
                course_id=course_id
            )
        )

    return render_template(
        "admin_quiz_form.html",
        course=course,
        question=None
    )


# ============================================================
# EDIT QUIZ QUESTION
# ============================================================

@app.route(
    "/admin/quizzes/question/<int:question_id>/edit",
    methods=["GET", "POST"]
)
@admin_required
def edit_quiz_question(question_id):

    db = get_db()

    question_row = db.execute(
        """
        SELECT
            q.*,
            c.title AS course_title
        FROM quizzes q
        JOIN courses c
            ON c.id=q.course_id
        WHERE q.id=?
        """,
        (question_id,)
    ).fetchone()

    if not question_row:

        flash(
            "Quiz question not found.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )

    if request.method == "POST":

        question = request.form.get(
            "question",
            ""
        ).strip()

        option_a = request.form.get(
            "option_a",
            ""
        ).strip()

        option_b = request.form.get(
            "option_b",
            ""
        ).strip()

        option_c = request.form.get(
            "option_c",
            ""
        ).strip()

        option_d = request.form.get(
            "option_d",
            ""
        ).strip()

        answer = request.form.get(
            "answer",
            ""
        ).strip().upper()

        if answer not in (
            "A",
            "B",
            "C",
            "D"
        ):

            flash(
                "Correct answer must be A, B, C or D.",
                "danger"
            )

            return redirect(
                url_for(
                    "edit_quiz_question",
                    question_id=question_id
                )
            )

        db.execute(
            """
            UPDATE quizzes
            SET question=?,
                option_a=?,
                option_b=?,
                option_c=?,
                option_d=?,
                answer=?
            WHERE id=?
            """,
            (
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                answer,
                question_id
            )
        )

        db.commit()

        flash(
            "Quiz question updated.",
            "success"
        )

        return redirect(
            url_for(
                "admin_quizzes",
                course_id=question_row["course_id"]
            )
        )

    return render_template(
        "admin_quiz_form.html",
        course=question_row,
        question=question_row
    )


# ============================================================
# DELETE QUIZ QUESTION
# ============================================================

@app.route(
    "/admin/quizzes/question/<int:question_id>/delete",
    methods=["POST", "GET"]
)
@admin_required
def delete_quiz_question(question_id):

    db = get_db()

    question_row = db.execute(
        """
        SELECT *
        FROM quizzes
        WHERE id=?
        """,
        (question_id,)
    ).fetchone()

    if not question_row:

        flash(
            "Quiz question not found.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )

    db.execute(
        """
        DELETE FROM quiz_attempts
        WHERE quiz_id=?
        """,
        (question_id,)
    )

    db.execute(
        """
        DELETE FROM quizzes
        WHERE id=?
        """,
        (question_id,)
    )

    db.commit()

    flash(
        "Quiz question deleted.",
        "success"
    )

    return redirect(
        url_for(
            "admin_quizzes",
            course_id=question_row["course_id"]
        )
    )


# ============================================================
# ADMIN STUDENT LIST
# ============================================================

@app.route(
    "/admin/students"
)
@admin_required
def admin_students():

    db = get_db()

    students = db.execute(
        """
        SELECT
            u.*,
            sa.last_active,
            sa.lessons_viewed,
            sa.lessons_completed,
            sa.quizzes_attempted,
            sa.activities_attempted
        FROM users u
        LEFT JOIN student_activity sa
            ON sa.user_id=u.id
        WHERE u.role='student'
        ORDER BY u.id DESC
        """
    ).fetchall()

    return render_template(
        "admin_students.html",
        students=students
    )


# ============================================================
# ADMIN STUDENT PROFILE / TRACKING
# ============================================================

@app.route(
    "/admin/student/<int:user_id>"
)
@admin_required
def admin_student_view(user_id):

    db = get_db()

    student = db.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
          AND role='student'
        """,
        (user_id,)
    ).fetchone()

    if not student:

        flash(
            "Student not found.",
            "danger"
        )

        return redirect(
            url_for("admin_students")
        )

    # --------------------------------------------------------
    # ACTIVITY
    # --------------------------------------------------------

    activity = db.execute(
        """
        SELECT *
        FROM student_activity
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    # --------------------------------------------------------
    # ENROLMENTS
    # --------------------------------------------------------

    enrolments = db.execute(
        """
        SELECT
            e.*,
            c.title AS course_title,
            c.price
        FROM enrollments e
        JOIN courses c
            ON c.id=e.course_id
        WHERE e.user_id=?
        ORDER BY e.id DESC
        """,
        (user_id,)
    ).fetchall()

    # --------------------------------------------------------
    # PAYMENTS
    # --------------------------------------------------------

    payments = db.execute(
        """
        SELECT
            p.*,
            c.title AS course_title
        FROM payments p
        JOIN courses c
            ON c.id=p.course_id
        WHERE p.user_id=?
        ORDER BY p.id DESC
        """,
        (user_id,)
    ).fetchall()

    # --------------------------------------------------------
    # LESSON PROGRESS
    # --------------------------------------------------------

    lesson_progress = db.execute(
        """
        SELECT
            lp.*,
            l.title AS lesson_title,
            c.title AS course_title
        FROM lesson_progress lp
        JOIN lessons l
            ON l.id=lp.lesson_id
        JOIN courses c
            ON c.id=l.course_id
        WHERE lp.user_id=?
        ORDER BY lp.id DESC
        """,
        (user_id,)
    ).fetchall()

    # --------------------------------------------------------
    # QUIZ ATTEMPTS
    # --------------------------------------------------------

    quiz_attempts = db.execute(
        """
        SELECT
            qa.*,
            q.question,
            c.title AS course_title
        FROM quiz_attempts qa
        JOIN quizzes q
            ON q.id=qa.quiz_id
        JOIN courses c
            ON c.id=q.course_id
        WHERE qa.user_id=?
        ORDER BY qa.id DESC
        LIMIT 100
        """,
        (user_id,)
    ).fetchall()

    # --------------------------------------------------------
    # REPORTS
    # --------------------------------------------------------

    reports = db.execute(
        """
        SELECT *
        FROM student_reports
        WHERE user_id=?
        ORDER BY id DESC
        """,
        (user_id,)
    ).fetchall()

    return render_template(
        "admin_student_view.html",
        student=student,
        activity=activity,
        enrolments=enrolments,
        payments=payments,
        lesson_progress=lesson_progress,
        quiz_attempts=quiz_attempts,
        reports=reports
    )


# ============================================================
# PARENT CONTACTS
# ============================================================

@app.route(
    "/admin/parent-contacts"
)
@admin_required
def admin_parent_contacts():

    db = get_db()

    students = db.execute(
        """
        SELECT
            id,
            full_name,
            email,
            phone,
            parent_phone,
            created_at
        FROM users
        WHERE role='student'
        ORDER BY full_name
        """
    ).fetchall()

    return render_template(
        "admin_parent_contacts.html",
        students=students
    )


# ============================================================
# PARTICIPATION TRACKING
# ============================================================

@app.route(
    "/admin/participation"
)
@admin_required
def admin_participation():

    db = get_db()

    students = db.execute(
        """
        SELECT
            u.id,
            u.full_name,
            u.email,
            u.phone,
            u.parent_phone,
            sa.last_active,
            sa.lessons_viewed,
            sa.lessons_completed,
            sa.quizzes_attempted,
            sa.activities_attempted,
            c.title AS last_course
        FROM users u
        LEFT JOIN student_activity sa
            ON sa.user_id=u.id
        LEFT JOIN courses c
            ON c.id=sa.last_course_id
        WHERE u.role='student'
        ORDER BY
            CASE
                WHEN sa.last_active IS NULL THEN 1
                ELSE 0
            END,
            sa.last_active DESC,
            u.full_name
        """
    ).fetchall()

    return render_template(
        "admin_participation.html",
        students=students
    )

# ============================================================
# PART 6 — TEACHER DASHBOARD, TEACHER MANAGEMENT
# ============================================================

@app.route("/teacher")
@login_required
def teacher_dashboard():
    if current_user()["role"] not in ("teacher", "admin"):
        flash("Teacher access required.", "danger")
        return redirect(url_for("dashboard"))

    if current_user()["role"] == "admin":
        courses = db_query("""
            SELECT c.*,
                   COUNT(DISTINCT tc.teacher_id) AS teacher_count,
                   COUNT(DISTINCT e.user_id) AS student_count
            FROM courses c
            LEFT JOIN teacher_courses tc ON tc.course_id = c.id
            LEFT JOIN enrollments e
                ON e.course_id = c.id
               AND e.status = 'active'
            GROUP BY c.id
            ORDER BY c.title
        """)
    else:
        courses = db_query("""
            SELECT c.*,
                   COUNT(DISTINCT e.user_id) AS student_count
            FROM courses c
            JOIN teacher_courses tc
              ON tc.course_id = c.id
            LEFT JOIN enrollments e
              ON e.course_id = c.id
             AND e.status = 'active'
            WHERE tc.teacher_id = ?
            GROUP BY c.id
            ORDER BY c.title
        """, (current_user()["id"],))

    return render_template(
        "teacher_dashboard.html",
        courses=courses
    )


@app.route("/teacher/course/<int:course_id>")
@login_required
def teacher_course(course_id):
    user = current_user()

    if user["role"] == "admin":
        allowed = True
    else:
        allowed = db_query("""
            SELECT 1
            FROM teacher_courses
            WHERE teacher_id = ?
              AND course_id = ?
        """, (user["id"], course_id), one=True)

    if not allowed:
        flash("You are not assigned to this course.", "danger")
        return redirect(url_for("teacher_dashboard"))

    course = db_query(
        "SELECT * FROM courses WHERE id = ?",
        (course_id,),
        one=True
    )

    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("teacher_dashboard"))

    students = db_query("""
        SELECT
            u.id,
            u.full_name,
            u.email,
            u.phone,
            e.status AS enrollment_status,
            e.enrolled_at,
            COALESCE(
                (
                    SELECT COUNT(*)
                    FROM lesson_progress lp
                    JOIN lessons l
                      ON l.id = lp.lesson_id
                    WHERE lp.user_id = u.id
                      AND l.course_id = ?
                      AND lp.completed = 1
                ), 0
            ) AS completed_lessons,
            (
                SELECT COUNT(*)
                FROM lessons
                WHERE course_id = ?
            ) AS total_lessons
        FROM users u
        JOIN enrollments e
          ON e.user_id = u.id
        WHERE e.course_id = ?
        ORDER BY u.full_name
    """, (course_id, course_id, course_id))

    lessons = db_query("""
        SELECT *
        FROM lessons
        WHERE course_id = ?
        ORDER BY lesson_order, id
    """, (course_id,))

    return render_template(
        "teacher_course.html",
        course=course,
        students=students,
        lessons=lessons
    )


@app.route("/teacher/course/<int:course_id>/participation")
@login_required
def teacher_course_participation(course_id):
    user = current_user()

    if user["role"] == "admin":
        allowed = True
    else:
        allowed = db_query("""
            SELECT 1
            FROM teacher_courses
            WHERE teacher_id = ?
              AND course_id = ?
        """, (user["id"], course_id), one=True)

    if not allowed:
        flash("You are not assigned to this course.", "danger")
        return redirect(url_for("teacher_dashboard"))

    course = db_query(
        "SELECT * FROM courses WHERE id = ?",
        (course_id,),
        one=True
    )

    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("teacher_dashboard"))

    participation = db_query("""
        SELECT
            u.id,
            u.full_name,
            u.email,
            u.phone,

            COALESCE(sa.lessons_viewed, 0)
                AS lessons_viewed,

            COALESCE(sa.lessons_completed, 0)
                AS lessons_completed,

            COALESCE(sa.quizzes_taken, 0)
                AS quizzes_taken,

            COALESCE(sa.activities_completed, 0)
                AS activities_completed,

            COALESCE(sa.last_seen, '')
                AS last_seen

        FROM users u

        JOIN enrollments e
          ON e.user_id = u.id

        LEFT JOIN student_activity sa
          ON sa.user_id = u.id

        WHERE e.course_id = ?
          AND e.status = 'active'

        ORDER BY u.full_name
    """, (course_id,))

    return render_template(
        "teacher_course_participation.html",
        course=course,
        participation=participation
    )


# ============================================================
# ADMIN — TEACHER MANAGEMENT
# ============================================================

@app.route("/admin/teachers")
@admin_required
def admin_teachers():
    teachers = db_query("""
        SELECT
            u.id,
            u.full_name,
            u.email,
            u.phone,
            u.created_at,

            COUNT(DISTINCT tc.course_id)
                AS assigned_courses

        FROM users u

        LEFT JOIN teacher_courses tc
          ON tc.teacher_id = u.id

        WHERE u.role = 'teacher'

        GROUP BY u.id

        ORDER BY u.full_name
    """)

    courses = db_query("""
        SELECT *
        FROM courses
        ORDER BY title
    """)

    return render_template(
        "admin_teachers.html",
        teachers=teachers,
        courses=courses
    )


@app.route("/admin/teacher/add", methods=["POST"])
@admin_required
def admin_add_teacher():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "").strip()

    if not full_name or not email or not password:
        flash(
            "Teacher name, email and password are required.",
            "danger"
        )
        return redirect(url_for("admin_teachers"))

    existing = db_query(
        "SELECT id FROM users WHERE email = ?",
        (email,),
        one=True
    )

    if existing:
        flash("A user with that email already exists.", "danger")
        return redirect(url_for("admin_teachers"))

    conn = get_db()

    conn.execute("""
        INSERT INTO users
        (full_name, email, phone, password_hash, role)
        VALUES (?, ?, ?, ?, 'teacher')
    """, (
        full_name,
        email,
        phone,
        generate_password_hash(password)
    ))

    conn.commit()
    conn.close()

    flash("Teacher account created successfully.", "success")

    return redirect(url_for("admin_teachers"))


@app.route(
    "/admin/teacher/<int:teacher_id>/assign",
    methods=["POST"]
)
@admin_required
def admin_assign_teacher(teacher_id):
    course_id = request.form.get("course_id", "").strip()

    if not course_id:
        flash("Please select a course.", "danger")
        return redirect(url_for("admin_teachers"))

    teacher = db_query("""
        SELECT *
        FROM users
        WHERE id = ?
          AND role = 'teacher'
    """, (teacher_id,), one=True)

    if not teacher:
        flash("Teacher not found.", "danger")
        return redirect(url_for("admin_teachers"))

    course = db_query(
        "SELECT * FROM courses WHERE id = ?",
        (course_id,),
        one=True
    )

    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("admin_teachers"))

    existing = db_query("""
        SELECT 1
        FROM teacher_courses
        WHERE teacher_id = ?
          AND course_id = ?
    """, (teacher_id, course_id), one=True)

    if existing:
        flash("Teacher is already assigned to this course.", "warning")
        return redirect(url_for("admin_teachers"))

    conn = get_db()

    conn.execute("""
        INSERT INTO teacher_courses
        (teacher_id, course_id)
        VALUES (?, ?)
    """, (teacher_id, course_id))

    conn.commit()
    conn.close()

    add_notification(
        teacher_id,
        "New Course Assignment",
        f"You have been assigned to teach {course['title']}."
    )

    flash("Course assigned to teacher successfully.", "success")

    return redirect(url_for("admin_teachers"))


@app.route(
    "/admin/teacher/<int:teacher_id>/remove/<int:course_id>",
    methods=["POST"]
)
@admin_required
def admin_remove_teacher(teacher_id, course_id):
    assignment = db_query("""
        SELECT *
        FROM teacher_courses
        WHERE teacher_id = ?
          AND course_id = ?
    """, (teacher_id, course_id), one=True)

    if not assignment:
        flash("Teacher assignment not found.", "danger")
        return redirect(url_for("admin_teachers"))

    conn = get_db()

    conn.execute("""
        DELETE FROM teacher_courses
        WHERE teacher_id = ?
          AND course_id = ?
    """, (teacher_id, course_id))

    conn.commit()
    conn.close()

    flash("Teacher removed from course.", "success")

    return redirect(url_for("admin_teachers"))

# ============================================================
# PART 7 — FINAL ROUTES AND APPLICATION STARTUP
# ============================================================


# ------------------------------------------------------------
# ADMIN — VIEW A SPECIFIC STUDENT'S ACTIVITY
# ------------------------------------------------------------

@app.route("/admin/student/<int:user_id>/activity")
@admin_required
def admin_student_activity(user_id):
    student = db_query("""
        SELECT *
        FROM users
        WHERE id = ?
          AND role = 'student'
    """, (user_id,), one=True)

    if not student:
        flash("Student not found.", "danger")
        return redirect(url_for("admin_students"))

    activity = db_query("""
        SELECT
            sa.*,
            u.full_name,
            u.email
        FROM student_activity sa
        JOIN users u
          ON u.id = sa.user_id
        WHERE sa.user_id = ?
    """, (user_id,), one=True)

    courses = db_query("""
        SELECT
            c.id,
            c.title,
            c.price,
            e.status,
            e.enrolled_at
        FROM enrollments e
        JOIN courses c
          ON c.id = e.course_id
        WHERE e.user_id = ?
        ORDER BY c.title
    """, (user_id,))

    return render_template(
        "admin_student_activity.html",
        student=student,
        activity=activity,
        courses=courses
    )


# ------------------------------------------------------------
# ADMIN — SEND NOTIFICATION TO STUDENT
# ------------------------------------------------------------

@app.route(
    "/admin/student/<int:user_id>/notify",
    methods=["POST"]
)
@admin_required
def admin_notify_student(user_id):
    student = db_query("""
        SELECT *
        FROM users
        WHERE id = ?
          AND role = 'student'
    """, (user_id,), one=True)

    if not student:
        flash("Student not found.", "danger")
        return redirect(url_for("admin_students"))

    title = request.form.get("title", "").strip()
    message = request.form.get("message", "").strip()

    if not title or not message:
        flash(
            "Notification title and message are required.",
            "danger"
        )
        return redirect(
            url_for("admin_student", user_id=user_id)
        )

    add_notification(
        user_id,
        title,
        message
    )

    flash(
        "Notification sent to the student.",
        "success"
    )

    return redirect(
        url_for("admin_student", user_id=user_id)
    )


# ------------------------------------------------------------
# ADMIN — ADD ACTIVITY TO A LESSON
# ------------------------------------------------------------

@app.route(
    "/admin/activity/<int:lesson_id>/add",
    methods=["POST"]
)
@admin_required
def admin_add_lesson_activity(lesson_id):
    lesson = db_query("""
        SELECT *
        FROM lessons
        WHERE id = ?
    """, (lesson_id,), one=True)

    if not lesson:
        flash("Lesson not found.", "danger")
        return redirect(url_for("admin"))

    title = request.form.get("title", "").strip()
    activity_type = request.form.get(
        "activity_type",
        "question"
    ).strip()

    instructions = request.form.get(
        "instructions",
        ""
    ).strip()

    content = request.form.get(
        "content",
        ""
    ).strip()

    if not title:
        flash("Activity title is required.", "danger")
        return redirect(
            url_for(
                "teacher_course",
                course_id=lesson["course_id"]
            )
        )

    conn = get_db()

    conn.execute("""
        INSERT INTO lesson_activities
        (
            lesson_id,
            title,
            activity_type,
            instructions,
            content
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        lesson_id,
        title,
        activity_type,
        instructions,
        content
    ))

    conn.commit()
    conn.close()

    flash(
        "Lesson activity added successfully.",
        "success"
    )

    return redirect(
        url_for(
            "teacher_course",
            course_id=lesson["course_id"]
        )
    )


# ------------------------------------------------------------
# ADMIN — REPORTS
# ------------------------------------------------------------

@app.route("/admin/reports")
@admin_required
def admin_reports():
    reports = db_query("""
        SELECT
            r.*,
            u.full_name AS student_name,
            u.email AS student_email
        FROM student_reports r
        JOIN users u
          ON u.id = r.student_id
        ORDER BY
            CASE
                WHEN r.status = 'pending' THEN 0
                ELSE 1
            END,
            r.created_at DESC
    """)

    return render_template(
        "admin_reports.html",
        reports=reports
    )


@app.route(
    "/admin/reports/<int:report_id>/reply",
    methods=["POST"]
)
@admin_required
def admin_reply_report(report_id):
    report = db_query("""
        SELECT *
        FROM student_reports
        WHERE id = ?
    """, (report_id,), one=True)

    if not report:
        flash("Report not found.", "danger")
        return redirect(url_for("admin_reports"))

    reply = request.form.get(
        "reply",
        ""
    ).strip()

    if not reply:
        flash("Please enter a reply.", "danger")
        return redirect(url_for("admin_reports"))

    conn = get_db()

    conn.execute("""
        UPDATE student_reports
        SET
            admin_reply = ?,
            status = 'replied',
            replied_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (reply, report_id))

    conn.commit()
    conn.close()

    add_notification(
        report["student_id"],
        "Report Response",
        reply
    )

    flash(
        "Reply sent to the student.",
        "success"
    )

    return redirect(url_for("admin_reports"))


# ------------------------------------------------------------
# ADMIN — DELETE / DISABLE STUDENT
# ------------------------------------------------------------

@app.route(
    "/admin/student/<int:user_id>/disable",
    methods=["POST"]
)
@admin_required
def admin_disable_student(user_id):
    student = db_query("""
        SELECT *
        FROM users
        WHERE id = ?
          AND role = 'student'
    """, (user_id,), one=True)

    if not student:
        flash("Student not found.", "danger")
        return redirect(url_for("admin_students"))

    conn = get_db()

    conn.execute("""
        UPDATE users
        SET role = 'disabled'
        WHERE id = ?
    """, (user_id,))

    conn.commit()
    conn.close()

    flash(
        "Student account disabled.",
        "success"
    )

    return redirect(url_for("admin_students"))


# ------------------------------------------------------------
# ADMIN — ENABLE STUDENT
# ------------------------------------------------------------

@app.route(
    "/admin/student/<int:user_id>/enable",
    methods=["POST"]
)
@admin_required
def admin_enable_student(user_id):
    student = db_query("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (user_id,), one=True)

    if not student:
        flash("User not found.", "danger")
        return redirect(url_for("admin_students"))

    conn = get_db()

    conn.execute("""
        UPDATE users
        SET role = 'student'
        WHERE id = ?
    """, (user_id,))

    conn.commit()
    conn.close()

    flash(
        "Student account enabled.",
        "success"
    )

    return redirect(url_for("admin_students"))


# ------------------------------------------------------------
# ADMIN — VIEW COURSES
# ------------------------------------------------------------

@app.route("/admin/courses")
@admin_required
def admin_courses():
    courses = db_query("""
        SELECT
            c.*,

            (
                SELECT COUNT(*)
                FROM lessons l
                WHERE l.course_id = c.id
            ) AS lesson_count,

            (
                SELECT COUNT(*)
                FROM enrollments e
                WHERE e.course_id = c.id
                  AND e.status = 'active'
            ) AS student_count

        FROM courses c
        ORDER BY c.title
    """)

    return render_template(
        "admin_courses.html",
        courses=courses
    )


# ------------------------------------------------------------
# ADMIN — COURSE DETAILS
# ------------------------------------------------------------

@app.route("/admin/course/<int:course_id>")
@admin_required
def admin_course_details(course_id):
    course = db_query("""
        SELECT *
        FROM courses
        WHERE id = ?
    """, (course_id,), one=True)

    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for("admin_courses"))

    lessons = db_query("""
        SELECT *
        FROM lessons
        WHERE course_id = ?
        ORDER BY lesson_order, id
    """, (course_id,))

    students = db_query("""
        SELECT
            u.id,
            u.full_name,
            u.email,
            u.phone,
            e.status,
            e.enrolled_at
        FROM enrollments e
        JOIN users u
          ON u.id = e.user_id
        WHERE e.course_id = ?
        ORDER BY u.full_name
    """, (course_id,))

    return render_template(
        "admin_course_details.html",
        course=course,
        lessons=lessons,
        students=students
    )



# ------------------------------------------------------------
# LOGOUT SAFETY ROUTE
# ------------------------------------------------------------

@app.route("/home")
def home():
    return redirect(url_for("index"))


# ============================================================
# SAFETY USER LOADER
# ============================================================

@app.before_request
def ensure_user_loaded():

    if not hasattr(g, "user"):
        g.user = None

    user_id = session.get("user_id")

    if user_id and g.user is None:

        db = get_db()

        g.user = db.execute(
            """
            SELECT *
            FROM users
            WHERE id=?
            """,
            (user_id,)
        ).fetchone()


# ============================================================
# APPLICATION STARTUP
# ============================================================

if __name__ == "__main__":
    init_db()

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get("PORT", 5000)
        ),
        debug=False
    )
