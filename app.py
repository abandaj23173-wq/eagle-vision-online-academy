import os
import sqlite3
from functools import wraps
from datetime import datetime

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    g,
    send_file,
)

from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4


# =========================================================
# APP SETUP
# =========================================================

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "academy.db")
CERT_DIR = os.path.join(BASE, "certificates")

os.makedirs(CERT_DIR, exist_ok=True)

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION"
)


# =========================================================
# DATABASE
# =========================================================

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

    # -----------------------------------------------------
    # TABLES
    # -----------------------------------------------------

    conn.executescript(
        """
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
            answer TEXT NOT NULL,
            FOREIGN KEY(course_id) REFERENCES courses(id)
        );

        CREATE TABLE IF NOT EXISTS quiz_attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            quiz_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            attempted_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(quiz_id) REFERENCES quizzes(id)
        );

        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            reference TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(course_id) REFERENCES courses(id)
        );
        """
    )

    # =====================================================
    # COURSES
    # =====================================================

    if conn.execute(
        "SELECT COUNT(*) FROM courses"
    ).fetchone()[0] == 0:

        courses = [
            (
                "Form 1 Mathematics",
                "Form 1",
                "Build strong foundations in mathematics.",
                5,
            ),
            (
                "Form 2 Mathematics",
                "Form 2",
                "Master key Form 2 concepts and exam skills.",
                5,
            ),
            (
                "Form 3 Mathematics",
                "Form 3",
                "Develop problem-solving and examination confidence.",
                5,
            ),
            (
                "O-Level Mathematics",
                "Form 4 / O-Level",
                "Complete revision, past papers and exam strategy.",
                10,
            ),
            (
                "O-Level Science",
                "Form 4 / O-Level",
                "Science concepts, practical thinking and exam practice.",
                10,
            ),
            (
                "O-Level Geography",
                "Form 4 / O-Level",
                "Geography concepts, maps, data and examination practice.",
                10,
            ),
            (
                "A-Level History",
                "Lower 6 / A-Level",
                "Structured history lessons and essay practice.",
                10,
            ),
        ]

        conn.executemany(
            """
            INSERT INTO courses
            (title, level, description, price)
            VALUES (?, ?, ?, ?)
            """,
            courses,
        )

        conn.commit()

        # ====================================================
    # LESSONS
    # ====================================================

    course_rows = conn.execute(
        "SELECT id, title FROM courses"
    ).fetchall()

    lesson_content = {

        "Form 1 Mathematics": [
            (
                "Number Skills",
                """Numbers are the foundation of mathematics. In this lesson,
students learn place value, factors, multiples, prime numbers, fractions,
decimals and percentages.

Worked example:
Find 25% of 80.
25% = 25/100
25/100 × 80 = 20

Practice:
1. Find the factors of 24.
2. Convert 0.75 into a fraction.
3. Find 15% of 200.""",
                1
            ),
            (
                "Algebra Basics",
                """Algebra uses letters to represent unknown numbers.

Example:
If x + 7 = 15, subtract 7 from both sides:
x = 8.

Students should learn to simplify expressions, substitute values and
solve simple equations.

Practice:
1. Simplify 3x + 2x.
2. Solve x + 9 = 17.
3. Find the value of 2a + 3 when a = 4.""",
                2
            ),
            (
                "Geometry and Measurement",
                """Geometry deals with shapes, angles, length, area and volume.

Important ideas include:
• Angles on a straight line total 180°.
• Angles around a point total 360°.
• The area of a rectangle is length × width.
• The perimeter of a rectangle is 2(length + width).

Practice:
1. Find the area of a rectangle measuring 8 cm by 5 cm.
2. Find the perimeter of a rectangle measuring 7 cm by 4 cm.
3. Find the missing angle on a straight line if one angle is 65°.""",
                3
            ),
        ],

        "Form 2 Mathematics": [
            (
                "Algebraic Expressions",
                """Algebraic expressions contain numbers, variables and operations.

Like terms can be combined.

Example:
3x + 5x - 2 = 8x - 2.

When multiplying:
4 × x = 4x.

When substituting x = 3 into 2x + 5:
2(3) + 5 = 11.

Practice:
1. Simplify 7x + 3x - 4.
2. Simplify 5a + 2a + 6.
3. Find the value of 3x + 2 when x = 4.""",
                1
            ),
            (
                "Linear Equations and Graphs",
                """A linear equation can be solved by keeping both sides balanced.

Example:
3x + 4 = 19
3x = 15
x = 5.

Linear graphs can be represented using ordered pairs and coordinate axes.

Remember:
The horizontal axis is the x-axis.
The vertical axis is the y-axis.

Practice:
1. Solve 2x + 7 = 17.
2. Solve 5x - 3 = 22.
3. Plot the points (1,2), (2,4) and (3,6).""",
                2
            ),
            (
                "Geometry and Mensuration",
                """Mensuration involves measuring lengths, areas and volumes.

For a triangle:
Area = ½ × base × height.

For a rectangle:
Area = length × width.

Angles in a triangle add up to 180°.

Example:
A triangle has angles 50° and 60°.
Third angle = 180° - 50° - 60° = 70°.

Practice:
1. Find the area of a triangle with base 10 cm and height 6 cm.
2. Find the missing angle in a triangle with angles 45° and 75°.
3. Find the area of a rectangle measuring 12 cm by 5 cm.""",
                3
            ),
        ],

        "Form 3 Mathematics": [
            (
                "Advanced Algebra",
                """Form 3 algebra develops skills in equations, factorisation
and algebraic manipulation.

Example:
x² + 5x + 6
= (x + 2)(x + 3).

Students should practise collecting like terms, expanding brackets and
factorising expressions.

Practice:
1. Expand (x + 3)(x + 2).
2. Factorise x² + 7x + 12.
3. Solve 2x + 5 = 17.""",
                1
            ),
            (
                "Functions and Graphs",
                """A function connects an input value to an output value.

For y = 2x + 1:

If x = 1:
y = 2(1) + 1 = 3.

If x = 2:
y = 2(2) + 1 = 5.

Tables of values can be used to plot straight-line graphs.

Practice:
1. Find y when x = 4 for y = 3x + 2.
2. Complete a table for y = 2x - 1.
3. Plot a straight-line graph from a table of values.""",
                2
            ),
            (
                "Trigonometry and Geometry",
                """Trigonometry can be used to calculate unknown sides and angles
in right-angled triangles.

The three basic ratios are sine, cosine and tangent.

Students should identify the opposite, adjacent and hypotenuse sides
before choosing a ratio.

Practice:
1. Identify the hypotenuse in a right-angled triangle.
2. State which trigonometric ratio uses opposite and adjacent sides.
3. Use a suitable trigonometric ratio to find an unknown angle.""",
                3
            ),
        ],

        "O-Level Mathematics": [
            (
                "Number and Algebra Revision",
                """O-Level Mathematics requires strong number and algebra skills.

Revise:
• Fractions
• Decimals
• Percentages
• Indices
• Standard form
• Algebraic expressions
• Equations
• Simultaneous equations

Example:
2x + 3 = 11
2x = 8
x = 4.

Practice:
1. Solve 4x - 7 = 21.
2. Simplify 3a + 5a - 2.
3. Convert 0.125 into a fraction.""",
                1
            ),
            (
                "Geometry, Graphs and Trigonometry",
                """Geometry questions require careful use of angle facts,
shape properties and measurement formulas.

Important facts:
Angles in a triangle = 180°.
Angles in a quadrilateral = 360°.

Trigonometry is especially useful in right-angled triangles.

Students should show working clearly and include correct units.

Practice:
1. Find a missing angle in a triangle.
2. Calculate the area of a circle when the radius is given.
3. Use trigonometry to find an unknown side.""",
                2
            ),
            (
                "Statistics and Exam Practice",
                """Statistics includes mean, median, mode and range.

Example:
For 2, 4, 6, 8, 10:
Mean = 30 ÷ 5 = 6.

Exam technique is also important. Read every question carefully,
show your working and check your final answer.

Practice:
1. Find the mean of 4, 6, 8 and 10.
2. Find the range of 3, 9, 5, 12 and 7.
3. Attempt a past-examination-style mathematics question.""",
                3
            ),
        ],

        "O-Level Science": [
            (
                "Cells and Living Organisms",
                """Cells are the basic units of living organisms.

Plant cells contain structures such as the cell wall, cell membrane,
cytoplasm, nucleus, chloroplasts and a large permanent vacuole.

Animal cells contain a cell membrane, cytoplasm and nucleus but do not
have a cell wall or chloroplasts.

Practice:
1. State the function of the nucleus.
2. Name a structure found in plant cells but not animal cells.
3. Explain why chloroplasts are important to plants.""",
                1
            ),
            (
                "Matter and Chemical Reactions",
                """Matter exists mainly as solids, liquids and gases.

Chemical reactions produce new substances.

Signs of a chemical reaction may include a colour change, gas production,
temperature change or formation of a precipitate.

Students should learn to identify reactants and products.

Practice:
1. Name the three common states of matter.
2. Give one sign of a chemical reaction.
3. Distinguish between a physical and chemical change.""",
                2
            ),
            (
                "Forces, Energy and Practical Skills",
                """Forces can change the motion or shape of objects.

Energy can be transferred between different forms.

Science examinations also test practical skills such as identifying
variables, recording results, drawing tables and interpreting graphs.

Practice:
1. Give two effects of a force.
2. Name two forms of energy.
3. Identify the independent variable in a simple experiment.""",
                3
            ),
        ],

        "O-Level Geography": [
            (
                "Mapwork Skills",
                """Mapwork is an important part of Geography.

Students should understand grid references, direction, scale, distance,
symbols and contour lines.

Always read the map carefully before answering questions.

Practice:
1. What is a grid reference used for?
2. What information does a map scale provide?
3. Explain what closely spaced contour lines indicate.""",
                1
            ),
            (
                "Physical Geography",
                """Physical Geography studies natural processes and features.

Topics include weather, climate, rivers, rocks, soils and landforms.

Rivers can erode, transport and deposit material.

Practice:
1. Name three processes of river erosion.
2. Explain how a river can transport sediment.
3. Distinguish between weather and climate.""",
                2
            ),
            (
                "Human Geography and Environment",
                """Human Geography examines how people interact with places.

Topics include population, settlement, agriculture, industry,
transport and environmental management.

Students should learn causes, effects and possible solutions when
answering environmental questions.

Practice:
1. Give two factors affecting population distribution.
2. State two environmental problems caused by human activity.
3. Suggest one way of conserving natural resources.""",
                3
            ),
        ],

        "A-Level History": [
            (
                "Zimbabwe and African History",
                """History involves studying change and continuity over time.

Students should identify causes, events, consequences and significance.

When answering an essay question, develop arguments and support them
with relevant historical evidence.

Practice:
1. Explain two causes of a major historical event.
2. Identify two consequences of a historical development.
3. Write a paragraph using specific historical evidence.""",
                1
            ),
            (
                "Source Analysis",
                """Historical sources can include speeches, letters,
photographs, newspapers and official documents.

When analysing a source, consider its content, origin, purpose,
context and reliability.

Do not simply copy the source. Explain what the evidence means.

Practice:
1. Identify the purpose of a historical source.
2. Explain one reason why a source may be biased.
3. Compare information from two different sources.""",
                2
            ),
            (
                "Essay Writing and Examination Skills",
                """A strong History essay needs a clear argument,
well-developed paragraphs and relevant evidence.

A useful paragraph structure is:
Point → Evidence → Explanation → Link.

Always answer the exact question asked and organise your ideas logically.

Practice:
1. Write an introduction to a History essay.
2. Develop one argument using supporting evidence.
3. Write a conclusion that answers the question directly.""",
                3
            ),
        ],
    }

    for course_row in course_rows:

        course_id = course_row["id"]
        course_title = course_row["title"]

        lessons = lesson_content.get(course_title, [])

        for title, content, position in lessons:

            existing = conn.execute(
                """
                SELECT id
                FROM lessons
                WHERE course_id = ? AND position = ?
                """,
                (course_id, position),
            ).fetchone()

            if existing:

                conn.execute(
                    """
                    UPDATE lessons
                    SET title = ?, content = ?
                    WHERE id = ?
                    """,
                    (title, content, existing["id"]),
                )

            else:

                conn.execute(
                    """
                    INSERT INTO lessons
                    (course_id, title, content, video_url, position)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (course_id, title, content, "", position),
                )

    conn.commit()
    # =====================================================
    # FORM 1 MATHEMATICS QUIZ
    # =====================================================

    form1_course = conn.execute(
        """
        SELECT id
        FROM courses
        WHERE title = 'Form 1 Mathematics'
        """
    ).fetchone()

    if form1_course and conn.execute(
        "SELECT COUNT(*) FROM quizzes WHERE course_id=?",
        (form1_course["id"],),
    ).fetchone()[0] == 0:

        questions = [
            (
                form1_course["id"],
                "What is 15 + 27?",
                "32",
                "42",
                "52",
                "62",
                "B",
            ),
            (
                form1_course["id"],
                "What is 7 × 6?",
                "36",
                "42",
                "48",
                "56",
                "B",
            ),
            (
                form1_course["id"],
                "What is the place value of 5 in 3,542?",
                "5",
                "50",
                "500",
                "5000",
                "C",
            ),
            (
                form1_course["id"],
                "Which fraction is equivalent to 1/2?",
                "1/3",
                "2/4",
                "3/5",
                "4/5",
                "B",
            ),
        ]

        conn.executemany(
            """
            INSERT INTO quizzes
            (course_id, question, option_a, option_b,
             option_c, option_d, answer)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            questions,
        )

        conn.commit()

    # =====================================================
    # FORM 2 MATHEMATICS QUIZ
    # =====================================================

    form2_course = conn.execute(
        """
        SELECT id
        FROM courses
        WHERE title = 'Form 2 Mathematics'
        """
    ).fetchone()

    if form2_course and conn.execute(
        "SELECT COUNT(*) FROM quizzes WHERE course_id=?",
        (form2_course["id"],),
    ).fetchone()[0] == 0:

        questions = [
            (
                form2_course["id"],
                "Solve: x + 7 = 15",
                "6",
                "7",
                "8",
                "9",
                "C",
            ),
            (
                form2_course["id"],
                "What is 25% of 80?",
                "10",
                "15",
                "20",
                "25",
                "C",
            ),
            (
                form2_course["id"],
                "What is the perimeter of a square with side length 6 cm?",
                "12 cm",
                "18 cm",
                "24 cm",
                "36 cm",
                "C",
            ),
            (
                form2_course["id"],
                "Simplify: 3x + 2x",
                "5",
                "5x",
                "6x",
                "x",
                "B",
            ),
        ]

        conn.executemany(
            """
            INSERT INTO quizzes
            (course_id, question, option_a, option_b,
             option_c, option_d, answer)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            questions,
        )

        conn.commit()

    # =====================================================
    # FORM 3 MATHEMATICS QUIZ
    # =====================================================

    form3_course = conn.execute(
        """
        SELECT id
        FROM courses
        WHERE title = 'Form 3 Mathematics'
        """
    ).fetchone()

    if form3_course and conn.execute(
        "SELECT COUNT(*) FROM quizzes WHERE course_id=?",
        (form3_course["id"],),
    ).fetchone()[0] == 0:

        questions = [
            (
                form3_course["id"],
                "Solve: 2x + 4 = 12",
                "2",
                "4",
                "6",
                "8",
                "B",
            ),
            (
                form3_course["id"],
                "What is the gradient of the line y = 3x + 2?",
                "2",
                "3",
                "5",
                "6",
                "B",
            ),
            (
                form3_course["id"],
                "What is √81?",
                "7",
                "8",
                "9",
                "10",
                "C",
            ),
            (
                form3_course["id"],
                "A triangle has angles of 50° and 60°. What is the third angle?",
                "60°",
                "70°",
                "80°",
                "90°",
                "B",
            ),
        ]

        conn.executemany(
            """
            INSERT INTO quizzes
            (course_id, question, option_a, option_b,
             option_c, option_d, answer)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            questions,
        )

        conn.commit()

    # =====================================================
    # O-LEVEL MATHEMATICS QUIZ
    # =====================================================

    math_course = conn.execute(
        """
        SELECT id
        FROM courses
        WHERE title = 'O-Level Mathematics'
        """
    ).fetchone()

    if math_course and conn.execute(
        "SELECT COUNT(*) FROM quizzes WHERE course_id=?",
        (math_course["id"],),
    ).fetchone()[0] == 0:

        questions = [
            (
                math_course["id"],
                "What is 12 × 8?",
                "86",
                "96",
                "108",
                "88",
                "B",
            ),
            (
                math_course["id"],
                "Solve: 2x = 10",
                "2",
                "5",
                "10",
                "20",
                "B",
            ),
        ]

        conn.executemany(
            """
            INSERT INTO quizzes
            (course_id, question, option_a, option_b,
             option_c, option_d, answer)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            questions,
        )

        conn.commit()

    # =====================================================
    # O-LEVEL SCIENCE QUIZ
    # =====================================================

    science_course = conn.execute(
        """
        SELECT id
        FROM courses
        WHERE title = 'O-Level Science'
        """
    ).fetchone()

    if science_course and conn.execute(
        "SELECT COUNT(*) FROM quizzes WHERE course_id=?",
        (science_course["id"],),
    ).fetchone()[0] == 0:

        questions = [
            (
                science_course["id"],
                "Which organ pumps blood around the human body?",
                "Lungs",
                "Heart",
                "Kidney",
                "Liver",
                "B",
            ),
            (
                science_course["id"],
                "Which gas is needed for respiration?",
                "Oxygen",
                "Nitrogen",
                "Carbon dioxide",
                "Hydrogen",
                "A",
            ),
            (
                science_course["id"],
                "What is the SI unit of force?",
                "Joule",
                "Watt",
                "Newton",
                "Pascal",
                "C",
            ),
            (
                science_course["id"],
                "Which part of a plant absorbs most water from the soil?",
                "Flower",
                "Root",
                "Leaf",
                "Fruit",
                "B",
            ),
        ]

        conn.executemany(
            """
            INSERT INTO quizzes
            (course_id, question, option_a, option_b,
             option_c, option_d, answer)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            questions,
        )

        conn.commit()

    # =====================================================
    # O-LEVEL GEOGRAPHY QUIZ
    # =====================================================

    geography_course = conn.execute(
        """
        SELECT id
        FROM courses
        WHERE title = 'O-Level Geography'
        """
    ).fetchone()

    if geography_course and conn.execute(
        "SELECT COUNT(*) FROM quizzes WHERE course_id=?",
        (geography_course["id"],),
    ).fetchone()[0] == 0:

        questions = [
            (
                geography_course["id"],
                "Which instrument is used to measure rainfall?",
                "Thermometer",
                "Rain gauge",
                "Barometer",
                "Anemometer",
                "B",
            ),
            (
                geography_course["id"],
                "What is the main cause of day and night?",
                "The Earth's revolution around the Sun",
                "The Earth's rotation on its axis",
                "The movement of the Moon",
                "Changes in the seasons",
                "B",
            ),
            (
                geography_course["id"],
                "Which type of rainfall occurs when moist air is forced to rise over mountains?",
                "Convectional rainfall",
                "Relief rainfall",
                "Frontal rainfall",
                "Evaporation",
                "B",
            ),
            (
                geography_course["id"],
                "Which layer of the Earth is the solid outer layer on which the continents are found?",
                "Crust",
                "Mantle",
                "Outer core",
                "Inner core",
                "A",
            ),
        ]

        conn.executemany(
            """
            INSERT INTO quizzes
            (course_id, question, option_a, option_b,
             option_c, option_d, answer)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            questions,
        )

        conn.commit()

    # =====================================================
    # A-LEVEL HISTORY QUIZ
    # =====================================================

    history_course = conn.execute(
        """
        SELECT id
        FROM courses
        WHERE title = 'A-Level History'
        """
    ).fetchone()

    if history_course and conn.execute(
        "SELECT COUNT(*) FROM quizzes WHERE course_id=?",
        (history_course["id"],),
    ).fetchone()[0] == 0:

        questions = [
            (
                history_course["id"],
                "What event immediately triggered the First World War in 1914?",
                "The assassination of Archduke Franz Ferdinand",
                "The invasion of Poland",
                "The Russian Revolution",
                "The signing of the Treaty of Versailles",
                "A",
            ),
            (
                history_course["id"],
                "Which country was ruled by Adolf Hitler?",
                "Italy",
                "Germany",
                "France",
                "Russia",
                "B",
            ),
            (
                history_course["id"],
                "What was a major purpose of the Berlin Conference of 1884–1885?",
                "To divide Africa among European powers",
                "To end the First World War",
                "To establish the United Nations",
                "To create the European Union",
                "A",
            ),
            (
                history_course["id"],
                "Which international organization was established after the Second World War to promote peace and cooperation?",
                "League of Nations",
                "United Nations",
                "African Union",
                "European Union",
                "B",
            ),
        ]

        conn.executemany(
            """
            INSERT INTO quizzes
            (course_id, question, option_a, option_b,
             option_c, option_d, answer)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            questions,
        )

        conn.commit()

    # =====================================================
    # ADMIN USER
    # =====================================================

    admin_exists = conn.execute(
        """
        SELECT 1
        FROM users
        WHERE email = 'admin@eaglevisionacademy.co.zw'
        """
    ).fetchone()

    if not admin_exists:
        conn.execute(
            """
            INSERT INTO users
            (full_name, email, phone, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "Eagle Vision Admin",
                "admin@eaglevisionacademy.co.zw",
                "+263 71 741 0018",
                generate_password_hash("ChangeMe123!"),
                "admin",
                datetime.utcnow().isoformat(),
            ),
        )

        conn.commit()


# =========================================================
# USER LOADING
# =========================================================

@app.before_request
def load_user():
    g.user = None

    if session.get("user_id"):
        g.user = db().execute(
            "SELECT * FROM users WHERE id=?",
            (session["user_id"],),
        ).fetchone()


# =========================================================
# ACCESS CONTROL
# =========================================================

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


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():
    courses = db().execute(
        """
        SELECT *
        FROM courses
        WHERE active=1
        ORDER BY id
        """
    ).fetchall()

    return render_template(
        "index.html",
        courses=courses,
    )


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["full_name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form["password"]

        if len(password) < 8:
            flash("Password must be at least 8 characters.")
            return redirect(url_for("register"))

        try:

            cur = db().execute(
                """
                INSERT INTO users
                (full_name, email, phone, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name,
                    email,
                    phone,
                    generate_password_hash(password),
                    datetime.utcnow().isoformat(),
                ),
            )

            db().commit()

            session["user_id"] = cur.lastrowid

            flash("Welcome to the Eagle Family!")

            return redirect(url_for("dashboard"))

        except sqlite3.IntegrityError:

            flash("That email is already registered.")

    return render_template("register.html")


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"].strip().lower()
        password = request.form["password"]

        user = db().execute(
            "SELECT * FROM users WHERE email=?",
            (email,),
        ).fetchone()

        if user and check_password_hash(
            user["password_hash"],
            password,
        ):

            session["user_id"] = user["id"]

            if user["role"] == "admin":
                return redirect(url_for("admin"))

            return redirect(url_for("dashboard"))

        flash("Incorrect email or password.")

    return render_template("login.html")


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("index"))


# =========================================================
# STUDENT DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    courses = db().execute(
        """
        SELECT c.*, e.status
        FROM courses c
        JOIN enrollments e
            ON e.course_id=c.id
        WHERE e.user_id=?
        ORDER BY c.id
        """,
        (g.user["id"],),
    ).fetchall()

    return render_template(
        "dashboard.html",
        courses=courses,
    )


# =========================================================
# COURSE PAGE
# =========================================================

@app.route("/course/<int:course_id>")
@login_required
def course(course_id):

    c = db().execute(
        "SELECT * FROM courses WHERE id=?",
        (course_id,),
    ).fetchone()

    if not c:
        return "Course not found", 404

    enrollment = db().execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=? AND course_id=?
        """,
        (
            g.user["id"],
            course_id,
        ),
    ).fetchone()

    lessons = db().execute(
        """
        SELECT
            l.*,
            COALESCE(p.completed, 0) AS completed
        FROM lessons l
        LEFT JOIN lesson_progress p
            ON p.lesson_id=l.id
            AND p.user_id=?
        WHERE l.course_id=?
        ORDER BY l.position
        """,
        (
            g.user["id"],
            course_id,
        ),
    ).fetchall()

    quizzes = db().execute(
        """
        SELECT *
        FROM quizzes
        WHERE course_id=?
        """,
        (course_id,),
    ).fetchall()

    return render_template(
        "course.html",
        course=c,
        enrollment=enrollment,
        lessons=lessons,
        quizzes=quizzes,
    )


# =========================================================
# ENROL
# =========================================================

@app.route("/enrol/<int:course_id>", methods=["POST"])
@login_required
def enrol(course_id):

    c = db().execute(
        "SELECT * FROM courses WHERE id=?",
        (course_id,),
    ).fetchone()

    if not c:
        return "Course not found", 404

    try:

        db().execute(
            """
            INSERT INTO enrollments
            (user_id, course_id, status, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                g.user["id"],
                course_id,
                "pending",
                datetime.utcnow().isoformat(),
            ),
        )

        db().commit()

        flash(
            "Enrolment request created. "
            "Submit payment to activate your course."
        )

    except sqlite3.IntegrityError:

        flash("You already requested this course.")

    return redirect(
        url_for(
            "course",
            course_id=course_id,
        )
    )


# =========================================================
# LESSON
# =========================================================

@app.route("/lesson/<int:lesson_id>")
@login_required
def lesson(lesson_id):

    l = db().execute(
        "SELECT * FROM lessons WHERE id=?",
        (lesson_id,),
    ).fetchone()

    if not l:
        return "Lesson not found", 404

    course = db().execute(
        "SELECT * FROM courses WHERE id=?",
        (l["course_id"],),
    ).fetchone()

    if not course:
        return "Course not found", 404

    enrollment = db().execute(
        """
        SELECT *
        FROM enrollments
        WHERE user_id=? AND course_id=?
        """,
        (
            g.user["id"],
            l["course_id"],
        ),
    ).fetchone()

    return render_template(
        "lesson.html",
        lesson=l,
        course=course,
        enrollment=enrollment,
    )


# =========================================================
# COMPLETE LESSON
# =========================================================

@app.route(
    "/lesson/<int:lesson_id>/complete",
    methods=["POST"],
)
@login_required
def complete_lesson(lesson_id):

    l = db().execute(
        "SELECT * FROM lessons WHERE id=?",
        (lesson_id,),
    ).fetchone()

    if not l:
        return "Lesson not found", 404

    active = db().execute(
        """
        SELECT 1
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
          AND status='active'
        """,
        (
            g.user["id"],
            l["course_id"],
        ),
    ).fetchone()

    if not active:

        flash(
            "Your course must be activated "
            "before completing lessons."
        )

        return redirect(
            url_for(
                "course",
                course_id=l["course_id"],
            )
        )

    db().execute(
        """
        INSERT INTO lesson_progress
        (user_id, lesson_id, completed, completed_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id, lesson_id)
        DO UPDATE SET
            completed=1,
            completed_at=excluded.completed_at
        """,
        (
            g.user["id"],
            lesson_id,
            datetime.utcnow().isoformat(),
        ),
    )

    db().commit()

    flash("Lesson marked complete.")

    return redirect(
        url_for(
            "course",
            course_id=l["course_id"],
        )
    )


# =========================================================
# QUIZ
# =========================================================

@app.route(
    "/quiz/<int:course_id>",
    methods=["GET", "POST"],
)
@login_required
def quiz(course_id):

    active = db().execute(
        """
        SELECT 1
        FROM enrollments
        WHERE user_id=?
          AND course_id=?
          AND status='active'
        """,
        (
            g.user["id"],
            course_id,
        ),
    ).fetchone()

    if not active:

        flash(
            "Activate the course to take its quiz."
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id,
            )
        )

    questions = db().execute(
        """
        SELECT *
        FROM quizzes
        WHERE course_id=?
        ORDER BY id
        """,
        (course_id,),
    ).fetchall()

    if request.method == "POST":

        score = 0

        for q in questions:

            if request.form.get(
                f"q{q['id']}"
            ) == q["answer"]:

                score += 1

        if questions:

            db().execute(
                """
                INSERT INTO quiz_attempts
                (user_id, quiz_id, score, attempted_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    g.user["id"],
                    questions[0]["id"],
                    score,
                    datetime.utcnow().isoformat(),
                ),
            )

            db().commit()

        flash(
            f"Quiz submitted: "
            f"{score}/{len(questions)}"
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id,
            )
        )

    return render_template(
        "quiz.html",
        questions=questions,
        course_id=course_id,
    )


# =========================================================
# PAYMENT
# =========================================================

@app.route(
    "/pay/<int:course_id>",
    methods=["GET", "POST"],
)
@login_required
def pay(course_id):

    c = db().execute(
        "SELECT * FROM courses WHERE id=?",
        (course_id,),
    ).fetchone()

    if not c:
        return "Course not found", 404

    if request.method == "POST":

        method = request.form["method"]
        reference = request.form["reference"].strip()

        db().execute(
            """
            INSERT INTO payments
            (user_id, course_id, method, reference,
             status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                g.user["id"],
                course_id,
                method,
                reference,
                "pending",
                datetime.utcnow().isoformat(),
            ),
        )

        db().commit()

        flash(
            "Payment details submitted. "
            "Your course will be activated after verification."
        )

        return redirect(url_for("dashboard"))

    return render_template(
        "payment.html",
        course=c,
    )


# =========================================================
# CERTIFICATE
# =========================================================

@app.route("/certificate/<int:course_id>")
@login_required
def certificate(course_id):

    c = db().execute(
        "SELECT * FROM courses WHERE id=?",
        (course_id,),
    ).fetchone()

    if not c:
        return "Course not found", 404

    total = db().execute(
        """
        SELECT COUNT(*)
        FROM lessons
        WHERE course_id=?
        """,
        (course_id,),
    ).fetchone()[0]

    done = db().execute(
        """
        SELECT COUNT(*)
        FROM lesson_progress p
        JOIN lessons l
            ON l.id=p.lesson_id
        WHERE p.user_id=?
          AND l.course_id=?
          AND p.completed=1
        """,
        (
            g.user["id"],
            course_id,
        ),
    ).fetchone()[0]

    if not total or done < total:

        flash(
            "Complete all lessons "
            "to unlock your certificate."
        )

        return redirect(
            url_for(
                "course",
                course_id=course_id,
            )
        )

    filename = os.path.join(
        CERT_DIR,
        f"certificate_{g.user['id']}_{course_id}.pdf",
    )

    cpdf = canvas.Canvas(
        filename,
        pagesize=A4,
    )

    width, height = A4

    cpdf.setStrokeColorRGB(
        0.04,
        0.14,
        0.30,
    )

    cpdf.rect(
        35,
        35,
        width - 70,
        height - 70,
    )

    cpdf.setFont(
        "Helvetica-Bold",
        25,
    )

    cpdf.drawCentredString(
        width / 2,
        height - 120,
        "EAGLE VISION ONLINE ACADEMY",
    )

    cpdf.setFont(
        "Helvetica",
        13,
    )

    cpdf.drawCentredString(
        width / 2,
        height - 150,
        "Learn. Revise. Achieve.",
    )

    cpdf.setFont(
        "Helvetica-Bold",
        18,
    )

    cpdf.drawCentredString(
        width / 2,
        height - 230,
        "CERTIFICATE OF COMPLETION",
    )

    cpdf.setFont(
        "Helvetica",
        14,
    )

    cpdf.drawCentredString(
        width / 2,
        height - 290,
        "This certificate is proudly presented to",
    )

    cpdf.setFont(
        "Helvetica-Bold",
        22,
    )

    cpdf.drawCentredString(
        width / 2,
        height - 335,
        g.user["full_name"],
    )

    cpdf.setFont(
        "Helvetica",
        14,
    )

    cpdf.drawCentredString(
        width / 2,
        height - 390,
        "for successfully completing",
    )

    cpdf.setFont(
        "Helvetica-Bold",
        18,
    )

    cpdf.drawCentredString(
        width / 2,
        height - 430,
        c["title"],
    )

    cpdf.setFont(
        "Helvetica",
        11,
    )

    cpdf.drawCentredString(
        width / 2,
        height - 500,
        f"Date: {datetime.utcnow().date().isoformat()}",
    )

    cpdf.drawCentredString(
        width / 2,
        height - 525,
        f"Certificate ID: "
        f"EVA-{g.user['id']:04d}-{course_id:04d}",
    )

    cpdf.save()

    return send_file(
        filename,
        as_attachment=True,
        download_name=os.path.basename(filename),
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
@admin_required
def admin():

    pending = db().execute(
        """
        SELECT
            p.*,
            u.full_name,
            u.email,
            c.title
        FROM payments p
        JOIN users u
            ON u.id=p.user_id
        JOIN courses c
            ON c.id=p.course_id
        WHERE p.status='pending'
        ORDER BY p.id DESC
        """
    ).fetchall()

    users = db().execute(
        """
        SELECT
            id,
            full_name,
            email,
            phone,
            role,
            created_at
        FROM users
        ORDER BY id DESC
        """
    ).fetchall()

    courses = db().execute(
        """
        SELECT *
        FROM courses
        ORDER BY id
        """
    ).fetchall()

    return render_template(
        "admin.html",
        pending=pending,
        users=users,
        courses=courses,
    )


# =========================================================
# APPROVE PAYMENT
# =========================================================

@app.route(
    "/admin/payment/<int:payment_id>/approve",
    methods=["POST"],
)
@admin_required
def approve_payment(payment_id):

    payment = db().execute(
        """
        SELECT *
        FROM payments
        WHERE id=?
        """,
        (payment_id,),
    ).fetchone()

    if payment:

        db().execute(
            """
            UPDATE payments
            SET status='approved'
            WHERE id=?
            """,
            (payment_id,),
        )

        db().execute(
            """
            UPDATE enrollments
            SET status='active'
            WHERE user_id=?
              AND course_id=?
            """,
            (
                payment["user_id"],
                payment["course_id"],
            ),
        )

# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
@admin_required
def admin():

    pending = db().execute(
        """
        SELECT
            p.*,
            u.full_name,
            u.email,
            c.title
        FROM payments p
        JOIN users u ON u.id=p.user_id
        JOIN courses c ON c.id=p.course_id
        WHERE p.status='pending'
        ORDER BY p.id DESC
        """
    ).fetchall()

    users = db().execute(
        """
        SELECT id, full_name, email, phone, role, created_at
        FROM users
        ORDER BY id DESC
        """
    ).fetchall()

    courses = db().execute(
        """
        SELECT *
        FROM courses
        ORDER BY id
        """
    ).fetchall()

    lessons = db().execute(
        """
        SELECT
            l.*,
            c.title AS course_title
        FROM lessons l
        JOIN courses c ON c.id=l.course_id
        ORDER BY c.id, l.position
        """
    ).fetchall()

    return render_template(
        "admin.html",
        pending=pending,
        users=users,
        courses=courses,
        lessons=lessons,
    )


# =========================================================
# APPROVE PAYMENT
# =========================================================

@app.route(
    "/admin/payment/<int:payment_id>/approve",
    methods=["POST"],
)
@admin_required
def approve_payment(payment_id):

    payment = db().execute(
        """
        SELECT *
        FROM payments
        WHERE id=?
        """,
        (payment_id,),
    ).fetchone()

    if payment:

        db().execute(
            """
            UPDATE payments
            SET status='approved'
            WHERE id=?
            """,
            (payment_id,),
        )

        db().execute(
            """
            UPDATE enrollments
            SET status='active'
            WHERE user_id=?
              AND course_id=?
            """,
            (
                payment["user_id"],
                payment["course_id"],
            ),
        )

        db().commit()

        flash(
            "Payment approved and course activated."
        )

    return redirect(url_for("admin"))


# =========================================================
# ADD LESSON
# =========================================================

@app.route(
    "/admin/lesson/add",
    methods=["POST"],
)
@admin_required
def add_lesson():

    course_id = request.form.get("course_id")
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    video_url = request.form.get("video_url", "").strip()
    position = request.form.get("position", "1")

    if not course_id or not title or not content:

        flash("Course, lesson title and lesson notes are required.")

        return redirect(url_for("admin"))

    try:
        position = int(position)

    except ValueError:

        position = 1

    db().execute(
        """
        INSERT INTO lessons
        (course_id, title, content, video_url, position)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            course_id,
            title,
            content,
            video_url,
            position,
        ),
    )

    db().commit()

    flash("Lesson added successfully.")

    return redirect(url_for("admin"))


# =========================================================
# EDIT LESSON
# =========================================================

@app.route(
    "/admin/lesson/<int:lesson_id>/edit",
    methods=["POST"],
)
@admin_required
def edit_lesson(lesson_id):

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    video_url = request.form.get("video_url", "").strip()
    position = request.form.get("position", "1")

    if not title or not content:

        flash("Lesson title and notes are required.")

        return redirect(url_for("admin"))

    try:
        position = int(position)

    except ValueError:

        position = 1

    db().execute(
        """
        UPDATE lessons
        SET title=?,
            content=?,
            video_url=?,
            position=?
        WHERE id=?
        """,
        (
            title,
            content,
            video_url,
            position,
            lesson_id,
        ),
    )

    db().commit()

    flash("Lesson updated successfully.")

    return redirect(url_for("admin"))


# =========================================================
# DELETE LESSON
# =========================================================

@app.route(
    "/admin/lesson/<int:lesson_id>/delete",
    methods=["POST"],
)
@admin_required
def delete_lesson(lesson_id):

    db().execute(
        """
        DELETE FROM lesson_progress
        WHERE lesson_id=?
        """,
        (lesson_id,),
    )

    db().execute(
        """
        DELETE FROM lessons
        WHERE id=?
        """,
        (lesson_id,),
    )

    db().commit()

    flash("Lesson deleted successfully.")

    return redirect(url_for("admin"))


# =========================================================
# TOGGLE COURSE
# =========================================================

@app.route(
    "/admin/course/<int:course_id>/toggle",
    methods=["POST"],
)
@admin_required
def toggle_course(course_id):

    db().execute(
        """
        UPDATE courses
        SET active =
            CASE active
                WHEN 1 THEN 0
                ELSE 1
            END
        WHERE id=?
        """,
        (course_id,),
    )

    db().commit()

    return redirect(url_for("admin"))


# =========================================================
# INITIALIZE DATABASE
# =========================================================

with app.app_context():
    init_db()


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":
    app.run(debug=True)
