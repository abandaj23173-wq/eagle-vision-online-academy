gunicorn# Eagle Vision Online Academy — Functional MVP

This is a real, runnable Flask + SQLite academy starter.

## Included
- Student registration and secure password hashing
- Student login/logout
- Student dashboard
- Course catalogue
- Enrolment workflow
- Manual payment submission and admin approval
- Lesson progress tracking
- Quizzes and scores
- Completion certificate PDF generation
- Admin dashboard
- Responsive mobile-friendly UI

## Run locally

1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run:
   `python -m venv .venv`
4. Activate it:
   Windows: `.venv\Scripts\activate`
   macOS/Linux: `source .venv/bin/activate`
5. Install:
   `pip install -r requirements.txt`
6. Start:
   `python app.py`
7. Open:
   `http://127.0.0.1:5000`

The database is created automatically.

## Admin
Default account:
- Email: admin@eaglevisionacademy.co.zw
- Password: ChangeMe123!

Change the password before any public deployment.

## Important before launch
- Set a strong SECRET_KEY environment variable.
- Use HTTPS.
- Add a real production database/managed SQLite or PostgreSQL.
- Configure automated payment processing after selecting a payment provider.
- Add real teacher video URLs and properly licensed notes/past papers.
- Add privacy/terms/parent consent pages.
- Configure backups and monitoring.
