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
            active INTEGER NOT NULL DEFAULT 1
        )
        """
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

    for title, description in courses:
        existing = conn.execute(
            "SELECT id FROM courses WHERE title=?",
            (title,)
        ).fetchone()

        if not existing:
            conn.execute(
                """
                INSERT INTO courses(title, description, active)
                VALUES(?,?,1)
                """,
                (title, description)
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
                Examine the causes and effects of colonial rule in
                Africa.
                """
            ),
            (
                "Independence Movements",
                """
                Study the development of African independence movements
                and the challenges faced during the struggle for
                independence.
                """
            ),
        ],
    }

    for course_title, lessons in lesson_data.items():

        course = conn.execute(
            "SELECT id FROM courses WHERE title=?",
            (course_title,)
        ).fetchone()

        if not course:
            continue

        for position, (title, content) in enumerate(
            lessons,
            start=1
        ):

            existing = conn.execute(
                """
                SELECT id
                FROM lessons
                WHERE course_id=? AND position=?
                """,
                (course["id"], position)
            ).fetchone()

            if not existing:
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
                        course["id"],
                        title,
                        content,
                        position
                    )
                )

    # ========================================================
    # QUIZ DATA
    # ========================================================

    quiz_data = {

        "Form 1 Mathematics": [
            (
                "What is 25% of 80?",
                "10",
                "20",
                "25",
                "40",
                "B"
            ),
            (
                "What is 7 × 8?",
                "54",
                "56",
                "64",
                "48",
                "B"
            ),
            (
                "Which number is a factor of 24?",
                "5",
                "7",
                "8",
                "11",
                "C"
            ),
            (
                "What is 3/4 as a decimal?",
                "0.25",
                "0.5",
                "0.75",
                "1.25",
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
                "Simplify 3x + 2x.",
                "5",
                "5x",
                "6x",
                "x",
                "B"
            ),
            (
                "What is 2(3 + 4)?",
                "10",
                "12",
                "14",
                "16",
                "C"
            ),
            (
                "What is the ratio 6:9 in simplest form?",
                "1:2",
                "2:3",
                "3:2",
                "6:3",
                "B"
            ),
        ],

        "Form 3 Mathematics": [
            (
                "Solve x + 5 = 12.",
                "5",
                "6",
                "7",
                "8",
                "C"
            ),
            (
                "What is the gradient of a horizontal line?",
                "0",
                "1",
                "-1",
                "Undefined",
                "A"
            ),
            (
                "How many degrees are in a triangle?",
                "90",
                "180",
                "270",
                "360",
                "B"
            ),
            (
                "What is 4²?",
                "8",
                "12",
                "16",
                "20",
                "C"
            ),
        ],

        "O-Level Mathematics": [
            (
                "What is the gradient of y = 3x + 2?",
                "2",
                "3",
                "-3",
                "1",
                "B"
            ),
            (
                "What is the mean of 2, 4, 6 and 8?",
                "4",
                "5",
                "6",
                "7",
                "B"
            ),
        ],

        "O-Level Science": [
            (
                "Which organelle controls most cell activities?",
                "Cell wall",
                "Nucleus",
                "Vacuole",
                "Ribosome",
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
            (
                "Which gas is required for aerobic respiration?",
                "Nitrogen",
                "Oxygen",
                "Carbon dioxide",
                "Hydrogen",
                "B"
            ),
        ],

        "O-Level Geography": [
            (
                "What does a map scale show?",
                "Temperature",
                "Relationship between map and ground distance",
                "Rainfall",
                "Population",
                "B"
            ),
            (
                "Which instrument measures rainfall?",
                "Barometer",
                "Rain gauge",
                "Thermometer",
                "Anemometer",
                "B"
            ),
            (
                "What is population density?",
                "Birth rate",
                "Number of people per unit area",
                "Death rate",
                "Migration rate",
                "B"
            ),
            (
                "Which direction is opposite to north?",
                "East",
                "West",
                "South",
                "North-east",
                "C"
            ),
        ],

        "A-Level History": [
            (
                "What is nationalism?",
                "A type of weather",
                "A strong identification with and desire for self-rule of a nation",
                "A farming method",
                "A trade system",
                "B"
            ),
            (
                "Colonialism involves:",
                "Independent trade only",
                "Control of one territory by another power",
                "Local elections",
                "Industrialisation only",
                "B"
            ),
            (
                "What is independence?",
                "Loss of sovereignty",
                "Self-government",
                "Colonial administration",
                "Foreign rule",
                "B"
            ),
            (
                "Nationalist movements generally sought:",
                "More colonial control",
                "Self-determination",
                "Less education",
                "More taxation",
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

        count = conn.execute(
            "SELECT COUNT(*) AS c FROM quizzes WHERE course_id=?",
            (course["id"],)
        ).fetchone()["c"]

        if count == 0:

            for q in questions:

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
                        course["id"],
                        q[0],
                        q[1],
                        q[2],
                        q[3],
                        q[4],
                        q[5]
                    )
                )

    # ========================================================
    # INTERACTIVE LESSON ACTIVITIES
    # ========================================================

    activity_data = {

        "Form 1 Mathematics": [
            (
                "What is 25% of 80?",
                "10",
                "20",
                "30",
                "40",
                "B"
            ),
            (
                "Which number is a factor of 24?",
                "5",
                "6",
                "7",
                "11",
                "B"
            ),
            (
                "What is 3/4 as a decimal?",
                "0.25",
                "0.50",
                "0.75",
                "1.50",
                "C"
            ),
        ],

        "Form 2 Mathematics": [
            (
                "What is -5 + 8?",
                "3",
                "-3",
                "13",
                "-13",
                "A"
            ),
            (
                "Simplify 3x + 2x.",
                "5",
                "5x",
                "6x",
                "x",
                "B"
            ),
            (
                "What is the simplest form of 6:9?",
                "1:2",
                "2:3",
                "3:2",
                "6:3",
                "B"
            ),
        ],

        "Form 3 Mathematics": [
            (
                "Solve x + 5 = 12.",
                "5",
                "6",
                "7",
                "8",
                "C"
            ),
            (
                "What is the gradient of a horizontal line?",
                "0",
                "1",
                "-1",
                "2",
                "A"
            ),
            (
                "How many degrees are in a triangle?",
                "90",
                "180",
                "270",
                "360",
                "B"
            ),
        ],

        "O-Level Mathematics": [
            (
                "What is the gradient of y = 3x + 2?",
                "2",
                "3",
                "-3",
                "1",
                "B"
            ),
            (
                "What is the mean of 2, 4, 6 and 8?",
                "4",
                "5",
                "6",
                "7",
                "B"
            ),
            (
                "What is 12²?",
                "124",
                "144",
                "122",
                "154",
                "B"
            ),
        ],

        "O-Level Science": [
            (
                "Which organelle controls most cell activities?",
                "Cell wall",
                "Nucleus",
                "Vacuole",
                "Cytoplasm",
                "B"
            ),
            (
                "A force is best described as:",
                "A push or pull",
                "A gas",
                "A liquid",
                "A cell",
                "A"
            ),
            (
                "Which gas is needed for aerobic respiration?",
                "Nitrogen",
                "Oxygen",
                "Hydrogen",
                "Helium",
                "B"
            ),
        ],

        "O-Level Geography": [
            (
                "Which instrument measures rainfall?",
                "Barometer",
                "Rain gauge",
                "Thermometer",
                "Anemometer",
                "B"
            ),
            (
                "Population density means:",
                "Birth rate",
                "People per unit area",
                "Death rate",
                "Migration",
                "B"
            ),
            (
                "Which direction is opposite north?",
                "East",
                "West",
                "South",
                "North-east",
                "C"
            ),
        ],

        "A-Level History": [
            (
                "Nationalism is strongly associated with:",
                "Self-determination",
                "Foreign domination",
                "Climate",
                "Agriculture",
                "A"
            ),
            (
                "Colonialism involves:",
                "Control of one territory by another power",
                "Equal partnership only",
                "Local self-rule",
                "No political control",
                "A"
            ),
            (
                "Independence means:",
                "Foreign rule",
                "Self-government",
                "Colonial administration",
                "Military occupation",
                "B"
            ),
        ],
    }

    # Put one activity on each lesson if none exists.
    for course_title, activities in activity_data.items():

        course = conn.execute(
            "SELECT id FROM courses WHERE title=?",
            (course_title,)
        ).fetchone()

        if not course:
            continue

        lessons = conn.execute(
            """
            SELECT *
            FROM lessons
            WHERE course_id=?
            ORDER BY position
            """,
            (course["id"],)
        ).fetchall()

        for lesson, activity in zip(lessons, activities):

            existing = conn.execute(
                """
                SELECT id
                FROM lesson_activities
                WHERE lesson_id=?
                """,
                (lesson["id"],)
            ).fetchone()

            if not existing:

                conn.execute(
                    """
                    INSERT INTO lesson_activities(
                        lesson_id,
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
                        lesson["id"],
                        activity[0],
                        activity[1],
                        activity[2],
                        activity[3],
                        activity[4],
                        activity[5],
                    )
                )

    # ========================================================
    # DEFAULT ADMIN
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
                datetime.utcnow().isoformat(),
            )
        )

    # ========================================================
    # INITIALISE ACTIVITY ROWS
    # ========================================================

    users = conn.execute(
        "SELECT id FROM users"
    ).fetchall()

    for user in users:

        conn.execute(
            """
            INSERT OR IGNORE INTO student_activity(
                user_id,
                last_active
            )
            VALUES(?,?)
            """,
            (
                user["id"],
                datetime.utcnow().isoformat()
            )
        )

    conn.commit()


# ============================================================
# HELPERS
# ============================================================

def now():
    return datetime.utcnow().isoformat()


def normalize_phone(phone):
    if not phone:
        return ""

    return "".join(
        char
        for char in phone
        if char.isdigit()
    )


def whatsapp_link(phone):
    number = normalize_phone(phone)

    if not number:
        return "#"

    if number.startswith("0"):
        number = "263" + number[1:]

    if not number.startswith("263"):
        number = "263" + number

    return "https://wa.me/" + number


def create_notification(
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
            now()
        )
    )

    db.commit()


def notify_admins(
    title,
    message,
    notification_type="info"
):
    db = get_db()

    admins = db.execute(
        """
        SELECT id
        FROM users
        WHERE role='admin'
        """
    ).fetchall()

    for admin in admins:

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
                admin["id"],
                title,
                message,
                notification_type,
                now()
            )
        )

    db.commit()


def touch_student_activity(
    course_id=None,
    viewed=False,
    completed=False,
    quiz=False,
    activity=False
):

    if not g.user:
        return

    if g.user["role"] != "student":
        return

    db = get_db()

    row = db.execute(
        """
        SELECT *
        FROM student_activity
        WHERE user_id=?
        """,
        (g.user["id"],)
    ).fetchone()

    if not row:

        db.execute(
            """
            INSERT INTO student_activity(
                user_id,
                last_active,
                lessons_viewed,
                lessons_completed,
                quizzes_attempted,
                activities_attempted,
                last_course_id
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                g.user["id"],
                now(),
                1 if viewed else 0,
                1 if completed else 0,
                1 if quiz else 0,
                1 if activity else 0,
                course_id,
            )
        )

    else:

        db.execute(
            """
            UPDATE student_activity
            SET
                last_active=?,
                lessons_viewed=lessons_viewed+?,
                lessons_completed=lessons_completed+?,
                quizzes_attempted=quizzes_attempted+?,
                activities_attempted=activities_attempted+?,
                last_course_id=COALESCE(?, last_course_id)
            WHERE user_id=?
            """,
            (
                now(),
                1 if viewed else 0,
                1 if completed else 0,
                1 if quiz else 0,
                1 if activity else 0,
                course_id,
                g.user["id"],
            )
        )

    db.commit()


def student_has_access(course_id):

    if not g.user:
        return False

    if g.user["role"] in ["admin", "teacher"]:
        return True

    db = get_db()

    enrollment = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
        AND course_id=?
        AND status='approved'
        """,
        (
            g.user["id"],
            course_id
        )
    ).fetchone()

    return enrollment is not None


def get_unread_notification_count():

    if not g.user:
        return 0

    db = get_db()

    row = db.execute(
        """
        SELECT COUNT(*) AS c
        FROM notifications
        WHERE user_id=?
        AND is_read=0
        """,
        (g.user["id"],)
    ).fetchone()

    return row["c"]


# ============================================================
# AUTH DECORATORS
# ============================================================

def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if not g.user:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


def admin_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if not g.user or g.user["role"] != "admin":
            flash("Administrator access required.", "danger")
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


def teacher_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if not g.user or g.user["role"] not in [
            "teacher",
            "admin"
        ]:
            flash("Teacher access required.", "danger")
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


# ============================================================
# LOAD USER
# ============================================================

@app.before_request
def load_user():

    g.user = None

    user_id = session.get("user_id")

    if user_id:

        db = get_db()

        g.user = db.execute(
            """
            SELECT *
            FROM users
            WHERE id=?
            """,
            (user_id,)
        ).fetchone()

    # --------------------------------------------------------
    # Require parent/guardian phone before students continue
    # --------------------------------------------------------

    if (
        g.user
        and g.user["role"] == "student"
        and not g.user["parent_phone"]
        and request.endpoint not in [
            "parent_contact",
            "logout",
            "static",
        ]
    ):
        return redirect(url_for("parent_contact"))

    # Track student activity
    if (
        g.user
        and g.user["role"] == "student"
        and request.endpoint not in [
            "static",
            "login",
            "register",
        ]
    ):
        touch_student_activity()


# ============================================================
# STARTUP
# ============================================================

with app.app_context():
    init_db()


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/robots.txt")
def robots():
    return Response(
        "User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n",
        mimetype="text/plain"
    )


@app.route("/sitemap.xml")
def sitemap():

    pages = [
        url_for("index", _external=True),
        url_for("register", _external=True),
        url_for("login", _external=True),
    ]

    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]

    for page in pages:
        xml.append(
            f"<url><loc>{page}</loc></url>"
        )

    xml.append("</urlset>")

    return Response(
        "\n".join(xml),
        mimetype="application/xml"
    )


# ============================================================
# REGISTER
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

        password = request.form.get(
            "password",
            ""
        )

        if not full_name or not email or not password:

            flash(
                "Please complete all required fields.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if len(password) < 6:

            flash(
                "Password must contain at least 6 characters.",
                "danger"
            )

            return render_template(
                "register.html"
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

            return render_template(
                "register.html"
            )

        cursor = db.execute(
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
                full_name,
                email,
                phone,
                generate_password_hash(password),
                "student",
                now()
            )
        )

        user_id = cursor.lastrowid

        db.execute(
            """
            INSERT OR IGNORE INTO student_activity(
                user_id,
                last_active
            )
            VALUES(?,?)
            """,
            (
                user_id,
                now()
            )
        )

        db.commit()

        session["user_id"] = user_id

        flash(
            "Account created successfully. Please add your parent/guardian phone number.",
            "success"
        )

        return redirect(
            url_for("parent_contact")
        )

    return render_template("register.html")


# ============================================================
# PARENT/GUARDIAN CONTACT
# ============================================================

@app.route(
    "/parent-contact",
    methods=["GET", "POST"]
)
@login_required
def parent_contact():

    if g.user["role"] != "student":
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        parent_phone = request.form.get(
            "parent_phone",
            ""
        ).strip()

        if not parent_phone:

            flash(
                "Parent/guardian phone number is required.",
                "danger"
            )

            return redirect(
                url_for("parent_contact")
            )

        if len(normalize_phone(parent_phone)) < 9:

            flash(
                "Please enter a valid parent/guardian phone number.",
                "danger"
            )

            return redirect(
                url_for("parent_contact")
            )

        db = get_db()

        db.execute(
            """
            UPDATE users
            SET parent_phone=?
            WHERE id=?
            """,
            (
                parent_phone,
                g.user["id"]
            )
        )

        db.commit()

        notify_admins(
            "New parent contact information",
            f"{g.user['full_name']} has provided a parent/guardian phone number.",
            "info"
        )

        flash(
            "Parent/guardian contact saved successfully.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <title>Parent / Guardian Contact</title>
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <style>
                body{
                    font-family:Arial,sans-serif;
                    background:#f3f6fb;
                    padding:30px;
                }
                .box{
                    max-width:520px;
                    margin:40px auto;
                    background:white;
                    padding:30px;
                    border-radius:16px;
                    box-shadow:0 5px 25px rgba(0,0,0,.08);
                }
                h1{color:#102a56;}
                input{
                    width:100%;
                    padding:14px;
                    box-sizing:border-box;
                    border:1px solid #ccc;
                    border-radius:8px;
                    margin:10px 0 20px;
                }
                button{
                    width:100%;
                    padding:14px;
                    border:0;
                    border-radius:8px;
                    background:#f5c400;
                    font-weight:bold;
                    cursor:pointer;
                }
                .note{
                    background:#eef5ff;
                    padding:15px;
                    border-radius:10px;
                    margin-bottom:20px;
                }
            </style>
        </head>
        <body>
            <div class="box">
                <h1>Parent / Guardian Contact</h1>

                <div class="note">
                    Eagle Vision Online Academy requires every student
                    to provide a parent or guardian contact number.
                    This allows the academy to communicate important
                    learning and participation matters to parents.
                </div>

                <form method="post">

                    <label>Parent / Guardian Phone Number</label>

                    <input
                        type="tel"
                        name="parent_phone"
                        placeholder="+263 7X XXX XXXX"
                        value="{{ g.user['parent_phone'] or '' }}"
                        required
                    >

                    <button type="submit">
                        Save Parent Contact
                    </button>

                </form>
            </div>
        </body>
        </html>
        """
    )


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
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

        db = get_db()

        user = db.execute(
            """
            SELECT *
            FROM users
            WHERE email=?
            """,
            (email,)
        ).fetchone()

        if user and check_password_hash(
            user["password_hash"],
            password
        ):

            session["user_id"] = user["id"]

            if user["role"] == "admin":
                return redirect(url_for("admin"))

            if user["role"] == "teacher":
                return redirect(url_for("teacher"))

            if not user["parent_phone"]:
                return redirect(
                    url_for("parent_contact")
                )

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Invalid email or password.",
            "danger"
        )

    return render_template("login.html")


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

    # Keep the student dashboard self-contained so students can always
    # browse subjects, enrol, pay, and open approved courses even if the
    # existing dashboard.html template does not contain course cards.
    db = get_db()

    enrollments = db.execute(
        """
        SELECT e.*, c.title, c.description
        FROM enrollments e
        JOIN courses c ON c.id=e.course_id
        WHERE e.user_id=?
        ORDER BY e.id DESC
        """,
        (g.user["id"],)
    ).fetchall()

    courses = db.execute(
        """
        SELECT *
        FROM courses
        ORDER BY id
        """
    ).fetchall()

    activity = db.execute(
        """
        SELECT *
        FROM student_activity
        WHERE user_id=?
        """,
        (g.user["id"],)
    ).fetchone()

    notifications = db.execute(
        """
        SELECT *
        FROM notifications
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
        """,
        (g.user["id"],)
    ).fetchall()

    unread_notifications = get_unread_notification_count()

    # Build a simple status map for every course.
    status_map = {}
    for course_row in courses:
        enrollment = db.execute(
            """
            SELECT status
            FROM enrollments
            WHERE user_id=? AND course_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (g.user["id"], course_row["id"])
        ).fetchone()
        status_map[course_row["id"]] = enrollment["status"] if enrollment else None

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <title>Student Dashboard - Eagle Vision Online Academy</title>
            <style>
                *{box-sizing:border-box}
                body{margin:0;font-family:Arial,sans-serif;background:#f3f6fb;color:#172033}
                .top{background:#102a56;color:white;padding:18px 16px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
                .top h1{margin:0;font-size:21px}
                .top a{color:white;text-decoration:none;margin-left:12px;font-weight:bold}
                .wrap{max-width:1050px;margin:auto;padding:20px}
                .welcome{background:white;border-radius:16px;padding:22px;margin-bottom:20px;box-shadow:0 3px 15px rgba(0,0,0,.07)}
                .welcome h2{margin:0 0 8px;color:#102a56}
                .notice{background:#fff8d9;border-left:5px solid #f5c400;padding:14px;border-radius:10px;margin:15px 0}
                .section-title{color:#102a56;margin:25px 0 12px}
                .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}
                .card{background:white;border-radius:16px;padding:20px;box-shadow:0 3px 15px rgba(0,0,0,.07)}
                .card h3{margin-top:0;color:#102a56}
                .price{font-size:20px;font-weight:bold;margin:10px 0;color:#111}
                .desc{color:#5c667a;line-height:1.5;min-height:48px}
                .btn{display:inline-block;border:0;border-radius:9px;padding:12px 15px;text-decoration:none;font-weight:bold;cursor:pointer;margin-top:8px}
                .primary{background:#f5c400;color:#111}
                .blue{background:#102a56;color:white}
                .green{background:#198754;color:white}
                .gray{background:#e8edf5;color:#333}
                form{display:inline}
                .small{font-size:13px;color:#667085}
                .badge{display:inline-block;padding:6px 9px;border-radius:20px;font-size:12px;font-weight:bold;background:#eef2f7;margin-bottom:8px}
                .approved{background:#dff6e8;color:#146c3e}
                .pending{background:#fff2c2;color:#775d00}
                .empty{background:white;padding:18px;border-radius:12px}
                .notification{padding:12px;border-bottom:1px solid #eee}
                @media(max-width:600px){.wrap{padding:13px}.top a{margin-left:5px;font-size:13px}}
            </style>
        </head>
        <body>
            <div class="top">
                <h1>Eagle Vision Online Academy</h1>
                <div>
                    <a href="{{ url_for('dashboard') }}">Dashboard</a>
                    <a href="{{ url_for('notifications') }}">Notifications{% if unread_notifications %} ({{ unread_notifications }}){% endif %}</a>
                    <a href="{{ url_for('report_admin') }}">Report to Admin</a>
                    <a href="{{ url_for('logout') }}">Logout</a>
                </div>
            </div>

            <div class="wrap">
                <div class="welcome">
                    <h2>Welcome, {{ g.user['full_name'] }} 👋</h2>
                    <p>Learn. Revise. Achieve.</p>
                    <div class="notice">
                        <strong>How learning works:</strong>
                        Choose a subject below → enrol → submit payment → wait for admin approval → open your course → study lessons → complete activities and quizzes.
                    </div>
                    {% if not g.user['parent_phone'] %}
                        <a class="btn primary" href="{{ url_for('parent_contact') }}">Add Parent / Guardian Contact</a>
                    {% endif %}
                </div>

                <h2 class="section-title">📚 Browse Courses & Subjects</h2>
                <div class="grid">
                {% for c in courses %}
                    {% set status = status_map[c['id']] %}
                    <div class="card">
                        <span class="badge">Course</span>
                        <h3>{{ c['title'] }}</h3>
                        <div class="price">${{ '%.2f'|format(c['price']|float) }}</div>
                        <p class="desc">{{ c['description'] or 'Study lessons, practise and prepare for examinations.' }}</p>

                        {% if status == 'approved' %}
                            <span class="badge approved">✓ Enrolled & Active</span><br>
                            <a class="btn green" href="{{ url_for('course', course_id=c['id']) }}">Start Learning</a>
                        {% elif status == 'pending' %}
                            <span class="badge pending">⏳ Enrolment Pending</span><br>
                            <a class="btn primary" href="{{ url_for('pay', course_id=c['id']) }}">Pay / Submit Payment</a>
                        {% else %}
                            <form method="post" action="{{ url_for('enrol', course_id=c['id']) }}">
                                <button class="btn blue" type="submit">Enrol Now</button>
                            </form>
                        {% endif %}
                    </div>
                {% endfor %}
                </div>

                <h2 class="section-title">🎓 My Courses</h2>
                {% if enrollments %}
                    <div class="grid">
                    {% for e in enrollments %}
                        <div class="card">
                            <h3>{{ e['title'] }}</h3>
                            <p>{{ e['description'] or '' }}</p>
                            {% if e['status'] == 'approved' %}
                                <span class="badge approved">Active</span><br>
                                <a class="btn green" href="{{ url_for('course', course_id=e['course_id']) }}">Open Course</a>
                            {% else %}
                                <span class="badge pending">{{ e['status']|capitalize }}</span><br>
                                <a class="btn primary" href="{{ url_for('pay', course_id=e['course_id']) }}">Pay / Submit Payment</a>
                            {% endif %}
                        </div>
                    {% endfor %}
                    </div>
                {% else %}
                    <div class="empty">You have not enrolled in a course yet. Choose a subject above to get started.</div>
                {% endif %}

                <h2 class="section-title">🔔 Recent Notifications</h2>
                <div class="card">
                    {% if notifications %}
                        {% for n in notifications %}
                            <div class="notification">
                                <strong>{{ n['title'] }}</strong><br>
                                <span class="small">{{ n['message'] }}</span>
                            </div>
                        {% endfor %}
                    {% else %}
                        <p class="small">No notifications yet.</p>
                    {% endif %}
                </div>
            </div>
        </body>
        </html>
        """,
        courses=courses,
        enrollments=enrollments,
        activity=activity,
        notifications=notifications,
        unread_notifications=unread_notifications,
        status_map=status_map
    )


# ============================================================
# COURSE
# ============================================================

@app.route("/course/<int:course_id>")
@login_required
def course(course_id):

    db = get_db()

    course_row = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course_row:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    if not student_has_access(course_id):

        flash(
            "You do not currently have access to this course.",
            "warning"
        )

        return redirect(
            url_for("dashboard")
        )

    lessons = db.execute(
        """
        SELECT
            l.*,
            COALESCE(lp.completed,0) AS completed
        FROM lessons l
        LEFT JOIN lesson_progress lp
            ON lp.lesson_id=l.id
            AND lp.user_id=?
        WHERE l.course_id=?
        ORDER BY l.position
        """,
        (
            g.user["id"],
            course_id
        )
    ).fetchall()

    activities_count = db.execute(
        """
        SELECT COUNT(*) AS c
        FROM lesson_activities la
        JOIN lessons l
            ON l.id=la.lesson_id
        WHERE l.course_id=?
        """,
        (course_id,)
    ).fetchone()["c"]

    return render_template(
        "course.html",
        course=course_row,
        lessons=lessons,
        activities_count=activities_count
    )


# ============================================================
# ENROL
# ============================================================

@app.route(
    "/enrol/<int:course_id>",
    methods=["POST"]
)
@login_required
def enrol(course_id):

    db = get_db()

    course_row = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course_row:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    existing = db.execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=?
        AND course_id=?
        """,
        (
            g.user["id"],
            course_id
        )
    ).fetchone()

    if existing:

        flash(
            "You have already requested this course.",
            "info"
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id
            )
        )

    db.execute(
        """
        INSERT INTO enrollments(
            user_id,
            course_id,
            status,
            created_at
        )
        VALUES(?,?,?,?,?)
        """,
        (
            g.user["id"],
            course_id,
            "pending",
            now()
        )
    )

    db.commit()

    notify_admins(
        "New course enrolment",
        f"{g.user['full_name']} requested enrolment in {course_row['title']}.",
        "enrolment"
    )

    create_notification(
        g.user["id"],
        "Enrolment request received",
        f"Your enrolment request for {course_row['title']} has been received.",
        "success"
    )

    flash(
        "Enrolment request submitted.",
        "success"
    )

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# LESSON
# ============================================================

@app.route("/lesson/<int:lesson_id>")
@login_required
def lesson(lesson_id):

    db = get_db()

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
        flash("Lesson not found.", "danger")
        return redirect(url_for("dashboard"))

    if not student_has_access(
        lesson_row["course_id"]
    ):

        flash(
            "You do not have access to this lesson.",
            "warning"
        )

        return redirect(
            url_for(
                "course",
                course_id=lesson_row["course_id"]
            )
        )

    touch_student_activity(
        course_id=lesson_row["course_id"],
        viewed=True
    )

    activities = db.execute(
        """
        SELECT *
        FROM lesson_activities
        WHERE lesson_id=?
        ORDER BY id
        """,
        (lesson_id,)
    ).fetchall()

    progress = db.execute(
        """
        SELECT *
        FROM lesson_progress
        WHERE user_id=?
        AND lesson_id=?
        """,
        (
            g.user["id"],
            lesson_id
        )
    ).fetchone()

    return render_template(
        "lesson.html",
        lesson=lesson_row,
        progress=progress,
        activities=activities
    )


# ============================================================
# COMPLETE LESSON
# ============================================================

@app.route(
    "/lesson/<int:lesson_id>/complete",
    methods=["POST"]
)
@login_required
def complete_lesson(lesson_id):

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
        flash("Lesson not found.", "danger")
        return redirect(url_for("dashboard"))

    if not student_has_access(
        lesson_row["course_id"]
    ):

        flash(
            "You do not have access to this lesson.",
            "danger"
        )

        return redirect(
            url_for(
                "dashboard"
            )
        )

    existing = db.execute(
        """
        SELECT *
        FROM lesson_progress
        WHERE user_id=?
        AND lesson_id=?
        """,
        (
            g.user["id"],
            lesson_id
        )
    ).fetchone()

    if existing:

        db.execute(
            """
            UPDATE lesson_progress
            SET completed=1,
                completed_at=?
            WHERE id=?
            """,
            (
                now(),
                existing["id"]
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
                g.user["id"],
                lesson_id,
                now()
            )
        )

    db.commit()

    touch_student_activity(
        course_id=lesson_row["course_id"],
        completed=True
    )

    create_notification(
        g.user["id"],
        "Lesson completed",
        f"You completed: {lesson_row['title']}. Keep going!",
        "success"
    )

    flash(
        "Lesson marked as completed.",
        "success"
    )

    return redirect(
        url_for(
            "course",
            course_id=lesson_row["course_id"]
        )
    )


# ============================================================
# INTERACTIVE LESSON ACTIVITY
# ============================================================

@app.route(
    "/lesson/<int:lesson_id>/activity",
    methods=["GET", "POST"]
)
@login_required
def lesson_activity(lesson_id):

    db = get_db()

    lesson_row = db.execute(
        """
        SELECT
            l.*,
            c.title AS course_title
        FROM lessons l
        JOIN courses c
            ON c.id=l.course_id
        WHERE l.id=?
        """,
        (lesson_id,)
    ).fetchone()

    if not lesson_row:
        flash("Lesson not found.", "danger")
        return redirect(url_for("dashboard"))

    if not student_has_access(
        lesson_row["course_id"]
    ):

        flash(
            "You do not have access to this activity.",
            "danger"
        )

        return redirect(
            url_for(
                "dashboard"
            )
        )

    activities = db.execute(
        """
        SELECT *
        FROM lesson_activities
        WHERE lesson_id=?
        ORDER BY id
        """,
        (lesson_id,)
    ).fetchall()

    if not activities:

        flash(
            "There is no activity for this lesson yet.",
            "info"
        )

        return redirect(
            url_for(
                "lesson",
                lesson_id=lesson_id
            )
        )

    result_message = None

    if request.method == "POST":

        score = 0
        attempted = 0

        for activity in activities:

            selected = request.form.get(
                f"activity_{activity['id']}"
            )

            if not selected:
                continue

            attempted += 1

            correct = (
                selected.upper()
                == activity["answer"].upper()
            )

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
                    g.user["id"],
                    activity["id"],
                    selected,
                    1 if correct else 0,
                    now()
                )
            )

        db.commit()

        if attempted:

            touch_student_activity(
                course_id=lesson_row["course_id"],
                activity=True
            )

            result_message = (
                f"You scored {score} out of "
                f"{attempted}."
            )

            create_notification(
                g.user["id"],
                "Lesson activity completed",
                result_message,
                "success" if score == attempted else "info"
            )

        else:

            result_message = (
                "Please answer at least one question."
            )

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <meta name="viewport"
                  content="width=device-width,initial-scale=1">

            <title>Lesson Activity</title>

            <style>
                body{
                    font-family:Arial,sans-serif;
                    background:#f3f6fb;
                    margin:0;
                    padding:20px;
                }

                .container{
                    max-width:800px;
                    margin:auto;
                }

                .header{
                    background:#102a56;
                    color:white;
                    padding:25px;
                    border-radius:15px;
                    margin-bottom:20px;
                }

                .question{
                    background:white;
                    padding:20px;
                    margin-bottom:15px;
                    border-radius:12px;
                    box-shadow:0 3px 12px rgba(0,0,0,.06);
                }

                label{
                    display:block;
                    padding:10px;
                    margin:7px 0;
                    background:#f4f6f9;
                    border-radius:8px;
                    cursor:pointer;
                }

                button{
                    width:100%;
                    padding:15px;
                    background:#f5c400;
                    border:0;
                    border-radius:10px;
                    font-weight:bold;
                    font-size:16px;
                }

                .result{
                    background:#e8f8ed;
                    padding:15px;
                    border-radius:10px;
                    margin-bottom:20px;
                }

                a{
                    display:inline-block;
                    margin-top:20px;
                    color:#102a56;
                    font-weight:bold;
                }
            </style>
        </head>

        <body>

        <div class="container">

            <div class="header">
                <h1>Interactive Lesson Activity</h1>
                <p>
                    {{ lesson["course_title"] }}
                </p>
                <strong>
                    {{ lesson["title"] }}
                </strong>
            </div>

            {% if result_message %}
                <div class="result">
                    <strong>{{ result_message }}</strong>
                </div>
            {% endif %}

            <form method="post">

                {% for activity in activities %}

                    <div class="question">

                        <h3>
                            {{ loop.index }}.
                            {{ activity["question"] }}
                        </h3>

                        <label>
                            <input
                                type="radio"
                                name="activity_{{ activity['id'] }}"
                                value="A"
                            >
                            A. {{ activity["option_a"] }}
                        </label>

                        <label>
                            <input
                                type="radio"
                                name="activity_{{ activity['id'] }}"
                                value="B"
                            >
                            B. {{ activity["option_b"] }}
                        </label>

                        <label>
                            <input
                                type="radio"
                                name="activity_{{ activity['id'] }}"
                                value="C"
                            >
                            C. {{ activity["option_c"] }}
                        </label>

                        <label>
                            <input
                                type="radio"
                                name="activity_{{ activity['id'] }}"
                                value="D"
                            >
                            D. {{ activity["option_d"] }}
                        </label>

                    </div>

                {% endfor %}

                <button type="submit">
                    Submit Activity
                </button>

            </form>

            <a href="{{ url_for(
                'lesson',
                lesson_id=lesson['id']
            ) }}">
                ← Back to Lesson
            </a>

        </div>

        </body>
        </html>
        """,
        lesson=lesson_row,
        activities=activities,
        result_message=result_message
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

    db = get_db()

    course_row = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course_row:
        flash("Course not found.", "danger")
        return redirect(url_for("dashboard"))

    if not student_has_access(course_id):

        flash(
            "You do not have access to this quiz.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
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

    score = None

    if request.method == "POST":

        score = 0

        for question in questions:

            answer = request.form.get(
                f"question_{question['id']}"
            )

            if not answer:
                continue

            correct = (
                answer.upper()
                == question["answer"].upper()
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
                    g.user["id"],
                    question["id"],
                    answer,
                    1 if correct else 0,
                    now()
                )
            )

        db.commit()

        touch_student_activity(
            course_id=course_id,
            quiz=True
        )

        create_notification(
            g.user["id"],
            "Quiz submitted",
            f"You scored {score} out of {len(questions)}.",
            "success"
        )

        flash(
            f"Quiz submitted. Score: {score}/{len(questions)}",
            "success"
        )

    return render_template(
        "quiz.html",
        course=course_row,
        questions=questions,
        score=score
    )


# ============================================================
# PAYMENT
# ============================================================

@app.route(
    "/pay/<int:course_id>",
    methods=["GET", "POST"]
)
@login_required
def pay(course_id):

    db = get_db()

    course_row = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course_row:

        flash(
            "Course not found.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    if request.method == "POST":

        amount = request.form.get(
            "amount",
            "0"
        ).strip()

        reference = request.form.get(
            "reference",
            ""
        ).strip()

        try:
            amount_value = float(amount)
        except ValueError:
            amount_value = 0

        if amount_value <= 0:

            flash(
                "Please enter a valid payment amount.",
                "danger"
            )

            return render_template(
                "payment.html",
                course=course_row
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
                g.user["id"],
                course_id,
                amount_value,
                reference,
                "pending",
                now()
            )
        )

        db.commit()

        notify_admins(
            "New payment submitted",
            f"{g.user['full_name']} submitted a payment for {course_row['title']}.",
            "payment"
        )

        create_notification(
            g.user["id"],
            "Payment submitted",
            f"Your payment for {course_row['title']} is waiting for admin approval.",
            "payment"
        )

        flash(
            "Payment submitted successfully.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "payment.html",
        course=course_row
    )


# ============================================================
# CERTIFICATE
# ============================================================

@app.route(
    "/certificate/<int:course_id>"
)
@login_required
def certificate(course_id):

    db = get_db()

    course_row = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if not course_row:
        return "Course not found", 404

    lessons = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM lessons
        WHERE course_id=?
        """,
        (course_id,)
    ).fetchone()["total"]

    completed = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM lesson_progress lp
        JOIN lessons l
            ON l.id=lp.lesson_id
        WHERE lp.user_id=?
        AND l.course_id=?
        AND lp.completed=1
        """,
        (
            g.user["id"],
            course_id
        )
    ).fetchone()["total"]

    if lessons == 0 or completed < lessons:

        return (
            "Certificate is available after completing "
            "all lessons.",
            403
        )

    filename = (
        f"certificate_{g.user['id']}_{course_id}.pdf"
    )

    filepath = os.path.join(
        CERT_DIR,
        filename
    )

    pdf = canvas.Canvas(
        filepath,
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
        g.user["full_name"]
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
        course_row["title"]
    )

    pdf.setFont(
        "Helvetica",
        12
    )

    pdf.drawCentredString(
        width / 2,
        100,
        "Learn. Revise. Achieve."
    )

    pdf.save()

    return Response(
        open(filepath, "rb").read(),
        mimetype="application/pdf",
        headers={
            "Content-Disposition":
            f"inline; filename={filename}"
        }
    )


@app.route(
    "/my-certificate/<int:course_id>"
)
@login_required
def my_certificate(course_id):

    return redirect(
        url_for(
            "certificate",
            course_id=course_id
        )
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
@admin_required
def admin():

    db = get_db()

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
        """
    ).fetchall()

    courses = db.execute(
        """
        SELECT *
        FROM courses
        ORDER BY id
        """
    ).fetchall()

    reports_count = db.execute(
        """
        SELECT COUNT(*) AS c
        FROM student_reports
        WHERE status='pending'
        """
    ).fetchone()["c"]

    students_count = db.execute(
        """
        SELECT COUNT(*) AS c
        FROM users
        WHERE role='student'
        """
    ).fetchone()["c"]

    return render_template(
        "admin.html",
        payments=payments,
        courses=courses,
        reports_count=reports_count,
        students_count=students_count
    )


# ============================================================
# ADMIN PAYMENT APPROVAL
# ============================================================

@app.route(
    "/admin/payment/<int:payment_id>/approve",
    methods=["POST"]
)
@admin_required
def approve_payment(payment_id):

    db = get_db()

    payment = db.execute(
        """
        SELECT
            p.*,
            c.title AS course_title
        FROM payments p
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

    db.execute(
        """
        UPDATE payments
        SET status='approved'
        WHERE id=?
        """,
        (payment_id,)
    )

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
            SET status='approved'
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
            VALUES(?,?,?,?,?)
            """,
            (
                payment["user_id"],
                payment["course_id"],
                "approved",
                now()
            )
        )

    db.commit()

    create_notification(
        payment["user_id"],
        "Payment approved",
        f"Your payment has been approved. You now have access to {payment['course_title']}.",
        "success"
    )

    flash(
        "Payment approved and course activated.",
        "success"
    )

    return redirect(
        url_for("admin")
    )


# ============================================================
# ADMIN LESSON MANAGEMENT
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
            "course_id"
        )

        title = request.form.get(
            "title",
            ""
        ).strip()

        content = request.form.get(
            "content",
            ""
        ).strip()

        position = request.form.get(
            "position",
            "1"
        )

        try:
            position = int(position)
        except ValueError:
            position = 1

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
        "admin_quiz_form.html",
        courses=courses
    )


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
        return "Lesson not found", 404

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        content = request.form.get(
            "content",
            ""
        ).strip()

        position = request.form.get(
            "position",
            "1"
        )

        try:
            position = int(position)
        except ValueError:
            position = lesson_row["position"]

        db.execute(
            """
            UPDATE lessons
            SET title=?,
                content=?,
                position=?
            WHERE id=?
            """,
            (
                title,
                content,
                position,
                lesson_id
            )
        )

        db.commit()

        flash(
            "Lesson updated.",
            "success"
        )

        return redirect(
            url_for("admin")
        )

    return render_template(
        "admin_quiz_form.html",
        lesson=lesson_row
    )


@app.route(
    "/admin/lesson/<int:lesson_id>/delete",
    methods=["POST"]
)
@admin_required
def delete_lesson(lesson_id):

    db = get_db()

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
# ADMIN COURSE TOGGLE
# ============================================================

@app.route(
    "/admin/course/<int:course_id>/toggle",
    methods=["POST"]
)
@admin_required
def toggle_course(course_id):

    db = get_db()

    db.execute(
        """
        UPDATE courses
        SET active =
            CASE
                WHEN active=1 THEN 0
                ELSE 1
            END
        WHERE id=?
        """,
        (course_id,)
    )

    db.commit()

    flash(
        "Course status updated.",
        "success"
    )

    return redirect(
        url_for("admin")
    )


# ============================================================
# ADMIN QUIZZES
# ============================================================

@app.route(
    "/admin/quizzes/<int:course_id>"
)
@admin_required
def admin_quizzes(course_id):

    db = get_db()

    course_row = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

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
        course=course_row,
        questions=questions
    )


@app.route(
    "/admin/quizzes/<int:course_id>/add",
    methods=["GET", "POST"]
)
@admin_required
def add_quiz(course_id):

    db = get_db()

    course_row = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    if request.method == "POST":

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
                request.form.get("question", ""),
                request.form.get("option_a", ""),
                request.form.get("option_b", ""),
                request.form.get("option_c", ""),
                request.form.get("option_d", ""),
                request.form.get("answer", "").upper(),
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
        course=course_row
    )


@app.route(
    "/admin/quizzes/question/<int:question_id>/edit",
    methods=["GET", "POST"]
)
@admin_required
def edit_quiz_question(question_id):

    db = get_db()

    question = db.execute(
        """
        SELECT *
        FROM quizzes
        WHERE id=?
        """,
        (question_id,)
    ).fetchone()

    if not question:
        return "Question not found", 404

    if request.method == "POST":

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
                request.form.get("question", ""),
                request.form.get("option_a", ""),
                request.form.get("option_b", ""),
                request.form.get("option_c", ""),
                request.form.get("option_d", ""),
                request.form.get("answer", "").upper(),
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
                course_id=question["course_id"]
            )
        )

    return render_template(
        "admin_quiz_form.html",
        question=question
    )


@app.route(
    "/admin/quizzes/question/<int:question_id>/delete",
    methods=["POST"]
)
@admin_required
def delete_quiz_question(question_id):

    db = get_db()

    question = db.execute(
        """
        SELECT course_id
        FROM quizzes
        WHERE id=?
        """,
        (question_id,)
    ).fetchone()

    if question:

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
                course_id=question["course_id"]
            )
        )

    return redirect(
        url_for("admin")
    )


# ============================================================
# RESULTS
# ============================================================

@app.route(
    "/results/<int:course_id>"
)
@login_required
def results(course_id):

    db = get_db()

    course_row = db.execute(
        """
        SELECT *
        FROM courses
        WHERE id=?
        """,
        (course_id,)
    ).fetchone()

    results = db.execute(
        """
        SELECT
            q.question,
            qa.answer,
            qa.correct,
            qa.attempted_at
        FROM quiz_attempts qa
        JOIN quizzes q
            ON q.id=qa.quiz_id
        WHERE qa.user_id=?
        AND q.course_id=?
        ORDER BY qa.id DESC
        """,
        (
            g.user["id"],
            course_id
        )
    ).fetchall()

    return render_template(
        "results.html",
        course=course_row,
        results=results
    )


# ============================================================
# ADMIN STUDENTS
# ============================================================

@app.route("/admin/students")
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
# ADMIN STUDENT VIEW
# ============================================================

@app.route(
    "/admin/student/<int:user_id>"
)
@admin_required
def admin_student(user_id):

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
        return "Student not found", 404

    activity = db.execute(
        """
        SELECT *
        FROM student_activity
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    enrollments = db.execute(
        """
        SELECT
            e.*,
            c.title
        FROM enrollments e
        JOIN courses c
            ON c.id=e.course_id
        WHERE e.user_id=?
        """,
        (user_id,)
    ).fetchall()

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
        enrollments=enrollments,
        reports=reports
    )


# ============================================================
# ADMIN PARENT CONTACTS
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
            u.id,
            u.full_name,
            u.email,
            u.phone,
            u.parent_phone,
            sa.last_active
        FROM users u
        LEFT JOIN student_activity sa
            ON sa.user_id=u.id
        WHERE u.role='student'
        ORDER BY u.full_name
        """
    ).fetchall()

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <meta name="viewport"
                  content="width=device-width,initial-scale=1">
            <title>Parent Contacts</title>
            <style>
                body{
                    font-family:Arial,sans-serif;
                    background:#f4f6f9;
                    padding:20px;
                }

                .container{
                    max-width:1100px;
                    margin:auto;
                }

                table{
                    width:100%;
                    border-collapse:collapse;
                    background:white;
                }

                th,td{
                    padding:12px;
                    border-bottom:1px solid #ddd;
                    text-align:left;
                }

                th{
                    background:#102a56;
                    color:white;
                }

                a{
                    text-decoration:none;
                    font-weight:bold;
                }

                .wa{
                    color:#168f3b;
                }

                .call{
                    color:#1557a6;
                }

                .back{
                    display:inline-block;
                    margin-bottom:20px;
                }
            </style>
        </head>
        <body>

        <div class="container">

            <a class="back"
               href="{{ url_for('admin') }}">
               ← Admin Dashboard
            </a>

            <h1>Parent / Guardian Contacts</h1>

            <table>

                <tr>
                    <th>Student</th>
                    <th>Email</th>
                    <th>Parent Phone</th>
                    <th>Contact</th>
                    <th>Last Active</th>
                </tr>

                {% for student in students %}

                <tr>

                    <td>
                        {{ student["full_name"] }}
                    </td>

                    <td>
                        {{ student["email"] }}
                    </td>

                    <td>
                        {{ student["parent_phone"] or
                           "NOT PROVIDED" }}
                    </td>

                    <td>

                        {% if student["parent_phone"] %}

                            <a class="call"
                               href="tel:{{ student['parent_phone'] }}">
                               Call
                            </a>

                            &nbsp;

                            <a class="wa"
                               target="_blank"
                               href="{{ whatsapp_link(
                                   student['parent_phone']
                               ) }}">
                               WhatsApp
                            </a>

                        {% else %}

                            No number

                        {% endif %}

                    </td>

                    <td>
                        {{ student["last_active"] or "Never" }}
                    </td>

                </tr>

                {% endfor %}

            </table>

        </div>

        </body>
        </html>
        """,
        students=students,
        whatsapp_link=whatsapp_link
    )


# ============================================================
# ADMIN PARTICIPATION / INACTIVE STUDENTS
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
        ORDER BY sa.last_active ASC
        """
    ).fetchall()

    active = []
    inactive = []
    no_parent = []

    cutoff = datetime.utcnow() - timedelta(days=7)

    for student in students:

        last_active = None

        if student["last_active"]:

            try:
                last_active = datetime.fromisoformat(
                    student["last_active"]
                )
            except ValueError:
                last_active = None

        is_inactive = (
            last_active is None
            or last_active < cutoff
        )

        item = {
            "student": student,
            "inactive": is_inactive
        }

        if is_inactive:
            inactive.append(item)
        else:
            active.append(item)

        if not student["parent_phone"]:
            no_parent.append(student)

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <meta name="viewport"
                  content="width=device-width,initial-scale=1">

            <title>Student Participation</title>

            <style>

                body{
                    font-family:Arial,sans-serif;
                    background:#f4f6f9;
                    margin:0;
                    padding:20px;
                }

                .container{
                    max-width:1200px;
                    margin:auto;
                }

                .cards{
                    display:grid;
                    grid-template-columns:
                        repeat(auto-fit,minmax(180px,1fr));
                    gap:15px;
                    margin:20px 0;
                }

                .card{
                    background:white;
                    padding:20px;
                    border-radius:12px;
                    box-shadow:0 2px 10px rgba(0,0,0,.06);
                }

                .number{
                    font-size:30px;
                    font-weight:bold;
                    color:#102a56;
                }

                table{
                    width:100%;
                    border-collapse:collapse;
                    background:white;
                    margin-bottom:30px;
                }

                th,td{
                    padding:11px;
                    border-bottom:1px solid #ddd;
                    text-align:left;
                }

                th{
                    background:#102a56;
                    color:white;
                }

                .inactive{
                    background:#fff0f0;
                }

                .active{
                    background:#effaf1;
                }

                .button{
                    display:inline-block;
                    padding:8px 12px;
                    border-radius:7px;
                    background:#102a56;
                    color:white;
                    text-decoration:none;
                    margin:2px;
                }

                .wa{
                    background:#168f3b;
                }

            </style>
        </head>

        <body>

        <div class="container">

            <p>
                <a href="{{ url_for('admin') }}">
                    ← Admin Dashboard
                </a>
            </p>

            <h1>Student Participation Monitor</h1>

            <div class="cards">

                <div class="card">
                    <div>Total Students</div>
                    <div class="number">
                        {{ students|length }}
                    </div>
                </div>

                <div class="card">
                    <div>Active</div>
                    <div class="number">
                        {{ active|length }}
                    </div>
                </div>

                <div class="card">
                    <div>Inactive 7+ Days</div>
                    <div class="number">
                        {{ inactive|length }}
                    </div>
                </div>

                <div class="card">
                    <div>No Parent Number</div>
                    <div class="number">
                        {{ no_parent|length }}
                    </div>
                </div>

            </div>

            <h2>Students Requiring Attention</h2>

            <table>

                <tr>
                    <th>Student</th>
                    <th>Last Active</th>
                    <th>Lessons</th>
                    <th>Quizzes</th>
                    <th>Activities</th>
                    <th>Parent</th>
                    <th>Contact</th>
                </tr>

                {% for item in inactive %}

                {% set student = item.student %}

                <tr class="inactive">

                    <td>
                        <strong>
                            {{ student["full_name"] }}
                        </strong>
                    </td>

                    <td>
                        {{ student["last_active"] or "Never" }}
                    </td>

                    <td>
                        {{ student["lessons_completed"] or 0 }}
                    </td>

                    <td>
                        {{ student["quizzes_attempted"] or 0 }}
                    </td>

                    <td>
                        {{ student["activities_attempted"] or 0 }}
                    </td>

                    <td>
                        {{ student["parent_phone"] or
                           "Not provided" }}
                    </td>

                    <td>

                        {% if student["parent_phone"] %}

                            <a class="button"
                               href="tel:{{ student['parent_phone'] }}">
                               Call
                            </a>

                            <a class="button wa"
                               target="_blank"
                               href="{{ whatsapp_link(
                                   student['parent_phone']
                               ) }}">
                               WhatsApp
                            </a>

                        {% endif %}

                        <a class="button"
                           href="{{ url_for(
                               'admin_student',
                               user_id=student['id']
                           ) }}">
                           View
                        </a>

                    </td>

                </tr>

                {% endfor %}

            </table>

            <h2>Currently Active Students</h2>

            <table>

                <tr>
                    <th>Student</th>
                    <th>Last Active</th>
                    <th>Lessons</th>
                    <th>Quizzes</th>
                    <th>Activities</th>
                </tr>

                {% for item in active %}

                {% set student = item.student %}

                <tr class="active">

                    <td>
                        {{ student["full_name"] }}
                    </td>

                    <td>
                        {{ student["last_active"] }}
                    </td>

                    <td>
                        {{ student["lessons_completed"] or 0 }}
                    </td>

                    <td>
                        {{ student["quizzes_attempted"] or 0 }}
                    </td>

                    <td>
                        {{ student["activities_attempted"] or 0 }}
                    </td>

                </tr>

                {% endfor %}

            </table>

        </div>

        </body>
        </html>
        """,
        students=students,
        active=active,
        inactive=inactive,
        no_parent=no_parent,
        whatsapp_link=whatsapp_link
    )


# ============================================================
# STUDENT NOTIFICATIONS
# ============================================================

@app.route("/notifications")
@login_required
def notifications():

    db = get_db()

    rows = db.execute(
        """
        SELECT *
        FROM notifications
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 50
        """,
        (g.user["id"],)
    ).fetchall()

    db.execute(
        """
        UPDATE notifications
        SET is_read=1
        WHERE user_id=?
        """,
        (g.user["id"],)
    )

    db.commit()

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <meta name="viewport"
                  content="width=device-width,initial-scale=1">

            <title>Notifications</title>

            <style>

                body{
                    font-family:Arial,sans-serif;
                    background:#f4f6f9;
                    padding:20px;
                }

                .container{
                    max-width:800px;
                    margin:auto;
                }

                .notification{
                    background:white;
                    padding:18px;
                    border-radius:12px;
                    margin-bottom:12px;
                    box-shadow:0 2px 8px rgba(0,0,0,.05);
                }

                .date{
                    color:#777;
                    font-size:12px;
                }

            </style>
        </head>

        <body>

        <div class="container">

            <p>
                <a href="{{ url_for('dashboard') }}">
                    ← Dashboard
                </a>
            </p>

            <h1>Notifications</h1>

            {% if rows %}

                {% for row in rows %}

                    <div class="notification">

                        <h3>
                            {{ row["title"] }}
                        </h3>

                        <p>
                            {{ row["message"] }}
                        </p>

                        <div class="date">
                            {{ row["created_at"] }}
                        </div>

                    </div>

                {% endfor %}

            {% else %}

                <p>
                    You do not have any notifications yet.
                </p>

            {% endif %}

        </div>

        </body>
        </html>
        """,
        rows=rows
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
                "Please enter a subject and message.",
                "danger"
            )

            return redirect(
                url_for("report_admin")
            )

        db = get_db()

        db.execute(
            """
            INSERT INTO student_reports(
                user_id,
                subject,
                message,
                status,
                created_at
            )
            VALUES(?,?,?,'pending',?)
            """,
            (
                g.user["id"],
                subject,
                message,
                now()
            )
        )

        db.commit()

        notify_admins(
            "New student report",
            f"{g.user['full_name']} submitted: {subject}",
            "report"
        )

        create_notification(
            g.user["id"],
            "Report sent",
            "Your message has been sent to the academy administration.",
            "success"
        )

        flash(
            "Your report has been sent to the administration.",
            "success"
        )

        return redirect(
            url_for("report_admin")
        )

    db = get_db()

    reports = db.execute(
        """
        SELECT *
        FROM student_reports
        WHERE user_id=?
        ORDER BY id DESC
        """,
        (g.user["id"],)
    ).fetchall()

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <meta name="viewport"
                  content="width=device-width,initial-scale=1">

            <title>Contact Admin</title>

            <style>

                body{
                    font-family:Arial,sans-serif;
                    background:#f4f6f9;
                    padding:20px;
                }

                .container{
                    max-width:800px;
                    margin:auto;
                }

                .box{
                    background:white;
                    padding:20px;
                    border-radius:12px;
                    margin-bottom:20px;
                }

                input,textarea{
                    width:100%;
                    box-sizing:border-box;
                    padding:12px;
                    margin:8px 0 15px;
                    border:1px solid #ccc;
                    border-radius:8px;
                }

                textarea{
                    min-height:150px;
                }

                button{
                    background:#f5c400;
                    border:0;
                    padding:13px 20px;
                    border-radius:8px;
                    font-weight:bold;
                }

                .reply{
                    background:#eef7ff;
                    padding:12px;
                    border-radius:8px;
                    margin-top:10px;
                }

            </style>
        </head>

        <body>

        <div class="container">

            <p>
                <a href="{{ url_for('dashboard') }}">
                    ← Dashboard
                </a>
            </p>

            <h1>Contact Administration</h1>

            <div class="box">

                <p>
                    Use this page to report a problem,
                    ask for help or communicate directly
                    with Eagle Vision administration.
                </p>

                <form method="post">

                    <label>Subject</label>

                    <input
                        name="subject"
                        required
                        placeholder="Example: I need help with Mathematics"
                    >

                    <label>Message</label>

                    <textarea
                        name="message"
                        required
                        placeholder="Write your message..."
                    ></textarea>

                    <button type="submit">
                        Send to Admin
                    </button>

                </form>

            </div>

            <h2>Your Reports</h2>

            {% for report in reports %}

                <div class="box">

                    <h3>
                        {{ report["subject"] }}
                    </h3>

                    <p>
                        {{ report["message"] }}
                    </p>

                    <strong>
                        Status:
                        {{ report["status"] }}
                    </strong>

                    {% if report["admin_reply"] %}

                        <div class="reply">

                            <strong>
                                Admin Reply
                            </strong>

                            <p>
                                {{ report["admin_reply"] }}
                            </p>

                        </div>

                    {% endif %}

                </div>

            {% else %}

                <p>
                    You have not sent any reports yet.
                </p>

            {% endfor %}

        </div>

        </body>
        </html>
        """,
        reports=reports
    )


# ============================================================
# ADMIN REPORTS
# ============================================================

@app.route("/admin/reports")
@admin_required
def admin_reports():

    db = get_db()

    reports = db.execute(
        """
        SELECT
            r.*,
            u.full_name,
            u.email
        FROM student_reports r
        JOIN users u
            ON u.id=r.user_id
        ORDER BY
            CASE
                WHEN r.status='pending' THEN 0
                ELSE 1
            END,
            r.id DESC
        """
    ).fetchall()

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <meta name="viewport"
                  content="width=device-width,initial-scale=1">

            <title>Student Reports</title>

            <style>

                body{
                    font-family:Arial,sans-serif;
                    background:#f4f6f9;
                    padding:20px;
                }

                .container{
                    max-width:900px;
                    margin:auto;
                }

                .report{
                    background:white;
                    padding:20px;
                    margin-bottom:15px;
                    border-radius:12px;
                }

                textarea{
                    width:100%;
                    box-sizing:border-box;
                    min-height:100px;
                    padding:12px;
                    border:1px solid #ccc;
                    border-radius:8px;
                }

                button{
                    margin-top:10px;
                    background:#102a56;
                    color:white;
                    border:0;
                    padding:12px 20px;
                    border-radius:8px;
                }

            </style>
        </head>

        <body>

        <div class="container">

            <p>
                <a href="{{ url_for('admin') }}">
                    ← Admin Dashboard
                </a>
            </p>

            <h1>Student Reports</h1>

            {% for report in reports %}

                <div class="report">

                    <h2>
                        {{ report["subject"] }}
                    </h2>

                    <p>
                        <strong>Student:</strong>
                        {{ report["full_name"] }}
                    </p>

                    <p>
                        <strong>Email:</strong>
                        {{ report["email"] }}
                    </p>

                    <p>
                        {{ report["message"] }}
                    </p>

                    <p>
                        <strong>Status:</strong>
                        {{ report["status"] }}
                    </p>

                    {% if report["admin_reply"] %}

                        <hr>

                        <strong>
                            Previous Reply:
                        </strong>

                        <p>
                            {{ report["admin_reply"] }}
                        </p>

                    {% endif %}

                    <form method="post"
                          action="{{ url_for(
                              'reply_report',
                              report_id=report['id']
                          ) }}">

                        <textarea
                            name="admin_reply"
                            placeholder="Write your reply..."
                            required
                        ></textarea>

                        <button type="submit">
                            Reply to Student
                        </button>

                    </form>

                </div>

            {% else %}

                <p>
                    No student reports.
                </p>

            {% endfor %}

        </div>

        </body>
        </html>
        """,
        reports=reports
    )


@app.route(
    "/admin/reports/<int:report_id>/reply",
    methods=["POST"]
)
@admin_required
def reply_report(report_id):

    reply = request.form.get(
        "admin_reply",
        ""
    ).strip()

    if not reply:

        flash(
            "Reply cannot be empty.",
            "danger"
        )

        return redirect(
            url_for("admin_reports")
        )

    db = get_db()

    report = db.execute(
        """
        SELECT *
        FROM student_reports
        WHERE id=?
        """,
        (report_id,)
    ).fetchone()

    if not report:

        flash(
            "Report not found.",
            "danger"
        )

        return redirect(
            url_for("admin_reports")
        )

    db.execute(
        """
        UPDATE student_reports
        SET
            status='replied',
            admin_reply=?,
            replied_at=?
        WHERE id=?
        """,
        (
            reply,
            now(),
            report_id
        )
    )

    db.commit()

    create_notification(
        report["user_id"],
        "Admin replied to your report",
        reply,
        "admin"
    )

    flash(
        "Reply sent to the student.",
        "success"
    )

    return redirect(
        url_for("admin_reports")
    )


# ============================================================
# ADMIN SEND DIRECT NOTIFICATION
# ============================================================

@app.route(
    "/admin/student/<int:user_id>/notify",
    methods=["POST"]
)
@admin_required
def admin_notify_student(user_id):

    title = request.form.get(
        "title",
        ""
    ).strip()

    message = request.form.get(
        "message",
        ""
    ).strip()

    if not title or not message:

        flash(
            "Title and message are required.",
            "danger"
        )

        return redirect(
            url_for(
                "admin_student",
                user_id=user_id
            )
        )

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

    create_notification(
        user_id,
        title,
        message,
        "admin"
    )

    flash(
        "Notification sent to student.",
        "success"
    )

    return redirect(
        url_for(
            "admin_student",
            user_id=user_id
        )
    )


# ============================================================
# ADMIN ADD INTERACTIVE ACTIVITY
# ============================================================

@app.route(
    "/admin/activity/<int:lesson_id>/add",
    methods=["GET", "POST"]
)
@admin_required
def add_activity(lesson_id):

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
        return "Lesson not found", 404

    if request.method == "POST":

        db.execute(
            """
            INSERT INTO lesson_activities(
                lesson_id,
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
                lesson_id,
                request.form.get("question", ""),
                request.form.get("option_a", ""),
                request.form.get("option_b", ""),
                request.form.get("option_c", ""),
                request.form.get("option_d", ""),
                request.form.get("answer", "").upper()
            )
        )

        db.commit()

        flash(
            "Interactive activity added.",
            "success"
        )

        return redirect(
            url_for(
                "lesson",
                lesson_id=lesson_id
            )
        )

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <meta name="viewport"
                  content="width=device-width,initial-scale=1">

            <title>Add Activity</title>

            <style>

                body{
                    font-family:Arial,sans-serif;
                    background:#f4f6f9;
                    padding:20px;
                }

                .box{
                    max-width:700px;
                    margin:auto;
                    background:white;
                    padding:25px;
                    border-radius:14px;
                }

                input,select{
                    width:100%;
                    box-sizing:border-box;
                    padding:12px;
                    margin:7px 0 15px;
                }

                button{
                    background:#f5c400;
                    border:0;
                    padding:13px 20px;
                    border-radius:8px;
                    font-weight:bold;
                }

            </style>
        </head>

        <body>

        <div class="box">

            <h1>Add Interactive Activity</h1>

            <p>
                Lesson:
                <strong>
                    {{ lesson["title"] }}
                </strong>
            </p>

            <form method="post">

                <label>Question</label>
                <input name="question" required>

                <label>Option A</label>
                <input name="option_a" required>

                <label>Option B</label>
                <input name="option_b" required>

                <label>Option C</label>
                <input name="option_c" required>

                <label>Option D</label>
                <input name="option_d" required>

                <label>Correct Answer</label>

                <select name="answer" required>
                    <option value="">Choose</option>
                    <option value="A">A</option>
                    <option value="B">B</option>
                    <option value="C">C</option>
                    <option value="D">D</option>
                </select>

                <button type="submit">
                    Add Activity
                </button>

            </form>

        </div>

        </body>
        </html>
        """,
        lesson=lesson_row
    )


# ============================================================
# TEACHER DASHBOARD
# ============================================================

@app.route("/teacher")
@teacher_
Preview truncated for large file
