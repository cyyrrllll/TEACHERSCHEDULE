# Teacher Scheduling System

San Jose-Litex Senior High School. A Flask application that keeps class programs and teacher programs
for the school and builds them automatically, with no clash of teacher, room or section.

The database is **PostgreSQL** (Neon), accessed with **psycopg 3**.

## Files

| File | Purpose |
|---|---|
| `flask_app.py` | The whole application (routes, templates, scheduling, database layer) |
| `requirements.txt` | Python packages |
| `README.md` | This file |

## How it works for the administrator

You only set up two things: **Sections** and **Teachers with their subjects**.

1. **Sections**: add each section with its track and elective (cluster) and room. Every section gets its
   fixed class program at once: the 6 core subjects, its elective Monday to Thursday in the last two
   periods, and Homeroom then Intervention/Remediation on Friday. Building and floor follow the room number.
2. **Teachers**: add teachers (or approve sign-up requests) and choose the subjects each can teach.
3. **Schedule Generator**: press *Assign teachers and build all class programs*. The system gives every
   subject a qualified teacher, adds the rooms and laboratories needed, and places every lesson without
   conflicts.
4. **Validation Center** to check and approve, **Reports and Printing** for PDF, Excel and print.

School Setup, Curriculum, Teacher Loading and Room Management are optional (Advanced) pages.

## Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `DATABASE_URL` | yes | Neon connection string, e.g. `postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require` |
| `SECRET_KEY` | yes on Render | Long random string. Keeps people signed in across restarts and redeploys |
| `DB_POOL_MAX` | no | Connections per worker process (default 5) |
| `PORT`, `HOST` | no | Only for `python flask_app.py` (local run) |

Use Neon's **direct** connection string (the host without `-pooler`). The program takes a database lock
at start-up so that several workers never create the tables or the starting data twice.

## Run locally

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
export SECRET_KEY="any-long-random-text"
python flask_app.py          # http://127.0.0.1:5000
```

## Deploy on Render

1. Push `flask_app.py`, `requirements.txt` and `README.md` to a Git repository.
2. Render: **New > Web Service**, connect the repository.
3. Settings:
   - **Runtime**: Python
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `gunicorn flask_app:app --workers 2 --threads 4 --timeout 300`
   - **Health check path**: `/`
4. **Environment** variables: `DATABASE_URL`, `SECRET_KEY`, `PYTHON_VERSION` (for example `3.12.7`).
5. Put the Render service and the Neon project **in the same region**.
6. Do **not** add `--preload` to the start command.

### First start

The tables are created automatically. On an empty database the program also creates the starting data once:
2 administrator accounts, the curriculum, 22 test sections, 60 test teachers and all class programs. This
makes about 2,750 database calls, so the first start takes longer than later ones (about 160 calls). Wait
for the deploy to finish before opening the site.

## Accounts

| Account | Sign in with | Password |
|---|---|---|
| Administrator | user type Administrator, username `admin` | `admin123` |
| Second administrator | user type Administrator, username `admin2` | `admin123` |
| Test teachers (60) | user type Teacher, their username, Teacher ID (T-number) and password | `teacher123` |

**Change the administrator passwords after the first sign-in.** Before real use, delete the test data:
School Setup > *Delete all teachers and sections*.

New teachers request an account on the sign-up page. The administrator approves it and sets the grade
level (Grade 11, Grade 12 or MID) on the Requests page.

## Notes

- Logos and problem-report photos are stored in the database, so nothing is lost when Render redeploys.
- Grade 11 sections use the AM shift and Grade 12 sections the PM shift automatically.
- The generated class programs are checked for teacher, room and section clashes; see the Validation Center.

## Manual testing checklist after deploying

- Sign in as Administrator and as a Teacher.
- Add a section and a teacher; press *Assign teachers and build all class programs*.
- Open a class program and a teacher's program; print or download a PDF and an Excel file.
- Request an account from the sign-up page and approve it as the administrator.
- Send a problem report with a photo and check that the administrator sees it.
- Upload a logo, redeploy, and check that it is still there.
