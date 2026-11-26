"""
TEACHER SCHEDULING SYSTEM - San Jose Litex Senior High School

Database:       PostgreSQL (Neon). Set the DATABASE_URL environment variable, for example
                postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require
                The tables are created automatically the first time the program starts.
Local run:      pip install -r requirements.txt
                set DATABASE_URL (and optionally SECRET_KEY), then  python flask_app.py
                -> open http://127.0.0.1:5000
Render:         Start command  gunicorn flask_app:app --workers 2 --threads 4 --timeout 300
                Environment    DATABASE_URL, SECRET_KEY, PYTHON_VERSION

Default accounts (change the passwords after the first sign-in):
  Administrator   admin / (no ID needed)       password  admin123
  Teachers        sign in as Teacher with username, Teacher ID (T-number) and password;
                  the 60 test teachers use password  teacher123  (see the Teachers page)

Two documents, modeled on the school's printed sheets:
  CLASS PROGRAM     one per section (room, adviser, Monday to Friday timetable,
                    legend, signatories). Teachers see the grade levels they handle.
  TEACHER'S PROGRAM one per teacher (loads, official time, timetable, daily teaching,
                    intervention and ancillary minutes). Only that teacher and the
                    administrator can open it.
  PROBLEM REPORTS   Anyone can report a problem (message + optional photo) from the sign-in
                    page or from Profile & Settings. The administrator is notified with a badge
                    in the menu, a banner, a pop-up and an inbox page (Reports).
  NOTIFICATIONS     A bell icon shows the unread count. Teachers are told when the administrator
                    updates their program or assigns them to a class period or section; the
                    administrator sees problem reports there. Both can delete what is finished.

ADMIN MAIN NAVIGATION (follows the order of the work)
  01 Dashboard             progress of every step, alerts, progress by section
  02 School Setup          school year, term, document details, logo, timetable, shifts, rules
  03 Subject Management: the fixed Strengthened Curriculum plus added subjects: 5 core subjects, Academic (5 clusters)
                           and TechPro (10 clusters); choose what is offered and set minutes/rooms
  04 Section Management    grade level, section, track, cluster, shift, room, adviser
  05 Teacher Management    accounts, profiles, specialization (curriculum choices), official time
  06 Teacher Loading       who teaches each subject of a section; qualifications
  07 Room Management       classrooms and laboratories / workshops
  08 Schedule Generator    automatic draft, manual adjustment, class programs
  09 Validation Center     conflicts, loading checks, time allocation
  10 Reports and Printing  print class and teacher programs, Excel/PDF downloads
  11 User Management       accounts, roles and permissions, requests and problem reports, audit trail
"""
import base64
import json
import uuid
import os
import re
import secrets
import threading
import time
from functools import wraps

from flask import (Flask, abort, flash, g, make_response, redirect,
                   render_template, request, session, url_for)
import psycopg
from psycopg import IntegrityError
from psycopg_pool import ConnectionPool
from jinja2 import DictLoader
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

APP_NAME = "TEACHER SCHEDULING SYSTEM"
BASE = os.path.dirname(os.path.abspath(__file__))

# PostgreSQL (Neon). The connection string comes from the DATABASE_URL environment variable.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):  # some hosts still hand out the old scheme
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Set it to your Neon connection string, for example "
                       "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require")
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "5"))
ADMIN_INITIAL_PASSWORD = os.environ.get("ADMIN_PASSWORD") or "admin123"   # set ADMIN_PASSWORD on Render; applies only to admin accounts created at start-up


def load_secret():
    """Use SECRET_KEY if set, otherwise create and keep a random key file."""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    path = os.path.join(BASE, "secret.key")
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        key = secrets.token_hex(32)
        try:
            with open(path, "w") as fh:
                fh.write(key)
        except OSError:
            pass
        return key


app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # Render sits behind a proxy
app.secret_key = load_secret()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),  # Render serves the site over HTTPS
                  PERMANENT_SESSION_LIFETIME=8 * 3600,
                  MAX_CONTENT_LENGTH=20 * 1024 * 1024)
MAX_LOGO = 2 * 1024 * 1024
# San Jose-Litex Senior High School seal, used until the administrator uploads another logo.
DEFAULT_LOGO = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAASwAAAEsCAMAAABOo35HAAABgFBMVEUcJ5edXhtiYmkXEiDbnGnn1aaWn9Ld4OtfZaLh5/Tj"
    "5OIcI11ea8g2SqOPkJScp9ixklmprOhZIxi6xN14g7OkrNcmPMZ2hshpa6ugaUlvUCabIxvacFXUtoeurrB1dfUHCXTR2fJ4"
    "eHkAAP9farAYGK+y2Os7RWC7x+jIXCEmRdJBPIt5iMoXY7GBfK3AvdYTdnludanOMy1rpuS4xef//6uIjbWFjrlvoKwA//+s"
    "hzlBPXI5RCpidsh5hLB4hrb//wD//3js0ndYY3Z//39x9PQZaOV6gX0AFT+6xrt/fwD/AP//qqp/P39/P794jOC5w1zfOUbC"
    "vOD9/fwAAAAuScwCAgMMBZIRB6cEAnAwRrTn6O/9/v05UcwnOq0DA1bU2OlKV660ttEXFm4uN5Bxdq/Gx9KUVgqHh7DV1tdU"
    "VpEoJ3JISI0TFhS0trcmJienqMs1NnOpWAhWZa+SmMiUlramp61DVMyWmJj2+vjIyuRnaapGRkj8+NZmZpY1NjYuMem8AAAA"
    "gHRSTlP+///////tG/VZ/f/5/v6m/wz//Pdg/vMG//////8GAgKUAgGwAxb/Yv/+/6cD//8GX/8HoQNhoA8B////ulylAQL/"
    "RAICA/8E/wIBAwQETP//Kv8A/v/////9/wb+/f///f7//vz///7//v/+/////v///Pz+//7/K/79/////6lqPy4AAE0SSURB"
    "VHja5b0HY+JYti4qC1uI7Jwq5+qu6tw9PTmcN3PCvfdF5MIKoIBEkWxDEWzA4a+/vdaWQBISCBvXnJqrma5yOWD0aYVvxc0I"
    "n+f6q6AkngqCEk/s/PBrq9viusavO4kNhXxpg/ypCPHB3NdQlHgcXuJ5IrFDrkQiDj//fSL+me5BYD7XL3r9lNzmTm57b6Tz"
    "JUkqlSS9Y/HcToLc76uN54IyFyzlsRBXEj/k9l6O0mk9Ta4RnyNwxeOK8i8FlvKTIOzkrI4ulaSj9Pl5mvx3JAFg27lnANOT"
    "F3PFShASz15auq7zEgH76OiI/Lhu5X5DvoBgPVf+BcD6qyDskxvNWbp0fnR0XnSuoyLB60jS09yvIF5PnrwIv1vlOfkvt53W"
    "AaQj+uPn58UjicDNEbQ3lH8RyVIePyE3OtIlKX0OEI2xIh8S8EBAOjz3M7E8T5RQoRIGuW09A1AVCUb4Ivgn+QR/3SVgx9Gg"
    "feFgKQIxwBvptCQ5IAVcUlFKp3eIjY8HwLVBHMPg7TYB+2j8ww7eeElShyNA/QuABXY5YUl60b7Ho5CrJJ2PdghUG37HQKzd"
    "YGdbN4mxm75sfZQ6VgIkS/niJWuQG2XOi87NHYVeu6XOy7cDYX8C1/8UNvZRAcF/Bv6Mrc/nkrSXS8T/ofwv5UsGa+P5INkB"
    "FTyKcBGrxg0owujdgHslcryOvi/0QnFNZ+q5eydc9wyW8krIdWyoouBVKlk5cI0vngpAYZXEy84cqOwLVDGnPE7cqyreM1gb"
    "yluL2uViROEyibV+m4gDW0/kOF0P0b8AuKTzHAkQhMdfKljEtu+ZLmWJoIhEusxO90+53PvtPX23ZH82GmL6z8q92vh7BUt5"
    "PNjLSMWjRa8SIxUz5xIjLfZjRdPamfKmXwxY+0JOl6IZqzDbvcA3k6eS4R8Lv1W+SLD2hZ26dPQ5L0naju/Hv0SwHgtx/vNi"
    "BWhxA+IclC8NLOU/lVzmc4NVLOk5ZRJQfjFgPRF2Rp8ZK7BwJX1HGdyTU7w3sP7+QuHMRRSoVGLoZTKTq1QqLQp4aTuOCdUv"
    "SbKeA3WfgU2GkqddAkeJMSEv1bH29rarXa7VanEtbptce3tpIPD4Lb7oMIx5fX10lOEUgRD5xJcDlqJsdGYLloSSI+m81etu"
    "aVo+7NKGWwQ6vpORUNIiyChw0yfK4y8GLKIDXDjtlqTSLiThra6hyfmIV3KL2+vUMyBjc9AyOwnlyZejhsqTQU4PiWYIP2cy"
    "eprjtPziV1Ljtjtg3maES0TFe4N7sfD3A9ZrEhOCwkjTImWaGYvbSuZvf8kaEbEMU9oNV8R6DpIWXwZYG4Ly0pQC8i+mpHeH"
    "dwFqYsmMNF+iFmxM5sZ/E3excR9BInM/WOX00pT2laT0rVQvVCWNPZ2odLBsbf+PL0KyHgNWbtZAkTI73WUiZWvk1rZeAn30"
    "OxMpk1MeOwXF/65gKRvPIWneMSHjJ42T6yWd25p/60a32jXkhfFKZ8xpnS+lE8tXxLuBBc9OUb5XnpPr6dMXL8CqDnJpTyKY"
    "qJ/FRbBTrXZKJFejt7g+ch1zioCV0nFhX1GWmmZm7iBE+4Lw6j8dDqr88osS/x+Jnffpc5dOEHKe2Yukfi1VLBSOj49FsXUL"
    "fRxuZ9z8CzWfSwi/TSjK3//ZYBF+/sSRrEF8YyO3lSMkey/Npy1p113cyvCtaHolN0TmGK8C44Arh/2o3B9Oi1dXH0sXDaQk"
    "Dkofwv7G498pruszg6Vs/DuUXgYbb5O5ly+76REJ4CDUI3bKrQ3EqFtbUUWjpRaOC3AR2UJFNK6bplmvVig63m+uxMrNasUP"
    "pdzqMF4fvJfbGQA4T8n16tWrb+D/T356Elc+H1j78Edi59cu39F1iHMpbZ4ysZkIUI1vuCoSrJgSQ9ASr8m/R6pI1LIgpqpA"
    "qlLX2b5LmTnyJVENMG6c7ub2pdJ5h8vtJKZC6qf78SfK5wCLuBjlbY7nJ9I0TiV9/bX7jabnmSrZ4FjW+cdIJCLVlE2RgEU+"
    "aZG/jxnyX0HliJQR5MRytVe3DPzmtgjGzQh6TU43Ubp27Z4A6ALrvORfvvzT+xy9dn5Lwdt/ft9gEQlWdjhLz1AjXgyvlW7N"
    "CVmIMKmi+gfnExZIVnlYjxFY2rImUlsPStmW8xb8i8gS+RpIXf66QT4ywx6B7lFG4mNKGfJ2oT0pQy5d73AvXz5DVXxyn2Bt"
    "PB0kElyHl9wNLQFQmZ2tmRJVbZZT3+WvCT7XEzUEpWO6/b4x1OBfBJ13JvxZruRZBIsi1s3n+9ccN2qzoa/fzfjiRmlixsiV"
    "PkrrutWFnsNvNu4NLPIgXv9lm4Ri5zNC/iPJ1I2ZUsXGCEsgulYnYH07ttlg4I8LJnVzdYRO64oATyvfKNi2n/yzSb6qigxv"
    "1WYQrz0ztOZIHvLXaaD4ne1cHErmQnQPyUTnnxDG8PUMPyeZ9KY3h4FWUohBtU7A4cafbYoMAFJujcFi5B61TckyQFfm8Rve"
    "EZZRAJ2cSUm2vI7RnaS3i/1HUknndwbCY+V+JEvJjTL8eWjlc5caq0poNHNdb9bBuVVVwKBM7Lc48WjDMgoPAZH8g4ePmTwF"
    "q2KI6CNlEzB7l2/BZws6NX2hkHFSWM4rk3GaI3idEFchoURtJ4kIFnSKJbpNKZ0mWGVCxYpp+jVwy7kbgwUuIBKPl5ebNqcq"
    "qC62bpSRwhfEbSJmCFYXBOy4rFHMWlTAmmDriJMkMFfq5XLK5ELwSm6DXwxI144/VUwTA/ZMid7tHFWyfoontjMZ2jqUCTXs"
    "2z4NJN6Npx9lVZHaHJV8olK20fK4/zFarTzI0LFIf4TR0BmK2hYK2Lf5NvxwqpLvqWjZxEaYiTTqjDSrp6QIHtLKKctVQ2hv"
    "TViZYnFW84HE1H3vunINgTHiN0QaQLEwkIIeo6fzhC1DYFlglkDhjm3hK5gaC58ty8TcE7CMikgFzECXAC9YDkNLrprz2uDO"
    "JajKPl4uWIluRi/OahsqMZZbrOD9syrwpCrQdB4JehlFpE7u4p2IYDFe4jpsiChSPRNwKJN4hymrbQ0NejM/AsxEopTwLRxx"
    "kYgnANgOtVyEdIVK1te0W5oHtF4vEyzlVx462KfFyfmzlHEnCyr1WJbEe3BbBabN5+U2wDbaKqM4aVQRya1OiGWy3jbb7WoT"
    "BfAaYupCXdbIVakZZUDHyiPrauTriCex+ihUJjoF8mhkPtCzyNcEra+l0AI2URapAw2WvywHLAVahzrS+QweKpkdl4zIfBkc"
    "P9ABVBNRo8JRJwwJQLPI92yjwpXHNyinCLKqhdS90Gbgi9f5erter/cgbDxWs/kUfKmuIeky5SbIqmhpDJVe4mJT14EBFpeZ"
    "XWskmmj9rESaOogiWRtKYpQ5DwELDKhkbrsfZhsgAUNu2Eb9WkajXNaovXkHXlJEAz+m4TLIDYHThM+XKRAyZAPV9ghlqDLE"
    "4KeKrykCqvDzSfufQL4Kamo7sLZRn1EIIlhldImPR6rJMvPlavB8YNT182IYbZdKGc7z7iCOEdtVWWZtsFKyhShVDcIrGXB3"
    "No4FtTohpRBJ53WMEcsAVlVGWdJ1tG5yD1+iBSE20TsLVbwOxpB8tZr/lvwcI6qcEaCMchpUcQZc5zw3iJKEjgBWAppoz2eo"
    "YH1rOpFncW+acpuacaIlyCuJQgI+YnuYp8wSqKlzcxD8iI0uZhpMyNQUOI2yTwZ+8g2E2sTebbXRcsFf4BplfN3yUAO7dkx+"
    "TFWDXGPXNGc230h7z5Qny1BDsO6zGvhKnanwptXkRmVRpV4eFIqoJqUOxCRfG7JRy/cKlDyMFRETWiJlWhbacgaErVDQkYte"
    "55HJNgxkF50sPgbT5viAJI2zCY6BhmsLDFe4Mp5DDfunJYC1ARTrPLxTaC/gvWVTInr0porOnYiPRW19u6pp1TZRPgvEpeBS"
    "xIpoZ5UhwLkWGfp1ImxpVL9uHolsvUrjSh4Fq5pHORN7Wpk+FfzGsYC7SZym2yn6QJJKPOIz5fslgLUv/FkPb/Ewu26QesYk"
    "hwA4VHq6SOWikqImXq4Tng4xS8GWI2QSth5StNQm+XkCFAOCom7vUaqv4UtaddRCDpEr14b4Cg0ZwC2I5qihuijX9cQgAnSW"
    "OUM9zjNVRXmxDOpg8WHUvWS6TXtypDbs91pVC5QZVERbtDDcE7tEBhgAjbAlcaSjK2vaz74p0kxym6DXKtsaXAf1A0T7EH0X"
    "LLT5JqQKwbzXqZZXaK6wlZd7E4vVJZ6Udz9Jy5xB5SV9h+bL7wTWhvBslJ7mo/iUzKbbtBumSIjn2MaDnkDyCXn3NWWoYjtv"
    "ezMWtEgro8W37J/pse12u15FvDUL/tHskVeC7Fcbw+fjwgjhHfGIqpFMgVETh3XErumNtcrI+yseM7+7SwhqkIBljs45ZW62"
    "Zi5YT4TA5iHESncbU0NFc2InXfqoNWIf/SAkjGl4IlboTXTbhV3yrUQAyfNPjT2E7K5+2f8wulYzxebbIKumib+ji5ktM7+N"
    "uZ460hBvUE54GziMgtc3dkmo+HVgU3CmeLQXF+J3BIv4wu0QXWe8bhAcHoXF4U3koRO1pFnPEYaH5M6GSLk5YplVIjb1Bl8d"
    "zq8sanK+2myoaqMMctnYQpdYpfkHsVsHdwAhp5vrYYRAXMD1t242HxJYg+LoO8o3yl3BSnSDSVap47tJjUbBpuxK5hGQDDQz"
    "okaNsYhEqtxtiGLsdEYdNSjMq7T4NugkL6N910dIRNtdseCJnODaRm9BAOypat31O4zw2EfPCa+e3A2sDWHDkoJ7Eafus4tk"
    "xzFblmPa0c2Rz1pQc0buqNaHbL26lV/8kg2ik1lksJiUJ2BZPD6jkSfZgM+NuEn4QGy7dHErNGmT5pVXd5MsmBfUp0eVdokO"
    "BsgEjT3sZgWZVvdYcIigLa1e2c5iie1aXs7f+qrI+WHK5hnHJFagCuchVQ0apmuYri+IKdmNVohVkdKJeUZrHljfCJw+VSDc"
    "PTL5oLulGQEnS9XHx0/MeJ0GvamqiZXk1PUdkHIAa9uUPdU1EQ/LLX4sNe4tajjR6UxiRsMM6eBNzyUP88HKTYMVpIO2+KPu"
    "NfPjghbowlClCffrpGU22GptCU1sebnKQNG1bPQQj5Tb14AtI784TT6woy3CiVPDSc4mGCz9B6JHd1XDaTpa0sNkw1Kd/FLe"
    "yfCR93qN7/5YPV1q15+RtXoyCrPzC+0wAntMyCPjqMchj26rQYLS78a2NahMRqLpuamH+WD9aZoz6OF61ER+KFZsn4QOsAJ1"
    "GYaYqsrS+yRJTONSfGqUVCdGp0EARNasyhyLKWPCt4JaWaS9wZxk/Hw1/JOft5cyM1o+amX0Q5Q/2Da+me+qhCPx8vKxyrfA"
    "eLkFC4w7ph8KNENPaGmFhaIao04K/j1m9+tpsIiFf3JXySq6wdolWM30+Zxoxzd23oWyemO7p+Xv5ZK7JHp2/ZuyChFTZ9Qi"
    "aA210aqLoqnNjhOlzlvhm7uA9eKJ8NJv3Oe0MV7Tdwvf1aOVQDF2T0A5Kf++l40CF+7RJC2hpRqkIMutuscH5DtMAHf4eY47"
    "ZOZx0kRampGTCXrvmB+FzAsJd9FulBdWwORtBwswJD0WM9jvhv1K0PIF2lj1vodkvTQN1vu7geXMlUzkant+h7b9hpvolUS1"
    "OVz4ntfWbodVLVWgD0or21lHfHTwkT/brBEqL/l6518qd5asksu8lzoRhKRHVYH2ebT7t7jp9duBhakGzD+0nQ/eqPheUtMP"
    "jATVvmxNqTtnPmohsEolPpL1qVNehSTrVi7wlmDZoUKV1sKhQtak2gisQfZ37PYYL1hFk4svD6yjkmlEm0JqoDYUwns25oG1"
    "eivBaou00I95WjDudYxGCwSr4ahRbvvMrcV4ihjF0vYywZpj3PnexGyhWLG39YIr67dTQxDpdv47EcsZDflapcVJg/pl0ZOU"
    "J88043WJpb07g7Unjee6rJlvdeQajiBhD+3KvtV1dUuwIPevarJt5YeW6NBSHskfA7mJK3+BbMLl7wrWYyHBl+wKUknSZgce"
    "JPprTUr4777Lf36w8v2+bTGhdo06SN5TXWWoERWtKSPv2d61cSewngi/cSYHpRI3J0g7LjTG0V8lOre6upoGa+Xq1kj3EBnR"
    "AsN1jFiZ4wpsoVz3mS0PWPpPwos7gLUv/ECLhrsSszdbB8GeD28lR2t+ZNY+3gEs+RoKvE1ajDtWs5pJ2+hEaApw4rAxN3UN"
    "sEnS+f5dwPqHouSk2Sksx1Ych1XO51/Z9flgJRfIghFrbqZpE6HY3SpjfEpLJtAM4bWkhrnrmrrbEX53e7CeCxv27p2pVIO3"
    "UVhjRbFx6whwff3KD5aPaNXWFwmAjEaTsWemDHXcrtOya/zemZ/tiUcsnW8pz28PVnywY6cV/ayh2m403D2k8pvbY5VPHq56"
    "0Fpb+egFK8kuxlJrDVpKrA7tpBbx01WR9qCKUKbus86jlvUxWtI5N7vhgZltsRJ7NOdQGvkIjQq0RR1NpCt5l8zCo0OP3Xr0"
    "0QvW1cFi3vEKu1NhvIyWWsUyRx2Q3WcvW6lYdaKIEx6fm914xMzuY+Oc1hMvFNjuiHWaJSU/1w8fuf61+vHjI49zPFzY3mtt"
    "GIqyY3oi9PiOATZopMOE4TBAEflfbqWGz6GTVMh1SnaI6dVB6ouxM627FLCSh4cuWVr/+NEV71ytH94iVNRMXoZucBz3gR5E"
    "1MtUBcTKzt86v3u8VqGUTswc3GRm6ODA2TjgK1DQbiiRJm5FfiloPXKbqfWPn9ZdWG3eiqJaTbPNlQEWbqtBI3soWBptZ3ph"
    "EpyZY7DeJoT/tShYz4V4QohzHbvC5kuOQvVJrI9EWjy51vpLAIvw0IkH/P3HCYUncvXxNjkIraGKKgecC8Ic6hvrlITZFsSY"
    "iqglKZeYNZrCBNqqXwhYby1C2HZxcag1lTiGwKHVwIeVb6rWEtBa+/jJQevq9x/HROtq/eMtYx9oF2lrTcpN7fohecsFbBsv"
    "lN25Iy1jh3REtGZVw5ig0XriEuLvO/YrEMEaTqWrjkH9hszxcUrrqQVfB8vtrtVPDru6Wvn0aSVpY7XifLhwTA2PdCRb9goE"
    "onYoVrbx8D7fPcZOFjDdhPDTRtimESagxyjxfyo7vD3YS8AqbU+3NECAWh8RPtwfitNBxO1s/IqDVnICFrFeH2+ZYqZTHaYT"
    "GJYNoyHa5TGx4Hu+aOPxhjOwCVuJKlmKEh+AZZcmi9r9DKpC00TEZonXOBlx7KfFt1ZERGsNwIIPrh4drtw+AdFS7ekeeK9m"
    "y6L/JAbMhKq5N+zpmnamJpPZxmMLlEhgvRaEZ3vu/SgBGT9etWe2CFm5VtERt5dBtlaolV9bWUF5ulolWN1WsDBgLYx7erfb"
    "DoEvV2lLvWc6Sh7nVqTM3jNFCd6WzngUUFE2CGFwb8qWShmfyYD+syoNIoijMfJ97H9M1ZahiB9XQKSIiH0CVgqi9nH1Di/I"
    "q7SJSzSb2O6Es3dDEmi7u6Rt+jCeHpNK+l5Cefp8rmSRmDve9a6+Mr1ZLINNtevdfB9jeVBFK284HQV3V8TDla9WVq5WKUgE"
    "q68+3SFXQ/MP5LEyDGOPL4JYyXTyrFD2ZlGw6mrTSqmeC1wnxbgnewdxmDzxlDxKdc9rbqs4u9vOJ5sULfLUOvA22GUwU+L7"
    "iGitr34k6ri6dvjRzb1ud2nWH5ojZmzYWS3fdeZlfR7cMD1pwL0BCWGUULDi5FKepX3NS970aJdaARh0Jopvc/iCU61fgmiB"
    "aSdKSC7wjZ9ub93d/ijlTML08lqdZmyY6YRSpyS5tz/sEeF6FQ8GS0FHmOv4uuJKetIb59ApLwyft5rOtoWC2FxS38IqESai"
    "feQieH11W4o1xbioKGn5Kp1FIBZ/uvBkmJMFTcDEcTJ/36ONzBgrwhi4qbkTbwRtUSsJ4SBXtSzLFO2dV4tbrKu1bHZtbe3q"
    "ypuBvyI2fsWWrE9frWR9P5SEn1ocQFNkIN1QYUWbywfWfju+7gdplEsInlOmGGdXWFxIbKO5KoYKFvadl9tqQ2u9g6YesSzi"
    "pd7Cul+tPSIGCqzSyjq5HhHg1pLJ5NUahYpcRBvRul9dwddW19cPVlYOD9ZvgVXeiKnXGuy+oRqovgusFbTMqQZH2MA1mAIr"
    "nlASY9MuhXAsbLswk62MObZW5dHIZKu37FJLrq1/PFwhcSBiBh+srIyxAuFaXSM44lfIlw4Jqmu39I3ZXr5iU3nyuEPqmUm9"
    "NL05MEkol/I7m6MyzvYiIldT00w+8m6UQfUbbXG8F+zY0yF2G4tuy9dXABJiQjXQkS7ytY94raw/upP94u38MhKtkKtrBkxG"
    "5IjO/cMjWT8RHZw6mUM68lW/NDoyL4594PExc+cYGvURHB+ghKDZNmsFDDzK2sf1WymfxyPGxDHRCucZU+MX0nmJ3yOSNXBJ"
    "1mNB4aZGA2D4ecv7an8Qnc1MQEdpg0pjCZ2ixCLZfGHFtmOoejZsq2tXd/8VvOp4RG84UnEPVW+XpncZSHw3LjyjvUgAlvJY"
    "wTGKon8PcicoNKXMvdzsWuMtDXdno2DXQdkOVtfG1ypKHJiuJRAIuQ0eseunrI2UWJ4s+9wydwM6vpt8XKHZZga7P15DL2TR"
    "D5Y5Va/nUna7dK9HfsVQvENl1WfogYNOKdvV2ioVs9W1O/8SQ1Wb2lQwREnXWDUxUzM9TcApicTfFQTrydMBl0kfzTPvGELL"
    "1XflRr0n55uiaOoFd97/DiYLpGrlUaC2XQGQXxERIyJ3N2381m+tejQVCHri9LC0mOAB6j8PsL+GAUK6VZfOz6dmTnyj4sZ1"
    "802zqtGpt554vIuZbfXWiSzCMImmHRDjBF4vXNWIiqKPJJJH6FjyagkGDG+hQguJxwXXrKIMmfQpRUyX9B0BrBYDPbbbUtC6"
    "Nclj3r+lkUK5ScQKp3opwWsvat+vAKS11VWbPyFSBxM1q/QvWFYmZJu/OK1NpMsmEGD811dXwbDdHrNktd3LOw3ztPc1pbnz"
    "y1ODm2neSgwUAGtf+FXXA4cvgxJp0CtzXeupNmlRI/VB2hb70SrFCDweggR/rqxOkDplb04+fPhwUsufkr8+nF1ma2OzRhym"
    "jRaQCfLHwQHA9oi+dHToZKshwgDpEN2Tahnw9zgPsBVwSAacnshzwisC1r6wwetBs/WefAN9aSdsVtuMSOOdSMmGpE0tbZyA"
    "SiFdJ3frus1k9uwDvc5ssOBiDZfargKf/2RT108OwwCOETlFCIl46HTLj+gQlFwtj5fuApSdwNnNtGQliAoyr4QdXQpYjOWt"
    "2FsTJurkO5rNNh+tHysJjAk1Du/v97ZEJN3iIPdiDj4esAhcFb+le0RM3aodGpFXBfBWI/tEnIISr+UGrEwQuYbqHUbvMiFj"
    "rpwiKIww4Pig/UUlT6X5HYxe8ZBlYJwiZT0yZwDJsjUGYuVplZEr2dQEHR9YH07YvhZk91GzQbVXI0sWTl5BtSJl0flqDcf5"
    "XWRxKxM4bn4upRMvNhhhx+KDNq55tBB7tc28bNSdEOv4OHr5i4C1GmpU5MoFmzr58CEcLLRe26fhSf61T1Ez9YazWqOFUwUi"
    "j3Pd7qkyeTqaPspkiucwb/6cCSLvuENT80WFsEgmmdeqJi3bw8qYu4FVA8+3eeIFKhgsFLAzNpv9ribfBawW7k+oOyt2yR1A"
    "34ZntDNAD4uZYvEcmuSZ+PvzoLN4S2mXxNNVYLiiaAt6a8t063E3Mlif8GaSsizXKqen/SzLXr65iX0IuYLBciC7uWTZ/7g4"
    "Pa1UajLdk7EWWQ1bIrZ6a3U62qdj0PjO49G3aL5UmlqkaO0oTDwdeG4x40XColU3cITVGuHx4FNEbgGwiGT1Y7HYScD9X/Z6"
    "2Wy2l4oElg+5E3YhsDRMx9NnbZv1io9VB+khGi0S9DCJtBS0dK009PWkiI4nFMv1Pg70LgrWRfAd3/QqREi2kuwssM7exFi8"
    "3px88EjkjbwIWHTHhHMjwUZ3LxCso7T+coPZ6QT6wnFHlm0khg1n0ShQuQautxpGt1nrIWDx/WxNq1QuLi6yN2FgbW5uAlhv"
    "3rBvyH+xGHwmdkuwjHFJv6DW4eierlW3uh47GHDQYBEPquY3mN90gtY9jdN+WipVrwIq8nZ5spi1sFgIvYJDAF6w8HadlpNa"
    "7b9uwmxW7MGDh5sfiAbHyB+xmPohtnmw6ZUsEoUvltcC8zsa9uoNFYsInnksbXqTQRH1cC8RAtaYOKCzJRFObysvt+plmnyn"
    "4tVaEKyeV6hi2expPqlVTvsVOcuefQgH6//98cHmh5OTWCqmqmostr4GWJ24wVqgIeIaI49ymW+WbbdO+FaqMqPKY1v4o/RO"
    "MFgT+l51yvSiyRs1wzIZO+ZRF2iPJEFKMp/PerHachPM2AxvuPnwx68ebBLJImgR6VpfW3e5iZs8tFh+WiDfVen1OHO8X96O"
    "d93J8Z4ZuFj4KP0b5gc9wBtK421PdYgKjh3A6pZlNRkU3foC6YZVBKvvAes0L9dqyWRePj1dW1s/nEUdNn98+CNo4glg9f+s"
    "rRweeA38YmBBOZU+78I43vUseTYC1praYO10AsAasyw5pY53/NPFEg3TzIyu+YXK9RQsDwAnY0Iu508Pf79+MItnbf5ILmq3"
    "Vv9tdXPTBe0lStZCLRGGKI5BIlyogdt5u/PIAwHrByaxVwoAixvHt2xDdHTbxqxQaC6YSl7Fu9nygZVMomRt9c4+HK6ursRC"
    "Y8OTD5tf/Qh2K/bH1bWHDw42XUrLjl8+8kXpAy76bDS5oWwwvtm6gDUGR1Sy4GDs4lSS3o3GFvEa1Bg6e8dxh+HCYFXcjDRW"
    "m5SLyT8P11cPTsIki1CrzQcPHvy4uflvBKsHm25vsDhYWooCVW5bffKstGqbNjLPjHgQrB1G4c4jLJsZVtHN2qqOHGWBi+pJ"
    "LeYFC4KVZH4rhjTicH2dDQQrRlgWoEXg+nGVYnX5wQsW9R+RDTzdnFhN0g4bVcXBare72go+/iKdgEB6ipUy6aD0gNHjnSC6"
    "oC40WUh9ux8saq+IPPUqKUDrJhCsw4crm6iJgNUqYOXO5thg/X6BJHOtTLhCk9wOz2p5TR2Pu7pkTwrYlXteIjxL2ElLcwLD"
    "8Yvk5Uq3Xi4sRrIoWIQ1Jm98NovIVZ9glc1WshPi5Adr8yGi9eHDCsjVw83LS4/tz+K8wSJtXJAUKDA8I6pwE3XacOYtFesB"
    "mYe0xMcZReGnwJICM+st1bwmWq4x4gIZB7tHDcCS37jBQi0ANtEnoc6sfNbmVw8Jb/hwSO2VP15aHCx7BZk9MW2hj/eN4FrM"
    "VLhDKDwXZ36rTJ8kHjw5/i0uD2pgS6ZqLAYWBm9umTg5JSHhGjFTJ/2tbGxWimb94VcPD2Kba//21Y8PYpvkez3ffUHTZYuV"
    "W51iQlOG2qva8G/d91t4oAtw1gUjKM+8YElHu3qgvWwWJhH7YkV7+9mzHgZPrnWgVyfsyax81jpBaeWA8PaVBw9iNzXiEGIx"
    "D7cFuV2spblut//BEgOZ3YZQR9Yqre41mwy28AhW57cCo8SdocIJWJ1Ai9UY86xFe2eufh8EFlGt36+ujA35YRhYq6tEDW+I"
    "gd+E/vGqB6yTCnaAL1bdl5t0iTND+KKcHBrV63qzASMQaiXYwsOxMBKXEJh4wi9a0/MntKgXc6YMj4P24MwLDq+mJYsY7XWb"
    "up8QAdoMBOtkfX2VJaq3SewVMVDfxrxg1abnXiNcXcIcG/qIxG7tBrYvFjzHAPk5PKTdiRY+YaA/sivNaCQdP4/+dbtsn9C4"
    "6H6LRwE5GrwOVila7BoJEENI6SELYgi0PZtnP3jBiskw97pos3yL0xm4RIdq0z30E7fVmdJD2HG3z8Chpb5llP62LJcq9vhm"
    "o2kFGaxTNjSyrl3Q8RJf+hPvml3HHMLN+traODw8k/OVwKTqNvvBa94x6bD+aSaBr0zvsGyo9kbA8b5+e6HIdYg7PKKrJpmg"
    "7WszrXcIJrWTy6CzNmp9INwxzAtUgjLwbGwsP2PdyvbZQLCmSxzASQ9WDj9cstmQUtnp2fTsaJOGIseTHA3dEzheoTgd8Oic"
    "8hjAUp4onGesQr9V89glVENrbpxOL9hLik8MiVYgWKHFiEjfzGI3OFq72CXbnzrUtsJ+OJGD06XHjruybZZZzfYrYWBJHTjD"
    "m8GFMztuE1/q3Ko5haXVUJa96F9ArevGnfzECXH5ZtZ9Q42Lz170T6HKBdcW+ShLXom9iYUChzRrZewaTm5Ytn8KNTLIlp1m"
    "4VldTr9Vu68Fc6aNulU1egV6qtI4Dz+9wxQO5mFoF7zbapXStwJraxYShzghfhksQ+QOL4xa+LZzmQrpWcDP9pHxxvxCeXJ2"
    "duaI5kUALY2pYjlT53uGhr81yfm26G75FtxJOi6atFu7E1apGNLEFvn64wywNqe5g11lvjiNOnwnV/qsvzJbAeawEpulzgEv"
    "n2xtoVmWNTjGoJGilZi6O5T2gWVBexbt/IsrUMQPBktuWfXrkVXttgyo780QgP5MsD4SQ7jtsdaX7MXiQ4pa3y1iZzJms+ZY"
    "tYBXqQATNct4gLDTHeQCK+mlByTUwaWcBKy/KYPE4/hkRb63JaSNnVgFOnhSLjfa7Xo9pDVyhkmi7nAC59ltgJpQESdCusSx"
    "u8NZYAU2ZKRoCWxStvB2hxCwdr3mfWPc2i38z0FcyE32ZriD5Lp67HIcNtEN6Z+ZVXPHdockvccb9vSuc6+EkYB8Xcoe+x5V"
    "sPL2sOSx6xRhb8NnZ9edcihBc9ZkHOXFhpIOAktzjZ44WDFidZZDDAGLRIdbLMpUZTkLqeUL4i/Osmskyl7MYuXpeJuHOoii"
    "d6O/e2MbbF1RFNegk4Cj0dNgGfYJhQU35S2EdSjXzsLd4crhJSKVX+JV48kvjLEzGNlF8A9WxTFOxLI0r3n/mmxPI670Xnnq"
    "AWswUKwAsLD/WWyUyxMdn9UREq6I5OmfXF7IEzXKstkxhZX7FxenxBT1L8ahSeUiy2dPsb50cQEc/PTiAn/89IJnLyaQ9y8X"
    "tu4QHBLuwJhmk+daw8DTld2stFR//Pwf7hE6IR4XfnDWXrhDQ53Y9q6c1Cqtfqvb5axRvdlOhWf+suFosa6X7VMRPDudYHyD"
    "cfalV6FZGiWegE1GY61djr8wCUpDJetGDhXJXnfUbPI6uerNZqYJcxCe7hD34sS/BAyUv+Up13KHhloTjkGr9gxDmzwBeR6P"
    "D6DnHudXcbt+uF8k2hcTURjn5FmMkc4ooY1VJi9/4YlpJlW0CAaL0k7Tniy1Nca3rNdw7U0cJb63T+Uez0gTTdyTpuLoljox"
    "geVUqtFo1q+tqhYRLfaN00ErT31PtsaO7/n0gw+sFOSdwQKeyLUPY7BOKvCPm9qFnW5wSYrdsHTpzgKdnc5sLj12+ULsanTn"
    "nYYusLjEUyXuk6z9+HtaQZSSHrDsroAJcRBFIyJY2Tz0n00zKuoVSRhnW60psODWb3j4hnwN0xBZaJI/qaBIXrKXJIKcysRc"
    "sGxWrkQwWBPu4GJFvqH44YSU6huDjYCNIbn0136wuqKLOdCXZQpMuEvzxsrZsBSTY8Zq+WCwbNN3k5XdqYqTihNdXoat7PIk"
    "Ni7C44ByYeryTItMwJK4oL0OT4PAqqoFX3fOzKm52o2vUyYsMrqZpNCDwMpPKHrFk3CvsbPFpnbyIQpaLZH2L8LVaJCoBMBT"
    "PZG0vSPKs1HLA1ZxGqwU47GDtPkrzMKf+ujh6ayIBfSK3HOtchoAVr6SpamwU1DDD6kUDPUgtCSYnmG8fUwvTBO7sGuSkydX"
    "i/HGO2OwjviNybYCF1jx98UpmyVr2nDLMIA1VK2RnmEaTCF0EmzKE4aAJbM3NyxNybPZk5MT2Q9W5eby5oJ8G/oB22mCga/1"
    "b25SpxSR0whmgLxqMKYcSBZfhWt7e7u6bTWDJAu2JJ/nlKfTaqgozmkV0lSiFHiW0eoRuOomI6qBYMn96Tj6dIZhY2UEh4c/"
    "WITpgqYAb84uoah/0keVO5Un1OEE/eBZBd1kLRJYhLMEmjY6M+C6wMJnp8E60v/sOtdiAhYMPAWBxTUbqbJLFQNtlswGRTph"
    "anjxweFRlcrkeyduv8I6eeUzueYCqyKfOV9g89HAAjoxjaucEj1JeNrvkJw28NLehmsJ4GQXjbInFQPAup7Ui+zwMHBX1sXN"
    "AmA5CguPnfY5nGTdlbJT2fZ6NxU08DGbTVTypzdTDN6LQtAzC3DK36qMvQHM6dLzbqiegPU6AKwNIljOcjI3WLY7PHZ7xHIQ"
    "dZCzsaCkbxgpzI4JWIV8mK0gsySfI4yK0KW8fAoMDbisTD4LqoQ0CrQdvhD6FAJC+ZOsHFSUVsVJKgvZo2ch8pg6BIEFaXjn"
    "ZBWPgW+46KjjDUO6QjBnEhGs+7pq/jjxhA0xblWTYcZWSy37VrGOwUrvTNssOADZPrRn1w3Wd+o4LKDFEBiiCp+LJjT6xi4U"
    "nJyczWCF93V5i7Nn/jjLjRY3atZHVrXVMgxjy2+FHbB29ZwyWahvZx1eK786c9IZT7gDPpbRYbkZ0zKGmsyRwJqZWYSt1U77"
    "faxHnbGfH6wbqMJd3lxCSe40POKXqyk7Td4ccd3W1IHDTtZByvwp/u8+yXoydoW+eV8Y0CPsDXYglK1Wq4eERIy48fZ2YNk0"
    "8XZgnbJz8yK0oU0dJ39RD9u+5C/HjA8Qez05x4+xXeF7fgIW582UFhimCbZrwh0iDlfcRAdLJuJ4ATKxeUOIFrnIX398gxXb"
    "/1okDX0a7Vca4qT1uoBHW6he/zoBS8r51HBf2XH1jZRanoiTwbOzs87sWeGYKUQc+L2M8s5h7Jd9c+YxzN5ehxMoc2ejQdaP"
    "BhYvHk95rXpwWrlkJcab7Bi6aiwnhUxH4+nfhIbKqTEhibwNcS5Ylf5/pALSnGdaUHn75Ia9mIvYRSSwcDDXFe4WpnqK+QlY"
    "mdzYH2KRdZBwNyR5wIIDMxg48zSr2qIrRh5xYtnZAnV5svDY7w2bnVlGiwYW1qyaRrc6arYbDI12PEMWroMtQLSexieStS/8"
    "JRO6bRP2oqrqd8TWNxuo3e8isyf2JgypUzdQsc2Dg02n9wOattxgxTYPNzdjPkJwUbklWLbfgDKM2KRiKmtGrwoTKmI9uMgq"
    "6e+Fb8bLxh67XKFnMNOmHNXra9rOy+HsL6NH7YG/CCwYyBe+OHLzwcOHDzYJSjCy6gErtvIQ1jasPjzYnFLJYBLPZiNJFtas"
    "1HLD5K0q9ClpTMEzbLol+dqNntilMOW54u2wCemiqTQZ0Z6kqt4erFP2LMZ6cjmbD1cIWA8exDYfrBzE3GBtHiBSCJi3+eOM"
    "PTsJrEGy0XiwWfAw7QbDeAnRljTV9UfBigsJa9c9keI9HVM2eHxalbI48RzRekovzmR/axnh98RHu3IDBKJHKw8erABcK6sH"
    "MNrrgLW5+oiARGVr9ZGn7nxBYsQYka+pdr+IYDkVabdHdBt4w12QLpZGCdtmKU+UnG/JkXtPN2eKago5hGi3E8JWxGgm/tSb"
    "dOqzZ5fZ9ZXfr7nLizGqhCubKw9WNg8PYbrXBisGMB18iAFUB+RjV68MNs98PCAveMJ6LehlNIOKp9raBzQ4y3XcEym+zj9p"
    "j9bCmLgw8DUruyNpPNQAsgz0NFoQW/g72lbEiquFRc7e3EBMSzv83ZmUzQcPvlqJbcYOEA2cVkWwiA4+XInd/HFz5SEssltd"
    "3XTnXGCiHx/Ah7NJnTsvs5FOjK/J+e2GWHCXF7x8yLdGS+o8UzYArJ+E1/5xlEm3MqfCWWT07CjcINnsViG3L2rRwDImiWTW"
    "vqdV/7w0yBbYqkcH2LMXS1GwiEQdrMRif4wR03WAxuvAK1h2i3Ile3b2H+OzrG6i9FIkYUt7azutmymbbPmXW6VL3j12cNI7"
    "sVrMvvDzFFhj7tC2T4RNlp1V+bgp7zjaSgft5FKmROFmYozpHM9EtIgoxR6srAB9oFilqBoeElGCFSMnMXadjR2CTsY8jaTr"
    "k4T25RlLg2b2LIrItwCecruz3RpqRqs6qjfr3rqx3Nn1D9jD0RYC89wVFvonLOyhz7JVpznrEWeWcUAv4v6Liw8nJN47u/Hk"
    "lOi0RXYsVzCc+eDh6sOYjZUtWQdgpchn/ni4DnWxw9WHjh6m3ILl+NgbWFFzdhLJZE16aFLtUSugMUTL7E4dyJ1Q4sQbbkzN"
    "G47blTXYD1yoyvZx35Z9zEH0Ta403+n9nHdE7PAh4QwHD746gNn6k5NUipmAtXoIhdiDlYMTIn+bY6PVH7+G/1dlo/XIjcRJ"
    "4ZgQ7ka9anjjqIBRVul9Iv6YUbyMFFehO+6QBoQjnrZnNWSDHofEqLc+mhat1ifXeDn76AHQqQMQqVQshmCdOWCtHhDtXCH6"
    "eROLHThg4VT0xzucAwIHuox38lFPKJbNUXUCGFcK2Pr0THg9NSMtwZEXjoXHE+9E6giJmR/SPkD1bseDJalYsDYl/eoBGniG"
    "YQhaANkELEIm1sn/YuwNYEXBwjmwO50DIrNt0TklYbLeARpfqsHOcMxMmYQlnU+B5Vj4bzHnQNEfkV9Thk7c9l1T63Ra3q4t"
    "AM8idivFIFogXRQsonYPCIs4PDg8Yf9I5Sw2Hoo+vNvZFnKlZWHLUWG8WQfHDx1b3Skdfe3D6mvIxhOwSlPj9+PmbkJF7SFD"
    "GjmxjZFl5O96EYsDW49o7zIoGgElZaMVc0gpoQ6bm4cwe39zQrFacSab1j6urN75TZDQZNtewTA+yci+taQeMFB+dJ5TmJ3p"
    "4fsjZqxnrRRt9SrT/lR5Ob2za/T8QpaCBSvIKFZMKjZJ0RyufkUiQhJcx042Vx3BOvkvVOPfXy3lfcCA/HWTcRaQO6tdNSlo"
    "oWQxHWf+HLC4x7XXYThqN9rNJYiT+4Kj5YgeJc9oTga0j2FsyRrHhsRMrWxuPoQ/DghvWD106qV3su5BdLBVrcMk5TizbDBh"
    "ex0C1joQqzV0NzosSZ58ikhbjWKq6iCFaKnuQHqVJhy+WnVCQ1xaRwOd5V7ysGe1v7X/sR20MxhXQhlSes7ezfu4Vqk/y4Jg"
    "EbgcqACrMVixtdXx9XDTzjeDEi7ngJmwzCDa92mjdQ6Leww+HWC0rHsGi/B4nAKnY7zjy5tWZokComw9hGzWCe2dWP+4sna/"
    "b02TQtar/IZI1nnAlqOOfM9gJem2tsARRG9aGfKnkwaPtcNleMLZdbKSFAzWDpPjg9bYSdp9i9ajj2h6goYyQgoWjsG6uud3"
    "xgWuV0awftADFyR28/euiJQ/VGIRwbKxum8lDNz554D1Z/2oGM1oZdleZYnaeXVATxA1YpHAYpFyfPq0RCWUv2td9wJSDkeh"
    "YP0mHbhN0r9BK1vJs6IYM5ZrthCt05MIYFGs7nY25FRORC2o7NQqAyNIsM6x+wiXus5bnQ+1VlOrF8R2XlviWBch8vQM1pO5"
    "YGE5cPXjMhkW0ZI2Hiob8ybntoPOGigCdUgwiT0pAKsjxgNWpVEoNM2CaBmNN8s18siZKmdzwHKwWibDSrUrllh4Z4piw50G"
    "S2YCD2Yonp+//J6J7wUuoi7pHiWMiQV61ndBXObE4Kp90nbtzUywsg5WSzTuhiqWscJeEFV3GsUI2lIKkgWLqOM5PXMekL7x"
    "no1itJ1iiFrPLxUtioDMzjhpoH8PWMHWELsrpOl5/HshxAH3Zyk7ncAg20MeksO0Pf/L/KG6TLBISG1vksmGgYW90eT7Pi43"
    "yqk2GPvxc+6F/LIeuEqyeJ6xdqAivR0MlksPk45cicyyg8arVYc6GcELEtm87QeXTrBaDK0Z0yqyk343jwLB4nVu8D2zAWvs"
    "gkx8xuUk6vbZDwWxwdeWjtbKCp7aMFZFF1g36NfX1j8uHasanxKdFLzLskDGQZKml5Tyox3hG+a1f8fR2MS79K2lqrqJNn65"
    "VMuxW/YZF5VLZy0nBeuEVk8Jb/90sGy5MrCTplAwm6q65fKFQWARk8Wn48oGo/xfdq+DX7rcJ0jLbF9mCHPgxWUcch/AID6u"
    "UzBwAGicdag5inofAeG3ono9EgvNfNXV08VJR7tHAVgdScMEnLvzWEhUIfMwRSC8CzhbqqhW8+x1/h6uNTiYyd5/nz2DIab+"
    "hxO7iI3nhN1LouEPlwQw3wFefMimYMl6FgewYBJlJMGRfb6gqOSJD3ttJpXNy/eTukmuT4RLzhKJMmyorh6tfLyv2Jnci5Vq"
    "pPqeuDDQIp3DMpoXtKf0scI1ES3Pd+yWMt4GgKRxj0kuMFwrj3zKhocbrtxjnqHyXdJzT73gw6/OJX7g9JQ+FeI8n05Pm/j7"
    "z9N40vIfVw7ccF2trcI5YKtXn+9N1EvBWBFXGKdqCF2l/x8foIglPfkZ0UJDTlTOwWYNhM3Rzc9zGWZwjpSQ940xWMq+kLBM"
    "gpbfahn5z3khnfp4AHDBaayggY+uPucbsIK1MEOUcN816PQcdrOli9Ks8yA/g3Dhob9EGdfoyY/ryc/664dmYKXCtJ493vfM"
    "Gz6H1a4eJk+A2zW38p8Zrkf0VE3wgZ9VA5G9B2lhsWT9nLAnUsZjv98Lib2pky5KVj7/+eH69BFOtP3cUIXwBgkOdB+88A2U"
    "7wsKN/Jhu3v/VZ5A23XwmRUwLDlTJH7vmRKwMUTZEAbPLF9cdO+l6RDx+if8Tjz53t9LanaewQa7v0/togG9TPw68pQY/zmi"
    "9U+5ts2por2kpzeEpy8CJIsKl/KM091w3XZp6Rd3aaa/EF0s6VzcNXvvAwviRCWRs1yW7n8b0dor+VMzZv3XgaAI4WDBF5VE"
    "tzNBmfnfQ7R8hwsQ3ErWjiD8VpgFlqA8iQ+U3GjcSeILp5earOzDJedrF7AKsQIz+/b2MfmUjs7L/SxdNnAKCzMq+H33ZLFK"
    "PsvO8wnl1WNhDlgQMgoJrm46P3ZvXIvWKGq4IOzS7l7GqlcNMqZn/Xzlxt5GdwFfwG+/vJ/Mh+atFkqmzinCcz82U2A5hj7n"
    "9EeU7o3GZ8dbeghcfRdYrD2ic4lfuaHbAWW6smeS1qzJyxQst8GSMukdxWPaQ8GCba8kxH5bNzHHSrjGQr+3Jy8AFtvvV84+"
    "sKeQQ86efLih62luiFgRoC5OiFiRjxHUPnzPqXu9+5wuFXmBDvQtt2ARL/j+ddxr2mdIFqzFeC683TbR1EnmIszUUptydLD6"
    "uD7mUmZhXvfMRqJ29uEGpIsl6MEBBhcXLBz8BBNO7E026hu5XmAOJM1MOJZUAtKeCMAqDCzy3fEEXfYgLZTXqooFlZUjg3Uh"
    "yzDFg7olj8G6QbBOQNRAFU/xOxGs6JpXFwvit1HzWIw0BkvSuwSo13EhOliwnuY/Fc72iWbkkk4VCkxR0criMQ5YyWHdYOVP"
    "T2H72tmpByxQ2suziC8tj3DXWjTZSroXE6RzOLWqLASWILwWEs6a16jMtIvzCseiqS3gDZ1lfxOwqI1na7Dwl3WBNW/7qMtw"
    "2qdURPLkrmO2S9wzZAPB1wywhMdCDrm8FDVV0xLtUSuxUYkG1s0liEqfzoi7wDrFDXZ+sC7ZwPM7giSLTrIdi9tRrPuYiUrc"
    "M+UnRbgNWBvCDo78SBGzD8b4VG5mxo4tv4Enxh1oA+sGq4Z93AiWWw0vav49weEXb5/yOF8TO5MlPenELy/+oSi3ASsuJLZL"
    "9qBYBB4/LNubEqDZRrUie0MAinhEN1iXONtbA/FyS1a/dhIZrHydNhTNRWtyfHspnRCeKjMAmQWWYoMFcDGd+VhhV5LYtHCK"
    "+g9yNG9YI6acRZwmYF0AU5dhUfIZ7NSdeMNKVDWEa0TPbZpj5V0jAnCsxwvhlmAJT4WXknOM3zxF1Bp0QN8Ey0XeIxvNG96c"
    "nRImdXniUUM4k+Dy5oYQ0pObE6jmA1Bgxm4iGni59e11r3ZN22TUmXbLdQBD+rUvcF4MrF8ms+a+VsCpoLhBxxyZvFEGqxWF"
    "EdKo5rTvnFju6Jgzmn966kRAWfjzxm5HimA8TdhA0Ohez7dbrnUX5z+4diHeDSyiiDMUS26jDh4XyiO61SAVgTz0YTPfZSV/"
    "cXl5iZbeXrgFH7D4FfIdlxf0O/vw6ctIZ2Bk7SPIxZZFl4qFa+KWK3WX3pksrLsrWEVmxgNqjo9Hp8t9xM9bnvU+A9Xe1Foo"
    "GxadhQ9DS65PBsCkvYQQvwtYf/OsfAiNEeWmOFmCg0bVGlat3j8nxwpbc5zjfFOaY7eC0XJPFkp/mu0K54H1/BdPv2loHtDu"
    "omRMZ3mbqeOqpWv5nwDWNWDVaFJzZcr8DLQ4dwlayil3AuupwkUp51/TEePy0MKATGV4YBEMeYftz41Wq91qgvHU8xQtsZ6v"
    "i1OnW7kTM5NsQ054dRewvveBdWRuh3NlsWLgutx6D9qAcSd29ATEna6hE+fL16LI4Eo0sSozzg6KOlXLKdmSO4yn6JdzttXd"
    "Fqyc5GpxCw57LLpRWDW28HAQsZVv0qUZURnEXW2Upaaoj2zhmidcWqVW7YUdBbWPGzHhafqCCu+o3C4cYXg3sLbmtopg1y8s"
    "p66UEbSybIl0EcQI/n7nepL3AVWymhILKnS6atdOsz55E+SJiSKV+HIFNRGOTvMZ9113Y/Iu/xvhG+EOYMH5o1M9zMnpzBF5"
    "gz2tTLeqd4e4NFc0ZTxnDI4yp42olXb1HuAyYrAIMlbJd8vOqTd6qmHgfmMenaLY0MCA+fdnT82r6t8L398FrN8J+525k4h5"
    "YtZFDrBCM4pL0YFo0e3oKfLE2+1r3O0mmvfQF06kRixbvfr4RGjxW6MCq9kLjHaNjIugBGeSt5Neku/vGNL/D2H/LmApwmvX"
    "8aO2HZwujVVVTkuhPKkj25wS+wAfHIvNLTi0WUwZHCyHVf+wVOEadq2WURb17sg+hQKNZpMm/+CQ1TbVvzoJrbwhxXCqWL8E"
    "sAZcaao9PjXlEo1KQ0TDdU1PJoA33EN+I45M2P1zTMfVGM+pSXe85H4TNjCZVtciTIUuz0STAJqP+8TELa1Med+3edkjVxp0"
    "2kpLBuuFwmWmRi+k6WmnfgyzM3Wa0yJGtabZi+900T5cCt90efx4s3cct9a4hkpf02zj3+/ERoumaiHUquKvLcsVcXpvMvEK"
    "deZo6WAJr4SddEAznC/uuYKEskjERqZUEFZttalnSjPuOKgwFixNVVnr9n31Rp2e0EujUSAGx41q0jmOsWqfb0UIfA9NqeqL"
    "v3VmauXTEsD6RnmWDhgZK5lTcXIrBfVCA8ddicGy6GZFCw1XgUlTsBizzWlOxawg3p6EsbHJ8SOMvaOoR5Mf1ETRoAcnmWCe"
    "1PNUZCuw273z5znZrHlg7QtvA0c3pczW9MOW8xQjmv9Dy9XCDYuqoVHsYPtSuQ4/iqfARV2VHlgZoVKFFp2ms/E0IHQvcDwX"
    "9cX4pPwZbosJnDlJ7wQU7BcDa58P2PoAsjUMy+QSFmifqVLeYkXqjDDTXDB5hK7Z7Rk8LEYr31oNZXRzxA0iTQfjXqAryqlh"
    "B7k3yjQHL1q+dzpiAmbk4NCYuRmaOWBtTK/HdaLETBBalkjCZ1NjqeXqGip6bg2dUkFMv7O36Koq3+tZ7TusDqyKdKgSIytm"
    "hBlt8B4GLinEMRqKlujPQqYDBwqXAdaT75VfA8dcQ5praCiNlQsI+NuoB1YeAx+xSUuw9ildDd26w0yslsIIUMMzNsRuEzEa"
    "2YYdVj/LfH/YVsmv+c6vg0fBc72lO4NF9PCHThhaGSOQT9sLB4mS4bJc8sCH1Md3MaAt4HZeyOSkkvlW9bYZwmskodd4nJxY"
    "a1GbOMzLeHpLWzZMtSzLWb4rT9mrrwPHc4hkDQTlbmBtKImOdB4IlpTJcEE5UzvoUA26D5SYEvxcoTlEZSy/a4gqEtR6skkU"
    "MtUzgimEt71brrSq7ofzHd3ES22WBgveya/i81SIGb1c8JwcMMn2ScFW5ejo/OVc5jAPLOWVwushLx/YiyTr9kbFFhLD40Ij"
    "Sc9tEY0qGuVRnjx29PUcDcHFslpuXveMihY8+Zkccla92RBF70YJVpyc89Wo0ANpRQMDB5oeKqj96VKOdHQkhazlyc3Vwvlg"
    "CTmdD0crYCKx1SR3XyexLPJBwhDfIGh1+m88lM3Ew0q74x2oaPNTKdiqylvVLh6z1iIIwWJGrW2f9nNc8KQNWhOwYJd7k5rF"
    "/FaZUlWGRNdyEFbBVxHOXnh8R7CIP0ykg7YCOpGPFSANFQPPA0Wj20BOBPYE/8bgEMVArFt2jtDujoCPv5XLKqx1zFeaCJGo"
    "8lp7fE6991xF+8g3dCZqdkjjd8x1YNaj6beocuAc0/hOtucZrAhgPfmtwvGhYBG0OmGNbte2YGGOWbyGahm5h17ePhRBrdbR"
    "3ugMDSKpD4Bd6iQCoEkMgDQ20u3KEeUGbvaARd2RHUfVMZucyVPHWJ4KDrR6OFbF86NOTnl+Z7Dw4EPp6ChctupboVUWAGlE"
    "XWJlSA/dlFEmsKbH0Gq/SRfCoGS1KpCBKnDXKgOnCKFTZVRVLAMb8e0Kp+StoenIUyoatVotwl5EtTlFAlsZJlysiBZa8XkV"
    "1ihgCXGFl4oz5NfMGKFNgHZwBoLF480Ay/4OYatjyEIcGMoUM0JouQr+0KgBOJUxQC6Y1awxRCvH+8MFFNCWfXzZCEldOz9S"
    "y9M5xqq5S8hO+F2k3yvx390ZLGiL3wGqVTwqFsPoaTc4JFHHJ4+UNRkzS2je8a7EbheTg9kkCkgTVVPUqFfjy+gttTG+Mn6i"
    "6m8Hg0+aGnYOpDTMa8P2dX6KuiUtJhQo2I1VlEhgmBD+dnewlLiyTahWMQwrnCsIopZaXRXtHikrv40uEcy7bKLxGlLiUEHB"
    "EEcYsYga9QIjWNov9mREm8/bp8aJ/mfyBgE2kPuqkOkIOZtrK8Mc7YaDRe6ryQ2EgfDXu6shuXbmopUJNFyG0US1ashyu+Cc"
    "yGZQiiqj5WoQFAGlLtrnsoyRsWiVnXQ+uZpOfFz2GyJ6nEYdRYq8kkZiczMgkdE1CRWVZmBVPLfmZxyigaX88ttBrkOfQPBF"
    "nhoT0gdRuyZMm+gPVRm00BaqX1WjmOXraNmGqEsMpicKTA9j4JGB5uydU8edOhhdQzDVIXUl2bzVCLAHyZFZ2g2hohgUwvaU"
    "nPKToiwDLBgTU3K6FC5YaLiYTnCUR4Sr7bhGNDpUxjSqftV8g8aPKGcmDfkYSIMdO1vaTTv95Sv72RkhIBpYT1VTgbtfuIwp"
    "7YZ7QbgkiUsIiiAsByzAK6ufk2sGWkdMiFfM9418BQ/DQD2qIJE36XmMYn+IOmQrZZM2gppbDecMUBINEXGEU1rAowZ2sR4z"
    "SaLsYvtCDqpWm6VwrKQMPP/zzF4ikhJGlCxl4/kzEoPq4WBJ6BWtMIJqQMqcRrY0PWflkZKW5RYqpZVEd1enfV7vNBQ3sdFo"
    "v2nWq47f6wa1haFjbcWaraC40siYsx5vJgNYSdZOBIq1iGTFB/GuLukIV5A6ggXd3WWksB42rdtUaWDbtHOZ+DfDNanhRyNN"
    "ZMdEk55sYKJFkzVtOBziLAL56lZw472otuXAfsCkZZZmYXVUJGAhVtHkKroaPk4McnomQ2lJoGztonClQ/NTBg9yV8OjfEzZ"
    "znzZ6/GGFbRploxLCzFrCDaq2oAzQLQ8npFkH7klG9U/TOhBW1Xb3eBfyemMdDTvymSsjUQ8msWKDJbw97gw+NnipVleEaMf"
    "fvbYVlYFWzSyaw70QFTRlE9VdAAaZgevaVqiDRwd88Jtav1BQlmGBNqpsc712BBZ3hrNEyviBNOSvkfkKiJU0cEiLzlQ4i9H"
    "EvYghQfWksTos/pJ+3haBLAhyz7LhdavEawWFTAWbBHlYMfjw3PFprFtsf12pI5Vbc+cJ1bg3Ev6XxLCTy+EpYNFrwSvEzyI"
    "F5FmMFTTmnGUmFyptqFHg71uXddHpkjjGGwrFlstlabQ0aClZHQGDXnLbuolPqJrTThI+K/oSowkleZo4LkkpXPC/PTo7cBS"
    "lMeCMMhxFuAlFSlJKQbqYombNaEoa3BEuNjsDmmPoNin1ZoCQ7NaVTocUdBNarp6qn2OEFOwsmowi3AbR71UmmusYFCHSyjz"
    "s6O3l6w4GMNEjksTvyjNkPNSKbOdnD2GhLlnWitt0FL2+CSqFlSJnKODCDC0xwSTe6lKivGeYjxlrDpmKQJSfKebSAziEQLC"
    "W4P1ixJ/CiKWyL1/ye+lO4SpHp3TBXhSSXJFYMR0ZbozCjc9VRwfPAUVY7lBs8T4h0EP6qQIpQwaRkM5yGxey3K3UAjf/7kF"
    "LFSakWGgb05Pbz8bCEo8rgj3J1mYO91wgqC3v/khx+Vy3N7Ll+mXFoEuM36fBLeSmemGS1er4cClsg5tFUHUQHog7FPtEwhb"
    "UCSEc5K6Bj2JkOCshrnAbRNzMQFbWYvj56l3RumfYQT6xYtFb31xsMj14nF8f2wYiZdE05/YyXEdCcyFI2ElRt8LNfVytV7G"
    "k4ntvsthdTRqdZvNdgo3T2tWu1xOtXmkm4ZbRqspPnDAP9nqmOPMsR8t8r5MqaN3rDT3l50EgepVhFzfcsBCjOLxjSf7P33z"
    "6t/j8RdPnz5F2Ha4tKfYRDj9jJOzNKPV6/nItyzXao4b0DQ5xD0EhQgBZp2I9y755DmxFGmOe5lL7GzEYYdmfGNDuc093xIs"
    "RRgkwDYqCqQ24M+NDZA15dme/5Ganda9N8MbllRinLP1XP4und7b49O55NuNeJwqAHF/4KVud91essbPRvnreNEIwet1ujQF"
    "V32bu0e8kpxuTkkVMU0ct7Pzlqic4rzV/f3HTzYSymNF+dxghbbdPJvu6GIYs9Ot3BNSexLjYetgMEvSHiFRNiZPv3/+VHly"
    "a4TuDyzI2eeaAee/Mkymwy17TCxpbOslZlea7lkBvvlC2N94rfhB+uW/E1hKfECHrSTPIZ3I66VOd7g0pGRuW6dMwV+NKOm5"
    "AbFMg2UI072CRXiFEO9IXrC+npivTKdqLEHAhl2LeD9Irgdk1zNdgtVgEFd+998eLGK3cnp4oEEioUyny2m3tvjJLWKmSiWm"
    "FELUd0tWYiO+dKm6J7CUV0p6Vn5kl9ypaeppbktbcBuprLX20oQkIFBhv6Kk7wzignIfaC0fLNjSlbDMebEsUaISidH2CGTz"
    "N/LLSc3obXd0IlG7u4EU3VWFyA2Ee7qYe3lVhdNnyJZ9v5gpZCA91knvdTnOGLpFTSYQasPhFsftpdO6JJnEmDNRUi/Wa+W1"
    "8oWApUCSKDH4y8xEpWumn1j/3V2iWCBoJMr1XBCOE51ldnd3d4+iXZK+IwhfjGSBsVDiwlsYYygeLXJJFBvXJZWko8WuEv/y"
    "r6+ef1lqKMSVnF46+uxXsdTZmN/t+N8LLGy94STps4MFp5/tK8IXJlmKshFyBtn9grU9uEfBui+woGqyMfrciliyCMVSvjjJ"
    "Qrb1LF06OiouaOZvf51LfI44YuULlCxBeaI86+Cm08XQ2gUitnsLFZT0l397LtzndX9gCfF4Ikm4aXERQ1+SMkCwzqVFNLhI"
    "G47hBIXH96iE9wtWIj4gIXUxk4lOtNJ773/e2fk5R0JAaSGwihlJ/78TCUH5QiUL6Sm0DM5sJXGNMErp3M7Azum/fW9JZjS8"
    "8NXPS52c8DgufKlqiGY+0QJNnG/lif5ZOazmCU+/wYpeIod9AlHAgjYrfphQ7hmr+wZLIZqIC3KK84wzgQoquJANFn4nPN8g"
    "pvpZrqNHCHjIkziXdG7wjXC/SvgZwCJopSU8Dj1cG0tSB6BSBu6+fWWDSldpFkq0NYXo4JYCeeQvWrJwQEN5a9GEzeSQO8/u"
    "JCnTye0owjdECh3RUIQBtCJ8A10oe0S6ZrCPYvH8SBo9g1RH4gsHi+6/jhN9AiOcOTq3rZfdbVlEqN7vwPco/rKkgsKlDHLd"
    "DvacFKfnSOhxqXr37eDpYyF+31jdO1gCFvqJgHTAWhed7nCqkZDAsrjXEByF9Asr+4/j0BVg6ZmMI15FpzEMWnjQ2g2ExEBQ"
    "7v9O7h8sBVqdye1sWR1e0vVJ7kqSOp09yAE/V17MSibG4Y+dlyM9I/HE+p3jYbvkT3wRffQXPMzrb+4a+RcsWZTNDwaJZ9k9"
    "ncfhg3OdfGC9zBGbHH89t7EatBGsFz/SdaT2gBSJojJ6Zzu3I5DYeRD/HIL1WcAiHHOAm3gHb3/Y4V7ixeV+2AFaRKRu7k+D"
    "JgNeg50cN0qndR4qHWmLf8/BS7witiqu/MuARa+NxxvUCuGF1vjfX21ERxy6Toj5S+z88Gu3lfvzzrPH8BpPf6t8tjsQ/n8Q"
    "+Nz+f1Yd1AAAAABJRU5ErkJggg==")


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
CATS = {"G11": "Grade 11 Teacher", "G12": "Grade 12 Teacher",
        "MID": "MID Teacher (Grades 11 and 12)"}
CAT_SHORT = {"G11": "Grade 11", "G12": "Grade 12", "MID": "MID Teacher"}  # how a grade level is shown
GRADES = {"G11": [11], "G12": [12], "MID": [11, 12]}
USER_TYPES = [
    ("TEACHER", "Teacher", "Views their Teacher's Program and class programs"),
    ("ADMIN", "Administrator", "Manages and edits schedules and class programs"),
]
KINDS = {"class": "Class period", "recess": "Recess", "homeroom": "Homeroom",
         "intervention": "Intervention / Remediation"}
KIND_LABEL = {"recess": "RECESS", "homeroom": "Homeroom",
              "intervention": "Intervention/Remediation"}
DEFAULT_CFG = {
    "school_name": "San Jose-Litex Senior High School",
    "school_address": "San Jose, Montalban, Rizal",
    "term": "Second Term, SY 2026-2027",
    "principal_name": "Arleen D. Canapi", "principal_title": "Principal II",
    "psds_name": "Priscilla V. Jose", "psds_title": "PSDS - Cluster 1",
    "sdo_name": "Doris DJ. Estalilla, CESO V",
    "sdo_title": "Schools Division Superintendent",
}
TERM_NAMES = ["First Term", "Second Term", "Third Term"]
SETTING_FIELDS = [
    ("school_name", "School name"), ("school_address", "School address"),
    ("term", "Term and school year"),
    ("principal_name", "Principal name"), ("principal_title", "Principal title"),
    ("psds_name", "District supervisor name"), ("psds_title", "District supervisor title"),
    ("sdo_name", "Division superintendent name"), ("sdo_title", "Division superintendent title"),
]
BUILDINGS = ["1", "2", "3"]
FLOORS = ["1", "2", "3", "4"]
TRACKS = ["Academic", "TechPro"]

# ---------------------------------------------------------------- Strengthened Curriculum (fixed)
# These are the only subjects, tracks and clusters the system offers. Every drop-down, section,
# teacher specialization and the schedule generator use exactly these names.
CORE_SUBJECTS = [  # code, name
    ("EC", "Effective Communication"),
    ("MK", "Mabisang Komunikasyon"),
    ("LCS", "Life and Career Skills"),
    ("GM", "General Mathematics"),
    ("GS", "General Science"),
    ("PKLP", "Pag-aaral ng Kasaysayan at Lipunang Pilipino (Philippine History and Society)"),
]
# Each cluster lists its official electives. A teacher whose specialization contains one of them is qualified
# for the cluster's class period, and the electives are what the pickers, Subject Management and reports show.
# (Which cluster owns which elective is set here and nowhere else.)
ACADEMIC_CLUSTERS = [  # code, name, electives, room type
    ("ASSH", "Arts, Social Sciences, and Humanities", [
        "Contemporary Literature 1", "Contemporary Literature 2", "Creative Composition 2",
        "Filipino 1 \u2013 Wika at Komunikasyon sa Akademikong Filipino", "Introduction to Philosophy",
        "Malikhaing Pagsulat"], "Regular"),
    ("BE", "Business and Entrepreneurship", [
        "Entrepreneurship", "Filipino 2 \u2013 Filipino para sa Larang Teknikal Propesyonal"], "Regular"),
    ("STEM", "Science, Technology, Engineering, and Mathematics (STEM)", [
        "Biology 1", "Biology 2", "Earth and Space Science 1", "Earth and Space Science 2",
        "Finite Mathematics 1", "Physics 1", "Physics 2"], "Regular"),
    ("SHW", "Sports, Health, and Wellness", ["Filipino 2 \u2013 Filipino sa Isports"], "Regular"),
    ("FE", "Field Experience", [], "Regular"),
]
TECHPRO_CLUSTERS = [
    ("AWHC", "Aesthetic, Wellness, and Human Care", [
        "Aesthetic Services (Beauty Care)", "Caregiving (Adult Care)", "Caregiving (Child Care)", "Hairdressing"],
     "TechPro Workshop"),
    ("AFBFI", "Agri-Fishery Business and Food Innovation", [
        "Agricultural Crops Production", "Agro-Entrepreneurship", "Aquaculture", "Food Processing"], "TechPro Workshop"),
    ("ACE", "Artisanry and Creative Enterprise", ["Handicrafts (Weaving)"], "TechPro Workshop"),
    ("ASET", "Automotive and Small Engine Technologies", [
        "Automotive Servicing (Electrical Repair)", "Automotive Servicing (Engine and Chassis Repair)"], "TechPro Workshop"),
    ("CBT", "Construction and Building Technology", ["Carpentry", "Construction Operation"], "TechPro Workshop"),
    ("CADT", "Creative Arts and Design Technology", ["Animation", "Illustration"], "Computer Laboratory"),
    ("HT", "Hospitality and Tourism", [
        "Hotel Operation (Housekeeping Services)", "Tourism Services"], "Cookery Laboratory"),
    ("ICT", "ICT Support and Computer Programming Technologies", [
        "Broadband Installation", "Computer Programming (Oracle Database)", "Computer Systems Servicing",
        "Contact Center Services"], "Computer Laboratory"),
    ("IND", "Industrial Technologies", [
        "Domestic Refrigeration and Air-Conditioning Servicing", "Electronics Product and Assembly Servicing",
        "Photovoltaic Systems Installation", "Technical Drafting"], "TechPro Workshop"),
    ("MAR", "Maritime", [], "TechPro Workshop"),
]
# names the electives used before this list, so teachers keep the qualifications that are still valid
ELECTIVE_RENAMES = {
    "Beauty Care": ["Aesthetic Services (Beauty Care)"],
    "Caregiving": ["Caregiving (Adult Care)", "Caregiving (Child Care)"],
    "Crop Production": ["Agricultural Crops Production"],
    "Handicrafts/Weaving": ["Handicrafts (Weaving)"],
    "Automotive Electrical and Engine Repair": ["Automotive Servicing (Electrical Repair)",
                                                "Automotive Servicing (Engine and Chassis Repair)"],
    "Construction Operations": ["Construction Operation"],
    "Tourism Promotion": ["Tourism Services"], "Tour Guiding": ["Tourism Services"],
    "Programming": ["Computer Programming (Oracle Database)"],
    "Electronics Assembly": ["Electronics Product and Assembly Servicing"],
    "Refrigeration and Air-Conditioning": ["Domestic Refrigeration and Air-Conditioning Servicing"],
}
TRACK_CLUSTERS = {"Academic": [c[1] for c in ACADEMIC_CLUSTERS], "TechPro": [c[1] for c in TECHPRO_CLUSTERS]}
CLUSTER_SPECS = {c[1]: c[2] for c in ACADEMIC_CLUSTERS + TECHPRO_CLUSTERS}
SPEC_TO_CLUSTER = {sp: c[1] for c in ACADEMIC_CLUSTERS + TECHPRO_CLUSTERS for sp in c[2]}
ACADEMIC_ELECTIVES = [sp for c in ACADEMIC_CLUSTERS for sp in c[2]]
TECHPRO_ELECTIVES = [sp for c in TECHPRO_CLUSTERS for sp in c[2]]
CORE_NAMES = [n for _c, n in CORE_SUBJECTS]
SPEC_GROUPS = [  # what a teacher can be specialized in (the exact system choices)
    ("Core subjects", CORE_NAMES),
    ("Academic clusters", TRACK_CLUSTERS["Academic"]),
    ("TechPro clusters", TRACK_CLUSTERS["TechPro"]),
    ("Academic electives", sorted(ACADEMIC_ELECTIVES)),
    ("TechPro electives", sorted(TECHPRO_ELECTIVES)),
]
CURRICULUM_NAMES = {n for _g, items in SPEC_GROUPS for n in items}
SPEC_SEP = "; "
# Quick Input lists the subjects of each cluster (a cluster with no listed subjects is its own subject).
QUICK_SPEC_GROUPS = [("Core subjects", CORE_NAMES)] + [
    (f"{tr}: {c[1]}", list(c[2]) or [c[1]])
    for tr, lst in (("Academic", ACADEMIC_CLUSTERS), ("TechPro", TECHPRO_CLUSTERS)) for c in lst]
# Older example data used free-text specializations; these are the ones the app itself created.
LEGACY_SPEC = {
    "Mathematics": CORE_NAMES[2], "English": CORE_NAMES[0], "Filipino": CORE_NAMES[0],
    "Science": CORE_NAMES[3], "Social Studies": CORE_NAMES[4], "Physical Education": "Sports, Health, and Wellness",
    "Research": CORE_NAMES[1], "Mathematics / Science": CORE_NAMES[2] + SPEC_SEP + CORE_NAMES[3],
    "TechPro - Food and Beverage": "Hospitality and Tourism", "TechPro - Bartending": "Hospitality and Tourism",
    "TechPro - Home Economics": "Hospitality and Tourism",
}
ADMIN_NAV = [  # number (not shown), title, subtitle, endpoint, endpoints that keep it highlighted, icon
    ("01", "Dashboard", "Progress and what to do next", "dashboard", ("dashboard",), "grid"),
    ("02", "Quick Input", "Sections, tracks, teachers and rooms", "quick_input", ("quick_input",), "bolt"),
    ("03", "Teacher Management", "Teachers and the subjects they teach", "teachers",
     ("teachers", "teacher_edit", "teacher_view"), "people"),
    ("04", "Section Management", "Sections, tracks and advisers", "sections", ("sections", "section_edit"), "school"),
    ("05", "Room Management", "Classrooms and laboratories", "auto_rooms", ("auto_rooms", "auto_room"), "door"),
    ("06", "Subject Management", "Tracks, clusters and subject hours", "curriculum", ("curriculum",), "book"),
    ("07", "Schedule Generator", "Validate, assign teachers and generate every class program", "auto_generate",
     ("auto_generate", "program", "entry_edit"), "calendar"),
    ("08", "Validation Center", "Conflicts and scheduling recommendations", "auto_conflicts",
     ("auto_conflicts", "auto_time"), "shieldcheck"),
    ("09", "Teacher Loading", "Change who teaches what by hand", "auto_loading",
     ("auto_loading", "auto_quals"), "clipboard"),
    ("11", "Notifications", "Requests and problem reports", "reports", ("reports", "signup_requests"), "bell"),
    ("12", "User Management", "Accounts, roles and audit trail", "users", ("users", "user_roles", "user_audit"), "shield"),
    ("13", "Reports and Printing", "Schedules and teaching-load reports", "auto_reports",
     ("auto_reports", "print_classes", "print_teachers"), "table"),
    ("14", "System Settings", "School year, timetable and shifts", "settings", ("settings",), "gear"),
]
NAV_SECTIONS = {"dashboard": "Overview", "auto_rooms": "School data", "auto_generate": "Scheduling",
                "reports": "Administration"}   # a small heading is printed above these items
TEACHER_NAV = [  # title, subtitle, endpoint, endpoints that keep it highlighted, icon
    ("My Schedule", "Your teaching program and load", "profile", ("profile",), "calendar"),
    ("Class Programs", "Programs of every section", "program", ("program", "entry_edit"), "table"),
    ("Notifications", "Messages for you", "notifications", ("notifications",), "bell"),
]
ACCOUNT_NAV = [  # shown in the account area of the sidebar, for every role
    ("My Profile", "account", ("account",), "people"),
    ("Account Settings", "account_settings", ("account_settings", "account_email_verify"), "gear"),
]
NAV_ICONS = {
    "bolt": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "school": '<path d="M3 21h18"/><path d="M5 21V10l7-5 7 5v11"/><path d="M10 21v-5h4v5"/><path d="M12 5V2"/>',
    "door": '<path d="M6 21V4a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v17"/><path d="M4 21h16"/><path d="M14 12h.01"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "book": '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
    "people": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
    "badge": '<rect x="4" y="3" width="16" height="18" rx="2"/><circle cx="12" cy="10" r="3"/><path d="M7 18c.8-2.2 2.7-3.5 5-3.5s4.2 1.3 5 3.5"/>',
    "clipboard": '<path d="M9 4H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2"/><rect x="9" y="2" width="6" height="4" rx="1"/><path d="M9 11h.01M13 11h3M9 15h.01M13 15h3"/>',
    "building": '<path d="M3 21V9l6-4v16"/><path d="M9 21V3h12v18"/><path d="M13 8h4M13 12h4M13 16h4M3 21h18"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><circle cx="12" cy="16" r="2.5"/>',
    "shieldcheck": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>',
    "table": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
}
SUBNAV = {  # pages that belong to one menu item are reached with tabs, not with extra menu items
    "loading": [("Teacher Load Summary", "auto_loading"), ("Qualifications", "auto_quals")],
    "schedule": [("Generate", "auto_generate")],
    "schedule_prog": [("Generate", "auto_generate"), ("Class Programs (edit by hand)", "program")],   # shown on the Class Programs page only
    "validation": [("Conflicts and Loading", "auto_conflicts"), ("Time Allocation", "auto_time")],
    "reports": [("Downloads and Summaries", "auto_reports"), ("Print Class Programs", "print_classes"),
                ("Print Teacher's Programs", "print_teachers")],
    "users": [("Accounts", "users"), ("Roles and Permissions", "user_roles"), ("Audit Trail", "user_audit")],
}
MAX_FAILS, LOCK_SECONDS = 5, 300
FAILS = {}  # (ip, username) -> (count, time of first failure)


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def nav_icon(key):
    return Markup('<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" '
                  'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                  + NAV_ICONS.get(key, "") + "</svg>")


def _nav_link(title, sub, endpoint, on, icon, badge=("", 0)):
    cls, n = badge
    pill = f'<span class="badge {cls}"{"" if n else " hidden"}>{n}</span>' if cls else ""
    return (f'<a class="mn{" on" if on else ""}" href="{url_for(endpoint)}" title="{title}"'
            f'{" aria-current=page" if on else ""}>'
            f'<span class="mn-ic">{nav_icon(icon)}</span>'
            f'<span class="mn-tx"><b>{title}{pill}</b>{f"<small>{sub}</small>" if sub else ""}</span></a>')


def main_nav(bell=0, pending=0):
    """The one navigation menu of the administrator (sidebar on desktop, drawer on phones)."""
    ep, out = request.endpoint, []
    badges = {"reports": ("nbadge", bell), "signup_requests": ("pbadge", pending)}
    for _n, title, sub, endpoint, group, icon in ADMIN_NAV:
        if endpoint in NAV_SECTIONS:
            out.append(f'<div class="navsep"><span>{NAV_SECTIONS[endpoint]}</span></div>')
        out.append(_nav_link(title, sub, endpoint, ep in group, icon, badges.get(endpoint, ("", 0))))
    return Markup("".join(out))


def teacher_nav(bell=0):
    """The one navigation menu of a teacher."""
    ep = request.endpoint
    return Markup("".join(
        _nav_link(t, sub, endpoint, ep in group, icon, ("nbadge", bell) if endpoint == "notifications" else ("", 0))
        for t, sub, endpoint, group, icon in TEACHER_NAV))


def account_nav():
    """Profile and settings, in the account area under the menu (the only place for them)."""
    ep = request.endpoint
    return Markup("".join(_nav_link(t, "", endpoint, ep in group, icon) for t, endpoint, group, icon in ACCOUNT_NAV))


def nav_back():
    """Where Back goes when the browser has no earlier page of this site."""
    ep = request.endpoint
    if g.get("user") and g.user["role"] == "admin":
        for _n, _t, _s, endpoint, group, _i in ADMIN_NAV:
            if ep in group:
                return url_for("dashboard") if ep == endpoint else url_for(endpoint)
        return url_for("dashboard")
    return url_for("home")


def subnav(group):
    """Tabs shown inside a menu item that has more than one page."""
    items = "".join(
        f'<a class="step{" on" if request.endpoint == ep else ""}" href="{url_for(ep)}">{label}</a>'
        for label, ep in SUBNAV[group])
    return Markup(f'<div class="steps noprint" role="navigation" aria-label="Pages in this section">{items}</div>')


app.jinja_env.globals.update(
    main_nav=main_nav, teacher_nav=teacher_nav, account_nav=account_nav, nav_icon=nav_icon, subnav=subnav, nav_back=nav_back, track_clusters=TRACK_CLUSTERS, spec_groups=SPEC_GROUPS,
    curriculum_names=CURRICULUM_NAMES, quick_groups=QUICK_SPEC_GROUPS, core_subjects=CORE_SUBJECTS, spec_sep=SPEC_SEP,
    days=DAYS, cats=CATS, kinds=KINDS, app_name=APP_NAME,
    buildings=BUILDINGS, floors=FLOORS, tracks=TRACKS, catname=CAT_SHORT,
    csrf_field=lambda: Markup(f'<input type="hidden" name="csrf" value="{csrf_token()}">'))


# --------------------------------------------------------------- database (PostgreSQL)
# The rest of the program writes SQL with "?" placeholders and reads rows by name or by position. This
# small layer turns that into PostgreSQL: placeholders, the reserved column name "end", INSERT OR
# IGNORE / INSERT OR REPLACE, and the id of a new row (cursor.lastrowid).
ID_TABLES = {"users", "sections", "classes", "signup_requests", "reports", "report_photos", "notifications",
             "reset_requests", "otp_codes", "subjects", "rooms", "room_types", "audit_log"}  # tables with a serial "id"
CONFLICT_KEYS = {"settings": ("k",), "files": ("k",), "loads": ("section_id", "subject_id")}


class Row:
    """A result row: row["name"], row[0], dict(row), row.keys() and unpacking all work."""
    __slots__ = ("_idx", "_vals")

    def __init__(self, idx, vals):
        self._idx, self._vals = idx, vals

    def __getitem__(self, k):
        return self._vals[self._idx[k] if isinstance(k, str) else k]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def keys(self):
        return list(self._idx)

    def get(self, k, default=None):
        return self._vals[self._idx[k]] if k in self._idx else default

    def __repr__(self):
        return f"Row({dict(zip(self._idx, self._vals))})"


def _row_factory(cursor):
    names = [c.name for c in (cursor.description or [])]
    idx = {n: i for i, n in enumerate(names)}
    return lambda values: Row(idx, tuple(values))


_STR = re.compile(r"('(?:[^']|'')*')")
_END = re.compile(r'(?<![\w"])end(?![\w"])')
_INSERT = re.compile(r"^\s*INSERT\s+(?:OR\s+(IGNORE|REPLACE)\s+)?INTO\s+(\w+)\s*(\(([^)]*)\))?", re.I)


def to_pg(sql, has_args):
    """Turn the "?" style SQL written in this program into PostgreSQL."""
    m = _INSERT.match(sql)
    mode = table = cols = None
    if m:
        mode, table = (m.group(1) or "").upper(), m.group(2).lower()
        cols = [c.strip() for c in (m.group(4) or "").split(",") if c.strip()]
    parts = _STR.split(sql)
    for i, part in enumerate(parts):
        if i % 2:  # a quoted string: only protect literal percent signs
            parts[i] = part.replace("%", "%%") if has_args else part
            continue
        if has_args:
            part = part.replace("%", "%%").replace("?", "%s")
        part = _END.sub('"end"', part)
        parts[i] = part
    out = "".join(parts)
    if m and mode:
        out = re.sub(r"(?i)INSERT\s+OR\s+(IGNORE|REPLACE)\s+INTO", "INSERT INTO", out, count=1)
    if mode == "IGNORE":
        out += " ON CONFLICT DO NOTHING"
    elif mode == "REPLACE":
        key = CONFLICT_KEYS[table]
        sets = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in key)
        out += f" ON CONFLICT ({', '.join(key)}) DO UPDATE SET {sets}"
    if m and table in ID_TABLES and "RETURNING" not in out.upper():
        out += " RETURNING id"
    return out, bool(m and table in ID_TABLES)


class PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur, self.lastrowid = cur, lastrowid

    def fetchone(self):
        return self._cur.fetchone() if self._cur.description else None

    def fetchall(self):
        return self._cur.fetchall() if self._cur.description else []

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def rowcount(self):
        return self._cur.rowcount


class PgConn:
    """The connection the program uses: execute(sql, args), commit(), rollback(), script(sql)."""

    def __init__(self, raw, pooled):
        self.raw, self.pooled = raw, pooled
        self.hold = False      # True while one multi-step job must be saved all-or-nothing
        self.failed = False

    def execute(self, sql, args=()):
        q, wants_id = to_pg(sql, bool(args))
        try:
            cur = self.raw.execute(q, tuple(args) if args else None)
            new_id = None
            if wants_id:
                row = cur.fetchone()
                new_id = row[0] if row else None
        except psycopg.Error:
            self.failed = True
            self.raw.rollback()  # PostgreSQL refuses further work in a failed transaction
            raise
        return PgCursor(cur, new_id)

    def executemany(self, sql, rows):
        """The same statement for many rows."""
        q, _ = to_pg(sql, True)
        try:
            with self.raw.cursor() as cur:
                cur.executemany(q, [tuple(r) for r in rows])
        except psycopg.Error:
            self.raw.rollback()
            raise

    def script(self, sql):
        """Several statements without parameters (table definitions)."""
        try:
            self.raw.execute(sql)
        except psycopg.Error:
            self.raw.rollback()
            raise

    def commit(self):
        if self.hold:          # inside generate_all(): saved once, at the very end
            return
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        if self.pooled:
            try:
                self.raw.rollback()  # never hand a half-finished transaction back to the pool
            except psycopg.Error:
                pass
            get_pool().putconn(self.raw)
        else:
            self.raw.close()


_pool = None
_pool_pid = None
_pool_lock = threading.Lock()


def get_pool():
    """One connection pool per worker process (created on first use, so it is safe with gunicorn)."""
    global _pool, _pool_pid
    if _pool is None or _pool_pid != os.getpid():
        with _pool_lock:
            if _pool is None or _pool_pid != os.getpid():
                pool = ConnectionPool(
                    DATABASE_URL, min_size=1, max_size=DB_POOL_MAX, open=False, name="scheduling",
                    kwargs={"autocommit": False, "row_factory": _row_factory, "prepare_threshold": None,
                            "connect_timeout": 15},  # prepare_threshold=None: works behind Neon's pooler
                    check=ConnectionPool.check_connection,  # Neon closes idle connections: test before use
                    max_idle=240, max_lifetime=1800)
                pool.open(wait=True, timeout=60)
                _pool, _pool_pid = pool, os.getpid()
    return _pool


def raw_connect():
    """A separate connection for start-up work (not from the pool). Call .close() when done."""
    return PgConn(psycopg.connect(DATABASE_URL, autocommit=False, row_factory=_row_factory,
                                  prepare_threshold=None, connect_timeout=15), False)


INIT_LOCK_KEY = 20260101


def acquire_init_lock():
    """Only one worker at a time may create tables and run the one-time set-up."""
    conn = psycopg.connect(DATABASE_URL, autocommit=True, prepare_threshold=None, connect_timeout=15)
    conn.execute("SELECT pg_advisory_lock(%s)", (INIT_LOCK_KEY,))
    return conn


def release_init_lock(conn):
    try:
        conn.execute("SELECT pg_advisory_unlock(%s)", (INIT_LOCK_KEY,))
    finally:
        conn.close()


def db():
    if "db" not in g:
        g.db = PgConn(get_pool().getconn(), True)
    return g.db


def query(sql, args=(), one=False):
    rows = db().execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows


def run(sql, args=()):
    conn = db()
    conn.execute(sql, args)
    conn.commit()


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def add_col(conn, table, col, decl):
    conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {decl}")


def init_db():
    conn = raw_connect()
    conn.script("""
    CREATE TABLE IF NOT EXISTS users(
        id SERIAL PRIMARY KEY, teacher_id TEXT UNIQUE, username TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL, role TEXT NOT NULL, category TEXT, password_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sections(
        id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, grade INTEGER NOT NULL, track TEXT);
    CREATE TABLE IF NOT EXISTS classes(
        id SERIAL PRIMARY KEY, section_id INTEGER NOT NULL, day TEXT NOT NULL,
        start TEXT NOT NULL, "end" TEXT NOT NULL, subject TEXT NOT NULL, teacher_id INTEGER);
    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS signup_requests(
        id SERIAL PRIMARY KEY, full_name TEXT NOT NULL, username TEXT NOT NULL,
        teacher_id TEXT NOT NULL, category TEXT NOT NULL, password_hash TEXT NOT NULL, created TEXT);
    CREATE TABLE IF NOT EXISTS files(
        k TEXT PRIMARY KEY, mime TEXT, data BYTEA, updated BIGINT);
    CREATE TABLE IF NOT EXISTS reports(
        id SERIAL PRIMARY KEY, user_id INTEGER, name TEXT, contact TEXT, message TEXT NOT NULL,
        photo BYTEA, photo_mime TEXT, created TEXT, is_read INTEGER DEFAULT 0,
        resolved INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS report_photos(
        id SERIAL PRIMARY KEY, report_id INTEGER NOT NULL, data BYTEA, mime TEXT);
    CREATE TABLE IF NOT EXISTS notifications(
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT, message TEXT NOT NULL,
        link TEXT, created TEXT, is_read INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS reset_requests(
        id SERIAL PRIMARY KEY, username TEXT NOT NULL, full_name TEXT NOT NULL,
        note TEXT, created TEXT);
    """)
    # Upgrades for databases made by earlier versions.
    add_col(conn, "reset_requests", "teacher_id", "TEXT")
    add_col(conn, "users", "email", "TEXT")
    add_col(conn, "signup_requests", "email", "TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS otp_codes(
        id SERIAL PRIMARY KEY, purpose TEXT, email TEXT, ref TEXT, code_hash TEXT,
        expires DOUBLE PRECISION, attempts INTEGER DEFAULT 0, created DOUBLE PRECISION, payload TEXT)""")
    for col, decl in [("item", "TEXT"), ("subject_area", "TEXT"), ("ancillary", "TEXT"),
                      ("official_time", "TEXT"), ("intervention_min", "INTEGER DEFAULT 0"),
                      ("ancillary_min", "INTEGER DEFAULT 0"), ("specialization", "TEXT"),
                      ("teaching_load", "TEXT"), ("max_sections", "INTEGER")]:
        add_col(conn, "users", col, decl)
    add_col(conn, "sections", "room", "TEXT")
    add_col(conn, "sections", "adviser_id", "INTEGER")
    add_col(conn, "sections", "building", "TEXT")
    add_col(conn, "sections", "floor", "TEXT")
    add_col(conn, "classes", "kind", "TEXT DEFAULT 'class'")
    add_col(conn, "classes", "code", "TEXT")
    conn.execute("UPDATE users SET category='MID' WHERE category='MEET'")
    # Give sections a building and floor from their room number (only where none is set yet).
    for nm, rm in SAMPLE_ROOMS.items():
        if conn.execute("SELECT 1 FROM sections WHERE name=? AND COALESCE(building,'')=''", (nm,)).fetchone():
            conn.execute("UPDATE sections SET room=?, building='1', floor=? WHERE name=?",
                         ("Room " + rm, rm[0], nm))
    for sid, rm in conn.execute("SELECT id, room FROM sections WHERE COALESCE(building,'')=''").fetchall():
        bld, flr = room_place(rm)
        if bld:
            conn.execute("UPDATE sections SET building=?, floor=? WHERE id=?", (bld, flr, sid))
    # Only two tracks exist now: TechPro and Academic (older data said "TVL").
    conn.execute("UPDATE sections SET track='TechPro' WHERE track LIKE 'TVL%'")
    conn.execute("UPDATE users SET specialization=replace(specialization,'TVL - ','TechPro - ') "
                 "WHERE specialization LIKE 'TVL - %'")
    conn.execute("UPDATE users SET subject_area=replace(subject_area,'TVL - ','TechPro - ') "
                 "WHERE subject_area LIKE '%TVL - %'")
    conn.commit()

    if not conn.execute("SELECT 1 FROM users").fetchone():
        ins = ("INSERT INTO users(teacher_id,username,full_name,role,category,password_hash,"
               "item,subject_area,ancillary,official_time,intervention_min,ancillary_min) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)")
        pw = generate_password_hash("teacher123")
        conn.execute(ins, ("ADMIN-001", "admin", "System Administrator", "admin", None,
                           generate_password_hash(ADMIN_INITIAL_PASSWORD), None, None, None, None, 0, 0))
        conn.execute(ins, ("T-1001", "msantos", "Maria Santos", "teacher", "G11", pw, "Teacher I",
                           "EC / MK / LCS / PKLP / Food and Beverage Operation",
                           "ADVISER (11-CHEF)", "6:00 AM - 3:00 PM", 60, 60))
        conn.execute(ins, ("T-1002", "jreyes", "Jose Reyes", "teacher", "G12", pw, "Teacher II",
                           "PR 2 / Bartending", "ADVISER (12-RECEPTIONIST)",
                           "12:00 NN - 7:00 PM", 60, 60))
        conn.execute(ins, ("T-1003", "adelacruz", "Ana Dela Cruz", "teacher", "MID", pw,
                           "Teacher III", "General Mathematics / General Science", "",
                           "6:00 AM - 3:00 PM", 60, 0))
        for uid, spec in ((2, "TechPro - Food and Beverage"), (3, "TechPro - Bartending"), (4, "Mathematics / Science")):
            conn.execute("UPDATE users SET specialization=? WHERE id=?", (spec, uid))
        conn.execute("INSERT INTO sections(name,grade,track,room,building,floor,adviser_id) "
                     "VALUES('11-Chef',11,'TechPro','Room 309','1','3',2)")
        conn.execute("INSERT INTO sections(name,grade,track,room,building,floor,adviser_id) "
                     "VALUES('12-Receptionist',12,'TechPro','Room 309','1','3',3)")
        cls = ("INSERT INTO classes(section_id,day,start,end,subject,code,kind,teacher_id) "
               "VALUES(?,?,?,?,?,?,?,?)")
        GS, GM = ("General Science", "GS"), ("General Mathematics", "GM")
        EC, MK = ("Effective Communication", "EC"), ("Mabisang Komunikasyon", "MK")
        LCS, PK = ("Life and Career Skills", "LCS"), ("Pag-aaral ng Kasaysayan at Lipunang Pilipino", "PKLP")
        FB = ("Food & Beverage Operation", "")
        MS, AD = 2, 4  # Maria Santos, Ana Dela Cruz
        chef = {
            "Monday": [("06:00", "07:00", GS, AD), ("07:00", "08:00", EC, MS), ("08:00", "09:00", PK, MS),
                       ("09:30", "10:30", LCS, MS), ("10:30", "11:30", GM, AD), ("11:30", "12:30", MK, MS)],
            "Tuesday": [("06:00", "07:00", GS, AD), ("07:00", "09:00", FB, MS), ("09:30", "10:30", EC, MS),
                        ("10:30", "11:30", GM, AD), ("11:30", "12:30", MK, MS)],
            "Wednesday": [("06:00", "07:00", LCS, MS), ("07:00", "09:00", FB, MS), ("09:30", "10:30", GS, AD),
                          ("10:30", "11:30", PK, MS), ("11:30", "12:30", GM, AD)],
            "Thursday": [("06:00", "07:00", LCS, MS), ("07:00", "09:00", FB, MS), ("09:30", "10:30", PK, MS),
                         ("10:30", "11:30", GM, AD), ("11:30", "12:30", GS, AD)],
            "Friday": [("06:00", "07:00", LCS, MS), ("07:00", "09:00", FB, MS), ("09:30", "10:30", PK, MS)],
        }
        for d, items in chef.items():
            for st, en, (subj, code), tid in items:
                conn.execute(cls, (1, d, st, en, subj, code or None, "class", tid))
            conn.execute(cls, (1, d, "09:00", "09:30", "RECESS", None, "recess", None))
        conn.execute(cls, (1, "Friday", "10:30", "11:30", "Homeroom", None, "homeroom", None))
        conn.execute(cls, (1, "Friday", "11:30", "12:30", "Intervention/Remediation", None,
                           "intervention", None))
        for d in DAYS:
            conn.execute(cls, (2, d, "13:00", "15:00", "Practical Research 2", "PR2", "class", 3))
            conn.execute(cls, (2, d, "15:00", "15:30", "RECESS", None, "recess", None))
            conn.execute(cls, (2, d, "15:30", "17:30", "Bartending", "BAR", "class", 3))
        conn.commit()

    if not conn.execute("SELECT 1 FROM users WHERE lower(username)='admin2'").fetchone():
        conn.execute("""INSERT INTO users(teacher_id,username,full_name,role,category,password_hash,
                         intervention_min,ancillary_min) VALUES(?,?,?,?,?,?,?,?)""",
                     ("ADMIN-002", "admin2", "System Administrator", "admin", None,
                      generate_password_hash(ADMIN_INITIAL_PASSWORD), 0, 0))
        conn.commit()
    conn.close()


def get_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        for r in query("SELECT k,v FROM settings"):
            cfg[r["k"]] = r["v"]
    except psycopg.Error:
        pass
    return cfg


@app.context_processor
def inject():
    cfg = get_cfg()
    u = g.get("user")
    pending = (query("SELECT COUNT(*) AS n FROM signup_requests", one=True)["n"]
               if u and u["role"] == "admin" else 0)
    logo = query("SELECT updated FROM files WHERE k='logo'", one=True)
    new_reports = admin_alerts() if u and u["role"] == "admin" else 0
    bell = 0
    if u:
        bell = (new_reports if u["role"] == "admin" else
                query("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND is_read=0",
                      (u["id"],), one=True)["n"])
    return {"cfg": cfg, "new_reports": new_reports, "bell": bell, "subjects_of": teacher_subjects_list,
            "tlabels": teacher_labels() if u else {}, "pending": pending,
            "has_logo": True, "custom_logo": bool(logo),
            "logo_url": url_for("logo", v=logo["updated"] if logo else 0),
            "year": time.strftime("%Y"),
            "approval": approval() if u and u["role"] == "admin" else None}


# ------------------------------------------------------------------- helpers
@app.before_request
def load_user():
    uid = session.get("uid")
    g.user = query("SELECT * FROM users WHERE id=?", (uid,), one=True) if uid else None
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400)


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def show_error(e):
    notes = {400: ("Request not accepted", "Your session may have expired. Go back, reload the page and try again."),
             403: ("Access not allowed", "Your account does not have permission to open this page."),
             404: ("Page not found", "The page you asked for does not exist."),
             413: ("File too large", "The file you sent is too large. Use smaller screenshots (3 MB each, 5 at most).")}
    title, text = notes[e.code]
    return render_template("error.html", title=title, text=text), e.code


@app.errorhandler(Exception)
def unexpected_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    ref = log_failure("request")
    try:
        conn = g.get("db")
        if conn:
            conn.rollback()
    except Exception:
        pass
    return render_template("error.html", title="Something went wrong",
                           text=f"The page could not be completed. Nothing was lost. Please try again; if it keeps "
                                f"happening, give this reference to the administrator: {ref}."), 500


def tomin(v):
    h, m = v.split(":")[:2]
    return int(h) * 60 + int(m)


@app.template_filter("tm")
def tm(v):
    h, m = divmod(int(v), 60)
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


@app.template_filter("t12")
def t12(v):
    return tm(tomin(v))


@app.template_filter("tmin")
def tmin(v):
    return tomin(v)


@app.template_filter("stamp12")
def stamp12(v):
    """Format a stored 'YYYY-MM-DD HH:MM' timestamp as normal Philippine time,
    e.g. 'Nov 8, 2026, 2:30 PM' instead of military time."""
    try:
        d = time.strptime((v or "").strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return v or ""
    h = (d.tm_hour % 12) or 12
    return (time.strftime("%b ", d) + str(d.tm_mday) + time.strftime(", %Y, ", d)
            + f"{h}:{d.tm_min:02d} " + ("AM" if d.tm_hour < 12 else "PM"))


def official_minutes(text):
    """Length of the official time, e.g. '6:00 AM - 3:00 PM' -> 540. None when unreadable."""
    found = re.findall(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM|NN)\b", text or "", re.I)
    if len(found) < 2:
        return None

    def conv(h, m, ap):
        h, m, ap = int(h), int(m or 0), ap.upper()
        h = h % 12 if ap == "AM" else (h % 12 + 12 if ap == "PM" else 12)
        return h * 60 + m
    span = conv(*found[1]) - conv(*found[0])
    return span if span > 0 else None


@app.template_filter("hrs")
def hrs(total):
    h, m = divmod(int(total), 60)
    parts = []
    if h:
        parts.append(f"{h} hr" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} min")
    return " ".join(parts) or "0 hrs"


def login_required(role=None):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            if not g.user:
                return redirect(url_for("login"))
            if role and g.user["role"] != role:
                abort(403)
            return f(*a, **k)
        return wrapper
    return deco


def grades_for(user):
    return GRADES.get(user["category"], [])


def to_int(v, lo=0, hi=600):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def admin_alerts():
    """What the administrator's bell counts: unread problem reports plus account
    requests that are still waiting for action."""
    return sum(query(sql, one=True)["n"] for sql in (
        "SELECT COUNT(*) AS n FROM reports WHERE is_read=0",
        "SELECT COUNT(*) AS n FROM signup_requests"))


def teacher_labels():
    """The number shown for each teacher everywhere in the system is the unique Teacher ID that the
    teacher typed in (T-4821 is shown as 4821), not a number counted by the system."""
    rows = query("SELECT id, teacher_id FROM users WHERE role='teacher' ORDER BY id")
    return {r["id"]: (re.sub(r"^T-", "", (r["teacher_id"] or "").strip(), flags=re.I) or str(r["id"])) for r in rows}


def ancillary_text(t):
    adv = query("SELECT name FROM sections WHERE adviser_id=? ORDER BY name", (t["id"],))
    return "ADVISER (" + ", ".join(a["name"].upper() for a in adv) + ")" if adv else "None"


def category_clash(tid, cat):
    """True when the teacher still has periods or an advisory outside the new grade level."""
    gs = GRADES[cat]
    marks = ",".join("?" * len(gs))
    return bool(query(f"""SELECT 1 FROM classes c JOIN sections s ON s.id=c.section_id
                          WHERE c.teacher_id=? AND s.grade NOT IN ({marks})""", (tid, *gs), one=True)
                or query(f"SELECT 1 FROM sections WHERE adviser_id=? AND grade NOT IN ({marks})",
                         (tid, *gs), one=True))


def sync_category(tid):
    """Keep a teacher's grade level matching what they are assigned: class periods and
    advisory in both Grade 11 and Grade 12 -> MID Teacher; only one grade level left ->
    back to G11 or G12. A teacher with no assignments at all keeps whatever the
    administrator set."""
    if not tid:
        return
    t = query("SELECT * FROM users WHERE id=? AND role='teacher'", (tid,), one=True)
    if not t:
        return
    gs = {r["grade"] for r in query(
        """SELECT s.grade FROM classes c JOIN sections s ON s.id=c.section_id
           WHERE c.teacher_id=? UNION SELECT grade FROM sections WHERE adviser_id=?""",
        (tid, tid))}
    new = "MID" if gs >= {11, 12} else ("G11" if gs == {11} else ("G12" if gs == {12} else None))
    if not new or new == t["category"]:
        return
    run("UPDATE users SET category=? WHERE id=?", (new, tid))
    old_auto = auto_official(t["category"])
    if old_auto and (t["official_time"] or "") == old_auto:  # class hours were automatic: follow the new level
        run("UPDATE users SET official_time=? WHERE id=?", (auto_official(new), tid))
    if new == "MID":
        msg = ("Your role was automatically changed to MID Teacher (Grades 11 and 12) "
               "because you were assigned in both grade levels.")
    else:
        msg = (f"Your role was automatically changed back to {CATS[new]} "
               "because you are now assigned in one grade level only.")
    notify(tid, "role", msg, url_for("profile"))


def maybe_promote_to_mid(tid, sec_grade):
    """When a G11-only or G12-only teacher is assigned a class in the other grade
    level, they now teach both levels, so their role becomes MID teacher
    (handles grades 11 and 12) and every entry in their program counts under
    that role. The teacher is notified of the change."""
    sync_category(tid)


def timeline(entries):
    """Turn entries into a Monday-Friday timetable.

    Rows run between every start/end time found in the entries. An entry that
    lasts across several rows becomes one tall cell (rowspan), like the printed
    program. Returns (rows, cells, rowmins).
    """
    pts = sorted({tomin(e["start"]) for e in entries} | {tomin(e["end"]) for e in entries})
    rows = list(zip(pts, pts[1:]))
    idx = {p: i for i, p in enumerate(pts)}
    cells = {d: [None] * len(rows) for d in DAYS}
    rowmins = [0] * len(rows)
    for e in sorted(entries, key=lambda r: (tomin(r["start"]), tomin(r["end"]))):
        i, j = idx[tomin(e["start"])], idx[tomin(e["end"])]
        if e["kind"] == "class":
            rowmins[i] += tomin(e["end"]) - tomin(e["start"])
        col = cells[e["day"]]
        if col[i] is None:
            span = j - i
            for k in range(i + 1, j):
                if col[k] is not None:
                    span = k - i
                    break
            col[i] = {"e": e, "span": span, "more": []}
            for k in range(i + 1, i + span):
                col[k] = "skip"
        else:  # overlapping data from an older version: keep it visible
            owner = col[i]
            if owner == "skip":
                k = i
                while col[k] == "skip":
                    k -= 1
                owner = col[k]
            owner["more"].append(e)
    return rows, cells, rowmins


def parse_minutes(text):
    """Minutes from '45', '1:00 PM - 2:30 PM' or '13:00-14:30'. None when it cannot be read."""
    text = (text or "").strip()
    if text.isdigit():
        return int(text)
    span = official_minutes(text)
    if span:
        return span
    f = re.match(r"^(\d{1,2}):(\d{2})\s*(?:-|to)\s*(\d{1,2}):(\d{2})$", text)
    if f:
        d = (int(f[3]) * 60 + int(f[4])) - (int(f[1]) * 60 + int(f[2]))
        return d if d > 0 else None
    return None


def minute_overrides(tid):
    r = query("SELECT v FROM settings WHERE k=?", (f"tmins_{tid}",), one=True)
    try:
        data = json.loads(r["v"]) if r else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def teacher_summary(t):
    auto = {d: 0 for d in DAYS}
    for r in query("SELECT day,start,end FROM classes WHERE teacher_id=? AND kind='class'", (t["id"],)):
        auto[r["day"]] += tomin(r["end"]) - tomin(r["start"])
    inter0, anc0 = t["intervention_min"] or 0, t["ancillary_min"] or 0
    ov = minute_overrides(t["id"])

    def pick(key, d, default):
        v = (ov.get(key) or {}).get(d)
        return v if isinstance(v, int) and 0 <= v <= 1440 else default
    per = {d: pick("teach", d, auto[d]) for d in DAYS}
    inter = {d: pick("inter", d, inter0) for d in DAYS}
    anc = {d: pick("anc", d, anc0) for d in DAYS}
    total = {d: per[d] + inter[d] + anc[d] for d in DAYS}
    # Teaching load = number of sections the teacher is assigned to (several subjects in one section count once).
    # It comes from the stored assignments, so it is right as soon as a teacher is assigned and never needs typing in.
    asg = query("""SELECT l.section_id, b.weekly_min FROM loads l
                   JOIN section_subjects ss ON ss.section_id=l.section_id AND ss.subject_id=l.subject_id
                   JOIN subjects b ON b.id=l.subject_id WHERE l.teacher_id=?""", (t["id"],))
    sec_ids = {r["section_id"] for r in asg}
    sec_ids |= {r["section_id"] for r in query("SELECT DISTINCT section_id FROM classes WHERE teacher_id=? AND kind='class'", (t["id"],))}
    loads, subs_n, asg_min = len(sec_ids), len(asg), sum(int(r["weekly_min"] or 0) for r in asg)
    official = official_minutes(t["official_time"])
    total_w = sum(total.values())
    # Weekly workload follows the official time when it is set (minutes per day x 5 days).
    work_w = official * len(DAYS) if official else total_w
    return dict(teach=per, teach_w=sum(per.values()), inter=inter, inter_w=sum(inter.values()),
                anc=anc, anc_w=sum(anc.values()), total=total, total_w=total_w, work_w=work_w,
                loads=loads, subs=subs_n, asg_w=asg_min, official=official,
                auto=dict(teach=auto, inter=inter0, anc=anc0))


# -------------------------------------------------------------------- auth
def name_key(text):
    return re.sub(r"[.,]", " ", (text or "").upper()).split()


def same_name(a, b):
    """Full names match when the first and last words agree (capital letters and the middle initial
    do not matter), so JUAN A. CRUZ and Juan Cruz are the same person."""
    x, y = name_key(a), name_key(b)
    if not x or not y:
        return False
    return (x[0] == y[0] and x[-1] == y[-1]) if len(x) > 1 and len(y) > 1 else x == y


@app.route("/", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("home"))
    sel = request.form.get("utype", "")
    sel = "ADMIN" if sel == "ADMIN" else "TEACHER"
    if request.method == "POST":
        f = request.form
        username = f.get("username", "").strip()
        num = re.sub(r"^\s*T-", "", f.get("teacher_num", "").strip(), flags=re.I)
        who = username.lower()
        key = (request.remote_addr, who)
        count, first = FAILS.get(key, (0, 0))
        if count and time.time() - first > LOCK_SECONDS:
            FAILS.pop(key, None)
            count = 0
        if count >= MAX_FAILS:
            flash("Too many failed sign-in attempts. Wait 5 minutes and try again.", "error")
            return render_template("login.html", types=USER_TYPES, sel=sel)
        if sel == "ADMIN":
            u = query("SELECT * FROM users WHERE lower(username)=lower(?) AND role='admin'", (username,), one=True)
            ok = bool(u and check_password_hash(u["password_hash"], f.get("password", "")))
        else:  # a teacher signs in with username, Employee ID (Teacher ID) and password
            u = query("""SELECT * FROM users WHERE lower(username)=lower(?) AND lower(teacher_id)=lower(?)
                         AND role='teacher'""", (username, f"T-{num}" if num.isdigit() else ""), one=True)
            ok = bool(u and check_password_hash(u["password_hash"], f.get("password", "")))
        if ok:
            FAILS.pop(key, None)
            session.clear()
            session.permanent = True
            session["uid"] = u["id"]
            audit_event(u, "Signed in")
            return redirect(url_for("home"))
        FAILS[key] = (count + 1, first if count else time.time())
        audit_event(None, "Failed sign-in", f"{sel.lower()}: {who[:40]}")
        flash("Sign-in failed. Check your " + ("username" if sel == "ADMIN" else "username, Employee ID") +
              " and password.", "error")
    return render_template("login.html", types=USER_TYPES, sel=sel)


MAX_PENDING = 100
SIGNUP_LOG = {}  # ip -> times of recent sign-up requests
RESET_LOG = {}  # ip -> times of recent forgot-password requests
MAX_RESETS = 200



# ---------------------------------------------------------------- Gmail verification (OTP)
GMAIL_RE = re.compile(r"[a-z0-9][a-z0-9._+-]{0,63}@gmail\.com")
OTP_MINUTES, OTP_TRIES, OTP_WAIT = 10, 5, 60
OTP_LOG = {}  # ip -> times of recent code requests


@app.context_processor
def _mail_helpers():
    return {"mask_email": lambda a: mask_email(a), "otp_minutes": OTP_MINUTES}


def valid_gmail(addr):
    return bool(GMAIL_RE.fullmatch((addr or "").strip().lower()))


def mask_email(addr):
    name, _, host = (addr or "").partition("@")
    return (name[:2] + "*" * max(1, len(name) - 2) + "@" + host) if name else ""


def mail_ready():
    brevo = bool((os.environ.get("BREVO_API_KEY") or "").strip())
    sender = bool((os.environ.get("MAIL_FROM") or "").strip())
    gmail = bool(
        os.environ.get("GMAIL_USER") and
        os.environ.get("GMAIL_APP_PASSWORD")
    )

    print("[MAIL CHECK] BREVO_API_KEY:", brevo)
    print("[MAIL CHECK] MAIL_FROM:", sender)
    print("[MAIL CHECK] GMAIL CONFIGURED:", gmail)

    return brevo or gmail


def send_mail(to, subject, text):
    """Send one plain-text email. Returns (True, '') or (False, reason).
    BREVO_API_KEY (+ MAIL_FROM)  -> Brevo over HTTPS, which also works on hosts that block SMTP.
    GMAIL_USER + GMAIL_APP_PASSWORD -> Gmail SMTP (needs a host that allows port 587)."""
    sender_name = get_cfg().get("school_name") or "Teacher Scheduling System"
    try:
        if os.environ.get("BREVO_API_KEY"):
            import urllib.request
            frm = os.environ.get("MAIL_FROM") or os.environ.get("GMAIL_USER") or ""
            body = json.dumps({"sender": {"name": sender_name, "email": frm},
                               "to": [{"email": to}], "subject": subject,
                               "textContent": text}).encode()
            req = urllib.request.Request(
                "https://api.brevo.com/v3/smtp/email", data=body, method="POST",
                headers={"api-key": os.environ["BREVO_API_KEY"], "content-type": "application/json",
                         "accept": "application/json"})
            urllib.request.urlopen(req, timeout=15).read()
            return True, ""
        if os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD"):
            import smtplib
            from email.message import EmailMessage
            msg = EmailMessage()
            msg["From"] = f"{sender_name} <{os.environ['GMAIL_USER']}>"
            msg["To"], msg["Subject"] = to, subject
            msg.set_content(text)
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"].replace(" ", ""))
                smtp.send_message(msg)
            return True, ""
        if os.environ.get("OTP_DEBUG"):  # testing only. The code is NEVER written to the log unless OTP_DEBUG=unsafe
            if os.environ.get("OTP_DEBUG") == "unsafe":
                print(f"[OTP_DEBUG] to {to}: {subject}\n{text}")
            else:
                print(f"[OTP_DEBUG] mail to {mask_email(to)}: {subject} (body hidden)")
            return True, ""
        return False, "Email sending is not set up yet. Please tell the administrator."
    except Exception as exc:  # network, login or provider problems
        print("Email could not be sent:", exc)
        return False, "The code could not be sent right now. Please try again in a moment."


def _otp_hash(code, email, purpose):
    import hashlib, hmac
    return hmac.new(app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key,
                    f"{purpose}|{email}|{code}".encode(), hashlib.sha256).hexdigest()


def send_otp(purpose, email, ref="", payload=None):
    """Create and email a 6-digit code. Returns (True, '') or (False, reason)."""
    if not mail_ready() and not os.environ.get("OTP_DEBUG"):
        return False, "Email sending is not set up yet. Please tell the administrator."
    now = time.time()
    ip_recent = [t for t in OTP_LOG.get(request.remote_addr, []) if now - t < 600]
    if len(ip_recent) >= 8:
        return False, "Too many codes requested from this device. Please wait 10 minutes."
    last = query("SELECT created FROM otp_codes WHERE purpose=? AND email=? ORDER BY id DESC",
                 (purpose, email), one=True)
    if last and now - last["created"] < OTP_WAIT:
        return False, f"Please wait {int(OTP_WAIT - (now - last['created'])) + 1} seconds before asking for a new code."
    code = f"{secrets.randbelow(1000000):06d}"
    ok, err = send_mail(email, "Your verification code",
                        f"Your verification code is {code}\n\nIt expires in {OTP_MINUTES} minutes. "
                        "If you did not ask for this code, you can ignore this email and nothing will change.")
    if not ok:
        return False, err
    run("DELETE FROM otp_codes WHERE purpose=? AND email=?", (purpose, email))
    run("INSERT INTO otp_codes(purpose,email,ref,code_hash,expires,created,payload) VALUES(?,?,?,?,?,?,?)",
        (purpose, email, str(ref), _otp_hash(code, email, purpose), now + OTP_MINUTES * 60, now,
         json.dumps(payload) if payload is not None else None))
    OTP_LOG[request.remote_addr] = ip_recent + [now]
    return True, ""


def check_otp(purpose, email, code):
    """Returns (payload_or_True, '') when right, or (None, reason). A wrong code uses one try."""
    import hmac
    row = query("SELECT * FROM otp_codes WHERE purpose=? AND email=? ORDER BY id DESC", (purpose, email), one=True)
    code = (code or "").strip().replace(" ", "")
    if not row:
        return None, "No code was sent yet. Ask for a new one."
    if time.time() > row["expires"]:
        run("DELETE FROM otp_codes WHERE id=?", (row["id"],))
        return None, "That code has expired. Ask for a new one."
    if row["attempts"] >= OTP_TRIES:
        run("DELETE FROM otp_codes WHERE id=?", (row["id"],))
        return None, "Too many wrong tries. Ask for a new code."
    if not hmac.compare_digest(row["code_hash"], _otp_hash(code, email, purpose)):
        run("UPDATE otp_codes SET attempts=attempts+1 WHERE id=?", (row["id"],))
        return None, "That code is not correct. Check the email and try again."
    run("DELETE FROM otp_codes WHERE id=?", (row["id"],))
    return (json.loads(row["payload"]) if row["payload"] else True), ""


def otp_wait(purpose, email):
    """Seconds left before another code may be requested (for the Resend button)."""
    last = query("SELECT created FROM otp_codes WHERE purpose=? AND email=? ORDER BY id DESC",
                 (purpose, email), one=True)
    return max(0, int(OTP_WAIT - (time.time() - last["created"])) + 1) if last else 0


def otp_resend(purpose, email, ref=""):
    """Send a new code with the same details as the one before. Returns (ok, message)."""
    row = query("SELECT payload, ref FROM otp_codes WHERE purpose=? AND email=? ORDER BY id DESC",
                (purpose, email), one=True)
    if not row:
        return False, "Your request expired. Please start again."
    ok, err = send_otp(purpose, email, ref=row["ref"] or ref,
                       payload=json.loads(row["payload"]) if row["payload"] else None)
    return (True, f"A new code was sent to {mask_email(email)}.") if ok else (False, err)


DECOY_EMAIL = "your.account@gmail.com"


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Forgot password: a 6-digit code goes to the Gmail saved on the account. The answer is the same whether or
    not the Employee ID exists, so the page cannot be used to find out which IDs are registered. Administrators
    no longer receive or process reset requests."""
    if request.method == "POST":
        f = request.form
        num = (f.get("teacher_num") or "").strip()
        now = time.time()
        recent = [t for t in RESET_LOG.get(request.remote_addr, []) if now - t < 600]
        if len(recent) >= 5:
            flash("Too many requests from this device. Please wait 10 minutes and try again.", "error")
            return render_template("forgot_password.html", v=f)
        if not num.isdigit() or len(num) > 9:
            flash("Enter your Employee ID number (digits only).", "error")
            return render_template("forgot_password.html", v=f)
        RESET_LOG[request.remote_addr] = recent + [now]
        u = query("SELECT * FROM users WHERE role='teacher' AND lower(teacher_id)=lower(?)", (f"T-{int(num)}",), one=True)
        if u and valid_gmail(u["email"]):
            email = u["email"].lower()
            if otp_wait("reset", email) > 0:  # a code went out a moment ago: go to the code page instead of an error
                session["otp_reset"] = {"email": email}
                flash("If that Employee ID has a Gmail saved, a code was already sent a moment ago. "
                      "Enter it below, or wait for the countdown to ask for a new one.", "ok")
                return redirect(url_for("forgot_verify"))
            ok, err = send_otp("reset", email, ref=u["id"], payload={"uid": u["id"]})
            if not ok:
                flash(err, "error")
                return render_template("forgot_password.html", v=f)
            session["otp_reset"] = {"email": email}
        else:
            session["otp_reset"] = {"email": DECOY_EMAIL, "decoy": True}   # looks the same; no code exists
        flash("If that Employee ID has a Gmail saved, a 6-digit code was sent to it. Enter the code below. "
              "If nothing arrives, ask the administrator to reset your password in Accounts.", "ok")
        return redirect(url_for("forgot_verify"))
    return render_template("forgot_password.html", v={})


@app.route("/forgot-password/verify", methods=["GET", "POST"])
def forgot_verify():
    pend = session.get("otp_reset")
    if not pend:
        return redirect(url_for("forgot_password"))
    email = pend["email"]
    if request.method == "POST":
        if pend.get("decoy"):
            flash("That code is not correct. Check the email and try again.", "error")
        elif request.form.get("action") == "resend":
            ok, msg = otp_resend("reset", email)
            flash(msg, "ok" if ok else "error")
        else:
            payload, err = check_otp("reset", email, request.form.get("code"))
            if not payload or payload is True:
                flash(err or "That code is not correct.", "error")
            else:
                session.pop("otp_reset", None)
                session["reset_ok"] = {"uid": payload["uid"], "until": time.time() + 600}
                return redirect(url_for("reset_new"))
    return render_template("verify_code.html", mode="reset", masked=mask_email(email), back=url_for("forgot_password"),
                           action=url_for("forgot_verify"), wait=0 if pend.get("decoy") else otp_wait("reset", email))


@app.route("/forgot-password/new", methods=["GET", "POST"])
def reset_new():
    ok = session.get("reset_ok")
    if not ok or time.time() > ok["until"]:
        session.pop("reset_ok", None)
        flash("Your code check expired. Please start again.", "error")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        pw = request.form.get("new", "")
        if len(pw) < 6:
            flash("The new password needs at least 6 characters.", "error")
        elif len(pw) > 128:
            flash("Use a password of 128 characters or fewer.", "error")
        elif pw != request.form.get("confirm"):
            flash("The new password and its confirmation do not match.", "error")
        else:
            u = query("SELECT * FROM users WHERE id=? AND role='teacher'", (ok["uid"],), one=True)
            session.pop("reset_ok", None)
            if not u:
                flash("That account is no longer available. Please contact the administrator.", "error")
                return redirect(url_for("login"))
            run("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), u["id"]))
            if u["email"]:
                run("DELETE FROM otp_codes WHERE purpose='reset' AND email=?", (u["email"].lower(),))
            audit_event(u, "Password reset with an email code")
            session["reset_done"] = True
            return redirect(url_for("reset_done"))
    return render_template("reset_new.html")


@app.route("/forgot-password/done")
def reset_done():
    """The confirmation page. It only opens right after a successful reset."""
    if not session.pop("reset_done", None):
        return redirect(url_for("login"))
    return render_template("reset_done.html")


def next_teacher_id():
    """The next Teacher ID in sequence, one past the highest number currently in use,
    so a newly approved teacher's ID continues the existing chronological order."""
    best = 1000
    for row in query("SELECT teacher_id FROM users WHERE role='teacher' AND teacher_id IS NOT NULL"):
        m = re.fullmatch(r"T-(\d+)", (row["teacher_id"] or "").strip())
        if m:
            best = max(best, int(m.group(1)))
    n = best + 1
    while query("SELECT 1 FROM users WHERE lower(teacher_id)=lower(?)", (f"T-{n}",), one=True):
        n += 1
    return f"T-{n}"


def suggest_teacher_num():
    """The next free Teacher ID number for the sign-up form: one past the highest ID used by an
    account or a waiting request, so new teachers follow the chronological order (1001, 1002, ...)."""
    best = 1000
    for tbl in ("users", "signup_requests"):
        for row in query(f"SELECT teacher_id FROM {tbl} WHERE teacher_id IS NOT NULL"):
            m = re.fullmatch(r"T-(\d+)", (row["teacher_id"] or "").strip())
            if m:
                best = max(best, int(m.group(1)))
    return best + 1


def id_taken(username, tid, skip_req=0):
    """True when the username or Teacher ID is used by an account or another waiting request."""
    return bool(
        query("SELECT 1 FROM users WHERE lower(username)=lower(?) OR lower(teacher_id)=lower(?)",
              (username, tid), one=True)
        or query("""SELECT 1 FROM signup_requests WHERE id!=?
                    AND (lower(username)=lower(?) OR lower(teacher_id)=lower(?))""",
                 (skip_req, username, tid), one=True))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """A teacher gives their name, Employee ID and Gmail, proves the Gmail with a 6-digit code, and then
    waits for the administrator to approve the account."""
    if g.user:
        return redirect(url_for("home"))
    f = request.form
    if request.method == "POST":
        name = clean(f.get("full_name"))
        email = (f.get("email") or "").strip().lower()
        pw = f.get("password", "")
        num = re.sub(r"^\s*T-", "", f.get("teacher_num", "").strip(), flags=re.I)
        tid = f"T-{int(num)}" if num.isdigit() and len(num) <= 9 and int(num) > 0 else ""
        user = (f.get("username") or "").strip()  # the teacher signs in with this username, the Employee ID and the password
        now = time.time()
        recent = [t for t in SIGNUP_LOG.get(request.remote_addr, []) if now - t < 600]
        err = None
        if len(recent) >= 5:
            err = "Too many requests from this device. Please wait 10 minutes and try again."
        elif len(name_key(name)) < 2:
            err = "Write your full name, for example JUAN A. CRUZ."
        elif not re.fullmatch(r"[A-Za-z0-9._-]{3,30}", user):
            err = "Choose a username of 3 to 30 characters: letters, numbers, dots, dashes or underscores."
        elif query("SELECT 1 FROM users WHERE lower(username)=lower(?)", (user,), one=True) \
                or query("SELECT 1 FROM signup_requests WHERE lower(username)=lower(?)", (user,), one=True):
            err = "That username is already taken. Choose another one."
        elif not tid:
            err = "Enter your Employee ID number (digits only), for example 1001."
        elif not valid_gmail(email):
            err = "Enter a valid Gmail address (it must end with @gmail.com). The code is sent there."
        elif len(pw) < 6:
            err = "The password needs at least 6 characters."
        elif pw != f.get("confirm"):
            err = "The password and its confirmation do not match."
        elif id_taken(user, tid):
            err = "That Employee ID is already in use or waiting for approval. Check it with the administrator."
        elif email_taken(email):
            err = "That Gmail address is already used by another account or request."
        elif query("SELECT COUNT(*) AS n FROM signup_requests", one=True)["n"] >= MAX_PENDING:
            err = "The request list is full. Please contact the administrator."
        if err:
            flash(err, "error")
            return render_template("signup.html", v=f)
        ok, err = send_otp("signup", email, payload={
            "full_name": name, "username": user, "teacher_id": tid, "email": email,
            "password_hash": generate_password_hash(pw)})
        if not ok:
            flash(err, "error")
            return render_template("signup.html", v=f)
        SIGNUP_LOG[request.remote_addr] = recent + [now]
        session["otp_signup"] = {"email": email}
        flash(f"We sent a 6-digit code to {mask_email(email)}.", "ok")
        return redirect(url_for("signup_verify"))
    return render_template("signup.html", v={})


def email_taken(email, skip_uid=0):
    email = (email or "").strip().lower()
    return bool(query("SELECT 1 FROM users WHERE lower(email)=? AND id!=?", (email, skip_uid), one=True)
                or query("SELECT 1 FROM signup_requests WHERE lower(email)=?", (email,), one=True))


@app.route("/signup/verify", methods=["GET", "POST"])
def signup_verify():
    pend = session.get("otp_signup")
    if not pend:
        return redirect(url_for("signup"))
    email = pend["email"]
    if request.method == "POST":
        if request.form.get("action") == "resend":
            ok, msg = otp_resend("signup", email)
            flash(msg, "ok" if ok else "error")
        else:
            d, err = check_otp("signup", email, request.form.get("code"))
            if not d or d is True:
                flash(err or "That code is not correct.", "error")
            elif id_taken(d["username"], d["teacher_id"]) or email_taken(email):
                session.pop("otp_signup", None)
                flash("That Employee ID or Gmail was taken while you were verifying. Please start again.", "error")
                return redirect(url_for("signup"))
            else:
                run("""INSERT INTO signup_requests(full_name,username,teacher_id,category,password_hash,email,created)
                       VALUES(?,?,?,?,?,?,?)""", (d["full_name"], d["username"], d["teacher_id"], "G11",
                                                   d["password_hash"], d["email"], ph_stamp()))
                session.pop("otp_signup", None)
                flash("Your Gmail is verified and your request was sent. You can sign in once the "
                      "administrator approves your account.", "ok")
                return redirect(url_for("login"))
    return render_template("verify_code.html", mode="signup", masked=mask_email(email), back=url_for("signup"),
                           action=url_for("signup_verify"), wait=otp_wait("signup", email))


TEMP_PASSWORD = "teacher123"  # what a reset gives the teacher; they change it in Settings
SHIFT_OF = {"G11": "AM", "G12": "PM", "MID": "MID"}  # a teacher's class hours follow the grade level handled


def auto_official(cat, tt=None):
    """Official time that follows the grade level: Grade 11 = AM shift, Grade 12 = PM shift,
    MID teacher = MID shift. Empty when that shift is not in the timetable."""
    tt = tt or get_tt()
    name = SHIFT_OF.get(cat)
    return shift_hours(tt, name) if name in tt else ""


def auto_hm(cat, tt=None):
    """The same time as 24-hour start and end for the time pickers, e.g. ('06:00', '12:30')."""
    return official_range(auto_official(cat, tt))


def random_password(n=8):
    import secrets, string
    alpha = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alpha) for _ in range(n))


def request_reply(ok, message, status):
    """Answer an approve / reject action. The page's own script asks for JSON and updates the card in
    place; a plain form post (no script) gets the usual flash message and redirect. Failures use an
    error status code so they are not written to the audit trail as completed actions."""
    if request.headers.get("X-Requested-With") == "fetch":
        body = {"ok": ok, "status": status, "message": message,
                "pending": query("SELECT COUNT(*) AS n FROM signup_requests", one=True)["n"],
                "bell": admin_alerts()}
        resp = make_response(json.dumps(body), 200 if ok else (409 if status == "gone" else 400))
        resp.headers["Content-Type"] = "application/json"
        resp.headers["Cache-Control"] = "no-store"
        return resp
    flash(message, "ok" if ok else "error")
    return redirect(url_for("reports"))


@app.route("/admin/requests", methods=["GET", "POST"])
@login_required("admin")
def signup_requests():
    if request.method == "POST":
        f = request.form
        r = query("SELECT * FROM signup_requests WHERE id=?", (f.get("rid", type=int),), one=True)
        if not r:
            return request_reply(False, "That request was already handled.", "gone")
        if f.get("action") == "reject":
            run("DELETE FROM signup_requests WHERE id=?", (r["id"],))
            return request_reply(True, f"Request from {r['full_name']} was rejected and removed.", "rejected")
        name, cat = clean(f.get("full_name")), f.get("category", "")
        num = (f.get("teacher_num") or "").strip()
        err = None
        tid = ""
        if not (name and num) or cat not in CATS:
            err = "Enter the name and Teacher ID number and choose a grade level."
        elif not num.isdigit() or len(num) > 9 or int(num) < 1:
            err = "The Teacher ID number must be a whole number."
        else:
            tid = f"T-{int(num)}"
            if id_taken(r["username"], tid, skip_req=r["id"]):
                err = "That Teacher ID or username is already in use."
        if err:
            return request_reply(False, err, "error")
        try:
            run("""INSERT INTO users(teacher_id,username,full_name,role,category,password_hash,email,
                                     official_time,intervention_min,ancillary_min) VALUES(?,?,?,?,?,?,?,?,0,0)""",
                (tid, r["username"], name, "teacher", cat, r["password_hash"], r["email"] or None,
                 auto_official(cat)))
        except IntegrityError:
            return request_reply(False, "That Teacher ID or username is already in use.", "error")
        run("DELETE FROM signup_requests WHERE id=?", (r["id"],))
        return request_reply(True, f"{name} was approved and added to the teachers list. They sign in with "
                                   f"their username and Employee ID {tid[2:]}. Their class hours follow the grade level "
                                   "automatically; set their subjects in Teacher Management.", "approved")
    return redirect(url_for("reports"))


@app.route("/logout")
def logout():
    if g.get("user"):
        audit_event(g.user, "Signed out")
    session.clear()
    return redirect(url_for("login"))


@app.route("/home")
@login_required()
def home():
    return redirect(url_for("dashboard" if g.user["role"] == "admin" else "profile"))


@app.route("/account")
@login_required()
def account():
    """Profile: the account's own visible details. Read-only; see Settings to change anything."""
    teacher = g.user["role"] == "teacher"
    return render_template("account.html",
                           summ=teacher_summary(g.user) if teacher else None,
                           ancillary=ancillary_text(g.user) if teacher else "")


@app.route("/account/settings", methods=["GET", "POST"])
@login_required()
def account_settings():
    """Settings: edit name/username and change password."""
    if request.method == "POST":
        f = request.form
        if f.get("action") == "email":
            email = (f.get("email") or "").strip().lower()
            if not check_password_hash(g.user["password_hash"], f.get("current", "")):
                flash("The current password is incorrect.", "error")
            elif not valid_gmail(email):
                flash("Enter a valid Gmail address (it must end with @gmail.com).", "error")
            elif email_taken(email, g.user["id"]):
                flash("That Gmail address is already used by another account.", "error")
            else:
                ok, err = send_otp("email", email, ref=g.user["id"], payload={"uid": g.user["id"]})
                if ok:
                    session["otp_email"] = {"email": email}
                    flash(f"We sent a 6-digit code to {mask_email(email)}.", "ok")
                    return redirect(url_for("account_email_verify"))
                flash(err, "error")
            return redirect(url_for("account_settings"))
        if f.get("action") == "profile":
            name = clean(f.get("full_name"))
            user = clean(f.get("username"), 40)
            if not (name and user):
                flash("Enter your name and username.", "error")
            elif not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", user):
                flash("The username needs 3 to 40 letters, numbers, dots, dashes or underscores "
                      "(no spaces).", "error")
            elif query("SELECT 1 FROM users WHERE lower(username)=lower(?) AND id!=?",
                       (user, g.user["id"]), one=True):
                flash("That username is already in use.", "error")
            else:
                run("UPDATE users SET full_name=?, username=? WHERE id=?", (name, user, g.user["id"]))
                flash("Profile updated.", "ok")
            return redirect(url_for("account_settings"))
        if not check_password_hash(g.user["password_hash"], f.get("current", "")):
            flash("The current password is incorrect.", "error")
        elif len(f.get("new", "")) < 6:
            flash("The new password needs at least 6 characters.", "error")
        elif f.get("new") != f.get("confirm"):
            flash("The new password and its confirmation do not match.", "error")
        else:
            run("UPDATE users SET password_hash=? WHERE id=?",
                (generate_password_hash(f["new"]), g.user["id"]))
            flash("Password changed.", "ok")
        return redirect(url_for("account_settings"))
    return render_template("account_settings.html")


@app.route("/account/email/verify", methods=["GET", "POST"])
@login_required()
def account_email_verify():
    pend = session.get("otp_email")
    if not pend:
        return redirect(url_for("account_settings"))
    email = pend["email"]
    if request.method == "POST":
        if request.form.get("action") == "resend":
            ok, msg = otp_resend("email", email)
            flash(msg, "ok" if ok else "error")
        else:
            d, err = check_otp("email", email, request.form.get("code"))
            if not d or d is True or d.get("uid") != g.user["id"]:
                flash(err or "That code is not correct.", "error")
            else:
                run("UPDATE users SET email=? WHERE id=?", (email, g.user["id"]))
                session.pop("otp_email", None)
                audit_event(g.user, "Gmail verified and saved")
                flash("Your Gmail was verified and saved. It is used for password reset codes.", "ok")
                return redirect(url_for("account_settings"))
    return render_template("verify_code.html", mode="email", masked=mask_email(email), back=url_for("account_settings"),
                           action=url_for("account_email_verify"), wait=otp_wait("email", email))


def ph_time():
    """The current time as a struct_time in Philippines time (GMT+8), regardless of the
    server's own timezone, since this school is in the Philippines."""
    return time.gmtime(time.time() + 8 * 3600)


def ph_stamp():
    """The current Philippines-time timestamp, formatted the way it is stored in the database."""
    return time.strftime("%Y-%m-%d %H:%M", ph_time())


def today_text():
    d = ph_time()
    return time.strftime("%B ", d) + str(d.tm_mday) + time.strftime(", %Y", d)


def notify(uid, kind, message, link=None):
    """Tell a teacher something changed. Admin accounts never receive these."""
    if not uid:
        return
    u = query("SELECT role FROM users WHERE id=?", (uid,), one=True)
    if not u or u["role"] != "teacher":
        return
    actor = g.user["full_name"] if g.get("user") and g.user["role"] == "admin" else None
    if actor:
        message = f"{message} (By: {actor})"
    run("INSERT INTO notifications(user_id,kind,message,link,created,is_read) VALUES(?,?,?,?,?,0)",
        (uid, kind, message, link, ph_stamp()))
    g.setdefault("_notified", set()).add(uid)
    run("""DELETE FROM notifications WHERE user_id=? AND id NOT IN
           (SELECT id FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100)""", (uid, uid))


def notify_program(uid):
    """Generic 'your program changed' notice. Repeated edits refresh one unread notice
    instead of stacking up, and a more specific notice made in the same request wins."""
    if uid in g.get("_notified", set()):
        return
    row = query("SELECT id FROM notifications WHERE user_id=? AND kind='program' AND is_read=0",
                (uid,), one=True)
    if row:
        run("UPDATE notifications SET created=? WHERE id=?", (ph_stamp(), row["id"]))
        g.setdefault("_notified", set()).add(uid)
    else:
        notify(uid, "program", "The administrator updated your Teacher's Program.", url_for("profile"))


def sec_label(sec):
    return sec["name"]


def short_section(name):
    """'11-Chef' -> 'Chef' (the grade prefix is added again when saving)."""
    return re.sub(r"^\s*1[12]\s*[-\u2013]\s*", "", name or "").strip()


def full_section(grade, name):
    base = short_section(name)
    return f"{grade}-{base}" if base else ""


app.jinja_env.filters["shortsec"] = lambda v: short_section(v)


def dur_options(cur, hi=600):
    """Choices for a per-day duration: every 5 min up to 3 hrs, then every 15 min."""
    vals = set(range(0, 181, 5)) | set(range(180, hi + 1, 15))
    try:
        vals.add(int(cur or 0))
    except (TypeError, ValueError):
        vals.add(0)
    return sorted(v for v in vals if v <= max(hi, int(cur or 0)))


def dur_text(v):
    h, m = divmod(int(v), 60)
    parts = []
    if h:
        parts.append(f"{h} hr" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} min")
    return " ".join(parts) or "0 min"


def official_range(text):
    """'6:00 AM - 3:00 PM' -> ('06:00', '15:00') for the time pickers."""
    found = re.findall(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM|NN)\b", text or "", re.I)
    if len(found) < 2:
        return ("", "")

    def conv(h, m, ap):
        h, m, ap = int(h), int(m or 0), ap.upper()
        h = h % 12 if ap == "AM" else (h % 12 + 12 if ap == "PM" else 12)
        return f"{h % 24:02d}:{m:02d}"
    return (conv(*found[0]), conv(*found[1]))


app.jinja_env.globals["dur_options"] = dur_options
app.jinja_env.filters["durtxt"] = dur_text
app.jinja_env.filters["otimes"] = official_range


def official_display(text):
    """'6:00 AM - 12:30 PM' for printing: the time range only, never minutes or hours. The stored value and the
    scheduling calculations are untouched."""
    a, b = official_range(text)
    if not a:
        return text or ""
    return tm(tomin(a)) + " \u2013 " + tm(tomin(b))


app.jinja_env.filters["official_range"] = official_display


def touch(kind, ident):
    """Remember the date the admin last changed a class program or a teacher's program."""
    if ident:
        run("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (f"upd_{kind}_{ident}", today_text()))
        if kind == "teacher":
            notify_program(ident)


def touch_teacher_of_entry(tid):
    touch("teacher", tid)


def touch_recess_teachers(sid):
    """A recess change also shows on the Teacher's Program of everyone teaching that section."""
    for r in query("SELECT DISTINCT teacher_id FROM classes WHERE section_id=? AND teacher_id IS NOT NULL", (sid,)):
        touch("teacher", r["teacher_id"])


def stamp(kind, ident):
    """The date the admin last changed the program, or None when it was never updated."""
    r = query("SELECT v FROM settings WHERE k=?", (f"upd_{kind}_{ident}",), one=True)
    return {"label": "DATE UPDATED", "date": r["v"]} if r else None


# ---------------------------------------------------------- teacher's program
def teacher_data(t):
    """Everything one Teacher's Program page needs."""
    rows = [dict(r) for r in query(
        """SELECT c.*, s.name AS section_name FROM classes c
           JOIN sections s ON s.id=c.section_id WHERE c.teacher_id=? AND c.kind='class'""", (t["id"],))]
    secids = sorted({r["section_id"] for r in rows})
    if secids:  # show the recess of the sections this teacher handles
        seen = set()
        for r in query(f"""SELECT c.*, s.name AS section_name FROM classes c
                           JOIN sections s ON s.id=c.section_id
                           WHERE c.kind='recess' AND c.section_id IN ({','.join('?' * len(secids))})""",
                       secids):
            key = (r["day"], r["start"], r["end"])
            if key not in seen:
                seen.add(key)
                rows.append(dict(r))
    trows, cells, rowmins = timeline(rows)
    return dict(t=t, rows=trows, cells=cells, rowmins=rowmins, subjects=teacher_subjects_list(t),
                summ=teacher_summary(t), ancillary=ancillary_text(t),
                stamp=stamp("teacher", t["id"]))


def show_teacher(t):
    pick = (query("SELECT id, full_name, teacher_id FROM users WHERE role='teacher' "
                  "ORDER BY full_name") if g.user["role"] == "admin" else [])
    return render_template("profile.html", t=t, d=teacher_data(t), pick=pick)


@app.route("/profile")
@login_required("teacher")
def profile():
    return show_teacher(g.user)


@app.route("/teacher/<int:tid>")
@login_required("admin")
def teacher_view(tid):
    t = query("SELECT * FROM users WHERE id=? AND role='teacher'", (tid,), one=True)
    if not t:
        abort(404)
    return show_teacher(t)


# -------------------------------------------------------------- class program
def class_data(cur, labels=None):
    """Everything one Class Program page needs."""
    labels = labels or teacher_labels()
    rows = [dict(r) for r in query(
        """SELECT c.*, u.full_name AS teacher_name FROM classes c
           LEFT JOIN users u ON u.id=c.teacher_id WHERE c.section_id=?""", (cur["id"],))]
    adviser = None
    if cur["adviser_id"]:
        a = query("SELECT full_name FROM users WHERE id=?", (cur["adviser_id"],), one=True)
        adviser = a["full_name"] if a else None
    legend = sorted({(r["code"], r["subject"]) for r in rows if r["kind"] == "class" and r["code"]})
    me = g.get("user")
    only_me = bool(me and me["role"] == "teacher")  # teachers see only their own periods named
    for r in rows:
        r["teacher_label"] = labels.get(r["teacher_id"]) if r.get("teacher_id") else None
        r["other"] = bool(only_me and r.get("teacher_id") and r["teacher_id"] != me["id"])
        if r["other"]:
            r["teacher_label"] = r["teacher_name"] = None
    # Periods with no teacher yet show "Teacher 1", "Teacher 2", ...: one number per subject, counted in the order
    # the subjects first appear in the week. The number is replaced by the teacher's name once one is assigned.
    order = {}
    for r in sorted((x for x in rows if x["kind"] == "class"),
                    key=lambda x: (tomin(x["start"]), DAYS.index(x["day"]) if x["day"] in DAYS else 9)):
        order.setdefault(r["code"] or r["subject"], len(order) + 1)
    for r in rows:
        r["teacher_ph"] = (f"Teacher {order[r['code'] or r['subject']]}"
                           if r["kind"] == "class" and not r.get("teacher_id") else None)
    tlegend = sorted({(r["teacher_label"], r["teacher_name"]) for r in rows
                      if r["kind"] == "class" and r["teacher_label"]})
    trows, cells, _ = timeline(rows)
    return dict(cur=cur, rows=trows, cells=cells, adviser=adviser, legend=legend, tlegend=tlegend,
                stamp=stamp("section", cur["id"]))


@app.route("/program")
@login_required()
def program():
    u = g.user
    if u["role"] == "admin":
        secs = [dict(r, is_adv=0) for r in sched_secs()]
    else:
        # Teachers only see the class programs they are actually assigned to:
        # sections where they teach a period, or sections they advise.
        # Sections they advise are labelled (My Advisory) but keep their normal order.
        secs = query("""SELECT DISTINCT s.*, (s.adviser_id=?) AS is_adv FROM sections s
                        WHERE s.adviser_id=? OR EXISTS(
                            SELECT 1 FROM classes c WHERE c.section_id=s.id AND c.teacher_id=?)
                        ORDER BY s.grade, s.name""", (u["id"], u["id"], u["id"]))
    total = len(secs)
    grades = sorted({x["grade"] for x in secs})
    grade = request.args.get("grade", type=int)
    if grade not in grades:
        grade = None
    if grade:
        secs = [x for x in secs if x["grade"] == grade]
    tracks = [t for t in TRACKS if any(x["track"] == t for x in secs)]
    track = request.args.get("track", "")
    if track not in tracks:
        track = ""
    if track:
        secs = [x for x in secs if x["track"] == track]
    gtotal = len(secs)
    q = request.args.get("q", "").strip()[:60]
    if q:  # section name, track or room number: every word must appear
        words = q.lower().split()

        def hit(x):
            hay = f"{x['name']} {x['track'] or ''} {x['room'] or ''}".lower()
            flat = re.sub(r"\s+", "", hay)
            return all(w in hay or w in flat for w in words)
        secs = [x for x in secs if hit(x)]
    sid = request.args.get("section", type=int)
    cur = next((x for x in secs if x["id"] == sid), secs[0] if secs else None)
    d = class_data(cur) if cur else None
    editing = u["role"] == "admin" and request.args.get("edit") == "1"
    docs = []
    if secs and not editing and (u["role"] == "admin" or q):
        labels = teacher_labels()
        docs = [class_data(x, labels) for x in secs]
    teachers = (query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name")
                if editing else [])
    return render_template("program.html", secs=secs, cur=cur, d=d, teachers=teachers,
                           q=q, total=total, gtotal=gtotal, editing=editing, docs=docs,
                           grade=grade, grades=grades, ptracks=tracks, ptrack=track)


def picked_ids():
    return {int(x) for x in request.args.getlist("id") if x.isdigit()}


@app.route("/admin/print/classes")
@login_required("admin")
def print_classes():
    secs = sched_secs()
    ids = picked_ids()
    if not ids:
        items = [(x["id"], x["name"], x["room"] or "",
                  " ".join(str(v or "") for v in (x["name"], x["room"], "grade", x["grade"], x["track"], x["cluster"],
                                                  x["shift"])).lower())
                 for x in secs]
        return render_template("printpick.html", items=items, title="Choose class programs to print",
                               back_url=url_for("program"), searchable=True, noun="class program",
                               hint="Search section, room, track or cluster&hellip;")
    labels = teacher_labels()
    docs = [class_data(x, labels) for x in secs if x["id"] in ids]
    return render_template("printall.html", kind="class", docs=docs,
                           title="Print selected class programs", back_url=url_for("print_classes"))


@app.route("/admin/print/teachers")
@login_required("admin")
def print_teachers():
    rows = query("SELECT * FROM users WHERE role='teacher' ORDER BY id")
    ids = picked_ids()
    if not ids:
        labels = teacher_labels()
        items = [(t["id"], f"{labels.get(t['id'], 'Teacher')} - {t['full_name']}",
                  "", f"{t['full_name']} {t['teacher_id'] or ''} {labels.get(t['id'], '')}".lower())   # one ID only; search still matches T-1001
                 for t in rows]
        return render_template("printpick.html", items=items, title="Choose teachers' programs to print",
                               back_url=url_for("teachers"), searchable=True)
    docs = [teacher_data(t) for t in rows if t["id"] in ids]
    return render_template("printall.html", kind="teacher", docs=docs,
                           title="Print selected teachers' programs", back_url=url_for("print_teachers"))


# --------------------------------------------------------------- admin tools
def overlaps(a1, a2, b1, b2):
    return a1 < b2 and b1 < a2


def valid_time(v):
    try:
        h, m = v.split(":")[:2]
        return 0 <= int(h) < 24 and 0 <= int(m) < 60
    except (ValueError, AttributeError):
        return False


def normalize(kind, subj, tid):
    """Recess, homeroom and intervention periods have no teacher and a standard label."""
    if kind != "class":
        return subj or KIND_LABEL[kind], None
    return subj, tid


def check_entry(sec, day, st, en, subj, tid, kind, exclude=0):
    """Return an error message, or None when the entry can be saved."""
    if (not sec or day not in DAYS or kind not in KINDS or not subj
            or not (valid_time(st) and valid_time(en))):
        return "Complete all fields before saving."
    if tomin(en) <= tomin(st):
        return "End time must be later than start time."
    t = None
    if tid:
        t = query("SELECT * FROM users WHERE id=? AND role='teacher'", (tid,), one=True)
        if not t:
            return "Selected teacher was not found."
        # Note: a teacher assigned outside their current grade level is no longer
        # blocked here; entry_add/entry_edit auto-promotes them to MID instead.
    for r in query("""SELECT c.*, s.name AS sname FROM classes c
                      JOIN sections s ON s.id=c.section_id
                      WHERE c.day=? AND c.id!=? AND (c.section_id=? OR c.teacher_id=?)""",
                   (day, exclude, sec["id"], tid)):
        if overlaps(tomin(st), tomin(en), tomin(r["start"]), tomin(r["end"])):
            who = ("This section already has" if r["section_id"] == sec["id"]
                   else f"{t['full_name']} already teaches")
            return (f"Time conflict on {day}: {who} {r['subject']} ({r['sname']}), "
                    f"{t12(r['start'])} to {t12(r['end'])}.")
    return None


def time_note(mins, ndays, kind, tid):
    """Plain-language time summary shown right after a period is saved."""
    note = f"Time: {hrs(mins)} per day"
    if ndays > 1:
        note += f" x {ndays} days = {hrs(mins * ndays)} per week"
    note += "."
    if kind == "class" and tid:
        t = query("SELECT * FROM users WHERE id=?", (tid,), one=True)
        if t:
            sm = teacher_summary(t)
            note += (f" {teacher_labels().get(tid, 'Teacher')} ({t['full_name']}) now has "
                     f"{hrs(sm['teach_w'])} of teaching per week and {hrs(sm['work_w'])} "
                     "of weekly workload.")
    return note


@app.post("/admin/entry")
@login_required("admin")
def entry_add():
    f = request.form
    sid = f.get("section_id", type=int)
    sec = query("SELECT * FROM sections WHERE id=?", (sid,), one=True)
    kind = f.get("kind", "class")
    days = [d for d in DAYS if d in f.getlist("day")]
    st, en = f.get("start", ""), f.get("end", "")
    code = f.get("code", "").strip() or None
    if kind not in KINDS:
        flash("Choose a valid period type.", "error")
        return redirect(url_for("program", section=sid, edit=1))
    subj, tid = normalize(kind, f.get("subject", "").strip(), f.get("teacher_id", type=int))
    if not days:
        flash("Select at least one day.", "error")
        return redirect(url_for("program", section=sid, edit=1))
    for d in days:
        err = check_entry(sec, d, st, en, subj, tid, kind)
        if err:
            flash(err + " Nothing was saved.", "error")
            return redirect(url_for("program", section=sid, edit=1))
    for d in days:
        run("INSERT INTO classes(section_id,day,start,end,subject,code,kind,teacher_id) "
            "VALUES(?,?,?,?,?,?,?,?)", (sid, d, st, en, subj, code, kind, tid))
    if tid:
        maybe_promote_to_mid(tid, sec["grade"])
        notify(tid, "assigned", f"You were assigned to {sec_label(sec)}: {subj}, "
               f"{', '.join(d[:3] for d in days)}, {t12(st)} to {t12(en)}.", url_for("program", section=sid))
    touch("section", sid)
    touch_teacher_of_entry(tid)
    if kind == "recess":
        touch_recess_teachers(sid)
    flash(f"Saved for {len(days)} day" + ("s. " if len(days) != 1 else ". ")
          + time_note(tomin(en) - tomin(st), len(days), kind, tid), "ok")
    return redirect(url_for("program", section=sid, edit=1))


@app.route("/admin/entry/<int:eid>/edit", methods=["GET", "POST"])
@login_required("admin")
def entry_edit(eid):
    e = query("SELECT * FROM classes WHERE id=?", (eid,), one=True)
    if not e:
        abort(404)
    sec = query("SELECT * FROM sections WHERE id=?", (e["section_id"],), one=True)
    if request.method == "POST":
        f = request.form
        kind = f.get("kind", "class")
        day, st, en = f.get("day"), f.get("start", ""), f.get("end", "")
        code = f.get("code", "").strip() or None
        if kind not in KINDS:
            flash("Choose a valid period type.", "error")
            return redirect(url_for("entry_edit", eid=eid))
        subj, tid = normalize(kind, f.get("subject", "").strip(), f.get("teacher_id", type=int))
        err = check_entry(sec, day, st, en, subj, tid, kind, exclude=eid)
        if err:
            flash(err, "error")
            return redirect(url_for("entry_edit", eid=eid))
        unchanged = (day == e["day"] and st == e["start"] and en == e["end"] and subj == e["subject"]
                     and code == e["code"] and kind == e["kind"] and tid == e["teacher_id"])
        if unchanged:
            flash("No changes were made.", "ok")
            return redirect(url_for("program", section=sec["id"], edit=1))
        run("UPDATE classes SET day=?,start=?,end=?,subject=?,code=?,kind=?,teacher_id=? WHERE id=?",
            (day, st, en, subj, code, kind, tid, eid))
        sync_category(tid)
        sync_category(e["teacher_id"])
        if tid and tid != e["teacher_id"]:
            notify(tid, "assigned", f"You were assigned to {sec_label(sec)}: {subj}, {day}, "
                   f"{t12(st)} to {t12(en)}.", url_for("program", section=sec["id"]))
        if e["teacher_id"] and e["teacher_id"] != tid:
            notify(e["teacher_id"], "removed",
                   f"You were removed from {sec_label(sec)}: {e['subject']}, {e['day']}.", url_for("profile"))
        touch("section", sec["id"])
        touch_teacher_of_entry(tid)
        touch_teacher_of_entry(e["teacher_id"])
        if kind == "recess" or e["kind"] == "recess":
            touch_recess_teachers(sec["id"])
        flash("Class period updated. " + time_note(tomin(en) - tomin(st), 1, kind, tid), "ok")
        return redirect(url_for("program", section=sec["id"], edit=1))
    teachers = query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name")
    return render_template("entry_edit.html", e=e, sec=sec, teachers=teachers)


@app.post("/admin/entry/<int:eid>/delete")
@login_required("admin")
def entry_delete(eid):
    row = query("SELECT section_id, teacher_id, kind, subject, day FROM classes WHERE id=?", (eid,), one=True)
    run("DELETE FROM classes WHERE id=?", (eid,))
    if row:
        sync_category(row["teacher_id"])
        if row["teacher_id"]:
            sec = query("SELECT * FROM sections WHERE id=?", (row["section_id"],), one=True)
            notify(row["teacher_id"], "removed", f"A class period was removed from your program: "
                   f"{row['subject']} ({sec_label(sec) if sec else 'section'}), {row['day']}.", url_for("profile"))
        touch("section", row["section_id"])
        touch_teacher_of_entry(row["teacher_id"])
        if row["kind"] == "recess":
            touch_recess_teachers(row["section_id"])
    flash("Class period removed.", "ok")
    return redirect(url_for("program", section=row["section_id"] if row else None, edit=1))


@app.route("/admin/teachers", methods=["GET", "POST"])
@login_required("admin")
def teachers():
    """05 Teacher Management: accounts, profiles, specialization and availability in one table.
    Adding a teacher only needs the name, grade level handled, subjects and number of sections: the
    class hours follow the grade level (Grade 11 = AM, Grade 12 = PM, MID = MID)."""
    tt = get_tt()
    if request.method == "POST":                     # teachers are registered in Quick Input now
        flash("Teachers are added in Quick Input.", "error")
        return redirect(url_for("quick_input") + "#teachers")
    rows = query("SELECT * FROM users WHERE role='teacher' ORDER BY id")  # TEACHER-01, 02, 03 ...
    summ = {r["id"]: teacher_summary(r) for r in rows}
    return render_template("teachers.html", rows=rows, summ=summ, suggested_id=next_teacher_id(),
                           shift_of=SHIFT_OF, temp_pw=TEMP_PASSWORD,
                           auto_hours={k: auto_official(k, tt) for k in CATS},
                           auto_hm={k: list(auto_hm(k, tt)) for k in CATS})


@app.route("/admin/teachers/<int:tid>/edit", methods=["GET", "POST"])
@login_required("admin")
def teacher_edit(tid):
    t = query("SELECT * FROM users WHERE id=? AND role='teacher'", (tid,), one=True)
    if not t:
        abort(404)
    if request.method == "POST":
        f = request.form
        name = f.get("full_name", "").strip()
        num = f.get("teacher_num", "").strip()
        code = f"T-{num}" if num else ""
        user, cat = f.get("username", "").strip(), f.get("category", "")
        inter, anc = to_int(f.get("intervention_min")), to_int(f.get("ancillary_min"))
        back = redirect(url_for("teacher_edit", tid=tid))
        if not (name and num and user) or cat not in CATS:
            flash("Complete the name, Teacher ID number, username and teacher type.", "error")
            return back
        if not num.isdigit():
            flash("The Teacher ID number must be a whole number.", "error")
            return back
        if inter is None or anc is None:
            flash("Minutes must be a whole number from 0 to 600.", "error")
            return back
        if category_clash(tid, cat):
            flash("This teacher still has class periods or an advisory in a grade level the new type "
                  "does not cover. Remove or reassign those first.", "error")
            return back
        item = f.get("item", "").strip()
        subj_area = f.get("subject_area", t["subject_area"] or "").strip()   # the form no longer shows it: keep what is stored
        spec = f.get("specialization", "").strip()
        load = (t["teaching_load"] or "")                  # the load is calculated from the assignments, never typed
        anc_txt = (t["ancillary"] or "")               # the ancillary is the advisory class: never typed, never overwritten
        raw_ms = f.get("max_sections", "").strip()
        ms = (to_int(raw_ms, 1, 20) if raw_ms else None)
        if raw_ms and ms is None:
            flash("The most sections must be a whole number from 1 to 20.", "error")
            return back
        off = f.get("official_time", "").strip()
        if cat != t["category"] and off == (t["official_time"] or "") and off in ("", auto_official(t["category"])):
            off = auto_official(cat)  # the class hours follow the new grade level
        unchanged = (name == t["full_name"] and code == t["teacher_id"] and user == t["username"]
                     and cat == t["category"] and item == (t["item"] or "")
                     and subj_area == (t["subject_area"] or "") and spec == (t["specialization"] or "")
                     and load == (t["teaching_load"] or "") and anc_txt == (t["ancillary"] or "")
                     and off == (t["official_time"] or "") and inter == (t["intervention_min"] or 0)
                     and anc == (t["ancillary_min"] or 0) and ms == t["max_sections"])
        if unchanged:
            match_quals(tid)   # nothing was edited, but make sure the teacher's specialization is matched to subjects
            flash("No changes were made.", "ok")
            return redirect(url_for("teachers"))
        try:
            run("""UPDATE users SET full_name=?, teacher_id=?, username=?, category=?, item=?,
                   subject_area=?, specialization=?, teaching_load=?, ancillary=?, official_time=?,
                   intervention_min=?, ancillary_min=?, max_sections=? WHERE id=?""",
                (name, code, user, cat, item, subj_area, spec, load, anc_txt, off, inter, anc, ms, tid))
            touch("teacher", tid)
            drop_removed_quals(tid, t["specialization"])
            match_quals(tid)
            flash("Teacher details updated.", "ok")
            return redirect(url_for("teachers"))
        except IntegrityError:
            flash("That username or Teacher ID is already in use.", "error")
            return back
    return render_template("teacher_edit.html", t=t, tl=teacher_summary(t), anc=ancillary_text(t))


@app.post("/admin/teachers/<int:tid>/minutes")
@login_required("admin")
def teacher_minutes(tid):
    """Admin edits the daily minutes shown on a Teacher's Program. Totals are computed."""
    t = query("SELECT * FROM users WHERE id=? AND role='teacher'", (tid,), one=True)
    if not t:
        abort(404)
    back = redirect(url_for("teacher_view", tid=tid))
    f = request.form
    if f.get("action") == "reset":
        run("DELETE FROM settings WHERE k=?", (f"tmins_{tid}",))
        touch("teacher", tid)
        flash("The minutes are automatic again.", "ok")
        return back
    sm = teacher_summary(dict(t, official_time=t["official_time"]))
    auto = dict(teach=sm["auto"]["teach"], inter={d: sm["auto"]["inter"] for d in DAYS},
                anc={d: sm["auto"]["anc"] for d in DAYS})
    labels = dict(teach="Daily actual teaching minutes", inter="Intervention / Remediation",
                  anc="Ancillary / Adviser's minutes")
    data, bad = {}, []
    for key in ("teach", "inter", "anc"):
        data[key] = {}
        for d in DAYS:
            raw = f.get(f"{key}_{d}", "").strip()
            if not raw:
                continue
            v = parse_minutes(raw)
            if v is None or v > 1440:
                bad.append(f"{labels[key]} on {d}")
            elif v != auto[key][d]:
                data[key][d] = v
    if bad:
        flash("Could not read: " + "; ".join(bad) + ". Type minutes like 45, or a time like "
              "1:00 PM - 2:30 PM. Nothing was saved.", "error")
        return back
    run("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (f"tmins_{tid}", json.dumps(data)))
    touch("teacher", tid)
    flash("Minutes saved. The total daily working minutes were computed.", "ok")
    return back


@app.post("/admin/teachers/<int:tid>/delete")
@login_required("admin")
def teacher_delete(tid):
    """Same code path as Quick Input: clears loads, qualifications, notifications and marks the
    affected programs out of date, so no record is left pointing at a deleted teacher."""
    from werkzeug.datastructures import MultiDict
    ok, msgs = qi_teacher_delete(MultiDict({"tid": str(tid)}))
    for m in msgs:
        flash(m, "ok" if ok else "error")
    return redirect(url_for("teachers"))


def clean(v, n=200):
    return (v or "").strip()[:n]


def minutes_field(f, key, current):
    v = f.get(key)
    return to_int((current or 0) if v is None else (v.strip() or 0))


# Room numbers from the school floor plans: 2xx = floor 2, 3xx = floor 3, 4xx = floor 4.
# The example sections share rooms the way the plans show (Grade 11 and Grade 12 in one room).
SAMPLE_ROOMS = {"11-Chef": "309", "12-Receptionist": "309",
                "11-Baker": "301", "12-Pastry": "301",
                "11-Barista": "308", "12-Bartender": "308",
                "11-Cookery": "310", "12-Steward": "310",
                "11-Housekeeping": "311", "12-Concierge": "311",
                "11-Tourism": "405", "12-Events": "405"}


def all_room_names(extra=()):
    """Room 101-112, 201-212, 301-312 and 401-412 (floors 1-4), then any other registered room."""
    std = [f"Room {fl}{n:02d}" for fl in (1, 2, 3, 4) for n in range(1, 13)]
    return std + sorted({x for x in extra if x and x not in std})


def register_room(name):
    """Kept for older callers. It does nothing now: a room exists only when an administrator registers it
    (Quick Input), so nothing appears in Room Management, Teacher Loading or Generate by itself."""
    return None


def live_track_clusters():
    """Active clusters of each track, read from Subject Management (fixed ones first, then added ones)."""
    out = {t: [] for t in TRACK_CLUSTERS}
    try:
        rows = [r for r in subject_catalog(kind="cluster") if r["track"] in out]
        fixed = {n: i for t, lst in TRACK_CLUSTERS.items() for i, n in enumerate(lst)}
        for r in sorted(rows, key=lambda r: (fixed.get(r["name"], 999), r["name"])):
            out[r["track"]].append(r["name"])
    except Exception:
        out = {t: list(v) for t, v in TRACK_CLUSTERS.items()}
    return out


@app.context_processor
def _live_clusters():
    live = spec_live()
    return {"track_clusters": live_track_clusters(), "quick_groups": live["quick"], "spec_groups": live["manage"],
            "spec_meta": live["meta"], "curriculum_names": live["names"]}


def room_place(room):
    """(building, floor) from a room number: 101-112 is floor 1, 201-212 is floor 2, 301-312 floor 3, 401-412 floor 4;
    rooms 01-05 are in Building 1, 06-07 in Building 2 and 08-12 in Building 3 ('Room 308' = Bldg. 3, floor 3)."""
    m = re.search(r"(?<!\d)([1234])(0[1-9]|1[0-2])(?!\d)", room or "")
    if not m:
        return "", ""
    n = int(m.group(2))
    return ("1" if n <= 5 else "2" if n <= 7 else "3"), m.group(1)


ACADEMIC_SAMPLE = {"11-Tourism", "12-Events", "12-Concierge"}  # the other example sections are TechPro
SAMPLE_CLUSTER = {n: ("Business and Entrepreneurship" if n in ACADEMIC_SAMPLE else "Hospitality and Tourism")
                  for n in list(SAMPLE_ROOMS) + ["11-Chef", "12-Receptionist"]}


@app.route("/admin/assignments", methods=["GET", "POST"])
@login_required("admin")
def assignments():
    """Saves the editable rows of the Teacher Management table (the page itself is /admin/teachers)."""
    if request.method == "POST":
        f = request.form
        labels, updates, errors = teacher_labels(), [], []
        for t in query("SELECT * FROM users WHERE role='teacher' ORDER BY id"):
            i = t["id"]
            if f"name_{i}" not in f:
                continue
            name, cat = clean(f.get(f"name_{i}")), f.get(f"cat_{i}", "")
            inter = minutes_field(f, f"inter_{i}", t["intervention_min"])
            ancm = minutes_field(f, f"ancm_{i}", t["ancillary_min"])
            raw_secs = (f.get(f"secs_{i}") or "").strip()
            secs = (to_int(raw_secs, 1, 20) if raw_secs else None) if f"secs_{i}" in f else t["max_sections"]
            if not name or cat not in CATS:
                errors.append(f"{labels[i]}: enter a name and choose a grade level.")
            elif raw_secs and secs is None:
                errors.append(f"{labels[i]}: sections they teach must be a whole number from 1 to 20.")
            elif inter is None or ancm is None:
                errors.append(f"{labels[i]}: minutes must be a whole number from 0 to 600.")
            elif cat != t["category"] and category_clash(i, cat):
                errors.append(f"{labels[i]} still has periods or an advisory in a grade level that "
                              "the new type does not cover. Remove or reassign those first.")
            else:
                def pick(key, cur, n=200):
                    return clean(f.get(key), n) if key in f else (cur or "")
                new_time = pick(f"time_{i}", t["official_time"], 60)
                if cat != t["category"] and new_time == (t["official_time"] or "") \
                        and new_time in ("", auto_official(t["category"])):
                    new_time = auto_official(cat)  # the class hours follow the new grade level
                updates.append((name, cat, pick(f"subj_{i}", t["subject_area"], 400), pick(f"spec_{i}", t["specialization"], 800),
                                pick(f"load_{i}", t["teaching_load"], 60), pick(f"anc_{i}", t["ancillary"]),
                                new_time, inter, ancm, secs or None, i))
        if errors:
            for e in errors:
                flash(e + " Nothing was saved.", "error")
        else:
            conn = db()
            old = {r["id"]: tuple(r[k] for k in ("full_name", "category", "subject_area", "specialization",
                                                  "teaching_load", "ancillary", "official_time",
                                                  "intervention_min", "ancillary_min", "max_sections"))
                   for r in query("SELECT * FROM users WHERE role='teacher'")}
            conn.executemany("""UPDATE users SET full_name=?, category=?, subject_area=?,
                                specialization=?, teaching_load=?, ancillary=?, official_time=?, intervention_min=?, ancillary_min=?,
                                max_sections=? WHERE id=?""", updates)
            conn.commit()
            for u in updates:
                o = old.get(u[-1])
                if o is not None and tuple((x or "") if isinstance(x, str) or x is None else x for x in o) != \
                        tuple((x or "") if isinstance(x, str) or x is None else x for x in u[:-1]):
                    touch("teacher", u[-1])
                if o is not None and (o[3] or "") != u[3]:
                    match_quals(u[-1])  # a new specialization qualifies the teacher for those subjects
            flash("Teacher details saved.", "ok")
    return redirect(url_for("teachers"))


def adviser_error(aid, grade):
    if not aid:
        return None
    a = query("SELECT * FROM users WHERE id=? AND role='teacher'", (aid,), one=True)
    if not a:
        return "Selected adviser was not found."
    return None  # a teacher advising the other grade level becomes MID automatically


def section_fields(f, current=None):
    """Track, cluster and shift from a section form. The cluster must belong to the chosen track."""
    track, cluster = f.get("track", "").strip(), f.get("cluster", "").strip()
    track = track if track in TRACKS else ""
    if cluster:
        owner = next((t for t, lst in live_track_clusters().items() if cluster in lst), None)
        if not owner:
            return None, "Choose a cluster from the list."
        if track and owner != track:
            return None, f"{cluster} belongs to the {owner} track, not {track}."
        track = owner
        row = query("SELECT offered FROM subjects WHERE name=?", (cluster,), one=True)
        if row and row["offered"] == 0 and cluster != (current["cluster"] if current else ""):
            return None, f"{cluster} is turned off. Turn it on in Subject Management first."
    # The shift is automatic: Grade 11 is AM and Grade 12 is PM (there is no MID class program).
    shift = "AM" if str(f.get("grade")) == "11" else "PM"
    return dict(track=track, cluster=cluster or None, shift=shift), None


@app.route("/admin/sections", methods=["GET", "POST"])
@login_required("admin")
def sections():
    """04 Section Management: grade level, section, track, cluster, shift, room and adviser."""
    if request.method == "POST":                     # sections are registered in Quick Input now
        flash("Sections are added in Quick Input.", "error")
        return redirect(url_for("quick_input") + "#sections")
    rows = query("""SELECT s.*, u.full_name AS adviser,
                    (SELECT COUNT(*) FROM section_subjects WHERE section_id=s.id) AS nsub,
                    (SELECT COUNT(*) FROM loads l WHERE l.section_id=s.id AND l.teacher_id IS NOT NULL
                       AND EXISTS(SELECT 1 FROM section_subjects x WHERE x.section_id=l.section_id
                                  AND x.subject_id=l.subject_id)) AS nload
                    FROM sections s LEFT JOIN users u ON u.id=s.adviser_id ORDER BY s.grade, s.name""")
    teachers_ = query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name")
    return render_template("sections.html", rows=rows, teachers=teachers_, **section_form_data())


def section_form_data():
    offered = {r["name"] for r in query("SELECT name FROM subjects WHERE kind='cluster' AND COALESCE(offered,1)=1")}
    return dict(offered_clusters={t: [c for c in lst if c in offered] for t, lst in live_track_clusters().items()},
                shifts=sorted(get_tt()))


@app.route("/admin/sections/<int:sid>/edit", methods=["GET", "POST"])
@login_required("admin")
def section_edit(sid):
    s = query("SELECT * FROM sections WHERE id=?", (sid,), one=True)
    if not s:
        abort(404)
    if request.method == "POST":
        f = request.form
        grade, aid = f.get("grade", type=int), f.get("adviser_id", type=int)
        name = full_section(grade, f.get("name", ""))
        back = redirect(url_for("section_edit", sid=sid))
        if grade not in (11, 12) or not name:
            flash("Enter a section name and choose 11 or 12.", "error")
            return back
        extra, err = section_fields(f, s)
        if err:
            flash(err, "error")
            return back
        if adviser_error(aid, grade):
            flash(adviser_error(aid, grade), "error")
            return back
        room = (f.get("room") or "").strip()
        rerr = room_error(room, grade, sid)              # only a registered, open and free classroom is accepted
        if rerr:
            flash(rerr, "error")
            return back
        rrow = query("SELECT * FROM rooms WHERE lower(name)=lower(?)", (room,), one=True) if room else None
        room = rrow["name"] if rrow else ""
        bldg, floor = (rrow["building"], rrow["floor"]) if rrow else (None, None)
        try:
            run("""UPDATE sections SET name=?, grade=?, track=?, cluster=?, shift=?, room=?, adviser_id=?,
                   building=?, floor=? WHERE id=?""",
                (name, grade, extra["track"], extra["cluster"], extra["shift"], room, aid,
                 bldg or None, floor or None, sid))
            sync_section_subjects(sid)
            if room != (s["room"] or ""):                   # the periods held in the old home room move to the new one
                old = query("SELECT id FROM rooms WHERE lower(name)=lower(?)", (s["room"] or "",), one=True)
                if old:
                    run("UPDATE classes SET room=?, room_id=? WHERE section_id=? AND kind='class' AND room_id=?",
                        (room or None, rrow["id"] if rrow else None, sid, old["id"]))
                else:
                    run("UPDATE classes SET room=?, room_id=? WHERE section_id=? AND kind='class' AND room_id IS NULL",
                        (room or None, rrow["id"] if rrow else None, sid))
            if room and rrow and room != (s["room"] or ""):
                # the administrator's choice wins: this section's classroom periods sit in its home room, and
                # classroom bookings that an older build made for other sections in this room are released
                run("""UPDATE classes SET room=?, room_id=? WHERE section_id=? AND kind='class'
                       AND subject IN (SELECT name FROM subjects WHERE rtype='Regular')""", (room, rrow["id"], sid))
                run("""UPDATE classes SET room=NULL, room_id=NULL WHERE room_id=? AND section_id!=? AND kind='class'
                       AND section_id NOT IN (SELECT id FROM sections WHERE lower(room)=lower(?))""", (rrow["id"], sid, room))
            has = query("SELECT COUNT(*) AS n, COUNT(teacher_id) AS t FROM classes WHERE section_id=? AND kind='class'", (sid,), one=True)
            if not has["n"] or (not has["t"] and (extra["cluster"] != s["cluster"] or grade != s["grade"] or room != (s["room"] or ""))):
                build_default_program(sid, force=True)   # still the starting program: rebuild it with the new elective
            elif has["n"] and (extra["cluster"] != s["cluster"] or grade != s["grade"]):
                mark_stale([sid])                          # teachers are already placed: regenerate it in Generate
            for x in {aid, s["adviser_id"]} | {r["teacher_id"] for r in query(
                    "SELECT DISTINCT teacher_id FROM classes WHERE section_id=?", (sid,))}:
                sync_category(x)
            if aid and aid != s["adviser_id"]:
                notify(aid, "adviser", f"You were assigned as adviser of {name}.",
                       url_for("program", section=sid))
            if s["adviser_id"] and s["adviser_id"] != aid:
                notify(s["adviser_id"], "removed",
                       f"You are no longer the adviser of {sec_label(s)}.", url_for("profile"))
            touch("section", sid)
            flash("Section updated.", "ok")
            return redirect(url_for("sections"))
        except IntegrityError:
            flash("A section with that name already exists.", "error")
            return back
    teachers_ = query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name")
    room_json = {str(g): room_options(sid, g, True) for g in (11, 12)}
    return render_template("section_edit.html", s=s, teachers=teachers_, room_json=room_json,
                           room_opts=room_json[str(s["grade"])], **section_form_data())


@app.post("/admin/sections/<int:sid>/delete")
@login_required("admin")
def section_delete(sid):
    """Same code path as Quick Input: removes the program, subject list and loads of the section."""
    from werkzeug.datastructures import MultiDict
    ok, msgs = qi_section_delete(MultiDict({"sid": str(sid)}))
    for m in msgs:
        flash(m, "ok" if ok else "error")
    return redirect(url_for("sections"))


def sniff_image(data):
    """Return the image type from the first bytes of the file (never trust the file name)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@app.route("/logo")
def logo():
    r = query("SELECT mime,data FROM files WHERE k='logo'", one=True)
    data, mime = (bytes(r["data"]), r["mime"]) if r else (DEFAULT_LOGO, "image/png")
    resp = make_response(data)
    resp.headers["Content-Type"] = mime
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.post("/admin/logo")
@login_required("admin")
def logo_upload():
    f = request.files.get("logo")
    if not f or not f.filename:
        flash("Choose an image file first.", "error")
    else:
        data = f.read(MAX_LOGO + 1)
        mime = sniff_image(data)
        if len(data) > MAX_LOGO:
            flash("That image is too large. Use a file under 2 MB.", "error")
        elif not mime:
            flash("Use a PNG, JPG, GIF or WEBP image.", "error")
        else:
            run("INSERT OR REPLACE INTO files(k,mime,data,updated) VALUES('logo',?,?,?)",
                (mime, data, int(time.time())))
            flash("School logo saved.", "ok")
    return redirect(url_for("settings"))


@app.post("/admin/logo/remove")
@login_required("admin")
def logo_remove():
    run("DELETE FROM files WHERE k='logo'")
    flash("The default school logo is now in use.", "ok")
    return redirect(url_for("settings"))


def save_timetable_rules(f):
    text = f.get("tt_text", "")
    tt = parse_tt(text)
    md, tn, mw = to_int(f.get("max_day"), 60, 720), to_int(f.get("turnover"), 0, 120), to_int(f.get("max_week"), 60, 3000)
    if not tt:
        return False, "The timetable has no readable periods. Add at least one period to a shift."
    if tt_overlap(tt):
        return False, tt_overlap(tt)
    if md is None or tn is None or mw is None:
        return False, "Daily limit must be 60-720 minutes, weekly limit 60-3000 and turnover 0-120 minutes."
    sset("tt_text", text)
    sset("max_teach_day", md)
    sset("max_teach_week", mw)
    sset("turnover", tn)
    return True, ("Timetable, shifts and scheduling rules saved. Run Validation Center to see whether "
                  "existing class programs still fit.")


RESET_TABLES = ("classes", "section_subjects", "loads", "teacher_subjects", "sections", "signup_requests", "reset_requests", "otp_codes")


def reset_counts():
    n = lambda sql: query(sql, one=True)["n"]
    return dict(teachers=n("SELECT COUNT(*) AS n FROM users WHERE role='teacher'"), sections=n("SELECT COUNT(*) AS n FROM sections"),
                classes=n("SELECT COUNT(*) AS n FROM classes"), rooms=n("SELECT COUNT(*) AS n FROM rooms"),
                requests=n("SELECT (SELECT COUNT(*) FROM signup_requests) + (SELECT COUNT(*) FROM reset_requests) + (SELECT COUNT(*) FROM otp_codes) AS n"))


def clear_test_data(with_rooms=True):
    """Delete the records administrators enter or generate: teachers, sections, subject and teacher assignments,
    class programs, scheduling drafts and requests. Administrator accounts, settings, the subject list, reports and
    the audit trail stay, and no table is dropped. Returns what was removed."""
    rc = reset_counts()
    conn = db()
    conn.execute("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE role='teacher')")
    for t in RESET_TABLES:
        conn.execute(f"DELETE FROM {t}")
    if with_rooms:
        conn.execute("DELETE FROM rooms")
    conn.execute("DELETE FROM users WHERE role='teacher'")
    conn.execute("DELETE FROM settings WHERE k LIKE 'upd_%' OR k LIKE 'tmins_%' OR k IN "
                 "('gen_draft','stale_sections','approved_at','approved_by','approved_periods','example_loaded')")
    conn.commit()
    return rc


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required("admin")
def settings():
    """02 School Setup: school year and term, document details, logo, timetable, shifts and rules."""
    if request.method == "POST":
        f = request.form
        act = f.get("action")
        if act == "timetable":
            ok, msg = save_timetable_rules(f)
            flash(msg, "ok" if ok else "error")
            return redirect(url_for("settings") + "#timetable")
        if act == "reset_people":
            if (f.get("confirm") or "").strip().upper() != "DELETE":
                flash("Nothing was deleted. Type DELETE in the box to confirm.", "error")
                return redirect(url_for("settings") + "#reset")
            rc = clear_test_data(with_rooms=bool(f.get("with_rooms")))
            audit_event(g.user, "Reset test data", f"{rc['teachers']} teachers, {rc['sections']} sections, {rc['classes']} class periods"
                        + (f", {rc['rooms']} rooms" if f.get("with_rooms") else ""))
            flash("Test data was cleared: " + f"{rc['teachers']} teachers, {rc['sections']} sections, {rc['classes']} class periods"
                  + (f", {rc['rooms']} rooms" if f.get("with_rooms") else "")
                  + ". Administrator accounts, school setup, email settings and the subject list were kept.", "ok")
            return redirect(url_for("settings") + "#reset")
        if act == "import_tt":
            up = request.files.get("tt_file")
            if not up or not up.filename.lower().endswith(".xlsx"):
                flash("Choose an Excel file (.xlsx).", "error")
                return redirect(url_for("settings") + "#timetable")
            try:
                text, errs = read_tt_excel(up)
            except ImportError:
                flash("Excel import needs a package. Run:  pip install openpyxl", "error")
                return redirect(url_for("settings") + "#timetable")
            except Exception:
                flash("That file could not be read. Download the template, fill it in and try again.", "error")
                return redirect(url_for("settings") + "#timetable")
            tt = parse_tt(text)
            if errs:
                flash(" ".join(errs[:3]) + (f" (+{len(errs) - 3} more)" if len(errs) > 3 else "") + " Nothing was imported.", "error")
            elif not tt:
                flash("No time slots were found in the file. Use the columns Shift, Start, End, Type.", "error")
            elif tt_overlap(tt):
                flash(tt_overlap(tt) + " Nothing was imported.", "error")
            else:
                sset("tt_text", text)
                flash(f"Imported {sum(len(v) for v in tt.values())} time slots in {len(tt)} shift(s): {', '.join(sorted(tt))}.", "ok")
            return redirect(url_for("settings") + "#timetable")
        if act == "reset_tt":
            sset("tt_text", DEFAULT_TT)
            flash("The timetable was reset to the standard AM and PM shifts.", "ok")
            return redirect(url_for("settings") + "#timetable")
        sy, tn_ = f.get("school_year", "").strip(), f.get("term_name", "").strip()
        ym = re.match(r"^(\d{4})-(\d{4})$", sy)
        if not f.get("school_name", "").strip():
            flash("The school name is required.", "error")
        elif not ym or int(ym[2]) != int(ym[1]) + 1 or tn_ not in TERM_NAMES:
            flash("Enter the school year like 2026-2027 (consecutive years) and choose the term.", "error")
        else:
            vals = {k: f.get(k, "").strip() for k, _ in SETTING_FIELDS}
            vals["term"] = f"{tn_}, SY {sy}"
            for k, v in vals.items():
                run("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, v))
            flash(f"School year saved: {vals['term']}.", "ok")
        return redirect(url_for("settings"))
    tt = get_tt()
    shifts = []
    for name in sorted(tt, key=lambda k: tt[k][0][0]):
        per = tt[name]
        cls = sum(e - s for s, e, k in per if k == "class")
        shifts.append(dict(name=name, start=hhmm(per[0][0]), end=hhmm(per[-1][1]), day=cls, week=cls * len(DAYS),
                           n=sum(1 for p in per if p[2] == "class")))
    tm_ = re.match(r"^(.*?),\s*SY\s*(\d{4}-\d{4})$", get_cfg()["term"] or "")
    return render_template("settings.html", rc=reset_counts(), fields=[x for x in SETTING_FIELDS if x[0] != "term"], terms=TERM_NAMES,
                           term_name=tm_[1] if tm_ else "", school_year=tm_[2] if tm_ else "", tt_text=gset("tt_text", "") or DEFAULT_TT,
                           max_day=gset("max_teach_day", "360"), max_week=gset("max_teach_week", "1800"),
                           turnover=gset("turnover", "0"), shifts=shifts)


# ------------------------------------------------------------ problem reports
REPORT_LOG = {}  # ip -> times of recent reports
MAX_REPORTS = 500
MAX_PHOTO = 3 * 1024 * 1024
MAX_PHOTOS = 5


@app.route("/help")
def help_center():
    """A plain guide on how to use the system. Open to everyone, signed in or not."""
    return render_template("help.html")


@app.route("/report", methods=["GET", "POST"])
def report():
    """Anyone (signed in or not) can send the administrator a message and an optional photo."""
    u = g.user
    f = request.form
    if request.method == "POST":
        msg = (f.get("message") or "").strip()[:2000]
        code = "" if u else clean(f.get("teacher_id"), 40)
        who = u
        if not u and code:
            who = query("SELECT * FROM users WHERE role='teacher' AND lower(teacher_id)=lower(?)",
                        (code,), one=True)
        name = who["full_name"] if who else ""
        contact = (who["teacher_id"] or who["username"]) if who else ""
        now = time.time()
        recent = [t for t in REPORT_LOG.get(request.remote_addr, []) if now - t < 600]
        err = None
        if len(recent) >= 5:
            err = "Too many reports from this device. Please wait 10 minutes and try again."
        elif not u and not code:
            err = "Please enter your Teacher ID."
        elif not who:
            err = "We could not find that Teacher ID. Check it and try again."
        elif len(msg) < 5:
            err = "Describe the problem in a few words (at least 5 characters)."
        elif query("SELECT COUNT(*) AS n FROM reports", one=True)["n"] >= MAX_REPORTS:
            err = "The report inbox is full. Please contact the administrator directly."
        shots = []
        picked = [p for p in request.files.getlist("photos") if p and p.filename]
        if not err and len(picked) > MAX_PHOTOS:
            err = "You can upload up to 5 screenshots only."
        if not err:
            for p in picked:
                data = p.read(MAX_PHOTO + 1)
                mime = sniff_image(data)
                if len(data) > MAX_PHOTO:
                    err = "A screenshot is too large. Use images under 3 MB each."
                elif not mime:
                    err = "Use PNG, JPG, GIF or WEBP screenshots."
                if err:
                    break
                shots.append((data, mime))
        if err:
            flash(err, "error")
            return render_template("report.html", v=f)
        conn = db()
        cur = conn.execute("""INSERT INTO reports(user_id,name,contact,message,created,is_read,resolved)
               VALUES(?,?,?,?,?,0,0)""",
            (who["id"] if who else None, name, contact, msg, ph_stamp()))
        for data, mime in shots:
            conn.execute("INSERT INTO report_photos(report_id,data,mime) VALUES(?,?,?)",
                         (cur.lastrowid, data, mime))
        conn.commit()
        REPORT_LOG[request.remote_addr] = recent + [now]
        flash("Your report was sent to the administrator. Thank you for letting us know.", "ok")
        return redirect(url_for("help_center") if u else url_for("login"))
    return render_template("report.html", v={})


@app.route("/admin/reports", methods=["GET", "POST"])
@login_required("admin")
def reports():
    if request.method == "POST":
        f = request.form
        rid, act = f.get("rid", type=int), f.get("action")
        if act == "resolve" and rid:
            run("UPDATE reports SET resolved=1-resolved, is_read=1 WHERE id=?", (rid,))
        elif act == "delete" and rid:
            run("DELETE FROM report_photos WHERE report_id=?", (rid,))
            run("DELETE FROM reports WHERE id=?", (rid,))
            flash("Report deleted.", "ok")
        elif act == "clear":
            run("DELETE FROM report_photos WHERE report_id IN (SELECT id FROM reports WHERE resolved=1)")
            run("DELETE FROM reports WHERE resolved=1")
            flash("Resolved reports were cleared.", "ok")
        return redirect(url_for("reports"))
    rows = query("""SELECT id,user_id,name,contact,message,created,is_read,resolved,
                           (photo IS NOT NULL) AS has_photo FROM reports
                    ORDER BY resolved, id DESC""")
    fresh = {r["id"] for r in rows if not r["is_read"]}
    run("UPDATE reports SET is_read=1 WHERE is_read=0")  # opening the inbox clears the badge
    shots = {}
    for r in query("SELECT id, report_id FROM report_photos ORDER BY id"):
        shots.setdefault(r["report_id"], []).append(r["id"])
    return render_template("reports.html", rows=rows, fresh=fresh, shots=shots,
                           any_resolved=any(r["resolved"] for r in rows),
                           signup_rows=query("SELECT * FROM signup_requests ORDER BY id"),
                           suggested_id=next_teacher_id())


@app.route("/notifications", methods=["GET", "POST"])
@login_required("teacher")
def notifications():
    uid = g.user["id"]
    if request.method == "POST":
        f = request.form
        if f.get("action") == "delete" and f.get("rid", type=int):
            run("DELETE FROM notifications WHERE id=? AND user_id=?", (f.get("rid", type=int), uid))
        elif f.get("action") == "clear":
            run("DELETE FROM notifications WHERE user_id=?", (uid,))
            flash("All notifications were deleted.", "ok")
        return redirect(url_for("notifications"))
    rows = query("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC", (uid,))
    fresh = {r["id"] for r in rows if not r["is_read"]}
    run("UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0", (uid,))
    return render_template("notifications.html", rows=rows, fresh=fresh)


@app.route("/notifications/count")
@login_required()
def notif_count():
    u = g.user
    if u["role"] == "admin":
        n = admin_alerts()
    else:
        n = query("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND is_read=0",
                  (u["id"],), one=True)["n"]
    resp = make_response(json.dumps({"n": n}))
    resp.headers["Content-Type"] = "application/json"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/admin/reports/shot/<int:pid>")
@login_required("admin")
def report_shot(pid):
    r = query("SELECT data, mime FROM report_photos WHERE id=?", (pid,), one=True)
    if not r or not r["data"]:
        abort(404)
    resp = make_response(bytes(r["data"]))
    resp.headers["Content-Type"] = r["mime"] or "image/jpeg"
    resp.headers["Cache-Control"] = "private, max-age=3600"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.route("/admin/reports/<int:rid>/photo")
@login_required("admin")
def report_photo(rid):
    r = query("SELECT photo, photo_mime FROM reports WHERE id=?", (rid,), one=True)
    if not r or not r["photo"]:
        abort(404)
    resp = make_response(bytes(r["photo"]))
    resp.headers["Content-Type"] = r["photo_mime"] or "image/jpeg"
    resp.headers["Cache-Control"] = "private, max-age=3600"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------------------------------------------------------------- templates
CSS = """
:root{--navy:#1b1f7a;--blue:#2d32c8;--tint:#eceefc;--paper:#f5f6fc;--line:#d3d7ee;--ink:#1c2133;
--muted:#5d6482;--gold:#a67c1f;--ok:#2e6b4a;--bad:#9b2c2c;--recess:#ffe94d;--recess-ink:#1c2733}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 "Inter","Segoe UI",Arial,sans-serif}
h1,h2,h3{font-family:"Poppins","Segoe UI",Arial,sans-serif;color:var(--navy);line-height:1.25;margin:0 0 .6rem}
h1{font-size:1.9rem}h2{font-size:1.3rem;margin-top:1.8rem}
a{color:var(--blue)}
:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
.top{background:var(--navy);color:#fff;border-bottom:4px solid var(--gold)}
.top .in{max-width:1180px;margin:auto;padding:.8rem 1.2rem;display:flex;flex-wrap:wrap;gap:1rem;align-items:center;justify-content:space-between}
.brand-name{font-family:"Poppins","Segoe UI",Arial,sans-serif;font-size:1.15rem;font-weight:700}
.brand-name small{display:block;font:400 .8rem "Inter","Segoe UI",Arial,sans-serif;color:#cfd9e6}
.top nav{display:flex;flex-wrap:wrap;gap:.3rem;align-items:center}
.top nav a{color:#fff;text-decoration:none;padding:.4rem .8rem;border-radius:3px}
.top nav a:hover,.top nav a.on{background:rgba(255,255,255,.16)}
.who{font-size:.9rem;color:#cfd9e6;margin-left:.6rem}
main{max-width:1180px;margin:auto;padding:1.6rem 1.2rem 3rem}
footer{text-align:center;color:var(--muted);font-size:.85rem;padding:1.5rem}
.card{background:#fff;border:1px solid var(--line);border-radius:4px;padding:1.2rem 1.4rem;margin:1rem 0}
.head{display:flex;flex-wrap:wrap;gap:.8rem;align-items:center;justify-content:space-between;margin-bottom:.8rem}
.head h1,.head h2{margin:0}
.msg{padding:.7rem 1rem;border-radius:3px;margin:0 0 1rem;border-left:4px solid}
.msg.ok{background:#e7f2ec;border-color:var(--ok);color:#1d4a33}
.msg.error{background:#f8e8e8;border-color:var(--bad);color:#6e1f1f}
label{display:block;font-weight:600;margin:.7rem 0 .2rem;font-size:.95rem}
input,select,textarea{width:100%;padding:.55rem .65rem;border:1px solid #aab4c0;border-radius:3px;font:inherit;background:#fff}
button,.btn{background:var(--blue);color:#fff;border:0;border-radius:3px;padding:.6rem 1.1rem;font:inherit;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
button:hover,.btn:hover{background:var(--blue-d)}
.btn.plain,button.plain{background:#fff;color:var(--blue);border:1px solid var(--blue)}
.btn.plain:hover,button.plain:hover{background:var(--tint)}
.small{padding:.3rem .7rem;font-size:.85rem}
button.danger{background:#fff;color:var(--bad);border:1px solid var(--bad);padding:.3rem .7rem;font-size:.85rem}
button.danger:hover{background:var(--bad);color:#fff}
.hint{color:var(--muted);font-size:.85rem;margin:.2rem 0 0}
.formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:0 1rem;align-items:end}
.formgrid .wide{grid-column:1/-1}
.chk{display:inline-flex;gap:.4rem;align-items:center;font-weight:400;margin:.2rem .9rem .2rem 0}
.chk input{width:auto}
.scroll{overflow-x:auto;background:#fff;border:1px solid var(--line);border-radius:4px}
table{border-collapse:collapse;width:100%}
.doc{background:#fff;border:1px solid var(--line);border-radius:4px;padding:1.6rem 1.8rem;margin:1rem 0}
.letterhead{text-align:center;border-bottom:2px solid var(--navy);padding-bottom:.7rem;margin-bottom:.9rem}
.letterhead .school{font-family:"Poppins","Segoe UI",Arial,sans-serif;font-weight:700;font-size:1.3rem;color:var(--navy)}
.letterhead .addr{color:var(--muted);font-size:.95rem}
.doc-date{text-align:left;font-weight:700;font-size:.95rem;margin:.2rem 0 .5rem;color:var(--navy)}
.letterhead>a{display:flex;flex:none}.logolink{display:inline-block}
.picklist{display:grid;grid-template-columns:repeat(auto-fill,minmax(15rem,1fr));gap:.5rem .9rem;margin-top:.6rem}
.minedit{border-collapse:collapse;width:100%;min-width:640px}.minedit th,.minedit td{border:1px solid var(--line,#d5dbe8);padding:.4rem .5rem;text-align:left}
.minedit input{width:100%;min-width:5.5rem}.minedit tr.tot td,.minedit tr.tot th{background:var(--tint,#eef2fb);font-weight:700}
details.card>summary{cursor:pointer;font-weight:700;color:var(--navy)}
body .slot .acts .btn,body .slot .acts button{padding:.3rem .7rem;font-size:.85rem;min-height:34px}
.editbanner{background:var(--tint,#eef2fb);border-left:4px solid var(--blue);padding:.6rem .9rem;border-radius:4px;margin:.4rem 0 .8rem}
.doc-title{text-align:center;font-size:1.55rem;margin:.4rem 0 0}
.doc-sub{text-align:center;font-weight:600;color:var(--muted);margin:.1rem 0 .6rem}
.room{text-align:center;font-family:"Poppins","Segoe UI",Arial,sans-serif;font-weight:700;font-size:1.2rem;color:var(--navy);margin:.6rem 0}
.roombtn{all:unset;cursor:pointer;font:inherit;font-weight:500;color:var(--navy);text-decoration:underline dotted;text-underline-offset:3px;border-radius:6px;padding:.1rem .3rem}
.roombtn:hover,.roombtn[aria-expanded=true]{background:var(--tint)}
.roombtn:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
.roompop{display:none;margin:.3rem auto 0;max-width:220px;font-size:.8rem;font-weight:600;color:var(--navy);background:#fff;border:1px solid var(--line);border-radius:8px;padding:.3rem .7rem}
.roompop.show{display:block}
@media print{body .roombtn{display:inline!important;text-decoration:underline!important;text-underline-offset:4px;color:#000!important;font-weight:500!important;cursor:default}
body .roompop,body .roompop.show{display:none!important}}
html.pm .roombtn{display:inline!important;text-decoration:underline!important;text-underline-offset:4px;color:#000!important;font-weight:500!important}
html.pm .roompop,html.pm .roompop.show{display:none!important}
@media print{.doc{zoom:var(--zl,1)}}
@media print and (orientation:portrait){.doc{zoom:var(--zp,1)}}
.sign.cls,.doc .sign.cls{display:grid!important;grid-template-columns:1fr 1fr!important;gap:.4rem 3rem!important;text-align:center}
.sign.cls>div:nth-child(1),.sign.cls>div:nth-child(4){grid-column:1/-1;width:min(62%,340px);justify-self:center}
.sign.cls .role{text-align:center}
.sign.cls .role,.doc .sign.cls .role{text-align:center!important;color:var(--ink)}
.sign.cls .name,.doc .sign.cls .name{border-top:0!important;padding-top:0!important;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}
html.pm .sign.cls,.doc .sign.cls{grid-template-columns:1fr 1fr!important}
@media print{.doc .sign.cls{display:grid!important;grid-template-columns:1fr 1fr!important}}
mark.lgc{background:none;color:inherit;font-weight:700;padding:0}
.room,.room .roombtn{font-weight:500}
.room .roombtn{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:4px}
@media print{.room,.room .roombtn,html.pm .room{font-weight:500!important}body .roombtn,.room .roombtn{text-decoration-thickness:1px!important}}
html.pm .room,html.pm .room .roombtn{font-weight:500!important;text-decoration-thickness:1px!important}
a.seclink{color:inherit;text-decoration:underline dotted;text-underline-offset:2px}
a.seclink:hover{color:var(--blue)}
@media print{a.seclink{text-decoration:none!important;color:inherit!important}}
.meta{display:flex;justify-content:space-between;flex-wrap:wrap;gap:.3rem 2.5rem;margin:.8rem 0 1rem}
.meta div{margin:.1rem 0}.meta b{color:var(--navy)}
.legend{font-size:.9rem;margin:.7rem 0 0}
.grid{min-width:860px}
.grid th,.grid td{border:1px solid var(--line);padding:.35rem .45rem;vertical-align:top;text-align:left}
.grid thead th{background:#cfe0f0;color:var(--navy);font-weight:700;text-align:center}
.grid tbody th{background:var(--tint);color:var(--navy);white-space:nowrap;width:140px;font-weight:600}
.grid td.num{text-align:center;font-weight:600;width:100px;white-space:nowrap}
.slot{background:var(--tint);border-left:4px solid var(--blue);padding:.3rem .5rem;margin:0 0 .25rem;border-radius:2px;height:calc(100% - .25rem)}
.slot.rec{background:var(--recess);border-left-color:var(--gold);text-align:center;color:var(--recess-ink)}
.slot strong{display:block;color:var(--navy)}
.slot.rec strong{color:inherit}
.slot span{color:var(--muted);font-size:.88rem;display:block}
.sum th{font-weight:700}
.sum.a th,.sum.a td{background:#ece6f2}
.sum.b th,.sum.b td{background:#e3efd8;font-weight:700}
.sum td{text-align:center;font-weight:600}
.acts{display:flex;gap:.4rem;margin-top:.4rem;flex-wrap:wrap}
.acts form{margin:0}
.empty{color:var(--muted);text-align:center;padding:1.4rem!important}
.sign{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:1rem 2rem;margin-top:2rem;text-align:center}
.sign .role{font-size:.9rem;color:var(--muted);text-align:left}
.sign .name{font-weight:700;color:var(--navy);margin-top:1.8rem;border-top:1px solid var(--ink);padding-top:.2rem}
.sign .title{font-size:.9rem}
.list th,.list td{padding:.6rem .7rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
.list th{background:var(--tint);color:var(--navy)}
.list form.inline{display:flex;gap:.4rem}.list form.inline input{min-width:130px}
.row-acts{display:flex;gap:.4rem;align-items:center}.row-acts form{margin:0}
.pick{display:flex;flex-wrap:wrap;gap:.8rem;align-items:end;margin-bottom:1rem}
.pick select{min-width:240px;width:auto}
.shotbtn{all:unset;cursor:zoom-in;display:inline-block}
.advpick{position:relative}
.advlist{list-style:none;margin:.25rem 0 0;padding:.25rem;position:absolute;left:0;right:0;z-index:30;max-height:15rem;overflow:auto;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 24px rgba(27,31,122,.2)}
.advlist[hidden],.advlist li[hidden]{display:none}
.advlist li{display:flex;flex-direction:column;padding:.5rem .7rem;border-radius:6px;cursor:pointer;line-height:1.25}
.advlist li:hover{background:var(--tint)}
.advlist li small{color:var(--muted)}
.advlist li.advnone{color:var(--muted);cursor:default}
.shotbox[hidden]{display:none}
.shotbox{position:fixed;inset:0;z-index:55;background:rgba(10,12,40,.9);display:flex;align-items:center;justify-content:center;padding:3.2rem 1rem 1rem}
.shotbox img{max-width:100%;max-height:100%;border-radius:6px;box-shadow:0 10px 40px rgba(0,0,0,.5)}
body .shotbox .shotback{position:fixed!important;top:.9rem;top:max(.9rem,env(safe-area-inset-top));left:.9rem;left:max(.9rem,env(safe-area-inset-left));z-index:60;width:auto;height:auto;min-height:44px;padding:.5rem 1rem .5rem .8rem;display:inline-flex;align-items:center;gap:.4rem;background:#fff;color:var(--navy);font-weight:700;border-radius:999px;box-shadow:0 4px 14px rgba(0,0,0,.35);overflow:visible}
body .shotbox .shotback:hover{background:#e3e7fb}
.shotbox .shotback svg{width:20px;height:20px;flex:none}
.tidfield{display:flex;align-items:stretch}
.tidfield .tidfix{display:inline-flex;align-items:center;padding:0 .6rem;border:1.5px solid var(--line);border-right:0;border-radius:8px 0 0 8px;background:var(--tint);color:var(--navy);font-weight:700}
.tidfield input{border-radius:0 8px 8px 0!important;flex:1;min-width:0}
.narrow{max-width:520px}
.cardrow{display:flex;flex-wrap:wrap;align-items:stretch;gap:1rem}
.cardrow>.card{flex:1 1 320px;margin:1rem 0;display:flex;flex-direction:column}
.cardrow>.card form{display:flex;flex-direction:column;flex:1}
fieldset{border:0;padding:0;margin:1rem 0}legend{font-weight:600;color:var(--navy);margin-bottom:.4rem;padding:0}
@media(max-width:800px){.doc{padding:1rem}}
@page{margin:10mm}
@media print{.top,.pick,footer,.card,button,.acts,.noprint,.btn{display:none!important}
body{background:#fff;font-size:12px}main{padding:0;max-width:none}
.doc{border:0;padding:0;margin:0}.scroll{border:0;overflow:visible}.grid{min-width:0}
.sign{margin-top:1.2rem}
.slot,.sum th,.sum td,.grid thead th,.grid tbody th{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
textarea{resize:vertical}
.assign td{vertical-align:top}.assign textarea{min-width:180px}.assign input,.assign select{min-width:130px}
.assign .tn{font-weight:700;color:var(--navy);letter-spacing:.03em}
.assign tr.rowview .vc{display:none!important}
/* Aligned columns: fixed widths, words wrap at spaces, everything starts at the top. */
table.list.assign{table-layout:fixed;width:100%;min-width:1040px}
table.list.assign th,table.list.assign td{vertical-align:top;text-align:left;padding:.65rem .55rem;font-size:.86rem;line-height:1.4}
table.list.assign th{font-size:.78rem;white-space:normal;word-break:normal;overflow-wrap:normal}
table.list.assign th:nth-child(1){width:104px}table.list.assign th:nth-child(2){width:80px}
table.list.assign th:nth-child(3){width:136px}table.list.assign th:nth-child(4){width:120px}
table.list.assign th:nth-child(5){width:78px}table.list.assign th:nth-child(6){width:116px}
table.list.assign th:nth-child(7){width:92px}table.list.assign th:nth-child(8){width:92px}
table.list.assign th:nth-child(9){width:80px}table.list.assign th:nth-child(10){width:80px}
table.list.assign th:nth-child(11){width:76px}
table.list.assign .tn{white-space:nowrap}
table.list.assign .vtext{display:block;white-space:pre-wrap;overflow-wrap:break-word;word-break:normal}
table.list.assign .hint{font-size:.74rem;line-height:1.35;margin:.3rem 0 0;overflow-wrap:break-word;word-break:normal}
table.list.assign td input:not([type=hidden]),table.list.assign td select,table.list.assign td textarea{width:100%;min-width:0;box-sizing:border-box;font-size:.82rem;padding:.35rem .4rem}
table.list.assign .otime{display:flex;flex-direction:column;gap:.2rem;align-items:stretch}
table.list.assign .otime input{font-size:.76rem;padding:.3rem .25rem}
table.list.assign .otime span{font-size:.74rem;text-align:center}
table.list.assign td.editcell{padding-left:.4rem;padding-right:.5rem}
table.list.assign .rowedit[hidden],table.list.assign .rowsave[hidden]{display:none!important}
table.list.assign .row-acts{display:flex;flex-direction:column;gap:.35rem;align-items:stretch}
table.list.assign .rowsave{display:flex;flex-direction:column;gap:.35rem}
table.list.assign .row-acts button{width:100%;min-width:0;padding:.4rem .3rem;font-size:.8rem}
table.list.assign .otime input{height:2rem;min-height:0;flex:none}
table.list.assign td textarea{min-height:5.6rem;resize:vertical}
@media(max-width:800px){table.list.assign{table-layout:auto;min-width:0}}
.assign tr.rowedit-on .vtext{display:none}
.assign .vtext{display:block;white-space:normal;overflow-wrap:anywhere;line-height:1.4;font-size:.93rem;color:var(--ink);padding:.15rem 0}
.assign .vtext.muted{color:var(--muted)}
.assign td:first-child .vtext{font-weight:600}
.assign tr.rowedit-on{background:#f4f6ff;outline:2px solid #c5cbe3}
.assign .editcell{white-space:nowrap}.assign .rowsave{display:inline-flex;gap:.4rem}.assign .rowsave[hidden]{display:none}
.assign tr.arow td{vertical-align:top}
@media(min-width:801px){.assign th.editth,.assign td.editcell{position:sticky;right:0;z-index:2;box-shadow:-8px 0 10px -8px rgba(27,31,122,.35)}
.assign td.editcell{background:#fff}.assign tr.rowedit-on td.editcell{background:#f4f6ff}.assign th.editth{background:#e6eaf8}}
.assign tr.rowedit-on{background:#f4f6ff;outline:2px solid #c5cbe3}
.assign .editcell{white-space:nowrap}.assign .rowsave{display:inline-flex;gap:.4rem}.assign .rowsave[hidden]{display:none}
.grid td.recess,.grid tbody th.recess{background:var(--recess);color:var(--recess-ink);-webkit-print-color-adjust:exact;print-color-adjust:exact}
.top .in{max-width:1240px;display:grid;grid-template-columns:1fr auto;grid-template-areas:"brand acct" "tabs tabs";gap:.25rem 1rem;align-items:center;padding:.7rem 1.2rem .45rem}
.brand-name{grid-area:brand}
.top nav{display:contents}
.tabs{grid-area:tabs;display:flex;flex-wrap:wrap;gap:.2rem;border-top:1px solid rgba(255,255,255,.2);padding-top:.45rem}
.acct{grid-area:acct;display:flex;align-items:center;gap:.4rem;justify-content:flex-end}
.top nav a{padding:.5rem .85rem;border-radius:6px;font-size:.97rem;font-weight:600;transition:background .15s}
.who{margin:0}
main{max-width:1240px}
input:not([type=checkbox]):not([type=radio]):not([type=hidden]),select{height:2.9rem}
.menubtn{display:none;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.4)}
.mobile-days{display:none}
.daytabs{display:flex;gap:.3rem;margin-bottom:.8rem}
.daytab{flex:1;background:#fff;color:var(--blue);border:1px solid var(--blue);padding:.6rem 0}
.daytab.on{background:var(--blue);color:#fff}
.dayp{display:none}.dayp.on{display:block}
.dayp h3{margin:.2rem 0 .4rem}
.mrow{margin:.55rem 0}
.mtime{font-weight:600;color:var(--navy);font-size:.92rem;padding:.3rem .6rem;background:var(--tint);border:1px solid var(--line);border-bottom:0;border-radius:4px 4px 0 0}
.mtime.recess{background:var(--recess);color:var(--recess-ink)}
.mrow .slot{height:auto;margin:0;border-radius:0 0 4px 4px;border:1px solid var(--line);border-left-width:4px}
.mrow .slot.rec{border-left-color:var(--gold)}
.mnone{color:var(--muted);text-align:center;padding:1.2rem}
.msum{margin-top:1rem;border:1px solid var(--line);border-radius:4px;overflow:hidden}
.msum div{display:flex;justify-content:space-between;padding:.45rem .7rem;background:#ece6f2}
.msum div.tot{background:#e3efd8;font-weight:700}
.msum div+div{border-top:1px solid var(--line)}
@media(max-width:800px){
body{font-size:16px}
h1{font-size:1.5rem}
main{padding:1rem .8rem 2.2rem}
button,.btn{min-height:44px}
.small,button.danger{min-height:40px}
.card{padding:1rem}
.head{flex-direction:column;align-items:stretch}
.head .btn,.head button{text-align:center;width:100%}
.pick select{min-width:0;width:100%}.pick>div{width:100%}
.formgrid{grid-template-columns:1fr}
.doc{padding:.9rem}
.doc-title{font-size:1.25rem}
.meta{flex-direction:column;gap:0}
.gridwrap{display:none}
.mobile-days{display:block}
.sign{grid-template-columns:1fr}
.scroll:has(.list.stack){overflow:visible;border:0;background:transparent}
.list.stack,.list.stack tbody,.list.stack tr,.list.stack td{display:block;width:100%}
.list.stack thead{display:none}
.list.stack tr{border:1px solid var(--line);border-radius:4px;margin:.7rem 0;padding:.5rem .7rem;background:#fff}
.list.stack td{border:0;padding:.35rem 0}
.list.stack td[data-label]::before{content:attr(data-label);display:block;font-size:.76rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.list.stack td.empty{text-align:center}
.list form.inline{flex-direction:column}
.assign input,.assign select,.assign textarea{min-width:0}
.row-acts{flex-wrap:wrap}
}
.top{background:linear-gradient(90deg,#1b1f7a,#2d32c8);border-bottom:0}
.grid thead th{background:#dfe2fa}
.card,.doc,.scroll,.msg{border-radius:10px}
input,select,textarea,button,.btn{border-radius:6px}
.viewtoggle{font-size:.9rem}
html{-webkit-text-size-adjust:100%}
a,button,.btn,select,.chk,.daytab{touch-action:manipulation;-webkit-tap-highlight-color:transparent}
button,.btn{transition:background .15s,box-shadow .15s,transform .06s}
button:hover,.btn:hover{box-shadow:0 3px 8px rgba(27,31,122,.22)}
button:active,.btn:active{transform:translateY(1px);box-shadow:none}
button:disabled{opacity:.65;cursor:wait;box-shadow:none}
input:focus,select:focus,textarea:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(45,50,200,.16);outline:0}
.list tbody tr{transition:background .12s}.list tbody tr:hover{background:#f7f8fe}
.chk{padding:.4rem .6rem;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}
.chk:has(input:checked){background:var(--tint);border-color:var(--blue)}
.chk input{width:1.2rem;height:1.2rem;accent-color:var(--blue)}
.daytab{min-height:44px;font-weight:600}
.pwwrap{position:relative;display:block}
.pwwrap>input{margin:0!important;padding-right:3rem!important}
.login .auth-body .pwwrap{margin-top:.3rem}
.pwwrap>.eye{position:absolute;top:0;bottom:0;right:.25rem;margin:auto 0;width:2.6rem;height:2.6rem;min-height:0!important;padding:0;display:flex;align-items:center;justify-content:center;background:transparent;color:var(--muted);border:0;border-radius:8px;box-shadow:none;text-shadow:none;transform:none;filter:none;-webkit-tap-highlight-color:transparent;touch-action:manipulation;transition:background-color .15s,color .15s}
.pwwrap>.eye svg{width:22px;height:22px;pointer-events:none}
@media(hover:hover){.pwwrap>.eye:hover{background:var(--tint);color:var(--blue)}}
.pwwrap>.eye:active{background:#e1e5f8;color:var(--navy);transform:none}
.pwwrap>.eye:focus-visible{outline:2px solid var(--blue);outline-offset:1px}
.pwwrap>.eye:focus:not(:focus-visible){outline:0}
@media(max-width:1100px){
.top .in{display:flex;flex-wrap:wrap;justify-content:space-between;padding:.6rem .9rem}
.menubtn{display:inline-block;min-height:44px}
.top nav{display:none;width:100%;flex-direction:column;gap:.2rem;padding-top:.5rem;border-top:1px solid rgba(255,255,255,.25)}
.top.open nav{display:flex}
.tabs{flex-direction:column;border-top:0;padding-top:0}
.acct{flex-direction:column;align-items:stretch;justify-content:flex-start;border-top:1px solid rgba(255,255,255,.2);padding-top:.3rem}
.top nav a{padding:.8rem .7rem;font-size:1.02rem}
.who{padding:.3rem .7rem}
}
/* ---- sign-in / sign-up screens ---- */
.login{min-height:100vh;min-height:100dvh;display:grid;grid-template-columns:6fr 5fr;background:#fff}
.login .side{position:relative;overflow:hidden;background:linear-gradient(160deg,#2c31c9,#1a1d85);color:#fff;padding:3.5rem 3.5rem 2rem;display:flex;flex-direction:column;justify-content:space-between}
.login .arcs{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.login .side-in{position:relative;margin:auto 0;max-width:30rem}
.login .logo{width:64px;height:64px;margin-bottom:2.2rem;display:block}
.login .side h1{letter-spacing:.02em;font:700 clamp(1.8rem,3.4vw,2.6rem)/1.15 "Inter","Segoe UI",Arial,sans-serif;color:#fff;margin:0 0 1.4rem}
.login .side p{color:#d9dcff;max-width:28rem;margin:0}
.login .copy{position:relative;color:#b9bdf3;font-size:.85rem}
.login .panel{display:flex;padding:2rem 3rem;position:relative}
.helpfab{position:absolute;top:1.1rem;right:1.1rem;display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:50%;background:var(--tint);color:var(--navy);text-decoration:none;box-shadow:0 2px 6px rgba(27,31,122,.15)}
.helpfab:hover{background:#dde2fb}
.helpfab-q{position:absolute;top:-3px;right:-3px;width:16px;height:16px;border-radius:50%;background:var(--gold);color:#fff;font-size:.68rem;font-weight:800;line-height:16px;text-align:center}
@media(max-width:800px){.helpfab{top:.7rem;right:.7rem;width:38px;height:38px}}
.authform{display:flex;flex-direction:column;width:100%;max-width:420px;margin:0 auto;min-height:calc(100vh - 4rem)}
.auth-brand{font-weight:700;font-size:1.15rem;color:#111}
.auth-body{margin:auto 0;padding:1.5rem 0}
.auth-body h2{font:700 1.6rem "Inter","Segoe UI",Arial,sans-serif;color:#111;margin:0 0 .4rem}
.auth-note{color:var(--muted);font-size:.85rem;margin:0 0 1rem}
.login label{font-size:.8rem;color:var(--muted);margin:1.1rem 0 0}
.login input,.login select{border:0;border-bottom:1.5px solid #cfd3e3;border-radius:0;padding:.6rem 0;background:transparent;font-size:1rem}
.login input:focus,.login select:focus{outline:0;border-bottom-color:var(--blue);box-shadow:0 2px 0 var(--blue)}
button.dark{background:#111;color:#fff;width:100%;padding:.85rem;margin-top:1.6rem;border-radius:6px}
button.dark:hover{background:#000}
.auth-foot{text-align:center;color:var(--muted);font-size:.85rem;margin:1.2rem 0 0}
.auth-foot a{font-weight:600}
@media(max-width:1100px){.login .side{padding:2.5rem 2rem}.login .panel{padding:2rem 1.8rem}}
@media(max-width:800px){
.login{grid-template-columns:1fr}
.login .side{padding:1.5rem 1.3rem 1.3rem;min-height:0}
.login .side-in{margin:0}
.login .logo{width:40px;height:40px;margin-bottom:.9rem}
.login .side h1{font-size:1.9rem;margin-bottom:.6rem}
.login .side p{font-size:.95rem}
.login .copy{display:none}
.login .panel{padding:1.2rem 1.3rem 2rem}
.authform{min-height:0}
.auth-brand{display:none}
.auth-body{padding:.4rem 0}
}
@media print{.mobile-days{display:none!important}.gridwrap{display:block!important}}

/* ======== Soft 3D (neumorphic) theme ======== */
:root{--bg:#e8edf5;--sh-d:rgba(150,165,190,.55);--sh-l:rgba(255,255,255,.95);--face:#f3f6fb}
body{background:linear-gradient(160deg,#eff3f9,#dde4ef) fixed}
.top{background:var(--face);color:var(--navy);border-bottom:0;border-radius:0 0 26px 26px;box-shadow:0 10px 24px var(--sh-d),0 -2px 0 #fff inset}
.brand-name{color:var(--navy)}.brand-name small{color:var(--muted)}
.tabs{border-top:1px solid rgba(27,31,122,.1)}
.top nav a{color:var(--navy);border-radius:14px;box-shadow:4px 4px 9px var(--sh-d),-4px -4px 9px var(--sh-l);background:var(--face);margin:.15rem .1rem}
.top nav a:hover{background:#fff}
.top nav a.on{background:linear-gradient(180deg,#4a52ee,#2d32c8);color:#fff;box-shadow:inset 3px 3px 7px rgba(0,0,30,.35),inset -2px -2px 5px rgba(255,255,255,.2)}
.who{color:var(--muted)}
.card,.doc,.scroll,.msg{border:0;background:var(--face);border-radius:22px;box-shadow:9px 9px 20px var(--sh-d),-9px -9px 20px var(--sh-l)}
.doc{background:#fbfcfe}
.scroll{background:#fbfcfe}
.msg{border-left:6px solid}
input:not([type=checkbox]):not([type=radio]):not([type=hidden]),select,textarea{border:0;border-radius:14px;background:#eef2f8;box-shadow:inset 4px 4px 9px var(--sh-d),inset -4px -4px 9px var(--sh-l)}
input:focus,select:focus,textarea:focus{box-shadow:inset 4px 4px 9px var(--sh-d),inset -4px -4px 9px var(--sh-l),0 0 0 3px rgba(45,50,200,.28)}
/* 3D buttons */
button,.btn{background:linear-gradient(180deg,#5a61f4 0%,#2d32c8 55%,#2227a8 100%);color:#fff;border:0;border-radius:16px;padding:.7rem 1.4rem;text-shadow:0 1px 1px rgba(0,0,40,.4);
box-shadow:0 6px 0 #161a6b,0 12px 18px rgba(27,31,122,.35),inset 0 2px 0 rgba(255,255,255,.4);position:relative;margin-bottom:6px;transition:transform .08s,box-shadow .08s,filter .15s}
button:hover,.btn:hover{background:linear-gradient(180deg,#6970ff 0%,#3a40da 55%,#2a2fb8 100%);filter:brightness(1.04);transform:translateY(-1px);
box-shadow:0 7px 0 #161a6b,0 14px 20px rgba(27,31,122,.38),inset 0 2px 0 rgba(255,255,255,.45)}
button:active,.btn:active{transform:translateY(5px);box-shadow:0 1px 0 #161a6b,0 3px 6px rgba(27,31,122,.3),inset 0 2px 0 rgba(255,255,255,.25)}
.btn.plain,button.plain{background:linear-gradient(180deg,#ffffff,#e6ebf5);color:var(--blue);text-shadow:none;border:0;
box-shadow:0 6px 0 #b4bfd6,0 12px 18px var(--sh-d),inset 0 2px 0 #fff}
.btn.plain:hover,button.plain:hover{background:linear-gradient(180deg,#ffffff,#eef2fb);box-shadow:0 7px 0 #b4bfd6,0 14px 20px var(--sh-d),inset 0 2px 0 #fff}
.btn.plain:active,button.plain:active{box-shadow:0 1px 0 #b4bfd6,0 3px 6px var(--sh-d),inset 0 2px 0 #fff}
button.danger{background:linear-gradient(180deg,#fff,#f5e4e4);color:var(--bad);border:0;text-shadow:none;box-shadow:0 4px 0 #d3aeae,0 8px 12px var(--sh-d),inset 0 2px 0 #fff}
button.danger:hover{background:linear-gradient(180deg,#d65a5a,#9b2c2c);color:#fff;box-shadow:0 5px 0 #6a1b1b,0 9px 14px rgba(155,44,44,.35),inset 0 2px 0 rgba(255,255,255,.35)}
button.danger:active{box-shadow:0 1px 0 #6a1b1b}
.small,.btn.small,button.small{padding:.4rem .9rem;border-radius:12px;margin-bottom:4px;box-shadow:0 4px 0 #161a6b,0 8px 12px rgba(27,31,122,.3),inset 0 2px 0 rgba(255,255,255,.4)}
.btn.plain.small,button.plain.small{box-shadow:0 4px 0 #b4bfd6,0 8px 12px var(--sh-d),inset 0 2px 0 #fff}
button.dark{background:linear-gradient(180deg,#444a63,#1a1d2b 60%,#0d0f18);box-shadow:0 6px 0 #000,0 12px 18px rgba(0,0,0,.35),inset 0 2px 0 rgba(255,255,255,.25);border-radius:999px;padding:.95rem;margin-bottom:8px}
button.dark:hover{background:linear-gradient(180deg,#575e7a,#262a3b 60%,#12141f)}
button.dark:active{box-shadow:0 1px 0 #000,0 3px 6px rgba(0,0,0,.3)}
.daytab{background:linear-gradient(180deg,#fff,#e6ebf5);color:var(--blue);border:0;box-shadow:0 4px 0 #b4bfd6,0 8px 12px var(--sh-d),inset 0 2px 0 #fff;margin-bottom:6px}
.daytab.on{background:linear-gradient(180deg,#5a61f4,#2227a8);color:#fff;box-shadow:inset 3px 3px 7px rgba(0,0,30,.4)}
.menubtn{background:linear-gradient(180deg,#fff,#e6ebf5);color:var(--navy);border:0;text-shadow:none;box-shadow:0 4px 0 #b4bfd6,0 8px 12px var(--sh-d),inset 0 2px 0 #fff}
button:disabled{box-shadow:0 2px 0 #161a6b;transform:translateY(3px)}
.chk{border:0;border-radius:14px;background:var(--face);box-shadow:4px 4px 9px var(--sh-d),-4px -4px 9px var(--sh-l)}
.chk:has(input:checked){background:#e1e5fb;box-shadow:inset 3px 3px 7px var(--sh-d),inset -3px -3px 7px var(--sh-l)}
.list th{background:#e6eaf8}.list tbody tr:hover{background:#f3f5fd}
/* sign-in screens */
.login .panel{background:var(--face)}
.login input:not([type=checkbox]):not([type=radio]):not([type=hidden]),.login select{border:0;border-bottom:1.5px solid #cfd3e3;border-radius:0;background:transparent;box-shadow:none;height:auto}
.login input:focus,.login select:focus{box-shadow:0 2px 0 var(--blue)}
/* ======== Program tables: aligned columns ======== */
.grid{table-layout:fixed;width:100%;min-width:900px;border-collapse:collapse}
.grid col.c-time{width:15%}.grid col.c-min{width:9%}
.grid th,.grid td{vertical-align:middle;text-align:center;padding:.4rem .35rem;word-wrap:break-word;overflow-wrap:anywhere}
.grid td{height:1px;border-color:#d9deef}
.grid thead th{padding:.7rem .4rem;background:#dfe2fa}
.grid tbody th{width:auto;white-space:normal;font-size:.9rem;line-height:1.25;text-align:center}
.grid td.num{width:auto;text-align:center}
.slot{height:100%;margin:0;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;min-height:2.7rem;border-left:0;border-radius:10px;padding:.35rem .4rem;background:#e9ecfc;box-shadow:3px 3px 7px var(--sh-d),-3px -3px 7px var(--sh-l)}
.slot.rec{box-shadow:inset 2px 2px 5px rgba(0,0,0,.12)}
.slot strong,.slot span{width:100%;text-align:center}
.slot .acts{justify-content:center}
.sum th{text-align:left;padding-left:.6rem}
.sum td{text-align:center}
.legend{line-height:1.5}
@page{margin:6mm}
@media print{
body{background:#fff!important;font-size:10px;line-height:1.25}
main{padding:0!important;max-width:none!important}
.mobile-days{display:none!important}
.gridwrap{display:block!important;overflow:visible!important;border:0!important;background:none!important}
.doc{padding:0!important;margin:0!important;border:0!important;border-radius:0!important;background:#fff!important;break-inside:avoid;page-break-inside:avoid;page-break-after:avoid}
.letterhead{padding-bottom:3px;margin-bottom:4px}
.letterhead .school{font-size:15px}
.letterhead .addr{font-size:10px}
.doc-title{font-size:15px;margin:2px 0 0}
.doc-sub{font-size:10px;margin:0 0 3px}
.room{font-size:12px;margin:3px 0}
.meta{margin:4px 0;font-size:10px;gap:0 2rem}
.meta div{margin:0}
.grid{min-width:0!important;width:100%;font-size:9px}
.grid th,.grid td{padding:2px 3px!important}
.grid thead th{padding:3px!important}
.slot{min-height:0!important;padding:1px 3px!important;font-size:9px}
.slot span{font-size:8.5px}
.legend{font-size:9px;margin:3px 0 0}
.sign{margin-top:6px!important;gap:2px 1rem;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
.sign .name{margin-top:12px;font-size:10px}
.sign .role,.sign .title{font-size:9px}
.doc *{box-shadow:none!important;text-shadow:none!important}
}
html.pm body{background:#fff!important;font-size:10px;line-height:1.25}
html.pm main{padding:0!important;max-width:none!important}
html.pm .mobile-days{display:none!important}
html.pm .gridwrap{display:block!important;overflow:visible!important;border:0!important;background:none!important}
html.pm .doc{padding:0!important;margin:0!important;border:0!important;border-radius:0!important;background:#fff!important;break-inside:avoid;page-break-inside:avoid;page-break-after:avoid}
html.pm .letterhead{padding-bottom:3px;margin-bottom:4px}
html.pm .letterhead .school{font-size:15px}
html.pm .letterhead .addr{font-size:10px}
html.pm .doc-title{font-size:15px;margin:2px 0 0}
html.pm .doc-sub{font-size:10px;margin:0 0 3px}
html.pm .room{font-size:12px;margin:3px 0}
html.pm .meta{margin:4px 0;font-size:10px;gap:0 2rem}
html.pm .meta div{margin:0}
html.pm .grid{min-width:0!important;width:100%;font-size:9px}
html.pm .grid th,html.pm .grid td{padding:2px 3px!important}
html.pm .grid thead th{padding:3px!important}
html.pm .slot{min-height:0!important;padding:1px 3px!important;font-size:9px}
html.pm .slot span{font-size:8.5px}
html.pm .legend{font-size:9px;margin:3px 0 0}
html.pm .sign{margin-top:6px!important;gap:2px 1rem;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
html.pm .sign .name{margin-top:12px;font-size:10px}
html.pm .sign .role,html.pm .sign .title{font-size:9px}
html.pm .doc *{box-shadow:none!important;text-shadow:none!important}
/* ======== Header and menu alignment ======== */
.top .in{max-width:1240px;margin:0 auto;display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"brand acct" "tabs tabs";align-items:center;gap:.55rem 1rem;padding:.75rem 1.2rem .65rem}
.brand{grid-area:brand;display:flex;align-items:center;gap:.8rem;min-width:0;text-decoration:none;color:var(--navy)}
.brand-logo{width:50px;height:50px;flex:none;object-fit:contain;border-radius:50%;background:#fff;padding:0;box-shadow:3px 3px 8px var(--sh-d),-3px -3px 8px var(--sh-l)}
.brand .brand-name{line-height:1.2}
.top .tabs{grid-area:tabs;display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-start;gap:.5rem;border-top:1px solid rgba(27,31,122,.1);padding-top:.65rem}
.top .acct{grid-area:acct;display:flex;align-items:center;justify-content:flex-end;gap:.6rem;justify-self:end}
.top .tabs a,.top .acct a{display:inline-flex;align-items:center;justify-content:center;min-height:42px;margin:0;padding:0 1.05rem;white-space:nowrap;font-size:.95rem;font-weight:600;line-height:1.1;text-decoration:none;border-radius:14px}
.top .acct .who{max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
@media(max-width:1100px){
.top .in{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;padding:.65rem .9rem}
.top nav{display:none;width:100%;flex-direction:column;gap:.5rem;align-items:stretch;padding-top:.5rem;border-top:1px solid rgba(27,31,122,.1)}
.top.open nav{display:flex}
.top .brand{flex:1 1 0}
.top .brand-name{font-size:1rem}
.top .brand-name small{font-size:.7rem}
.menubtn{flex:none}
.menubtn:hover,.menubtn:active{background:linear-gradient(180deg,#fff,#e6ebf5);color:var(--navy)}
.top .tabs{flex-direction:column;flex-wrap:nowrap;align-items:stretch;gap:.5rem;border-top:0;padding-top:0}
.top .acct{flex-direction:column;align-items:stretch;justify-self:stretch;gap:.5rem;border-top:1px solid rgba(27,31,122,.1);padding-top:.5rem}
.top .tabs a,.top .acct a{justify-content:flex-start;width:100%;min-height:46px;padding:0 1rem;font-size:1rem}
.top .acct .who{max-width:none;padding:.2rem 1rem}
}
/* ======== Menu as a small box ======== */
@media(max-width:1100px){
body .top{position:relative}
body .top .in{position:static}
body .top nav{position:absolute!important;top:calc(100% + 6px);right:.7rem;left:auto!important;width:min(270px,calc(100vw - 1.4rem))!important;z-index:90;background:#fff;border:1px solid #c9cff0!important;border-radius:14px;box-shadow:0 14px 34px rgba(27,31,122,.3);padding:.55rem!important;max-height:calc(100vh - 110px);overflow-y:auto;gap:.3rem!important}
body .top nav::before{content:"";position:absolute;top:-7px;right:20px;width:12px;height:12px;background:#fff;border-left:1px solid #c9cff0;border-top:1px solid #c9cff0;transform:rotate(45deg)}
body .top .tabs{gap:.3rem!important}
body .top .tabs a,body .top .acct a{min-height:42px!important;font-size:.95rem!important;padding:0 .8rem!important}
body .top .acct{padding-top:.4rem!important;gap:.3rem!important}
body .top .acct .who{padding:.15rem .8rem!important;font-size:.85rem}
body .top .acct .bell.desk{display:none}
}
/* ======== Back button (icon) ======== */
.backbtn{display:inline-flex;align-items:center;justify-content:center;width:46px;height:46px;flex:none;border-radius:50%;color:var(--blue);background:linear-gradient(180deg,#fff,#e6ebf5);box-shadow:0 5px 0 #b4bfd6,0 10px 14px var(--sh-d),inset 0 2px 0 #fff;text-decoration:none;margin-bottom:5px;transition:transform .08s,box-shadow .08s}
.backbtn:hover{background:#fff;transform:translateY(-1px)}
.backbtn:active{transform:translateY(4px);box-shadow:0 1px 0 #b4bfd6,0 3px 6px var(--sh-d),inset 0 2px 0 #fff}
.backbtn svg{width:24px;height:24px}
.titlerow{display:flex;align-items:center;gap:.9rem;margin-bottom:.5rem}
.titlerow h1{margin:0}
/* ======== School logo ======== */
.letterhead{display:flex;align-items:center;justify-content:center;gap:1.1rem;text-align:center}
.letterhead .lh-text{flex:1;min-width:0}
.lh-logo{width:92px;height:92px;flex:none;object-fit:contain;display:block}
.lh-spacer{visibility:hidden}
.login .logoimg{width:120px;height:120px;object-fit:contain;background:#fff;border-radius:50%;padding:4px;box-shadow:0 8px 20px rgba(0,0,40,.3)}
@media(max-width:800px){.lh-logo{width:52px;height:52px}.letterhead{gap:.6rem}.login .logoimg{width:64px;height:64px;margin-bottom:.9rem}}
.logoedit{display:flex;gap:1.4rem;align-items:center;flex-wrap:wrap}
.logoprev{width:120px;height:120px;object-fit:contain;border-radius:50%;background:#fff;padding:4px;box-shadow:inset 3px 3px 7px var(--sh-d),inset -3px -3px 7px var(--sh-l)}
.logoprev.none{display:flex;align-items:center;justify-content:center;text-align:center;color:var(--muted);font-size:.85rem}
input[type=file]{height:auto!important;padding:.6rem .7rem}
/* ======== Search sections ======== */
.pick .searchbox{flex:1 1 320px;max-width:520px}
.sfield{position:relative}
.sfield>svg{position:absolute;left:.9rem;top:50%;transform:translateY(-50%);width:20px;height:20px;color:var(--muted);pointer-events:none}
.sfield input{padding-left:2.7rem;padding-right:2.8rem;-webkit-appearance:none;appearance:none}
.sfield input::-webkit-search-cancel-button{display:none}
.sclear{position:absolute;right:.5rem;top:50%;transform:translateY(-50%);width:2rem;height:2rem;display:flex;align-items:center;justify-content:center;border-radius:50%;color:var(--muted);text-decoration:none;font-size:1.5rem;line-height:1}
.sclear:hover{background:var(--tint);color:var(--blue)}
/* ======== Clickable teacher number ======== */
.slot button.tlink{all:unset;display:inline-flex;align-items:center;min-height:30px;padding:0 .4rem;cursor:pointer;color:var(--blue);font-weight:700;font-size:.88rem;text-decoration:underline dotted;text-underline-offset:3px;border-radius:6px;-webkit-tap-highlight-color:transparent}
.slot button.tlink:hover,.slot button.tlink[aria-expanded=true]{background:rgba(45,50,200,.12)}
.slot button.tlink:focus-visible{outline:3px solid var(--gold);outline-offset:2px}
.slot .tname{display:none;font-weight:700;color:var(--navy);font-size:.88rem}
.slot .tname.show{display:block}
/* ======== Computed time ======== */
.hm{display:block;font-weight:400;font-size:.78rem;color:var(--muted);margin-top:.1rem}
@media print{
.lh-logo{width:66px!important;height:66px!important}
.slot button.tlink{display:inline-flex!important;color:inherit!important;text-decoration:none!important;min-height:0!important;padding:0!important}
.slot .tname{font-size:9px}
.hm{font-size:8px}
.backbtn{display:none!important}
}
html.pm .lh-logo{width:66px;height:66px}
@media print{
.slot button.tlink{font-size:9px!important;min-height:0!important;padding:0!important;display:inline!important}
.slot .tname{font-size:9px!important}
main{animation:none!important;opacity:1!important;transform:none!important}
}
html.pm .slot button.tlink{font-size:9px!important;min-height:0!important;padding:0!important;display:inline!important}
html.pm .slot .tname{font-size:9px!important}
html.pm main{animation:none!important;opacity:1!important;transform:none!important}
/* ======== Flat formal theme ======== */
body{background:#f3f5fb}
main{animation:fadein .35s ease}
@keyframes fadein{from{opacity:0}to{opacity:1}}
.top{background:#fff;border-radius:0;box-shadow:none;border-bottom:3px solid var(--blue)}
.brand-logo{box-shadow:none}
body .card,body .doc,body .scroll,body .msg{box-shadow:none;border:1px solid var(--line);border-radius:8px;background:#fff}
body .msg{border-left-width:5px}
main input:not([type=checkbox]):not([type=radio]):not([type=hidden]),main select,main textarea{background:#fff;border:1px solid #b9c0d9;border-radius:6px;box-shadow:none}
main input:not([type=checkbox]):not([type=radio]):not([type=hidden]):focus,main select:focus,main textarea:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(45,50,200,.18)}
/* schedule tables: flat, no 3D */
body .scroll.gridwrap{border:1px solid #c5cbe3;border-radius:8px;box-shadow:none;background:#fff}
body .grid thead th{background:var(--navy);color:#fff;border-color:var(--navy)}
body .grid td,body .grid th{border:1px solid #d9deef}
body .grid thead th{border-color:var(--navy)}
body .grid tbody th{background:#eef0fb;color:var(--navy)}
body .grid td.recess,body .grid tbody th.recess{background:var(--recess);color:var(--recess-ink)}
body .slot{box-shadow:none;background:#e9ecfc;border-left:4px solid var(--blue);border-radius:4px}
body .slot.rec{box-shadow:none;border-left:0;background:transparent}
body .mrow .slot{box-shadow:none}
body .msum{box-shadow:none}
/* buttons: solid fills, no outlines, no 3D */
body button,body .btn{background:var(--blue);color:#fff;border:0;border-radius:6px;padding:.65rem 1.25rem;margin-bottom:0;text-shadow:none;box-shadow:none;filter:none;transform:none;font-weight:600;transition:background .15s,color .15s}
body button:hover,body .btn:hover{background:var(--blue-d);box-shadow:none;filter:none;transform:none}
body button:active,body .btn:active{background:#2a41b8;box-shadow:none;transform:none}
body button:disabled{opacity:.6;cursor:wait;box-shadow:none;transform:none}
body .btn.plain,body button.plain{background:#e3e7fb;color:var(--navy);border:0;box-shadow:none}
body .btn.plain:hover,body button.plain:hover{background:#cfd6f6;color:var(--navy);box-shadow:none}
body .btn.plain:active,body button.plain:active{background:#bfc8f2;box-shadow:none;transform:none}
body button.danger{background:#fbe4e4;color:var(--bad);border:0;box-shadow:none;text-shadow:none}
body button.danger:hover{background:var(--bad);color:#fff;box-shadow:none}
body button.danger:active{background:#7a2020;box-shadow:none}
body .small,body .btn.small,body button.small{padding:.4rem .9rem;border-radius:6px;margin-bottom:0;box-shadow:none}
body .btn.plain.small,body button.plain.small{box-shadow:none}
body button.dark{background:#1c2133;border:0;border-radius:6px;box-shadow:none;padding:.85rem;margin-bottom:0}
body button.dark:hover{background:#000}
body .daytab{background:#e3e7fb;color:var(--navy);border:0;border-radius:6px;box-shadow:none;margin-bottom:0}
body .daytab.on{background:var(--blue);color:#fff;box-shadow:none}
body .menubtn,body .menubtn:hover,body .menubtn:active{background:#e3e7fb;color:var(--navy);border:0;border-radius:6px;box-shadow:none;margin-bottom:0}
body .backbtn{background:#e3e7fb;color:var(--navy);border:0;border-radius:6px;box-shadow:none;margin-bottom:0;transform:none}
body .backbtn:hover{background:#cfd6f6;transform:none}
body .backbtn:active{background:#bfc8f2;box-shadow:none;transform:none}
body .top .tabs a,body .top .acct a{background:#eef0fb;color:var(--navy);border:0;border-radius:6px;box-shadow:none}
body .top .tabs a:hover,body .top .acct a:hover{background:#d9def8}
body .top .tabs a.on{background:var(--blue);color:#fff;box-shadow:none}
body .chk{box-shadow:none;border:0;border-radius:6px;background:#eef0fb}
body .chk:has(input:checked){box-shadow:none;background:#d5dbf8}
/* ======== Opening intro ======== */
#intro{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:.9rem;background:linear-gradient(160deg,#2c31c9,#1a1d85);color:#fff;text-align:center;padding:2rem;cursor:pointer;transition:opacity .6s ease,visibility .6s}
#intro.hide{opacity:0;visibility:hidden}
html.introseen #intro{display:none}
#intro .i-logo{width:150px;height:150px;object-fit:contain;background:transparent;border-radius:0;padding:0;filter:drop-shadow(0 0 2px rgba(255,255,255,.7)) drop-shadow(0 0 8px rgba(255,255,255,.35));animation:ifade .6s ease both}
#intro h1{color:#fff;font-size:clamp(1.6rem,4.2vw,2.6rem);margin:.4rem 0 0;animation:irise .8s .25s both}
#intro .i-sch{color:#e6e8ff;font-weight:600;font-size:1.1rem;animation:irise .8s .4s both}
@keyframes ifade{from{opacity:0}to{opacity:1}}
#intro .i-sub{color:#b9bdf3;font-size:.95rem;animation:irise .8s .55s both}
#intro .i-bar{width:min(260px,70vw);height:4px;background:rgba(255,255,255,.25);border-radius:4px;overflow:hidden;margin-top:1rem}
#intro .i-bar i{display:block;height:100%;width:0;background:var(--recess);animation:iload 2.3s .2s ease-out forwards}
body #intro button.i-skip{background:rgba(255,255,255,.16);color:#fff;margin-top:1rem;padding:.5rem 1.2rem;font-size:.9rem}
body #intro button.i-skip:hover{background:rgba(255,255,255,.28)}
@keyframes ipop{from{transform:scale(.6);opacity:0}to{transform:scale(1);opacity:1}}
@keyframes irise{from{transform:translateY(14px);opacity:0}to{transform:none;opacity:1}}
@keyframes iload{to{width:100%}}
@media(prefers-reduced-motion:reduce){ #intro *{animation:none!important}#intro .i-bar i{width:100%}main{animation:none}}
@media print{ #intro{display:none!important}}
@media print{
.doc{padding:0!important;margin:0!important;border:0!important;border-radius:0!important;box-shadow:none!important;background:#fff!important;width:auto!important}
.doc + .doc{break-before:page!important;page-break-before:always!important}
.meta{display:flex!important;flex-direction:row!important;flex-wrap:nowrap!important;justify-content:space-between!important;gap:0 2rem!important;font-size:10px!important;line-height:1.3!important;margin:4px 0!important}
.meta > div{flex:1 1 50%!important;min-width:0!important;margin:0!important}
.doc-title{font-size:15px!important;margin:2px 0 0!important}
.gridwrap{display:block!important;overflow:visible!important;border:0!important;background:none!important}
.mobile-days{display:none!important}
.grid{min-width:0!important;width:100%!important;table-layout:fixed!important;font-size:9px!important}
.grid th, .grid td, .grid thead th, .grid tbody th{font-size:9px!important;line-height:1.2!important;padding:2px 3px!important;white-space:normal!important;width:auto!important}
.grid td.num{white-space:nowrap!important}
.slot{min-height:0!important;padding:1px 3px!important;font-size:9px!important;border-radius:0!important}
.slot strong{font-size:9px!important}
.sign{display:grid!important;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))!important;margin-top:6px!important;gap:2px 1rem!important}
.sign .name{margin-top:12px!important;font-size:10px!important}
.sign .role, .sign .title, .legend{font-size:9px!important}
.room{font-size:12px!important;margin:3px 0!important}
}
html.pm .doc{padding:0!important;margin:0!important;border:0!important;border-radius:0!important;box-shadow:none!important;background:#fff!important;width:auto!important}
html.pm .doc + .doc{break-before:page!important;page-break-before:always!important}
html.pm .meta{display:flex!important;flex-direction:row!important;flex-wrap:nowrap!important;justify-content:space-between!important;gap:0 2rem!important;font-size:10px!important;line-height:1.3!important;margin:4px 0!important}
html.pm .meta > div{flex:1 1 50%!important;min-width:0!important;margin:0!important}
html.pm .doc-title{font-size:15px!important;margin:2px 0 0!important}
html.pm .gridwrap{display:block!important;overflow:visible!important;border:0!important;background:none!important}
html.pm .mobile-days{display:none!important}
html.pm .grid{min-width:0!important;width:100%!important;table-layout:fixed!important;font-size:9px!important}
html.pm .grid th,html.pm .grid td,html.pm .grid thead th,html.pm .grid tbody th{font-size:9px!important;line-height:1.2!important;padding:2px 3px!important;white-space:normal!important;width:auto!important}
html.pm .grid td.num{white-space:nowrap!important}
html.pm .slot{min-height:0!important;padding:1px 3px!important;font-size:9px!important;border-radius:0!important}
html.pm .slot strong{font-size:9px!important}
html.pm .sign{display:grid!important;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))!important;margin-top:6px!important;gap:2px 1rem!important}
html.pm .sign .name{margin-top:12px!important;font-size:10px!important}
html.pm .sign .role,html.pm .sign .title,html.pm .legend{font-size:9px!important}
html.pm .room{font-size:12px!important;margin:3px 0!important}
/* ---- boxed sign-in / sign-up card ---- */
.login .auth-body{background:#fff;border:1.5px solid #cfd6ea;border-radius:16px;padding:2rem 2rem 1.6rem;margin:auto 0;box-shadow:0 12px 32px rgba(27,31,122,.12),0 2px 6px rgba(27,31,122,.06)}
.login .auth-body h2{padding-bottom:.7rem;margin-bottom:.8rem;border-bottom:2px solid var(--blue)}
.login .auth-body input:not([type=checkbox]):not([type=radio]):not([type=hidden]),.login .auth-body select{border:1.5px solid #cfd6ea;border-radius:8px;padding:.65rem .8rem;background:#f8faff;margin-top:.3rem}
.login .auth-body input:focus,.login .auth-body select:focus{outline:0;border-color:var(--blue);background:#fff;box-shadow:0 0 0 3px rgba(44,49,201,.15)}
.login .auth-body .tidfield{margin-top:.3rem}
.login .auth-body .tidfield .tidfix{border:1.5px solid #cfd6ea;border-right:0;border-radius:8px 0 0 8px;background:#eef2fb;color:var(--navy)}
.login .auth-body .tidfield input{margin-top:0!important;border-left:0!important}
.login .auth-body label{margin-top:1rem}
.login .auth-body button.dark{border-radius:8px;box-shadow:0 6px 14px rgba(17,17,17,.25)}
@media(max-width:800px){.login .auth-body{padding:1.4rem 1.2rem 1.2rem;border-radius:14px}}
.brandrow{display:flex;align-items:center;gap:.9rem;margin-bottom:2.2rem}
.login .brandrow .logo,.login .brandrow .logoimg{margin-bottom:0;flex:none}
.brandschool small{display:block;font-weight:500;font-size:.8rem;letter-spacing:.04em;color:#c9ccf7;margin-top:.15rem}
.brandschool{font-size:.95rem;font-weight:600;letter-spacing:.03em;line-height:1.3;color:#e6e8ff;max-width:13rem}
@media(max-width:800px){.brandrow{margin-bottom:.9rem;gap:.7rem}.brandschool{font-size:.85rem}}
@media(min-width:801px){
.login .brandrow{gap:1.2rem;align-items:center;margin-bottom:2rem}
.login .brandrow .logoimg,.login .brandrow .logo{width:108px;height:108px}
.login .brandrow .brandschool{font-family:"Poppins","Segoe UI",Arial,sans-serif;font-size:1.3rem;font-weight:600;line-height:1.25;letter-spacing:0;max-width:20rem;color:#fff;align-self:center;text-wrap:balance}
.login .brandrow .brandschool small{font-family:"Inter","Segoe UI",Arial,sans-serif;font-size:.9rem;font-weight:500;letter-spacing:.05em;margin-top:.45rem}
}

/* ======== Typography refresh ======== */
body{font-family:"Inter","Segoe UI",Arial,sans-serif;font-size:16px;line-height:1.6;letter-spacing:.005em;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
h1,h2,h3,.brand-name,.letterhead .school,.doc-title,.room,.login .side h1,.login .auth-body h2,#intro h1{font-family:"Poppins","Segoe UI",Arial,sans-serif;letter-spacing:-.01em}
h1{font-size:2rem;font-weight:700;line-height:1.2}
h2{font-size:1.4rem;font-weight:600;line-height:1.3}
h3{font-size:1.15rem;font-weight:600;line-height:1.3}
main h1::after{content:"";display:block;width:52px;height:4px;margin-top:.5rem;border-radius:4px;background:linear-gradient(90deg,var(--blue),var(--gold))}
label{font-weight:600;font-size:.92rem;color:#2b3350;letter-spacing:.01em}
input,select,textarea{font-size:1rem;font-family:inherit}
button,.btn{font-family:"Inter","Segoe UI",Arial,sans-serif;font-weight:600;letter-spacing:.01em}
.hint{font-size:.88rem;line-height:1.45}
.msg{font-size:.97rem}
.list th{font-family:"Poppins","Segoe UI",Arial,sans-serif;font-weight:600;font-size:.88rem;letter-spacing:.02em}
.list td{font-size:.97rem}
.grid thead th{font-family:"Poppins","Segoe UI",Arial,sans-serif;font-weight:600;font-size:.92rem;letter-spacing:.02em}
.slot strong{font-weight:600}
.legend{font-size:.92rem}
.login .auth-body h2{font-size:1.55rem;font-weight:700}
@media(max-width:800px){h1{font-size:1.55rem}h2{font-size:1.25rem}}

/* ======== Menu button: three lines ======== */
.menubtn{display:none;width:48px;height:48px;padding:0;align-items:center;justify-content:center}
.bars{position:relative;display:block;width:24px;height:18px}
.bars i{position:absolute;left:0;right:0;height:3px;border-radius:3px;background:currentColor;transition:transform .25s,opacity .2s,top .25s}
.bars i:nth-child(1){top:0}.bars i:nth-child(2){top:7.5px}.bars i:nth-child(3){top:15px}
.top.open .bars i:nth-child(1){top:7.5px;transform:rotate(45deg)}
.top.open .bars i:nth-child(2){opacity:0}
.top.open .bars i:nth-child(3){top:7.5px;transform:rotate(-45deg)}
@media(max-width:1100px){body .menubtn{display:inline-flex}}

/* ======== Pressed and loading states ======== */
html{-webkit-tap-highlight-color:transparent}
body button:not(.eye):not(.tlink):not(.sclear),body .btn,body .backbtn,body .daytab{-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}
.chk:active{background:#c9d1f7}
body button.busy{cursor:wait}
body button.busy:disabled{opacity:.92}
body button.busy::after{content:"";display:inline-block;width:1em;height:1em;margin-left:.6rem;border:2px solid rgba(255,255,255,.45);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;vertical-align:-.15em}
body button.plain.busy::after,body button.danger.busy::after{border-color:rgba(45,50,200,.25);border-top-color:var(--blue)}
body button.dark.busy{background:#2d32c8}
@keyframes spin{to{transform:rotate(360deg)}}

/* ======== Report a problem, notifications ======== */
.reportlnk{display:flex!important;align-items:center;justify-content:center;gap:.5rem;margin-top:.9rem;width:100%}
.photoprev{display:block;max-width:100%;max-height:220px;margin-top:.6rem;border-radius:8px;border:1px solid var(--line)}
.photoprev[hidden],.badge[hidden],.sclear[hidden],.toast[hidden]{display:none!important}
.badge{display:inline-block;min-width:1.35rem;padding:0 .4rem;margin-left:.45rem;border-radius:999px;background:#d92d2d;color:#fff;font-size:.75rem;font-weight:700;line-height:1.35rem;text-align:center}
a.msg{display:block;text-decoration:none}
.msg.notice{background:#fff6dc;border-color:var(--gold);color:#5a4210}
.pill{display:inline-block;padding:.15rem .6rem;border-radius:999px;font-size:.75rem;font-weight:700;margin-left:.3rem}
.pill.new{background:#fde68a;color:#5a4210}.pill.ok{background:#d1fae5;color:#14532d}
.report.fresh{border-left:5px solid var(--gold)}.report.done{opacity:.8}
.rhead{display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap}
.rmsg{white-space:pre-wrap;margin:.7rem 0;overflow-wrap:anywhere}
.rphoto{max-width:100%;max-height:340px;border-radius:8px;border:1px solid var(--line);display:block}
.toast{position:fixed;left:50%;bottom:1.2rem;transform:translateX(-50%);max-width:92vw;background:#1c2133;color:#fff;padding:.8rem 1.2rem;border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.3);z-index:9000;display:flex;gap:1rem;align-items:center}
.toast a{color:#ffd966;font-weight:700}
body .toast button.toastx{background:transparent;padding:0 .4rem;font-size:1.4rem;line-height:1;min-height:0;color:#fff}

/* ======== Teacher search ======== */
.tsearch{margin:0 0 1rem;max-width:560px}
[data-find][hidden],#tqnone[hidden]{display:none!important}
.tresults{list-style:none;margin:.6rem 0 0;padding:0;display:grid;gap:.4rem}
.tresults a{display:flex;justify-content:space-between;gap:1rem;padding:.65rem .9rem;border:1px solid var(--line);border-radius:8px;background:#fff;text-decoration:none;color:var(--navy);font-weight:600}
.tresults a:hover{background:var(--tint)}
.tresults small{color:var(--muted);font-weight:500}

/* ======== Notification bell ======== */
body .bell,body .top .acct a.bell{position:relative;display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;min-height:44px;padding:0;border-radius:50%;background:#e3e7fb;color:var(--navy);overflow:visible;text-decoration:none}
body .top .acct a.bell{justify-content:center;width:44px}
.bell .badge{position:absolute;top:-4px;right:-4px;margin:0}
body .bell.on{background:var(--blue);color:#fff}
body .bell:active{background:#d9def8;color:var(--navy);transform:none}
.bell.mob{display:none!important}
@media(max-width:1100px){.bell.mob{display:inline-flex!important;margin-left:auto;margin-right:.6rem}.acct .bell.desk{display:none!important}}
.note.fresh{border-left:5px solid var(--gold)}

/* ======== Type filter (Excel-style V button) ======== */
.typeth{position:relative}
.thwrap{display:inline-flex;align-items:center;gap:.4rem}
body button.vbtn{min-height:0;width:26px;height:26px;padding:0;border-radius:6px;background:#e3e7fb;color:var(--navy);display:inline-flex;align-items:center;justify-content:center;box-shadow:none}
.typeth.open .vbtn,.typeth.active .vbtn{background:var(--blue);color:#fff}
.list th.typeth.open,.list th.typeth.active{background:#dfe4fb;color:var(--blue)}
td.typecell.hl{background:#eef1ff;font-weight:600;color:var(--blue)}
.vmenu{position:fixed;z-index:200;min-width:240px;background:#fff;border:1px solid var(--line);border-radius:10px;box-shadow:0 12px 30px rgba(20,25,80,.28);padding:.35rem;display:grid;gap:.15rem;text-align:left;font-family:"Inter","Segoe UI",Arial,sans-serif}
.vmenu[hidden]{display:none}
body .vmenu button.vopt{background:transparent;color:var(--navy);box-shadow:none;border:0;text-align:left;justify-content:flex-start;padding:.6rem .75rem;font-weight:500;border-radius:6px;width:100%;min-height:0;display:block}
body .vmenu button.vopt:hover{background:#eef0fb}
body .vmenu button.vopt.on{background:var(--blue);color:#fff;font-weight:600}
.typesel{display:none;margin:0 0 1rem;max-width:560px}
@media(max-width:800px){.typesel{display:block}}

/* ======== Save / Cancel button rows ======== */
body .btnrow{display:flex;flex-wrap:wrap;gap:.7rem;align-items:stretch;margin:1.2rem 0 0}
body .btnrow>*{margin:0}
body .btnrow button,body .btnrow .btn{display:inline-flex;align-items:center;justify-content:center;min-height:46px;padding:0 1.4rem;line-height:1.2;text-align:center;vertical-align:top}
@media(max-width:800px){body .btnrow>*{flex:1 1 0;min-width:0}}

/* ======== Screenshots ======== */
.thumbs{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:.6rem;margin-top:.6rem}
.thumbs:empty{display:none}
.thumb{position:relative;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff}
.thumb img{display:block;width:100%;height:110px;object-fit:cover}
body .thumb button.thumbx{position:absolute;top:4px;right:4px;width:28px;height:28px;min-height:0;padding:0;border-radius:50%;background:rgba(28,33,51,.85);color:#fff;font-size:1.2rem;line-height:1;display:flex;align-items:center;justify-content:center}
body .brand-logo{background:transparent;border-radius:0;padding:0;box-shadow:none;filter:drop-shadow(0 0 2px rgba(255,255,255,.8)) drop-shadow(0 1px 4px rgba(27,31,122,.25))}
.login .logoimg{background:transparent;border-radius:0;padding:0;box-shadow:none;filter:drop-shadow(0 0 2px rgba(255,255,255,.7)) drop-shadow(0 0 8px rgba(255,255,255,.35))}
.otime{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap}
.otime input[type=time]{flex:1 1 7.5rem;min-width:7.5rem}
.minedit select{width:100%;min-width:7rem}
.assign select{min-width:130px}
.progitem{margin:0 0 2.6rem;padding-bottom:1.4rem;border-bottom:2px dashed #c5cbe3;min-height:70vh;scroll-margin-top:1rem}
.progitem:last-child{border-bottom:0}
.progitem .doc{margin:.4rem 0 .6rem}
.progitem .grid tbody tr{height:3.4rem}
body button.fabtop{position:fixed;right:1.1rem;bottom:1.1rem;z-index:150;width:54px;height:54px;min-height:0;padding:0;border-radius:50%;display:flex;align-items:center;justify-content:center;box-shadow:0 6px 18px rgba(27,31,122,.4)}
body button.fabtop svg{width:26px;height:26px}
.fabtop[hidden]{display:none!important}
body button.fabtop{position:fixed!important;right:1.1rem;right:max(1.1rem,env(safe-area-inset-right));bottom:1.1rem;bottom:max(1.1rem,env(safe-area-inset-bottom));overflow:visible}
@media(max-width:800px){body button.fabtop{width:48px;height:48px;right:.8rem;bottom:.9rem}}
button.linklike{all:unset;cursor:pointer;color:var(--blue);text-decoration:underline;font-weight:600;font-size:.9rem}
a.btn.signout{background:#fff;color:var(--bad);border:1px solid var(--bad)}
a.btn.signout:hover{background:var(--bad);color:#fff}
.advtag{display:inline-block;margin:0 0 .5rem;padding:.25rem .7rem;border-radius:999px;background:#fff4d6;color:#7a5200;font-weight:700;font-size:.85rem}
.helpfab.inline{position:relative;top:auto;right:auto;margin-left:auto;flex:none}
@media print{.progitem{margin:0!important;padding:0!important;border:0!important;min-height:0!important}.progitem+.progitem{break-before:page!important;page-break-before:always!important}}
html.pm .progitem{margin:0!important;padding:0!important;border:0!important;min-height:0!important}
html.pm .progitem+.progitem{break-before:page!important;page-break-before:always!important}
.rgallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:.6rem;margin-top:.6rem}
.rgallery img{width:100%;height:150px;object-fit:cover;border-radius:8px;border:1px solid var(--line);display:block}
"""

ADDON_CSS = """
.steps{display:flex;flex-wrap:wrap;gap:.4rem;margin:0 0 1rem}
.step{padding:.4rem .9rem;border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--navy);text-decoration:none;font-weight:600;font-size:.9rem}
.step.on{background:var(--blue);color:#fff;border-color:var(--blue)}
@media(hover:hover){.step:hover:not(.on){background:var(--tint);border-color:var(--blue)}}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem;margin:.6rem 0}
.kpi{background:var(--tint);border:1px solid var(--line);border-radius:8px;padding:.7rem .9rem}
.kpi b{display:block;font:700 1.6rem "Poppins","Segoe UI",sans-serif;color:var(--navy)}.kpi span{color:var(--muted);font-size:.85rem}
.kpi.bad b{color:var(--bad)}.kpi.ok b{color:var(--ok)}
.mx{border-collapse:collapse;width:auto;min-width:100%}.mx td,.mx th{border:1px solid var(--line);text-align:center;padding:.35rem .45rem;font-size:.85rem}
.mx th{background:var(--tint);color:var(--navy)}.mx td.l,.mx th.l{text-align:left}
.ck{margin:0}
.tt{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9rem;min-height:12rem}
.why{color:var(--bad)}.okt{color:var(--ok)}
.bar{height:8px;background:var(--tint);border-radius:99px;overflow:hidden;min-width:70px}.bar i{display:block;height:100%;background:var(--blue)}
details.card>summary{cursor:pointer;font-weight:600;color:var(--navy)}
ul.issues{margin:.3rem 0 0;padding-left:1.2rem}ul.issues li{margin:.2rem 0}

/* ======== Admin main navigation (the 11 menu items) ======== */
.shell{display:block}
.mainnav,.side{display:flex;flex-direction:column;gap:.45rem}
.mn{display:grid;grid-template-columns:2rem 2.4rem minmax(0,1fr) 1.2rem;align-items:center;gap:.5rem;padding:.7rem .8rem;border-radius:14px;text-decoration:none;color:var(--ink);background:#fff;border:1px solid var(--line);min-height:62px}
.mn:hover{background:var(--tint)}
.mn.on{background:var(--blue);border-color:var(--blue);color:#fff}
.mn-num{font:600 .82rem "Poppins","Segoe UI",sans-serif;color:var(--muted);text-align:center}
.mn-ic{display:flex;align-items:center;justify-content:center;color:var(--navy)}
.mn-tx b{display:block;font:600 1rem/1.2 "Poppins","Segoe UI",sans-serif;white-space:normal}
.mn-tx small{display:block;font-size:.8rem;line-height:1.3;color:var(--muted);margin-top:.1rem;white-space:normal}
.mn-go{color:var(--muted)}
.mn.on .mn-num,.mn.on .mn-ic,.mn.on .mn-tx small,.mn.on .mn-go{color:#fff}
.side-h{font:700 .78rem "Poppins","Segoe UI",sans-serif;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);padding:.2rem .4rem .3rem}
.side-f{display:flex;flex-wrap:wrap;gap:.3rem .9rem;padding:.8rem .4rem 0;font-size:.9rem}
.side{display:none}
@media(min-width:1101px){
 .shell{display:grid;grid-template-columns:318px minmax(0,1fr);align-items:start;max-width:1640px;margin:0 auto}
 .side{display:flex;position:sticky;top:0;max-height:100vh;overflow-y:auto;padding:1rem .8rem 2rem 1rem}
 body .top .mainnav,body .top .admtabs{display:none!important}
 body .top .in{grid-template-areas:"brand acct"}
 .shellmain main{max-width:1180px;margin-left:0}
 .shellmain footer{text-align:left;padding-left:1.2rem}
}
@media(max-width:1100px){
 body .top nav{width:min(420px,calc(100vw - 1rem))!important;right:.5rem!important;max-height:calc(100vh - 90px)}
 body .top .mainnav{gap:.4rem}
 body .top .mn{min-height:60px;background:#fff}
 body .top .mn.on{background:var(--blue)}
 body .top .admtabs{margin-top:.2rem}
}
@media print{.shell{display:block!important}.side{display:none!important}}
/* ======== Alignment fixes (navigation and whole system) ======== */
*,*::before,*::after{box-sizing:border-box}
/* Navigation cards: never shrink or clip, same grid on desktop sidebar and mobile menu */
.mainnav,.side,body .top .mainnav{align-items:stretch}
body .top .mainnav{flex:0 0 auto;overflow:visible;width:100%}
.mn,body .top nav a.mn{flex:0 0 auto;display:grid;grid-template-columns:2rem 2.4rem minmax(0,1fr) 1.2rem;align-items:center;column-gap:.5rem;width:100%;height:auto;min-height:64px;margin:0;padding:.65rem .8rem;overflow:visible;line-height:1.2;box-shadow:none;border:1px solid var(--line);border-radius:14px;background:#fff;color:var(--ink)}
.mn:hover,body .top nav a.mn:hover{background:var(--tint)}
.mn.on,body .top nav a.mn.on{background:var(--blue);border-color:var(--blue);color:#fff;box-shadow:none}
.mn-num{align-self:center;justify-self:center;line-height:1}
.mn-ic{align-self:center;justify-self:center;width:2.4rem;height:2.4rem}
.mn-ic svg,.mn-go{display:block;flex:none}
.mn-go{justify-self:center;align-self:center}
.mn-tx{align-self:center;min-width:0}
.mn-tx b,.mn-tx small{overflow-wrap:break-word;word-break:normal}
.side-f a{white-space:nowrap}
@media(max-width:480px){
 .mn,body .top nav a.mn{grid-template-columns:1.6rem 2rem minmax(0,1fr) 1rem;column-gap:.4rem;padding:.6rem .6rem;min-height:60px}
 .mn-ic{width:2rem;height:2rem}
 .mn-tx b{font-size:.95rem}.mn-tx small{font-size:.76rem}
}
/* Forms: labels and fields line up from the top even when one field has a hint */
.formgrid{align-items:start}
.formgrid>div{min-width:0}
.formgrid input:not([type=checkbox]):not([type=radio]),.formgrid select,.formgrid textarea{width:100%;max-width:100%}
.formgrid .hint{margin:.3rem 0 0}
/* Tables: centred cells, buttons in one tidy column, no overflow of the page */
table.list th,table.list td{vertical-align:middle}
.scroll{max-width:100%;-webkit-overflow-scrolling:touch}
.row-acts{justify-content:flex-end}
.row-acts .btn,.row-acts button{display:inline-flex;align-items:center;justify-content:center;white-space:nowrap}
.btnrow .btn,.btnrow button{display:inline-flex;align-items:center;justify-content:center}
img,svg,video,canvas{max-width:100%}
main,.shellmain{min-width:0}
.howto{margin:.4rem 0 0;padding-left:1.3rem}.howto li{margin:.4rem 0;line-height:1.45}
/* ======== Compact desktop sidebar and design polish ======== */
.navsep{font:700 .72rem "Poppins","Segoe UI",sans-serif;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);padding:.9rem .4rem .2rem;border-top:1px solid var(--line);margin-top:.5rem}
body.sidemini .navsep span{display:none}
.autocard{border-left:4px solid var(--blue)}
.autocard button{font-size:1rem;padding:.75rem 1.3rem}
.side-h{display:flex;align-items:center;justify-content:space-between;gap:.4rem}
.side-toggle{display:none}
@media(min-width:1101px){
 .shell{grid-template-columns:240px minmax(0,1fr);transition:grid-template-columns .2s ease}
 body.sidemini .shell{grid-template-columns:76px minmax(0,1fr)}
 .side{padding:.9rem .6rem 2rem .8rem;gap:.12rem}
 .side .mn{grid-template-columns:1.6rem 1.5rem minmax(0,1fr);column-gap:.5rem;min-height:0;height:auto;padding:.5rem .65rem;border:0;border-radius:10px;background:transparent;box-shadow:none}
 .side .mn-go,.side .mn-tx small{display:none}
 .side .mn-tx b{font-size:.9rem;font-weight:500;line-height:1.25}
 .side .mn-num{font-size:.72rem}
 .side .mn:hover{background:var(--tint)}
 .side .mn.on{background:var(--blue);color:#fff;box-shadow:0 4px 12px rgba(45,50,200,.28)}
 .side .mn.on .mn-tx b{font-weight:600}
 .side-toggle{display:inline-flex;align-items:center;justify-content:center;width:1.7rem;height:1.7rem;padding:0;background:transparent;color:var(--navy);box-shadow:none;border-radius:8px;font-size:1.3rem;line-height:1}
 .side-toggle:hover{background:var(--tint)}
 .side-toggle .ex{display:none}
 body.sidemini .shell>.side{padding:.9rem .5rem 2rem}
 body.sidemini .side-h{justify-content:center}
 body.sidemini .side-h span:first-child,body.sidemini .shell>.side .mn-num,body.sidemini .shell>.side .mn-tx,body.sidemini .side-f{display:none}
 body.sidemini .shell>.side .mn{grid-template-columns:1fr;justify-items:center;padding:.6rem 0}
 body.sidemini .side-toggle .cl{display:none}
 body.sidemini .side-toggle .ex{display:inline}
}
/* Design polish: consistent shapes, focus rings and feedback */
:root{--ring:0 0 0 3px rgba(45,50,200,.25)}
body{-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
*{scrollbar-width:thin;scrollbar-color:#b6bde6 transparent}
::selection{background:#d9dcff}
h1{letter-spacing:-.01em}
input,select,textarea{border:1px solid #c3cae3;border-radius:10px;padding:.62rem .8rem;transition:border-color .15s,box-shadow .15s}
input:hover,select:hover,textarea:hover{border-color:#9aa5d6}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--blue);box-shadow:var(--ring)}
button,.btn{border-radius:10px;padding:.62rem 1.15rem;transition:background .15s,box-shadow .15s,transform .06s}
button:not(.plain):not(.danger):not(.side-toggle):not(.eye):hover,.btn:not(.plain):not(.danger):hover{background:var(--blue-d)}
button:active,.btn:active{transform:translateY(1px)}
button:focus-visible,.btn:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid rgba(45,50,200,.4);outline-offset:2px}
table.list tbody tr{transition:background .12s}
table.list tbody tr:hover{background:rgba(45,50,200,.045)}
.msg{border-radius:12px}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition-duration:.01ms!important;animation-duration:.01ms!important}}
/* ======== Sign-in card (Teacher / Admin) ======== */
[hidden]{display:none!important}
.lgwrap{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:1.2rem;background:#e8edf5}
.lgcard{width:100%;max-width:780px;background:#1d3f72;border-radius:34px;padding-top:32px;box-shadow:0 18px 50px rgba(28,61,111,.16)}
.lginner{background:#fff;border-radius:34px;padding:2.6rem 3rem 2.4rem}
.lgtabs{display:flex;border:2px solid #d9e0ee;border-radius:18px;background:#eef2f8;overflow:hidden;margin-bottom:2rem}
.lgtabs button{flex:1;border:0;border-radius:0;background:transparent;color:#6b7a99;font-weight:800;font-size:1.05rem;letter-spacing:.02em;padding:1.1rem .5rem;box-shadow:none;text-transform:uppercase}
.lgtabs button.on{background:#1d3f72;color:#fff}
.lgtabs button:not(.on):hover{background:#e3e9f4;color:#1d3f72}
h1.lgtitle{text-align:center;color:#1d3f72;font-size:clamp(1.9rem,5vw,2.6rem);line-height:1.15;margin:.2rem 0 .5rem;border:0;padding:0}
h1.lgtitle::after{display:none}
.lgsub{text-align:center;color:#6b7a99;font-weight:700;margin:0 0 1.8rem;font-size:1.05rem}
.lglabel{display:block;font-weight:800;text-transform:uppercase;color:#111;margin:1.3rem 0 .35rem}
.lghelp{display:block;color:#6b7a99;font-size:.84rem;font-weight:700;margin:0 0 .6rem}
.lginner input:not([type=checkbox]){width:100%;border:2px solid #d9e0ee;border-radius:16px;background:#fbfcff;padding:1.05rem 1.1rem;font-size:1.05rem}
.lginner input:focus{border-color:#1d3f72;box-shadow:0 0 0 3px rgba(29,63,114,.2)}
.lginner .tidfield{display:flex;align-items:stretch}
.lginner .tidfield .tidfix{display:flex;align-items:center;padding:0 1rem;background:#eef2f8;border:2px solid #d9e0ee;border-right:0;border-radius:16px 0 0 16px;font-weight:800;color:#1d3f72}
.lginner .tidfield input{border-radius:0 16px 16px 0}
.lgcode{text-align:center;letter-spacing:.5em;font-size:1.6rem!important;font-weight:800}
button.lgbtn{width:100%;background:#1d3f72;color:#fff;border-radius:16px;padding:1.15rem;font-weight:800;font-size:1.2rem;margin-top:1.8rem;box-shadow:none}
button.lgbtn:not(.plain):not(.danger):not(.side-toggle):hover{background:var(--blue-d)}
.lglinks{text-align:center;margin-top:1.6rem;display:flex;flex-direction:column;align-items:center;gap:.9rem}
.lglinks a{font-weight:800;color:#1d3f72;text-decoration:underline}
.lglinks a.lgblue{color:#2a4fa0}
.lgresend{text-align:center;margin-top:1.4rem}
.lgresend .hint{display:block;margin-bottom:.3rem}
.lgresend button{background:none;box-shadow:none;color:#1d3f72;font-weight:800;text-decoration:underline;padding:.3rem}
.lgresend button:disabled{color:#8a96b0;text-decoration:none;cursor:not-allowed}
@media(max-width:600px){.lgcard{border-radius:26px;padding-top:24px}.lginner{border-radius:26px;padding:1.6rem 1.2rem}.lgtabs button{padding:.95rem .4rem}}
/* ======== Dashboard ======== */
.dash-top{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:1rem;align-items:stretch}
@media(max-width:800px){.dash-top{grid-template-columns:1fr}}
.ring{display:flex;align-items:center;gap:1.1rem}
.ring .pct{width:92px;height:92px;border-radius:50%;display:grid;place-items:center;flex:none;background:conic-gradient(var(--blue) calc(var(--p)*1%),var(--tint) 0)}
.ring .pct span{width:70px;height:70px;border-radius:50%;background:#fff;display:grid;place-items:center;font:700 1.25rem "Poppins","Segoe UI",sans-serif;color:var(--navy)}
.stepcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:.7rem;margin:.6rem 0 1rem}
.stepcard{display:block;text-decoration:none;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:12px;padding:.8rem .9rem;border-left:5px solid #c9cde4}
.stepcard.done{border-left-color:var(--ok)}.stepcard.todo{border-left-color:var(--gold)}
.stepcard b{font-family:"Poppins","Segoe UI",sans-serif;color:var(--navy)}
.stepcard small{display:block;color:var(--muted);margin-top:.2rem}
.stepcard .st{float:right;font-size:.75rem;font-weight:700;border-radius:99px;padding:.1rem .55rem}
.stepcard.done .st{background:#d1fae5;color:#14532d}.stepcard.todo .st{background:#fde68a;color:#5a4210}
.alerts{list-style:none;margin:.3rem 0 0;padding:0}
.alerts li{display:flex;gap:.7rem;align-items:flex-start;justify-content:space-between;padding:.55rem .2rem;border-top:1px solid var(--line)}
.alerts li:first-child{border-top:0}
.alerts .dot{flex:none;width:.7rem;height:.7rem;border-radius:50%;margin-top:.45rem;background:var(--gold)}
.alerts .bad .dot{background:var(--bad)}.alerts .ok .dot{background:var(--ok)}
.alerts .t{flex:1;min-width:0;overflow-wrap:anywhere}
/* ======== Curriculum / pickers ======== */
.cur-note{background:var(--tint);border:1px solid var(--line);border-radius:10px;padding:.7rem .9rem;margin:.5rem 0 1rem}
.cur-name{font-weight:600}.cur-spec{display:block;font-size:.82rem;color:var(--muted)}
table.list td input[type=number]{max-width:7.5rem}
.specpick{min-width:220px}
.specpick .sp-text{display:none;white-space:normal;overflow-wrap:anywhere;font-size:.93rem}
.specpick details.sp-box{border:1px solid var(--line);border-radius:10px;background:#fff;padding:.3rem .6rem}
.specpick summary{cursor:pointer;font-weight:600;color:var(--navy);font-size:.92rem}
.specpick .sp-list{max-height:260px;overflow:auto;margin-top:.4rem}
.specpick fieldset{border:0;border-top:1px solid var(--line);margin:.4rem 0 0;padding:.3rem 0 0}
.specpick legend{font-size:.78rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);padding:0}
.specpick label{display:flex;gap:.5rem;align-items:flex-start;font-weight:400;font-size:.9rem;margin:.15rem 0}
.specpick input[type=checkbox]{margin-top:0}
.specpick .sp-tools{position:sticky;top:0;background:#fff;padding:.1rem 0 .4rem;z-index:1}
.specpick .sp-qrow{display:flex;gap:.4rem;align-items:center}.specpick .sp-q{flex:1 1 auto;min-width:0;margin:0}
.specpick .sp-acts{display:flex;flex-wrap:wrap;gap:.4rem .6rem;align-items:center;margin-top:.4rem}
.specpick .sp-res{margin-left:auto;font-size:.8rem;color:var(--muted)}
.specpick .sp-empty{margin:.5rem .2rem;color:var(--muted);font-size:.9rem}
.specpick .sp-pop button.small{padding:.25rem .6rem;font-size:.82rem;min-height:34px}
.specpick label.sp-nomatch,.specpick fieldset.sp-nomatch,.specpick [hidden]{display:none!important}
.qi-bar .specpick details.sp-box,.qi-row .specpick details.sp-box{position:relative}
.qi-bar .specpick details.sp-box[open]>.sp-pop,.qi-row .specpick details.sp-box[open]>.sp-pop{position:absolute;left:0;top:100%;z-index:40;width:min(28rem,calc(100vw - 2.5rem));background:#fff;border:1px solid var(--line);border-radius:10px;box-shadow:0 12px 30px rgba(20,24,80,.2);padding:.55rem;margin-top:.3rem}
.qi-bar .specpick .sp-list,.qi-row .specpick .sp-list{max-height:min(46vh,320px)}

.assign tr.rowview .specpick .sp-text{display:block}
.assign tr.rowview .specpick details.sp-box{display:none}
.chipline{display:flex;flex-wrap:wrap;gap:.3rem;margin-top:.3rem}
.chip{background:var(--tint);border:1px solid var(--line);border-radius:99px;padding:.05rem .6rem;font-size:.8rem}
table.list.assign.tm{table-layout:fixed;width:100%;min-width:940px}
table.list.assign.tm th:nth-child(1){width:23%}table.list.assign.tm th:nth-child(2){width:12%}
table.list.assign.tm th:nth-child(3){width:28%}table.list.assign.tm th:nth-child(4){width:17%}
table.list.assign.tm th:nth-child(5){width:12%}table.list.assign.tm th:nth-child(6){width:8%}
.assign .specpick{min-width:0}.assign .specpick .sp-text{white-space:normal;overflow-wrap:anywhere;line-height:1.4}
.assign .specpick .sp-list{max-height:220px}
table.list.assign.tm td{vertical-align:top}
@media(max-width:800px){table.list.assign.tm{min-width:0}}
.stepcard .roles{border-top:1px dashed var(--line);margin-top:.5rem;padding-top:.4rem;font-size:.8rem}

details.tip{margin:.2rem 0 .8rem;font-size:.92rem}
details.tip summary{cursor:pointer;color:var(--muted);font-weight:600;list-style:none}
details.tip summary::before{content:"\\24D8  "}
details.tip p{margin:.4rem 0 0;color:var(--muted)}
.fitnote{border-radius:12px;padding:.8rem 1rem;margin:.6rem 0 1rem}
/* ======== timetable editor ======== */
.ttcard{border:1px solid var(--line);border-radius:12px;padding:.7rem .9rem;margin:.6rem 0;background:#fff}
.ttcard h4{margin:0 0 .5rem;font-family:"Poppins","Segoe UI",sans-serif;color:var(--navy)}
.ttrow{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.3rem 0}
.ttrow input[type=time]{width:auto}.ttrow select{width:auto}
.ttrow .x{padding:.2rem .6rem}
.user-role{display:inline-block;border-radius:99px;padding:.1rem .6rem;font-size:.78rem;font-weight:700;background:var(--tint);color:var(--navy)}
.user-role.admin{background:#fde68a;color:#5a4210}

/* ===== Table alignment: one consistent look for every data table ===== */
table.list th,table.list td{padding:.7rem .8rem;text-align:left;vertical-align:middle}
table.list th:first-child,table.list td:first-child{padding-left:1rem}
table.list th:last-child,table.list td:last-child{padding-right:1rem}
table.list th{font-size:.84rem;line-height:1.3;white-space:normal;vertical-align:middle}
.nw{white-space:nowrap}
table.list td.num,table.list th.num,.ctr{text-align:center}
/* every field inside a table cell has the same height and fills its cell */
table.list td>input:not([type=hidden]):not([type=checkbox]):not([type=radio]),table.list td>select{height:2.5rem;min-height:0;box-sizing:border-box;width:100%;min-width:0;padding:.4rem .6rem;font-size:.9rem}
table.list td .tidfield{height:2.5rem}
table.list td .tidfield input{height:100%;box-sizing:border-box;font-size:.9rem;padding:.4rem .6rem}
table.list td .tidfield .tidfix{box-sizing:border-box;font-size:.9rem}
table.list td .specpick details.sp-box{box-sizing:border-box;min-height:2.5rem}
table.list td .specpick details.sp-box>summary{line-height:1.7rem}
table.list td .row-acts{justify-content:flex-end}
table.list td input[type=checkbox]{display:block;margin:0}
/* editable rows (Teacher Management, Assignments): text and fields sit on the same line, so rows do not jump */
.assign td,.assign th{vertical-align:top}
@media(min-width:801px){
.assign .vtext{display:flex;align-items:center;min-height:2.5rem;padding:0;line-height:1.35}
.assign td:first-child .vtext{min-height:0}
.assign tr.rowedit-on{outline:0;background:#f4f6ff}
.assign tr.rowedit-on>td{box-shadow:inset 0 2px 0 #c5cbe3,inset 0 -2px 0 #c5cbe3}
.assign tr.rowedit-on>td:first-child{box-shadow:inset 2px 0 0 #c5cbe3,inset 0 2px 0 #c5cbe3,inset 0 -2px 0 #c5cbe3}
.assign td.editcell{box-shadow:-8px 0 10px -8px rgba(27,31,122,.35)}
.assign tr.rowedit-on>td.editcell{box-shadow:-8px 0 10px -8px rgba(27,31,122,.35),inset -2px 0 0 #c5cbe3,inset 0 2px 0 #c5cbe3,inset 0 -2px 0 #c5cbe3}
table.list.assign.tm td:nth-child(4),table.list.assign.tm th:nth-child(4){text-align:center}
table.list.assign.tm td:nth-child(4) .vtext{justify-content:center}
table.list.assign.tm td:nth-child(4) input{text-align:center}
table.list.assign.tm td:nth-child(5) .vtext{white-space:nowrap}}
table.list.assign .otime input{height:2.2rem}
table.list.assign td.editcell{vertical-align:top}
/* Quick Input table */
table.list.qi{table-layout:fixed;min-width:640px}
table.list.qi th:nth-child(1){width:30%}table.list.qi th:nth-child(2){width:42%}table.list.qi th:nth-child(3){width:28%}
/* Account requests table */
table.list.reqtab{table-layout:fixed;min-width:860px}
table.list.reqtab th:nth-child(1){width:150px}table.list.reqtab th:nth-child(2){width:23%}table.list.reqtab th:nth-child(3){width:150px}
table.list.reqtab th:nth-child(4){width:110px}table.list.reqtab th:nth-child(6){width:170px}

/* ======== Alignment pass ======== */
.formgrid{align-items:start}
.formgrid>.fgbtn{align-self:end;display:flex;align-items:flex-end}
.formgrid>.fgbtn::before{content:"";display:block;width:0}
.formgrid>.fgbtn button{margin:0;min-height:46px;padding:0 1.4rem;white-space:nowrap}
.formgrid>.fgbtn button.danger{min-height:46px;font-size:.95rem;padding:0 1.4rem}
.formgrid:has(>.fgbtn){align-items:end}
.formgrid select,.formgrid input:not([type=checkbox]):not([type=radio]){min-height:46px}
.card>h3:first-child,details.card>summary+h3{margin-top:0}
.card,details.card{margin-left:0;margin-right:0;max-width:100%}
details.card{padding:1rem 1.2rem}
details.card[open]>summary{margin-bottom:.4rem}
main>h1+.steps{margin-top:.6rem}
table.list td,table.list th{vertical-align:middle}
table.list td input:not([type=checkbox]),table.list td select{width:100%;min-width:0}
.row-acts{display:flex;gap:.5rem;align-items:center}.row-acts form{margin:0}
.bar{margin:.1rem 0 .3rem}
.qlegend{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 .8rem}
.qcat{padding:.3rem .8rem;border-radius:999px;font-size:.85rem;background:#fff;border:1px solid var(--line);color:var(--navy)}
.qm th.qh{font-size:.8rem;letter-spacing:.06em;text-transform:uppercase;padding:.5rem .6rem}
.qm th.qc-academic{background:#e3ebff}.qm th.qc-core{background:#e7f2ec}.qm th.qc-techpro{background:#fff1d6}.qm th.qc-other{background:#eee}
.qm th.qs{font-size:.78rem;font-weight:600;min-width:2.6rem}
.qm td.first,.qm th.first,.qm th.qh{border-left:2px solid var(--navy)}
.qm td.l,.qm th.l{position:sticky;left:0;background:#fff;z-index:1;min-width:11rem}
.qm th.l{background:var(--tint)}
.wide-sel{grid-column:span 2}
@media(max-width:600px){.wide-sel{grid-column:1/-1}}
/* Header: logo and school name hug the left edge, profile hugs the right edge (no centered container) */
body .top .in{max-width:none!important;width:100%;margin:0!important;padding-left:1.2rem;padding-right:1.2rem}
body .top .brand{justify-self:start;margin-right:auto;text-align:left}
body .top .acct{justify-self:end;margin-left:auto;justify-content:flex-end}
@media(min-width:1101px){.shell{max-width:none;margin:0}}

/* ======== SJLSHS brand layer: palette taken from the school seal (royal blue, deep navy, shield gold) ======== */
:root{--navy:#131184;--blue:#2e49cc;--blue-d:#3a55d6;--tint:#eef1fd;--paper:#f6f7fc;--line:#d9dff3;--ink:#1a2038;
--muted:#59627f;--gold:#b8861b;--gold-l:#fff4d6;--ok:#2e6b4a;--bad:#a12b2b;--warn:#8a5a00;
--r:10px;--sh1:0 1px 2px rgba(19,17,132,.06),0 2px 8px rgba(19,17,132,.05);--sh2:0 6px 20px rgba(19,17,132,.12)}
body{background:var(--paper);color:var(--ink);-webkit-font-smoothing:antialiased}
body :focus-visible{outline:3px solid var(--gold);outline-offset:2px;border-radius:6px}
body .top{border-bottom:3px solid var(--blue);box-shadow:var(--sh1)}
body .card,body .doc,body .scroll{border-radius:var(--r);border-color:var(--line);box-shadow:var(--sh1)}
body .card h3{color:var(--navy)}
/* buttons: one primary, one outline, one danger, same size and feel everywhere */
body button,body .btn{background:var(--blue);color:#fff;border:1px solid var(--blue);border-radius:8px;box-shadow:none;text-shadow:none;
 min-height:42px;padding:.55rem 1.15rem;font-weight:600;transition:background 160ms ease-out,border-color 160ms ease-out,box-shadow 160ms ease-out,transform 160ms ease-out}
body button:not(.eye):not(.sclear):not(.qi-tile):not(.roombtn):not(.tlink):not(.tf-dir):not(.tf-clear):not(.daytab):not(.shotbtn):not(.vopt):not(.lgtabs *):hover:not(:disabled),body .btn:hover{background:var(--blue-d);border-color:var(--blue-d);box-shadow:0 4px 12px rgba(46,73,204,.28);transform:scale(1.02)}
body button:not(.eye):not(.sclear):not(.qi-tile):not(.roombtn):not(.tlink):not(.tf-dir):not(.tf-clear):not(.daytab):not(.shotbtn):not(.vopt):not(.lgtabs *):active:not(:disabled),body .btn:active{transform:scale(.97);box-shadow:0 1px 2px rgba(19,17,132,.25)}
@media(hover:none){body button:not(.eye):not(.sclear):not(.qi-tile):not(.roombtn):not(.tlink):not(.tf-dir):not(.tf-clear):not(.daytab):not(.shotbtn):not(.vopt):not(.lgtabs *):hover:not(:disabled),body .btn:hover{transform:none;box-shadow:none}}
body button.plain,body .btn.plain{background:#fff;color:var(--blue);border-color:var(--blue)}
body button.plain:hover:not(:disabled),body .btn.plain:hover{background:var(--tint);box-shadow:none}
body button.danger,body .btn.danger{background:#fff;color:var(--bad);border-color:var(--bad)}
body button.danger:hover:not(:disabled){background:var(--bad);color:#fff;border-color:var(--bad);box-shadow:0 4px 12px rgba(161,43,43,.25)}
body button.small,body .btn.small{min-height:34px;padding:.3rem .8rem;font-size:.85rem;margin-bottom:0}
body button:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}
/* fields */
body input:not([type=checkbox]):not([type=radio]):not([type=hidden]),body select,body textarea{border:1px solid #c3cbe8;border-radius:8px;background:#fff;transition:border-color .15s,box-shadow .15s}
body input:focus,body select:focus,body textarea:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(46,73,204,.18);outline:0}
body label{font-weight:600;color:var(--navy)}
/* tables */
body table.list{border-collapse:separate;border-spacing:0}
body table.list thead th{background:var(--tint);color:var(--navy);font:600 .78rem "Poppins","Segoe UI",sans-serif;letter-spacing:.05em;text-transform:uppercase;border-bottom:2px solid var(--blue)}
body table.list tbody tr{transition:background .12s}
body table.list tbody tr:nth-child(even){background:#fafbff}
body table.list tbody tr:hover{background:var(--tint)}
body table.list td{border-bottom:1px solid var(--line)}
/* dashboard cards */
body .kpi{background:#fff;border:1px solid var(--line);border-top:3px solid var(--gold);border-radius:var(--r);box-shadow:var(--sh1);transition:transform .15s,box-shadow .15s}
body .kpi:hover{transform:translateY(-2px);box-shadow:var(--sh2)}
body .kpi b{color:var(--navy)}
body .stepcard{border-radius:var(--r);transition:transform .15s,box-shadow .15s,border-color .15s}
/* sidebar: active page marked in blue with a gold edge */
/* status colours */
body .msg.ok,body .msg.success{border-left:4px solid var(--ok)}
body .msg.error{border-left:4px solid var(--bad)}
body .okt{color:var(--ok)}body .why{color:var(--bad)}
/* phones and tablets: tables scroll inside their box, buttons and fields stay thumb-sized */
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
@media(max-width:700px){
 body main{padding-left:.8rem;padding-right:.8rem}
 body .card{padding:1rem}
 body .btnrow{display:flex;flex-direction:column;gap:.5rem}
 body .btnrow button,body .btnrow .btn{width:100%}
 body input:not([type=checkbox]):not([type=radio]),body select,body textarea{font-size:16px;min-height:44px} /* 16px stops iPhone zoom on focus */
 body .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
@media print{body .card,body .kpi{box-shadow:none}}
/* ======== Dashboard (banner, four stat cards, navigation list) and the unnumbered menu ======== */
body .mn-num,body .shell>.side .mn-num{display:none}
body.sidemini .shell>.side .mn{grid-template-columns:1fr}
.dash-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.8rem;margin:0 0 1rem}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media(max-width:900px){.dash-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
.dstat{display:flex;flex-direction:column;gap:.3rem;background:#fff;border:1px solid var(--line);border-radius:14px;padding:1rem 1.1rem;text-decoration:none;color:var(--ink);box-shadow:var(--sh1);transition:transform .15s,box-shadow .15s,border-color .15s}
.dstat .ic{width:40px;height:40px;border-radius:10px;background:var(--tint);color:var(--blue);display:flex;align-items:center;justify-content:center;margin-bottom:.3rem}
.dstat b{font:700 2rem/1 "Poppins","Segoe UI",sans-serif;color:var(--navy)}
.dstat.bad b{color:var(--bad)}.dstat.ok b{color:var(--ok)}.dstat.warn{border-color:var(--gold)}.dstat.warn b{color:var(--warn)}
.recent{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem}.recent h4{margin:0 0 .3rem;color:var(--navy)}.recent p{margin:.15rem 0}
.dstat .l{font-weight:600}.dstat small{color:var(--muted)}

/* ======== Navigation v2: one sidebar per role (drawer on phones), dialogs, toasts, motion ======== */
:root{--t-fast:150ms;--t-med:220ms;--side-bg:#0e1a5a;--side-ink:#d9e0ff;--side-mute:rgba(255,255,255,.62);--side-line:rgba(255,255,255,.16)}
body .top .in{display:flex!important;align-items:center;gap:.8rem;flex-wrap:nowrap;padding:.55rem 1rem}
body .top .brand{margin:0!important}
body .top .menubtn{display:none}
.navback{display:none}
body .shell{display:block}
body .shell>.side{display:flex;flex-direction:column;gap:.15rem;background:var(--side-bg);color:var(--side-ink);border-right:0;padding:.9rem .7rem 1rem}
body .shell>.side .mainnav{display:flex;flex-direction:column;gap:.15rem}
body .shell>.side .mn{display:grid;grid-template-columns:2rem minmax(0,1fr);align-items:center;gap:.65rem;min-height:44px;height:auto;padding:.5rem .7rem;border:0;border-radius:10px;background:transparent;color:var(--side-ink);text-decoration:none;position:relative;transition:background-color var(--t-fast) ease-out,color var(--t-fast) ease-out}
body .shell>.side .mn:hover{background:rgba(255,255,255,.1);color:#fff;transform:none;border:0}
body .shell>.side .mn:active{background:rgba(255,255,255,.18)}
body .shell>.side .mn.on,body .shell>.side .mn.on:hover{background:#fff;color:var(--side-bg);box-shadow:none}
body .shell>.side .mn[aria-disabled="true"]{opacity:.5;pointer-events:none}
body .shell>.side .mn-ic{display:flex;color:inherit}
body .shell>.side .mn-tx b{display:flex;align-items:center;gap:.4rem;font:500 .93rem/1.25 "Poppins","Segoe UI",sans-serif;color:inherit}
body .shell>.side .mn.on .mn-tx b{font-weight:600}
body .shell>.side .mn-tx small{display:none}
body .shell>.side .mn .badge{margin-left:auto}
body .shell>.side .navsep{border-top:0;margin-top:.7rem;padding:.2rem .7rem .25rem}
body .shell>.side .navsep span{color:var(--side-mute)}
body .shell>.side .side-h{display:flex;align-items:center;justify-content:space-between;color:var(--side-mute);font-size:.78rem;letter-spacing:.06em;text-transform:uppercase;padding:0 .4rem .3rem}
body .shell>.side .side-toggle{background:rgba(255,255,255,.1);color:#fff;border:0;box-shadow:none;min-height:32px;padding:.2rem .6rem}
body .shell>.side .side-toggle:hover:not(:disabled){background:rgba(255,255,255,.2);box-shadow:none;transform:none}
body .side-acct{margin-top:auto;border-top:1px solid var(--side-line);padding-top:.7rem;display:flex;flex-direction:column;gap:.15rem}
body .shell>.side .who{display:flex;align-items:center;gap:.65rem;padding:.2rem .5rem .55rem;margin:0;color:#fff}
body .shell>.side .av{width:36px;height:36px;border-radius:50%;background:#fff;color:var(--side-bg);display:grid;place-items:center;font-weight:700;flex:none}
body .shell>.side .wn{font-weight:600;line-height:1.2;overflow:hidden;text-overflow:ellipsis;min-width:0}
body .shell>.side .wn small{display:block;color:var(--side-mute);font-weight:400;font-size:.8rem}
body .shell>.side .mn.out{color:#ffc2c2}
body .shell>.side .mn.out:hover{background:rgba(255,120,120,.18);color:#fff}
@media(min-width:1101px){
 body .shell{display:grid;grid-template-columns:264px minmax(0,1fr);align-items:start;max-width:none;margin:0;transition:grid-template-columns var(--t-med) ease-out}
 body.sidemini .shell{grid-template-columns:72px minmax(0,1fr)}
 body .shell>.side{position:sticky;top:0;height:100vh;max-height:100vh;overflow-y:auto}
 body.sidemini .shell>.side .wn,body.sidemini .shell>.side .navsep span{display:none}
 body.sidemini .shell>.side .mn,body.sidemini .shell>.side .who{grid-template-columns:1fr;justify-items:center;justify-content:center}
 body.sidemini .shell>.side .mn-tx{display:none}
 }
@media(max-width:1100px){
 body .top{position:sticky;top:0;z-index:100}
 body .top .menubtn{display:inline-flex;align-items:center;justify-content:center;min-width:44px}
 body .shell>.side{position:fixed;top:0;left:0;bottom:0;width:min(300px,86vw);height:auto;max-height:none;z-index:200;overflow-y:auto;transform:translateX(-105%);visibility:hidden;box-shadow:var(--sh2);transition:transform var(--t-med) ease-out,visibility 0s linear var(--t-med)}
 body.navopen .shell>.side{transform:none;visibility:visible;transition:transform var(--t-med) ease-out}
 .navback{display:block;position:fixed;inset:0;background:rgba(12,10,60,.45);opacity:0;pointer-events:none;transition:opacity var(--t-med) ease-out;z-index:190}
 body.navopen .navback{opacity:1;pointer-events:auto}
 body.navopen{overflow:hidden}
 body .shell>.side .side-toggle{display:none}
 body .shellmain main{max-width:none}
}
/* page fade (opacity only, so nothing shifts) */
main{animation:qfade var(--t-med) ease-out}
@keyframes qfade{from{opacity:0}to{opacity:1}}
@keyframes qshake{20%,60%{transform:translateX(-3px)}40%,80%{transform:translateX(3px)}}
.login .auth-body button.dark{background:linear-gradient(180deg,#3a40d8,#2c31c9);color:#fff;border:0;box-shadow:0 6px 14px rgba(44,49,201,.35)}
.login .auth-body button.dark:hover:not(:disabled){background:linear-gradient(180deg,#2f35cf,#1a1d85);box-shadow:0 8px 18px rgba(26,29,133,.4)}
.login .auth-body button.dark:active:not(:disabled){box-shadow:0 2px 6px rgba(26,29,133,.35)}
body input:user-invalid,body select:user-invalid{border-color:var(--bad);animation:qshake .25s ease-out}
/* confirmation dialog */
.qmodal{position:fixed;inset:0;z-index:400;display:flex;align-items:center;justify-content:center;padding:1rem;background:rgba(12,10,60,.45);opacity:0;pointer-events:none;transition:opacity var(--t-med) ease-out}
.qmodal[hidden]{display:none}.qmodal.on{opacity:1;pointer-events:auto}
.qm-card{background:#fff;border-radius:14px;box-shadow:var(--sh2);width:min(440px,100%);max-height:calc(100vh - 2rem);overflow:auto;padding:1.2rem 1.3rem;transform:translateY(8px) scale(.98);transition:transform var(--t-med) ease-out}
.qmodal.on .qm-card{transform:none}
.qm-card h3{margin:0 0 .4rem}.qm-card p{margin:0 0 1.1rem;white-space:pre-line}
.qm-acts{display:flex;justify-content:flex-end;gap:.6rem;flex-wrap:wrap}
body .qm-card.danger [data-yes]{background:var(--bad);border-color:var(--bad)}
@media(max-width:480px){.qm-acts button{flex:1}}
/* toasts */
#toasts{position:fixed;top:.9rem;right:.9rem;z-index:300;display:flex;flex-direction:column;gap:.5rem;width:min(390px,calc(100vw - 1.8rem));pointer-events:none}
.qtoast{pointer-events:auto;display:flex;gap:.6rem;align-items:flex-start;background:#fff;border:1px solid var(--line);border-left:4px solid var(--ok);border-radius:10px;box-shadow:var(--sh2);padding:.7rem .8rem;animation:qtin var(--t-med) ease-out}
.qtoast.error{border-left-color:var(--bad)}
.qtoast.out{opacity:0;transform:translateX(12px);transition:opacity var(--t-fast),transform var(--t-fast)}
.qtoast .qi{flex:none;width:22px;height:22px;border-radius:50%;display:grid;place-items:center;color:#fff;background:var(--ok);margin-top:1px}
.qtoast.error .qi{background:var(--bad)}
.qtoast .qi path{stroke-dasharray:24;stroke-dashoffset:24;animation:qdraw .35s .1s ease-out forwards}
.qtoast .qt{flex:1;font-size:.92rem;line-height:1.4;min-width:0;overflow-wrap:anywhere}
body .qtoast .qx{background:none;border:0;color:var(--muted);min-height:0;padding:0 .3rem;font-size:1.3rem;line-height:1;box-shadow:none}
body .qtoast .qx:hover{background:none;color:var(--ink);transform:none;box-shadow:none}
@keyframes qtin{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:none}}
@keyframes qdraw{to{stroke-dashoffset:0}}
@media(max-width:700px){ #toasts{top:auto;bottom:.8rem;right:.9rem;left:.9rem;width:auto}}
@media print{ #toasts,.qmodal,.navback{display:none!important}}

"""


UX_CSS = r"""
/* ======== UX layer: stable buttons (the last word on button motion) ======== */
/* Older layers of this stylesheet each gave buttons their own hover/active transform (translate and scale).
   They stacked up and made buttons jump. Buttons now change colour and shadow only, never position or size. */
body button:hover,body button:active,body .btn:hover,body .btn:active,body .daytab:hover,body .daytab:active,body .menubtn:active,body .backbtn:hover,body .backbtn:active{transform:none!important}
body button,body .btn{position:relative;transition:background-color .12s ease,border-color .12s ease,box-shadow .12s ease,color .12s ease;-webkit-tap-highlight-color:transparent}
body button:not(.eye):not(.sclear):not(.qi-tile):not(.roombtn):not(.tlink):not(.tf-dir):not(.tf-clear):not(.daytab):not(.shotbtn):not(.vopt):not(.lgtabs *):active:not(:disabled),body .btn:active{filter:brightness(.93);box-shadow:inset 0 2px 4px rgba(0,0,40,.22)}
body button.plain:not(:disabled):active,body .btn.plain:active{filter:none;background:#dfe4fb;box-shadow:inset 0 2px 3px rgba(27,31,122,.18)}
body button.danger:not(:disabled):active{filter:none;box-shadow:inset 0 2px 3px rgba(120,20,20,.25)}
body button:disabled{transform:none!important}
/* busy: the label stays (invisible) so the button keeps its exact width, a spinner sits on top */
body button.busy{color:transparent!important;text-shadow:none!important;pointer-events:none;cursor:progress}
body button.busy::after{content:"";display:block;position:absolute;left:50%;top:50%;width:1.1em;height:1.1em;margin:-.55em 0 0 -.55em;vertical-align:baseline;border-radius:50%;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;animation:spin .7s linear infinite}
body button.plain.busy::after,body button.danger.busy::after,body .lgresend button.busy::after,body button.linklike.busy::after{border-color:rgba(45,50,200,.25);border-top-color:var(--blue)}

/* ======== Login (mobile): the Help / Report buttons can never sit behind the card ======== */
.login .reportlink{display:inline-flex;align-items:center;gap:.4rem;font-weight:600}
.login .reportlink svg{flex:none}
@media(max-width:800px){
 .login .panel{flex-direction:column;align-items:stretch;padding:.9rem 1.3rem 2rem}
 .login .panel>.helpfab{position:static;align-self:flex-end;flex:none;width:auto;height:40px;margin:0 0 .8rem;padding:0 1rem 0 .8rem;gap:.45rem;border-radius:999px;z-index:5;font-size:.85rem;font-weight:700}
 .login .panel>.helpfab::after{content:"Help";line-height:1}
 .login .panel>.helpfab .helpfab-q{top:-4px;right:2px}
 .login .panel>.authform{position:relative;z-index:1;width:100%;margin:0 auto}
}
@media(max-width:360px){.login .panel{padding-left:.9rem;padding-right:.9rem}.login .auth-body{padding:1.2rem 1rem 1rem!important}}

/* ======== Account recovery flow (Forgot password, code, new password, done) ======== */
.login.af .panel{background:linear-gradient(160deg,#f7f9ff,#e7ecfa);align-items:center;justify-content:center;padding:2rem 1.6rem}
.af-wrap{position:relative;isolation:isolate;width:100%;max-width:440px;margin:auto;padding-bottom:20px}
.af-card{position:relative;z-index:1;background:#fff;border:1px solid #cfd8f0;border-radius:20px;padding:1.9rem 1.7rem 1.5rem;box-shadow:inset 0 1px 0 #fff,0 2px 4px rgba(27,31,122,.06),0 14px 30px rgba(27,31,122,.13)}
.af-wrap::before,.af-wrap::after{content:"";position:absolute;z-index:0;border-radius:20px;border:1px solid #cfd8f0}
.af-wrap::before{left:14px;right:14px;top:12px;bottom:10px;background:#e4e9f8}
.af-wrap::after{left:28px;right:28px;top:24px;bottom:0;background:#d3dbf3}
.af-ico{display:grid;place-items:center;width:62px;height:62px;margin:-2.9rem auto .9rem;border-radius:50%;color:#fff;background:linear-gradient(160deg,#4b52e8,#1f2398);box-shadow:inset 0 2px 0 rgba(255,255,255,.35),0 0 0 6px #fff,0 8px 18px rgba(27,31,122,.35)}
.af-ico svg{width:28px;height:28px}
.af-ico.ok{background:linear-gradient(160deg,#3f9a6b,#1f6a45)}
.af-steps{list-style:none;display:flex;margin:0 0 1.3rem;padding:0;counter-reset:s}
.af-steps li{flex:1;position:relative;text-align:center;font-size:.72rem;font-weight:700;letter-spacing:.03em;color:#8a93b4;text-transform:uppercase;padding-top:2.15rem}
.af-steps li span{position:absolute;left:50%;top:0;width:1.7rem;height:1.7rem;margin-left:-.85rem;border-radius:50%;display:grid;place-items:center;background:#eef1fb;border:1.5px solid #cfd8f0;color:#6b7599;font-size:.8rem;z-index:1}
.af-steps li::before{content:"";position:absolute;top:.82rem;left:-50%;width:100%;height:2px;background:#d6dcf1}
.af-steps li:first-child::before{display:none}
.af-steps li.done,.af-steps li.on{color:var(--navy)}
.af-steps li.done span{background:var(--blue);border-color:var(--blue);color:#fff}
.af-steps li.on span{background:#fff;border-color:var(--blue);color:var(--blue);box-shadow:0 0 0 3px rgba(45,50,200,.16)}
.af-steps li.done::before,.af-steps li.on::before{background:var(--blue)}
.af-title{font:700 1.5rem "Poppins","Segoe UI",Arial,sans-serif;color:var(--navy);text-align:center;margin:0 0 .35rem;border:0;padding:0}
.af-title::after{display:none}
.af-sub{text-align:center;color:var(--muted);font-size:.9rem;margin:0 0 1.2rem;overflow-wrap:anywhere}
.af-sub b{color:var(--ink)}
.af-card .msg{margin:0 0 1rem;border-radius:10px;font-size:.9rem}
.af-card label{display:block;font-size:.76rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:#3a4366;margin:1rem 0 .35rem}
.login .af-card input:not([type=checkbox]):not([type=radio]):not([type=hidden]){width:100%;border:1.5px solid #cdd6ee;border-radius:12px;background:#f8faff;padding:.8rem .95rem;font-size:1rem;box-shadow:inset 0 2px 3px rgba(27,31,122,.06);margin:0}
.login .af-card input:not([type=checkbox]):not([type=radio]):not([type=hidden]):focus{outline:0;border-color:var(--blue);background:#fff;box-shadow:inset 0 2px 3px rgba(27,31,122,.04),0 0 0 3px rgba(45,50,200,.16)}
.af-card .tidfield{display:flex;align-items:stretch}
.af-card .tidfield .tidfix{display:flex;align-items:center;padding:0 .95rem;background:#eaeffb;border:1.5px solid #cdd6ee;border-right:0;border-radius:12px 0 0 12px;font-weight:800;color:var(--navy)}
.login .af-card .tidfield input:not([type=hidden]){border-radius:0 12px 12px 0!important;border-left:0!important}
.af-card .pwwrap{display:block}
.af-card .af-btn{display:flex;align-items:center;justify-content:center;width:100%;min-height:50px;margin:1.4rem 0 0;border:0;border-radius:12px;color:#fff;font-weight:700;font-size:1rem;letter-spacing:.04em;text-transform:uppercase;background:linear-gradient(180deg,#4046e0,#2a2fb8);box-shadow:inset 0 1px 0 rgba(255,255,255,.3),0 3px 0 #161a6b,0 10px 18px rgba(27,31,122,.28)}
.af-card .af-btn:hover:not(:disabled){background:linear-gradient(180deg,#363cd6,#23279f);box-shadow:inset 0 1px 0 rgba(255,255,255,.25),0 3px 0 #12155a,0 12px 20px rgba(27,31,122,.32)}
.af-card .af-btn:active:not(:disabled){filter:none;box-shadow:inset 0 2px 5px rgba(0,0,40,.4),0 3px 0 #12155a,0 4px 8px rgba(27,31,122,.2)}
.af-links{display:flex;flex-direction:column;align-items:center;gap:.6rem;margin:1.2rem 0 0;font-size:.85rem;text-align:center;color:var(--muted)}
.af-links a{font-weight:700;color:var(--navy);text-decoration:underline}
.af-resend{display:flex;justify-content:center;margin:1rem 0 0}
.af-resend button{background:none!important;border:0!important;box-shadow:none!important;color:var(--navy)!important;font-weight:700;text-decoration:underline;min-height:38px;padding:.3rem .7rem;font-size:.9rem}
.af-resend button:disabled{color:#7d86a8!important;text-decoration:none;cursor:not-allowed;opacity:1}
.af-otp{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:.5rem}
.login .af-card .af-otp input:not([type=hidden]){text-align:center;padding:.75rem 0;font-size:1.4rem;font-weight:700;border-radius:12px;min-width:0}
.af-otp-one{text-align:center;letter-spacing:.45em;font-size:1.4rem!important;font-weight:700}
.af-meter{display:flex;gap:4px;margin:.5rem 0 0}
.af-meter i{flex:1;height:5px;border-radius:3px;background:#dde3f5;transition:background-color .15s}
.af-meter[data-s="1"] i:nth-child(1){background:#c0392b}
.af-meter[data-s="2"] i:nth-child(-n+2){background:#d98b1d}
.af-meter[data-s="3"] i:nth-child(-n+3){background:#7aa63a}
.af-meter[data-s="4"] i{background:#2e8b57}
.af-hint{font-size:.78rem;color:var(--muted);margin:.35rem 0 0;min-height:1.1em}
.af-hint.bad{color:var(--bad)}.af-hint.good{color:var(--ok)}
.af-note{display:flex;gap:.55rem;align-items:flex-start;margin:1.1rem 0 0;padding:.65rem .8rem;border-radius:10px;background:#eef2fc;border:1px solid #d6def3;color:#3a4366;font-size:.8rem;line-height:1.4}
.af-note svg{flex:none;width:16px;height:16px;margin-top:2px;color:var(--blue)}
@media(max-width:800px){
 .login.af .panel{padding:1.6rem 1rem 2rem;align-items:stretch}
 .af-card{padding:1.6rem 1.15rem 1.3rem}
 .af-steps li{font-size:.62rem;letter-spacing:0}
}
@media(max-width:380px){.af-otp{gap:.3rem}.login .af-card .af-otp input:not([type=hidden]){font-size:1.15rem}}
@media(prefers-reduced-motion:no-preference){.af-card{animation:ifade .35s both}}

/* ======== Admin notifications: account requests ======== */
.rq-sum{display:flex;flex-wrap:wrap;gap:.6rem;margin:0 0 1.2rem}
.rq-chip{display:inline-flex;align-items:center;gap:.5rem;min-width:0;padding:.45rem .85rem;border-radius:999px;background:#fff;border:1px solid var(--line);font-size:.85rem;font-weight:600;color:var(--navy);text-decoration:none}
.rq-chip b{display:inline-grid;place-items:center;min-width:1.6rem;height:1.6rem;padding:0 .4rem;border-radius:999px;background:var(--blue);color:#fff;font-size:.8rem}
.rq-chip.zero b{background:#b8bfda}
.rq-h{display:flex;flex-wrap:wrap;align-items:baseline;gap:.5rem .8rem;margin:1.6rem 0 .8rem}
.rq-h h2{margin:0}
.rq-list{display:grid;gap:1rem;grid-template-columns:repeat(auto-fill,minmax(min(100%,400px),1fr));align-items:start}
.rq-card{display:flex;flex-direction:column;gap:.85rem;min-width:0;background:#fff;border:1px solid var(--line);border-left:5px solid var(--blue);border-radius:14px;padding:1rem 1.1rem;box-shadow:0 1px 2px rgba(27,31,122,.06),0 8px 18px rgba(27,31,122,.07)}
.rq-card.is-approved{border-left-color:var(--ok)}
.rq-card.is-rejected{border-left-color:var(--bad)}
.rq-top{display:flex;gap:.8rem;align-items:flex-start;min-width:0}
.rq-av{flex:none;display:grid;place-items:center;width:44px;height:44px;border-radius:50%;color:#fff;font-weight:700;font-size:1.1rem;background:linear-gradient(160deg,#4b52e8,#1f2398);box-shadow:inset 0 1px 0 rgba(255,255,255,.35)}
.rq-who{flex:1;min-width:0}
.rq-name{font-weight:700;font-size:1.02rem;line-height:1.3;color:var(--navy);overflow-wrap:anywhere;word-break:break-word}
.rq-sub{font-size:.8rem;color:var(--muted);margin-top:.1rem}
.rq-state{flex:none;margin:0}
.rq-dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:.4rem .9rem;margin:0}
.rq-dl dt{color:var(--muted);font-size:.74rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding-top:.15rem}
.rq-dl dd{margin:0;min-width:0;overflow-wrap:anywhere;word-break:break-word}
.rq-email{font-weight:600;color:var(--ink);user-select:all}
.rq-edit{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr));gap:.6rem;margin:0}
.rq-edit label{display:block;font-size:.74rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin:0 0 .25rem}
.rq-edit input,.rq-edit select{width:100%;min-width:0}
.rq-acts{display:flex;flex-wrap:wrap;gap:.6rem}
.rq-acts form{flex:1 1 140px;margin:0}
.rq-acts button{width:100%}
.rq-result{display:flex;align-items:center;gap:.5rem;margin:0;padding:.6rem .8rem;border-radius:10px;font-weight:600;font-size:.9rem}
.rq-result.ok{background:#e7f2ec;color:#1d4a33}
.rq-result.bad{background:#f8e8e8;color:#6e1f1f}
.rq-result.err{background:#fff6dc;color:#5a4210}
.rq-card.is-approved .rq-edit,.rq-card.is-rejected .rq-edit{display:none}
.rq-empty{padding:1.4rem;text-align:center;color:var(--muted);background:#fff;border:1px dashed var(--line);border-radius:14px}
@media(max-width:520px){.rq-dl{grid-template-columns:minmax(0,1fr);gap:.1rem}.rq-dl dd{margin-bottom:.45rem}.rq-card{padding:.9rem}}

/* ======== Filters, sorting and flexible search for tables and card lists ======== */
[data-tf-hide]{display:none!important}
.tf-bar{display:flex;flex-wrap:wrap;gap:.6rem .8rem;align-items:flex-end;margin:0 0 .8rem;padding:.8rem .9rem;background:#fff;border:1px solid var(--line);border-radius:12px;box-shadow:0 1px 2px rgba(27,31,122,.05)}
.tf-bar label{display:block;font-size:.72rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin:0 0 .25rem}
.tf-search{flex:2 1 240px;min-width:0}
.tf-field{flex:1 1 150px;min-width:0;max-width:100%}
.tf-bar input,.tf-bar select{width:100%;min-width:0;max-width:100%;margin:0}
.tf-sfield,.tsearch .sfield{position:relative;min-width:0;max-width:100%}
.tf-sfield>svg{position:absolute;left:.8rem;top:50%;margin-top:-9px;color:var(--muted);pointer-events:none}
.tf-sfield input[type=search]{padding-left:2.5rem;padding-right:2.6rem;text-overflow:ellipsis}
.tf-sfield input::-webkit-search-cancel-button{display:none}
.tf-sortrow{display:flex;gap:.4rem}
.tf-sortrow select{flex:1 1 auto}
.tf-bar button.tf-dir{flex:none;min-width:5.2rem;min-height:42px;padding:.3rem .6rem;margin:0}
.tf-bar button.tf-clear{flex:none;min-height:42px;margin:0}
.tf-count{flex:1 0 100%;margin:0!important}
.tf-bar .tf-clear:disabled{opacity:.45}
th.tf-sortable{cursor:pointer;user-select:none}
th.tf-sortable:hover{color:var(--blue)}
th.tf-sortable::after{content:"\2195";margin-left:.35em;font-size:.8em;opacity:.4}
th.tf-sortable[aria-sort=ascending]::after{content:"\25B2";opacity:.9}
th.tf-sortable[aria-sort=descending]::after{content:"\25BC";opacity:.9}
.tf-empty td,.tf-empty-card{text-align:center;color:var(--muted);padding:1.4rem!important}
.tf-empty-card{background:#fff;border:1px dashed var(--line);border-radius:12px}
.tf-empty button{margin:.6rem 0 0}
@media(max-width:600px){.tf-search,.tf-field{flex:1 1 100%}.tf-bar button.tf-clear{flex:1 1 100%}}
/* flexible search fields everywhere */
.tsearch{max-width:none;width:100%}
.tsearch .sfield input{width:100%;min-width:0;text-overflow:ellipsis}
.tsearch .formgrid>div{min-width:0}
.typesel{max-width:100%}.typesel select{max-width:100%}
.af-card a.af-btn{text-decoration:none;box-sizing:border-box}
.af-card .pwwrap input{padding-right:3.2rem!important}
.af-resend button{min-width:11.5rem}
.af-card .af-otp-one{margin:0}
.rq-acts button.danger{border:1.5px solid var(--bad);background:#fff;color:var(--bad)}
.rq-acts button.danger:hover:not(:disabled){background:var(--bad);color:#fff}
@media(max-width:520px){.rq-top{flex-wrap:wrap}.rq-state{order:3;margin-left:calc(44px + .8rem)}}
.tf-bar button.tf-dir,.tf-bar button.tf-clear{border:1.5px solid #b9c1ec;background:#fff;color:var(--navy)}
.tf-bar button.tf-dir:hover:not(:disabled),.tf-bar button.tf-clear:hover:not(:disabled){background:var(--tint)}
"""

EDIT_MODAL_JS = r"""<script>(function(){
/* Edit pages (teacher, section) open in a dialog. The page is loaded inside the dialog, so every field, check and
   message of the normal edit page is used. Any link or button with data-modal-href opens it; without JavaScript it
   is still an ordinary link to the edit page. */
function path(){return location.pathname.replace(/\/+$/,'');}
if(window.name==='editframe'){
 var onEdit=/\/edit$/.test(path());
 if(!onEdit){document.documentElement.style.visibility='hidden';}
 document.addEventListener('DOMContentLoaded',function(){
  if(!onEdit){var m=document.querySelector('main .msg.ok'),e=document.querySelector('main .msg.error');
   parent.postMessage({editDone:true,reload:true,msg:m?m.textContent.trim():'Changes saved.'},location.origin);}
 });
 document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('a.btn.plain');
  if(a&&/^\s*cancel\s*$/i.test(a.textContent)){e.preventDefault();parent.postMessage({editDone:true,reload:false},location.origin);}});
 return;
}
var dlg=null,frame=null,ttl=null;
function make(){
 if(dlg)return;
 dlg=document.createElement('dialog');dlg.id='editmodal';dlg.className='dlg editmodal noprint';dlg.setAttribute('aria-labelledby','editmodal-t');
 dlg.innerHTML='<div class="em-head"><h3 id="editmodal-t">Edit</h3><button type="button" class="plain small em-x" aria-label="Close">&times;</button></div><div class="em-body"><p class="hint em-load">Loading&hellip;</p><iframe name="editframe" title="Edit form"></iframe></div>';
 document.body.appendChild(dlg);
 frame=dlg.querySelector('iframe');ttl=dlg.querySelector('h3');
 dlg.querySelector('.em-x').addEventListener('click',function(){dlg.close();});
 dlg.addEventListener('click',function(e){if(e.target===dlg){var r=dlg.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dlg.close();}});
 dlg.addEventListener('close',function(){frame.src='about:blank';document.documentElement.classList.remove('modal-open');});
 frame.addEventListener('load',function(){if(frame.src&&frame.src.indexOf('about:blank')<0)dlg.querySelector('.em-load').hidden=true;});
}
function toast(msg,bad){
 var t=document.createElement('div');t.className='flash-toast'+(bad?' bad':'');t.setAttribute('role','status');t.textContent=msg;
 document.body.appendChild(t);setTimeout(function(){t.classList.add('out');},4200);setTimeout(function(){t.remove();},4800);
}
document.addEventListener('click',function(e){
 var b=e.target.closest&&e.target.closest('[data-modal-href]');
 if(!b||e.metaKey||e.ctrlKey||e.shiftKey||e.button)return;
 if(typeof HTMLDialogElement==='undefined')return;
 e.preventDefault();e.stopImmediatePropagation();
 make();ttl.textContent=b.getAttribute('data-modal-title')||'Edit';
 dlg.querySelector('.em-load').hidden=false;frame.src=b.getAttribute('data-modal-href');
 document.documentElement.classList.add('modal-open');if(!dlg.open)dlg.showModal();
},true);
window.addEventListener('message',function(e){
 if(e.origin!==location.origin||!e.data||!e.data.editDone)return;
 if(dlg&&dlg.open)dlg.close();
 if(e.data.reload){try{sessionStorage.setItem('flashToast',e.data.msg||'Changes saved.');}catch(x){}location.reload();}
});
try{var m=sessionStorage.getItem('flashToast');if(m){sessionStorage.removeItem('flashToast');document.addEventListener('DOMContentLoaded',function(){toast(m);});}}catch(x){}
})();</script>
"""

TF_JS = r"""<script>(function(){
/* Search, sort and filters for admin tables and card lists. Opt in with data-tools="what the rows are".
   TABLES: a small funnel button sits at the right edge of every column header. It opens a menu for that column only
   (sort, search the values, tick the values to show). The only control above a table is one plain search box.
   CARD LISTS: data-items="css selector", data-tf-filters="key:Label", data-tf-sorts="key:Label:type",
   and data-tf-key="value" on every card. A cell can set data-tv="value" to override what it shows.
   Rows are only hidden or reordered, never removed, so forms around the table still save every row. */
var WS=new RegExp('['+String.fromCharCode(0)+'-'+String.fromCharCode(32)+']+','g');
function norm(s){return String(s==null?'':s).replace(WS,' ').trim();}
function el(tag,cls,html){var e=document.createElement(tag);if(cls)e.className=cls;if(html!=null)e.innerHTML=html;return e;}
var ICON='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>';
var FUNNEL='<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 5h18l-7 8.5V20l-4-2v-4.5z"/></svg>';
var uid=0;
function cellValue(td){
 if(!td)return '';
 var v=td.getAttribute('data-tv');if(v!==null)return norm(v);
 var sp=td.querySelector('.specpick input[type=hidden]');if(sp)return norm(sp.value);
 var ot=td.querySelector('input[data-official]');if(ot)return norm(ot.value);
 var s=td.querySelector('select');
 if(s)return norm(s.selectedIndex>=0&&s.options[s.selectedIndex]?s.options[s.selectedIndex].text:'');
 var i=td.querySelector('input:not([type=hidden])');
 if(i){if(i.type==='checkbox'||i.type==='radio')return i.checked?'Yes':'No';return norm(i.value);}
 return norm(td.textContent);
}
function num(s){var m=String(s).match(/-?[0-9]+([.][0-9]+)?/);return m?parseFloat(m[0]):NaN;}
function cmpv(isNum,a,b){
 if(isNum){var x=num(a),y=num(b),nx=isNaN(x),ny=isNaN(y);if(nx&&ny)return 0;if(nx)return 1;if(ny)return -1;return x-y;}
 return a.localeCompare(b,undefined,{numeric:true,sensitivity:'base'});
}
var BLANK='(Blank)';
function fv(v){return(v===''||v==='-')?BLANK:v;}

/* ---------------- one shared column menu ---------------- */
var pop=null,popFor=null;
function closePop(){if(!pop)return;pop.hidden=true;if(popFor&&popFor.btn){popFor.btn.setAttribute('aria-expanded','false');}popFor=null;}
function placePop(){
 if(!pop||!popFor)return;
 var r=popFor.btn.getBoundingClientRect(),vw=document.documentElement.clientWidth,vh=window.innerHeight;
 var w=Math.min(290,vw-16);pop.style.width=w+'px';
 var left=r.right-w;left=Math.max(8,Math.min(left,vw-w-8));
 pop.style.left=left+'px';
 var below=vh-r.bottom-12,above=r.top-12,h=pop.scrollHeight||320;
 var list=pop.querySelector('.tfp-list');
 if(below>=Math.min(h,360)||below>=above){pop.style.top=(r.bottom+6)+'px';pop.style.bottom='auto';pop.style.maxHeight=Math.max(200,below)+'px';}
 else{pop.style.top='auto';pop.style.bottom=(vh-r.top+6)+'px';pop.style.maxHeight=Math.max(200,above)+'px';}
}
function ensurePop(){
 if(pop)return pop;
 pop=el('div','tfpop noprint');pop.hidden=true;pop.setAttribute('role','dialog');
 document.body.appendChild(pop);
 document.addEventListener('mousedown',function(e){if(pop.hidden)return;if(pop.contains(e.target)||(popFor&&popFor.btn.contains(e.target)))return;closePop();});
 document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!pop.hidden){var b=popFor&&popFor.btn;closePop();if(b)b.focus();}});
 window.addEventListener('resize',function(){if(!pop.hidden)placePop();});
 window.addEventListener('scroll',function(){if(!pop.hidden)placePop();},true);
 return pop;
}

/* ---------------- tables ---------------- */
function buildTable(root){
 var head=root.tHead&&root.tHead.rows[root.tHead.rows.length-1];
 if(!head||!root.tBodies.length||root.__tf)return;
 var name=root.getAttribute('data-tools')||'records';
 var items=[].filter.call(root.tBodies[0].rows,function(r){return !r.querySelector('td.empty')&&r.id!=='tqnone'&&!r.classList.contains('tf-empty');});
 if(!items.length)return;
 root.__tf=true;root.classList.add('tf-cols');
 items.forEach(function(it,i){it.__i=i;});
 var id='tf'+(++uid),cols=[],sortCol=null,asc=true,q=null,qx=null,clr=null;
 var noFilter=true;   /* column filters removed from every table: search box only */
 [].forEach.call(head.cells,function(th,i){
  var label=norm(th.getAttribute('data-label')||th.textContent);
  if(!label||th.classList.contains('editth')||/^actions?$/i.test(label))return;
  var c={i:i,th:th,label:label,sel:null,isNum:th.getAttribute('data-ts')==='num',nameSort:root.hasAttribute('data-sortname')&&cols.length===0};
  c.get=function(it){return fv(cellValue(it.cells[i]));};
  if(noFilter)return;                                  /* Room Management: search only */
  if(root.hasAttribute('data-sortname')&&!c.nameSort&&!th.hasAttribute('data-tf'))return;   /* Teacher and Section Management: name sort + the few useful filters */
  if(!c.nameSort){var seenv={},nv=0;items.forEach(function(it){var v=c.get(it);if(!seenv[v]){seenv[v]=1;nv++;}});if(nv>60)return;}
  cols.push(c);
 });
 /* the funnel button at the right side of each header */
 cols.forEach(function(c,n){
  var th=c.th;th.classList.add('tf-th');
  var wrap=el('span','tf-hd'),lbl=el('span','tf-lbl');
  while(th.firstChild)lbl.appendChild(th.firstChild);
  var btn=el('button','tf-btn',FUNNEL);btn.type='button';
  btn.setAttribute('aria-haspopup','dialog');btn.setAttribute('aria-expanded','false');
  btn.setAttribute('aria-label','Filter and sort '+c.label);btn.title='Filter '+c.label;
  wrap.appendChild(lbl);wrap.appendChild(btn);th.appendChild(wrap);
  c.btn=btn;
  btn.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();openMenu(c);});
 });
 /* the one plain search box */
 if(!root.hasAttribute('data-nosearch')){
  var w=el('div','tf-search noprint');
  w.innerHTML='<div class="tf-sfield">'+ICON+'<input id="'+id+'q" type="search" autocomplete="off" maxlength="80" enterkeyhint="search" aria-label="Search '+name+'"><a href="#" class="sclear" role="button" title="Clear search" aria-label="Clear search" hidden>&times;</a></div>';
  var anchor=root.closest('.scroll')||root;anchor.parentNode.insertBefore(w,anchor);
  q=w.querySelector('input');qx=w.querySelector('.sclear');
 }
 var live=el('p','sr-only');live.setAttribute('aria-live','polite');root.parentNode.insertBefore(live,root);
 var last=items[items.length-1],end=document.createComment('tf-end');last.parentNode.insertBefore(end,last.nextSibling);
 var empty=el('tr','tf-empty');empty.hidden=true;
 empty.innerHTML='<td colspan="'+head.cells.length+'" class="empty">No '+name+' match your search.<br><button type="button" class="plain small">Clear search</button></td>';
 root.tBodies[0].appendChild(empty);
 function haystack(it){var d=it.getAttribute('data-find');if(d)return d.toLowerCase();return [].map.call(it.cells,cellValue).join(' ').toLowerCase();}
 function active(){return cols.some(function(c){return c.sel;})||(q&&q.value)||sortCol;}
 function mark(){cols.forEach(function(c){
  var on=!!c.sel||c===sortCol;c.btn.classList.toggle('on',on);
  if(c===sortCol)c.th.setAttribute('aria-sort',asc?'ascending':'descending');else c.th.removeAttribute('aria-sort');});}
 function reorder(){
  var order=items.slice();
  if(sortCol){var dir=asc?1:-1;order.sort(function(a,b){var r=cmpv(sortCol.isNum,sortCol.get(a),sortCol.get(b));return r?r*dir:a.__i-b.__i;});}
  else order.sort(function(a,b){return a.__i-b.__i;});
  order.forEach(function(it){end.parentNode.insertBefore(it,end);});
 }
 function apply(){
  var words=q?norm(q.value).toLowerCase().split(' ').filter(Boolean):[],shown=0;
  items.forEach(function(it){
   var ok=true;
   if(words.length){var h=haystack(it);ok=words.every(function(x){return h.indexOf(x)>-1;});}
   if(ok)for(var k=0;k<cols.length;k++){var c=cols[k];if(c.sel&&!c.sel[c.get(it)]){ok=false;break;}}
   if(ok){shown++;it.removeAttribute('data-tf-hide');}else it.setAttribute('data-tf-hide','1');
  });
  if(qx)qx.hidden=!(q&&q.value);
  empty.hidden=shown>0;mark();
  live.textContent='Showing '+shown+' of '+items.length+' '+name;
 }
 function resetAll(){if(q)q.value='';cols.forEach(function(c){c.sel=null;});sortCol=null;asc=true;reorder();apply();}
 if(q){q.addEventListener('input',apply);q.addEventListener('keydown',function(e){if(e.key==='Enter')e.preventDefault();});}
 if(qx)qx.addEventListener('click',function(e){e.preventDefault();q.value='';apply();q.focus();});
 empty.querySelector('button').addEventListener('click',resetAll);

 /* the menu of one column */
 function openMenu(c){
  ensurePop();
  if(popFor&&popFor===c&&!pop.hidden){closePop();return;}
  closePop();
  var vals=[],seen={};
  items.forEach(function(it){var v=c.get(it);if(!seen[v]){seen[v]=1;vals.push(v);}});
  vals.sort(function(a,b){if(a===BLANK)return 1;if(b===BLANK)return -1;return cmpv(c.isNum,a,b);});
  var chosen={};vals.forEach(function(v){chosen[v]=c.sel?!!c.sel[v]:true;});
  pop.innerHTML='';pop.setAttribute('aria-label','Filter '+c.label);
  var top=el('div','tfp-top');
  top.innerHTML='<div class="tfp-title">'+c.label+'</div>'+(c.nameSort?'<div class="tfp-sort"><button type="button" data-s="asc">A&ndash;Z</button><button type="button" data-s="desc">Z&ndash;A</button></div>':'');
  var sw=el('div','tfp-search');sw.hidden=true;sw.innerHTML='<input type="hidden">';
  var all=el('label','tfp-all chk');all.innerHTML='<input type="checkbox" class="ck"><span>Select all</span>';
  var list=el('div','tfp-list');list.setAttribute('role','group');
  var foot=el('div','tfp-foot');foot.innerHTML='<button type="button" class="plain small" data-x="clear">Clear</button><button type="button" class="small" data-x="done">Done</button>';
  pop.appendChild(top);pop.appendChild(sw);
  if(!c.nameSort){pop.appendChild(all);pop.appendChild(list);}
  pop.appendChild(foot);
  var si=sw.querySelector('input'),allCk=all.querySelector('input');
  var sb=top.querySelectorAll('.tfp-sort button');
  function sortState(){[].forEach.call(sb,function(b){b.classList.toggle('on',sortCol===c&&((b.dataset.s==='asc')===asc));});}
  function shownVals(){var t=norm(si.value).toLowerCase();return vals.filter(function(v){return !t||v.toLowerCase().indexOf(t)>-1;});}
  function paint(){
   var sv=shownVals();list.innerHTML='';
   sv.slice(0,300).forEach(function(v){
    var l=el('label','tfp-opt chk'),cb=el('input','ck');cb.type='checkbox';cb.checked=!!chosen[v];
    var sp=el('span');sp.textContent=v;l.appendChild(cb);l.appendChild(sp);
    cb.addEventListener('change',function(){chosen[v]=cb.checked;commit();syncAll();});list.appendChild(l);});
   if(!sv.length)list.appendChild(el('p','hint tfp-none','Nothing found.'));
   else if(sv.length>300)list.appendChild(el('p','hint tfp-none','Showing the first 300. Type to narrow the list.'));
   syncAll();
  }
  function syncAll(){var sv=shownVals(),n=sv.filter(function(v){return chosen[v];}).length;allCk.checked=sv.length>0&&n===sv.length;allCk.indeterminate=n>0&&n<sv.length;}
  function commit(){var every=vals.every(function(v){return chosen[v];});
   if(every)c.sel=null;else{c.sel={};vals.forEach(function(v){if(chosen[v])c.sel[v]=true;});}
   apply();}
  allCk.addEventListener('change',function(){shownVals().forEach(function(v){chosen[v]=allCk.checked;});paint();commit();});
  si.addEventListener('input',paint);
  si.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();var sv=shownVals();vals.forEach(function(v){chosen[v]=sv.indexOf(v)>-1;});paint();commit();}});
  [].forEach.call(sb,function(b){b.addEventListener('click',function(){var d=b.dataset.s==='asc';if(sortCol===c&&asc===d){sortCol=null;asc=true;}else{sortCol=c;asc=d;}reorder();apply();sortState();});});
  foot.querySelector('[data-x=clear]').addEventListener('click',function(){c.sel=null;if(sortCol===c){sortCol=null;asc=true;reorder();}apply();closePop();c.btn.focus();});
  foot.querySelector('[data-x=done]').addEventListener('click',function(){closePop();c.btn.focus();});
  paint();sortState();
  popFor=c;c.btn.setAttribute('aria-expanded','true');pop.hidden=false;placePop();
  setTimeout(function(){var f=pop.querySelector('input.ck,button');if(f){try{f.focus({preventScroll:true});}catch(x){f.focus();}}},0);
 }
 apply();
}

/* ---------------- card lists (account requests, problem reports) ---------------- */
function buildCards(root){
 var items=[].slice.call(root.querySelectorAll(root.getAttribute('data-items')||':scope > *')),fields=[],name=root.getAttribute('data-tools')||'records';
 if(!items.length||root.__tf)return;
 var map={};
 var mk=function(k,l){if(!map[k]){map[k]={label:l,get:function(it){return norm(it.getAttribute('data-tf-'+k));}};fields.push(map[k]);}return map[k];};
 var parse=function(a,fn){(root.getAttribute(a)||'').split(',').forEach(function(p){p=p.split(':');if(p.length>=2&&p[0])fn(p[0],p[1],p[2]);});};
 parse('data-tf-filters',function(k,l){mk(k,l).filter=true;});
 parse('data-tf-sorts',function(k,l,t){mk(k,l).sort=t||'text';});
 root.__tf=true;
 items.forEach(function(it,i){it.__i=i;});
 var id='tf'+(++uid),bar=el('div','tf-bar noprint'),q=null,qx=null,sortSel=null,dirBtn=null,asc=true,sel=[];
 bar.setAttribute('role','search');bar.setAttribute('aria-label','Search '+name);
 if(!root.hasAttribute('data-nosearch')){
  var w=el('div','tf-search');
  w.innerHTML='<div class="tf-sfield">'+ICON+'<input id="'+id+'q" type="search" autocomplete="off" maxlength="80" enterkeyhint="search" aria-label="Search '+name+'"><a href="#" class="sclear" role="button" title="Clear search" aria-label="Clear search" hidden>&times;</a></div>';
  bar.appendChild(w);q=w.querySelector('input');qx=w.querySelector('.sclear');
 }
 fields.forEach(function(f,n){
  if(!f.filter)return;
  var seen={},vals=[];
  items.forEach(function(it){var v=fv(f.get(it));if(!seen[v]){seen[v]=1;vals.push(v);}});
  if(vals.length<1||vals.length>40)return;
  vals.sort(function(a,b){return a.localeCompare(b,undefined,{numeric:true,sensitivity:'base'});});
  var d=el('div','tf-field'),sid=id+'f'+n,o='<option value="">'+f.label+': all</option>';
  vals.forEach(function(){o+='<option></option>';});
  d.innerHTML='<select id="'+sid+'" aria-label="'+f.label+'">'+o+'</select>';
  var s=d.querySelector('select');
  vals.forEach(function(v,k){s.options[k+1].value=v;s.options[k+1].textContent=v;});
  s.__f=f;sel.push(s);bar.appendChild(d);
 });
 var sorts=fields.filter(function(f){return f.sort;});
 if(sorts.length){
  var sw=el('div','tf-field tf-sort'),so='<option value="">Default order</option>';
  sorts.forEach(function(f,k){so+='<option value="'+k+'">Sort: '+f.label+'</option>';});
  sw.innerHTML='<div class="tf-sortrow"><select id="'+id+'s" aria-label="Sort by">'+so+'</select><button type="button" class="plain small tf-dir" title="Ascending order" aria-label="Ascending order">A-Z</button></div>';
  sortSel=sw.querySelector('select');dirBtn=sw.querySelector('button');bar.appendChild(sw);
 }
 var cnt=el('p','hint tf-count');cnt.setAttribute('aria-live','polite');bar.appendChild(cnt);
 root.parentNode.insertBefore(bar,root);
 var empty=el('div','tf-empty-card','No '+name+' match.<br><button type="button" class="plain small">Clear filters</button>');
 empty.hidden=true;root.parentNode.insertBefore(empty,root.nextSibling);
 function reorder(){
  var order=items.slice(),k=sortSel?sortSel.value:'';
  if(k!==''){var f=sorts[+k],dir=asc?1:-1;order.sort(function(a,b){var c=cmpv(f.sort==='num',f.get(a),f.get(b));return c?c*dir:a.__i-b.__i;});}
  else order.sort(function(a,b){return a.__i-b.__i;});
  order.forEach(function(it){root.appendChild(it);});
  if(dirBtn){dirBtn.textContent=asc?'A-Z':'Z-A';var t=asc?'Ascending order':'Descending order';dirBtn.title=t;dirBtn.setAttribute('aria-label',t);}
 }
 function apply(){
  var words=q?norm(q.value).toLowerCase().split(' ').filter(Boolean):[],shown=0;
  items.forEach(function(it){
   var ok=true;
   if(words.length){var h=(it.getAttribute('data-find')||norm(it.textContent)).toLowerCase();ok=words.every(function(x){return h.indexOf(x)>-1;});}
   if(ok)sel.forEach(function(s){if(s.value&&fv(s.__f.get(it))!==s.value)ok=false;});
   if(ok){shown++;it.removeAttribute('data-tf-hide');}else it.setAttribute('data-tf-hide','1');
  });
  if(qx)qx.hidden=!(q&&q.value);
  empty.hidden=shown>0;cnt.textContent='Showing '+shown+' of '+items.length+' '+name;
 }
 function reset(){if(q)q.value='';sel.forEach(function(s){s.value='';});if(sortSel)sortSel.value='';asc=true;reorder();apply();}
 if(q){q.addEventListener('input',apply);q.addEventListener('keydown',function(e){if(e.key==='Enter')e.preventDefault();});}
 if(qx)qx.addEventListener('click',function(e){e.preventDefault();q.value='';apply();q.focus();});
 sel.forEach(function(s){s.addEventListener('change',apply);});
 if(sortSel)sortSel.addEventListener('change',function(){reorder();apply();});
 if(dirBtn)dirBtn.addEventListener('click',function(){asc=!asc;reorder();apply();});
 empty.querySelector('button').addEventListener('click',reset);
 apply();
}
function build(root){if(root.tagName==='TABLE')buildTable(root);else buildCards(root);}
document.querySelectorAll('[data-tools]').forEach(build);
})();</script>
"""

BTN_JS = r"""<script>(function(){
/* One submit handler for the whole system. It stops a second click or Enter from sending the form twice
   and shows a spinner only while a real request is on its way. The button keeps its exact size and label
   space, so nothing moves or jumps. */
function unlock(b){b.classList.remove('busy');b.disabled=false;b.removeAttribute('aria-busy');b.style.removeProperty('min-width');b.style.removeProperty('min-height');}
function lock(f,b){
 var r=b.getBoundingClientRect();
 b.style.minWidth=r.width+'px';b.style.minHeight=r.height+'px';
 /* disabling is deferred one tick: a button that is disabled inside its own submit event drops its name/value from the form data */
 setTimeout(function(){b.classList.add('busy');b.setAttribute('aria-busy','true');b.disabled=true;
  setTimeout(function(){f.__sending=false;unlock(b);},20000);},0);   /* never leave a button stuck if the request fails */
}
document.addEventListener('submit',function(ev){
 if(ev.defaultPrevented)return;                       /* a confirmation, a validation or an AJAX form took over */
 var f=ev.target,b=ev.submitter||f.querySelector('button[type=submit],button:not([type])');
 if(f.__sending){ev.preventDefault();return;}         /* second click or Enter while the first is on its way */
 f.__sending=true;
 if(b&&!b.classList.contains('eye'))lock(f,b);
});
window.addEventListener('pageshow',function(){
 document.querySelectorAll('form').forEach(function(f){f.__sending=false;});
 document.querySelectorAll('button.busy').forEach(unlock);
});
})();</script>
"""

FIX_CSS = r"""
/* ======== Column filters (funnel at the right of every header) ======== */
.tf-search{margin:0 0 .7rem;max-width:420px}
.tf-search .tf-sfield{position:relative}
.tf-search input[type=search]{width:100%;margin:0;min-height:42px}
.tf-th{position:relative}
.tf-hd{display:flex;align-items:center;justify-content:space-between;gap:.4rem;min-width:0}
.tf-lbl{min-width:0;overflow-wrap:normal;word-break:normal;hyphens:none;white-space:normal}
.tf-btn{flex:none;display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;min-height:0!important;min-width:0!important;padding:0!important;margin:0;border:1px solid transparent;border-radius:6px;background:transparent;color:var(--muted);box-shadow:none;cursor:pointer}
.tf-btn:hover{background:var(--tint);color:var(--blue)}
.tf-btn.on{background:var(--blue);color:#fff}
.tf-btn:focus-visible{outline:2px solid var(--blue);outline-offset:1px}
th.tf-sortable{cursor:default}th.tf-sortable::after{content:none}
.tfpop{position:fixed;z-index:3000;display:flex;flex-direction:column;gap:.5rem;box-sizing:border-box;padding:.75rem;background:#fff;border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 32px rgba(27,31,122,.22);overflow:hidden;text-transform:none;letter-spacing:0;font-weight:400;color:var(--ink,#1b1f3a)}
.tfpop[hidden]{display:none}
.tfp-title{font-weight:700;font-size:.9rem;margin-bottom:.35rem}
.tfp-sort{display:flex;gap:.4rem}
.tfp-sort button{flex:1;min-height:36px;padding:.3rem .4rem;font-size:.8rem;border:1.5px solid #b9c1ec;background:#fff;color:var(--navy);box-shadow:none}
.tfp-sort button.on{background:var(--blue);color:#fff;border-color:var(--blue)}
.tfp-search input{width:100%;margin:0;min-height:38px}
.tfp-all,.tfp-opt{display:flex;align-items:center;gap:.5rem;margin:0;padding:.3rem .2rem;font-size:.86rem;font-weight:400;cursor:pointer;text-transform:none;letter-spacing:0}
.tfp-all{border-bottom:1px solid var(--line);font-weight:600}
.tfp-opt span,.tfp-all span{min-width:0;overflow-wrap:anywhere}
.tfp-list{overflow-y:auto;min-height:60px;max-height:240px;flex:1 1 auto;-webkit-overflow-scrolling:touch}
.tfp-foot{display:flex;justify-content:space-between;gap:.5rem}
.tfp-foot button{min-height:38px}
.tf-empty td{text-align:center}
@media(max-width:520px){.tf-btn{width:34px;height:34px}.tfp-opt,.tfp-all{padding:.5rem .2rem}}
/* tables keep their header (and its filters) on small screens and scroll sideways inside their own box */
.list.stack.tf-cols{display:table;width:100%;min-width:640px}
.list.stack.tf-cols thead{display:table-header-group}
.list.stack.tf-cols tbody{display:table-row-group}
.list.stack.tf-cols tr{display:table-row;border:0;margin:0;padding:0;background:none}
.list.stack.tf-cols td{display:table-cell;width:auto;padding:.65rem .6rem;border-bottom:1px solid var(--line)}
.list.stack.tf-cols td[data-label]::before{display:none!important}
.list.assign.stack.tf-cols{min-width:1100px}
table.list.assign.tm th,table.list.assign.tm td{overflow-wrap:normal;word-break:normal}
table.list.assign.tm th:nth-child(1){width:20%}table.list.assign.tm th:nth-child(2){width:12%}
table.list.assign.tm th:nth-child(3){width:20%}table.list.assign.tm th:nth-child(4){width:10%}
table.list.assign.tm th:nth-child(5){width:16%}table.list.assign.tm th:nth-child(6){width:12%}
table.list.assign.tm th:nth-child(7){width:10%}
table.list th{overflow-wrap:normal;word-break:normal;hyphens:none}
.scroll:has(.list.stack.tf-cols){overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);background:#fff;border-radius:10px;max-width:100%}

.qi-dspec{flex:1 1 18rem;min-width:min(100%,18rem)}
.roval{margin:0;min-height:42px;display:flex;align-items:center;gap:.4rem}
/* ======== Edit dialog (teacher and section edit pages) ======== */
.editmodal{width:min(860px,calc(100vw - 1rem));max-width:none;height:min(86vh,820px);height:min(86dvh,820px);padding:0;border:0;border-radius:14px;box-shadow:0 18px 50px rgba(20,24,80,.35);overflow:hidden}
.editmodal[open]{display:flex;flex-direction:column}
.editmodal::backdrop{background:rgba(20,24,60,.5)}
.em-head{display:flex;align-items:center;justify-content:space-between;gap:.6rem;padding:.8rem 1rem;border-bottom:1px solid var(--line);background:#fff}
.em-head h3{margin:0;font-size:1.1rem}
.em-x{width:40px;height:40px;padding:0;font-size:1.5rem;line-height:1}
.em-body{position:relative;flex:1 1 auto;min-height:0}
.em-body iframe{position:absolute;inset:0;width:100%;height:100%;border:0;background:#fff}
.em-load{position:absolute;left:1rem;top:1rem;margin:0}
.modal-open{overflow:hidden}
.inmodal .top,.inmodal .side,.inmodal .navback,.inmodal footer,.inmodal #intro,.inmodal .titlerow,.inmodal .toast,.inmodal main .card~.card{display:none!important}
.inmodal .shell{display:block;padding:0}
.inmodal main{padding:1rem!important;margin:0!important;max-width:none!important;width:100%!important}
.inmodal main>.card{box-shadow:none;border:0;padding:0}
.inmodal .btnrow{position:sticky;bottom:0;background:#fff;padding:.7rem 0;border-top:1px solid var(--line);margin-top:1rem;z-index:3;display:flex;gap:.6rem}html.inmodal body .btnrow{display:flex!important;flex-direction:row!important;gap:.6rem;padding:.6rem 0!important}html.inmodal body .btnrow>button,html.inmodal body .btnrow>a{flex:1 1 0!important;width:auto!important;margin:0!important}.inmodal main{padding-bottom:0!important}
.flash-toast{position:fixed;left:50%;bottom:1.2rem;transform:translateX(-50%);z-index:4000;max-width:calc(100vw - 2rem);padding:.75rem 1.1rem;border-radius:10px;background:#1f6b3a;color:#fff;font-weight:600;box-shadow:0 8px 24px rgba(0,0,0,.25);transition:opacity .5s}
.flash-toast.bad{background:#a32a2a}.flash-toast.out{opacity:0}
@media(max-width:600px){.editmodal{width:100vw;height:100vh;height:100dvh;max-height:none;border-radius:0}}

/* ======== Login: the Help Center is its own button, never behind the form ======== */
body .login .helpfab{position:fixed!important;top:.8rem!important;right:.8rem!important;left:auto!important;z-index:200;display:inline-flex;align-items:center;gap:.45rem;width:auto!important;height:42px!important;padding:0 1rem 0 .8rem!important;margin:0!important;border-radius:999px;background:#fff;color:var(--navy);border:1.5px solid #b9c1ec;font-size:.85rem;font-weight:700;box-shadow:0 3px 10px rgba(27,31,122,.2)}
body .login .helpfab::after{content:"Help Center";line-height:1}
body .login .helpfab:hover{background:var(--tint)}
body .login .helpfab-q{display:none}
body .login .panel{padding-top:4.2rem}
@media(max-width:480px){body .login .helpfab::after{content:"Help"}}

/* ======== Responsive safety net ======== */
html,body{max-width:100%;overflow-x:clip}
main,.shell>*,.card,.formgrid>*,.dlg-grid>*{min-width:0}
img,svg,video,canvas{max-width:100%}
img{height:auto}
.logoimg,.brand-logo,.logoprev{object-fit:contain}
.scroll{max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}
.dlg{width:min(640px,calc(100vw - 1rem));max-height:calc(100vh - 1rem);max-height:calc(100dvh - 1rem);overflow:auto}
.dlg-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.7rem}
.dlg-grid .wide{grid-column:1/-1}
@media(max-width:560px){.dlg-grid{grid-template-columns:minmax(0,1fr)}.btnrow{display:flex;flex-wrap:wrap;gap:.5rem}.btnrow>*{flex:1 1 140px}}
@media(max-width:800px){button,.btn,select,input:not([type=checkbox]):not([type=radio]){min-height:44px}.row-acts{flex-wrap:wrap}h1{overflow-wrap:anywhere}table.list td,table.list th{overflow-wrap:anywhere}}
@media(max-width:360px){main{padding-left:.6rem!important;padding-right:.6rem!important}}

/* ======== Auth screens: one shared layout fix for sign-in, sign-up, code, forgot and reset pages ======== */
/* The admin sidebar rules (.side = sticky, max-height:100vh) leaked into the blue brand panel on any auth page
   that did not carry its own override (sign-up, verify, forgot, reset). The blue panel then stopped at the window
   height while the form kept scrolling, leaving a white gap. These rules apply to every .login page. */
.login{align-items:stretch;min-height:100vh;min-height:100dvh}
.login>.side{position:relative!important;top:auto!important;height:auto!important;max-height:none!important;align-self:stretch;overflow:hidden}
.login>.panel{min-width:0;align-items:flex-start}
.login>.panel>.authform{min-height:0!important;margin:auto!important;width:100%;max-width:440px}
.login .auth-body{margin:0!important}
.login.af>.panel{align-items:center}
@media(min-width:801px){.login>.side{min-height:100%}}
@media(max-width:800px){.login>.side{height:auto!important}.login>.panel>.authform{margin:0 auto!important}}

/* ======== App shell: sidebar fits the space under the header ======== */
/* The sidebar was 100vh tall but starts below the header, so every page overflowed by the header height and the
   last menu items were cut off. The header now stays put and the sidebar takes exactly the remaining height. */
@media(min-width:1101px){
 body .top{position:sticky;top:0;z-index:100}
 body .shell>.side{top:var(--hdrh,71px);height:calc(100vh - var(--hdrh,71px));height:calc(100dvh - var(--hdrh,71px));max-height:none}
 body .shell{min-height:calc(100vh - var(--hdrh,71px))}
}
@media(min-width:1101px){
 /* account block (profile, settings, sign out) stays visible while the menu scrolls */
 body .shell>.side{padding-bottom:0}
 body .shell>.side .side-acct{position:sticky;bottom:0;z-index:2;background:var(--side-bg);margin-top:auto;padding-bottom:.7rem;box-shadow:0 -10px 12px -6px var(--side-bg)}
}
@media(min-width:1101px) and (max-height:860px){
 body .shell>.side{gap:.05rem;padding-top:.6rem}
 body .shell>.side .mn{min-height:38px;padding:.3rem .65rem}
 body .shell>.side .navsep{margin-top:.35rem}
 body .shell>.side .side-acct{padding-top:.4rem}
 body .shell>.side .who{padding-bottom:.3rem}
}
"""

UX2_CSS = r"""
/* ======== Interaction states: light, readable, never stuck ======== */
/* Hover only exists on devices that can hover. On touch screens :hover sticks after a tap, which showed up as a
   coloured background that would not go away, so there the rest colours are restored. */
@media(hover:none){
 body button.plain:hover:not(:disabled),body .btn.plain:hover{background:#fff!important;color:var(--blue)!important}
 body button.danger:hover:not(:disabled){background:#fff!important;color:var(--bad)!important;border-color:var(--bad)!important}
 body button:not(.plain):not(.danger):not(.dark):not(.eye):not(.sclear):not(.tlink):not(.side-toggle):not(.menubtn):not(.daytab):not(.vopt):not(.roombtn):not(.i-skip):not(.qx):not(.lgbtn):not(.tf-dir):not(.tf-clear):not(.qi-tile):not(.shotbtn):not(.lgtabs *):hover:not(:disabled){background:var(--blue)!important;border-color:var(--blue)!important}
 body .list tbody tr:hover{background:transparent}
}
body .shell>.side .side-toggle:hover:not(:disabled){background:rgba(255,255,255,.2)!important;color:#fff}
body .shell>.side .mn:hover{color:#fff}
body .shell>.side .mn:focus-visible{outline:2px solid #fff;outline-offset:-2px}
body .shell>.side .mn.on:hover,body .shell>.side .mn.on:focus-visible{background:#fff;color:var(--side-bg)}
body button:focus:not(:focus-visible),body a:focus:not(:focus-visible),body select:focus:not(:focus-visible){outline:0}
body select option,body select optgroup{background:#fff;color:var(--ink)}
body select:focus,body select:active{background-color:#fff;color:var(--ink)}
body .daytab:active,body .lgtabs button:active{background:#d9def8;color:var(--navy)}

/* ======== One checkbox everywhere: same box, same click area, same alignment ======== */
body input[type=checkbox]{-webkit-appearance:none;appearance:none;display:inline-block;position:relative;flex:none;box-sizing:border-box;width:22px!important;height:22px!important;min-width:22px!important;min-height:22px!important;max-width:22px!important;margin:0;padding:0;border:2px solid #8f9bc9;border-radius:6px;background:#fff;cursor:pointer;vertical-align:middle;transform:none!important;transition:background-color .12s ease,border-color .12s ease}
body input[type=checkbox]::before{content:"";position:absolute;inset:-11px}
body input[type=checkbox]:hover:not(:disabled){border-color:var(--blue)}
body input[type=checkbox]:checked{background:var(--blue);border-color:var(--blue)}
body input[type=checkbox]:checked::after{content:"";position:absolute;left:6px;top:2px;width:6px;height:11px;border:solid #fff;border-width:0 2.5px 2.5px 0;transform:rotate(45deg)}
body input[type=checkbox]:disabled{opacity:.5;cursor:not-allowed}
body input[type=checkbox]:focus-visible{outline:3px solid rgba(46,73,204,.4);outline-offset:2px}
body .chk,body .specpick label,body .dlg-chk .chk{display:flex;align-items:center;gap:.65rem;min-height:44px;margin:.15rem 0;padding:.35rem .7rem;line-height:1.3;font-weight:500;overflow-wrap:anywhere}
body .chk>span,body .specpick label>span{min-width:0;flex:1}
body .specpick .sp-list label{min-height:40px;border-radius:8px}
body .specpick .sp-list label:hover{background:var(--tint)}
body .chk:has(input:checked),body .specpick label:has(input:checked){background:#e4e9fb}
body table.list td input[type=checkbox]{display:block;margin:0 auto}

/* ======== Alignment system: same control height, spacing and table rhythm in every module ======== */
body main input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=file]),body main select{height:44px;min-height:44px;box-sizing:border-box;padding:.4rem .75rem;line-height:1.3}
body main textarea{box-sizing:border-box;padding:.6rem .75rem}
body main label{display:block;margin:0 0 .3rem;font-size:.82rem;font-weight:600;color:#3a4366}
body .formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));gap:.9rem 1rem;align-items:end}
body .formgrid>div{min-width:0}
body .formgrid .wide{grid-column:1/-1}
body .formgrid .fgbtn{align-self:end}
body .btnrow{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;margin-top:1rem}
body .btnrow>*{margin:0}
body .card{padding:1.1rem 1.2rem}
body .card>h3:first-child{margin-top:0}
body table.list{border-collapse:separate;border-spacing:0;width:100%}
body table.list th{padding:.7rem .8rem;text-align:left;vertical-align:middle;white-space:normal}
body table.list td{padding:.6rem .8rem;vertical-align:middle;overflow-wrap:anywhere}
body table.list td input:not([type=checkbox]),body table.list td select{height:40px;min-height:40px}
body .cell-wrap{display:block;overflow-wrap:anywhere;word-break:break-word}
body .row-acts,body .qi-acts{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem}
body .row-acts>form,body .qi-acts>form{margin:0}
body .editth{width:1%;white-space:nowrap}
body .editcell{white-space:nowrap}
body .pagehead{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.6rem 1rem;margin:0 0 .6rem}
body .pagehead h1{margin:0}
/* teacher shifts and official time: one tidy line, fixed columns, long text wraps instead of pushing the layout */
body .otime{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:.35rem;width:100%}
body .otime input[type=time]{width:100%;min-width:0;padding-left:.5rem;padding-right:.3rem}
body .otime>span{color:var(--muted);font-size:.85rem;text-align:center}
@media(min-width:801px){
body table.list.assign.tm{table-layout:fixed;width:100%;min-width:1040px}
body table.list.assign.tm th:nth-child(1){width:17%}body table.list.assign.tm th:nth-child(2){width:11%}
body table.list.assign.tm th:nth-child(3){width:20%}body table.list.assign.tm th:nth-child(4){width:8%}
body table.list.assign.tm th:nth-child(5){width:20%}body table.list.assign.tm th:nth-child(6){width:10%}
body table.list.assign.tm th:nth-child(7){width:14%}
body table.list.assign.tm td{vertical-align:top}
}
@media(max-width:800px){body table.list.assign.tm{table-layout:auto;min-width:0!important;width:100%!important}body table.list.assign.tm td{display:block;width:100%}}
body table.list.assign.tm td .tn{font-weight:700;color:var(--navy);overflow-wrap:anywhere}
body .qi-list td,body .qi-list th{vertical-align:middle}
body .qi-list td:last-child{white-space:nowrap}

/* ======== Edit / Add dialog (Subject Management and Room Management) ======== */
dialog.dlg{border:0;border-radius:16px;padding:0;width:min(560px,calc(100vw - 1.6rem));max-height:calc(100vh - 2rem);overflow:auto;color:var(--ink);background:#fff;box-shadow:0 24px 60px rgba(14,26,90,.35)}
dialog.dlg::backdrop{background:rgba(14,26,90,.45)}
dialog.dlg:not([open]){display:none}
.dlg-form{padding:1.2rem 1.3rem 1.3rem}
.dlg-form h3{margin:0 0 .8rem;color:var(--navy)}
.dlg-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.8rem 1rem;align-items:end}
.dlg-grid>div{min-width:0}
.dlg-grid>.wide{grid-column:1/-1}
.dlg-grid input,.dlg-grid select{width:100%;min-width:0}
.dlg-grid [hidden]{display:none!important}
.dlg-form .btnrow{justify-content:flex-end}
.dlg-form .msg{margin:0 0 .8rem}
@media(max-width:560px){.dlg-grid{grid-template-columns:minmax(0,1fr)}.dlg-form .btnrow>*{flex:1 1 100%}}
.subj-t td:nth-child(2) .cur-name{overflow-wrap:anywhere}

/* ======== Teacher's Program: header in two aligned columns ======== */
.doc .meta2{display:grid;grid-template-columns:max-content minmax(0,1fr) max-content minmax(0,1fr);column-gap:.5rem;row-gap:.25rem;align-items:baseline;margin:.8rem 0 1rem;font-size:.95rem;line-height:1.35}
.doc .meta2 .ml{font-weight:700;color:var(--navy);white-space:nowrap}
.doc .meta2 .mv{min-width:0;overflow-wrap:anywhere}
.doc .meta2 .ml.r{padding-left:1.6rem}
@media(max-width:560px){.doc .meta2{font-size:.82rem;column-gap:.35rem}.doc .meta2 .ml.r{padding-left:.7rem}}
@media print{html .doc .meta2,html.pm .doc .meta2{display:grid!important;grid-template-columns:max-content minmax(0,1fr) max-content minmax(0,1fr)!important;column-gap:6px!important;row-gap:2px!important;font-size:10px!important;line-height:1.3!important;margin:4px 0!important}
 html .doc .meta2 .ml.r{padding-left:14px!important}}

/* ======== Signature blocks: the name sits ON the line, centred, with the title under it ======== */
html .doc .sign,html .doc .sign.cls{display:grid!important;grid-template-columns:repeat(auto-fit,minmax(190px,1fr))!important;gap:1.2rem 2rem!important;align-items:stretch;text-align:center}
html .doc .sign.cls{grid-template-columns:repeat(2,minmax(0,1fr))!important}
html .doc .sign>div{display:flex;flex-direction:column;justify-content:space-between;min-width:0}
html .doc .sign .role{margin:0 0 2.2rem!important;text-align:center!important;font-size:.9rem;color:var(--ink)}
html .doc .sign .name{margin:0!important;padding:0 .4rem .12rem!important;border:0!important;border-bottom:1px solid var(--ink)!important;text-decoration:none!important;text-align:center!important;font-weight:700;line-height:1.25;color:var(--ink);overflow-wrap:anywhere}
html .doc .sign .title{margin:.2rem 0 0!important;text-align:center!important;font-size:.85rem;color:var(--ink)}
@media print{
 html .doc .sign,html.pm .doc .sign{grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:2px 22px!important;margin-top:8px!important}
 html .doc .sign.cls,html.pm .doc .sign.cls{grid-template-columns:repeat(2,minmax(0,1fr))!important}
 html .doc .sign .role,html.pm .doc .sign .role{margin:0 0 22px!important;font-size:9px!important}
 html .doc .sign .name,html.pm .doc .sign .name{margin:0!important;font-size:10px!important;padding:0 2px 1px!important}
 html .doc .sign .title,html.pm .doc .sign .title{font-size:9px!important;margin:1px 0 0!important}}

/* ======== Printing several programs: every program starts on its own page ======== */
@media print{
 html body .pdoc{break-inside:avoid!important;page-break-inside:avoid!important;break-after:auto;page-break-after:auto}
 html body .pdoc + .pdoc,html.pm body .pdoc + .pdoc{break-before:page!important;page-break-before:always!important}
 html body .pdoc .doc-date{display:none!important}}

/* ======== Light buttons (tiles, tabs, text buttons): hover is a soft tint, never the dark blue fill of solid buttons ======== */
body .qi-tile:hover,body .qi-tile.on:hover{background:var(--tint);border-color:var(--blue);color:var(--ink);transform:none;box-shadow:0 0 0 2px var(--tint) inset}
body .daytab:not(.on):hover{background:var(--tint);color:var(--blue)}
body .roombtn:hover,body .slot button.tlink:hover{transform:none;box-shadow:none}

/* ======== Teacher's Program details: left = aligned label/value; right = each label followed directly by its value ======== */
html body .doc .meta2{display:grid!important;grid-template-columns:max-content minmax(0,1fr) max-content!important;
 column-gap:.6rem!important;row-gap:.45rem!important;align-items:start!important;margin:.9rem 0 1.1rem!important;line-height:1.4}
html body .doc .meta2 .ml{white-space:nowrap;padding:0!important;margin:0}
html body .doc .meta2 .mv{min-width:0;overflow-wrap:anywhere}
html body .doc .meta2 .mr{display:block;white-space:nowrap;padding-left:1.2rem}
html body .doc .meta2 .mr .ml{margin-right:.4rem}
@media(max-width:560px){html body .doc .meta2{grid-template-columns:max-content minmax(0,1fr)!important;column-gap:.6rem!important}
 html body .doc .meta2 .mr{grid-column:1/-1;padding-left:0;white-space:normal}}
@media print{
 html.pm body .doc .meta2,html body .doc .meta2{display:grid!important;grid-template-columns:max-content minmax(0,1fr) max-content!important;column-gap:6px!important;row-gap:3px!important;font-size:10px!important;margin:6px 0 8px!important}
 html.pm body .doc .meta2 .mr,html body .doc .meta2 .mr{padding-left:12px!important}
 html.pm body .doc .meta2 .mr .ml,html body .doc .meta2 .mr .ml{margin-right:4px!important}}

/* ======== Teacher's Program signatures: three centred blocks with short lines ======== */
html body .doc .sign:not(.cls){display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:1rem 1.5rem!important;justify-items:center;align-items:start;margin-top:1.4rem!important;break-inside:avoid;page-break-inside:avoid}
html body .doc .sign:not(.cls)>div{display:flex!important;flex-direction:column!important;align-items:center!important;justify-content:flex-start!important;width:100%;min-width:0}
html body .doc .sign:not(.cls) .role{margin:0 0 1.6rem!important;text-align:center!important}
html body .doc .sign:not(.cls) .name{display:block!important;width:max-content!important;min-width:9rem;max-width:100%;margin:0 auto!important;padding:0 .4rem .12rem!important;text-align:center!important;border:0!important;border-bottom:1px solid var(--ink)!important}
html body .doc .sign:not(.cls) .title{margin:.2rem auto 0!important;text-align:center!important}
@media(max-width:560px){html body .doc .sign:not(.cls){grid-template-columns:1fr!important}}
@media print{
 html.pm body .doc .sign:not(.cls),html body .doc .sign:not(.cls){grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:6px 14px!important;margin-top:10px!important}
 html.pm body .doc .sign:not(.cls) .role,html body .doc .sign:not(.cls) .role{margin:0 0 16px!important}
 html.pm body .doc .sign:not(.cls) .name,html body .doc .sign:not(.cls) .name{min-width:120px}}

/* ======== Class Program signatures: Prepared by (centre), Checked / Reviewed (two columns), Approved by (centre).
   Short lines: the line is only as wide as the printed name (never the whole column). ======== */
html body .doc .sign.cls{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:1.1rem 2.5rem!important;
 justify-items:center;align-items:start;text-align:center;margin-top:1.4rem!important;break-inside:avoid;page-break-inside:avoid}
html body .doc .sign.cls>.sg{display:flex!important;flex-direction:column!important;align-items:center!important;justify-content:flex-start!important;width:100%;min-width:0}
html body .doc .sign.cls>.sg.sg-one{grid-column:1/-1!important;width:100%!important;justify-self:center!important}
html body .doc .sign.cls .role{margin:0 0 1.9rem!important;text-align:center!important}
html body .doc .sign.cls .name{display:block!important;width:max-content!important;min-width:11rem;max-width:min(100%,17rem);margin:0 auto!important;
 padding:0 .5rem .12rem!important;text-align:center!important;border:0!important;border-bottom:1px solid var(--ink)!important}
html body .doc .sign.cls .title{margin:.2rem auto 0!important;text-align:center!important;max-width:17rem;overflow-wrap:anywhere}
@media(max-width:560px){html body .doc .sign.cls{grid-template-columns:1fr!important}}
@media print{
 html.pm body .doc .sign.cls,html body .doc .sign.cls{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:8px 28px!important;margin-top:10px!important}
 html.pm body .doc .sign.cls .role,html body .doc .sign.cls .role{margin:0 0 20px!important}
 html.pm body .doc .sign.cls .name,html body .doc .sign.cls .name{min-width:150px;max-width:210px}
 html.pm body .doc .sign.cls .title,html body .doc .sign.cls .title{max-width:210px}}

/* Outline (plain) and danger buttons: their own hover/press colours must win over the generic primary rule,
   otherwise an outline button turned solid blue on hover while its text stayed blue (unreadable). */
@media(hover:hover){
 body button.plain:hover:not(:disabled),body .btn.plain:hover{background:var(--tint)!important;color:var(--blue)!important;border-color:var(--blue)!important;box-shadow:none!important}
 body button.danger:hover:not(:disabled){background:var(--bad)!important;color:#fff!important;border-color:var(--bad)!important;box-shadow:none!important}
}
body button.plain:active:not(:disabled),body .btn.plain:active{background:#dfe4fb!important;color:var(--navy)!important;border-color:var(--blue)!important}
body button.danger:active:not(:disabled){background:#8d2222!important;color:#fff!important;border-color:#8d2222!important}
body button.plain:focus-visible,body .btn.plain:focus-visible{background:#fff;color:var(--blue)}
body main .tf-sfield input[type=search],body main .tsearch .sfield input{padding-left:2.7rem!important;padding-right:2.7rem!important}
body .editcell button.plain,body .editcell .btn.plain,body .row-acts>button.plain{border:1.5px solid #b9c1ec;background:#fff;color:var(--blue);min-height:36px;padding:.3rem .85rem}
body .editcell button.danger,body .row-acts>form>button.danger{border:1.5px solid var(--bad);min-height:36px;padding:.3rem .85rem}
.tf-sort{flex:1 1 220px}
.dlg-form .btnrow button.plain{border:1.5px solid #b9c1ec;background:#fff;color:var(--blue);min-height:44px;padding:.4rem 1.1rem}
"""

DLG_JS = r"""<script>(function(){
/* One small helper for every "Edit" / "Add" dialog. A button with data-edit-dlg="dialogId" and data-json='{...}'
   opens that dialog and fills each field whose name is a key of the JSON. Keys starting with "_" are options:
   _title (heading), _lock (field names shown but not editable), _mode ("new" or "edit"). */
function fill(d,o){
 var lock=o._lock||[];
 d.setAttribute('data-mode',o._mode||'edit');
 var t=d.querySelector('[data-title]');if(t&&o._title)t.textContent=o._title;
 d.querySelectorAll('[name]').forEach(function(el){
  var k=el.name;if(k==='csrf'||k==='action')return;
  if(Object.prototype.hasOwnProperty.call(o,k)){if(el.type==='checkbox')el.checked=!!o[k];else el.value=o[k]==null?'':o[k];}
  el.disabled=lock.indexOf(k)>-1;
 });
 var n=d.querySelector('[data-note]');if(n)n.textContent=o._note||'';
 d.dispatchEvent(new CustomEvent('dlg:fill',{detail:o}));
}
function open(d){if(typeof d.showModal==='function'){if(!d.open)d.showModal();}else d.setAttribute('open','');}
function shut(d){if(typeof d.close==='function')d.close();else d.removeAttribute('open');}
window.dlgOpen=function(id,o){var d=document.getElementById(id);if(!d)return;fill(d,o||{});open(d);var f=d.querySelector('input:not([type=hidden]):not(:disabled),select:not(:disabled)');if(f)setTimeout(function(){f.focus();},30);};
document.addEventListener('click',function(e){
 var b=e.target.closest('[data-edit-dlg]');
 if(b){var o={};try{o=JSON.parse(b.getAttribute('data-json')||'{}');}catch(x){}window.dlgOpen(b.getAttribute('data-edit-dlg'),o);return;}
 var c=e.target.closest('[data-close]');
 if(c){var d=c.closest('dialog');if(d)shut(d);return;}
 if(e.target.tagName==='DIALOG'&&e.target.classList.contains('dlg')){var r=e.target.getBoundingClientRect();
  if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)shut(e.target);}
});
})();</script>
"""

TEMPLATES = {
"base.html": """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script>try{if(localStorage.getItem('view')==='desktop'){document.querySelector('meta[name=viewport]').setAttribute('content','width=1100');}}catch(e){}</script>
<script>if(window.name==='editframe'){document.documentElement.className+=' inmodal introseen';}</script>
<script>try{if(sessionStorage.getItem('intro')==='1')document.documentElement.classList.add('introseen');}catch(e){}</script>
<title>{% block title %}{% endblock %} | {{ app_name }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Poppins:wght@500;600;700&display=swap" rel="stylesheet">
<style>""" + CSS + ADDON_CSS + UX_CSS + UX2_CSS + FIX_CSS + """</style></head><body>
<div id="intro" role="status" aria-label="Welcome">{% if has_logo %}<img class="i-logo" src="{{ logo_url }}" alt="">{% else %}<svg class="i-logo" viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="12" fill="#2d32c8"/><path d="M24 12 7 20l17 8 17-8-17-8z" fill="#fff"/><path d="M14 25v7c0 2 4.5 5 10 5s10-3 10-5v-7l-10 4.6L14 25z" fill="#fff" opacity=".85"/></svg>{% endif %}
<h1>{{ app_name }}</h1><div class="i-sch">{{ cfg.school_name }}</div>
<div class="i-bar"><i></i></div><button type="button" class="i-skip">Skip</button></div>
{% if g.user %}<header class="top"><div class="in">
<button type="button" class="menubtn" id="menubtn" aria-expanded="false" aria-controls="sidenav" aria-label="Open menu"><span class="bars" aria-hidden="true"><i></i><i></i><i></i></span></button>
<a class="brand" href="{{ url_for('home') }}">{% if has_logo %}<img class="brand-logo" src="{{ logo_url }}" alt="{{ cfg.school_name }} logo">{% else %}<svg class="brand-logo" viewBox="0 0 48 48" role="img" aria-label="School"><rect width="48" height="48" rx="12" fill="#2d32c8"/><path d="M24 12 7 20l17 8 17-8-17-8z" fill="#fff"/><path d="M14 25v7c0 2 4.5 5 10 5s10-3 10-5v-7l-10 4.6L14 25z" fill="#fff" opacity=".85"/></svg>{% endif %}
<div class="brand-name">{{ app_name }}<small>San Jose Litex Senior High School</small></div></a>
</div></header>
<div class="shell"><div class="navback" id="navback"></div><aside class="side noprint" id="sidenav" aria-label="Main navigation"><div class="side-h"><span>Menu</span><button type="button" class="side-toggle" id="sidetoggle" aria-label="Collapse or expand the menu" title="Collapse or expand the menu"><span class="cl">&lsaquo;</span><span class="ex">&rsaquo;</span></button></div><nav class="mainnav">{{ main_nav(bell, pending) if g.user.role == "admin" else teacher_nav(bell) }}</nav><div class="side-acct"><div class="who"><span class="av" aria-hidden="true">{{ g.user.full_name[:1]|upper }}</span><span class="wn">{{ g.user.full_name }}<small>{{ "Administrator" if g.user.role == "admin" else "Teacher" }}</small></span></div>{{ account_nav() }}<a class="mn out" href="{{ url_for("logout") }}" title="Sign out"><span class="mn-ic"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg></span><span class="mn-tx"><b>Sign out</b></span></a></div></aside><div class="shellmain">{% endif %}{% block page %}<main>

{% if g.user and g.user.role == 'admin' and approval and request.endpoint in ('dashboard','auto_generate','auto_conflicts','program','auto_loading','auto_reports') %}<div class="msg ok noprint"><strong>Schedule approved and locked</strong> by {{ approval.by }} on {{ approval.at|stamp12 }}. Changes are blocked until it is reopened in Validation Center.</div>{% endif %}
{% for cat, m in get_flashed_messages(with_categories=true) %}<div class="msg {{ cat }}" role="status">{{ m }}</div>{% endfor %}
{% block content %}{% endblock %}</main>
<footer>{{ cfg.school_name }} &middot; {{ app_name }}<br><a href="#" class="viewtoggle" hidden></a></footer>{% endblock %}{% if g.user %}</div></div>{% endif %}
<script>(function(){
var b=document.getElementById('menubtn'),bd=document.getElementById('navback'),sd=document.getElementById('sidenav'),bo=document.body;
function setMenu(o){bo.classList.toggle('navopen',o);if(b){b.setAttribute('aria-expanded',o);b.setAttribute('aria-label',o?'Close menu':'Open menu');}
 if(o&&sd&&window.matchMedia('(max-width:1100px)').matches){var f=sd.querySelector('.mn.on')||sd.querySelector('.mn');if(f)f.focus({preventScroll:true});}}
if(b&&sd){b.addEventListener('click',function(){setMenu(!bo.classList.contains('navopen'));});
 if(bd)bd.addEventListener('click',function(){setMenu(false);});
 sd.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('a.mn');if(!a)return;
  if(!a.classList.contains('out')&&!(e.metaKey||e.ctrlKey||e.shiftKey||e.button)){sd.querySelectorAll('a.mn.on').forEach(function(x){x.classList.remove('on');x.removeAttribute('aria-current');});a.classList.add('on');a.setAttribute('aria-current','page');}
  setMenu(false);});
 document.addEventListener('keydown',function(e){if(e.key==='Escape'&&bo.classList.contains('navopen')){setMenu(false);b.focus();}});
 var mq=window.matchMedia('(min-width:1101px)');if(mq.addEventListener)mq.addEventListener('change',function(m){if(m.matches)setMenu(false);});}
document.querySelectorAll('table.list').forEach(function(t){
 var hs=t.querySelectorAll('thead th');if(!hs.length)return;
 t.classList.add('stack');
 t.querySelectorAll('tbody tr').forEach(function(r){var i=0;
  Array.prototype.forEach.call(r.children,function(c){var l=hs[i]?(hs[i].getAttribute('data-label')||hs[i].textContent.trim()):'';if(l)c.setAttribute('data-label',l);i+=c.colSpan||1;});});});
document.querySelectorAll('.mobile-days').forEach(function(w){
 var tabs=w.querySelectorAll('.daytab'),pan=w.querySelectorAll('.dayp');
 var names=Array.prototype.map.call(tabs,function(x){return x.getAttribute('data-d')});
  function show(d){tabs.forEach(function(x){x.classList.toggle('on',x.getAttribute('data-d')===d)});
  pan.forEach(function(x){x.classList.toggle('on',x.getAttribute('data-dp')===d)});}
 tabs.forEach(function(x){x.addEventListener('click',function(){show(x.getAttribute('data-d'))})});
 show(names.indexOf('Monday')>=0?'Monday':names[0]);});
})();</script>
<script>(function(){
function conv(h,m,a){h=+h;m=+(m||0);a=a.toUpperCase();h=a==='AM'?h%12:(a==='PM'?h%12+12:12);return h*60+m;}
function calc(t){var f=[],re=/(\\d{1,2})(?::(\\d{2}))?\\s*(AM|PM|NN)\\b/gi,m;
 while((m=re.exec(t)))f.push(m);if(f.length<2)return null;
 var d=conv(f[1][1],f[1][2],f[1][3])-conv(f[0][1],f[0][2],f[0][3]);return d>0?d:null;}
function hrs(v){var h=Math.floor(v/60),m=v%60,p=[];if(h)p.push(h+' hr'+(h!==1?'s':''));if(m)p.push(m+' min');return p.join(' ')||'0 hrs';}
document.querySelectorAll('input[data-official]').forEach(function(i){
 if(i.closest('.assign'))return; /* no minutes hint in the Assignments table */
 var w=i.closest('.otime')||i.parentNode;
 var o=w.nextElementSibling;
 if(!o||!o.classList||!o.classList.contains('offmin')){o=document.createElement('p');o.className='hint offmin';w.parentNode.insertBefore(o,w.nextSibling);}
 function up(){var v=calc(i.value);o.textContent=v?'= '+v+' minutes ('+hrs(v)+') per day, '+hrs(v*5)+' per week':(i.value.trim()?'Set the start and end time to compute the minutes.':'');}
 i.addEventListener('input',up);up();});
})();</script>
<script>(function(){
document.querySelectorAll('[data-otime]').forEach(function(w){
 var h=w.querySelector('input[type=hidden]'),a=w.querySelector('.ot-from'),b=w.querySelector('.ot-to');
 function f(v){var p=v.split(':'),H=+p[0],ap=H>=12?'PM':'AM';H=H%12||12;return H+':'+p[1]+' '+ap;}
 function up(){h.value=(a.value&&b.value)?f(a.value)+' - '+f(b.value):'';h.dispatchEvent(new Event('input',{bubbles:true}));}
 a.addEventListener('input',up);b.addEventListener('input',up);});
})();</script>
<script>(function(){
var EYE='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
var OFF='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.9 10.9 0 0 1 12 19C5 19 1 12 1 12a18.5 18.5 0 0 1 5.06-5.94M9.9 4.24A9.1 9.1 0 0 1 12 4c7 0 11 7 11 7a18.5 18.5 0 0 1-2.16 3.19M14.12 14.12a3 3 0 1 1-4.24-4.24"/><path d="M1 1l22 22"/></svg>';
document.querySelectorAll('input[type=password]').forEach(function(i){
 var w=document.createElement('span');w.className='pwwrap';i.parentNode.insertBefore(w,i);w.appendChild(i);
 var b=document.createElement('button');b.type='button';b.className='eye';b.innerHTML=EYE;
 b.setAttribute('aria-label','Show password');b.setAttribute('aria-pressed','false');
 b.addEventListener('mousedown',function(e){e.preventDefault();});  /* a tap must not pull focus (and the keyboard) out of the field */
 b.addEventListener('click',function(){var show=i.type==='password',s0=i.selectionStart,s1=i.selectionEnd,had=document.activeElement===i;
  i.type=show?'text':'password';b.innerHTML=show?OFF:EYE;
  b.setAttribute('aria-label',show?'Hide password':'Show password');b.setAttribute('aria-pressed',show?'true':'false');
  if(had){i.focus({preventScroll:true});try{i.setSelectionRange(s0,s1);}catch(x){}}});
 w.appendChild(b);});
})();</script>
<script>document.querySelectorAll('.viewtoggle').forEach(function(a){
var d=false;try{d=localStorage.getItem('view')==='desktop'}catch(e){}
if(Math.max(screen.width,screen.height)>1000&&!d)return;
a.hidden=false;a.textContent=d?'Switch to mobile view':'Switch to desktop view';
a.addEventListener('click',function(e){e.preventDefault();try{localStorage.setItem('view',d?'mobile':'desktop')}catch(x){}location.reload();});});</script>
<script>(function(){
function fit(){var h=document.documentElement,L=document.querySelectorAll('.doc');if(!L.length)return;
 L.forEach(function(d){d.style.removeProperty('--zl');d.style.removeProperty('--zp');d.style.removeProperty('width');});
 h.classList.add('pm');
 [['--zl',297,210],['--zp',210,297]].forEach(function(o){
  var PW=Math.floor((o[1]-12)/25.4*96),PH=Math.floor((o[2]-12)/25.4*96)-6;
  L.forEach(function(d){var lo=.4,hi=1.2,i,z;function ok(v){d.style.setProperty('width',(PW/v)+'px','important');return d.scrollHeight*v<=PH*.95;}
   if(ok(hi)){lo=hi;}else{for(i=0;i<9;i++){z=(lo+hi)/2;if(ok(z))lo=z;else hi=z;}}
   d.style.setProperty(o[0],lo.toFixed(3));d.style.removeProperty('width');});});
 h.classList.remove('pm');}
function reset(){document.querySelectorAll('.doc').forEach(function(d){d.style.removeProperty('--zl');d.style.removeProperty('--zp');});}
window.addEventListener('beforeprint',fit);window.addEventListener('afterprint',reset);
})();</script>
<script>(function(){
if(!document.querySelector('header.top'))return; /* only inside the system, not on the login pages */
/* ---- one confirmation dialog for the whole system ---- */
var modal=document.createElement('div');modal.className='qmodal';modal.hidden=true;
modal.innerHTML='<div class="qm-card" role="alertdialog" aria-modal="true" aria-labelledby="qm-t" aria-describedby="qm-m"><h3 id="qm-t"></h3><p id="qm-m"></p><div class="qm-acts"><button type="button" class="plain" data-no>Cancel</button><button type="button" data-yes>Continue</button></div></div>';
document.body.appendChild(modal);
var card=modal.firstChild,yes=modal.querySelector('[data-yes]'),no=modal.querySelector('[data-no]'),onOk=null,back=null;
function closeModal(){modal.classList.remove('on');setTimeout(function(){modal.hidden=true;},220);if(back&&back.focus)back.focus();onOk=null;}
window.uiConfirm=function(msg,ok){var bad=/delete|remove|reject|cannot be undone|replace/i.test(msg);
 document.getElementById('qm-t').textContent=bad?'Please confirm':'Confirm';document.getElementById('qm-m').textContent=msg;
 card.classList.toggle('danger',bad);yes.textContent=bad?'Yes, continue':'Continue';
 back=document.activeElement;onOk=ok;modal.hidden=false;requestAnimationFrame(function(){modal.classList.add('on');(bad?no:yes).focus();});};
yes.addEventListener('click',function(){var f=onOk;closeModal();if(f)f();});
no.addEventListener('click',closeModal);
modal.addEventListener('click',function(e){if(e.target===modal)closeModal();});
document.addEventListener('keydown',function(e){if(modal.hidden)return;if(e.key==='Escape')closeModal();
 if(e.key==='Tab'){var els=[no,yes],i=els.indexOf(document.activeElement);e.preventDefault();els[(i+(e.shiftKey?-1:1)+2)%2].focus();}});
/* the old inline confirm("...") questions use the same dialog */
function lit(v){v=(v||'').trim();var pre='return confirm(';if(v.indexOf(pre)!==0)return null;v=v.slice(pre.length);
 if(v.slice(-1)===';')v=v.slice(0,-1);if(v.slice(-1)!==')')return null;v=v.slice(0,-1).trim();
 var q=v.charAt(0);if((q!=="'"&&q!=='"')||v.charAt(v.length-1)!==q)return null;
 var inner=v.slice(1,-1),out='',i,c;for(i=0;i<inner.length;i++){c=inner.charAt(i);
  if(c===String.fromCharCode(92)){i++;out+=inner.charAt(i);}else if(c===q)return null;else out+=c;}
 return out;}
document.querySelectorAll('form[onsubmit]').forEach(function(f){var m=lit(f.getAttribute('onsubmit'));if(m!==null){f.removeAttribute('onsubmit');f.setAttribute('data-confirm',m);}});
document.querySelectorAll('button[onclick]').forEach(function(x){var m=lit(x.getAttribute('onclick'));if(m!==null){x.removeAttribute('onclick');x.setAttribute('data-confirm',m);}});
document.addEventListener('submit',function(ev){
 var f=ev.target;if(!f||f.tagName!=='FORM')return;
 if(f.__ok){f.__ok=false;return;}
 var b=ev.submitter||null,m=(b&&b.getAttribute('data-confirm'))||f.getAttribute('data-confirm');
 if(!m){
  if((f.getAttribute('method')||'get').toLowerCase()!=='post')return;
  if(f.hasAttribute('data-noconfirm')||f.hasAttribute('onsubmit'))return; /* already asks */
  b=b||f.querySelector('button[type=submit],button:not([type])');if(!b)return;
  if((b.getAttribute('onclick')||'').indexOf('confirm')>-1)return;
  var t=(b.textContent||b.value||'').trim().toLowerCase();
  if(f.id==='addform')m='Are you sure you want to add this period?';
  else if(/delete|remove|clear|reject|decline/.test(t))m='Are you sure you want to delete this? This cannot be undone.';
  else if(/approve|reset/.test(t))m='Are you sure you want to continue?';
  else if(/\\badd\\b|create|^new\\b/.test(t))m='Are you sure you want to add this?';
  else if(/save|update|change|apply|done/.test(t))m='Are you sure you want to save these changes?';
 }
 if(!m)return;
 ev.preventDefault();ev.stopImmediatePropagation();
 window.uiConfirm(m,function(){f.__ok=true;if(f.requestSubmit){try{f.requestSubmit(ev.submitter||undefined);}catch(x){f.submit();}}else f.submit();});
},true);
/* ---- flash messages become toasts: success fades out by itself, errors stay until dismissed ---- */
var host=document.createElement('div');host.id='toasts';host.className='noprint';document.body.appendChild(host);
document.querySelectorAll('main .msg[role=status]').forEach(function(m){
 var ok=!m.classList.contains('error'),t=document.createElement('div');
 t.className='qtoast '+(ok?'ok':'error');t.setAttribute('role',ok?'status':'alert');
 t.innerHTML='<span class="qi"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(ok?'<path d="M5 12.5l4.5 4.5L19 7.5"/>':'<path d="M12 7v6M12 17h.01"/>')+'</svg></span><span class="qt"></span><button type="button" class="qx" aria-label="Dismiss">&times;</button>';
 t.querySelector('.qt').innerHTML=m.innerHTML;
 function gone(){t.classList.add('out');setTimeout(function(){if(t.parentNode)t.parentNode.removeChild(t);},220);}
 t.querySelector('.qx').addEventListener('click',gone);setTimeout(gone,ok?6000:14000);
 host.appendChild(t);m.parentNode.removeChild(m);});
})();</script>
<script>(function(){
function strip(im){var raw=new Image();raw.onload=function(){try{
 var W=raw.naturalWidth,H=raw.naturalHeight;if(!W||!H||W*H>4000000)return;
 var c=document.createElement('canvas');c.width=W;c.height=H;var x=c.getContext('2d');x.drawImage(raw,0,0);
 var d=x.getImageData(0,0,W,H),a=d.data;if(a[3]<20)return;
 var r0=a[0],g0=a[1],b0=a[2],tol=60,seen=new Uint8Array(W*H),st=[];
 function near(i){var o=i*4;return a[o+3]>0&&Math.abs(a[o]-r0)+Math.abs(a[o+1]-g0)+Math.abs(a[o+2]-b0)<tol;}
 for(var i=0;i<W;i++){st.push(i,(H-1)*W+i);}for(var j=0;j<H;j++){st.push(j*W,j*W+W-1);}
 while(st.length){var n=st.pop();if(n<0||n>=W*H||seen[n]||!near(n))continue;seen[n]=1;a[n*4+3]=0;
  var cx=n%W;if(cx>0)st.push(n-1);if(cx<W-1)st.push(n+1);st.push(n-W,n+W);}
 x.putImageData(d,0,0);im.src=c.toDataURL('image/png');}catch(e){}};
 raw.src=im.getAttribute('src');}
document.querySelectorAll('#intro img.i-logo,img.brand-logo,img.logoimg').forEach(strip);
})();</script>
<script>(function(){var el=document.getElementById('intro');if(!el)return;
if(document.documentElement.classList.contains('introseen')){el.remove();return;}
try{sessionStorage.setItem('intro','1');}catch(e){}
document.body.style.overflow='hidden';
function done(){el.classList.add('hide');document.body.style.overflow='';setTimeout(function(){if(el.parentNode)el.remove();},700);}
var t=setTimeout(done,800);el.addEventListener('click',function(){clearTimeout(t);done();});})();</script>
<script>document.addEventListener('click',function(ev){var b=ev.target.closest?ev.target.closest('.tlink'):null;if(!b)return;
var id=b.getAttribute('data-t'),on=b.getAttribute('aria-expanded')!=='true';
document.querySelectorAll('.tlink').forEach(function(x){if(x.getAttribute('data-t')!==id)return;
var sl=x.closest('.slot'),n=sl?sl.querySelector('.tname'):null;if(!n)return;
n.classList.toggle('show',on);x.setAttribute('aria-expanded',on?'true':'false');});});</script>
<script>document.addEventListener('click',function(ev){var b=ev.target.closest?ev.target.closest('.roombtn'):null;
if(!b){document.querySelectorAll('.roompop.show').forEach(function(p){p.classList.remove('show');});
document.querySelectorAll('.roombtn[aria-expanded=true]').forEach(function(x){x.setAttribute('aria-expanded','false');});return;}
var on=b.getAttribute('aria-expanded')!=='true',pop=b.parentNode.querySelector('.roompop');if(!pop)return;
pop.classList.toggle('show',on);b.setAttribute('aria-expanded',on?'true':'false');});</script>
""" + BTN_JS + """
""" + TF_JS + DLG_JS + EDIT_MODAL_JS + """{% if g.user %}<div class="toast noprint" id="toast" role="status" aria-live="polite" hidden><span>{{ 'New request or problem report received.' if g.user.role == 'admin' else 'You have a new notification.' }}</span><a href="{{ url_for('reports') if g.user.role == 'admin' else url_for('notifications') }}">Open</a><button type="button" class="toastx" id="toastx" aria-label="Dismiss">&times;</button></div>
<script>(function(){
var last={{ bell }},badges=document.querySelectorAll('.nbadge'),toast=document.getElementById('toast');
function setb(n){badges.forEach(function(b){b.textContent=n;b.hidden=!n;});}
document.getElementById('toastx').addEventListener('click',function(){toast.hidden=true;});
function check(){if(document.hidden)return;
 fetch('{{ url_for('notif_count') }}',{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.ok?r.json():null;}).then(function(d){
  if(!d)return;setb(d.n);if(d.n>last){toast.hidden=false;setTimeout(function(){toast.hidden=true;},12000);}last=d.n;}).catch(function(){});}
setInterval(check,30000);document.addEventListener('visibilitychange',check);
})();</script>{% endif %}
{% if g.user %}<script>(function(){function back(fb){var r=document.referrer,same=false;try{same=r&&new URL(r).origin===location.origin&&r!==location.href;}catch(e){}if(same&&history.length>1){history.back();}else{location.href=fb;}}
var d=document.getElementById('dockback');if(d)d.addEventListener('click',function(){back(d.getAttribute('data-fallback'));});
document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('a.backbtn');if(!a)return;var r=document.referrer,same=false;try{same=r&&new URL(r).origin===location.origin&&r!==location.href;}catch(x){}if(same&&history.length>1){e.preventDefault();history.back();}});})();</script>
{% if request.endpoint not in ('dashboard','profile','home') %}<script>(function(){
var m=document.querySelector('main');if(!m||m.querySelector('.backbtn'))return;
var row=document.createElement('div');row.className='backrow noprint';row.style.margin='0 0 .7rem';
row.innerHTML='<a class="backbtn noprint" href="{{ nav_back() }}" title="Back" aria-label="Back"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7"/></svg></a>';
m.insertBefore(row,m.firstChild);})();</script>{% endif %}
<script>(function(){var b=document.getElementById('sidetoggle');
if(b){try{if(localStorage.getItem('sidemini')==='1')document.body.classList.add('sidemini');}catch(e){}
b.addEventListener('click',function(){var on=document.body.classList.toggle('sidemini');try{localStorage.setItem('sidemini',on?'1':'0');}catch(e){}});}
setTimeout(function(){[].forEach.call(document.querySelectorAll('.msg.ok:not(.fitnote)'),function(m){m.style.transition='opacity .4s';m.style.opacity='0';setTimeout(function(){m.style.display='none';},450);});},6000);})();</script>
{% endif %}<script>(function(){var h=document.querySelector('header.top');if(!h)return;function f(){document.documentElement.style.setProperty('--hdrh',h.offsetHeight+'px');}f();window.addEventListener('resize',f);window.addEventListener('load',f);if(window.ResizeObserver)new ResizeObserver(f).observe(h);})();</script></body></html>""",

"macros.html": """{% macro back(url, label='Back') %}<a class="backbtn noprint" href="{{ url }}" title="{{ label }}" aria-label="{{ label }}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7"/></svg></a>{% endmacro %}

{% macro adviser_picker(teachers, selected=none, field='adviser_id', empty='Not assigned') %}
{% set cur = namespace(t=none) %}{% for t in teachers %}{% if t.id == selected %}{% set cur.t = t %}{% endif %}{% endfor %}
<div class="advpick" id="advpick"><input type="hidden" id="{{ field }}" name="{{ field }}" value="{{ selected or '' }}">
<input type="search" id="adv_q" class="advq" autocomplete="off" aria-label="Search teachers" value="{{ (tlabels.get(cur.t.id) ~ ' - ' ~ cur.t.full_name ~ ' (' ~ catname.get(cur.t.category, '') ~ ')') if cur.t else '' }}">
<ul class="advlist" id="adv_list" role="listbox" hidden>
<li data-id="" data-find="not assigned unassigned none clear" role="option">{{ empty }}</li>
{% for t in teachers %}<li data-id="{{ t.id }}" data-find="{{ (t.full_name ~ ' ' ~ tlabels.get(t.id, '') ~ ' ' ~ (t.teacher_id or '') ~ ' ' ~ t.category)|lower }}" data-text="{{ tlabels.get(t.id) }} - {{ t.full_name }} ({{ catname.get(t.category, '') }})" role="option"><strong>{{ t.full_name }}</strong><small>{{ tlabels.get(t.id) }} &middot; {{ t.teacher_id }} &middot; {{ catname.get(t.category, '') }}</small></li>{% endfor %}
<li class="advnone" id="adv_none" hidden>No teacher matches that name.</li></ul></div>
<script>(function(){
var box=document.getElementById('advpick'),q=document.getElementById('adv_q'),list=document.getElementById('adv_list'),hid=document.getElementById('{{ field }}'),none=document.getElementById('adv_none');
var items=[].slice.call(list.querySelectorAll('li[data-id]')),chosen=q.value;
function show(){var w=q.value===chosen&&hid.value?'':q.value.toLowerCase().trim().split(/\\s+/).filter(Boolean),n=0;
items.forEach(function(li){var f=li.getAttribute('data-find'),ok=!w.length||w.every(function(x){return f.indexOf(x)>-1;});li.hidden=!ok;if(ok)n++;});
none.hidden=n>0;list.hidden=false;}
function pick(li){hid.value=li.getAttribute('data-id');chosen=hid.value?li.getAttribute('data-text'):'';q.value=chosen;list.hidden=true;}
q.addEventListener('focus',function(){q.select();show();});
q.addEventListener('input',function(){if(q.value===''){hid.value='';chosen='';}show();});
list.addEventListener('mousedown',function(e){e.preventDefault();});
list.addEventListener('click',function(e){var li=e.target.closest('li[data-id]');if(li)pick(li);});
document.addEventListener('click',function(e){if(!box.contains(e.target)){list.hidden=true;q.value=chosen;}});
q.addEventListener('keydown',function(e){if(e.key==='Escape'){list.hidden=true;q.value=chosen;}
if(e.key==='Enter'){var f=items.filter(function(li){return !li.hidden;});if(!list.hidden){e.preventDefault();if(f.length)pick(f[0]);}}});
})();</script>
{% endmacro %}

{% macro class_doc(d, can_edit=false) %}
{% if d.stamp %}<p class="doc-date noprint">{{ d.stamp.label }}: {{ d.stamp.date }}</p>{% endif %}
<article class="doc">
{{ letterhead("GRADE " ~ d.cur.grade ~ " CLASS PROGRAM") }}
{% if d.cur.room %}
<p class="room"><button type="button" class="roombtn" data-room aria-expanded="false">{{ d.cur.room|upper }}</button><span class="roompop{{ '' if d.cur.building and d.cur.floor else ' nobf' }}">{% if d.cur.building and d.cur.floor %}Bldg. {{ d.cur.building }}, Floor {{ d.cur.floor }}{% else %}Building and floor not set yet.{% endif %}</span></p>
{% else %}<p class="room">Room not set</p>{% endif %}
<div class="meta"><div><b>Grade Level/Section:</b> {{ d.cur.name }}{% if d.cur.track %} ({{ d.cur.track }}){% endif %}</div>
<div><b>Adviser:</b> {{ d.adviser or 'Not assigned' }}</div></div>
{{ grid(d.rows, d.cells, 'program', can_edit) }}
{% if d.legend %}<p class="legend"><strong>Legend:</strong> {% for c, n in d.legend %}<mark class="lgc">{{ c }}</mark>-{{ n }}{{ ', ' if not loop.last }}{% endfor %}</p>{% endif %}
<div class="sign cls">
<div class="sg sg-one"><div class="role">Prepared by:</div><div class="name">{{ (d.adviser or '________________')|upper }}</div><div class="title">Adviser</div></div>
<div class="sg"><div class="role">Checked and verified by:</div><div class="name">{{ cfg.principal_name|upper }}</div><div class="title">{{ cfg.principal_title }}</div></div>
<div class="sg"><div class="role">Reviewed by:</div><div class="name">{{ cfg.psds_name|upper }}</div><div class="title">{{ cfg.psds_title }}</div></div>
<div class="sg sg-one"><div class="role">Approved by:</div><div class="name">{{ cfg.sdo_name|upper }}</div><div class="title">{{ cfg.sdo_title }}</div></div>
</div></article>
{% endmacro %}

{% macro teacher_doc(d) %}{% set t = d.t %}
{% if d.stamp %}<p class="doc-date noprint">{{ d.stamp.label }}: {{ d.stamp.date }}</p>{% endif %}
<article class="doc">
{{ letterhead("TEACHER'S PROGRAM") }}
<div class="meta2">
<span class="ml">Teacher:</span><span class="mv">{% if tlabels.get(t.id) %}Teacher-{{ tlabels.get(t.id) }}{% else %}-{% endif %} &ndash; {{ t.full_name|upper }}</span>
<span class="mr"><span class="ml">Item:</span> <span class="mv">{{ t.item or '-' }}</span></span>
<span class="ml">Subject:</span><span class="mv">{% if d.subjects %}{{ d.subjects|join('; ') }}{% else %}No subjects assigned{% endif %}</span>
<span class="mr"><span class="ml">No. of Teaching Loads:</span> <span class="mv">{{ d.summ.loads }}</span></span>
<span class="ml">Ancillary:</span><span class="mv">{{ d.ancillary }}</span>
<span class="mr"><span class="ml">Official Time:</span> <span class="mv">{{ (t.official_time|official_range) if t.official_time else '-' }}</span></span>
</div>
{{ grid(d.rows, d.cells, 'teacher', false, d.rowmins, d.summ) }}
<div class="sign">
<div><div class="role">Conformed:</div><div class="name">{{ t.full_name|upper }}</div><div class="title">Teacher</div></div>
<div><div class="role">Checked and verified by:</div><div class="name">{{ cfg.principal_name|upper }}</div><div class="title">{{ cfg.principal_title }}</div></div>
<div><div class="role">Reviewed by:</div><div class="name">{{ cfg.psds_name|upper }}</div><div class="title">{{ cfg.psds_title }}</div></div>
</div></article>
{% endmacro %}

{% macro otime(name, value, label) %}{% set rg = value|otimes %}<div class="otime" data-otime><input type="hidden" name="{{ name }}" value="{{ value or '' }}" data-official><input type="time" class="ot-from" value="{{ rg[0] }}" aria-label="{{ label }} start"><span>to</span><input type="time" class="ot-to" value="{{ rg[1] }}" aria-label="{{ label }} end"></div>{% endmacro %}

{% macro durselect(name, minutes, label, hi=600, k='', day='', auto='') %}<select name="{{ name }}" aria-label="{{ label }}"{% if k %} data-k="{{ k }}" data-d="{{ day }}" data-auto="{{ auto }}"{% endif %}>{% for v in dur_options(minutes, hi) %}<option value="{{ v }}" {{ 'selected' if v == (minutes or 0) }}>{{ v|durtxt }}</option>{% endfor %}</select>{% endmacro %}

{% macro specpick(name, value, label='Specialization', groups=none) %}{% set L = spec_live() %}{% set picked = (value or '').split(';')|map('trim')|select|list %}{% set G = groups or L.manage %}{% set gn = [] %}{% for _g, _items in G %}{% for _it in _items %}{% if gn.append(_it) %}{% endif %}{% endfor %}{% endfor %}
<div class="specpick"><input type="hidden" name="{{ name }}" value="{{ picked|join(spec_sep) }}"><div class="sp-text">{{ picked|join(', ') or '-' }}</div>
<details class="sp-box"><summary>{{ label }}: <span class="sp-count">{{ picked|length }}</span> selected</summary><div class="sp-pop">
<div class="sp-tools"><div class="sp-qrow"><input type="search" class="sp-q" aria-label="Search subjects" autocomplete="off"><button type="button" class="plain small sp-clearq">Clear search</button></div>
<div class="sp-acts"><button type="button" class="plain small sp-all">Select all matching</button><button type="button" class="plain small sp-none">Clear selection</button><span class="sp-res" aria-live="polite"></span></div></div>
<div class="sp-list">
{% for grp, items in G %}<fieldset><legend>{{ grp }}</legend>{% for it in items %}{% set m = L.meta.get(it) or {} %}<label data-s="{{ (it ~ ' ' ~ (m.code or '') ~ ' ' ~ (m.cluster or '') ~ ' ' ~ (m.category or '') ~ ' ' ~ (m.cls or '') ~ ' ' ~ grp)|lower }}"><input type="checkbox" value="{{ it }}" {{ 'checked' if it in picked }}><span>{{ it }}</span></label>{% endfor %}</fieldset>{% endfor %}{% set extra = picked|reject('in', gn)|list if groups else [] %}{% if extra %}<fieldset><legend>Already selected</legend>{% for it in extra %}<label data-s="{{ it|lower }}"><input type="checkbox" value="{{ it }}" checked><span>{{ it }}</span></label>{% endfor %}</fieldset>{% endif %}</div>
<p class="sp-empty" hidden>No matching subjects found</p></div>
{% set unknown = picked|reject('in', L.names)|list %}{% if unknown %}<p class="hint">Not an active subject: {{ unknown|join(', ') }}. It is dropped when you save; pick the matching choices instead.</p>{% endif %}</details></div>
<script>(function(){if(window.__specInit)return;window.__specInit=true;
function up(w){var h=w.querySelector('input[type=hidden]'),v=[];
w.querySelectorAll('.sp-list input[type=checkbox]').forEach(function(c){if(c.checked)v.push(c.value);});
h.value=v.join('; ');var n=w.querySelector('.sp-count');if(n)n.textContent=v.length;
var t=w.querySelector('.sp-text');if(t)t.textContent=v.length?v.join(', '):'-';}
function visible(l){var f=l.closest('fieldset');return !l.classList.contains('sp-nomatch')&&!(f&&f.hidden);}
function filt(w){var qi=w.querySelector('.sp-q');if(!qi)return;var terms=qi.value.toLowerCase().split(/\\s+/).filter(Boolean),shown=0,total=0;
w.querySelectorAll('.sp-list label').forEach(function(l){var hay=l.getAttribute('data-s')||'',ok=terms.every(function(t){return hay.indexOf(t)>-1;});l.classList.toggle('sp-nomatch',!ok);total++;if(ok)shown++;});
w.querySelectorAll('.sp-list fieldset').forEach(function(f){f.classList.toggle('sp-nomatch',!f.querySelector('label:not(.sp-nomatch)'));});
var e=w.querySelector('.sp-empty');if(e)e.hidden=shown>0;
var r=w.querySelector('.sp-res');if(r)r.textContent=terms.length?(shown+' of '+total+' match'):(total+' subjects');}
document.addEventListener('input',function(e){var q=e.target;if(q&&q.classList&&q.classList.contains('sp-q')){var w=q.closest('.specpick');if(w)filt(w);}});
document.addEventListener('keydown',function(e){if(e.key==='Enter'&&e.target.classList&&e.target.classList.contains('sp-q'))e.preventDefault();});
document.addEventListener('click',function(e){var b=e.target.closest?e.target.closest('.sp-clearq,.sp-all,.sp-none'):null;if(!b)return;var w=b.closest('.specpick');if(!w)return;
if(b.classList.contains('sp-clearq')){var q=w.querySelector('.sp-q');q.value='';filt(w);q.focus();}
else if(b.classList.contains('sp-all')){w.querySelectorAll('.sp-list label').forEach(function(l){if(visible(l))l.querySelector('input').checked=true;});up(w);}
else{w.querySelectorAll('.sp-list input[type=checkbox]').forEach(function(c){c.checked=false;});up(w);}});
document.addEventListener('toggle',function(e){var d=e.target;if(d&&d.classList&&d.classList.contains('sp-box')&&d.open){var w=d.closest('.specpick');filt(w);}},true);
document.addEventListener('change',function(e){var c=e.target;if(!c||c.type!=='checkbox')return;var w=c.closest?c.closest('.specpick'):null;if(w)up(w);});})();</script>
{% endmacro %}

{% macro hm(v) %}{% if v >= 60 %}<span class="hm">{{ v|hrs }}</span>{% endif %}{% endmacro %}

{% macro letterhead(title) %}
<div class="letterhead">{% if has_logo %}<a href="{{ url_for('home') }}" title="Home" aria-label="Home"><img class="lh-logo" src="{{ logo_url }}" alt=""></a>{% endif %}<div class="lh-text"><div class="school">{{ cfg.school_name }}</div><div class="addr">{{ cfg.school_address }}</div></div>{% if has_logo %}<img class="lh-logo lh-spacer" src="{{ logo_url }}" alt="" aria-hidden="true">{% endif %}</div>
<h2 class="doc-title">{{ title }}</h2><p class="doc-sub">{{ cfg.term }}</p>
{% endmacro %}

{% macro entry(e, mode, can_edit) %}
{% if e.kind == 'class' %}<div class="slot"><strong>{% if mode == 'teacher' %}{{ e.subject }}{% else %}{{ e.code or e.subject }}{% endif %}</strong>
{% if mode == 'teacher' %}<span>Section: <a class="seclink" href="{{ url_for('program', section=e.section_id) }}" title="Open the {{ e.section_name }} class program">{{ e.section_name }}</a></span><span>{{ ((e.end|tmin) - (e.start|tmin))|hrs }}</span>
{% elif e.other %}<span>Another teacher</span>
{% elif e.teacher_label %}<span class="tname show">{{ e.teacher_name }}</span>
{% else %}<span class="tname show">{{ e.teacher_ph or 'No teacher assigned' }}</span>{% endif %}{% if e.room and mode == 'teacher' %}<span>{{ e.room }}</span>{% endif %}
{% else %}<div class="slot rec"><strong>{{ e.subject }}</strong>{% endif %}
{% if can_edit %}<div class="acts"><a class="btn plain small" href="{{ url_for('entry_edit', eid=e.id) }}">Edit</a>
<form method="post" action="{{ url_for('entry_delete', eid=e.id) }}" onsubmit="return confirm('Remove this period?')">{{ csrf_field() }}<button class="danger">Remove</button></form></div>{% endif %}
</div>
{% endmacro %}

{% macro grid(rows, cells, mode, can_edit=false, rowmins=none, summ=none) %}
<div class="scroll gridwrap"><table class="grid">
<colgroup><col class="c-time">{% for d in days %}<col class="c-day">{% endfor %}{% if rowmins is not none %}<col class="c-min">{% endif %}</colgroup>
<thead><tr><th scope="col">Time</th>{% for d in days %}<th scope="col" data-day="{{ d }}">{{ d }}</th>{% endfor %}{% if rowmins is not none %}<th scope="col">No. of minutes</th>{% endif %}</tr></thead><tbody>
{% for r in rows %}{% set ri = loop.index0 %}{% set ns = namespace(rec=false) %}{% for d in days %}{% set c0 = cells[d][ri] %}{% if c0 and c0 != 'skip' and c0.e.kind == 'recess' %}{% set ns.rec = true %}{% endif %}{% endfor %}<tr><th scope="row"{% if ns.rec %} class="recess"{% endif %}>{{ r[0]|tm }} to {{ r[1]|tm }}</th>
{% for d in days %}{% set c = cells[d][ri] %}{% if c is none %}<td data-day="{{ d }}"></td>{% elif c != 'skip' %}<td data-day="{{ d }}" rowspan="{{ c.span }}"{% if c.e.kind == 'recess' %} class="recess"{% endif %}>{{ entry(c.e, mode, can_edit) }}{% for m in c.more %}{{ entry(m, mode, can_edit) }}{% endfor %}</td>{% endif %}{% endfor %}
{% if rowmins is not none %}<td class="num{{ ' recess' if ns.rec }}">{{ rowmins[ri] or '' }}</td>{% endif %}</tr>
{% else %}<tr><td colspan="8" class="empty">No periods have been posted yet.</td></tr>{% endfor %}
{% if summ %}
<tr class="sum a"><th scope="row">Daily actual teaching minutes</th>{% for d in days %}<td data-day="{{ d }}">{{ summ.teach[d] }} minutes{{ hm(summ.teach[d]) }}</td>{% endfor %}<td class="num">{{ summ.teach_w }}{{ hm(summ.teach_w) }}</td></tr>
<tr class="sum a"><th scope="row">Intervention / Remediation</th>{% for d in days %}<td data-day="{{ d }}">{{ summ.inter[d] }} minutes{{ hm(summ.inter[d]) }}</td>{% endfor %}<td class="num">{{ summ.inter_w }}{{ hm(summ.inter_w) }}</td></tr>
<tr class="sum a"><th scope="row">Ancillary / Adviser's minutes</th>{% for d in days %}<td data-day="{{ d }}">{{ summ.anc[d] }} minutes{{ hm(summ.anc[d]) }}</td>{% endfor %}<td class="num">{{ summ.anc_w }}{{ hm(summ.anc_w) }}</td></tr>
<tr class="sum b"><th scope="row">Total daily working minutes</th>{% for d in days %}<td data-day="{{ d }}">{{ summ.total[d] }} minutes{{ hm(summ.total[d]) }}</td>{% endfor %}<td class="num">{{ summ.total_w|string }} minutes{{ hm(summ.total_w) }}</td></tr>
{% endif %}
</tbody></table></div>
<div class="mobile-days">
<div class="daytabs" role="tablist">{% for d in days %}<button type="button" class="daytab" data-d="{{ d }}">{{ d[:3] }}</button>{% endfor %}</div>
{% for d in days %}<section class="dayp" data-dp="{{ d }}" data-day="{{ d }}"><h3>{{ d }}</h3>
{% if not (cells[d]|select('mapping')|list) %}<p class="mnone">No periods on this day.</p>{% endif %}
{% for r in rows %}{% set ri = loop.index0 %}{% set c = cells[d][ri] %}{% if c and c != 'skip' %}
<div class="mrow"><div class="mtime{{ ' recess' if c.e.kind == 'recess' }}">{{ r[0]|tm }} to {{ rows[ri + c.span - 1][1]|tm }}</div>{{ entry(c.e, mode, can_edit) }}{% for m in c.more %}{{ entry(m, mode, can_edit) }}{% endfor %}</div>
{% endif %}{% endfor %}
{% if summ %}<div class="msum"><div><span>Daily actual teaching</span><b>{{ summ.teach[d] }} min{% if summ.teach[d] >= 60 %} ({{ summ.teach[d]|hrs }}){% endif %}</b></div>
<div><span>Intervention / Remediation</span><b>{{ summ.inter[d] }} min{% if summ.inter[d] >= 60 %} ({{ summ.inter[d]|hrs }}){% endif %}</b></div>
<div><span>Ancillary / Adviser's</span><b>{{ summ.anc[d] }} min{% if summ.anc[d] >= 60 %} ({{ summ.anc[d]|hrs }}){% endif %}</b></div>
<div class="tot"><span>Total working minutes</span><b>{{ summ.total[d] }} min{% if summ.total[d] >= 60 %} ({{ summ.total[d]|hrs }}){% endif %}</b></div></div>{% endif %}
</section>{% endfor %}</div>{% endmacro %}

{% macro tsearch(list_mode=false, noun='teacher', hint='Search teachers&hellip;') %}
<div class="tsearch noprint" role="search"><label for="tq">Search {{ noun }}s</label>
<div class="sfield"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
<input id="tq" type="search" aria-label="Search {{ noun }}s" autocomplete="off" maxlength="60" enterkeyhint="search"{% if list_mode %} data-list="1"{% endif %}>
<a href="#" id="tqx" class="sclear" role="button" title="Clear search" aria-label="Clear search" hidden>&times;</a></div>
<p class="hint" id="tqcount" aria-live="polite"></p></div>
<script>(function(){
function init(){
var q=document.getElementById('tq'),x=document.getElementById('tqx'),c=document.getElementById('tqcount'),
 items=document.querySelectorAll('[data-find]'),none=document.getElementById('tqnone'),lm=q.hasAttribute('data-list');
function up(){var w=q.value.toLowerCase().trim().split(' ').filter(Boolean),n=0,cat=window.__cat||'';
 items.forEach(function(el){var t=el.getAttribute('data-find'),ok=w.every(function(k){return t.indexOf(k)>-1;});
  var okc=!cat||el.getAttribute('data-cat')===cat;
  var vis=lm?(w.length>0&&ok):(ok&&okc);el.hidden=!vis;if(vis)n++;});
 x.hidden=!q.value;
 c.textContent=(w.length||cat)?(n+' of '+items.length+' {{ noun }}'+(items.length===1?'':'s')+' shown'):'';
 if(none)none.hidden=!((w.length||cat)&&!n);}
window.findApply=up;
q.addEventListener('input',up);
q.addEventListener('keydown',function(e){if(e.key==='Enter'&&lm){var a=document.querySelector('[data-find]:not([hidden]) a');if(a){e.preventDefault();location.href=a.href;}}});
x.addEventListener('click',function(e){e.preventDefault();q.value='';up();q.focus();});
up();}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();</script>
{% endmacro %}

{% macro report_form(v) %}
<form method="post" action="{{ url_for('report') }}" enctype="multipart/form-data" id="r_form">{{ csrf_field() }}
<p class="hint">Tell the administrator what went wrong. You can attach up to 5 screenshots or photos of the problem.</p>
{% if not g.user %}<label for="r_tid">Teacher ID</label><input id="r_tid" name="teacher_id" value="{{ v.get('teacher_id', '') }}" maxlength="40" autocomplete="off" required>{% endif %}
<label for="r_msg">What is the problem?</label>
<textarea id="r_msg" name="message" rows="5" maxlength="2000" required>{{ v.get('message', '') }}</textarea>
<label for="r_photo">Upload screenshots (up to 5, optional)</label>
<input id="r_photo" type="file" name="photos" accept="image/*" multiple>
<p class="hint" id="r_cnt" aria-live="polite"></p>
<div class="thumbs" id="r_prevs"></div>
<p class="hint">PNG, JPG, GIF or WEBP, up to 3 MB each. Large photos are made smaller automatically.</p>
<div class="btnrow"><button type="submit" data-busy="Sending...">Send report</button></div></form>
<script>(function(){
var inp=document.getElementById('r_photo'),list=document.getElementById('r_prevs'),cnt=document.getElementById('r_cnt'),form=document.getElementById('r_form'),MAX=5,MAXB=3*1024*1024,files=[];
function sync(){if(!window.DataTransfer)return;var dt=new DataTransfer();files.forEach(function(f){dt.items.add(f);});inp.files=dt.files;}
function render(){list.innerHTML='';
 files.forEach(function(f,i){var w=document.createElement('div');w.className='thumb';
  var im=document.createElement('img');im.src=URL.createObjectURL(f);im.alt='Screenshot '+(i+1);
  var b=document.createElement('button');b.type='button';b.className='thumbx';b.setAttribute('aria-label','Remove screenshot '+(i+1));b.innerHTML='&times;';
  b.addEventListener('click',function(){files.splice(i,1);render();});
  w.appendChild(im);w.appendChild(b);list.appendChild(w);});
 cnt.textContent=files.length?files.length+' of '+MAX+' screenshots added':'';sync();}
function shrink(f,done){
 if(f.size<=1500000||f.type==='image/gif'||!HTMLCanvasElement.prototype.toBlob){done(f);return;}
 var url=URL.createObjectURL(f),img=new Image();
 img.onload=function(){var k=Math.min(1,1600/Math.max(img.width,img.height)),c=document.createElement('canvas');
  c.width=Math.round(img.width*k);c.height=Math.round(img.height*k);c.getContext('2d').drawImage(img,0,0,c.width,c.height);
  c.toBlob(function(b){done(b&&b.size<f.size?new File([b],'screenshot.jpg',{type:'image/jpeg'}):f);},'image/jpeg',0.82);};
 img.onerror=function(){done(f);};img.src=url;}
inp.addEventListener('change',function(){
 var picked=Array.prototype.slice.call(inp.files).filter(function(f){return /^image/.test(f.type);}),room=MAX-files.length;
 if(picked.length>room)alert('You can upload up to 5 screenshots only. Extra images were skipped.');
 picked=picked.slice(0,Math.max(room,0));var n=picked.length;
 if(!n){render();return;}
 picked.forEach(function(f){shrink(f,function(g){files.push(g);n--;if(n===0)render();});});});
form.addEventListener('submit',function(e){
 for(var i=0;i<files.length;i++){if(files[i].size>MAXB){e.preventDefault();alert('Screenshot '+(i+1)+' is larger than 3 MB. Remove it or choose a smaller one.');return;}}
 if(files.length>MAX){e.preventDefault();alert('You can upload up to 5 screenshots only.');}});
})();</script>
{% endmacro %}
""",

"error.html": """{% extends "base.html" %}{% from "macros.html" import back with context %}{% block title %}{{ title }}{% endblock %}
{% block content %}<div class="titlerow">{{ back(url_for('home') if g.user else url_for('login'), 'Back to my page' if g.user else 'Back to sign-in') }}<h1>{{ title }}</h1></div><div class="card"><p>{{ text }}</p></div>{% endblock %}""",

"login.html": """{% extends "base.html" %}{% block title %}Sign in{% endblock %}
{% block page %}<style>
.login .lgtabs{display:flex;border:1.5px solid #d9e0ee;border-radius:12px;background:#eef2f8;overflow:hidden;margin:0 0 1.3rem}
.login .lgtabs button{flex:1;width:auto;min-height:0;margin:0;border:0;border-radius:0;background:transparent;color:#6b7a99;font-weight:800;font-size:.82rem;letter-spacing:.05em;padding:.78rem .4rem;box-shadow:none;text-transform:uppercase}
.login .lgtabs button.on{background:#1d3f72;color:#fff}
.login .lgtabs button:not(.on):hover{background:#e3e9f4;color:#1d3f72}
.login .lghint{display:block;color:var(--muted);font-size:.72rem;font-weight:600;margin:.2rem 0 0}
@media(prefers-reduced-motion:no-preference){.login .side-in{animation:irise .8s .1s both}.login .copy{animation:ifade 1s .45s both}.login .auth-body{animation:irise .7s .25s both}.login .auth-brand{animation:ifade .8s .2s both}}
/* ---- laptop / desktop fit: the sign-in screen always fills the window ---- */
@media(min-width:801px){
.login{height:auto;min-height:100vh;min-height:100dvh;align-items:stretch}
.login .side{position:relative!important;top:auto!important;max-height:none!important;height:auto;align-self:stretch;overflow:hidden}
.login .panel{align-items:flex-start;padding:2rem 2.5rem}
.login .panel>.authform{min-height:0!important;margin:auto!important;width:100%;max-width:440px}
.login .auth-body{margin:0!important}
}
@media(min-width:801px) and (max-width:1366px){
.login .side{padding:2.5rem 2.5rem 1.5rem}
.login .brandrow .logoimg,.login .brandrow .logo{width:88px;height:88px}
.login .brandrow .brandschool{font-size:1.15rem}
.login .brandrow{margin-bottom:1.5rem}
.login .side h1{font-size:clamp(1.8rem,3vw,2.3rem)}
}
@media(min-width:801px) and (max-height:820px){
.login .panel{padding:1.2rem 2rem}
.login .auth-body{padding:1.2rem 1.6rem 1.1rem!important}
.login .lgtabs{margin-bottom:.8rem}
.login .lgtabs button{padding:.6rem .4rem}
.login .auth-body h2{font-size:1.35rem!important;padding-bottom:.5rem;margin-bottom:.6rem}
.login .auth-note{margin:0 0 .4rem;font-size:.82rem;line-height:1.45}
.login .auth-body label{margin-top:.6rem!important}
.login .auth-body input:not([type=checkbox]):not([type=radio]):not([type=hidden]){padding:.5rem .75rem!important}
.login .auth-body button.dark{margin-top:.9rem;padding:.7rem}
.login .auth-foot{margin-top:.5rem!important}
.login .brandrow .logoimg,.login .brandrow .logo{width:76px;height:76px}
.login .side{padding-top:1.8rem;padding-bottom:1.2rem}
}
@media(min-width:801px) and (max-height:640px){
.login .auth-body{padding:.9rem 1.3rem .8rem!important}
.login .auth-note{display:none}
.login .copy{display:none}
}
</style>
<div class="login">
<div class="side">
<svg class="arcs" viewBox="0 0 600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true" fill="none" stroke="#fff" stroke-opacity=".13" stroke-width="1.5"><circle cx="780" cy="1040" r="420"/><circle cx="780" cy="1040" r="560"/><circle cx="780" cy="1040" r="700"/><circle cx="780" cy="1040" r="840"/><circle cx="780" cy="1040" r="980"/><circle cx="780" cy="1040" r="1120"/></svg>
<div class="side-in">
<div class="brandrow">{% if has_logo %}<img class="logoimg" src="{{ logo_url }}" alt="{{ cfg.school_name }} logo">{% else %}<svg class="logo" viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="12" fill="#fff"/><path d="M24 12 7 20l17 8 17-8-17-8z" fill="#2d32c8"/><path d="M14 25v7c0 2 4.5 5 10 5s10-3 10-5v-7l-10 4.6L14 25z" fill="#2d32c8" opacity=".85"/></svg>{% endif %}
<div class="brandschool">San Jose Litex<br>Senior High School<small>School ID: 342566</small></div></div>
<h1>{{ app_name }}</h1>
<p>See your Teacher's Program and class schedules anytime, on your phone or computer. Schedules are posted and kept up to date by the school administrator.</p>
</div>
<div class="copy">&copy; 2026 San Jose-Litex Senior High School. All rights reserved.</div>
</div>
<div class="panel">
<a class="helpfab" href="{{ url_for('help_center') }}" title="Help Center" aria-label="Help Center"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 13v-1a8 8 0 0 1 16 0v1"/><rect x="2" y="13" width="5" height="7" rx="2.5"/><rect x="17" y="13" width="5" height="7" rx="2.5"/><path d="M20 20a4 4 0 0 1-4 3h-2"/></svg><span class="helpfab-q">?</span></a>
<form class="authform" method="post" id="lf">{{ csrf_field() }}
<input type="hidden" name="utype" id="utype" value="{{ sel if sel in ('TEACHER', 'ADMIN') else 'TEACHER' }}">
<div class="auth-body">
<div class="lgtabs" role="tablist" aria-label="User type"><button type="button" role="tab" data-t="TEACHER">Teacher</button><button type="button" role="tab" data-t="ADMIN">Admin</button></div>
<h2>Log in to manage your classes</h2>
<p class="auth-note" data-only="TEACHER">Don't have an account? <a href="{{ url_for('signup') }}">Request an account</a> now. Wait for the administrator to approve it.</p>
{% for cat, m in get_flashed_messages(with_categories=true) %}<div class="msg {{ cat }}" role="alert">{{ m }}</div>{% endfor %}
<label for="username">Username</label>
<input id="username" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" value="{{ request.form.get('username', '') }}" required maxlength="40">
<div data-pane="TEACHER">
<label for="teacher_num">Employee ID</label>
<input id="teacher_num" name="teacher_num" type="text" inputmode="numeric" autocomplete="off" maxlength="12" value="{{ request.form.get('teacher_num', '') }}">
</div>
<label for="password">Password</label>
<input id="password" type="password" name="password" autocomplete="current-password" required>
<p class="auth-foot" data-only="TEACHER" style="margin-top:.7rem"><a href="{{ url_for('forgot_password') }}">Forgot password?</a></p>
<button class="dark" type="submit" data-busy="Signing in...">Sign In</button>
<p class="auth-foot"><a href="#" class="viewtoggle" hidden></a></p>
</div>
</form>
</div>
</div>
<script>(function(){var f=document.getElementById('lf'),u=document.getElementById('utype');
function set(v){u.value=v;
[].forEach.call(f.querySelectorAll('.lgtabs button'),function(b){var on=b.getAttribute('data-t')===v;b.classList.toggle('on',on);b.setAttribute('aria-selected',on?'true':'false');});
[].forEach.call(f.querySelectorAll('[data-pane]'),function(p){var on=p.getAttribute('data-pane')===v;p.hidden=!on;[].forEach.call(p.querySelectorAll('input'),function(i){i.disabled=!on;i.required=on;});});
[].forEach.call(f.querySelectorAll('[data-only]'),function(p){p.hidden=p.getAttribute('data-only')!==v;});}
[].forEach.call(f.querySelectorAll('.lgtabs button'),function(b){b.addEventListener('click',function(){set(b.getAttribute('data-t'));});});
set(u.value);})();</script>{% endblock %}""",

"profile.html": """{% extends "base.html" %}{% from "macros.html" import teacher_doc, back, tsearch, durselect with context %}
{% block title %}Teacher's Program{% endblock %}
{% block content %}
<div class="head noprint"><div class="titlerow">{% if g.user.role == 'admin' %}{{ back(url_for('teachers'), 'Back to teachers') }}{% endif %}<h1>{{ "My Teacher's Program" if g.user.role == 'teacher' else t.full_name }}</h1></div>
<button type="button" class="plain" onclick="window.print()">Print</button></div>
{% if g.user.role == 'admin' and pick|length > 1 %}<div class="card noprint">{{ tsearch(true) }}
<ul class="tresults">{% for p in pick %}{% if p.id != t.id %}<li data-find="{{ (p.full_name ~ ' ' ~ p.teacher_id)|lower }}" hidden><a href="{{ url_for('teacher_view', tid=p.id) }}"><span>{{ p.full_name }}</span><small>{{ p.teacher_id }}</small></a></li>{% endif %}{% endfor %}</ul></div>{% endif %}
{% if g.user.role == 'admin' %}
<details class="card noprint" id="minedit"><summary>Edit minutes (teaching, intervention, ancillary and total)</summary>
<form method="post" action="{{ url_for('teacher_minutes', tid=t.id) }}" style="margin-top:.8rem">{{ csrf_field() }}
<p class="hint">Choose the time for each day from the lists (for example 1 hr 30 min). The total daily working time adds up by itself.</p>
<div class="scroll"><table class="minedit"><thead><tr><th></th>{% for day in days %}<th>{{ day }}</th>{% endfor %}</tr></thead><tbody>
<tr><th scope="row">Daily actual teaching minutes</th>{% for day in days %}<td>{{ durselect('teach_' ~ day, d.summ.teach[day], 'Teaching time ' ~ day, 720, 'teach', day, d.summ.auto.teach[day]) }}</td>{% endfor %}</tr>
<tr><th scope="row">Intervention / Remediation</th>{% for day in days %}<td>{{ durselect('inter_' ~ day, d.summ.inter[day], 'Intervention time ' ~ day, 720, 'inter', day, d.summ.auto.inter) }}</td>{% endfor %}</tr>
<tr><th scope="row">Ancillary / Adviser's minutes</th>{% for day in days %}<td>{{ durselect('anc_' ~ day, d.summ.anc[day], 'Ancillary time ' ~ day, 720, 'anc', day, d.summ.auto.anc) }}</td>{% endfor %}</tr>
<tr class="tot"><th scope="row">Total daily working minutes</th>{% for day in days %}<td data-total="{{ day }}">0</td>{% endfor %}</tr>
</tbody></table></div>
<div class="btnrow"><button type="submit" name="action" value="save">Save minutes</button>
<button type="submit" name="action" value="reset" class="plain" formnovalidate onclick="return confirm('Go back to the automatic minutes?')">Back to automatic</button></div></form></details>
<script>(function(){var ins=document.querySelectorAll('#minedit [data-k]');
function conv(h,m,a){h=+h;m=+(m||0);a=(a||'').toUpperCase();if(a)h=a==='AM'?h%12:(a==='PM'?h%12+12:12);return h*60+m;}
function val(t,auto){t=(t||'').trim();if(!t)return +auto||0;if(/^\\d+$/.test(t))return +t;
 var f=[],re=/(\\d{1,2})(?::(\\d{2}))?\\s*(AM|PM|NN)\\b/gi,m;while((m=re.exec(t)))f.push(m);
 if(f.length>=2){var d=conv(f[1][1],f[1][2],f[1][3])-conv(f[0][1],f[0][2],f[0][3]);return d>0?d:0;}
 m=t.match(/^(\\d{1,2}):(\\d{2})\\s*(?:-|to)\\s*(\\d{1,2}):(\\d{2})$/);
 if(m){var e=conv(m[3],m[4])-conv(m[1],m[2]);return e>0?e:0;}return 0;}
function up(){document.querySelectorAll('#minedit [data-total]').forEach(function(c){var day=c.getAttribute('data-total'),t=0;
 ins.forEach(function(i){if(i.getAttribute('data-d')===day)t+=val(i.value,i.getAttribute('data-auto'));});
 var h=Math.floor(t/60),r=t%60;c.textContent=t+' min'+(t>=60?' ('+h+' hr'+(h!==1?'s':'')+(r?' '+r+' min':'')+')':'');});}
ins.forEach(function(i){i.addEventListener('input',up)});up();})();</script>
{% endif %}
{{ teacher_doc(d) }}
{% if g.user.role == 'teacher' %}<p class="noprint" style="color:var(--muted)">Only you and the administrator can see this program. Contact the administrator to request a change.</p>{% endif %}
{% endblock %}""",

"program.html": """{% extends "base.html" %}{% from "macros.html" import class_doc, adviser_picker with context %}
{% block title %}Class Programs{% endblock %}
{% block content %}{% if g.user.role == 'admin' %}{{ subnav('schedule_prog') }}{% endif %}
<div class="head noprint"><h1>Class Programs</h1><div class="row-acts">{% if g.user.role == 'admin' and total %}<a class="btn plain" href="{{ url_for('print_classes') }}">Choose programs to print</a>{% endif %}{% if g.user.role == 'admin' and cur and secs %}{% if editing %}<a class="btn" href="{{ url_for('program', section=cur.id, grade=grade) }}">Done editing</a>{% else %}<a class="btn plain" href="{{ url_for('program', section=cur.id, edit=1, grade=grade) }}">Edit schedule</a>{% endif %}{% endif %}{% if cur %}<button type="button" class="plain" onclick="window.print()">{{ 'Print all shown' if docs else 'Print this program' }}</button>{% endif %}</div></div>
{% if not total %}<div class="card">No sections are available yet.{% if g.user.role == 'admin' %} Register the sections in Quick Input first.{% endif %}</div>
{% else %}
<form class="pick noprint" id="searchbar" method="get" action="{{ url_for('program') }}" role="search" style="scroll-margin-top:.6rem">
<div class="searchbox"><label for="q">Search sections</label>
<div class="sfield"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
<input id="q" type="search" name="q" value="{{ q }}" aria-label="Search sections" autocomplete="off" enterkeyhint="search" maxlength="60">
{% if q %}<a class="sclear" href="{{ url_for('program') }}" title="Clear search" aria-label="Clear search">&times;</a>{% endif %}</div></div>
<button type="submit">Search</button>
{% if grades|length > 1 %}<div><label for="grade">Grade level</label>
<select id="grade" name="grade" onchange="var s=this.form.elements['section'];if(s)s.disabled=true;this.form.submit()"><option value="">All grades</option>{% for gr in grades %}<option value="{{ gr }}" {{ 'selected' if grade == gr }}>{{ gr }}</option>{% endfor %}</select></div>{% endif %}
{% if ptracks|length > 1 or ptrack %}<div><label for="ptrack">Track</label>
<select id="ptrack" name="track" onchange="var s=this.form.elements['section'];if(s)s.disabled=true;this.form.submit()"><option value="">All tracks</option>{% for t in ptracks %}<option value="{{ t }}" {{ 'selected' if ptrack == t }}>{{ t }}</option>{% endfor %}</select></div>{% endif %}
{% if secs %}<div><label for="section">Section</label>
{% if editing %}<input type="hidden" name="edit" value="1">{% endif %}<select id="section" name="section" {% if docs %}onchange="var t=document.getElementById('sec-'+this.value);if(t)t.scrollIntoView({behavior:'smooth',block:'start'})"{% else %}onchange="this.form.submit()"{% endif %}>
{% for s in secs %}<option value="{{ s.id }}" {{ 'selected' if s.id == cur.id }}>{{ s.name }}{{ ' (My Advisory)' if s.is_adv }}</option>{% endfor %}</select></div>{% endif %}
</form>
{% if q %}<p class="hint noprint">{{ secs|length }} of {{ gtotal }} section{{ '' if gtotal == 1 else 's' }} match &ldquo;{{ q }}&rdquo;.</p>{% endif %}
{% if not secs %}<div class="card">No section matches your search. <a href="{{ url_for('program') }}">Show all sections</a></div>
{% else %}
{% if editing %}
<p class="editbanner noprint"><b>Edit mode is on.</b> Add a period below, or use Edit / Remove on a period. Press <b>Done editing</b> when finished.</p>
<div class="card"><h3>Add to this class program</h3>
<form method="post" action="{{ url_for('entry_add') }}" id="addform">{{ csrf_field() }}<input type="hidden" name="section_id" value="{{ cur.id }}">
<div class="formgrid">
<div><label for="kind">Type</label><select id="kind" name="kind">{% for k, v in kinds.items() %}<option value="{{ k }}">{{ v }}</option>{% endfor %}</select></div>
<div><label for="start">Start time</label><input id="start" type="time" name="start" required></div>
<div><label for="end">End time</label><input id="end" type="time" name="end" required></div>
<div><label for="subject">Subject</label><input id="subject" name="subject"></div>
<div><label for="code">Subject code</label><input id="code" name="code" maxlength="12"></div>
<div><label for="adv_q">Teacher</label>{{ adviser_picker(teachers, none, 'teacher_id', 'Unassigned') }}</div>
<div class="wide"><fieldset><legend>Days</legend>{% for d in days %}<label class="chk"><input type="checkbox" name="day" value="{{ d }}"> {{ d }}</label>{% endfor %}
<button type="button" class="plain small" onclick="document.querySelectorAll('#addform input[name=day]').forEach(function(x){x.checked=true});document.getElementById('addform').dispatchEvent(new Event('change'))">Select Monday to Friday</button>
<p class="hint">Tick every day that has this period. Recess, homeroom and intervention periods do not use a teacher.</p></fieldset></div>
<div class="wide"><p class="hint" id="durout" aria-live="polite" style="font-weight:600;color:var(--navy)"></p></div>
<div><button type="submit">Save period</button></div></div></form></div>
<script>(function(){var f=document.getElementById('addform');if(!f)return;
var s=f.querySelector('[name=start]'),e=f.querySelector('[name=end]'),o=document.getElementById('durout');
function m(v){var p=(v||'').split(':');return p.length<2?NaN:(+p[0])*60+(+p[1]);}
function h(n){var a=Math.floor(n/60),b=n%60,t=[];if(a)t.push(a+(a===1?' hr':' hrs'));if(b)t.push(b+' min');return t.join(' ')||'0 min';}
function upd(){var d=m(e.value)-m(s.value),k=f.querySelectorAll('input[name=day]:checked').length;
if(isNaN(d)){o.textContent='';return;}
if(d<=0){o.textContent='End time must be later than start time.';return;}
var t='Time computed: '+h(d)+' ('+d+' minutes)';
if(k>1)t+=' x '+k+' days = '+h(d*k)+' per week';
o.textContent=t;}
f.addEventListener('input',upd);f.addEventListener('change',upd);upd();})();</script>
{% endif %}
{% if docs %}<p class="hint noprint">Showing {{ docs|length }} class program{{ '' if docs|length == 1 else 's' }}{% if grade %} for Grade {{ grade }}{% endif %}. Scroll down to see the others, or pick a section above to jump to it.</p>
{% for x in docs %}<section class="progitem" id="sec-{{ x.cur.id }}">{% if x.cur.is_adv %}<p class="advtag noprint">My Advisory</p>{% endif %}{{ class_doc(x, false) }}</section>{% endfor %}
{% else %}{% if cur.is_adv %}<p class="advtag noprint">My Advisory</p>{% endif %}{{ class_doc(d, editing) }}{% endif %}
{% endif %}{% endif %}
<button type="button" class="fabtop noprint" id="fabtop" title="Go back up to the search bar" aria-label="Go back up to the search bar" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg></button>
<script>(function(){var b=document.getElementById('fabtop'),bar=document.getElementById('searchbar');if(!b||!bar)return;
document.body.appendChild(b);
function chk(){b.hidden=(window.pageYOffset||document.documentElement.scrollTop)<250;}
window.addEventListener('scroll',chk,{passive:true});chk();
b.addEventListener('click',function(){bar.scrollIntoView({behavior:'smooth',block:'start'});var q=document.getElementById('q');if(q)setTimeout(function(){try{q.focus({preventScroll:true});}catch(e){}},500);});
})();</script>{% endblock %}""",

"printall.html": """{% extends "base.html" %}{% from "macros.html" import class_doc, teacher_doc, back with context %}
{% block title %}{{ title }}{% endblock %}
{% block content %}
<div class="head noprint"><div class="titlerow">{{ back(back_url, 'Back') }}<h1>{{ title }}</h1></div>{% if docs %}<button type="button" onclick="window.print()">Print ({{ docs|length }} page{{ '' if docs|length == 1 else 's' }})</button>{% endif %}</div>
<p class="hint noprint">Every selected program prints on its own page, one page each. <a href="{{ back_url }}">Choose different programs</a></p>
{% for d in docs %}<div class="pdoc">{% if kind == 'class' %}{{ class_doc(d, false) }}{% else %}{{ teacher_doc(d) }}{% endif %}</div>
{% else %}<div class="card">Nothing to print yet.</div>{% endfor %}
{% endblock %}""",

"printpick.html": """{% extends "base.html" %}{% from "macros.html" import back, tsearch with context %}
{% block title %}{{ title }}{% endblock %}
{% block content %}
<div class="head noprint"><div class="titlerow">{{ back(back_url, 'Back') }}<h1>{{ title }}</h1></div></div>{{ subnav('reports') }}
<form method="get" class="card noprint">
{% if searchable %}{{ tsearch(false, noun or 'teacher', hint or 'Search teachers&hellip;') }}{% endif %}
<p class="hint">Tick the programs you want. Only those will be shown for printing.</p>
<p><button type="button" class="plain small" id="selall">Select all</button> <button type="button" class="plain small" id="selnone">Clear</button> <span class="hint" id="selcount"></span></p>
<div class="picklist">{% for pid, label, sub, find in items %}<label class="chk" data-find="{{ find }}"><input type="checkbox" name="id" value="{{ pid }}"> {{ label }}{% if sub %} <span class="hint">({{ sub }})</span>{% endif %}</label>
{% else %}<p>Nothing to print yet.</p>{% endfor %}</div>
<p style="margin-top:1rem"><button type="submit" id="goprint" disabled>Show selected to print</button></p></form>
<script>(function(){var b=document.querySelectorAll('.picklist input'),g=document.getElementById('goprint'),c=document.getElementById('selcount');
function up(){var n=0;b.forEach(function(x){if(x.checked)n++});g.disabled=!n;c.textContent=n?n+' selected':'';}
b.forEach(function(x){x.addEventListener('change',up)});
document.getElementById('selall').onclick=function(){b.forEach(function(x){if(!x.parentNode.hidden)x.checked=true});up()};
document.getElementById('selnone').onclick=function(){b.forEach(function(x){x.checked=false});up()};up();})();</script>
{% endblock %}""",

"entry_edit.html": """{% extends "base.html" %}{% from "macros.html" import back, adviser_picker with context %}{% block title %}Edit period{% endblock %}
{% block content %}
<div class="titlerow">{{ back(url_for('program', section=sec.id, edit=1), 'Back to class program') }}<h1>Edit period</h1></div>
<p style="color:var(--muted)">{{ sec.name }}</p>
<div class="card"><form method="post" id="editform">{{ csrf_field() }}<div class="formgrid">
<div><label for="kind">Type</label><select id="kind" name="kind">{% for k, v in kinds.items() %}<option value="{{ k }}" {{ 'selected' if k == (e.kind or 'class') }}>{{ v }}</option>{% endfor %}</select></div>
<div><label for="day">Day</label><select id="day" name="day">{% for d in days %}<option {{ 'selected' if d == e.day }}>{{ d }}</option>{% endfor %}</select></div>
<div><label for="start">Start time</label><input id="start" type="time" name="start" value="{{ e.start }}" required></div>
<div><label for="end">End time</label><input id="end" type="time" name="end" value="{{ e.end }}" required></div>
<div><label for="subject">Subject</label><input id="subject" name="subject" value="{{ e.subject }}"></div>
<div><label for="code">Subject code</label><input id="code" name="code" value="{{ e.code or '' }}" maxlength="12"></div>
<div><label for="adv_q">Teacher</label>{{ adviser_picker(teachers, e.teacher_id, 'teacher_id', 'Unassigned') }}</div>
<div class="wide"><p class="hint" id="durout" aria-live="polite" style="font-weight:600;color:var(--navy)"></p></div>
</div>
<div class="btnrow"><button type="submit">Save changes</button>
<a class="btn plain" href="{{ url_for('program', section=sec.id) }}">Cancel</a></div></form></div>
<script>(function(){var f=document.getElementById('editform'),s=document.getElementById('start'),e=document.getElementById('end'),o=document.getElementById('durout');
function m(v){var p=(v||'').split(':');return p.length<2?NaN:(+p[0])*60+(+p[1]);}
function h(n){var a=Math.floor(n/60),b=n%60,t=[];if(a)t.push(a+(a===1?' hr':' hrs'));if(b)t.push(b+' min');return t.join(' ')||'0 min';}
function upd(){var d=m(e.value)-m(s.value);if(isNaN(d)){o.textContent='';return;}
o.textContent=d<=0?'End time must be later than start time.':'Time computed: '+h(d)+' ('+d+' minutes)';}
f.addEventListener('input',upd);f.addEventListener('change',upd);upd();})();</script>
{% endblock %}""",

"account.html": """{% extends "base.html" %}{% from "macros.html" import back with context %}{% block title %}Profile{% endblock %}
{% block content %}<div class="titlerow">{{ back(url_for('home'), 'Back') }}<h1>Profile</h1></div>
<div class="card"><div class="head"><h2 style="margin:0">My profile</h2>
</div>
<div class="scroll"><table class="list">
{% if g.user.role == 'teacher' %}
<tr><th scope="row">Placeholder name</th><td>{% if tlabels.get(g.user.id) %}Teacher-{{ tlabels.get(g.user.id) }}{% else %}-{% endif %}</td></tr>
<tr><th scope="row">Name</th><td>{{ g.user.full_name }}</td></tr>
<tr><th scope="row">Teacher ID / Username</th><td>{{ g.user.teacher_id }} / {{ g.user.username }}</td></tr>
<tr><th scope="row">Grade level handled</th><td>{{ catname.get(g.user.category, '-') }}</td></tr>
<tr><th scope="row">Gmail</th><td>{{ mask_email(g.user.email) if g.user.email else 'Not added yet (add it in Settings)' }}</td></tr>
<tr><th scope="row">Subjects</th><td>{{ (subjects_of(g.user)|join('; ')) or 'No subjects assigned' }}</td></tr>
<tr><th scope="row">Specialization</th><td>{{ g.user.specialization or '-' }}</td></tr>
<tr><th scope="row">Teaching load</th><td>{{ summ.loads }}</td></tr>
<tr><th scope="row">Ancillary</th><td>{{ ancillary }}</td></tr>
<tr><th scope="row">Official time</th><td>{{ g.user.official_time or '-' }}</td></tr>
{% else %}
<tr><th scope="row">Name</th><td>{{ g.user.full_name }}</td></tr>
<tr><th scope="row">Username</th><td>{{ g.user.username }}</td></tr>
<tr><th scope="row">Role</th><td>Administrator</td></tr>
{% endif %}</table></div>
{% if g.user.role == 'teacher' %}<p class="hint">Your name and username can be changed in Account Settings in the menu. The rest is set by the administrator - contact them to request a change.</p>{% endif %}</div>{% endblock %}""",

"account_settings.html": """{% extends "base.html" %}{% from "macros.html" import back with context %}{% block title %}Settings{% endblock %}
{% block content %}<div class="titlerow">{{ back(url_for('account'), 'Back') }}<h1>Settings</h1><a class="helpfab inline" href="{{ url_for('help_center') }}" title="Help Center" aria-label="Help Center"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 13v-1a8 8 0 0 1 16 0v1"/><rect x="2" y="13" width="5" height="7" rx="2.5"/><rect x="17" y="13" width="5" height="7" rx="2.5"/><path d="M20 20a4 4 0 0 1-4 3h-2"/></svg><span class="helpfab-q">?</span></a></div>
<div class="cardrow">
<div class="card narrow"><h2>Edit profile</h2><form method="post">{{ csrf_field() }}<input type="hidden" name="action" value="profile">
<label for="full_name">Name</label><input id="full_name" name="full_name" value="{{ g.user.full_name }}" required maxlength="200">
<label for="username">Username</label><input id="username" name="username" value="{{ g.user.username }}" required maxlength="40" autocomplete="username">
<p style="margin-top:1.2rem"><button type="submit">Save profile</button></p></form></div>
{% if g.user.role == 'teacher' %}<div class="card narrow"><h2>Gmail for verification codes</h2><p class="hint">{% if g.user.email %}Saved: <b>{{ mask_email(g.user.email) }}</b>. You can change it below.{% else %}No Gmail saved yet. Add one so you can reset your own password with a code.{% endif %}</p><form method="post">{{ csrf_field() }}<input type="hidden" name="action" value="email">
<label for="email">Gmail address</label><input id="email" name="email" type="email" required maxlength="80" autocomplete="email">
<label for="ecur">Current password</label><input id="ecur" type="password" name="current" autocomplete="current-password" required>
<p style="margin-top:1.2rem"><button type="submit">Send verification code</button></p></form></div>{% endif %}
<div class="card narrow"><h2>Change password</h2><form method="post">{{ csrf_field() }}
<label for="current">Current password</label><input id="current" type="password" name="current" autocomplete="current-password" required>
<label for="new">New password (at least 6 characters)</label><input id="new" type="password" name="new" minlength="6" autocomplete="new-password" required>
<label for="confirm">Confirm new password</label><input id="confirm" type="password" name="confirm" minlength="6" autocomplete="new-password" required>
<p style="margin-top:1.2rem"><button type="submit">Change password</button></p></form></div>

</div>{% endblock %}""",

"signup.html": """{% extends "base.html" %}{% block title %}Request an account{% endblock %}
{% block page %}<style>
.login .lghint{display:block;color:var(--muted);font-size:.72rem;font-weight:600;margin:.2rem 0 0}
@media(prefers-reduced-motion:no-preference){.login .side-in{animation:irise .8s .1s both}.login .copy{animation:ifade 1s .45s both}.login .auth-body{animation:irise .7s .25s both}.login .auth-brand{animation:ifade .8s .2s both}}
</style>
<div class="login">
<div class="side">
<svg class="arcs" viewBox="0 0 600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true" fill="none" stroke="#fff" stroke-opacity=".13" stroke-width="1.5"><circle cx="780" cy="1040" r="420"/><circle cx="780" cy="1040" r="560"/><circle cx="780" cy="1040" r="700"/><circle cx="780" cy="1040" r="840"/><circle cx="780" cy="1040" r="980"/><circle cx="780" cy="1040" r="1120"/></svg>
<div class="side-in">
<div class="brandrow">{% if has_logo %}<img class="logoimg" src="{{ logo_url }}" alt="{{ cfg.school_name }} logo">{% else %}<svg class="logo" viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="12" fill="#fff"/><path d="M24 12 7 20l17 8 17-8-17-8z" fill="#2d32c8"/><path d="M14 25v7c0 2 4.5 5 10 5s10-3 10-5v-7l-10 4.6L14 25z" fill="#2d32c8" opacity=".85"/></svg>{% endif %}
<div class="brandschool">San Jose Litex<br>Senior High School<small>School ID: 342566</small></div></div>
<h1>Join us</h1>
<p>Send a request for a teacher account. The administrator will review it, add you to the list of teachers and set up your schedule details.</p>
</div>
<div class="copy">&copy; 2026 San Jose-Litex Senior High School. All rights reserved.</div>
</div>
<div class="panel">
<form class="authform" method="post">{{ csrf_field() }}
<div class="auth-brand">{{ app_name|upper }}</div>
<div class="auth-body">
<h2>Request an account</h2>
<p class="auth-note">Already have an account? <a href="{{ url_for('login') }}">Sign in</a>.</p>
{% for cat, m in get_flashed_messages(with_categories=true) %}<div class="msg {{ cat }}" role="alert">{{ m }}</div>{% endfor %}
<label for="full_name">Full name</label>
<input id="full_name" name="full_name" autocomplete="name" value="{{ v.get('full_name','') }}" required maxlength="200">
<label for="username">Username</label>
<input id="username" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" value="{{ v.get('username','') }}" required maxlength="30">
<label for="teacher_num">Employee ID</label>
<input id="teacher_num" name="teacher_num" type="text" inputmode="numeric" value="{{ v.get('teacher_num','') }}" required autocomplete="off" maxlength="12">
<label for="email">Email</label>
<input id="email" name="email" type="email" value="{{ v.get('email','') }}" required maxlength="80" autocomplete="email">
<label for="password">Password</label>
<input id="password" type="password" name="password" minlength="6" required autocomplete="new-password">
<label for="confirm">Confirm password</label>
<input id="confirm" type="password" name="confirm" minlength="6" required autocomplete="new-password">
<p id="pwmatch" class="lghint" aria-live="polite" style="min-height:1.1rem"></p>
<button class="dark" type="submit" data-busy="Sending code...">Send request</button>
<p class="auth-foot"><a href="#" class="viewtoggle" hidden></a></p>
</div>
</form>
</div>
</div>
<script>(function(){var a=document.getElementById('password'),c=document.getElementById('confirm'),m=document.getElementById('pwmatch');
function chk(){if(!c.value){m.textContent='';return;}var ok=a.value===c.value;m.textContent=ok?'Passwords match.':'Passwords do not match yet.';m.style.color=ok?'var(--ok)':'var(--bad)';}
a.addEventListener('input',chk);c.addEventListener('input',chk);})();</script>{% endblock %}""",

"reset_new.html": r"""{% extends "auth_base.html" %}{% from "af_macros.html" import steps, note with context %}{% block title %}New password{% endblock %}
{% block sidetitle %}Reset password{% endblock %}
{% block sidetext %}Your code was verified. Choose a new password to finish recovering your account.{% endblock %}
{% block afico %}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="15" r="4"/><path d="M10.8 12.2L20 3M16 7l3 3M14 9l2 2"/></svg>{% endblock %}
{% block afbody %}{{ steps(3) }}
<h2 class="af-title">Create a new password</h2>
<p class="af-sub">Your code was correct. Choose a new password and confirm it.</p>
{% for cat, m in get_flashed_messages(with_categories=true) %}<div class="msg {{ cat }}" role="alert">{{ m }}</div>{% endfor %}
<form method="post" id="npform">{{ csrf_field() }}
<label for="new">New password</label>
<input id="new" type="password" name="new" minlength="6" maxlength="128" required autocomplete="new-password" autofocus>
<div class="af-meter" id="meter" data-s="0" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
<p class="af-hint" id="strength" aria-live="polite">At least 6 characters. A longer mix of letters and numbers is stronger.</p>
<label for="confirm">Confirm new password</label>
<input id="confirm" type="password" name="confirm" minlength="6" maxlength="128" required autocomplete="new-password">
<p class="af-hint" id="match" aria-live="polite"></p>
<button class="af-btn" type="submit">Change password</button>
</form>{% endblock %}
{% block afscript %}<script>(function(){
var a=document.getElementById('new'),b=document.getElementById('confirm'),m=document.getElementById('meter'),s=document.getElementById('strength'),t=document.getElementById('match');
var names=['','Weak','Fair','Good','Strong'];
function score(v){if(v.length<6)return v.length?1:0;var n=1;if(v.length>=10)n++;if(/[a-z]/.test(v)&&/[A-Z]/.test(v))n++;if(/[0-9]/.test(v)&&/[^A-Za-z0-9]|[A-Za-z]/.test(v)&&v.length>=8)n++;return Math.min(n,4);}
function up(){var v=a.value,n=score(v);m.setAttribute('data-s',n);
 if(!v){s.className='af-hint';s.textContent='At least 6 characters. A longer mix of letters and numbers is stronger.';}
 else if(v.length<6){s.className='af-hint bad';s.textContent='Too short: use at least 6 characters.';}
 else{s.className='af-hint '+(n>=3?'good':'');s.textContent='Strength: '+names[n];}
 if(b.value){var ok=a.value===b.value;t.className='af-hint '+(ok?'good':'bad');t.textContent=ok?'Passwords match.':'Passwords do not match yet.';}else{t.className='af-hint';t.textContent='';}}
a.addEventListener('input',up);b.addEventListener('input',up);
document.getElementById('npform').addEventListener('submit',function(e){if(a.value!==b.value){e.preventDefault();t.className='af-hint bad';t.textContent='Passwords do not match.';b.focus();}});
})();</script>{% endblock %}
""",

"reset_done.html": r"""{% extends "auth_base.html" %}{% from "af_macros.html" import steps with context %}{% block title %}Password changed{% endblock %}
{% block sidetitle %}All set{% endblock %}
{% block sidetext %}Your password has been updated. Sign in with your new password to continue to your schedule.{% endblock %}
{% block afico %}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>{% endblock %}
{% block afbody %}{{ steps(4) }}
<h2 class="af-title">Password changed</h2>
<p class="af-sub">Your password was updated successfully. Use your new password the next time you sign in.</p>
<a class="af-btn" href="{{ url_for('login') }}">Back to sign in</a>{% endblock %}
""",

"help.html": """{% extends "base.html" %}{% from "macros.html" import report_form with context %}{% block title %}Help{% endblock %}
{% block content %}<div class="titlerow"><h1>Help Center</h1>{% if not g.user %}<a class="btn plain" href="{{ url_for('login') }}">Back to sign in</a>{% endif %}</div>
<p style="color:var(--muted)">A quick guide on how to use the {{ app_name }}.</p>

<div class="card"><h2>Signing in</h2>
<p>Pick <strong>Teacher</strong> or <strong>Admin</strong> on the sign-in page. Teachers type their full name, Employee ID and password; administrators use their username and password. New teachers choose <strong>New here? Create Account</strong>, enter their Gmail and the 6-digit code sent to it, then wait for the administrator to approve the account. Forgot your password? Choose <strong>Forgot password?</strong>, enter your Employee ID and the code sent to your Gmail (use <strong>Resend</strong> if it did not arrive).</p></div>

<div class="card"><h2>For teachers</h2>
<ul>
<li><strong>My Teacher's Program</strong> shows your own weekly class schedule, computed from the periods the administrator assigned you.</li>
<li><strong>Class Programs</strong> shows the class program of every section you are assigned to teach or advise.</li>
<li>Tap a room number on a class program to see which building and floor it's in.</li>
<li><strong>Profile</strong> (the person icon beside the bell) shows your account details. <strong>Settings</strong> is where you edit your name and username or change your password.</li>
<li>The bell icon shows notifications, such as new assignments or a change to your role.</li>
</ul></div>

<div class="card"><h2>For administrators</h2>
<ul>
<li><strong>Teacher Management</strong> holds teacher accounts, specialization and official time; <strong>Teacher Loading</strong> assigns who teaches each subject.</li>
<li><strong>Section Management</strong> creates sections with their track, cluster, shift, room and adviser; the <strong>Dashboard</strong> shows what still needs doing.</li>
<li><strong>Class Programs</strong> lets you add, edit or remove periods for any section. A teacher assigned in both Grade 11 and Grade 12 automatically becomes a MID teacher, and goes back to G11 or G12 when only one grade level is left.</li>
<li><strong>Requests</strong> lists new account requests waiting for your action, and problem reports from teachers.</li>
<li><strong>Document details</strong> sets the school name and logo used across the system and on printed programs.</li>
</ul></div>

<div class="card"><h2>Printing</h2>
<p>Open a class program or teacher's program and use the on-screen Print button, or your browser's own print option.</p></div>

{% if not (g.user and g.user.role == 'admin') %}<div class="card narrow" id="report"><h2>Report a problem</h2>{{ report_form({}) }}</div>{% endif %}{% endblock %}""",

"af_macros.html": r"""{% macro steps(n) %}<ol class="af-steps" aria-label="Progress">{% for label in ['Identify', 'Verify', 'New password'] %}<li class="{{ 'done' if loop.index < n else ('on' if loop.index == n else '') }}"{% if loop.index == n %} aria-current="step"{% endif %}><span>{% if loop.index < n %}&#10003;{% else %}{{ loop.index }}{% endif %}</span>{{ label }}</li>{% endfor %}</ol>{% endmacro %}
{% macro note(text) %}<div class="af-note"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg><span>{{ text }}</span></div>{% endmacro %}
""",

"auth_base.html": r"""{% extends "base.html" %}
{% block page %}<div class="login af">
<div class="side">
<svg class="arcs" viewBox="0 0 600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true" fill="none" stroke="#fff" stroke-opacity=".13" stroke-width="1.5"><circle cx="780" cy="1040" r="420"/><circle cx="780" cy="1040" r="560"/><circle cx="780" cy="1040" r="700"/><circle cx="780" cy="1040" r="840"/><circle cx="780" cy="1040" r="980"/><circle cx="780" cy="1040" r="1120"/></svg>
<div class="side-in">
<div class="brandrow">{% if has_logo %}<img class="logoimg" src="{{ logo_url }}" alt="{{ cfg.school_name }} logo">{% else %}<svg class="logo" viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="12" fill="#fff"/><path d="M24 12 7 20l17 8 17-8-17-8z" fill="#2d32c8"/><path d="M14 25v7c0 2 4.5 5 10 5s10-3 10-5v-7l-10 4.6L14 25z" fill="#2d32c8" opacity=".85"/></svg>{% endif %}
<div class="brandschool">San Jose Litex<br>Senior High School<small>School ID: 342566</small></div></div>
<h1>{% block sidetitle %}{{ app_name }}{% endblock %}</h1>
<p>{% block sidetext %}{% endblock %}</p>
</div>
<div class="copy">&copy; 2026 San Jose-Litex Senior High School. All rights reserved.</div>
</div>
<div class="panel"><div class="af-wrap"><div class="af-card">
<div class="af-ico" aria-hidden="true">{% block afico %}{% endblock %}</div>
{% block afbody %}{% endblock %}
</div></div></div>
</div>
{% block afscript %}{% endblock %}{% endblock %}
""",

"verify_code.html": r"""{% extends "auth_base.html" %}{% from "af_macros.html" import steps, note with context %}{% block title %}Enter your code{% endblock %}
{% block sidetitle %}{% if mode == 'reset' %}Reset password{% elif mode == 'email' %}Verify email{% else %}Join us{% endif %}{% endblock %}
{% block sidetext %}{% if mode == 'reset' %}Enter the code we sent to your email, then choose a new password.{% elif mode == 'email' %}Enter the code we sent to confirm your new email address.{% else %}Send a request for a teacher account. The administrator will review it, add you to the list of teachers and set up your schedule details.{% endif %}{% endblock %}
{% block afico %}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 4.5-3.2 8.2-8 9-4.8-.8-8-4.5-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/></svg>{% endblock %}
{% block afbody %}{% if mode == 'reset' %}{{ steps(2) }}{% endif %}
<h2 class="af-title">Enter your code</h2>
<p class="af-sub">We sent a 6-digit code to <b>{{ masked }}</b>. It works for {{ otp_minutes }} minutes.</p>
{% for cat, m in get_flashed_messages(with_categories=true) %}<div class="msg {{ cat }}" role="alert">{{ m }}</div>{% endfor %}
<form method="post" id="otpform">{{ csrf_field() }}
<label for="code">6-digit code</label>
<div class="af-otp" id="otpboxes" hidden></div>
<input id="code" class="af-otp-one" name="code" inputmode="numeric" pattern="[0-9 ]{6,7}" maxlength="7" autocomplete="one-time-code" required autofocus>
<p class="af-hint" id="otphint" aria-live="polite"></p>
<button class="af-btn" type="submit" id="verifybtn">{{ 'Verify and continue' if mode == 'reset' else ('Verify email' if mode == 'email' else 'Verify and send request') }}</button>
<div class="af-resend"><button type="submit" id="resendbtn" data-wait="{{ wait }}" formaction="{{ action }}" formnovalidate name="action" value="resend">Resend code</button></div>
</form>
<div class="af-links"><a href="{{ back }}">Go back</a></div>{% endblock %}
{% block afscript %}<script>(function(){
var form=document.getElementById('otpform'),one=document.getElementById('code'),boxes=document.getElementById('otpboxes'),hint=document.getElementById('otphint'),rb=document.getElementById('resendbtn');
var inputs=[];
function digits(s){return String(s||'').split('').filter(function(c){return c>='0'&&c<='9';}).join('').slice(0,6);}
function sync(){one.value=inputs.map(function(i){return i.value;}).join('');}
function fill(from,str){var d=digits(str);for(var k=0;k<d.length&&from+k<6;k++)inputs[from+k].value=d.charAt(k);sync();var n=Math.min(from+d.length,5);inputs[n].focus();inputs[n].select();}
for(var n=0;n<6;n++){(function(n){
 var i=document.createElement('input');i.type='text';i.inputMode='numeric';i.maxLength=6;i.autocomplete=n===0?'one-time-code':'off';
 i.setAttribute('aria-label','Digit '+(n+1)+' of 6');i.pattern='[0-9]*';
 i.addEventListener('input',function(){var d=digits(i.value);if(d.length>1){i.value='';fill(n,d);return;}i.value=d;sync();hint.textContent='';if(d&&n<5)inputs[n+1].focus();});
 i.addEventListener('keydown',function(e){
  if(e.key==='Backspace'&&!i.value&&n>0){inputs[n-1].value='';inputs[n-1].focus();sync();}
  else if(e.key==='ArrowLeft'&&n>0){e.preventDefault();inputs[n-1].focus();}
  else if(e.key==='ArrowRight'&&n<5){e.preventDefault();inputs[n+1].focus();}});
 i.addEventListener('paste',function(e){var t=(e.clipboardData||window.clipboardData).getData('text');e.preventDefault();fill(n,t);});
 i.addEventListener('focus',function(){i.select();});
 inputs.push(i);boxes.appendChild(i);})(n);}
one.hidden=true;one.required=false;boxes.hidden=false;
document.querySelector('label[for=code]').setAttribute('for','');
inputs[0].focus();
form.addEventListener('submit',function(e){
 if(e.submitter&&e.submitter.id==='resendbtn')return;
 if(digits(one.value).length<6){e.preventDefault();hint.className='af-hint bad';hint.textContent='Enter all 6 digits of the code.';var f=inputs.filter(function(x){return !x.value;})[0]||inputs[5];f.focus();}
});
var w=parseInt(rb.getAttribute('data-wait'),10)||0;
function tick(){if(w>0){rb.disabled=true;rb.textContent='Resend code in '+w+'s';w--;setTimeout(tick,1000);}else{rb.disabled=false;rb.textContent='Resend code';}}
tick();
})();</script>{% endblock %}
""",

"forgot_password.html": r"""{% extends "auth_base.html" %}{% from "af_macros.html" import steps, note with context %}{% block title %}Forgot password{% endblock %}
{% block sidetitle %}Account recovery{% endblock %}
{% block sidetext %}Locked out? Confirm your Employee ID and we will send a one-time code to the Gmail saved on your account, so only you can choose a new password.{% endblock %}
{% block afico %}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/><path d="M12 15v2"/></svg>{% endblock %}
{% block afbody %}{{ steps(1) }}
<h2 class="af-title">Forgot password</h2>
<p class="af-sub">Enter your Employee ID. We send a 6-digit code to the Gmail saved on your account.</p>
{% for cat, m in get_flashed_messages(with_categories=true) %}<div class="msg {{ cat }}" role="alert">{{ m }}</div>{% endfor %}
<form method="post" id="fpform">{{ csrf_field() }}
<label for="teacher_num">Employee ID</label>
<div class="tidfield"><span class="tidfix">T-</span><input id="teacher_num" name="teacher_num" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="9" value="{{ v.get('teacher_num','') }}" required autocomplete="off" autofocus></div>
<button class="af-btn" type="submit">Send code</button>
</form>
{{ note('No Gmail saved on your account, or no code arrives? Ask the administrator to reset your password in Accounts.') }}
<div class="af-links"><a href="{{ url_for('login') }}">Back to sign in</a></div>{% endblock %}
""",

"requests_block.html": r"""{% set open_probs = rows|rejectattr('resolved')|list|length %}
<div class="rq-sum noprint" aria-label="What is waiting for you">
<a class="rq-chip{{ '' if signup_rows else ' zero' }}" href="#acct" id="chip-acct"><b id="cnt-acct">{{ signup_rows|length }}</b> Account approvals</a>
<a class="rq-chip{{ '' if open_probs else ' zero' }}" href="#probs"><b>{{ open_probs }}</b> Open problem reports</a>
</div>
<div class="rq-h" id="acct"><h2>Account approvals</h2><span class="hint" style="margin:0">New teacher registrations with a verified Gmail. Check the email, then approve or reject.</span></div>
{% if signup_rows %}
<div class="rq-list" id="rqlist" data-tools="account requests" data-items=".rq-card" data-tf-filters="grade:Grade level" data-tf-sorts="when:Date registered:text,name:Name:text">
{% for r in signup_rows %}<article class="rq-card" id="rq{{ r.id }}" data-find="{{ (r.full_name ~ ' ' ~ (r.email or '') ~ ' ' ~ r.username ~ ' ' ~ (r.teacher_id or ''))|lower }}" data-tf-grade="{{ cats.get(r.category, r.category) }}" data-tf-when="{{ r.created }}" data-tf-name="{{ r.full_name|lower }}">
<div class="rq-top"><span class="rq-av" aria-hidden="true">{{ r.full_name[:1]|upper }}</span>
<div class="rq-who"><div class="rq-name">{{ r.full_name }}</div><div class="rq-sub">New teacher registration</div></div>
<span class="pill new rq-state">Awaiting approval</span></div>
<dl class="rq-dl">
<dt>Email</dt><dd class="rq-email">{{ r.email or 'No email on file' }}</dd>
<dt>Username</dt><dd>{{ r.username }}</dd>
<dt>Employee ID</dt><dd>{{ r.teacher_id or '-' }}</dd>
<dt>Registered</dt><dd>{{ r.created|stamp12 }}</dd>
</dl>
<div class="rq-edit">
<div><label for="rqn{{ r.id }}">Full name</label><input id="rqn{{ r.id }}" form="a{{ r.id }}" name="full_name" value="{{ r.full_name }}" maxlength="200" required></div>
<div><label for="rqt{{ r.id }}">Employee ID</label><div class="tidfield"><span class="tidfix">T-</span><input id="rqt{{ r.id }}" form="a{{ r.id }}" name="teacher_num" type="number" min="1" step="1" value="{{ r.teacher_id[2:] if r.teacher_id else suggested_id[2:] }}" required></div></div>
<div><label for="rqg{{ r.id }}">Grade level handled</label><select id="rqg{{ r.id }}" form="a{{ r.id }}" name="category">{% for k, v in cats.items() %}<option value="{{ k }}" {{ 'selected' if k == r.category }}>{{ v }}</option>{% endfor %}</select></div>
</div>
<div class="rq-acts">
<form id="a{{ r.id }}" class="rq-form" method="post" action="{{ url_for('signup_requests') }}" data-confirm="Approve the account of {{ r.full_name }} ({{ r.email or 'no email' }})? They will be added to the teachers list and can sign in.">{{ csrf_field() }}<input type="hidden" name="rid" value="{{ r.id }}"><input type="hidden" name="action" value="approve"><button type="submit">Approve</button></form>
<form class="rq-form" method="post" action="{{ url_for('signup_requests') }}" data-confirm="Reject and remove the registration of {{ r.full_name }} ({{ r.email or 'no email' }})? This cannot be undone.">{{ csrf_field() }}<input type="hidden" name="rid" value="{{ r.id }}"><input type="hidden" name="action" value="reject"><button type="submit" class="danger">Reject</button></form>
</div></article>{% endfor %}</div>
{% endif %}
<div class="rq-empty" id="rq-empty"{% if signup_rows %} hidden{% endif %}>No accounts are waiting for approval.</div>
{% if signup_rows %}<script>(function(){
var chips=document.getElementById('cnt-acct'),chip=document.getElementById('chip-acct');
function badges(sel,n){document.querySelectorAll(sel).forEach(function(b){b.textContent=n;b.hidden=!n;});}
function finish(card,kind,msg){
 var acts=card.querySelector('.rq-acts'),p=document.createElement('p');
 p.className='rq-result '+kind;p.setAttribute('role','status');p.textContent=msg;
 acts.parentNode.replaceChild(p,acts);
}
function setPending(n,bell){
 chips.textContent=n;chip.classList.toggle('zero',!n);
 badges('.pbadge',n);badges('.nbadge',bell);
 if(!document.querySelector('.rq-card:not(.is-approved):not(.is-rejected):not(.is-gone)')){
  var e=document.getElementById('rq-empty');e.textContent='All account requests have been handled.';e.hidden=false;}
}
document.querySelectorAll('form.rq-form').forEach(function(f){
 f.addEventListener('submit',function(ev){
  ev.preventDefault();                               /* the confirmation dialog has already been answered */
  if(f.__busy)return;f.__busy=true;
  var card=f.closest('.rq-card'),btns=card.querySelectorAll('.rq-acts button'),btn=ev.submitter||f.querySelector('button');
  var old=card.querySelector('.rq-result.err');if(old)old.remove();
  btns.forEach(function(b){b.disabled=true;});btn.classList.add('busy');
  function undo(){f.__busy=false;btns.forEach(function(b){b.disabled=false;});btn.classList.remove('busy');}
  fetch(f.getAttribute('action'),{method:'POST',body:new FormData(f),credentials:'same-origin',headers:{'X-Requested-With':'fetch','Accept':'application/json'}})
  .then(function(r){return r.json().then(function(d){return{ok:r.ok,d:d};},function(){return{ok:false,d:{message:'Your session may have expired. Reload the page and try again.'}};});})
  .then(function(x){
   var d=x.d||{},st=card.querySelector('.rq-state');
   if(x.ok&&(d.status==='approved'||d.status==='rejected')){
    var yes=d.status==='approved';
    card.classList.add(yes?'is-approved':'is-rejected');
    st.className='pill rq-state '+(yes?'ok':'');st.textContent=yes?'Approved':'Rejected';
    finish(card,yes?'ok':'bad',d.message);setPending(d.pending,d.bell);
   }else if(d.status==='gone'){
    card.classList.add('is-gone');st.className='pill rq-state';st.textContent='Already handled';
    finish(card,'err',d.message);setPending(d.pending,d.bell);
   }else{
    var p=document.createElement('p');p.className='rq-result err';p.setAttribute('role','alert');p.textContent=d.message||'That did not work. Please try again.';
    card.querySelector('.rq-acts').parentNode.insertBefore(p,card.querySelector('.rq-acts'));undo();
   }})
  .catch(function(){
   var p=document.createElement('p');p.className='rq-result err';p.setAttribute('role','alert');p.textContent='Could not reach the server. Check your connection and try again.';
   card.querySelector('.rq-acts').parentNode.insertBefore(p,card.querySelector('.rq-acts'));undo();});
 });
});
})();</script>{% endif %}
""",

"report.html": """{% extends "base.html" %}{% from "macros.html" import back, report_form with context %}{% block title %}Report a problem{% endblock %}
{% block content %}<div class="titlerow">{{ back(url_for('help_center') if g.user else url_for('login'), 'Back') }}<h1>Report a Problem</h1></div>
<div class="card narrow">{{ report_form(v) }}</div>{% endblock %}""",

"notifications.html": """{% extends "base.html" %}{% block title %}Notifications{% endblock %}
{% block content %}<div class="head"><h1>Notifications</h1>{% if rows %}<form method="post" onsubmit="return confirm('Delete all notifications?')">{{ csrf_field() }}<input type="hidden" name="action" value="clear"><button class="danger">Clear all</button></form>{% endif %}</div>
{% for r in rows %}<article class="card note{{ ' fresh' if r.id in fresh }}"><div class="rhead"><div><p class="rmsg">{{ r.message }}</p><div class="hint">{{ r.created|stamp12 }}</div></div><div>{% if r.id in fresh %}<span class="pill new">New</span>{% endif %}</div></div>
<div class="row-acts" style="margin-top:.6rem">{% if r.link %}<a class="btn plain small" href="{{ r.link }}">View</a>{% endif %}
<form method="post">{{ csrf_field() }}<input type="hidden" name="rid" value="{{ r.id }}"><input type="hidden" name="action" value="delete"><button class="danger">Delete</button></form></div></article>
{% else %}<div class="card">No notifications yet. You will be told here when the administrator updates your Teacher's Program or assigns you to a class period or section.</div>{% endfor %}{% endblock %}""",

"reports.html": """{% extends "base.html" %}{% block title %}Notifications{% endblock %}
{% block content %}{{ subnav('users') }}<div class="head"><div><h1>Requests and Problem Reports</h1><p class="hint" style="margin-top:.6rem">Account requests and problem reports from teachers appear here. Delete a report once it is solved so this list stays short.</p></div>{% if any_resolved %}<form method="post" onsubmit="return confirm('Delete all resolved reports?')">{{ csrf_field() }}<input type="hidden" name="action" value="clear"><button class="danger">Clear resolved</button></form>{% endif %}</div>
{% include "requests_block.html" %}
<div class="rq-h" id="probs"><h2>Problem reports</h2></div>
<div class="rq-probs" data-tools="problem reports" data-items="article.report" data-tf-filters="state:Status" data-tf-sorts="when:Date reported:text,name:Name:text">
{% for r in rows %}<article class="card report{{ ' fresh' if r.id in fresh }}{{ ' done' if r.resolved }}" data-find="{{ ((r.name or '') ~ ' ' ~ (r.contact or '') ~ ' ' ~ r.message)|lower }}" data-tf-state="{{ 'Resolved' if r.resolved else ('New' if r.id in fresh else 'Open') }}" data-tf-when="{{ r.created }}" data-tf-name="{{ (r.name or '')|lower }}">
<div class="rhead"><div><strong>{{ r.name }}</strong>{% if r.contact %} <span class="hint">({{ r.contact }})</span>{% endif %}
<div class="hint">{{ r.created|stamp12 }}</div></div>
<div>{% if r.id in fresh %}<span class="pill new">New</span>{% endif %}{% if r.resolved %}<span class="pill ok">Resolved</span>{% endif %}</div></div>
<p class="rmsg">{{ r.message }}</p>
{% if r.has_photo %}<button type="button" class="shotbtn" data-full="{{ url_for('report_photo', rid=r.id) }}"><img class="rphoto" src="{{ url_for('report_photo', rid=r.id) }}" alt="Photo attached to the report" loading="lazy"></button>{% endif %}
{% if shots.get(r.id) %}<p class="hint">{{ shots[r.id]|length }} screenshot{{ '' if shots[r.id]|length == 1 else 's' }} attached. Tap one to open it full size.</p><div class="rgallery">{% for pid in shots[r.id] %}<button type="button" class="shotbtn" data-full="{{ url_for('report_shot', pid=pid) }}"><img src="{{ url_for('report_shot', pid=pid) }}" alt="Screenshot {{ loop.index }} of the report" loading="lazy"></button>{% endfor %}</div>{% endif %}
<div class="row-acts" style="margin-top:.8rem">
<form method="post">{{ csrf_field() }}<input type="hidden" name="rid" value="{{ r.id }}"><input type="hidden" name="action" value="resolve"><button class="plain small">{{ 'Reopen' if r.resolved else 'Mark as resolved' }}</button></form>
<form method="post" onsubmit="return confirm('Delete this report?')">{{ csrf_field() }}<input type="hidden" name="rid" value="{{ r.id }}"><input type="hidden" name="action" value="delete"><button class="danger">Delete</button></form></div></article>
{% else %}<div class="card">No problem reports yet. When a user reports a problem it appears here and you get a notification.</div>{% endfor %}</div>
<div id="shotbox" class="shotbox noprint" hidden><button type="button" class="backbtn shotback" id="shotback" title="Back" aria-label="Back"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7"/></svg><span>Back</span></button><img id="shotimg" src="" alt="Full size screenshot"></div>
<script>(function(){
var box=document.getElementById('shotbox'),img=document.getElementById('shotimg'),back=document.getElementById('shotback');
document.body.appendChild(box);
var pushed=false;
function open(src){img.src=src;box.hidden=false;document.body.style.overflow='hidden';back.focus();
try{history.pushState({shot:1},'');pushed=true;}catch(e){pushed=false;}}
function close(){if(box.hidden)return;box.hidden=true;img.src='';document.body.style.overflow='';
if(pushed){pushed=false;try{history.back();}catch(e){}}}
window.addEventListener('popstate',function(){if(!box.hidden){pushed=false;close();}});
document.querySelectorAll('.shotbtn').forEach(function(b){b.addEventListener('click',function(){open(b.getAttribute('data-full'));});});
back.addEventListener('click',close);
box.addEventListener('click',function(ev){if(ev.target===box)close();});
document.addEventListener('keydown',function(ev){if(ev.key==='Escape'&&!box.hidden)close();});
})();</script>
{% endblock %}""",
}
# ======================================================================================
# AUTOMATED CLASS PROGRAM GENERATION (add-on)
# Subjects -> Rooms -> Qualifications -> Teacher loading -> Generate -> Review -> Apply.
# The generator writes into the same `classes` table the manual editor uses, so Class
# Programs, Teacher's Programs, printing and notifications keep working unchanged.
# ======================================================================================
import random
from collections import defaultdict

RTYPES = ["Regular", "Computer Laboratory", "Cookery Laboratory", "Science Laboratory",
          "TechPro Workshop", "Other Laboratory"]
DEFAULT_TT = """# SHIFT start-end [recess]   (one line per period; the shift name is the first word)
AM 06:00-07:00
AM 07:00-08:00
AM 08:00-09:00
AM 09:00-09:30 recess
AM 09:30-10:30
AM 10:30-11:30
AM 11:30-12:30
PM 13:00-14:00
PM 14:00-15:00
PM 15:00-15:30 recess
PM 15:30-16:30
PM 16:30-17:30
PM 17:30-18:30
MID 09:00-10:00
MID 10:00-11:00
MID 11:00-12:00
MID 12:00-13:00 recess
MID 13:00-14:00
MID 14:00-15:00
MID 15:00-16:00
"""
def curriculum_rows():
    """The Strengthened Curriculum as database rows. Minutes are starting values the school can edit."""
    core_min = {"EC": 120, "MK": 120, "LCS": 240, "GM": 240, "GS": 240, "PKLP": 240}
    rows = [(c, n, n, 0, "", core_min[c], 60, "Regular", "core", "") for c, n in CORE_SUBJECTS]
    rows += [(c, n, n, 0, "Academic", 480, 120, rt, "cluster", ", ".join(sp)) for c, n, sp, rt in ACADEMIC_CLUSTERS]
    rows += [(c, n, n, 0, "TechPro", 480, 120, rt, "cluster", ", ".join(sp)) for c, n, sp, rt in TECHPRO_CLUSTERS]
    return rows


def seed_curriculum(conn):
    """Make sure every fixed subject and cluster exists. Minutes the school already edited are kept."""
    n = 0
    for code, name, area, grade, track, wk, se, rt, kind, detail in curriculum_rows():
        row = conn.execute("SELECT id, COALESCE(edited,0) FROM subjects WHERE lower(name)=lower(?)", (name,)).fetchone()
        if row and row[1]:
            continue                                   # edited by an administrator: never overwritten at startup
        if row:
            conn.execute("UPDATE subjects SET code=?, name=?, area=?, grade=0, track=?, kind=?, detail=? WHERE id=?",
                         (code, name, area, track, kind, detail, row[0]))
        else:
            conn.execute("INSERT INTO subjects(code,name,area,grade,track,weekly_min,session_min,rtype,kind,detail,offered) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,1)", (code, name, area, grade, track, wk, se, rt, kind, detail))
            n += 1
    conn.commit()
    return n


def migrate_curriculum():
    """One-time move to the fixed curriculum: remove subjects that are not part of it and map the
    free-text specializations the old example data used."""
    conn = raw_connect()
    conn.execute("UPDATE subjects SET offered=1 WHERE offered IS NULL")
    v3 = not conn.execute("SELECT 1 FROM settings WHERE k='curriculum_v3'").fetchone()
    both = "effective communication / mabisang komunikasyon"
    if v3:  # the old combined subject becomes Effective Communication (its sections and teachers carry over)
        old = conn.execute("SELECT id FROM subjects WHERE lower(name)=?", (both,)).fetchone()
        ec = conn.execute("SELECT id FROM subjects WHERE lower(name)='effective communication'").fetchone()
        if old and not ec:
            conn.execute("UPDATE subjects SET name='Effective Communication', code='EC' WHERE id=?", (old[0],))
        elif old and ec:
            for t, cols in (("section_subjects", "section_id"), ("teacher_subjects", "user_id")):
                conn.execute(f"INSERT OR IGNORE INTO {t}({cols}, subject_id) SELECT {cols}, ? FROM {t} WHERE subject_id=?", (ec[0], old[0]))
                conn.execute(f"DELETE FROM {t} WHERE subject_id=?", (old[0],))
            conn.execute("INSERT OR IGNORE INTO loads(section_id,subject_id,teacher_id) SELECT section_id, ?, teacher_id FROM loads WHERE subject_id=?", (ec[0], old[0]))
            conn.execute("DELETE FROM loads WHERE subject_id=?", (old[0],))
            conn.execute("DELETE FROM subjects WHERE id=?", (old[0],))
    seed_curriculum(conn)
    if v3:
        ec = conn.execute("SELECT id FROM subjects WHERE lower(name)='effective communication'").fetchone()
        mk = conn.execute("SELECT id FROM subjects WHERE lower(name)='mabisang komunikasyon'").fetchone()
        if ec and mk:  # every section, teacher qualification and teacher load of EC is copied to MK
            conn.execute("INSERT OR IGNORE INTO section_subjects(section_id,subject_id) SELECT section_id, ? FROM section_subjects WHERE subject_id=?", (mk[0], ec[0]))
            conn.execute("INSERT OR IGNORE INTO teacher_subjects(user_id,subject_id) SELECT user_id, ? FROM teacher_subjects WHERE subject_id=?", (mk[0], ec[0]))
            conn.execute("INSERT OR IGNORE INTO loads(section_id,subject_id,teacher_id) SELECT section_id, ?, teacher_id FROM loads WHERE subject_id=?", (mk[0], ec[0]))
        new_both = "Effective Communication" + SPEC_SEP + "Mabisang Komunikasyon"
        for col in ("specialization", "subject_area"):
            for uid, txt in conn.execute(f"SELECT id, {col} FROM users WHERE {col} LIKE '%Mabisang Komunikasyon%'").fetchall():
                fixed = re.sub(r"Effective Communication\s*/\s*Mabisang Komunikasyon", new_both, txt or "")
                if fixed != txt:
                    conn.execute(f"UPDATE users SET {col}=? WHERE id=?", (fixed, uid))
        for _c, nm, _a, _g, _t, wk, se, _rt, _k, _d in curriculum_rows():  # new weekly hours of the class program
            conn.execute("UPDATE subjects SET weekly_min=?, session_min=? WHERE lower(name)=lower(?)", (wk, se, nm))
        ids = [r[0] for r in conn.execute("SELECT id FROM sections").fetchall()]
        conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('stale_sections',?)", (json.dumps(ids),))
        conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('curriculum_v3','1')")
    done = conn.execute("SELECT 1 FROM settings WHERE k='curriculum_v2'").fetchone()
    if not done:
        keep = {n.lower() for _c, n in CORE_SUBJECTS} | {c[1].lower() for c in ACADEMIC_CLUSTERS + TECHPRO_CLUSTERS}
        for sid, name in conn.execute("SELECT id, name FROM subjects").fetchall():
            if name.lower() not in keep:
                for t in ("section_subjects", "teacher_subjects", "loads"):
                    conn.execute(f"DELETE FROM {t} WHERE subject_id=?", (sid,))
                conn.execute("DELETE FROM subjects WHERE id=?", (sid,))
        for uid, spec in conn.execute("SELECT id, specialization FROM users WHERE role='teacher'").fetchall():
            if spec and spec.strip() in LEGACY_SPEC:
                conn.execute("UPDATE users SET specialization=? WHERE id=?", (LEGACY_SPEC[spec.strip()], uid))
        conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('curriculum_v2','1')")
    if not conn.execute("SELECT 1 FROM settings WHERE k='electives_v1'").fetchone():
        for uid, spec in conn.execute("SELECT id, specialization FROM users WHERE role='teacher'").fetchall():
            old = [x.strip() for x in (spec or "").split(";") if x.strip()]
            new = []
            for tk in old:
                for nm in ELECTIVE_RENAMES.get(tk, [tk]):
                    if nm not in new:
                        new.append(nm)
            if new != old:
                conn.execute("UPDATE users SET specialization=? WHERE id=?", (SPEC_SEP.join(new), uid))
        conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('electives_v1','1')")
    conn.execute("UPDATE sections SET shift='AM' WHERE grade=11 AND COALESCE(shift,'')<>'AM'")
    conn.execute("UPDATE sections SET shift='PM' WHERE grade=12 AND COALESCE(shift,'')<>'PM'")
    for nm, cl in list(SAMPLE_CLUSTER.items()):
        conn.execute("UPDATE sections SET cluster=? WHERE name=? AND COALESCE(cluster,'')=''", (cl, nm))
    conn.commit()
    conn.close()


def init_auto_db():
    conn = raw_connect()
    conn.script("""
    CREATE TABLE IF NOT EXISTS subjects(
        id SERIAL PRIMARY KEY, code TEXT, name TEXT NOT NULL, area TEXT, grade INTEGER DEFAULT 0,
        track TEXT DEFAULT '', weekly_min INTEGER NOT NULL, session_min INTEGER NOT NULL,
        rtype TEXT DEFAULT 'Regular');
    CREATE TABLE IF NOT EXISTS rooms(
        id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, rtype TEXT DEFAULT 'Regular',
        building TEXT, floor TEXT);
    CREATE TABLE IF NOT EXISTS room_types(
        id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, facilities TEXT DEFAULT '',
        builtin INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS section_subjects(
        section_id INTEGER NOT NULL, subject_id INTEGER NOT NULL, PRIMARY KEY(section_id, subject_id));
    CREATE TABLE IF NOT EXISTS teacher_subjects(
        user_id INTEGER NOT NULL, subject_id INTEGER NOT NULL, PRIMARY KEY(user_id, subject_id));
    CREATE TABLE IF NOT EXISTS loads(
        section_id INTEGER NOT NULL, subject_id INTEGER NOT NULL, teacher_id INTEGER,
        PRIMARY KEY(section_id, subject_id));
    """)
    add_col(conn, "sections", "shift", "TEXT")
    add_col(conn, "sections", "cluster", "TEXT")
    add_col(conn, "subjects", "kind", "TEXT DEFAULT ''")
    add_col(conn, "subjects", "offered", "INTEGER DEFAULT 1")
    add_col(conn, "subjects", "detail", "TEXT")
    add_col(conn, "subjects", "custom", "INTEGER DEFAULT 0")     # 1 = added by an administrator
    add_col(conn, "subjects", "edited", "INTEGER DEFAULT 0")     # 1 = edited by an administrator (startup never overwrites it)
    add_col(conn, "subjects", "status", "TEXT")                  # active / inactive / archived
    conn.execute("UPDATE subjects SET status = CASE WHEN COALESCE(offered,1)=1 THEN 'active' ELSE 'inactive' END "
                 "WHERE status IS NULL OR status=''")
    conn.execute("ALTER TABLE subjects ALTER COLUMN status SET DEFAULT 'active'")
    conn.commit()
    for ix, ddl in (("ux_subjects_name", "CREATE UNIQUE INDEX IF NOT EXISTS ux_subjects_name ON subjects (lower(name))"),
                    ("ux_subjects_code", "CREATE UNIQUE INDEX IF NOT EXISTS ux_subjects_code ON subjects (lower(code)) "
                                         "WHERE code IS NOT NULL AND code <> ''")):
        try:                                   # only when the existing data has no duplicates; otherwise skipped, not forced
            conn.execute(ddl)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            print(f"Skipped unique index {ix}: existing duplicate subjects must be resolved first ({type(exc).__name__}).")
    add_col(conn, "rooms", "grade_access", "TEXT DEFAULT 'Both'")  # Both, 11 or 12
    conn.execute("""CREATE TABLE IF NOT EXISTS audit_log(
        id SERIAL PRIMARY KEY, at TEXT, user_id INTEGER, who TEXT, role TEXT, action TEXT, detail TEXT, ip TEXT)""")
    add_col(conn, "classes", "room", "TEXT")
    add_col(conn, "classes", "room_id", "INTEGER")
    for ddl in ("CREATE INDEX IF NOT EXISTS ix_classes_section ON classes(section_id)",
                "CREATE INDEX IF NOT EXISTS ix_classes_teacher ON classes(teacher_id)",
                "CREATE INDEX IF NOT EXISTS ix_classes_room ON classes(room_id)",
                "CREATE INDEX IF NOT EXISTS ix_loads_teacher ON loads(teacher_id)",
                "CREATE INDEX IF NOT EXISTS ix_users_role ON users(role)"):
        conn.execute(ddl)
    conn.commit()
    repair_orphans(conn)
    conn.close()


def repair_orphans(conn):
    """Remove links that point at records which no longer exist (left behind by older delete routes).
    Only dangling links are touched; valid records are never changed. Returns how many were fixed."""
    fixes = (
        "DELETE FROM loads WHERE section_id NOT IN (SELECT id FROM sections) "
        "OR subject_id NOT IN (SELECT id FROM subjects)",
        "UPDATE loads SET teacher_id=NULL WHERE teacher_id IS NOT NULL AND teacher_id NOT IN (SELECT id FROM users)",
        "DELETE FROM section_subjects WHERE section_id NOT IN (SELECT id FROM sections) "
        "OR subject_id NOT IN (SELECT id FROM subjects)",
        "DELETE FROM teacher_subjects WHERE user_id NOT IN (SELECT id FROM users) "
        "OR subject_id NOT IN (SELECT id FROM subjects)",
        "UPDATE classes SET teacher_id=NULL WHERE teacher_id IS NOT NULL AND teacher_id NOT IN (SELECT id FROM users)",
        "UPDATE classes SET room=NULL, room_id=NULL WHERE room_id IS NOT NULL AND room_id NOT IN (SELECT id FROM rooms)",
        "DELETE FROM classes WHERE section_id NOT IN (SELECT id FROM sections)",
        "UPDATE sections SET adviser_id=NULL WHERE adviser_id IS NOT NULL AND adviser_id NOT IN (SELECT id FROM users)",
    )
    total = 0
    try:
        for sql in fixes:
            total += conn.execute(sql).rowcount or 0
        conn.commit()
    except Exception as exc:                                 # never stop the site from starting
        conn.rollback()
        print("Orphan repair skipped:", exc)
    if total:
        print(f"Repaired {total} dangling link(s) left by earlier deletes.")
    return total


# ------------------------------------------------------------------ settings and timetable
def gset(k, d=""):
    r = query("SELECT v FROM settings WHERE k=?", (k,), one=True)
    return r["v"] if r else d


def sset(k, v):
    run("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, str(v)))


def parse_tt(text):
    """'AM 06:00-07:00' / 'AM 09:00-09:30 recess' -> {'AM': [(360, 420, 'class'), ...]}."""
    tt = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(\S+)\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*(class|recess|break)?\s*$", line, re.I)
        if not m or m[1].startswith("#"):
            continue
        s, e = int(m[2]) * 60 + int(m[3]), int(m[4]) * 60 + int(m[5])
        if e > s:
            kind = "recess" if (m[6] or "").lower() in ("recess", "break") else "class"
            tt.setdefault(m[1].upper(), []).append((s, e, kind))
    for k in tt:
        tt[k].sort()
    return tt


def tt_overlap(tt):
    for k, per in tt.items():
        for a, b in zip(per, per[1:]):
            if b[0] < a[1]:
                return f"Periods overlap in {k}: {tm(a[0])}-{tm(a[1])} and {tm(b[0])}-{tm(b[1])}."
    return None


def get_tt():
    return parse_tt(gset("tt_text", "") or DEFAULT_TT) or parse_tt(DEFAULT_TT)


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def g12_programs():
    """Grade 12 always gets a class program, like Grade 11 (there is no lock any more)."""
    return True


def sched_secs():
    """The sections that get a class program."""
    rows = query("SELECT * FROM sections ORDER BY grade, name")
    return rows if g12_programs() else [r for r in rows if r["grade"] != 12]


def teacher_shift(t, tt):
    """AM, MID or PM when the teacher's official time equals one shift; '' for a custom time."""
    a, b = official_range(t["official_time"])
    if not a:
        return ""
    for name, per in tt.items():
        if (tomin(a), tomin(b)) == (per[0][0], per[-1][1]):
            return name
    return ""


def shift_hours(tt, name):
    def f(m):
        h, mi = divmod(int(m), 60)
        ap = "NN" if (h, mi) == (12, 0) else ("AM" if h < 12 else "PM")
        return f"{(h % 12) or 12}:{mi:02d} {ap}"
    per = tt[name]
    return f"{f(per[0][0])} - {f(per[-1][1])}"


def sec_shift(s, tt):
    want = "AM" if s["grade"] == 11 else "PM"
    if want in tt:
        return want
    keys = sorted(tt, key=lambda k: tt[k][0][0])
    return keys[0] if s["grade"] == 11 or len(keys) == 1 else keys[-1]


def teacher_window(t):
    a, b = official_range(t["official_time"])
    return (tomin(a), tomin(b)) if a and b else (0, 1440)


def session_lengths(weekly, sess):
    sess = max(10, sess)
    n, rem = divmod(weekly, sess)
    return [sess] * n + ([rem] if rem else [])


def blocks_for(periods, L):
    """Start/end of every run of back-to-back class periods that adds up to exactly L minutes."""
    out = []
    for i in range(len(periods)):
        tot, j, ok = 0, i, False
        while j < len(periods):
            s, e, kind = periods[j]
            if kind != "class" or (j > i and s != periods[j - 1][1]):
                break
            tot += e - s
            if tot == L:
                ok = True
                break
            if tot > L:
                break
            j += 1
        if ok:
            out.append((periods[i][0], periods[j][1]))
    return out


def rtype_options():
    """Every room type the school can use: the Room Types list first (Room Management), then - only as a safety net -
    any type a room or subject still carries that is not on the list yet."""
    try:
        seen = [r["name"] for r in query("SELECT name FROM room_types ORDER BY id")]
    except Exception:
        seen = []
    if not seen:
        seen = list(RTYPES)
    if "Regular" not in seen:
        seen.insert(0, "Regular")
    for r in query("SELECT rtype FROM rooms UNION SELECT rtype FROM subjects"):
        if r["rtype"] and r["rtype"] not in seen:
            seen.append(r["rtype"])
    return seen


# ------------------------------------------------------------------ room types (the facilities a room can have)
# One list, kept in Room Management. Subject Management ("Room needed") and Quick Input / Room Management (a room's
# type) both choose from it, and the generator only puts a subject in a room whose type matches.
RT_NAME_MAX = 60
RT_RESERVED = {"regular", "regular classroom", "classroom"}      # _is_classroom() treats these as the classroom type
RT_NOTES = {
    "Regular": "Ordinary classroom. Sections use it as their home room.",
    "Computer Laboratory": "Computers for ICT, programming, animation and illustration.",
    "Cookery Laboratory": "Kitchen stations and equipment for cookery and food subjects.",
    "Science Laboratory": "Laboratory tables, sinks and apparatus for science subjects.",
    "TechPro Workshop": "Tools and workbenches for TechPro workshop subjects.",
    "Other Laboratory": "Any other specialised laboratory.",
}


def seed_room_types():
    """Start-up: put the built-in types on the list once, and make sure no type that a room or subject already uses
    is missing from it. Types an administrator adds or deletes later are never touched here."""
    conn = raw_connect()
    try:
        if not conn.execute("SELECT 1 FROM settings WHERE k='room_types_v1'").fetchone():
            for nm in RTYPES:
                conn.execute("INSERT OR IGNORE INTO room_types(name, facilities, builtin) VALUES(?,?,1)",
                             (nm, RT_NOTES.get(nm, "")))
            conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('room_types_v1','1')")
        conn.execute("INSERT OR IGNORE INTO room_types(name, facilities, builtin) VALUES('Regular',?,1)", (RT_NOTES["Regular"],))
        for r in conn.execute("SELECT rtype FROM rooms UNION SELECT rtype FROM subjects").fetchall():
            nm = r[0]
            if nm and not conn.execute("SELECT 1 FROM room_types WHERE lower(name)=lower(?)", (nm,)).fetchone():
                conn.execute("INSERT OR IGNORE INTO room_types(name, facilities, builtin) VALUES(?,?,0)", (nm, ""))
        conn.commit()
    finally:
        conn.close()


def ensure_room_type(name):
    """Register `name` on the list when it is not there yet (used when subjects are set back to starting values)."""
    name = clean(name, RT_NAME_MAX)
    if name and not query("SELECT 1 FROM room_types WHERE lower(name)=lower(?)", (name,), one=True):
        try:
            run("INSERT INTO room_types(name, facilities, builtin) VALUES(?,?,0)", (name, ""))
        except IntegrityError:
            pass


def room_type_rows():
    """The Room Types table: each type with how many rooms and subjects use it and what may be done to it."""
    rooms = {r["rtype"]: r["n"] for r in query("SELECT rtype, COUNT(*) AS n FROM rooms GROUP BY rtype")}
    subs = {r["rtype"]: r["n"] for r in query("SELECT rtype, COUNT(*) AS n FROM subjects GROUP BY rtype")}
    out = []
    for t in query("SELECT * FROM room_types ORDER BY id"):
        nr, ns = rooms.get(t["name"], 0), subs.get(t["name"], 0)
        out.append(dict(id=t["id"], name=t["name"], facilities=t["facilities"] or "", builtin=bool(t["builtin"]),
                        rooms=nr, subjects=ns, classroom=(t["name"] == "Regular")))
    return out


def _rt_check(name, exclude_id=0):
    if not name:
        return "Enter the room type name."
    if name.lower() in RT_RESERVED and name != "Regular":
        return f"{name} is the same as the Regular classroom type."
    if query("SELECT 1 FROM room_types WHERE lower(name)=lower(?) AND id!=?", (name, exclude_id), one=True):
        return f"{name} is already on the list."
    return None


def room_type_add(name, facilities):
    """Add a room type. Returns (ok, message, name)."""
    name, fac = clean(name, RT_NAME_MAX), clean(facilities, 200)
    err = _rt_check(name)
    if err:
        return False, err, name
    try:
        run("INSERT INTO room_types(name, facilities, builtin) VALUES(?,?,0)", (name, fac))
    except IntegrityError:
        return False, f"{name} is already on the list.", name
    audit_event(g.user, "Room type created", name)
    return True, f"{name} was added. You can now choose it for subjects and rooms.", name


def room_type_update(tid, name, facilities):
    """Edit a room type. Renaming also renames it on every room and subject that uses it, so nothing is left
    pointing at the old name. The built-in types keep their names because the curriculum refers to them."""
    cur = query("SELECT * FROM room_types WHERE id=?", (tid,), one=True) if tid else None
    if not cur:
        return False, "That room type no longer exists."
    fac = clean(facilities, 200)
    name = cur["name"] if cur["builtin"] else clean(name, RT_NAME_MAX)
    err = _rt_check(name, cur["id"])
    if err:
        return False, err
    try:
        run("UPDATE room_types SET name=?, facilities=? WHERE id=?", (name, fac, cur["id"]))
    except IntegrityError:
        return False, f"{name} is already on the list."
    if name != cur["name"]:
        run("UPDATE rooms SET rtype=? WHERE rtype=?", (name, cur["name"]))
        run("UPDATE subjects SET rtype=? WHERE rtype=?", (name, cur["name"]))
    audit_event(g.user, "Room type edited", f"{cur['name']}" + (f" -> {name}" if name != cur["name"] else ""))
    return True, f"{name} was updated." + (" Rooms and subjects that used it now show the new name." if name != cur["name"] else "")


def room_type_remove(tid):
    """Delete a room type that no room and no subject uses. Returns (ok, message)."""
    cur = query("SELECT * FROM room_types WHERE id=?", (tid,), one=True) if tid else None
    if not cur:
        return False, "That room type no longer exists."
    if cur["name"] == "Regular":
        return False, "Regular is the classroom type. Sections use it for their home rooms, so it cannot be deleted."
    nr = query("SELECT COUNT(*) AS n FROM rooms WHERE rtype=?", (cur["name"],), one=True)["n"]
    ns = query("SELECT COUNT(*) AS n FROM subjects WHERE rtype=?", (cur["name"],), one=True)["n"]
    if nr or ns:
        parts = ([f"{nr} room{'s' if nr != 1 else ''}"] if nr else []) + ([f"{ns} subject{'s' if ns != 1 else ''}"] if ns else [])
        return False, (f"{cur['name']} is still used by {' and '.join(parts)}. "
                       "Change those to another room type first, then delete it.")
    run("DELETE FROM room_types WHERE id=?", (cur["id"],))
    audit_event(g.user, "Room type deleted", cur["name"])
    return True, f"{cur['name']} was deleted."


# ------------------------------------------------------------------ the subject service (single source of truth)
SUBJECT_STATUSES = ("active", "inactive", "archived")


def subj_status(s):
    """active / inactive / archived. Rows from before the status column fall back to the old 'offered' flag."""
    try:
        st = s["status"]
    except (KeyError, IndexError):
        st = None
    if st in SUBJECT_STATUSES:
        return st
    return "active" if (s["offered"] is None or s["offered"]) else "inactive"


def subject_catalog(status="active", kind=None, track=None, grade=None, q=None):
    """The one place that reads the subject list. status: 'active' (default), a status name, or None for all.
    kind: 'core' / 'cluster'. grade: keeps subjects that apply to that grade level."""
    out = []
    needle = (q or "").strip().lower()
    for s in query("SELECT * FROM subjects ORDER BY id"):
        if status and subj_status(s) != status:
            continue
        k = "cluster" if (s["kind"] or "") == "cluster" else "core"
        if kind and k != kind:
            continue
        if track and (s["track"] or "") != track:
            continue
        if grade and s["grade"] not in (0, None, int(grade)):
            continue
        if needle and needle not in " ".join(str(s[x] or "") for x in ("name", "code", "track", "kind")).lower():
            continue
        out.append(s)
    return out


def subjects_for_section(sec):
    """Active subjects that belong to this section (its core subjects and its own elective)."""
    return [s for s in subject_catalog() if eligible(s, sec)]


def subjects_for_teacher(tid):
    """Active subjects the teacher is qualified for (saved qualifications plus the specialization)."""
    mine = {sid for uid, sid in qualified_pairs() if uid == tid}
    return [s for s in subject_catalog() if s["id"] in mine]


def live_spec(mode="quick"):
    """What a teacher can be specialized in, read from Subject Management (active subjects only), as
    (groups, meta). groups: [(label, [names])]; meta[name]: code, cluster, category, classification for search.
    mode 'quick': core + each cluster's subjects.  mode 'manage': also lists the clusters themselves."""
    rows = subject_catalog()
    meta, groups = {}, []
    core = [s for s in rows if (s["kind"] or "") != "cluster"]
    groups.append(("Core subjects", [s["name"] for s in core]))
    for s in core:
        meta[s["name"]] = dict(code=s["code"] or "", cluster="", category="Core", cls="Core subject")
    by_track = {"Academic": [], "TechPro": []}
    for s in rows:
        if (s["kind"] or "") == "cluster" and (s["track"] or "") in by_track:
            by_track[s["track"]].append(s)
    elective_groups = []
    for tr in ("Academic", "TechPro"):
        for c in by_track[tr]:
            items = list(CLUSTER_SPECS.get(c["name"]) or [c["name"]])
            for it in items:
                meta[it] = dict(code=(c["code"] or "") if it == c["name"] else "", cluster=c["name"], category=tr,
                                cls=f"{tr} elective")
            elective_groups.append((tr, c["name"], items))
    if mode == "quick":
        groups += [(f"{tr}: {cl}", items) for tr, cl, items in elective_groups]
    else:
        for tr in ("Academic", "TechPro"):
            groups.append((f"{tr} clusters", [c["name"] for c in by_track[tr]]))
            for c in by_track[tr]:
                meta.setdefault(c["name"], dict(code=c["code"] or "", cluster=c["name"], category=tr,
                                                cls=f"{tr} cluster"))
        for tr in ("Academic", "TechPro"):
            names = {c["name"] for c in by_track[tr]}
            groups.append((f"{tr} electives",
                           sorted({it for t_, cl, items in elective_groups if t_ == tr for it in items} - names)))
    return groups, meta


def spec_live():
    """Picker data for the current request, read from Subject Management once and shared by every picker."""
    cached = g.get("_spec_live")
    if cached is None:
        quick, qmeta = live_spec("quick")
        manage, mmeta = live_spec("manage")
        names = {n for _g, items in quick + manage for n in items}
        cached = g._spec_live = dict(quick=quick, manage=manage, meta={**mmeta, **qmeta}, names=sorted(names))
    return cached


def live_spec_names():
    """Every specialization name an administrator may currently choose."""
    return set(spec_live()["names"])


app.jinja_env.globals["spec_live"] = spec_live


def subject_dependencies(sub):
    """Everything that still uses a subject. Used before a permanent delete."""
    sid, name = sub["id"], sub["name"]
    deps = {}
    secs = query("SELECT s.name FROM section_subjects ss JOIN sections s ON s.id=ss.section_id WHERE ss.subject_id=? "
                 "ORDER BY s.name", (sid,))
    if secs:
        deps["Section subjects / electives"] = [r["name"] for r in secs]
    if (sub["kind"] or "") == "cluster":
        chosen = query("SELECT name FROM sections WHERE cluster=? ORDER BY name", (name,))
        if chosen:
            deps["Sections that chose this elective"] = [r["name"] for r in chosen]
    spec = [t["full_name"] for t in query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name")
            if spec_entries(t) and teacher_has_subject(spec_entries(t), sub)]
    if spec:
        deps["Teacher specializations"] = spec
    qual = query("SELECT u.full_name FROM teacher_subjects ts JOIN users u ON u.id=ts.user_id WHERE ts.subject_id=?",
                 (sid,))
    extra = sorted({r["full_name"] for r in qual} - set(spec))
    if extra:
        deps["Teacher qualifications"] = extra
    loads = query("SELECT s.name FROM loads l JOIN sections s ON s.id=l.section_id WHERE l.subject_id=?", (sid,))
    if loads:
        deps["Teacher assignments"] = sorted({r["name"] for r in loads})
    cls = query("SELECT DISTINCT s.name FROM classes c JOIN sections s ON s.id=c.section_id WHERE c.subject=? "
                "AND c.kind='class'", (name,))
    if cls:
        deps["Class programs and teacher programs"] = [r["name"] for r in cls]
    return deps


def eligible(sub, sec):
    """A cluster belongs only to sections of its track and cluster; core subjects belong to every section.
    Inactive and archived subjects belong to no section, so they never enter a newly generated schedule."""
    if subj_status(sub) != "active":
        return False
    if sub["offered"] is not None and not sub["offered"]:
        return False
    if (sub["kind"] or "") == "cluster":
        return ((sub["track"] or "") == (sec["track"] or "") and (sec["cluster"] or "") == sub["name"]
                and sub["grade"] in (0, None, sec["grade"]))
    return (sub["grade"] in (0, None, sec["grade"])) and (not sub["track"] or sub["track"] == sec["track"])


# ------------------------------------------------------------------ the scheduling engine
class Busy:
    """Who or what is occupied when. Keys: ('t', teacher), ('s', section), ('r', room)."""

    def __init__(self):
        self.d = {}

    def add(self, key, day, s, e):
        self.d.setdefault((key, day), []).append((s, e))

    def hit(self, key, day, s, e, buf=0):
        for a, b in self.d.get((key, day), ()):
            if s < b + buf and a < e + buf:
                return True
        return False

    def total(self, key, day):
        return sum(b - a for a, b in self.d.get((key, day), ()))

    def gap(self, key, day, s, e):
        iv = self.d.get((key, day))
        if not iv:
            return 0
        return min(min(max(0, s - b, a - e) for a, b in iv), 120) / 20


def load_problem(section_ids):
    ids = set(section_ids)
    secs = {s["id"]: dict(s) for s in query("SELECT * FROM sections")}
    subs = {s["id"]: dict(s) for s in query("SELECT * FROM subjects")}
    teachers = {t["id"]: dict(t) for t in query("SELECT * FROM users WHERE role='teacher'")}
    tasks = []
    for r in query("""SELECT ss.section_id, ss.subject_id, l.teacher_id FROM section_subjects ss
                      LEFT JOIN loads l ON l.section_id=ss.section_id AND l.subject_id=ss.subject_id"""):
        if r["section_id"] in ids and r["section_id"] in secs and r["subject_id"] in subs:
            tasks.append(dict(sid=r["section_id"], sub=r["subject_id"], tid=r["teacher_id"]))
    fixed = []
    for c in query("SELECT * FROM classes WHERE kind='class'"):
        if c["section_id"] in ids:
            continue
        s, e = tomin(c["start"]), tomin(c["end"])
        if c["teacher_id"]:
            fixed.append((("t", c["teacher_id"]), c["day"], s, e))
        if c["room_id"]:
            fixed.append((("r", c["room_id"]), c["day"], s, e))
    return dict(tt=get_tt(), maxday=to_int(gset("max_teach_day", "360"), 60, 720) or 360,
                turn=to_int(gset("turnover", "0"), 0, 120) or 0, secs=secs, subs=subs,
                teachers=teachers, rooms=[dict(r) for r in query("SELECT * FROM rooms ORDER BY name")],
                tasks=tasks, fixed=fixed)


def diagnose(P, j, fail):
    sub, t = j["sub"], P["teachers"][j["tid"]]
    L, shift = j["L"], j["shift"]
    if not j["blocks"]:
        return (f"The {shift} timetable has no {L}-minute run of back-to-back class periods. "
                "Change the subject's meeting length or the timetable.")
    if not fail:
        return "No time slot was available."
    other = {k: v for k, v in fail.items() if k != "window"}
    cause = max(other, key=other.get) if other else "window"
    return {
        "section": (f"The section has no free {L}-minute block left in its {shift} timetable inside "
                    f"{t['full_name']}'s official time. Free up that time, change the teacher, or widen the official time."),
        "window": (f"No {L}-minute block of the {shift} timetable fits inside {t['full_name']}'s official time "
                   f"({t['official_time'] or 'whole day'}). Change the teacher or the official time."),
        "teacher": f"{t['full_name']} is already teaching at every time this section is free inside their official time.",
        "daycap": f"{t['full_name']} would pass the daily teaching limit of {P['maxday']} minutes.",
        "norooms": (f"No room of type '{sub['rtype']}' is registered. Add one in Quick Input." if sub["rtype"] != "Regular"
                    else "This section's home room is not a registered classroom. Choose one in Section Management."),
        "room": f"Every '{sub['rtype']}' room is occupied whenever the teacher and the section are free. Add a room.",
    }[cause]


def attempt(P, rnd):
    busy = Busy()
    for k, d, s, e in P["fixed"]:
        busy.add(k, d, s, e)
    by_type = defaultdict(list)
    for r in P["rooms"]:
        by_type[r["rtype"]].append(r)
    jobs, missing = [], {}
    cache = {}
    for t in P["tasks"]:
        sec, sub = P["secs"][t["sid"]], P["subs"][t["sub"]]
        if not t["tid"] or t["tid"] not in P["teachers"]:
            missing[(sec["id"], sub["id"])] = dict(
                sid=sec["id"], section=sec["name"], subject=sub["name"], teacher="-", minutes=sub["weekly_min"],
                reason="No teacher is assigned. " + why_no_teacher(sec, sub))
            continue
        shift = sec_shift(sec, P["tt"])
        tw = teacher_window(P["teachers"][t["tid"]])
        for L in session_lengths(sub["weekly_min"], sub["session_min"]):
            key = (shift, L)
            if key not in cache:
                cache[key] = blocks_for(P["tt"][shift], L)
            per = P["tt"][shift]
            span = (per[0][0], per[-1][1])
            ov = max(0, min(tw[1], span[1]) - max(tw[0], span[0]))
            blocks, days = cache[key], DAYS
            cpl = [(a, b) for a, b, k in per if k == "class"]
            if len(cpl) >= 3:  # the last two class periods are the elective (Mon-Thu) and Homeroom + Intervention (Fri)
                est = cpl[-2][0]
                if (sub["kind"] or "") == "cluster":
                    blocks, days = [x for x in blocks if x[0] >= est], DAYS[:4]
                else:
                    blocks = [x for x in blocks if x[1] <= est]
            jobs.append(dict(sec=sec, sub=sub, tid=t["tid"], L=L, shift=shift, win=tw, blocks=blocks, days=days,
                             tight=(span[1] - span[0] - ov) / 60))

    def hard(j):
        # labs, long meetings and teachers whose official time barely overlaps the shift go first
        return ((50 if j["sub"]["rtype"] != "Regular" else 0) + j["L"] / 10
                + j["tight"] * 4 + rnd.random() * 8)
    jobs.sort(key=hard, reverse=True)
    subday, placed, soft = defaultdict(set), [], 0.0
    for j in jobs:
        sid, tid, sub, L = j["sec"]["id"], j["tid"], j["sub"], j["L"]
        cands = by_type.get(sub["rtype"], [])
        home = (j["sec"].get("room") or "").strip().lower()
        by_hand = sub["rtype"] == "Regular"       # classrooms are given to sections by the administrator, never by the generator
        if by_hand:
            cands = [r for r in cands if r["name"].strip().lower() == home] if home else []
        elif home:
            cands = sorted(cands, key=lambda r: r["name"].lower() != home)
        buf = P["turn"] if sub["rtype"] != "Regular" else 0
        fail, best = defaultdict(int), None
        for day in j["days"]:
            for s, e in j["blocks"]:
                if s < j["win"][0] or e > j["win"][1]:
                    fail["window"] += 1
                    continue
                if busy.hit(("s", sid), day, s, e):
                    fail["section"] += 1
                    continue
                if busy.hit(("t", tid), day, s, e):
                    fail["teacher"] += 1
                    continue
                if busy.total(("t", tid), day) + L > P["maxday"]:
                    fail["daycap"] += 1
                    continue
                if by_hand and not home:
                    room = {"id": None, "name": None}   # no home room chosen yet: the period is placed without a room
                else:
                    room = next((r for r in cands if not busy.hit(("r", r["id"]), day, s, e, buf)), None)
                    if not room:
                        fail["room" if cands else "norooms"] += 1
                        continue
                sc = ((60 if day in subday[(sid, sub["id"])] else 0)
                      + busy.gap(("t", tid), day, s, e) + busy.gap(("s", sid), day, s, e)
                      + busy.total(("t", tid), day) / 60 * 2 + rnd.random() * 3)
                if best is None or sc < best[0]:
                    best = (sc, day, s, e, room)
        if best:
            sc, day, s, e, room = best
            busy.add(("s", sid), day, s, e)
            busy.add(("t", tid), day, s, e)
            if room["id"] is not None:
                busy.add(("r", room["id"]), day, s, e)
            subday[(sid, sub["id"])].add(day)
            soft += sc
            t = P["teachers"][tid]
            placed.append(dict(sid=sid, section=j["sec"]["name"], subject_id=sub["id"], subject=sub["name"],
                               code=sub["code"] or "", teacher_id=tid, teacher=t["full_name"], day=day,
                               start=hhmm(s), end=hhmm(e), room_id=room["id"], room=room["name"]))
        else:
            k = (sid, sub["id"])
            row = missing.setdefault(k, dict(sid=sid, section=j["sec"]["name"], subject=sub["name"],
                                             teacher=P["teachers"][tid]["full_name"], minutes=0,
                                             reason=diagnose(P, j, fail)))
            row["minutes"] += L
    return dict(sessions=placed, unplaced=list(missing.values()), soft=soft)


def edge_colour(edges, ncol):
    """Colour the edges of a bipartite multigraph with ncol colours so that no two edges that share an end
    have the same colour (possible whenever no end has more than ncol edges). Edges are (u, v) pairs."""
    at = defaultdict(dict)  # end -> {colour: edge index}
    col = [None] * len(edges)

    def ends(i):
        return ("s", edges[i][0]), ("t", edges[i][1])

    def put(i, c):
        col[i] = c
        for x in ends(i):
            at[x][c] = i

    def drop(i):
        for x in ends(i):
            del at[x][col[i]]

    for i, (u, v) in enumerate(edges):
        U, V = ("s", u), ("t", v)
        a = next((c for c in range(ncol) if c not in at[U]), None)
        b = next((c for c in range(ncol) if c not in at[V]), None)
        if a is None or b is None:
            return None
        if a in at[V]:
            if b in at[U]:  # swap colours a/b along the path that starts at V with colour a
                path, node, c = [], V, a
                while c in at[node]:
                    e = at[node][c]
                    path.append(e)
                    x, y = ends(e)
                    node = x if node == y else y
                    c = b if c == a else a
                old = [col[e] for e in path]
                for e in path:
                    drop(e)
                for e, c0 in zip(path, old):
                    put(e, b if c0 == a else a)
            else:
                a = b
        put(i, a)
    return col


def day_plan(k, ndays, per_day, rnd):
    """Which days each subject meets (at most once a day) so that every day has exactly per_day lessons."""
    for _ in range(40):
        rem, plan = dict(k), {}
        days = list(range(ndays))
        rnd.shuffle(days)
        ok = True
        for d in days:
            order = sorted((x for x in rem if rem[x] > 0), key=lambda x: -rem[x] + rnd.random() * 1.6)
            if len(order) < per_day:
                ok = False
                break
            plan[d] = order[:per_day]
            for x in plan[d]:
                rem[x] -= 1
        if ok and all(v == 0 for v in rem.values()):
            return plan
    return None


def structured_core(P, rnd):
    """Exact placement of the core subjects. Every section meets each core subject on different days and
    fills the first class periods of every day; teachers are never in two places at once because the
    lessons of each day are colour-coded into periods (edge colouring). Sections this cannot handle are
    left to the general placement."""
    tt, out, done = P["tt"], [], set()
    maxday = P["maxday"]
    fixed_busy = Busy()
    for k, d, a, b in P["fixed"]:
        fixed_busy.add(k, d, a, b)
    by_sec = defaultdict(list)
    for t in P["tasks"]:
        if (P["subs"][t["sub"]]["kind"] or "") != "cluster":
            by_sec[t["sid"]].append(t)
    plans, tday, rooms_used = {}, defaultdict(int), defaultdict(set)
    order = list(by_sec)
    rnd.shuffle(order)
    for sid in order:
        sec = P["secs"][sid]
        shift = sec_shift(sec, tt)
        cpl = [(a, b) for a, b, k in tt[shift] if k == "class"]
        if len(cpl) < 3:
            continue
        core_per = cpl[:-2]
        if any(b - a != 60 for a, b in core_per):
            continue
        tasks = by_sec[sid]
        ks, lesson_t = {}, {}
        good = all(t["tid"] in P["teachers"] for t in tasks)
        for t in tasks:
            sub = P["subs"][t["sub"]]
            lens = session_lengths(sub["weekly_min"], sub["session_min"])
            if sub["rtype"] != "Regular" or any(x != 60 for x in lens) or len(lens) > len(DAYS):
                good = False
            ks[t["sub"]], lesson_t[t["sub"]] = len(lens), t["tid"]
        if not good or sum(ks.values()) != len(DAYS) * len(core_per):
            continue
        for t in tasks:
            w = teacher_window(P["teachers"][t["tid"]])
            if w[0] > core_per[0][0] or w[1] < core_per[-1][1] or any(
                    (("t", t["tid"]), d) in fixed_busy.d for d in DAYS):
                good = False
        home = (sec.get("room") or "").strip().lower()
        room = next((r for r in P["rooms"] if r["name"].lower() == home and r["rtype"] == "Regular"), None)
        if not good or not room or room["id"] in rooms_used[shift] or any(
                (("r", room["id"]), d) in fixed_busy.d for d in DAYS):
            continue
        cap = min(len(core_per), max(0, (maxday - 120) // 60))
        best = None
        for _ in range(30):
            plan = day_plan(ks, len(DAYS), len(core_per), rnd)
            if not plan:
                continue
            cnt = defaultdict(int)
            for d, subs_ in plan.items():
                for x in subs_:
                    cnt[(lesson_t[x], d)] += 1
            if any(tday[k] + n > cap for k, n in cnt.items()):
                continue
            cost = sum((tday[k] + n) ** 2 for k, n in cnt.items()) + rnd.random()
            if best is None or cost < best[0]:
                best = (cost, plan, cnt)
        if not best:
            continue
        for k, n in best[2].items():
            tday[k] += n
        plans[sid] = (best[1], room, core_per, lesson_t)
        rooms_used[shift].add(room["id"])
    for d in range(len(DAYS)):
        edges, meta = [], []
        for sid, (plan, room, core_per, lesson_t) in plans.items():
            for x in plan.get(d, []):
                edges.append((sid, lesson_t[x]))
                meta.append((sid, x))
        ncol = max((len(v[2]) for v in plans.values()), default=0)
        col = edge_colour(edges, ncol) if edges else []
        if col is None:  # cannot happen when every teacher has at most ncol lessons a day; fall back
            for sid in {m[0] for m in meta}:
                plans.pop(sid, None)
            continue
        for (sid, x), c in zip(meta, col):
            if sid not in plans:
                continue
            _plan, room, core_per, lesson_t = plans[sid]
            a, b = core_per[c]
            t, sub, sec = P["teachers"][lesson_t[x]], P["subs"][x], P["secs"][sid]
            out.append(dict(sid=sid, section=sec["name"], subject_id=x, subject=sub["name"], code=sub["code"] or "",
                            teacher_id=t["id"], teacher=t["full_name"], day=DAYS[d], start=hhmm(a), end=hhmm(b),
                            room_id=room["id"], room=room["name"]))
    for sid in plans:
        for sub_id in plans[sid][3]:
            done.add((sid, sub_id))
    return out, done


def solve(section_ids, tries=40, seed=None):
    P = load_problem(section_ids)
    rnd = random.Random(seed)
    pre, done = structured_core(P, rnd)
    full = P
    P = dict(P, tasks=[t for t in P["tasks"] if (t["sid"], t["sub"]) not in done],
             fixed=list(P["fixed"]) + [x for c in pre for x in (
                 (("t", c["teacher_id"]), c["day"], tomin(c["start"]), tomin(c["end"])),
                 (("r", c["room_id"]), c["day"], tomin(c["start"]), tomin(c["end"])),
                 (("s", c["sid"]), c["day"], tomin(c["start"]), tomin(c["end"])))])
    best = None
    for _ in range(tries):
        res = attempt(P, rnd)
        if best is None or (len(res["unplaced"]), res["soft"]) < (len(best["unplaced"]), best["soft"]):
            best = res
        if not best["unplaced"] and _ >= 4:
            break
    best["sessions"] = pre + best["sessions"]
    best["sections"] = sorted(section_ids)
    best["tries"] = tries
    best["when"] = ph_stamp()
    best["maxday"], best["turn"] = P["maxday"], P["turn"]
    return best


def apply_draft(d):
    tt = get_tt()
    touched = set()
    conn = db()
    secs = {s["id"]: s for s in query("SELECT * FROM sections")}
    for sid in d["sections"]:
        if sid not in secs:
            continue
        touched |= {r["teacher_id"] for r in query(
            "SELECT DISTINCT teacher_id FROM classes WHERE section_id=? AND teacher_id IS NOT NULL", (sid,))}
        conn.execute("DELETE FROM classes WHERE section_id=?", (sid,))
        for day in DAYS:
            per = tt[sec_shift(secs[sid], tt)]
            cpl = [(a, b) for a, b, k in per if k == "class"]
            for s, e, kind in per:
                if kind == "recess":
                    conn.execute("INSERT INTO classes(section_id,day,start,end,subject,code,kind,teacher_id) "
                                 "VALUES(?,?,?,?,?,?,?,?)", (sid, day, hhmm(s), hhmm(e), "RECESS", None, "recess", None))
            if day == "Friday" and len(cpl) >= 3:  # Friday ends with Homeroom, then Intervention/Remediation
                for (a, b), (nm, kd) in zip(cpl[-2:], (("Homeroom", "homeroom"), ("Intervention/Remediation", "intervention"))):
                    conn.execute("INSERT INTO classes(section_id,day,start,end,subject,code,kind,teacher_id) "
                                 "VALUES(?,?,?,?,?,?,?,?)", (sid, day, hhmm(a), hhmm(b), nm, None, kd, None))
    for x in d["sessions"]:
        if x["sid"] in secs:
            conn.execute("INSERT INTO classes(section_id,day,start,end,subject,code,kind,teacher_id,room,room_id) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (x["sid"], x["day"], x["start"], x["end"], x["subject"], x["code"] or None, "class",
                          x["teacher_id"], x["room"], x["room_id"]))
            touched.add(x["teacher_id"])
    conn.commit()
    for sid in d["sections"]:
        touch("section", sid)
    for tid in touched:
        if tid:
            touch("teacher", tid)
            sync_category(tid)


# Rows = the first four class periods, columns = Monday..Friday. Same as the printed class programs:
# GM, GS, LCS and PKLP 4 hours each, EC and MK 2 hours each.
CORE_PATTERN = [["GM", "MK", "GS", "LCS"], ["MK", "GM", "PKLP", "LCS"], ["GS", "GM", "PKLP", "EC"],
                ["GS", "LCS", "EC", "PKLP"], ["GS", "LCS", "PKLP", "GM"]]


def build_default_program(sid, force=False):
    """The fixed class program every section starts with, before any teacher is chosen:
    the 6 core subjects in the first periods, the section's elective (cluster) in the last two
    periods Monday-Thursday, and Homeroom then Intervention/Remediation in the last two periods of Friday.
    Teachers and rooms are filled in later by Generate."""
    sec = query("SELECT * FROM sections WHERE id=?", (sid,), one=True)
    if not sec:
        return False
    if not force and query("SELECT 1 FROM classes WHERE section_id=?", (sid,), one=True):
        return False
    if sec["grade"] == 12 and not g12_programs():
        return False
    tt = get_tt()
    per = tt[sec_shift(dict(sec), tt)]
    cpl = [(a, b) for a, b, k in per if k == "class"]
    if len(cpl) < 3:
        return False
    core_per, elective = cpl[:-2], (cpl[-2][0], cpl[-1][1])
    core = {r["code"]: r for r in query("SELECT * FROM subjects WHERE kind='core' AND COALESCE(offered,1)=1")}
    room = (sec["room"] or "").strip()
    register_room(room)
    rr = query("SELECT id FROM rooms WHERE lower(name)=lower(?)", (room,), one=True) if room else None
    rid = rr["id"] if rr else None
    plan = {}  # day -> [code per core period]
    if len(core_per) == 4:
        plan = dict(zip(DAYS, CORE_PATTERN))
    else:  # a different timetable: give every period the subject with the most hours left that day
        left = {c: max(0, (r["weekly_min"] or 0) // 60) for c, r in core.items()}
        for d in DAYS:
            used, row = set(), []
            for _ in core_per:
                pick = max((c for c in left if left[c] > 0 and c not in used), key=lambda c: left[c], default=None)
                if pick:
                    left[pick] -= 1
                    used.add(pick)
                row.append(pick)
            plan[d] = row
    conn = db()
    conn.execute("DELETE FROM classes WHERE section_id=?", (sid,))
    ins = ("INSERT INTO classes(section_id,day,start,end,subject,code,kind,teacher_id,room,room_id) "
           "VALUES(?,?,?,?,?,?,?,?,?,?)")
    clu = query("SELECT * FROM subjects WHERE kind='cluster' AND name=?", (sec["cluster"],), one=True) if sec["cluster"] else None
    for i, day in enumerate(DAYS):
        for s_, e_, kind in per:
            if kind == "recess":
                conn.execute(ins, (sid, day, hhmm(s_), hhmm(e_), "RECESS", None, "recess", None, None, None))
        for (a, b), code in zip(core_per, plan.get(day, [])):
            sub = core.get(code)
            if sub:
                conn.execute(ins, (sid, day, hhmm(a), hhmm(b), sub["name"], sub["code"], "class", None, room or None, rid))
        if day != "Friday" and clu:
            conn.execute(ins, (sid, day, hhmm(elective[0]), hhmm(elective[1]), clu["name"], clu["code"], "class",
                               None, None, None))
        if day == "Friday":
            for (a, b), (nm, kd) in zip(cpl[-2:], (("Homeroom", "homeroom"), ("Intervention/Remediation", "intervention"))):
                conn.execute(ins, (sid, day, hhmm(a), hhmm(b), nm, None, kd, None, None, None))
    conn.commit()
    touch("section", sid)
    return True


# ------------------------------------------------------------------ setup helpers
def load_starter_subjects():
    """Add any missing subject or cluster of the Strengthened Curriculum (edited minutes are kept)."""
    return seed_curriculum(db())


def sync_section_subjects(sid):
    """Give a section its core subjects (when it has none yet) and exactly its own cluster."""
    sec = query("SELECT * FROM sections WHERE id=?", (sid,), one=True)
    if not sec:
        return False
    have = {r["subject_id"] for r in query("SELECT subject_id FROM section_subjects WHERE section_id=?", (sid,))}
    first, changed = not have, False
    for s in query("SELECT * FROM subjects"):
        ok = eligible(s, sec)
        if (s["kind"] or "") == "cluster":
            if ok and s["id"] not in have:
                run("INSERT OR IGNORE INTO section_subjects(section_id,subject_id) VALUES(?,?)", (sid, s["id"]))
                changed = True
            elif not ok and s["id"] in have:
                run("DELETE FROM section_subjects WHERE section_id=? AND subject_id=?", (sid, s["id"]))
                run("DELETE FROM loads WHERE section_id=? AND subject_id=?", (sid, s["id"]))
                changed = True
        elif ok:
            run("INSERT OR IGNORE INTO section_subjects(section_id,subject_id) VALUES(?,?)", (sid, s["id"]))
            changed = True
    if changed and query("SELECT 1 FROM classes WHERE section_id=? AND kind='class'", (sid,), one=True):
        mark_stale([sid])
    return changed


def missing_room_types():
    """Room types that offered subjects need but no registered room has."""
    need = {r["rtype"] for r in query("SELECT DISTINCT rtype FROM subjects WHERE COALESCE(offered,1)=1")}
    have = {r["rtype"] for r in query("SELECT DISTINCT rtype FROM rooms")}
    return sorted(x for x in need if x and x not in have)


def ensure_room_types():
    """Used to create laboratory and workshop rooms by itself. It no longer creates any room. A room type that
    offered subjects need but no registered room has is reported by missing_room_types() instead."""
    return 0


def _qnorm(text):
    """Lower case, no accents, no punctuation, single spaces: 'Pag-aaral ng  Kasaysayan' == 'pag aaral ng kasaysayan'."""
    import unicodedata
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _qcore(text):
    """Name without a trailing '(...)' note and without the filler words sa / ng, so the old short name
    'Pag-aaral sa Kasaysayan at Lipunang Pilipino' still matches the full curriculum name."""
    t = re.sub(r"\([^)]*\)", " ", text or "")
    return " ".join(w for w in _qnorm(t).split() if w not in ("sa", "ng"))


def spec_entries(t):
    """The teacher's specialization as a list of entries. The old free-text Subject is only used while
    the specialization is empty."""
    raw = (t["specialization"] or "").strip() or (t["subject_area"] or "")
    return [x.strip() for x in re.split(r"[;\n]+", raw) if x.strip()]


def teacher_subjects_list(t):
    """The subjects saved for one teacher in Teacher Management, de-duplicated, in the order entered."""
    seen, out = set(), []
    for e in spec_entries(t):
        k = _qnorm(e)
        if k and k not in seen:
            seen.add(k)
            out.append(e)
    return out


def teacher_has_subject(entries, sub):
    """True when one of the teacher's specialization entries names this subject (or, for a cluster, one of
    its electives), or a core subject code is written in it. Tolerant of case, punctuation, accents,
    a missing '(...)' note and the sa / ng spelling."""
    name = (sub["name"] or "").strip()
    n_full, n_core = _qnorm(name), _qcore(name)
    ents = [(_qnorm(e), _qcore(e)) for e in entries]
    if n_full and any(f == n_full or (c and c == n_core) for f, c in ents):
        return True
    blob = " " + " ".join(f for f, _c in ents) + " "      # entries typed with commas / slashes / "and" still count
    if len(n_full.split()) >= 2 and (" " + n_full + " ") in blob:
        return True
    if (sub["kind"] or "") == "cluster":
        for el in CLUSTER_SPECS.get(name, []):
            ef, ec = _qnorm(el), _qcore(el)
            if any(f == ef or (c and c == ec) for f, c in ents):
                return True
    if (sub["kind"] or "") == "core":
        text = " ".join(f for f, _c in ents)
        for tok in re.split(r"[/\s]+", (sub["code"] or "").lower()):
            if len(tok) >= 2 and re.search(r"(?<![a-z0-9])" + re.escape(tok) + r"(?![a-z0-9])", text):
                return True
    return False


def qualified_pairs():
    """Every (teacher_id, subject_id) the teacher is qualified for: saved qualifications plus the ones that follow
    from the specialization. Read-only, so page views never write to the database."""
    pairs = {(r["user_id"], r["subject_id"]) for r in query("SELECT user_id, subject_id FROM teacher_subjects")}
    subs = query("SELECT * FROM subjects")
    for t in query("SELECT * FROM users WHERE role='teacher'"):
        entries = spec_entries(t)
        if entries:
            pairs |= {(t["id"], s["id"]) for s in subs if teacher_has_subject(entries, s)}
    return pairs


def match_quals(uid=None):
    """A teacher is qualified for a subject when the subject (or, for a cluster, one of its electives) is in
    the teacher's specialization. Only adds qualifications: the ones set by hand in Teacher Loading stay."""
    n = 0
    subs = query("SELECT * FROM subjects")
    have = {(r["user_id"], r["subject_id"]) for r in query("SELECT * FROM teacher_subjects")}
    for t in query("SELECT * FROM users WHERE role='teacher'"):
        if uid and t["id"] != uid:
            continue
        entries = spec_entries(t)
        if not entries:
            continue
        for s in subs:
            if teacher_has_subject(entries, s) and (t["id"], s["id"]) not in have:
                run("INSERT INTO teacher_subjects(user_id,subject_id) VALUES(?,?)", (t["id"], s["id"]))
                have.add((t["id"], s["id"]))
                n += 1
    return n


def drop_removed_quals(tid, old_spec):
    """After a specialization edit: a subject the teacher no longer lists loses its qualification, its teaching
    load and its class periods, and the affected programs are marked out of date. Qualifications for subjects that
    were never in the specialization (set by hand in Teacher Loading) are left alone. Returns the sections affected."""
    t = query("SELECT * FROM users WHERE id=?", (tid,), one=True)
    if not t:
        return []
    new_e, old_e = spec_entries(t), spec_entries(dict(t, specialization=old_spec or ""))
    hit = set()
    for s in query("SELECT * FROM subjects"):
        if teacher_has_subject(old_e, s) and not teacher_has_subject(new_e, s):
            run("DELETE FROM teacher_subjects WHERE user_id=? AND subject_id=?", (tid, s["id"]))
            for r in query("SELECT section_id FROM loads WHERE teacher_id=? AND subject_id=?", (tid, s["id"])):
                hit.add(r["section_id"])
            run("UPDATE loads SET teacher_id=NULL WHERE teacher_id=? AND subject_id=?", (tid, s["id"]))
            for r in query("SELECT DISTINCT section_id FROM classes WHERE teacher_id=? AND kind='class' AND subject=?",
                           (tid, s["name"])):
                hit.add(r["section_id"])
            run("UPDATE classes SET teacher_id=NULL WHERE teacher_id=? AND kind='class' AND subject=?", (tid, s["name"]))
    if hit:
        mark_stale(sorted(hit))
        touch("teacher", tid)
    return sorted(hit)


def why_no_teacher(sec, sub):
    """Plain-language reason a subject of a section has no teacher, so a teacher who HAS the specialization
    is not reported as 'no teacher'."""
    tt = get_tt()
    ids = [r["user_id"] for r in query("SELECT user_id FROM teacher_subjects WHERE subject_id=?", (sub["id"],))]
    names = {t["id"]: dict(t) for t in query("SELECT * FROM users WHERE role='teacher'")}
    qual = [names[i] for i in ids if i in names]
    if not qual:
        return (f"No teacher has {sub['name']} in their specialization. "
                "Add it to a teacher's specialization in Teacher Management.")
    shift = sec_shift(sec, tt)
    per = tt[shift]
    span = (per[0][0], per[-1][1])
    in_shift = [t for t in qual if max(0, min(span[1], teacher_window(t)[1]) - max(span[0], teacher_window(t)[0])) > 0]
    who = ", ".join(t["full_name"] for t in qual[:3]) + (" and others" if len(qual) > 3 else "")
    if not in_shift:
        return (f"{who} {'is' if len(qual) == 1 else 'are'} qualified, but the official time "
                f"{'does' if len(qual) == 1 else 'do'} not cover the {shift} shift of {sec['name']} "
                f"({t12(hhmm(span[0]))} to {t12(hhmm(span[1]))}). Change the teacher type or official time in Teacher Management.")
    return (f"{', '.join(t['full_name'] for t in in_shift[:3])} {'is' if len(in_shift) == 1 else 'are'} qualified "
            f"for {shift} shift but already at the weekly limit or already teaching an elective in that shift. "
            "Add another teacher with this specialization or choose one by hand in Teacher Loading.")


def teacher_minutes_assigned():
    out = defaultdict(int)
    for r in query("""SELECT l.teacher_id, b.weekly_min FROM loads l JOIN subjects b ON b.id=l.subject_id
                      JOIN section_subjects ss ON ss.section_id=l.section_id AND ss.subject_id=l.subject_id
                      WHERE l.teacher_id IS NOT NULL"""):
        out[r["teacher_id"]] += r["weekly_min"]
    return out


def _why_class(has_quals, why):
    if not has_quals:
        return "Incompatible specialization"
    kinds = {k for k, _t in why}
    if kinds == {"availability"}:
        return "Teacher unavailable"
    if kinds == {"workload"}:
        return "Workload limit"
    return "Teacher unavailable and workload limit"


def autofill(overwrite=False, jitter=0, report=None):
    """Attach every eligible subject to sections that have none, then give each unassigned
    subject the best qualified teacher (shift fit, then lightest load)."""
    match_quals()   # a specialization chosen anywhere always counts, even if it was never matched before
    tt = get_tt()
    subs = [dict(s) for s in query("SELECT * FROM subjects")]
    secs = [dict(s) for s in sched_secs()]
    added = 0
    for sec in secs:
        before = query("SELECT COUNT(*) AS n FROM section_subjects WHERE section_id=?", (sec["id"],), one=True)["n"]
        sync_section_subjects(sec["id"])
        now = query("SELECT COUNT(*) AS n FROM section_subjects WHERE section_id=?", (sec["id"],), one=True)["n"]
        added += now - before
        if not now and report is not None:
            report.append(dict(section=sec["name"], subject="(all subjects)", cause="Section has no subjects",
                               reason="No subject matches this section's grade level, track or elective. Set the track and elective in Section Management."))
    teachers = {t["id"]: dict(t) for t in query("SELECT * FROM users WHERE role='teacher'")}
    quals = defaultdict(set)
    for r in query("SELECT * FROM teacher_subjects"):
        quals[r["subject_id"]].add(r["user_id"])
    load = teacher_minutes_assigned()
    maxday = to_int(gset("max_teach_day", "360"), 60, 720) or 360
    cap = maxday * len(DAYS)
    secd0 = {s["id"]: s for s in secs}
    subd0 = {s["id"]: s for s in subs}
    shift_load = defaultdict(int)
    for r in query("SELECT section_id, subject_id, teacher_id FROM loads WHERE teacher_id IS NOT NULL"):
        if r["section_id"] in secd0 and r["subject_id"] in subd0:
            shift_load[(r["teacher_id"], sec_shift(secd0[r["section_id"]], tt))] += subd0[r["subject_id"]]["weekly_min"]
    todo = []
    for r in query("SELECT ss.section_id, ss.subject_id FROM section_subjects ss"):
        cur = query("SELECT teacher_id FROM loads WHERE section_id=? AND subject_id=?",
                    (r["section_id"], r["subject_id"]), one=True)
        if overwrite or not cur or not cur["teacher_id"]:
            todo.append((r["section_id"], r["subject_id"]))
    secd = {s["id"]: s for s in secs}
    subd = {s["id"]: s for s in subs}
    todo.sort(key=lambda x: len(quals[x[1]]))
    given = 0
    if overwrite:  # start again from nothing
        load = defaultdict(int)
        shift_load = defaultdict(int)
    secs_of = defaultdict(set)  # sections each teacher already teaches (for the "sections they teach" limit)
    if not overwrite:
        for r in query("SELECT section_id, teacher_id FROM loads WHERE teacher_id IS NOT NULL"):
            if r["section_id"] in secd0:
                secs_of[r["teacher_id"]].add(r["section_id"])
    core_load = defaultdict(int)  # minutes of core subjects per teacher
    for r in ([] if overwrite else query("""SELECT l.teacher_id, b.weekly_min FROM loads l JOIN subjects b ON b.id=l.subject_id
                      WHERE l.teacher_id IS NOT NULL AND b.kind='core'""")):
        core_load[r["teacher_id"]] += r["weekly_min"]
    elective_taken = set()  # (teacher, shift): electives of a shift all run at the same time
    for r in ([] if overwrite else query("""SELECT l.section_id, l.teacher_id FROM loads l JOIN subjects b ON b.id=l.subject_id
                      WHERE l.teacher_id IS NOT NULL AND b.kind='cluster'""")):
        if r["section_id"] in secd0:
            elective_taken.add((r["teacher_id"], sec_shift(secd0[r["section_id"]], tt)))
    for sid, bid in todo:
        sec, sub = secd.get(sid), subd.get(bid)
        if not sec or not sub:
            continue
        shift = sec_shift(sec, tt)
        per = tt[shift]
        span = (per[0][0], per[-1][1])
        best = None
        why = []   # (kind, text) for every qualified teacher who could not take this subject
        for tid in quals[bid]:
            t = teachers.get(tid)
            if not t:
                continue
            tn = t["full_name"]
            if load[tid] + sub["weekly_min"] > cap:
                why.append(("workload", f"{tn} is at the weekly teaching limit ({load[tid] / 60:.1f} of {cap / 60:.1f} hours)"))
                continue
            lim = t.get("max_sections") or 0
            if lim and sid not in secs_of[tid] and len(secs_of[tid]) >= lim:
                why.append(("workload", f"{tn} already teaches the {lim} section(s) set as their limit"))
                continue  # this teacher already teaches the number of sections set for them
            w = teacher_window(t)
            fit = max(0, min(span[1], w[1]) - max(span[0], w[0])) / max(1, span[1] - span[0])
            usable = sum(max(0, min(e, w[1]) - max(s, w[0])) for s, e, k in per if k == "class")
            if fit == 0:
                why.append(("availability", f"{tn}'s official time does not cover the {shift} shift"))
                continue
            if shift_load[(tid, shift)] + sub["weekly_min"] > min(usable, maxday) * len(DAYS):
                why.append(("workload", f"{tn} has no teaching time left in the {shift} shift"))
                continue
            if (sub["kind"] or "") == "cluster" and (tid, shift) in elective_taken:
                why.append(("availability", f"{tn} already teaches another elective at the same time in the {shift} shift"))
                continue
            if (sub["kind"] or "") != "cluster":
                core_cap = max(0, sum(1 for x in per if x[2] == "class") - 2) * 60 * len(DAYS)
                if core_load[tid] + sub["weekly_min"] > core_cap:
                    why.append(("workload", f"{tn} reached the limit for core subjects in the {shift} shift"))
                    continue
            score = (1 - fit) * 1000 + load[tid] + random.random() * jitter + (150 if GRADES.get(t["category"]) and sec["grade"] not in GRADES[t["category"]] else 0)
            if best is None or score < best[0]:
                best = (score, tid)
        if not best and report is not None:
            has_q = any(x in teachers for x in quals[bid])
            txt = ("No teacher has " + sub["name"] + " in their specialization. Add it to a teacher in Teacher Management."
                   if not has_q else "; ".join(x[1] for x in why[:3]) + (f"; and {len(why) - 3} more" if len(why) > 3 else ""))
            report.append(dict(section=sec["name"], subject=sub["name"], cause=_why_class(has_q, why), reason=txt))
        if best:
            run("INSERT OR REPLACE INTO loads(section_id,subject_id,teacher_id) VALUES(?,?,?)", (sid, bid, best[1]))
            load[best[1]] += sub["weekly_min"]
            secs_of[best[1]].add(sid)
            shift_load[(best[1], shift)] += sub["weekly_min"]
            if (sub["kind"] or "") == "cluster":
                elective_taken.add((best[1], shift))
            else:
                core_load[best[1]] += sub["weekly_min"]
            given += 1
    return added, given, len(todo) - given


def quick_setup():
    parts = []
    n = load_starter_subjects()
    if n:
        parts.append(f"{n} subjects restored")
    miss = missing_room_types()
    if miss:
        parts.append("no registered room for: " + ", ".join(miss) + " (register them in Quick Input)")
    q = match_quals()
    a, gv, left = autofill()
    parts.append(f"{q} teacher qualifications matched, {a} section subjects added, {gv} teachers assigned"
                 + (f", {left} left without a teacher (no qualified teacher has enough time in that shift)" if left else ""))
    return "Quick setup finished: " + "; ".join(parts) + "."


# ------------------------------------------------------------------ routes
@app.route("/admin/curriculum")
def auto_subjects():
    """The old address of Subject Management."""
    return redirect(url_for("curriculum"), 301)


GRADE_ACCESS = ("Both", "11", "12")


def _is_classroom(r):
    return (r["rtype"] or "Regular").strip().lower() in ("regular", "regular classroom", "classroom")


def _grade_ok(acc, grade):
    acc = str(acc or "Both").strip()
    return acc.lower() in ("both", "all", "") or str(grade) in acc


def room_options(sid, grade, detail=False):
    """Registered classrooms that section `sid` (None for a new section) can use as its home room at `grade`.
    detail=False: only the free ones. detail=True: every registered classroom with free=True/False and the reason
    when it is not free (other grade level, or the home room the administrator already gave to another section in
    the same shift), so the list is never empty while rooms exist. Rooms are assigned by hand, never by the system."""
    shift = "AM" if grade == 11 else "PM"
    taken = {}
    for o in query("SELECT name, room, shift, grade FROM sections WHERE COALESCE(room,'')!='' AND id!=?", (sid or 0,)):
        sh = o["shift"] or ("AM" if o["grade"] == 11 else "PM")
        taken.setdefault(o["room"].strip().lower(), {})[sh] = o["name"]
    out = []
    for r in sorted(query("SELECT * FROM rooms"), key=lambda r: natkey(r["name"])):
        if not _is_classroom(r):
            continue
        why = ""
        if not _grade_ok(r["grade_access"], grade):
            why = f"Grade {r['grade_access']} only"
        elif taken.get(r["name"].strip().lower(), {}).get(shift):
            why = f"home room of {taken[r['name'].strip().lower()][shift]}"
        label = r["name"] + (f" (Bldg. {r['building']}" + (f", Floor {r['floor']}" if r["floor"] else "") + ")" if r["building"] else "")
        out.append(dict(name=r["name"], label=label, free=not why, why=why))
    return out if detail else [x for x in out if x["free"]]


def room_error(room, grade, sid):
    """Why `room` cannot be the home room of section `sid` at `grade`, or None when it can (or none is chosen)."""
    if not room:
        return None
    r = query("SELECT * FROM rooms WHERE lower(name)=lower(?)", (room,), one=True)
    if not r:
        return f"{room} is not a registered room. Register it in Quick Input first."
    if not _is_classroom(r):
        return f"{r['name']} is a {r['rtype']}, not a classroom. Choose a regular classroom."
    if not _grade_ok(r["grade_access"], grade):
        return f"{r['name']} can only be used by Grade {r['grade_access']} sections."
    if r["name"] not in [x["name"] for x in room_options(sid, grade)]:
        return f"{r['name']} is already the home room of another section in the same shift."
    return None


def room_update(rid, name, rtype, access, building, floor):
    """Edit one registered room (Room Management and Quick Input). Returns (ok, message)."""
    room = query("SELECT * FROM rooms WHERE id=?", (rid,), one=True) if rid else None
    if not room:
        return False, "That room no longer exists."
    name = clean(name, 60)
    if not name:
        return False, "Enter the room name."
    if rtype not in set(rtype_options()):
        return False, "Choose a room type from the list."
    if access not in GRADE_ACCESS:
        return False, "Choose which grade level can use the room."
    if (building and building not in BUILDINGS) or (floor and floor not in FLOORS):
        return False, "Choose the building and floor from the lists."
    if query("SELECT 1 FROM rooms WHERE lower(name)=lower(?) AND id!=?", (name, rid), one=True):
        return False, f"{name} is already registered."
    if access != "Both":
        other = 12 if access == "11" else 11
        users = [x["name"] for x in query("SELECT name FROM sections WHERE lower(room)=lower(?) AND grade=?", (room["name"], other))]
        if users:
            return False, (f"Grade {other} sections use this room ({', '.join(users[:3])}{'...' if len(users) > 3 else ''}). "
                           "Give them another room first.")
    try:
        run("UPDATE rooms SET name=?, rtype=?, grade_access=?, building=?, floor=? WHERE id=?",
            (name, rtype, access, building or None, floor or None, rid))
    except IntegrityError:
        return False, f"{name} is already registered."
    if name != room["name"]:                           # keep section home rooms and booked periods in step
        run("UPDATE sections SET room=? WHERE lower(room)=lower(?)", (name, room["name"]))
        run("UPDATE classes SET room=? WHERE room_id=?", (name, rid))
    return True, f"{name} was updated."


def natkey(text):
    """Natural order: Room 2 comes before Room 10, 101 before 309."""
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", str(text or ""))]


def rooms_page(rf=None, rf_err=None, tf=None, tf_err=None):
    tt = get_tt()
    cap = sum(e - s for per in tt.values() for s, e, k in per if k == "class") * len(DAYS)
    used = {r["room_id"]: r["m"] for r in query(
        "SELECT room_id, SUM(" + MIN_SQL + ") AS m "
        "FROM classes WHERE kind='class' AND room_id IS NOT NULL GROUP BY room_id")}
    page = render_template("auto_rooms.html", rows=sorted(query("SELECT * FROM rooms"), key=lambda r: natkey(r["name"])),
                           rtypes=rtype_options(), used=used, cap=cap or 1, rf=rf, rf_err=rf_err,
                           types=room_type_rows(), tf=tf, tf_err=tf_err)
    return (page, 400) if (rf_err or tf_err) else page


@app.route("/admin/rooms", methods=["GET", "POST"])
@login_required("admin")
def auto_rooms():
    if request.method == "POST":
        f = request.form
        act = f.get("action")
        if act == "add":                             # rooms are registered in Quick Input
            flash("Rooms are added in Quick Input.", "error")
            return redirect(url_for("quick_input", tab="rooms") + "#rooms")
        if act == "delete":
            rid = f.get("rid", type=int)
            room = query("SELECT * FROM rooms WHERE id=?", (rid,), one=True) if rid else None
            if not room:
                flash("Choose the room you want to delete.", "error")
            else:
                run("UPDATE classes SET room=NULL, room_id=NULL WHERE room_id=?", (rid,))
                run("UPDATE sections SET room='', building=NULL, floor=NULL WHERE lower(room)=lower(?)", (room["name"],))
                run("DELETE FROM rooms WHERE id=?", (rid,))
                flash(f"{room['name']} was deleted.", "ok")
        elif act == "type_save":                     # add or edit a room type (the facilities a room can have)
            tid = f.get("tid", type=int)
            vals = dict(tid=tid or "", name=clean(f.get("name"), RT_NAME_MAX), facilities=clean(f.get("facilities"), 200),
                        _mode="edit" if tid else "new", _title="Edit room type" if tid else "Add room type", _lock=[], _note="")
            if tid:
                ok, msg = room_type_update(tid, vals["name"], vals["facilities"])
            else:
                ok, msg, _n = room_type_add(vals["name"], vals["facilities"])
            if not ok:
                return rooms_page(tf=vals, tf_err=msg)
            flash(msg, "ok")
            return redirect(url_for("auto_rooms") + "#types")
        elif act == "type_delete":
            ok, msg = room_type_remove(f.get("tid", type=int))
            flash(msg, "ok" if ok else "error")
            return redirect(url_for("auto_rooms") + "#types")
        elif act == "edit":
            rid = f.get("rid", type=int)
            vals = dict(rid=rid, name=clean(f.get("name"), 60), rtype=f.get("rtype", ""), grade_access=f.get("grade_access", "Both"),
                        building=f.get("building", ""), floor=f.get("floor", ""))
            ok, msg = room_update(rid, vals["name"], vals["rtype"], vals["grade_access"], vals["building"], vals["floor"])
            if not ok:
                return rooms_page(rf=vals, rf_err=msg)
            flash(msg, "ok")
        else:
            flash("Nothing was changed.", "error")
        return redirect(url_for("auto_rooms"))
    return rooms_page()


@app.route("/admin/rooms/<int:rid>")
@login_required("admin")
def auto_room(rid):
    room = query("SELECT * FROM rooms WHERE id=?", (rid,), one=True)
    if not room:
        abort(404)
    rows = [dict(r) for r in query(
        """SELECT c.*, s.name AS sname, u.full_name AS tname FROM classes c JOIN sections s ON s.id=c.section_id
           LEFT JOIN users u ON u.id=c.teacher_id WHERE c.room_id=? AND c.kind='class'""", (rid,))]
    rows.sort(key=lambda r: (DAYS.index(r["day"]), r["start"]))
    return render_template("auto_room.html", room=room, rows=rows)


@app.route("/admin/qualifications", methods=["GET", "POST"])
@login_required("admin")
def auto_quals():
    teachers_ = query("SELECT * FROM users WHERE role='teacher' ORDER BY id")
    subs = query("SELECT * FROM subjects ORDER BY grade, name")
    if request.method == "POST":
        if request.form.get("action") == "match":
            flash(f"{match_quals()} new qualifications were matched from the teachers' specialization text.", "ok")
        else:
            run("DELETE FROM teacher_subjects")
            for t in teachers_:
                for s in subs:
                    if request.form.get(f"q_{t['id']}_{s['id']}"):
                        run("INSERT INTO teacher_subjects(user_id,subject_id) VALUES(?,?)", (t["id"], s["id"]))
            flash("Qualifications saved.", "ok")
        return redirect(url_for("auto_quals"))
    have = {(r["user_id"], r["subject_id"]) for r in query("SELECT * FROM teacher_subjects")}
    buckets = {"Academic": [], "Core": [], "TechPro": [], "Other": []}
    for sub in subs:
        if (sub["kind"] or "") == "core":
            buckets["Core"].append(sub)
        elif (sub["track"] or "") in ("Academic", "TechPro"):
            buckets[sub["track"]].append(sub)
        else:
            buckets["Other"].append(sub)
    groups = [(k, sorted(v, key=lambda x: (x["name"] or "").lower())) for k, v in buckets.items() if v]
    have = qualified_pairs()    # saved qualifications plus the ones that follow from the specialization
    sub_count = defaultdict(int)     # subject id -> teachers qualified for it
    for _uid, _sid in have:
        sub_count[_sid] += 1
    cat_total = {}                   # category -> teachers qualified in at least one subject of it
    for cat, items in groups:
        ids = {x["id"] for x in items}
        cat_total[cat] = len({u for u, sid in have if sid in ids})
    return render_template("auto_quals.html", teachers_=teachers_, subs=subs, have=have, groups=groups,
                           sub_count=sub_count, cat_total=cat_total)


@app.route("/admin/loading", methods=["GET", "POST"])
@login_required("admin")
def auto_loading():
    secs = sched_secs()
    if request.method == "POST":
        f = request.form
        if f.get("action") == "autofill":
            snap = lambda: {(r["section_id"], r["subject_id"]): r["teacher_id"] for r in query("SELECT * FROM loads")}
            before_all = snap()
            rep_items = []
            try:
                a, gv, left = autofill(overwrite=bool(f.get("overwrite")), report=rep_items)
            except Exception:
                app.logger.exception("auto-assign failed")
                flash("The automatic assignment could not finish. Nothing was lost; please try again.", "error")
                return redirect(url_for("auto_loading"))
            after_all = snap()
            changed = {k[0] for k in set(after_all.items()) ^ set(before_all.items())}
            built = {r["section_id"] for r in query("SELECT DISTINCT section_id FROM classes WHERE kind='class'")}
            if changed & built:
                mark_stale(sorted(changed & built))            # class programs of those sections are now out of date
            sset("last_assign", json.dumps(dict(when=ph_stamp(), added=a, given=gv, left=len(rep_items), sections=len(secs),
                                                replaced=bool(f.get("overwrite")), items=rep_items[:400])))
            flash(f"Assigned {gv} subject(s) to qualified teachers across {len(secs)} section(s)."
                  + (f" {len(rep_items)} could not be assigned. See the report below." if rep_items else " Every subject has a teacher."),
                  "ok" if not rep_items else "error")
            return redirect(url_for("auto_loading") + "#assignreport")
        sid = f.get("section_id", type=int)
        sec = query("SELECT * FROM sections WHERE id=?", (sid,), one=True)
        if not sec:
            abort(404)
        before = {(r["subject_id"], r["teacher_id"]) for r in query("SELECT subject_id, teacher_id FROM loads WHERE section_id=?", (sid,))}
        run("DELETE FROM section_subjects WHERE section_id=?", (sid,))
        run("DELETE FROM loads WHERE section_id=?", (sid,))
        warn = 0
        for s in query("SELECT * FROM subjects"):
            if f.get(f"take_{s['id']}") or ((s["kind"] or "") == "core" and eligible(s, sec)):
                run("INSERT INTO section_subjects(section_id,subject_id) VALUES(?,?)", (sid, s["id"]))
                tid = f.get(f"teacher_{s['id']}", type=int)
                if tid and query("SELECT 1 FROM users WHERE id=? AND role='teacher'", (tid,), one=True):
                    run("INSERT INTO loads(section_id,subject_id,teacher_id) VALUES(?,?,?)", (sid, s["id"], tid))
                    if not query("SELECT 1 FROM teacher_subjects WHERE user_id=? AND subject_id=?", (tid, s["id"]), one=True):
                        warn += 1
        after = {(r["subject_id"], r["teacher_id"]) for r in query("SELECT subject_id, teacher_id FROM loads WHERE section_id=?", (sid,))}
        if before != after and query("SELECT 1 FROM classes WHERE section_id=? AND kind='class'", (sid,), one=True):
            mark_stale([sid])
        flash(f"Loading saved for {sec['name']}." + (f" {warn} teacher(s) are not listed as qualified." if warn else ""),
              "ok" if not warn else "error")
        return redirect(url_for("auto_loading", section=sid))
    cur = next((s for s in secs if str(s["id"]) == request.args.get("section", "")), secs[0] if secs else None)
    rows, tt = [], get_tt()
    teachers_ = query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name")
    assigned = teacher_minutes_assigned()
    if cur:
        take = {r["subject_id"] for r in query("SELECT subject_id FROM section_subjects WHERE section_id=?", (cur["id"],))}
        load = {r["subject_id"]: r["teacher_id"] for r in query("SELECT * FROM loads WHERE section_id=?", (cur["id"],))}
        qs = defaultdict(set)
        for uid_, sid_ in qualified_pairs():
            qs[sid_].add(uid_)
        for s in query("SELECT * FROM subjects ORDER BY name"):
            if eligible(s, cur) or s["id"] in take:
                opts = sorted(teachers_, key=lambda t: (t["id"] not in qs[s["id"]], t["full_name"]))
                rows.append(dict(s=s, taken=s["id"] in take, tid=load.get(s["id"]), opts=opts, q=qs[s["id"]]))
    summ = []
    try:
        la = json.loads(gset("last_assign", "") or "null")
    except ValueError:
        la = None
    if isinstance(la, dict):
        # Never read the saved report through la.items in the template: on a dict that is the built-in items() method.
        items = la.get("items")
        la["unassigned"] = [u for u in items if isinstance(u, dict)] if isinstance(items, list) else []
    else:
        la = None                                     # an older or damaged saved report: show none instead of failing
    return render_template("auto_loading.html", la=la, secs=secs, cur=cur, rows=rows,
                           cur_shift=sec_shift(dict(cur), tt) if cur else "", summ=summ, lv=validate_loading())


# ======================================================================================
# TWO-BUTTON SCHEDULING: VALIDATE ALL REQUIREMENTS, THEN GENERATE ALL CLASS PROGRAMS AND ASSIGN TEACHERS
# ======================================================================================
GEN_LOCK_KEY = 20260202


class GenerationBlocked(Exception):
    """Generation stopped on purpose; everything done so far is rolled back."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or []


def validation_fingerprint():
    """A short code of every record the scheduler reads. If anything changes after validation, the code
    changes and the Generate button locks again until the system is validated again."""
    import hashlib
    parts = []
    for sql in ("SELECT id,name,grade,track,room,cluster,shift FROM sections ORDER BY id",
                "SELECT section_id,subject_id FROM section_subjects ORDER BY 1,2",
                "SELECT id,specialization,official_time,category,teaching_load,max_sections,intervention_min,"
                "ancillary_min FROM users WHERE role='teacher' ORDER BY id",
                "SELECT user_id,subject_id FROM teacher_subjects ORDER BY 1,2",
                "SELECT id,name,rtype,grade_access FROM rooms ORDER BY id",
                "SELECT id,weekly_min,rtype,offered,kind FROM subjects ORDER BY id",
                "SELECT k,v FROM settings WHERE k IN ('tt_text','max_teach_day','max_teach_week','turnover') ORDER BY k"):
        parts.append(json.dumps([[str(v) for v in tuple(r)] for r in query(sql)]))
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def validate_all():
    """Read-only inspection of everything the generator needs. It never writes to the database.
    Returns the counts, every error (with module, place, problem and how to fix it) and the warnings."""
    tt, maxweek = get_tt(), weekly_limit()
    secs = [dict(s) for s in sched_secs()]
    subs = {s["id"]: dict(s) for s in query("SELECT * FROM subjects")}
    teachers = [dict(t) for t in query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name")]
    tids = {t["id"] for t in teachers}
    rooms = [dict(r) for r in query("SELECT * FROM rooms ORDER BY name")]
    have = defaultdict(set)
    for r in query("SELECT section_id, subject_id FROM section_subjects"):
        have[r["section_id"]].add(r["subject_id"])
    manual = defaultdict(set)
    for r in query("SELECT user_id, subject_id FROM teacher_subjects"):
        manual[r["subject_id"]].add(r["user_id"])
    entries = {t["id"]: spec_entries(t) for t in teachers}
    errors, warns = [], []

    def err(module, ep, where, problem, fix):
        errors.append(dict(module=module, ep=ep, where=where, problem=problem, fix=fix))

    def warn(module, ep, where, problem, fix):
        warns.append(dict(module=module, ep=ep, where=where, problem=problem, fix=fix))

    def qualified(sub):
        return {t["id"] for t in teachers if entries[t["id"]] and teacher_has_subject(entries[t["id"]], sub)} \
            | (manual[sub["id"]] & tids)

    def in_shift(t, shift):
        per = tt[shift]
        a, b = teacher_window(t)
        return max(0, min(per[-1][1], b) - max(per[0][0], a)) > 0

    tmap = {t["id"]: t for t in teachers}
    if not secs:
        err("Section Management", "quick_input", "Sections", "No sections are registered.",
            "Add the sections in Quick Input > Sections.")
    if not teachers:
        err("Teacher Management", "teachers", "Teachers", "No teachers are registered.",
            "Add the teachers and their specialized subjects in Quick Input > Teachers.")
    if not rooms:
        warn("Room Management", "auto_rooms", "Rooms", "No rooms are registered.",
             "Optional unless a subject needs a laboratory or workshop. Register rooms in Quick Input > Rooms.")
    for t in teachers:
        if not entries[t["id"]]:
            warn("Teacher Management", "teachers", t["full_name"],
                 "No specialized subjects, so this teacher will not be given any class.",
                 "Open the teacher and add the subjects they can teach.")

    # ---- sections: core subjects, electives, home rooms
    room_by_name = {_qnorm(r["name"]): r for r in rooms}
    room_shift = defaultdict(list)
    need_by_sub = defaultdict(list)
    required = 0
    for sec in secs:
        shift = sec_shift(sec, tt)
        mine = have[sec["id"]]
        expected = {i for i, s in subs.items() if eligible(s, sec)}
        if not mine:
            err("Section Management", "sections", sec["name"], "The section has no subjects.",
                "Edit the section, choose its track and elective cluster, and save it.")
            continue
        miss = sorted(subs[i]["name"] for i in expected - mine)
        if miss:
            err("Section Management", "sections", sec["name"],
                "Required subject(s) missing: " + ", ".join(miss) + ".",
                "Edit the section and save it again so its core subjects and elective are rebuilt.")
        extra = sorted(subs[i]["name"] for i in mine - expected if i in subs)
        if extra:
            err("Section Management", "sections", sec["name"],
                "Subject(s) that do not belong to this grade, track or cluster: " + ", ".join(extra) + ".",
                "Edit the section and save it again to remove them.")
        if not any((subs[i]["kind"] or "") == "cluster" for i in mine if i in subs):
            chosen = next((x for x in subs.values() if (x["kind"] or "") == "cluster" and x["name"] == (sec["cluster"] or "")), None)
            if chosen is not None and subj_status(chosen) != "active":
                err("Subject Management", "curriculum", sec["name"],
                    f"The elective '{chosen['name']}' chosen for this section is {subj_status(chosen)}, so it is not scheduled.",
                    "Choose another elective for the section in Section Management, or set the subject to Active again.")
            else:
                err("Section Management", "sections", sec["name"], "No elective cluster is selected.",
                    "Edit the section and choose its elective cluster.")
        for i in mine & set(subs):
            need_by_sub[i].append(sec)
            required += 1
        per = tt[shift]
        cpl = [(a, b) for a, b, k in per if k == "class"]
        week = sum(b - a for a, b in cpl) * 5 - (sum(b - a for a, b in cpl[-2:]) if len(cpl) >= 3 else 0)
        need = sum(subs[i]["weekly_min"] for i in mine if i in subs)
        if need > week:
            err("System Settings", "settings", sec["name"],
                f"The subjects need {need} minutes a week but the {shift} shift only has {week} minutes of class time.",
                "Lengthen the timetable in System Settings or reduce the subject minutes in Subject Management.")
        room = room_by_name.get(_qnorm(sec["room"]))
        if not (sec["room"] or "").strip():
            warn("Section Management", "sections", sec["name"],
                 "No home room is chosen, so its regular classes are placed without a room.",
                 "Optional: choose a home room in Section Management.")
        elif not room:
            err("Section Management", "sections", sec["name"],
                f"Home room '{sec['room']}' is not a registered room.",
                "Register the room in Quick Input > Rooms, or choose another room for the section.")
        else:
            ga = (room["grade_access"] or "Both")
            if ga not in ("Both", str(sec["grade"])):
                warn("Room Management", "auto_rooms", room["name"],
                    f"{room['name']} is for Grade {ga} only but is the home room of {sec['name']} (Grade {sec['grade']}).",
                    "Change the room's grade level or choose another room for the section.")
            room_shift[(room["id"], shift)].append(sec["name"])
    for (rid, shift), names in room_shift.items():
        if len(names) > 1:
            err("Room Management", "auto_rooms", next(r["name"] for r in rooms if r["id"] == rid),
                f"Used as the home room of {', '.join(names)} in the same {shift} shift.",
                "Give each section in the same shift its own room.")

    # ---- teachers: qualified, available, enough hours
    pairs, hours_all = set(), 0
    for sid_, lst in need_by_sub.items():
        sub = subs[sid_]
        q = qualified(sub)
        names = ", ".join(s["name"] for s in lst[:4]) + (" and others" if len(lst) > 4 else "")
        if not q:
            err("Teacher Management", "teachers", sub["name"],
                f"No teacher has {sub['name']} in their specialization (needed by {names}).",
                "Add this subject to a teacher's specialization in Teacher Management.")
            continue
        pairs |= {(t, sid_) for t in q}
        for shift in sorted({sec_shift(s, tt) for s in lst}):
            ok_t = [t for t in q if in_shift(tmap[t], shift)]
            where = [s["name"] for s in lst if sec_shift(s, tt) == shift]
            if not ok_t:
                err("Teacher Management", "teachers", sub["name"],
                    f"Qualified teacher(s) exist, but none is on duty during the {shift} shift of {', '.join(where[:3])}.",
                    "Change a qualified teacher's official time, or add a teacher for that shift.")
            else:
                cpl = [(a, b) for a, b, k in tt[shift] if k == "class"]
                if (sub["kind"] or "") == "cluster" and len(cpl) >= 2:     # elective = the last two class periods
                    blk = (cpl[-2][0], cpl[-1][1])
                    if not any(teacher_window(tmap[t])[0] <= blk[0] and blk[1] <= teacher_window(tmap[t])[1] for t in ok_t):
                        err("Teacher Management", "teachers", sub["name"],
                            f"The elective is taught {t12(hhmm(blk[0]))} to {t12(hhmm(blk[1]))} in the {shift} shift, but no "
                            f"qualified teacher's official time covers that whole block.",
                            "Change a qualified teacher's official time, or add a teacher whose hours cover it.")
                        continue
                req = sum(sub["weekly_min"] for s in lst if sec_shift(s, tt) == shift)

                def usable(t):                    # class minutes a week that fall fully inside the teacher's hours
                    wa, wb = teacher_window(tmap[t])
                    return sum(b - a for a, b in cpl if a >= wa and b <= wb) * 5
                cap = sum(min(maxweek, usable(t)) for t in ok_t)
                if req > cap:
                    err("Teacher Management", "teachers", sub["name"],
                        f"{sub['name']} needs {req} minutes a week in the {shift} shift but its qualified teachers can "
                        f"only give {cap} minutes (weekly limit {maxweek} minutes each).",
                        "Add another teacher with this subject or raise the weekly limit in System Settings.")
        hours_all += sum(subs[sid_]["weekly_min"] for _ in lst)
    cap_all = sum(maxweek for t in teachers if entries[t["id"]])
    if hours_all > cap_all and teachers:
        err("Teacher Management", "teachers", "All teachers",
            f"All sections need {hours_all} teaching minutes a week but the teachers with subjects can give {cap_all}.",
            "Add teachers or raise the weekly teaching limit in System Settings.")

    # ---- rooms for subjects that need a laboratory or workshop
    have_types = {r["rtype"] for r in rooms}
    for rt in sorted({subs[i]["rtype"] for i in need_by_sub if subs[i]["rtype"]} - have_types):
        users = sorted({subs[i]["name"] for i in need_by_sub if subs[i]["rtype"] == rt})
        err("Room Management", "auto_rooms", rt,
            f"No room of type '{rt}' is registered, but {', '.join(users[:3])} need(s) one.",
            "Register a room of this type in Quick Input > Rooms.")
    if rooms:
        warn("Room Management", "auto_rooms", "Room capacity",
             "Room capacity and the number of students per section are not recorded in this system, so they cannot be checked.",
             "Nothing to do. Rooms are checked by type, grade level and availability.")

    # ---- database relationships
    for label, sql in (
            ("Teaching loads that point to a missing teacher, section or subject",
             "SELECT COUNT(*) AS n FROM loads l WHERE (l.teacher_id IS NOT NULL AND l.teacher_id NOT IN (SELECT id FROM users)) "
             "OR l.section_id NOT IN (SELECT id FROM sections) OR l.subject_id NOT IN (SELECT id FROM subjects)"),
            ("Teacher qualifications that point to a missing teacher or subject",
             "SELECT COUNT(*) AS n FROM teacher_subjects WHERE user_id NOT IN (SELECT id FROM users) "
             "OR subject_id NOT IN (SELECT id FROM subjects)"),
            ("Class periods that point to a missing teacher, room or section",
             "SELECT COUNT(*) AS n FROM classes WHERE (teacher_id IS NOT NULL AND teacher_id NOT IN (SELECT id FROM users)) "
             "OR (room_id IS NOT NULL AND room_id NOT IN (SELECT id FROM rooms)) "
             "OR section_id NOT IN (SELECT id FROM sections)")):
        n = query(sql, one=True)["n"]
        if n:
            err("Database", "auto_generate", f"{n} record(s)", label + ".",
                "Restart the application: the automatic repair removes these dangling links.")

    existing = query("SELECT COUNT(*) AS n FROM classes WHERE kind='class' AND teacher_id IS NOT NULL", one=True)["n"]
    conflicts = len(check_program()["issues"]) if existing else 0
    if conflicts:
        warn("Class Programs", "auto_conflicts", "Stored programs",
             f"The current class programs have {conflicts} conflict(s). Generating replaces them.",
             "Generate again after validation passes.")
    counts = dict(sections=len(secs), subjects=required, teachers=len(teachers), rooms=len(rooms),
                  matches=len(pairs), missing=len(errors), conflicts=conflicts,
                  unavailable=sum(1 for t in teachers if not entries[t["id"]]))
    return dict(ok=not errors, errors=errors, warnings=warns, counts=counts, existing=existing,
                fingerprint=validation_fingerprint(), when=ph_stamp())


def _workload_summary():
    """Teaching minutes per teacher, read from the saved class programs."""
    out = {}
    for r in query("""SELECT c.teacher_id, u.full_name, c.section_id, c.start, c."end" FROM classes c
                      JOIN users u ON u.id=c.teacher_id WHERE c.kind='class'"""):
        w = out.setdefault(r["teacher_id"], dict(name=r["full_name"], minutes=0, sections=set()))
        w["minutes"] += tomin(r["end"]) - tomin(r["start"])
        w["sections"].add(r["section_id"])
    return sorted(({"name": w["name"], "minutes": w["minutes"], "sections": len(w["sections"])}
                   for w in out.values()), key=lambda x: -x["minutes"])


def generate_all(confirm_overwrite=False, token=""):
    """Assign teachers, place every class and save everything in ONE transaction. Any failure rolls the whole
    thing back, so the previous programs stay exactly as they were."""
    conn = db()
    if gset("approved_at", ""):
        return dict(ok=False, stage="locked", message="The schedule is approved and locked. Reopen it in "
                    "Validation Center (Final approval) before generating again.", details=[])
    try:
        try:
            last = json.loads(gset("last_validation", "") or "null")
        except ValueError:
            last = None
        if not (last and last.get("ok") and last.get("fingerprint") == validation_fingerprint()):
            return dict(ok=False, stage="validation", message="Validate all requirements first. The records changed or "
                        "were never validated, so generation did not start.", details=[])
        rep = validate_all()
    except Exception as exc:                              # nothing has been written yet
        conn.rollback()
        app.logger.exception("validation before generation failed")
        return dict(ok=False, stage="error", message="Generation did not start: the final check failed "
                    f"({type(exc).__name__}). Nothing was changed.", details=[])
    if not rep["ok"]:
        return dict(ok=False, stage="validation", message="Generation did not start because validation failed. "
                    "Fix the problems listed below and validate again.", details=[], report=rep)
    if rep["existing"] and not confirm_overwrite:
        return dict(ok=False, stage="confirm", message="Existing class programs were not replaced. Confirm the "
                    "replacement to continue.", details=[])
    conn.rollback()                                       # end the read-only snapshot; start the real transaction
    conn.hold, conn.failed = True, False
    try:
        if not conn.execute("SELECT pg_try_advisory_xact_lock(?) AS got", (GEN_LOCK_KEY,)).fetchone()["got"]:
            raise GenerationBlocked("Another generation is already running. Wait for it to finish.")
        if gset("gen_token", "") != token:
            raise GenerationBlocked("This request was already processed or is out of date. Nothing was changed. "
                                    "Reload the page and try again.")
        sset("gen_token", secrets.token_hex(8))
        ids = [s["id"] for s in sched_secs()]
        match_quals()
        autofill()
        best = None
        for rnd in range(6):
            d = solve(ids, tries=40, seed=rnd)
            if best is None or len(d["unplaced"]) < len(best["unplaced"]):
                best = d
            if not best["unplaced"]:
                break
            autofill(overwrite=True, jitter=60 * (rnd + 1))
        left = [f"{r['sname']} - {r['subname']}: " + why_no_teacher(
                    query("SELECT * FROM sections WHERE id=?", (r["section_id"],), one=True),
                    query("SELECT * FROM subjects WHERE id=?", (r["subject_id"],), one=True))
                for r in query("""SELECT l.section_id, l.subject_id, s.name AS sname, b.name AS subname
                                  FROM loads l JOIN section_subjects ss ON ss.section_id=l.section_id AND ss.subject_id=l.subject_id
                                  JOIN sections s ON s.id=l.section_id JOIN subjects b ON b.id=l.subject_id
                                  WHERE l.teacher_id IS NULL AND l.section_id IN (%s)""" % ",".join(map(str, ids or [0])))]
        if left or best["unplaced"]:
            det = left + [f"{u['section']} - {u['subject']} ({u['teacher']}): {u['reason']}" for u in best["unplaced"]]
            raise GenerationBlocked("The class programs could not be completed, so nothing was saved and the "
                                    "previous programs were kept.", det)
        apply_draft(best)
        clear_stale(ids)
        chk = check_program()
        bad = blocking_program_issues(chk)
        if bad:
            raise GenerationBlocked("The generated programs still had conflicts, so nothing was saved.", bad[:15])
        if conn.failed:
            raise GenerationBlocked("A database error occurred during generation. Nothing was saved.")
        last["fingerprint"] = validation_fingerprint()      # generation adds derived qualifications: still the same validated data
        sset("last_validation", json.dumps(last))
        conn.hold = False
        conn.commit()
        return dict(ok=True, stage="done", message="CLASS PROGRAMS SUCCESSFULLY GENERATED!", details=[],
                    sections=len(ids), placed=len(best["sessions"]), when=ph_stamp())
    except GenerationBlocked as exc:
        conn.hold = False
        conn.rollback()
        sset("gen_token", secrets.token_hex(8))
        return dict(ok=False, stage="generation", message=str(exc), details=exc.details)
    except Exception as exc:                              # any other failure: roll back, keep the old programs
        conn.hold = False
        conn.rollback()
        app.logger.exception("generation failed")
        sset("gen_token", secrets.token_hex(8))
        return dict(ok=False, stage="error", message="Generation failed and was rolled back. The previous class "
                    f"programs were kept. ({type(exc).__name__})", details=[])
    finally:
        conn.hold = False


@app.route("/admin/generate", methods=["GET", "POST"])
@login_required("admin")
def auto_generate():
    if request.method == "POST":
        f = request.form
        act = f.get("action")
        if act == "validate":
            rep = validate_all()
            sset("last_validation", json.dumps(rep))
            if rep["ok"]:
                flash("ALL REQUIREMENTS VERIFIED. YOUR SYSTEM IS READY FOR CLASS PROGRAM GENERATION.", "ok")
            else:
                flash(f"Validation found {len(rep['errors'])} problem(s). Fix them, then validate again.", "error")
        elif act == "generate":
            res = generate_all(f.get("confirm_overwrite") == "1", f.get("token", ""))
            if res["stage"] in ("done", "generation", "error"):    # a refused click must not hide the last real result
                sset("last_generation", json.dumps({k: v for k, v in res.items() if k != "report"}))
            flash(res["message"], "ok" if res["ok"] else "error")
        return redirect(url_for("auto_generate") + ("#results" if act == "generate" else ""))
    try:
        lv = json.loads(gset("last_validation", "") or "null")
    except ValueError:
        lv = None
    try:
        lg = json.loads(gset("last_generation", "") or "null")
    except ValueError:
        lg = None
    current = validation_fingerprint()
    valid_now = bool(lv and lv.get("ok") and lv.get("fingerprint") == current)
    outdated = bool(lv and lv.get("fingerprint") != current)
    if not gset("gen_token", ""):
        sset("gen_token", secrets.token_hex(8))
    locked = bool(gset("approved_at", ""))
    secs = [dict(r) for r in query("""SELECT s.id, s.name, (SELECT COUNT(*) FROM classes c WHERE c.section_id=s.id
                                      AND c.kind='class' AND c.teacher_id IS NOT NULL) AS n FROM sections s ORDER BY s.grade, s.name""")]
    with_prog = [s for s in secs if s["n"]]
    sel = request.args.get("section", type=int) or (with_prog[0]["id"] if with_prog else None)
    rows = []
    if sel:
        rows = [dict(r) for r in query("""SELECT c.day, c.start, c."end", c.subject, c.room, u.full_name AS teacher
                    FROM classes c LEFT JOIN users u ON u.id=c.teacher_id
                    WHERE c.section_id=? AND c.kind='class' ORDER BY c.start, c.day""", (sel,))]
        rows.sort(key=lambda r: (DAYS.index(r["day"]), r["start"]))
    ps = programs_status()
    return render_template("auto_generate.html", lv=lv, lg=lg, valid_now=valid_now, outdated=outdated,
                           complete=ps["complete"], room_notes=[x["text"] for x in check_program()["entries"]
                                                                if x["kind"] in ROOM_NOTE_KINDS][:20],
                           token=gset("gen_token", ""), locked=locked, secs=secs, sel=sel, rows=rows,
                           workload=_workload_summary(), maxweek=weekly_limit(),
                           has_programs=bool(with_prog),
                           stale=[r["name"] for r in query("SELECT id, name FROM sections") if r["id"] in stale_ids()])



AUTO_TEMPLATES = {
"auto_rooms.html": r"""{% extends "base.html" %}{% block title %}Rooms{% endblock %}
{% set glabel = {'Both': 'Grades 11 and 12', '11': 'Grade 11 only', '12': 'Grade 12 only'} %}
{% block content %}<div class="pagehead"><h1>Room Management</h1><div class="row-acts"><button type="button" class="danger" data-edit-dlg="deltypedlg" data-json='{}'>Delete room type</button><button type="button" data-edit-dlg="typedlg" data-json='{{ {"tid": "", "name": "", "facilities": "", "_mode": "new", "_title": "Add room type", "_lock": [], "_note": "Add a new kind of room the school has, such as a Music Room or an Art Studio."}|tojson }}'>+ Add room type</button></div></div>
<p class="hint">Only the rooms listed here can be used by sections and class programs. Nothing is added automatically. Register rooms in Quick Input.</p>
<div class="scroll"><table data-tools="rooms" class="list rooms-t"><thead><tr><th data-ts="text">Room</th><th data-ts="text" data-tf>Type</th><th data-ts="text" data-tf>Grade level</th><th data-ts="text" data-tf>Building</th><th data-ts="text" data-tf>Floor</th><th data-ts="num">Use</th><th class="editth">Actions</th></tr></thead><tbody>
{% for r in rows %}{% set k = r.id %}{% set u = used.get(k, 0) %}<tr>
<td><b class="cell-wrap">{{ r.name }}</b></td>
<td>{{ r.rtype }}</td>
<td data-tv="{{ glabel.get(r.grade_access or 'Both', 'Grades 11 and 12') }}">{{ glabel.get(r.grade_access or 'Both', 'Grades 11 and 12') }}</td>
<td>{{ r.building or '-' }}</td><td>{{ r.floor or '-' }}</td>
<td data-tv="{{ (u * 100 / cap)|int }}"><div class="bar"><i style="width:{{ [100, (u * 100 / cap)|int]|min }}%"></i></div><p class="hint">{{ u|hrs }} per week ({{ (u * 100 / cap)|int }}%)</p></td>
<td class="editcell"><div class="row-acts"><button type="button" class="plain small" data-edit-dlg="roomdlg" aria-label="Edit {{ r.name }}" data-json='{{ {"rid": r.id, "name": r.name, "rtype": r.rtype, "grade_access": r.grade_access or "Both", "building": r.building or "", "floor": r.floor or ""}|tojson }}'>Edit</button><a class="btn plain small" href="{{ url_for('auto_room', rid=k) }}">View</a>
<form method="post" data-confirm="Delete {{ r.name }}? It is removed from the room list and from every class period that uses it. This cannot be undone.">{{ csrf_field() }}<input type="hidden" name="action" value="delete"><input type="hidden" name="rid" value="{{ r.id }}"><button type="submit" class="danger small">Delete</button></form></div></td></tr>
{% else %}<tr><td colspan="7" class="empty">No rooms yet. Register them in Quick Input.</td></tr>{% endfor %}</tbody></table></div>
<dialog id="typedlg" class="dlg" aria-labelledby="typedlg-t"><form method="post" class="dlg-form" data-noconfirm novalidate>{{ csrf_field() }}<input type="hidden" name="action" value="type_save"><input type="hidden" name="tid" value="">
<h3 id="typedlg-t" data-title>Add room type</h3>
<div class="msg error" role="alert" id="typeerr" {% if not tf_err %}hidden{% endif %}>{{ tf_err }}</div>
<div class="dlg-grid">
<div><label for="ty_name">Room type name</label><input id="ty_name" name="name" maxlength="60" required></div>
</div>
<p class="hint" data-note></p>
<div class="btnrow"><button type="submit">Save</button><button type="button" class="plain" data-close>Cancel</button></div>
</form></dialog>
<script>(function(){var d=document.getElementById('typedlg'),m=document.getElementById('typeerr');
d.addEventListener('dlg:fill',function(){m.hidden=true;});
d.querySelector('form').addEventListener('submit',function(e){if(!d.querySelector('[name=name]').value.trim()){e.preventDefault();m.textContent='Enter the room type name.';m.hidden=false;}});
{% if tf %}document.addEventListener('DOMContentLoaded',function(){window.dlgOpen('typedlg',{{ tf|tojson }});{% if tf_err %}m.hidden=false;{% endif %}});{% endif %}})();</script>
<dialog id="deltypedlg" class="dlg" aria-labelledby="deltypedlg-t"><form method="post" class="dlg-form" data-confirm="Delete this room type? This cannot be undone.">{{ csrf_field() }}<input type="hidden" name="action" value="type_delete">
<h3 id="deltypedlg-t">Delete room type</h3>
{% set removable = types|rejectattr('classroom')|list %}
<label for="ty_del">Room type to delete</label>
<select id="ty_del" name="tid" required><option value="">Choose a room type</option>{% for t in removable %}<option value="{{ t.id }}" {{ 'disabled' if t.rooms or t.subjects }}>{{ t.name }}{% if t.rooms or t.subjects %} (in use: {{ t.rooms }} room{{ '' if t.rooms == 1 else 's' }}, {{ t.subjects }} subject{{ '' if t.subjects == 1 else 's' }}){% endif %}</option>{% endfor %}</select>
<p class="hint">A room type that rooms or subjects still use cannot be deleted. Change those to another type first. Regular cannot be deleted.</p>
<div class="btnrow"><button type="submit" class="danger">Delete</button><button type="button" class="plain" data-close>Cancel</button></div>
</form></dialog>
<dialog id="roomdlg" class="dlg" aria-labelledby="roomdlg-t"><form method="post" class="dlg-form" data-noconfirm novalidate>{{ csrf_field() }}<input type="hidden" name="action" value="edit"><input type="hidden" name="rid" value="">
<h3 id="roomdlg-t">Edit room</h3>
<div class="msg error" role="alert" id="roomerr" {% if not rf_err %}hidden{% endif %}>{{ rf_err }}</div>
<div class="dlg-grid">
<div><label for="rm_name">Room name or number</label><input id="rm_name" name="name" maxlength="60" required></div>
<div><label for="rm_type">Room type</label><select id="rm_type" name="rtype">{% for x in rtypes %}<option>{{ x }}</option>{% endfor %}</select></div>
<div><label for="rm_grade">Grade level that can use it</label><select id="rm_grade" name="grade_access"><option value="Both">Grades 11 and 12</option><option value="11">Grade 11 only</option><option value="12">Grade 12 only</option></select></div>
<div><label for="rm_b">Building</label><select id="rm_b" name="building"><option value="">-</option>{% for b in buildings %}<option>{{ b }}</option>{% endfor %}</select></div>
<div><label for="rm_f">Floor</label><select id="rm_f" name="floor"><option value="">-</option>{% for fl in floors %}<option>{{ fl }}</option>{% endfor %}</select></div>
</div>
<div class="btnrow"><button type="submit">Save changes</button><button type="button" class="plain" data-close>Cancel</button></div>
</form></dialog>
<script>(function(){var d=document.getElementById('roomdlg'),m=document.getElementById('roomerr');
d.addEventListener('dlg:fill',function(){m.hidden=true;});
d.querySelector('form').addEventListener('submit',function(e){if(!d.querySelector('[name=name]').value.trim()){e.preventDefault();m.textContent='Enter the room name.';m.hidden=false;}});
{% if rf %}document.addEventListener('DOMContentLoaded',function(){window.dlgOpen('roomdlg',{{ rf|tojson }});{% if rf_err %}m.hidden=false;{% endif %}});{% endif %}})();</script>{% endblock %}
""",

"auto_room.html": """{% extends "base.html" %}{% from "macros.html" import back with context %}{% block title %}{{ room.name }}{% endblock %}
{% block content %}<div class="titlerow">{{ back(url_for('auto_rooms'), 'Back to rooms') }}<h1>{{ room.name }}</h1></div>
<div class="scroll"><table data-tools="periods" class="list"><thead><tr><th data-tf>Day</th><th>Time</th><th data-ts="text" data-tf>Section</th><th data-ts="text">Subject</th><th data-ts="text" data-tf>Teacher</th></tr></thead><tbody>
{% for r in rows %}<tr><td>{{ r.day }}</td><td>{{ r.start|t12 }} to {{ r.end|t12 }}</td><td><a href="{{ url_for('program', section=r.section_id) }}">{{ r.sname }}</a></td><td>{{ r.subject }}</td><td>{{ r.tname or '-' }}</td></tr>
{% else %}<tr><td colspan="5" class="empty">This room is free all week.</td></tr>{% endfor %}</tbody></table></div>{% endblock %}""",

"auto_quals.html": """{% extends "base.html" %}{% block title %}Qualifications{% endblock %}
{% block content %}<h1>Teacher Loading</h1>{{ subnav('loading') }}
{% if not subs %}<div class="msg notice">Add subjects first.</div>{% else %}
<div class="qlegend">{% for cat, items in groups %}<span class="qcat qc-{{ cat|lower }}"><b>{{ cat }}</b> {{ items|length }} subject{{ '' if items|length == 1 else 's' }} &middot; {{ cat }} total: <b>{{ cat_total[cat] }}</b> teacher{{ '' if cat_total[cat] == 1 else 's' }}</span>{% endfor %}</div><div class="scroll"><table class="mx qm"><thead><tr><th class="l" rowspan="2">Teacher</th>{% for cat, items in groups %}<th class="qh qc-{{ cat|lower }}" colspan="{{ items|length }}">{{ cat }} (total: {{ cat_total[cat] }})</th>{% endfor %}</tr><tr>{% for cat, items in groups %}{% for s in items %}<th class="qs qc-{{ cat|lower }}{{ ' first' if loop.first }}" title="{{ s.name }}">{{ s.code or s.name[:6] }}</th>{% endfor %}{% endfor %}</tr></thead><tbody>
{% for t in teachers_ %}<tr><td class="l"><b>{{ tlabels.get(t.id) }}</b> {{ t.full_name }}<br><small>{{ t.official_time or 'Whole day' }}</small></td>{% for cat, items in groups %}{% for s in items %}<td class="{{ 'first' if loop.first }}" style="text-align:center">{% if (t.id, s.id) in have %}<b style="color:var(--ok)" aria-label="{{ t.full_name }} is qualified for {{ s.name }}">&#10003;</b>{% endif %}</td>{% endfor %}{% endfor %}</tr>
{% else %}<tr><td class="l" colspan="{{ subs|length + 1 }}">No teachers yet.</td></tr>{% endfor %}</tbody>
<tfoot><tr><td class="l"><b>Qualified teachers</b></td>{% for cat, items in groups %}{% for s in items %}<td class="{{ 'first' if loop.first }}" style="text-align:center"><b>{{ sub_count.get(s.id, 0) }}</b></td>{% endfor %}{% endfor %}</tr></tfoot></table></div>{% endif %}{% endblock %}""",

}
TEMPLATES.update(AUTO_TEMPLATES)


# ======================================================================================
# LOADING VALIDATION, TIME ALLOCATION, CONFLICTS, ADJUSTMENT ASSISTANCE, REPORTS
# ======================================================================================
import io
from flask import send_file


def daily_limit():
    return to_int(gset("max_teach_day", "360"), 60, 720) or 360


def weekly_limit():
    return to_int(gset("max_teach_week", "1800"), 60, 3000) or 1800


def hm_text(m):
    m = int(m or 0)
    h, r = divmod(m, 60)
    return (f"{h} hr{'s' if h != 1 else ''}" if h else "") + (" " if h and r else "") + (f"{r} min" if r or not h else "")


def usable_min(w, per):
    """Class minutes of one shift that fall inside a teacher's official time window."""
    return sum(max(0, min(e, w[1]) - max(s, w[0])) for s, e, k in per if k == "class")


def stale_ids():
    try:
        return [int(x) for x in json.loads(gset("stale_sections", "[]") or "[]")]
    except ValueError:
        return []


def mark_stale(ids):
    sset("stale_sections", json.dumps(sorted(set(stale_ids()) | set(ids))))


def clear_stale(ids):
    sset("stale_sections", json.dumps([i for i in stale_ids() if i not in set(ids)]))


def build_busy(exclude_ids=()):
    busy = Busy()
    ex = set(exclude_ids)
    for c in query("SELECT * FROM classes WHERE kind='class'"):
        if c["id"] in ex:
            continue
        s, e = tomin(c["start"]), tomin(c["end"])
        busy.add(("s", c["section_id"]), c["day"], s, e)
        if c["teacher_id"]:
            busy.add(("t", c["teacher_id"]), c["day"], s, e)
        if c["room_id"]:
            busy.add(("r", c["room_id"]), c["day"], s, e)
    return busy


# ------------------------------------------------------------------ 1. loading validation
def _validate_loading():
    tt, maxday, maxweek = get_tt(), daily_limit(), weekly_limit()
    issues, warns = [], []
    teachers_ = {t["id"]: dict(t) for t in query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name")}
    secs = {s["id"]: dict(s) for s in sched_secs()}
    subs = {s["id"]: dict(s) for s in query("SELECT * FROM subjects")}
    quals = qualified_pairs()
    mins, nsec = defaultdict(int), defaultdict(int)
    preps, unq = defaultdict(set), defaultdict(int)
    by_shift = defaultdict(int)
    have_sub = defaultdict(set)
    used_subjects = {r["subject_id"] for r in query("SELECT DISTINCT subject_id FROM section_subjects")}
    for o in query("""SELECT ss.section_id, ss.subject_id, l.teacher_id FROM section_subjects ss
                      LEFT JOIN loads l ON l.section_id=ss.section_id AND l.subject_id=ss.subject_id"""):
        sec, sub = secs.get(o["section_id"]), subs.get(o["subject_id"])
        if not sec or not sub:
            continue
        have_sub[sec["id"]].add(sub["name"].strip().lower())
        tid = o["teacher_id"]
        if not tid:
            issues.append(f"Incomplete loading: {sec['name']} - {sub['name']} has no teacher assigned. " + why_no_teacher(sec, sub))
            continue
        t = teachers_.get(tid)
        if not t:
            issues.append(f"Incomplete loading: the teacher assigned to {sec['name']} - {sub['name']} no longer exists.")
            continue
        mins[tid] += sub["weekly_min"]
        nsec[tid] += 1
        preps[tid].add(sub["id"])
        by_shift[(tid, sec_shift(sec, tt))] += sub["weekly_min"]
        if (tid, sub["id"]) not in quals:
            unq[tid] += 1
            issues.append(f"Outside qualification: {t['full_name']} is assigned {sub['name']} ({sec['name']}) "
                          "but is not qualified for it.")
        if not eligible(sub, sec):
            warns.append(f"{sub['name']} is not meant for {sec['name']} (grade or track differs).")
    for sid, sec in secs.items():
        if not have_sub.get(sid):
            warns.append(f"{sec['name']} has no subjects yet.")
    # duplicates
    seen = defaultdict(list)
    for s in subs.values():
        seen[(s["name"] or "").strip().lower()].append(s)
        if s["code"]:
            seen[("code", s["code"].strip().lower())].append(s)
    for k, lst in seen.items():
        if len(lst) > 1:
            label = k if isinstance(k, str) else k[1].upper()
            issues.append(f"Duplicate subject record: '{label}' exists {len(lst)} times in the subject list.")
    taught = defaultdict(set)
    for c in query("SELECT section_id, subject, teacher_id FROM classes WHERE kind='class' AND teacher_id IS NOT NULL"):
        taught[(c["section_id"], c["subject"])].add(c["teacher_id"])
    for (sid, name), ts in taught.items():
        if len(ts) > 1 and sid in secs:
            issues.append(f"Duplicate assignment: {secs[sid]['name']} - {name} is taught by "
                          f"{len(ts)} different teachers in the class program.")
    rows = []
    for tid, t in teachers_.items():
        w = teacher_window(t)
        notes, status = [], "OK"
        if mins[tid] > maxweek:
            status = "Over limit"
            issues.append(f"Over limit: {t['full_name']} is assigned {hm_text(mins[tid])} per week; the limit is {hm_text(maxweek)}.")
        for shift, per in tt.items():
            need = by_shift.get((tid, shift), 0)
            avail = min(usable_min(w, per), maxday) * len(DAYS)
            if need > avail:
                status = "Cannot fit" if status == "OK" else status
                issues.append(f"Cannot fit: {t['full_name']} has {hm_text(need)} per week in the {shift} shift but only "
                              f"{hm_text(avail)} of official time ({t['official_time'] or 'whole day'}) overlaps it.")
        if not mins[tid]:
            status = "No load" if status == "OK" else status
            warns.append(f"{t['full_name']} has no teaching load assigned.")
        elif not t["official_time"]:
            warns.append(f"{t['full_name']} has no official time set; the whole day is assumed.")
        if unq[tid]:
            status = "Unqualified" if status == "OK" else status
        sched = 0
        for c_ in query("SELECT start, \"end\" FROM classes WHERE kind='class' AND teacher_id=?", (tid,)):
            try:
                sched += max(0, tomin(c_["end"]) - tomin(c_["start"]))
            except (ValueError, AttributeError):
                issues.append(f"Unreadable class time for {t['full_name']}: '{c_['start']}' to '{c_['end']}'. "
                              "Regenerate the class program.")
        rows.append(dict(t=t, minutes=mins[tid], nsec=nsec[tid], npre=len(preps[tid]), unq=unq[tid],
                         sched=sched, status=status, window=t["official_time"] or "Whole day"))
    for s in subs.values():
        if not any((t_id, s["id"]) in quals for t_id in teachers_):
            warns.append(f"No qualified teacher exists for {s['name']}.")
        if not s["session_min"] or s["session_min"] < 1 or not s["weekly_min"]:
            issues.append(f"Invalid minutes: {s['name']} has {s['weekly_min'] or 0} minutes per week and "
                          f"{s['session_min'] or 0} minutes per meeting. Correct them in Subject Management.")
        elif s["session_min"] > s["weekly_min"]:
            warns.append(f"{s['name']}: the meeting length is longer than the weekly time.")
        elif s["weekly_min"] % s["session_min"]:
            warns.append(f"{s['name']}: {hm_text(s['weekly_min'])} is not a whole number of {hm_text(s['session_min'])} meetings; "
                         "the last meeting will be shorter.")
        if (s["rtype"] and s["id"] in used_subjects
                and not query("SELECT 1 FROM rooms WHERE rtype=?", (s["rtype"],), one=True)):
            warns.append(f"Room note: no '{s['rtype']}' room is registered for {s['name']}.")
    return dict(rows=rows, issues=issues, warns=sorted(set(warns)), maxweek=maxweek, maxday=maxday)


def log_failure(what):
    """Record the real exception with the route and a short reference the administrator can quote.
    Nothing from the database connection string or the exception text is shown to the user."""
    ref = uuid.uuid4().hex[:8].upper()
    try:
        who, where = (g.user["id"] if g.get("user") else "anonymous"), f"{request.method} {request.path}"
    except RuntimeError:
        who, where = "n/a", "outside a request"
    app.logger.error("[%s] %s failed. route=%s user=%s", ref, what, where, who, exc_info=True)
    return ref


def validate_loading():
    """Teacher loading validation. If a damaged record makes the check fail, the page still opens and says so,
    instead of the whole page returning HTTP 500."""
    try:
        return _validate_loading()
    except Exception:
        ref = log_failure("teacher loading validation")
        try:
            lim = (weekly_limit(), daily_limit())
        except Exception:
            lim = (1800, 360)
        return dict(rows=[], issues=[f"The teacher loading check could not finish (reference {ref}). The error was "
                                     "recorded in the server log; check the subjects and teachers for damaged values."],
                    warns=[], maxweek=lim[0], maxday=lim[1], failed=ref)


# ------------------------------------------------------------------ 2. time allocation
def time_allocation():
    tt, maxday, maxweek = get_tt(), daily_limit(), weekly_limit()
    order = sorted(tt, key=lambda k: tt[k][0][0])
    shifts = []
    for name in order:
        per = tt[name]
        cls = sum(e - s for s, e, k in per if k == "class")
        shifts.append(dict(name=name, start=hhmm(per[0][0]), end=hhmm(per[-1][1]), day=cls, week=cls * len(DAYS),
                           periods=[(hhmm(s), hhmm(e), k) for s, e, k in per]))
    subs = []
    for s in query("SELECT * FROM subjects ORDER BY grade, name"):
        lens = session_lengths(s["weekly_min"], s["session_min"])
        blocks = {n: {L: len(blocks_for(tt[n], L)) for L in sorted(set(lens))} for n in order}
        subs.append(dict(s=s, n=len(lens), lens=lens, blocks=blocks,
                         bad=[n for n in order if any(v == 0 for v in blocks[n].values())]))
    secs = []
    for sec in sched_secs():
        sh = sec_shift(dict(sec), tt)
        need = query("""SELECT COALESCE(SUM(b.weekly_min),0) AS m FROM section_subjects ss JOIN subjects b ON b.id=ss.subject_id
                        WHERE ss.section_id=?""", (sec["id"],), one=True)["m"]
        cap = next(x["week"] for x in shifts if x["name"] == sh)
        secs.append(dict(sec=sec, shift=sh, need=need, cap=cap, pct=int(100 * need / cap) if cap else 0))
    tch = []
    for t in query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name"):
        w = teacher_window(dict(t))
        union = 0
        for a, b in class_union(tt):
            union += max(0, min(b, w[1]) - max(a, w[0]))
        cap = min(min(union, maxday) * len(DAYS), maxweek)
        need = query("""SELECT COALESCE(SUM(b.weekly_min),0) AS m FROM loads l JOIN subjects b ON b.id=l.subject_id
                        JOIN section_subjects ss ON ss.section_id=l.section_id AND ss.subject_id=l.subject_id
                        WHERE l.teacher_id=?""", (t["id"],), one=True)["m"]
        tch.append(dict(t=t, need=need, cap=cap, pct=int(100 * need / cap) if cap else (100 if need else 0),
                        window=t["official_time"] or "Whole day"))
    return dict(shifts=shifts, subs=subs, secs=secs, tch=tch, maxday=maxday, maxweek=maxweek)


def class_union(tt):
    iv = sorted((s, e) for per in tt.values() for s, e, k in per if k == "class")
    out = []
    for s, e in iv:
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def free_slots(kind, ident, L):
    """Every free block of L minutes for a section, teacher or room, per day."""
    tt, busy, maxday = get_tt(), build_busy(), daily_limit()
    pers, win, key = list(tt.values()), (0, 1440), (kind[0], ident)
    if kind == "section":
        sec = query("SELECT * FROM sections WHERE id=?", (ident,), one=True)
        pers = [tt[sec_shift(dict(sec), tt)]] if sec else []
    elif kind == "teacher":
        t = query("SELECT * FROM users WHERE id=? AND role='teacher'", (ident,), one=True)
        win = teacher_window(dict(t)) if t else win
    out = {d: set() for d in DAYS}
    for per in pers:
        for day in DAYS:
            for s, e in blocks_for(per, L):
                if s < win[0] or e > win[1] or busy.hit(key, day, s, e):
                    continue
                if kind == "teacher" and busy.total(key, day) + L > maxday:
                    continue
                out[day].add((s, e))
    return {d: sorted(v) for d, v in out.items()}


# ------------------------------------------------------------------ 3. conflict detection
def _check_program():
    tt, maxday = get_tt(), daily_limit()
    items = []

    def add(kind, text, pid=None, sev="issue"):
        items.append(dict(kind=kind, text=text, pid=pid, sev=sev))
    secd = {s["id"]: dict(s) for s in query("SELECT * FROM sections")}
    shift_of = {i: sec_shift(s, tt) for i, s in secd.items()}
    rows = [dict(r) for r in query(
        """SELECT c.*, s.name AS sname, u.full_name AS tname, u.official_time AS otime, r.rtype AS rrtype
           FROM classes c JOIN sections s ON s.id=c.section_id
           LEFT JOIN users u ON u.id=c.teacher_id LEFT JOIN rooms r ON r.id=c.room_id WHERE c.kind='class'""")]
    groups = defaultdict(list)
    for r in rows:
        for kind, ident, label in (("section", r["section_id"], r["sname"]), ("teacher", r["teacher_id"], r["tname"]),
                                   ("room", r["room_id"], r["room"])):
            if ident:
                groups[(kind, ident, r["day"], label)].append(r)
    for (kind, _i, day, label), lst in groups.items():
        for i, a in enumerate(lst):
            for b in lst[i + 1:]:
                if tomin(a["start"]) < tomin(b["end"]) and tomin(b["start"]) < tomin(a["end"]):
                    cross = kind == "room" and shift_of.get(a["section_id"]) != shift_of.get(b["section_id"])
                    add("room-shift" if cross else kind,
                        f"{'Room conflict across shifts' if cross else kind.capitalize() + ' conflict'}: {label} on {day} - "
                        f"{a['sname']} {a['subject']} ({t12(a['start'])}-{t12(a['end'])}) overlaps {b['sname']} {b['subject']} "
                        f"({t12(b['start'])}-{t12(b['end'])}).", a["id"])
    done = defaultdict(int)
    for r in rows:
        done[(r["section_id"], r["subject"])] += tomin(r["end"]) - tomin(r["start"])
    for r in query("""SELECT ss.section_id, s.name AS sname, b.name AS bname, b.weekly_min FROM section_subjects ss
                      JOIN sections s ON s.id=ss.section_id JOIN subjects b ON b.id=ss.subject_id"""):
        got = done.get((r["section_id"], r["bname"]), 0)
        if got < r["weekly_min"]:
            pid = next((x["id"] for x in rows if x["section_id"] == r["section_id"] and x["subject"] == r["bname"]), None)
            add("hours", f"Incomplete hours: {r['sname']} - {r['bname']} has {hm_text(got)} of the required "
                         f"{hm_text(r['weekly_min'])} per week.", pid)
    sub_type = {r["name"]: r["rtype"] for r in query("SELECT name, rtype FROM subjects")}
    perday = defaultdict(int)
    for r in rows:
        s, e = tomin(r["start"]), tomin(r["end"])
        if r["teacher_id"]:
            perday[(r["tname"], r["day"])] += e - s
            w = teacher_window({"official_time": r["otime"]})
            if s < w[0] or e > w[1]:
                add("window", f"Outside teacher availability: {r['tname']} ({r['otime'] or 'whole day'}) teaches "
                              f"{r['sname']} {r['subject']} on {r['day']} {t12(r['start'])}-{t12(r['end'])}.", r["id"])
        per = tt[shift_of[r["section_id"]]]
        if s < per[0][0] or e > per[-1][1]:
            add("shift", f"Outside shift: {r['sname']} {r['subject']} on {r['day']} {t12(r['start'])} is outside "
                         f"the {shift_of[r['section_id']]} timetable.", r["id"])
        elif any(k == "recess" and s < pe and ps < e for ps, pe, k in per):
            add("shift", f"{r['sname']} {r['subject']} on {r['day']} {t12(r['start'])} overlaps recess.", r["id"])
        want = sub_type.get(r["subject"])
        if want and r["room_id"] and r["rrtype"] != want:
            add("roomtype", f"Wrong room type: {r['sname']} {r['subject']} is in a {r['rrtype']} but needs a {want}.", r["id"])
        if want and not r["room_id"]:
            add("noroom", f"No room assigned: {r['sname']} {r['subject']} ({r['day']}).", r["id"], "warn")
    for (name, day), m in perday.items():
        if m > maxday:
            add("daycap", f"{name} teaches {hm_text(m)} on {day} (limit {hm_text(maxday)}).", None, "warn")
    seen, uniq = set(), []
    for x in items:
        if x["text"] not in seen:
            seen.add(x["text"])
            uniq.append(x)
    return dict(entries=uniq, issues=[x["text"] for x in uniq if x["sev"] == "issue"],
                warns=[x["text"] for x in uniq if x["sev"] == "warn"][:40], rows=len(rows))


ROOM_NOTE_KINDS = {"roomtype", "room-shift", "noroom"}   # room details: shown as notes, never block progress


def blocking_program_issues(chk):
    """Conflicts that really make a program unusable (teacher, section, room double-booking, missing hours,
    outside hours). Room-type and room-note items are left out."""
    return [x["text"] for x in chk["entries"] if x["sev"] == "issue" and x["kind"] not in ROOM_NOTE_KINDS]


def programs_status(chk=None, lv=None):
    """One shared answer to 'are the class programs finished?' for the dashboard and the generator page."""
    chk = chk or check_program()
    lv = lv or validate_loading()
    secs = [dict(s) for s in sched_secs()]
    with_prog = {r["section_id"] for r in query("SELECT DISTINCT section_id FROM classes WHERE kind='class'")}
    unsched = [s for s in secs if s["id"] not in with_prog]
    stale = [s for s in secs if s["id"] in stale_ids()]
    issues = blocking_program_issues(chk)
    complete = bool(secs) and not unsched and not stale and not issues and not lv["issues"]
    return dict(complete=complete, secs=secs, unsched=unsched, stale=stale, issues=issues, lv=lv)


def check_program():
    """Conflict check. A damaged class row is reported as a problem instead of crashing the page."""
    try:
        return _check_program()
    except Exception:
        ref = log_failure("schedule conflict check")
        msg = (f"The schedule check could not finish (reference {ref}). A class period may have unreadable data; "
               "regenerate the class programs. The error is in the server log.")
        return dict(entries=[dict(kind="check", text=msg, pid=None, sev="issue")], issues=[msg], warns=[], rows=0)


# ------------------------------------------------------------------ 4. adjustment assistance
def period_row(pid):
    r = query("""SELECT c.*, s.name AS sname, s.grade, s.track, s.shift AS sshift, s.room AS home FROM classes c
                 JOIN sections s ON s.id=c.section_id WHERE c.id=? AND c.kind='class'""", (pid,), one=True)
    return dict(r) if r else None


def need_rtype(p):
    sub = query("SELECT rtype FROM subjects WHERE lower(name)=lower(?)", (p["subject"],), one=True)
    if sub:
        return sub["rtype"]
    room_ = query("SELECT rtype FROM rooms WHERE id=?", (p["room_id"],), one=True) if p["room_id"] else None
    return room_["rtype"] if room_ else "Regular"


def slot_error(busy, sec, teacher, day, s, e, maxday, tt):
    L = e - s
    if (s, e) not in set(blocks_for(tt[sec_shift(sec, tt)], L)):
        return f"{t12(hhmm(s))}-{t12(hhmm(e))} is not a valid {hm_text(L)} block in the {sec_shift(sec, tt)} timetable."
    if busy.hit(("s", sec["id"]), day, s, e):
        return f"{sec['name']} already has a class then."
    if teacher:
        w = teacher_window(teacher)
        if s < w[0] or e > w[1]:
            return f"{teacher['full_name']} is outside official time then."
        if busy.hit(("t", teacher["id"]), day, s, e):
            return f"{teacher['full_name']} is already teaching then."
        if busy.total(("t", teacher["id"]), day) + L > maxday:
            return f"{teacher['full_name']} would pass the daily teaching limit."
    return None


def free_room(busy, p, day, s, e, prefer=None):
    rt = need_rtype(p)
    buf = daily_turn() if rt != "Regular" else 0
    cands = [dict(r) for r in query("SELECT * FROM rooms WHERE rtype=? ORDER BY name", (rt,))]
    cands.sort(key=lambda r: (r["id"] != prefer, (r["name"] or "").lower() != (p.get("home") or "").lower()))
    return [r for r in cands if not busy.hit(("r", r["id"]), day, s, e, buf)]


def daily_turn():
    return to_int(gset("turnover", "0"), 0, 120) or 0


def suggest_slots(p, limit=20):
    tt, maxday = get_tt(), daily_limit()
    busy = build_busy([p["id"]])
    sec = dict(query("SELECT * FROM sections WHERE id=?", (p["section_id"],), one=True))
    teacher = query("SELECT * FROM users WHERE id=?", (p["teacher_id"],), one=True) if p["teacher_id"] else None
    teacher = dict(teacher) if teacher else None
    s0, e0 = tomin(p["start"]), tomin(p["end"])
    out = []
    for day in DAYS:
        for s, e in blocks_for(tt[sec_shift(sec, tt)], e0 - s0):
            if (day, s) == (p["day"], s0) or slot_error(busy, sec, teacher, day, s, e, maxday, tt):
                continue
            rooms_ = free_room(busy, p, day, s, e, p["room_id"])
            if rooms_ or not p["room_id"]:
                out.append(dict(day=day, start=hhmm(s), end=hhmm(e), room=rooms_[0] if rooms_ else None,
                                same_day=day == p["day"], d=abs(s - s0)))
    out.sort(key=lambda x: (not x["same_day"], x["d"], DAYS.index(x["day"])))
    return out[:limit]


def meetings_of(p):
    return [dict(r) for r in query("""SELECT * FROM classes WHERE section_id=? AND subject=? AND kind='class'
                                      ORDER BY id""", (p["section_id"], p["subject"]))]


def suggest_teachers(p):
    tt, maxday = get_tt(), daily_limit()
    sub = query("SELECT * FROM subjects WHERE lower(name)=lower(?)", (p["subject"],), one=True)
    if not sub:
        return []
    meets = meetings_of(p)
    busy = build_busy([m["id"] for m in meets])
    sec = dict(query("SELECT * FROM sections WHERE id=?", (p["section_id"],), one=True))
    out = []
    for t in query("""SELECT u.* FROM users u JOIN teacher_subjects q ON q.user_id=u.id AND q.subject_id=?
                      WHERE u.role='teacher' AND u.id IS NOT ? ORDER BY u.full_name""", (sub["id"], p["teacher_id"])):
        t, ok, why = dict(t), 0, ""
        w = teacher_window(t)
        extra = defaultdict(int)
        for m in meets:
            s, e = tomin(m["start"]), tomin(m["end"])
            err = None
            if s < w[0] or e > w[1]:
                err = "outside official time"
            elif busy.hit(("t", t["id"]), m["day"], s, e):
                err = "already teaching"
            elif busy.total(("t", t["id"]), m["day"]) + extra[m["day"]] + (e - s) > maxday:
                err = "daily limit"
            if err:
                why = why or f"{m['day']} {t12(m['start'])}: {err}"
            else:
                ok += 1
                extra[m["day"]] += e - s
        out.append(dict(t=t, ok=ok, total=len(meets), why=why))
    out.sort(key=lambda x: (x["ok"] != x["total"], -x["ok"], x["t"]["full_name"]))
    return out


def suggest_rooms(p):
    busy = build_busy([p["id"]])
    s, e = tomin(p["start"]), tomin(p["end"])
    return [r for r in free_room(busy, p, p["day"], s, e, p["room_id"]) if r["id"] != p["room_id"]]


def notify_change(p, tids, text):
    touch("section", p["section_id"])
    for tid in {t for t in tids if t}:
        touch("teacher", tid)


def apply_move(p, day, s, e, room_id):
    tt, maxday = get_tt(), daily_limit()
    sec = dict(query("SELECT * FROM sections WHERE id=?", (p["section_id"],), one=True))
    teacher = query("SELECT * FROM users WHERE id=?", (p["teacher_id"],), one=True) if p["teacher_id"] else None
    busy = build_busy([p["id"]])
    err = slot_error(busy, sec, dict(teacher) if teacher else None, day, s, e, maxday, tt)
    if err:
        return False, err
    room_ = query("SELECT * FROM rooms WHERE id=?", (room_id,), one=True) if room_id else None
    if room_ and room_["id"] not in [r["id"] for r in free_room(busy, p, day, s, e)]:
        return False, f"{room_['name']} is not free then."
    run("UPDATE classes SET day=?, start=?, end=?, room=?, room_id=? WHERE id=?",
        (day, hhmm(s), hhmm(e), room_["name"] if room_ else None, room_["id"] if room_ else None, p["id"]))
    notify_change(p, [p["teacher_id"]], "moved")
    return True, f"{p['subject']} moved to {day} {t12(hhmm(s))}-{t12(hhmm(e))}."


def apply_room(p, room_id):
    busy = build_busy([p["id"]])
    s, e = tomin(p["start"]), tomin(p["end"])
    room_ = query("SELECT * FROM rooms WHERE id=?", (room_id,), one=True)
    if not room_ or room_["id"] not in [r["id"] for r in free_room(busy, p, p["day"], s, e)]:
        return False, "That room is not free or not the right type."
    run("UPDATE classes SET room=?, room_id=? WHERE id=?", (room_["name"], room_["id"], p["id"]))
    notify_change(p, [p["teacher_id"]], "room")
    return True, f"{p['subject']} now uses {room_['name']}."


def apply_teacher(p, tid):
    cand = next((x for x in suggest_teachers(p) if x["t"]["id"] == tid), None)
    if not cand or cand["ok"] != cand["total"]:
        return False, "That teacher is not free for every meeting of this subject."
    old = p["teacher_id"]
    for m in meetings_of(p):
        run("UPDATE classes SET teacher_id=? WHERE id=?", (tid, m["id"]))
    sub = query("SELECT id FROM subjects WHERE lower(name)=lower(?)", (p["subject"],), one=True)
    if sub:
        run("INSERT OR REPLACE INTO loads(section_id,subject_id,teacher_id) VALUES(?,?,?)", (p["section_id"], sub["id"], tid))
    notify_change(p, [old, tid], "teacher")
    sync_category(tid)
    return True, f"{p['subject']} for {p['sname']} is now taught by {cand['t']['full_name']} (loading updated)."


# ------------------------------------------------------------------ 5. reports and exports
def room_utilization():
    tt = get_tt()
    order = sorted(tt, key=lambda k: tt[k][0][0])
    cap = sum(e - s for per in tt.values() for s, e, k in per if k == "class") * len(DAYS) or 1
    shift_of = {s["id"]: sec_shift(dict(s), tt) for s in query("SELECT * FROM sections")}
    use = defaultdict(lambda: defaultdict(int))
    secs_in = defaultdict(set)
    for c in query("SELECT * FROM classes WHERE kind='class' AND room_id IS NOT NULL"):
        use[c["room_id"]][shift_of.get(c["section_id"], "?")] += tomin(c["end"]) - tomin(c["start"])
        secs_in[c["room_id"]].add(c["section_id"])
    rows = []
    for r in query("SELECT * FROM rooms ORDER BY rtype, name"):
        by = use[r["id"]]
        tot = sum(by.values())
        rows.append(dict(r=r, by={n: by.get(n, 0) for n in order}, total=tot, pct=int(100 * tot / cap),
                         nsec=len(secs_in[r["id"]]), shared=sum(1 for n in order if by.get(n)) > 1, free=cap - tot))
    return dict(rows=rows, order=order, cap=cap)


def entity_grids(kind, ident=None):
    """[(title, subtitle, rows, cells, name)] where cells[row][day] = {'text','span','kind'} | 'skip' | None.
    Each program only shows the periods of its own shift (Grade 11 = AM, Grade 12 = PM)."""
    tt = get_tt()
    table = {"sections": "sections", "teachers": "users", "rooms": "rooms"}[kind]
    where = " WHERE role='teacher'" if kind == "teachers" else ""
    ents = [dict(x) for x in query(f"SELECT * FROM {table}{where} ORDER BY {'grade, name' if kind == 'sections' else 'full_name' if kind == 'teachers' else 'name'}")]
    if ident:
        ents = [x for x in ents if x["id"] == ident]
    secd = {x["id"]: dict(x) for x in query("SELECT * FROM sections")}
    kinds = "('class','homeroom','intervention')" if kind == "sections" else "('class')"
    out = []
    cfg_ = get_cfg()
    for ent in ents:
        col = {"sections": "c.section_id", "teachers": "c.teacher_id", "rooms": "c.room_id"}[kind]
        pers = [dict(r) for r in query(f"""SELECT c.*, s.name AS sname, u.full_name AS tname FROM classes c
                   JOIN sections s ON s.id=c.section_id LEFT JOIN users u ON u.id=c.teacher_id
                   WHERE c.kind IN {kinds} AND {col}=?""", (ent["id"],))]
        if kind == "sections":
            shifts = [sec_shift(ent, tt)]
        else:
            shifts = sorted({sec_shift(secd[p["section_id"]], tt) for p in pers if p["section_id"] in secd})
            if not shifts:
                ts = teacher_shift(ent, tt) if kind == "teachers" else ""
                shifts = [ts] if ts in tt else sorted(tt)
        rows = sorted({(s, e, k) for n in shifts for s, e, k in tt[n]})
        cells = [[None] * len(DAYS) for _ in rows]
        for p in pers:
            s, e = tomin(p["start"]), tomin(p["end"])
            idx = [i for i, (rs, re_, rk) in enumerate(rows) if rs < e and re_ > s and rk == "class"]
            if not idx or p["day"] not in DAYS:
                continue
            di = DAYS.index(p["day"])
            if p["kind"] != "class":
                txt = p["subject"]
            elif kind == "sections":
                txt = f"{p['subject']}\n{p['tname'] or '-'}"  # no room in the class program table
            elif kind == "teachers":
                txt = f"{p['subject']}\n{p['sname']}\n{p['room'] or ''}"
            else:
                txt = f"{p['sname']}\n{p['subject']}\n{p['tname'] or '-'}"
            txt = txt.strip()
            if isinstance(cells[idx[0]][di], dict):
                cells[idx[0]][di]["text"] += "\n" + txt
            else:
                cells[idx[0]][di] = dict(text=txt, span=len(idx), kind=p["kind"])
                for i in idx[1:]:
                    cells[i][di] = "skip"
        if kind == "sections":
            room = (ent["room"] or "").strip()
            room_txt = (room if room.lower().startswith("room") else f"Room {room}") if room else "Room not set"
            title = f"Class Program {ent['name']}" + (f"({ent['track']})" if ent["track"] else "")
            sub = f"Shift {shifts[0]} | {room_txt}"
        elif kind == "teachers":
            title, sub = f"Teacher's Program - {ent['full_name']}", f"Official time: {ent['official_time'] or 'Whole day'}"
        else:
            title, sub = f"Room Program - {ent['name']}", f"{ent['rtype']} (shared across shifts)"
        out.append((title, f"{sub} | {cfg_.get('term', '')}", rows, cells, ent["name"] if "name" in ent else ent["full_name"]))
    return out


def table_report(kind):
    if kind == "loads":
        v = validate_loading()
        head = ["Teacher", "Category", "Official time", "Classes handled", "Different subjects", "Assigned per week",
                "Scheduled per week", "Weekly limit", "Status"]
        data = [[x["t"]["full_name"], x["t"]["category"] or "", x["window"], x["nsec"], x["npre"], hm_text(x["minutes"]),
                 hm_text(x["sched"]), hm_text(v["maxweek"]), x["status"]] for x in v["rows"]]
        return "Teacher Teaching-Load Summary", head, data
    u = room_utilization()
    head = ["Room", "Type"] + [f"{n} per week" for n in u["order"]] + ["Total per week", "Utilization", "Sections", "Shared by shifts"]
    data = [[x["r"]["name"], x["r"]["rtype"]] + [hm_text(x["by"][n]) for n in u["order"]] +
            [hm_text(x["total"]), f"{x['pct']}%", x["nsec"], "Yes" if x["shared"] else "No"] for x in u["rows"]]
    return "Room Utilization Report", head, data


def build_xlsx(kind, ident):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    wb, thin = Workbook(), Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DCE3F7")
    wb.remove(wb.active)
    names = set()

    def sheet(title):
        base = re.sub(r"[\[\]\\/*?:]", "-", title)[:28] or "Sheet"
        n, i = base, 2
        while n in names:
            n, i = f"{base[:25]}-{i}", i + 1
        names.add(n)
        return wb.create_sheet(n)
    if kind in ("loads", "utilization"):
        title, head, data = table_report(kind)
        ws = sheet(title)
        ws.append([title])
        ws["A1"].font = Font(bold=True, size=14)
        ws.append([get_cfg().get("school_name", ""), get_cfg().get("term", "")])
        ws.append([])
        ws.append(head)
        for c in ws[4]:
            c.font, c.fill, c.border = Font(bold=True), head_fill, box
        for r in data:
            ws.append(r)
        for row in ws.iter_rows(min_row=5):
            for c in row:
                c.border = box
        for i, col in enumerate(ws.columns):
            ws.column_dimensions[col[0].column_letter].width = 26 if i == 0 else 20
    else:
        for title, sub, rows, cells, name in entity_grids(kind, ident):
            ws = sheet(name)
            ws["A1"], ws["A2"] = title, sub
            ws["A1"].font = Font(bold=True, size=14)
            ws["A2"].font = Font(size=10, color="444444")
            for rr in (1, 2):
                ws.merge_cells(start_row=rr, start_column=1, end_row=rr, end_column=1 + len(DAYS))
                ws.cell(row=rr, column=1).alignment = Alignment(horizontal="left", vertical="center")
            ws.row_dimensions[1].height = 24
            for j, h in enumerate(["Time"] + DAYS):
                c = ws.cell(row=4, column=j + 1, value=h)
                c.font, c.fill, c.border, c.alignment = Font(bold=True), head_fill, box, Alignment(horizontal="center")
            for i, (s, e, k) in enumerate(rows):
                r = 5 + i
                tc = ws.cell(row=r, column=1, value=f"{t12(hhmm(s))} - {t12(hhmm(e))}")
                tc.border, tc.alignment = box, Alignment(horizontal="center", vertical="center")
                if k == "recess":
                    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=1 + len(DAYS))
                    c = ws.cell(row=r, column=2, value="RECESS")
                    c.alignment = Alignment(horizontal="center", vertical="center")
                    c.fill, c.font = PatternFill("solid", fgColor="EEEEEE"), Font(bold=True)
                    for j in range(2, 2 + len(DAYS)):
                        ws.cell(row=r, column=j).border = box
                    ws.row_dimensions[r].height = 22
                    continue
                for d in range(len(DAYS)):
                    cell = cells[i][d]
                    c = ws.cell(row=r, column=2 + d)
                    c.border = box
                    if isinstance(cell, dict):
                        c.value = cell["text"]
                        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
                        plain = cell.get("kind") in ("homeroom", "intervention")
                        c.fill = PatternFill("solid", fgColor="F3F3F3" if plain else "E8F0FE")
                        if plain:
                            c.font = Font(bold=True)
                        if cell["span"] > 1:
                            ws.merge_cells(start_row=r, start_column=2 + d, end_row=r + cell["span"] - 1, end_column=2 + d)
                ws.row_dimensions[r].height = 52
                if k == "recess":
                    ws.row_dimensions[r].height = 22
            ws.column_dimensions["A"].width = 22
            for d in range(len(DAYS)):
                ws.column_dimensions[chr(66 + d)].width = 26
            ws.page_setup.orientation = "landscape"
            ws.page_setup.fitToWidth = 1
            ws.page_setup.fitToHeight = 1
            from openpyxl.worksheet.properties import PageSetupProperties
            ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    if not wb.sheetnames:
        wb.create_sheet("Empty")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def build_pdf(kind, ident):
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    st = getSampleStyleSheet()
    small = ParagraphStyle("s", parent=st["BodyText"], fontSize=7.5, leading=9, alignment=1)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24,
                            title="Class Scheduler")
    flow = []
    base = [("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE3F7")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    if kind in ("loads", "utilization"):
        title, head, data = table_report(kind)
        flow += [Paragraph(escape(title), st["Title"]), Paragraph(escape(f"{get_cfg().get('school_name', '')} - {get_cfg().get('term', '')}"), st["Normal"]), Spacer(1, 10)]
        t = Table([[Paragraph(f"<b>{escape(str(h))}</b>", small) for h in head]] +
                  [[Paragraph(escape(str(c)), small) for c in r] for r in data], repeatRows=1)
        t.setStyle(TableStyle(base))
        flow.append(t)
    else:
        grids = entity_grids(kind, ident)
        for n, (title, sub, rows, cells, _name) in enumerate(grids):
            if n:
                flow.append(PageBreak())
            flow += [Paragraph(escape(title), st["Heading2"]), Paragraph(escape(sub), st["Normal"]), Spacer(1, 8)]
            data = [[Paragraph("<b>Time</b>", small)] + [Paragraph(f"<b>{d}</b>", small) for d in DAYS]]
            style = list(base)
            for i, (s, e, k) in enumerate(rows):
                r = i + 1
                line = [Paragraph(escape(f"{t12(hhmm(s))} - {t12(hhmm(e))}"), small)]
                if k == "recess":
                    line += [Paragraph("RECESS", small)] + [""] * (len(DAYS) - 1)
                    style += [("SPAN", (1, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), colors.HexColor("#EEEEEE"))]
                else:
                    for d in range(len(DAYS)):
                        c = cells[i][d]
                        line.append(Paragraph(escape(c["text"]).replace("\n", "<br/>"), small) if isinstance(c, dict) else "")
                        if isinstance(c, dict):
                            style.append(("BACKGROUND", (d + 1, r), (d + 1, r), colors.HexColor("#E8F0FE")))
                            if c["span"] > 1:
                                style.append(("SPAN", (d + 1, r), (d + 1, r + c["span"] - 1)))
                data.append(line)
            need = [34] * len(rows)  # tall enough for the text of every cell
            for i in range(len(rows)):
                for d in range(len(DAYS)):
                    c = cells[i][d]
                    if isinstance(c, dict) and rows[i][2] == "class":
                        h = Paragraph(escape(c["text"]).replace("\n", "<br/>"), small).wrap(145 - 12, 1000)[1] + 10
                        for q in range(i, min(len(rows), i + c["span"])):
                            need[q] = max(need[q], h / c["span"])
                    if isinstance(c, dict) and c.get("kind") in ("homeroom", "intervention"):
                        style.append(("BACKGROUND", (d + 1, i + 1), (d + 1, i + 1), colors.HexColor("#F3F3F3")))
            need = [22 if rows[i][2] == "recess" else need[i] for i in range(len(rows))]
            t = Table(data, colWidths=[85] + [145] * len(DAYS), rowHeights=[18] + need)
            t.setStyle(TableStyle(style))
            flow.append(t)
    if not flow:
        flow.append(Paragraph("Nothing to export yet.", st["Normal"]))
    doc.build(flow)
    buf.seek(0)
    return buf


# ------------------------------------------------------------------ routes
@app.route("/admin/time-allocation")
@login_required("admin")
def auto_time():
    ta = time_allocation()
    res, q = None, request.args.get("find", "")
    L = to_int(request.args.get("length"), 10, 480) or 60
    if ":" in q:
        kind, _, ident = q.partition(":")
        if kind in ("section", "teacher", "room") and ident.isdigit():
            res = dict(kind=kind, id=int(ident), L=L, free=free_slots(kind, int(ident), L))
    return render_template("auto_time.html", ta=ta, res=res, q=q, L=L,
                           secs=sched_secs(),
                           tchs=query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name"),
                           rooms_=query("SELECT * FROM rooms ORDER BY name"), days=DAYS)


@app.route("/admin/conflicts", methods=["GET", "POST"])
@login_required("admin")
def auto_conflicts():
    """09 Validation Center: the system detects conflicts and suggests alternatives; the administrator
    approves the corrections and finally approves (locks) the schedule."""
    if request.method == "POST":
        f = request.form
        act = f.get("action")
        if act == "approve":
            chk, lv = check_program(), validate_loading()
            if not chk["rows"]:
                flash("There is no class program to approve yet.", "error")
            elif blocking_program_issues(chk) or lv["issues"]:
                flash(f"Fix the {len(blocking_program_issues(chk)) + len(lv['issues'])} problem(s) first, then approve.", "error")
            elif stale_ids():
                flash("Some programs are out of date. Regenerate them before approving.", "error")
            else:
                sset("approved_at", ph_stamp())
                sset("approved_by", g.user["full_name"])
                sset("approved_periods", chk["rows"])
                flash("Schedule approved and locked. Reports are now final.", "ok")
        elif act == "reopen":
            sset("approved_at", "")
            flash("The schedule was reopened. You can edit again; approve it once more when done.", "ok")
        elif act == "move":
            p = period_row(f.get("period", type=int))
            if not p:
                abort(404)
            ok, msg = apply_move(p, f.get("day"), tomin(f.get("start")), tomin(f.get("end")), f.get("room_id", type=int))
            flash(msg, "ok" if ok else "error")
        return redirect(url_for("auto_conflicts"))
    chk = check_program()
    sugg, n = {}, 0
    for x in chk["entries"]:
        if x["sev"] == "issue" and x["pid"] and x["kind"] in ("teacher", "section", "room", "room-shift", "window", "shift", "roomtype") \
                and x["pid"] not in sugg and n < 10:
            p = period_row(x["pid"])
            if p:
                sugg[x["pid"]] = dict(p=p, slots=suggest_slots(p, 3))
                n += 1
    return render_template("auto_conflicts.html", chk=chk, lv=validate_loading(), sugg=sugg)


@app.route("/admin/exports")
@login_required("admin")
def auto_reports():
    return render_template("auto_reports.html", lv=validate_loading(), ru=room_utilization(),
                           secs=sched_secs(),
                           tchs=query("SELECT * FROM users WHERE role='teacher' ORDER BY full_name"),
                           rooms_=query("SELECT * FROM rooms ORDER BY name"))


@app.route("/admin/export/<kind>.<fmt>")
@login_required("admin")
def auto_export(kind, fmt):
    if kind not in ("sections", "teachers", "rooms", "loads", "utilization") or fmt not in ("xlsx", "pdf"):
        abort(404)
    ident = request.args.get("id", type=int)
    try:
        buf = build_xlsx(kind, ident) if fmt == "xlsx" else build_pdf(kind, ident)
    except ImportError:
        flash("Exports need two extra packages. Run:  pip install openpyxl reportlab", "error")
        return redirect(url_for("auto_reports"))
    mime = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx" else "application/pdf")
    return send_file(buf, mimetype=mime, as_attachment=True,
                     download_name=f"{kind}{'-' + str(ident) if ident else ''}.{fmt}")



# ======================================================================================
# ADMIN MODULES: DASHBOARD, CURRICULUM MANAGEMENT, USER MANAGEMENT AND THE AUDIT TRAIL
# ======================================================================================
MIN_SQL = ("(CASE WHEN start ~ '^[0-9]{2}:[0-9]{2}' AND end ~ '^[0-9]{2}:[0-9]{2}' THEN "
           "((CAST(substr(end,1,2) AS INTEGER)*60+CAST(substr(end,4,2) AS INTEGER))"
           "-(CAST(substr(start,1,2) AS INTEGER)*60+CAST(substr(start,4,2) AS INTEGER))) ELSE 0 END)")


def setup_status():
    """Progress of the whole scheduling process, in the same order as the main navigation."""
    cfg = get_cfg()
    tt = get_tt()
    secs = [dict(s) for s in sched_secs()]
    tchs = [dict(t) for t in query("SELECT * FROM users WHERE role='teacher' ORDER BY id")]
    lv, chk = validate_loading(), check_program()
    ps = programs_status(chk, lv)
    prog_issues = ps["issues"]
    n_core = query("SELECT COUNT(*) AS n FROM subjects WHERE kind='core' AND COALESCE(offered,1)=1", one=True)["n"]
    n_off = query("SELECT COUNT(*) AS n FROM subjects WHERE kind='cluster' AND COALESCE(offered,1)=1", one=True)["n"]
    n_clu = query("SELECT COUNT(*) AS n FROM subjects WHERE kind='cluster'", one=True)["n"]
    rooms_n = query("SELECT COUNT(*) AS n FROM rooms", one=True)["n"]
    stale = [s for s in secs if s["id"] in stale_ids()]
    no_cluster = [s for s in secs if not s["track"] or not s["cluster"]]
    no_spec = [t for t in tchs if not (t["specialization"] or "").strip()]
    no_time = [t for t in tchs if not (t["official_time"] or "").strip()]
    with_prog = {r["section_id"] for r in query("SELECT DISTINCT section_id FROM classes WHERE kind='class'")}
    unsched = [s for s in secs if s["id"] not in with_prog]
    miss_rt = missing_room_types()
    no_subjects = [s for s in secs if not query("SELECT 1 FROM section_subjects WHERE section_id=?", (s["id"],), one=True)]
    appr = approval()
    sy_ok = bool(re.search(r"SY\s*\d{4}-\d{4}", cfg["term"] or "")) and bool(cfg["school_name"])
    tt_saved = bool(gset("tt_text", ""))
    all_sched = bool(secs) and not unsched and not stale
    all_ok = ps["complete"]
    steps = [
        dict(num=1, title="Add the sections", ep="quick_input", anchor="#sections", done=bool(secs) and not no_cluster,
             text=(f"{len(secs)} section(s)" + (f"; {len(no_cluster)} need a track and cluster" if no_cluster else "")
                   if secs else "No sections yet")),
        dict(num=2, title="Add the teachers and their subjects", ep="quick_input", anchor="#teachers", done=bool(tchs) and not no_spec,
             text=(f"{len(tchs)} teacher(s)" + (f"; {len(no_spec)} without subjects" if no_spec else "")
                   if tchs else "No teachers yet")),
        dict(num=3, title="Generate the class programs", ep="auto_generate", anchor="", done=all_ok,
             text=(f"{len(secs) - len(unsched)} of {len(secs)} sections scheduled"
                   + (f"; {len(stale)} out of date" if stale else "")
                   + (f"; {len(prog_issues)} conflict(s)" if prog_issues else "")) if secs else "Add sections first"),
        dict(num=4, title="Check, approve and print", ep="auto_conflicts", anchor="#approval", done=bool(appr),
             text=(f"Approved by {appr['by']} on {appr['at']}" if appr else "Not approved yet")),
    ]
    alerts = []

    def alert(level, text, ep, label):
        alerts.append(dict(level=level, text=text, href=url_for(ep), label=label))
    p = query("SELECT COUNT(*) AS n FROM signup_requests", one=True)["n"]
    if p:
        alert("warn", f"{p} teacher account request(s) are waiting for approval.", "reports", "Review")
    p = query("SELECT COUNT(*) AS n FROM reports WHERE resolved=0", one=True)["n"]
    if p:
        alert("warn", f"{p} problem report(s) are not resolved yet.", "reports", "Open")
    if no_cluster:
        alert("bad", "Set a track and cluster for: " + ", ".join(s["name"] for s in no_cluster[:6])
              + ("..." if len(no_cluster) > 6 else "") + ".", "sections", "Fix")
    if no_spec:
        alert("warn", f"{len(no_spec)} teacher(s) have no specialization, so they cannot be loaded automatically.",
              "teachers", "Fix")
    for i in lv["issues"][:4]:
        alert("bad", i, "auto_loading", "Fix")
    if len(lv["issues"]) > 4:
        alert("bad", f"...and {len(lv['issues']) - 4} more loading problem(s).", "auto_loading", "See all")
    if stale:
        alert("warn", "Loading changed after the program was made for: " + ", ".join(s["name"] for s in stale[:6]) + ".",
              "auto_generate", "Regenerate")
    if secs and unsched:
        alert("warn", f"{len(unsched)} section(s) have no class program yet.", "auto_generate", "Generate")
    for i in prog_issues[:4]:
        alert("bad", i, "auto_conflicts", "Fix")
    if len(prog_issues) > 4:
        alert("bad", f"...and {len(prog_issues) - 4} more schedule problem(s).", "auto_conflicts", "See all")
    if all_ok and not appr:
        alert("warn", "Everything checks out. Approve the schedule to lock this version.", "auto_conflicts", "Approve")
    done = sum(1 for s in steps if s["done"])
    nxt = next((s for s in steps if not s["done"]), None)
    prog = []
    for s in secs:
        need = query("""SELECT COALESCE(SUM(b.weekly_min),0) AS m FROM section_subjects ss
                        JOIN subjects b ON b.id=ss.subject_id WHERE ss.section_id=?""", (s["id"],), one=True)["m"]
        got = query(f"SELECT COALESCE(SUM({MIN_SQL}),0) AS m FROM classes WHERE section_id=? AND kind='class'",
                    (s["id"],), one=True)["m"]
        nsub = query("SELECT COUNT(*) AS n FROM section_subjects WHERE section_id=?", (s["id"],), one=True)["n"]
        nload = query("""SELECT COUNT(*) AS n FROM loads l JOIN section_subjects x ON x.section_id=l.section_id
                         AND x.subject_id=l.subject_id WHERE l.section_id=? AND l.teacher_id IS NOT NULL""",
                      (s["id"],), one=True)["n"]
        prog.append(dict(s=s, need=need, got=got, nsub=nsub, nload=nload,
                         pct=min(100, int(100 * got / need)) if need else 0))
    kpis = dict(sections=len(secs), teachers=len(tchs), rooms=rooms_n, subjects=n_core + n_off, scheduled=len(with_prog),
                periods=chk["rows"], conflicts=len(prog_issues))
    return dict(steps=steps, alerts=alerts, done=done, total=len(steps), pct=int(100 * done / len(steps)),
                nxt=nxt, prog=prog, kpis=kpis)


@app.route("/admin/dashboard")
@login_required("admin")
def dashboard():
    recent = dict(
        sections=query("SELECT name FROM sections ORDER BY id DESC LIMIT 5"),
        teachers=query("SELECT full_name FROM users WHERE role='teacher' ORDER BY id DESC LIMIT 5"),
        rooms=query("SELECT name, rtype FROM rooms ORDER BY id DESC LIMIT 5"))
    return render_template("dashboard.html", st=setup_status(), today=today_text(), recent=recent)


# ---------------------------------------------------------------- curriculum
def subj_locks(cur):
    """Fields that cannot be edited: the type and track of every subject, and the name of a built-in one."""
    return ["kind", "track"] + (["name"] if not cur["custom"] else []) + (["offered"] if cur["kind"] == "core" else [])


def audit_subject(action, sub_name, sid):
    audit_event(g.user, action, f"{sub_name} (subject id {sid})")


def set_subject_status(sub, new):
    """Active / inactive / archived. Leaving 'active' removes the subject from section requirements and teaching
    loads, so it cannot enter a newly generated schedule. Existing class periods, teacher qualifications and
    specializations are kept as history; the affected programs are marked out of date. Returns (ok, message)."""
    old = subj_status(sub)
    if new not in SUBJECT_STATUSES:
        return False, "Choose Active, Inactive or Archived."
    if new == old:
        return True, ""
    if new != "active" and (sub["kind"] or "") == "core" and not sub["custom"] \
            and query("SELECT 1 FROM sections LIMIT 1", one=True):
        return False, (f"{sub['name']} is a built-in core subject that every section needs, so it cannot be "
                       "made inactive while sections exist.")
    sid = sub["id"]
    run("UPDATE subjects SET status=?, offered=?, edited=1 WHERE id=?", (new, 1 if new == "active" else 0, sid))
    if new != "active":
        secs = [r["section_id"] for r in query("SELECT section_id FROM section_subjects WHERE subject_id=?", (sid,))]
        run("DELETE FROM section_subjects WHERE subject_id=?", (sid,))
        run("DELETE FROM loads WHERE subject_id=?", (sid,))
    else:
        for r in query("SELECT id FROM sections"):
            sync_section_subjects(r["id"])
        secs = [r["section_id"] for r in query("SELECT section_id FROM section_subjects WHERE subject_id=?", (sid,))]
    stale = [x for x in secs if query("SELECT 1 FROM classes WHERE section_id=? AND kind='class'", (x,), one=True)]
    if stale:
        mark_stale(stale)
    audit_subject({"active": "Subject reactivated", "inactive": "Subject deactivated",
                   "archived": "Subject archived"}[new], sub["name"], sid)
    return True, ""


def subjects_page(sf=None, sf_err=None, blocked=None):
    subs = [dict(s) for s in query("SELECT * FROM subjects ORDER BY id")]
    used = {r["subject_id"]: r["n"] for r in query("SELECT subject_id, COUNT(*) AS n FROM section_subjects GROUP BY subject_id")}
    show_arch = bool(request.args.get("archived"))
    for s in subs:
        s["used"] = used.get(s["id"], 0)
        s["offered"] = 1 if s["offered"] is None else s["offered"]
        s["custom"] = 1 if s.get("custom") else 0
        s["status"] = subj_status(s)
        s["grade"] = s["grade"] or 0
    n_arch = sum(1 for s in subs if s["status"] == "archived")
    if not show_arch:
        subs = [s for s in subs if s["status"] != "archived"]
    page = render_template("curriculum.html", core=[s for s in subs if s["kind"] == "core"],
                           academic=[s for s in subs if s["kind"] == "cluster" and s["track"] == "Academic"],
                           techpro=[s for s in subs if s["kind"] == "cluster" and s["track"] == "TechPro"],
                           rtypes=rtype_options(), missing_types=missing_room_types(), sf=sf, sf_err=sf_err,
                           blocked=blocked, show_arch=show_arch,
                           n_arch=n_arch, new_ids=",".join(str(i) for i in session.pop("new_subjects", [])))
    return (page, 400) if sf_err else page


def subject_save(f):
    """Add a subject, or edit one. An edit updates the same database row; it never creates a copy."""
    sid = f.get("sid", type=int)
    cur = query("SELECT * FROM subjects WHERE id=?", (sid,), one=True) if sid else None
    if sid and not cur:
        flash("That subject no longer exists.", "error")
        return redirect(url_for("curriculum"))
    custom = (not cur) or bool(cur["custom"])
    kind = cur["kind"] if cur else (f.get("kind") or "")
    track = (cur["track"] or "") if cur else (f.get("track") or "")
    if cur and custom and kind == "cluster" and f.get("track"):
        track = f.get("track")
    name = cur["name"] if (cur and not custom) else clean(f.get("name"), 80)
    code, rtype, detail = clean(f.get("code"), 20), clean(f.get("rtype")) or "Regular", clean(f.get("detail"), 200)
    wk, se = to_int(f.get("weekly_min"), 30, 2400), to_int(f.get("session_min"), 10, 480)
    grade_raw = f.get("grade") if f.get("grade") not in (None, "") else (cur["grade"] if cur else 0)
    grade = to_int(grade_raw, 0, 12)
    status = (f.get("status") or (subj_status(cur) if cur else "active")).strip().lower()
    vals = dict(sid=sid or "", name=name, code=code, kind=kind, track=track or "Academic", weekly_min=f.get("weekly_min", ""),
                session_min=f.get("session_min", ""), rtype=rtype, grade=grade or 0, status=status, detail=detail,
                _mode="edit" if cur else "new", _title="Edit subject" if cur else "Add subject",
                _lock=subj_locks(cur) if cur else [], _note="")
    err = None
    if kind not in ("core", "cluster"):
        err = "Choose the subject type."
    elif not name:
        err = "Enter the subject name."
    elif not code:
        err = "Enter the subject code."
    elif kind == "cluster" and track not in ("Academic", "TechPro"):
        err = "Choose the track of the cluster."
    elif grade not in (0, 11, 12):
        err = "Choose the grade level: both, Grade 11 or Grade 12."
    elif wk is None or se is None:
        err = "Minutes per week must be 30 to 2400 and minutes per meeting 10 to 480."
    elif se > wk:
        err = "A meeting cannot be longer than the whole week."
    elif rtype not in set(rtype_options()):
        err = "Choose a room type from the list."
    elif status not in SUBJECT_STATUSES:
        err = "Choose Active, Inactive or Archived."
    elif query("SELECT 1 FROM subjects WHERE lower(name)=lower(?) AND id!=?", (name, sid or 0), one=True):
        err = f"A subject named {name} already exists."
    elif query("SELECT 1 FROM subjects WHERE lower(code)=lower(?) AND id!=?", (code, sid or 0), one=True):
        err = f"The code {code} is already used by another subject."
    if not err and cur and kind == "cluster":
        users = [x["name"] for x in query("SELECT name FROM sections WHERE cluster=?", (cur["name"],))]
        if users and track != (cur["track"] or ""):
            err = "The track cannot change while sections use this cluster."
    if not err and cur and status != subj_status(cur):
        if (kind == "core" and not custom and status != "active"
                and query("SELECT 1 FROM sections LIMIT 1", one=True)):
            err = (f"{cur['name']} is a built-in core subject that every section needs, so it cannot be made "
                   "inactive while sections exist.")
    if err:
        return subjects_page(sf=vals, sf_err=err)
    if not cur:
        conn = db()
        try:
            made = conn.execute("""INSERT INTO subjects(code,name,area,grade,track,weekly_min,session_min,rtype,kind,detail,
                                   offered,custom,edited,status) VALUES(?,?,?,?,?,?,?,?,?,?,1,1,1,'active')""",
                                (code, name, name, grade, track if kind == "cluster" else "", wk, se, rtype, kind,
                                 detail or None))
            conn.commit()
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            return subjects_page(sf=vals, sf_err=f"{name} (or its code) already exists. Nothing was saved.")
        new_id = made.lastrowid
        for x in query("SELECT id FROM sections"):          # core subjects reach every section; electives follow the section's choice
            sync_section_subjects(x["id"])
        audit_subject("Subject created", name, new_id)
        session["new_subjects"] = (session.get("new_subjects") or []) + [new_id]
        flash(f"{name} was added and saved." + (" Every section now has it." if kind == "core" else
              " Choose it as the elective of a section in Section Management."), "ok")
        return redirect(url_for("curriculum"))
    old = (cur["weekly_min"], cur["session_min"], cur["rtype"], cur["grade"] or 0)
    if custom:
        run("""UPDATE subjects SET code=?, name=?, area=?, track=?, grade=?, weekly_min=?, session_min=?, rtype=?,
               detail=?, edited=1 WHERE id=?""",
            (code, name, name, track if kind == "cluster" else "", grade, wk, se, rtype, detail or None, sid))
        if kind == "cluster" and name != cur["name"]:
            run("UPDATE sections SET cluster=? WHERE cluster=?", (name, cur["name"]))
        if name != cur["name"]:
            # teachers' specializations and class periods keep the subject as text: follow the rename everywhere
            old_n = _qnorm(cur["name"])
            for t in query("SELECT id, specialization FROM users WHERE role='teacher' AND specialization<>''"):
                ents = [x.strip() for x in re.split(r"[;\n]+", t["specialization"]) if x.strip()]
                renamed = [name if _qnorm(x) == old_n else x for x in ents]
                if renamed != ents:
                    run("UPDATE users SET specialization=? WHERE id=?", (SPEC_SEP.join(renamed), t["id"]))
            run("UPDATE classes SET subject=? WHERE subject=?", (name, cur["name"]))
    else:
        run("UPDATE subjects SET code=?, weekly_min=?, session_min=?, rtype=?, detail=?, edited=1 WHERE id=?",
            (code, wk, se, rtype, detail or None, sid))
    fresh = query("SELECT * FROM subjects WHERE id=?", (sid,), one=True)
    if status != subj_status(fresh):
        ok_, why = set_subject_status(fresh, status)
        if not ok_:
            return subjects_page(sf=vals, sf_err=why)
    if old != (wk, se, rtype, grade or 0):
        for x in query("SELECT id FROM sections"):
            sync_section_subjects(x["id"])
        for r in query("SELECT DISTINCT section_id FROM section_subjects WHERE subject_id=?", (sid,)):
            if query("SELECT 1 FROM classes WHERE section_id=? AND kind='class'", (r["section_id"],), one=True):
                mark_stale([r["section_id"]])
    audit_subject("Subject edited", name, sid)
    flash(f"{name} was updated.", "ok")
    return redirect(url_for("curriculum"))


def subject_status_action(f):
    sub = query("SELECT * FROM subjects WHERE id=?", (f.get("sid", type=int),), one=True)
    if not sub:
        flash("That subject no longer exists.", "error")
        return redirect(url_for("curriculum"))
    new = (f.get("status") or "").lower()
    ok, why = set_subject_status(sub, new)
    if not ok:
        flash(why, "error")
    elif new == subj_status(sub):
        flash(f"{sub['name']} is already {new}.", "ok")
    elif new == "active":
        flash(f"{sub['name']} is active again and available for new selections and schedules.", "ok")
    else:
        flash(f"{sub['name']} is now {new}. It no longer appears in new selections or new schedules; "
              "existing records were kept.", "ok")
    return redirect(url_for("curriculum"))


def subject_delete(f):
    """Permanent delete, only for a subject nothing uses. Otherwise nothing is deleted: the page explains what
    still uses it and offers Deactivate or Archive. Class periods and other history are never removed here."""
    sub = query("SELECT * FROM subjects WHERE id=?", (f.get("sid", type=int),), one=True)
    if not sub:
        flash("That subject no longer exists.", "error")
        return redirect(url_for("curriculum"))
    deps = subject_dependencies(sub)
    if deps or not sub["custom"]:
        return subjects_page(blocked=dict(sub=sub, deps=deps, builtin=not sub["custom"]))
    try:
        run("DELETE FROM subjects WHERE id=?", (sub["id"],))
    except psycopg.Error:
        app.logger.exception("subject delete failed for id %s", sub["id"])
        flash(f"{sub['name']} could not be deleted because the database still references it. Nothing was changed.", "error")
        return redirect(url_for("curriculum"))
    audit_subject("Subject deleted", sub["name"], sub["id"])
    flash(f"{sub['name']} was permanently deleted.", "ok")
    return redirect(url_for("curriculum"))


@app.route("/admin/subjects", methods=["GET", "POST"])
@login_required("admin")
def curriculum():
    """Subject Management: the Strengthened Curriculum subjects (names fixed) plus the subjects an administrator
    adds. The school edits what it offers and the time and room each subject needs."""
    if request.method == "POST":
        f = request.form
        if f.get("action") == "subject_save":
            return subject_save(f)
        if f.get("action") == "subject_delete":
            return subject_delete(f)
        if f.get("action") == "subject_status":
            return subject_status_action(f)
        if f.get("action") == "reset":
            for _c, name, _a, _g, _t, wk, se, rt, _k, _d in curriculum_rows():
                ensure_room_type(rt)                       # a starting value must exist on the Room Types list
                run("UPDATE subjects SET weekly_min=?, session_min=?, rtype=? WHERE lower(name)=lower(?)",
                    (wk, se, rt, name))
            flash("Minutes and room types were set back to the starting values.", "ok")
            return redirect(url_for("curriculum"))
        bad, blocked, changed = 0, [], set()
        valid_rtypes = set(rtype_options())
        for s in query("SELECT * FROM subjects"):
            i = s["id"]
            if f"wk_{i}" not in f:
                continue
            wk, se = to_int(f.get(f"wk_{i}"), 30, 2400), to_int(f.get(f"se_{i}"), 10, 480)
            if wk is None or se is None:
                bad += 1
                continue
            rt = clean(f.get(f"rtype_{i}")) or "Regular"
            if rt not in valid_rtypes:                      # only room types on the Room Types list can be chosen
                rt = s["rtype"] or "Regular"
            st_now = subj_status(s)
            if st_now == "archived":                       # archived subjects keep their state; only the numbers can change
                off = 0
            else:
                off = 1 if (s["kind"] or "") == "core" or f.get(f"off_{i}") else 0
            old = (s["weekly_min"], s["session_min"], s["rtype"], 1 if s["offered"] is None else s["offered"])
            if old != (wk, se, rt, off):
                changed.add(i)
            run("UPDATE subjects SET weekly_min=?, session_min=?, rtype=? WHERE id=?", (wk, se, rt, i))
            if st_now != "archived" and bool(off) != (st_now == "active"):
                ok_, why = set_subject_status(query("SELECT * FROM subjects WHERE id=?", (i,), one=True),
                                              "active" if off else "inactive")
                if not ok_:
                    blocked.append(why)
        for i in changed:
            for r in query("SELECT DISTINCT section_id FROM section_subjects WHERE subject_id=?", (i,)):
                if query("SELECT 1 FROM classes WHERE section_id=? AND kind='class'", (r["section_id"],), one=True):
                    mark_stale([r["section_id"]])
        ensure_room_types()
        if bad:
            flash(f"{bad} subject(s) had invalid minutes (30-2400 per week, 10-480 per meeting) and were skipped.", "error")
        if blocked:
            flash(" ".join(blocked), "error")
        if not bad and not blocked:
            flash("Subjects saved." + (" Programs of sections that use changed subjects are marked out of date."
                                         if changed else ""), "ok")
        return redirect(url_for("curriculum"))
    return subjects_page()



# ---------------------------------------------------------------- final approval (lock)
def approval():
    at = gset("approved_at", "")
    return dict(at=at, by=gset("approved_by", ""), periods=gset("approved_periods", "0")) if at else None


LOCKED_EP = {"entry_add", "entry_edit", "entry_delete", "auto_loading", "auto_quals", "section_edit",
             "section_delete", "teacher_delete", "curriculum", "auto_rooms"}
LOCKED_ACT = {"auto_generate": {"generate", "apply", "regen", "quick"}, "auto_conflicts": {"move"},
              "settings": {"timetable", "import_tt", "reset_tt"},
              "quick_input": {"save_sections", "edit_section", "delete_section", "save_new_teachers",
                     "edit_teacher", "delete_teacher", "save_rooms", "edit_room", "delete_room", "run"}}


@app.before_request
def lock_guard():
    """Once the administrator approves the schedule, anything that could change it is refused."""
    if request.method != "POST" or not g.get("user") or g.user["role"] != "admin":
        return None
    ep, act = request.endpoint, request.form.get("action")
    if ep in LOCKED_EP or act in LOCKED_ACT.get(ep, ()):
        if approval():
            flash("The schedule is approved and locked. Reopen it in Validation Center (Final approval) to make changes.", "error")
            return redirect(request.referrer or url_for("dashboard"))
    return None


def parse_time_cell(v):
    import datetime
    if isinstance(v, (datetime.datetime, datetime.time)):
        return v.hour * 60 + v.minute
    if isinstance(v, (int, float)) and 0 <= v < 1:
        return int(round(v * 1440))
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?$", str(v or "").strip(), re.I)
    if not m:
        return None
    h, mi, ap = int(m[1]), int(m[2]), (m[3] or "").upper()
    h = h + 12 if ap == "PM" and h < 12 else (0 if ap == "AM" and h == 12 else h)
    return h * 60 + mi if h < 24 and mi < 60 else None


def read_tt_excel(fileobj):
    """Rows of: Shift | Start | End | Type (class or recess). A header row is skipped."""
    from openpyxl import load_workbook
    ws = load_workbook(fileobj, data_only=True).active
    lines, errs = [], []
    for i, row in enumerate(ws.iter_rows(values_only=True), 1):
        row = list(row) + [None] * 4
        if all(c is None or str(c).strip() == "" for c in row[:4]):
            continue
        s, e = parse_time_cell(row[1]), parse_time_cell(row[2])
        name = re.sub(r"\s+", "", str(row[0] or "")).upper()
        if s is None or e is None:
            if i > 1:
                errs.append(f"Row {i}: the start or end time is not a time like 06:00 or 6:00 AM.")
            continue
        if not name:
            errs.append(f"Row {i}: the shift name (for example AM or PM) is missing.")
        elif e <= s:
            errs.append(f"Row {i}: the end time must be later than the start time.")
        else:
            kind = str(row[3] or "").strip().lower()
            lines.append(f"{name} {hhmm(s)}-{hhmm(e)}" + (" recess" if kind in ("recess", "break") else ""))
    return "\n".join(lines) + "\n", errs


@app.route("/admin/timetable-template.xlsx")
@login_required("admin")
def tt_template():
    try:
        from openpyxl import Workbook
    except ImportError:
        flash("Excel needs a package. Run:  pip install openpyxl", "error")
        return redirect(url_for("settings"))
    wb = Workbook()
    ws = wb.active
    ws.title = "Time slots"
    ws.append(["Shift", "Start", "End", "Type"])
    for name, per in get_tt().items():
        for s, e, k in per:
            ws.append([name, hhmm(s), hhmm(e), "recess" if k == "recess" else "class"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="timetable-template.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")



# ---------------------------------------------------------------- quick input (central school set-up)
def unique_username(name):
    base = re.sub(r"[^a-z0-9]", "", name.lower())[:20] or "teacher"
    u, n = base, 1
    while query("SELECT 1 FROM users WHERE lower(username)=lower(?)", (u,), one=True) or \
            query("SELECT 1 FROM signup_requests WHERE lower(username)=lower(?)", (u,), one=True):
        n += 1
        u = f"{base}{n}"
    return u


QI_MAX_ROWS = 200      # most input fields one Save All may carry
QI_NAME_MAX = 60


def qi_short(name):
    """'Grade 11 - Chef', '11-Chef' and 'Chef' all become 'Chef' (the grade prefix is added when saving)."""
    return re.sub(r"^\s*(?:grade\s*)?1[12]\s*[-\u2013]\s*|^\s*grade\s*1[12]\s+", "", name or "", flags=re.I).strip()


def qi_name_key(name):
    return " ".join(name_key(name))


def qi_track_of(item):
    """Academic / TechPro for a cluster or a TechPro specialization; '' for a core subject or an unknown entry."""
    cluster = SPEC_TO_CLUSTER.get(item, item)
    return next((t for t, lst in live_track_clusters().items() if cluster in lst), "")


def qi_tracks_of_spec(spec):
    return sorted({qi_track_of(x.strip()) for x in (spec or "").split(";") if x.strip()} - {""})


def qi_clean_spec(raw, keep=""):
    """A specialization from the picker: only names of the fixed curriculum (or ones the teacher already has)."""
    ok = live_spec_names() | {x.strip() for x in (keep or "").split(";") if x.strip()}
    out = []
    for x in (raw or "").split(";"):
        x = x.strip()
        if x and x in ok and x not in out:
            out.append(x)
    return SPEC_SEP.join(out)[:800]


def qi_sections_save(f):
    """Save All for sections. All-or-nothing: if any filled row has a problem nothing is saved."""
    names, grades, clusters = f.getlist("s_name"), f.getlist("s_grade"), f.getlist("s_cluster")
    if len(names) > QI_MAX_ROWS:
        return False, [f"Add at most {QI_MAX_ROWS} sections at a time."]
    existing = {r["name"].lower() for r in query("SELECT name FROM sections")}
    rows, errs, seen = [], [], set()
    for i, raw in enumerate(names):
        short = clean(qi_short(raw), QI_NAME_MAX)
        if not short:
            continue                                   # an empty field is simply ignored
        grade = to_int(grades[i] if i < len(grades) else "", 11, 12)
        cl = (clusters[i] if i < len(clusters) else "").strip()
        if grade is None:
            errs.append(f"Row {i + 1}: choose Grade 11 or Grade 12.")
            continue
        extra, err = section_fields({"track": "", "cluster": cl, "grade": grade})
        if err:
            errs.append(f"Row {i + 1} ({short}): {err}")
            continue
        full = f"{grade}-{short}"
        if full.lower() in seen:
            errs.append(f"{full} is typed more than once.")
        elif full.lower() in existing:
            errs.append(f"{full} is already registered.")
        else:
            seen.add(full.lower())
            rows.append((full, grade, extra))
    if not rows and not errs:
        errs.append("Type at least one section name.")
    if errs:
        return False, errs
    made = 0
    for full, grade, extra in rows:
        try:
            conn = db()
            cur = conn.execute("INSERT INTO sections(name,grade,track,cluster,shift,room) VALUES(?,?,?,?,?,?)",
                               (full, grade, extra["track"], extra["cluster"], extra["shift"], ""))
            conn.commit()
            sync_section_subjects(cur.lastrowid)
            build_default_program(cur.lastrowid)
            made += 1
        except IntegrityError:
            errs.append(f"{full} is already registered.")
    if errs and not made:
        return False, errs
    return True, [f"Saved {made} section{'s' if made != 1 else ''}. They are now part of the scheduling process."]


def qi_section_edit(f):
    sid = f.get("sid", type=int)
    s = query("SELECT * FROM sections WHERE id=?", (sid,), one=True) if sid else None
    if not s:
        return False, ["That section no longer exists."]
    short = clean(qi_short(f.get("name")), QI_NAME_MAX)
    grade = to_int(f.get("grade"), 11, 12)
    if not short or grade is None:
        return False, ["Enter a section name and choose Grade 11 or Grade 12."]
    extra, err = section_fields({"track": "", "cluster": f.get("cluster", ""), "grade": grade}, s)
    if err:
        return False, [err]
    full = f"{grade}-{short}"
    if query("SELECT 1 FROM sections WHERE lower(name)=lower(?) AND id!=?", (full, sid), one=True):
        return False, [f"{full} is already registered."]
    try:
        run("UPDATE sections SET name=?, grade=?, track=?, cluster=?, shift=? WHERE id=?",
            (full, grade, extra["track"], extra["cluster"], extra["shift"], sid))
    except IntegrityError:
        return False, [f"{full} is already registered."]
    sync_section_subjects(sid)
    changed = extra["cluster"] != s["cluster"] or grade != s["grade"]
    has = query("SELECT COUNT(*) AS n, COUNT(teacher_id) AS t FROM classes WHERE section_id=? AND kind='class'",
                (sid,), one=True)
    if not has["n"] or (not has["t"] and changed):
        build_default_program(sid, force=True)
    elif has["n"] and changed:
        mark_stale([sid])                               # teachers already placed: regenerate in Generate
    for x in {s["adviser_id"]} | {r["teacher_id"] for r in query(
            "SELECT DISTINCT teacher_id FROM classes WHERE section_id=?", (sid,))}:
        sync_category(x)
    touch("section", sid)
    return True, [f"{full} was updated."]


def qi_section_delete(f):
    sid = f.get("sid", type=int)
    sec = query("SELECT * FROM sections WHERE id=?", (sid,), one=True) if sid else None
    if not sec:
        return False, ["That section no longer exists."]
    who = {r["teacher_id"] for r in query("SELECT DISTINCT teacher_id FROM classes WHERE section_id=?", (sid,))}
    who.add(sec["adviser_id"])
    run("DELETE FROM classes WHERE section_id=?", (sid,))
    run("DELETE FROM section_subjects WHERE section_id=?", (sid,))
    run("DELETE FROM loads WHERE section_id=?", (sid,))
    run("DELETE FROM sections WHERE id=?", (sid,))
    for x in who:
        sync_category(x)
    return True, [f"{sec['name']} and its class program were deleted."]


def qi_teachers_save(f):
    names, cats, specs = f.getlist("t_name"), f.getlist("t_cat"), f.getlist("t_spec")
    if len(names) > QI_MAX_ROWS:
        return False, [f"Add at most {QI_MAX_ROWS} teachers at a time."]
    existing = {qi_name_key(r["full_name"]) for r in query("SELECT full_name FROM users WHERE role='teacher'")}
    rows, errs, seen = [], [], set()
    for i, raw in enumerate(names):
        nm = re.sub(r"\s+", " ", clean(raw, 120))
        if not nm:
            continue
        cat = (cats[i] if i < len(cats) else "G11")
        key = qi_name_key(nm)
        if cat not in CATS:
            errs.append(f"Row {i + 1} ({nm}): choose the grade level handled.")
        elif not key:
            errs.append(f"Row {i + 1}: enter a valid full name.")
        elif key in seen:
            errs.append(f"{nm} is typed more than once.")
        elif key in existing:
            errs.append(f"{nm} is already registered as a teacher.")
        else:
            seen.add(key)
            rows.append((nm, cat, qi_clean_spec(specs[i] if i < len(specs) else "")))
    if not rows and not errs:
        errs.append("Type at least one teacher name.")
    if errs:
        return False, errs
    tt, made = get_tt(), 0
    for nm, cat, spec in rows:
        for _try in range(3):                           # a second admin saving at the same moment could take the ID
            try:
                run("""INSERT INTO users(teacher_id,username,full_name,role,category,password_hash,specialization,
                                         official_time,intervention_min,ancillary_min)
                       VALUES(?,?,?,?,?,?,?,?,0,0)""",
                    (next_teacher_id(), unique_username(nm), nm, "teacher", cat,
                     generate_password_hash(TEMP_PASSWORD), spec, auto_official(cat, tt)))
                made += 1
                break
            except IntegrityError:
                continue
    match_quals()
    return True, [f"Saved {made} teacher{'s' if made != 1 else ''}. Class hours follow the grade level handled. "
                  f"Each new account has the temporary password {TEMP_PASSWORD} (changed in Settings by the teacher)."]


def qi_teacher_edit(f):
    tid = f.get("tid", type=int)
    t = query("SELECT * FROM users WHERE id=? AND role='teacher'", (tid,), one=True) if tid else None
    if not t:
        return False, ["That teacher no longer exists."]
    nm, cat = re.sub(r"\s+", " ", clean(f.get("t_name"), 120)), f.get("t_cat", "")
    if not qi_name_key(nm) or cat not in CATS:
        return False, ["Enter the teacher's full name and choose the grade level handled."]
    if any(qi_name_key(r["full_name"]) == qi_name_key(nm)
           for r in query("SELECT full_name FROM users WHERE role='teacher' AND id!=?", (tid,))):
        return False, [f"{nm} is already registered as a teacher."]
    spec = qi_clean_spec(f.get("t_spec"), keep=t["specialization"] or "")
    tt, sh = get_tt(), f.get("t_shift", "").upper()
    if sh in tt and sh != "MID":
        hours = shift_hours(tt, sh)
    elif cat != t["category"]:
        hours = auto_official(cat, tt)
    else:
        hours = t["official_time"] or ""
    run("UPDATE users SET full_name=?, category=?, specialization=?, official_time=? WHERE id=?",
        (nm, cat, spec, hours, tid))
    match_quals(tid)
    drop_removed_quals(tid, t["specialization"])
    touch("teacher", tid)
    return True, [f"{nm} was updated."]


def qi_teacher_delete(f):
    tid = f.get("tid", type=int)
    t = query("SELECT * FROM users WHERE id=? AND role='teacher'", (tid,), one=True) if tid else None
    if not t:
        return False, ["That teacher no longer exists."]
    sids = [r["section_id"] for r in query("SELECT DISTINCT section_id FROM classes WHERE teacher_id=?", (tid,))]
    run("UPDATE classes SET teacher_id=NULL WHERE teacher_id=?", (tid,))
    run("UPDATE sections SET adviser_id=NULL WHERE adviser_id=?", (tid,))
    run("UPDATE loads SET teacher_id=NULL WHERE teacher_id=?", (tid,))
    run("DELETE FROM teacher_subjects WHERE user_id=?", (tid,))
    run("DELETE FROM notifications WHERE user_id=?", (tid,))
    run("DELETE FROM settings WHERE k IN (?,?)", (f"tmins_{tid}", f"upd_teacher_{tid}"))
    run("DELETE FROM users WHERE id=? AND role='teacher'", (tid,))
    if sids:
        mark_stale(sids)
    return True, [f"{t['full_name']} was deleted. Their class periods are now unassigned; run Generate to reassign them."]


def qi_rooms_save(f):
    names, types = f.getlist("r_name"), f.getlist("r_type")
    if len(names) > QI_MAX_ROWS:
        return False, [f"Add at most {QI_MAX_ROWS} rooms at a time."]
    allowed = set(rtype_options())
    existing = {r["name"].lower() for r in query("SELECT name FROM rooms")}
    rows, errs, seen = [], [], set()
    for i, raw in enumerate(names):
        nm = clean(raw, QI_NAME_MAX)
        if not nm:
            continue
        rt = (types[i] if i < len(types) else "Regular") or "Regular"
        if rt not in allowed:
            errs.append(f"Row {i + 1} ({nm}): choose a room type from the list.")
        elif nm.lower() in seen:
            errs.append(f"{nm} is typed more than once.")
        elif nm.lower() in existing:
            errs.append(f"{nm} is already registered.")
        else:
            seen.add(nm.lower())
            rows.append((nm, rt))
    if not rows and not errs:
        errs.append("Type at least one room name.")
    if errs:
        return False, errs
    made = 0
    for nm, rt in rows:
        b, fl = room_place(nm)
        try:
            run("INSERT INTO rooms(name,rtype,building,floor) VALUES(?,?,?,?)", (nm, rt, b or None, fl or None))
            made += 1
        except IntegrityError:
            errs.append(f"{nm} is already registered.")
    if errs and not made:
        return False, errs
    return True, [f"Saved {made} room{'s' if made != 1 else ''}. Rooms stay available for the whole school year "
                  f"and are used by every class program you generate."]


def qi_room_edit(f):
    rid = f.get("rid", type=int)
    room = query("SELECT * FROM rooms WHERE id=?", (rid,), one=True) if rid else None
    if not room:
        return False, ["That room no longer exists."]
    nm, rt = clean(f.get("r_name"), QI_NAME_MAX), f.get("r_type", "Regular") or "Regular"
    b, fl = room_place(nm)
    ok, msg = room_update(rid, nm, rt, f.get("r_grade") or room["grade_access"] or "Both",
                          b or room["building"], fl or room["floor"])
    return ok, [msg]


def qi_room_delete(f):
    _gone = query("SELECT name FROM rooms WHERE id=?", (f.get("rid", type=int),), one=True)
    if _gone:
        run("UPDATE sections SET room='', building=NULL, floor=NULL WHERE lower(room)=lower(?)", (_gone["name"],))
    return qi_room_delete_core(f)


def qi_room_delete_core(f):
    rid = f.get("rid", type=int)
    room = query("SELECT * FROM rooms WHERE id=?", (rid,), one=True) if rid else None
    if not room:
        return False, ["That room no longer exists."]
    run("UPDATE classes SET room=NULL, room_id=NULL WHERE room_id=?", (rid,))
    run("DELETE FROM rooms WHERE id=?", (rid,))
    return True, [f"{room['name']} was deleted and removed from the periods that used it."]


QI_ACTIONS = {"save_sections": ("sections", qi_sections_save), "edit_section": ("sections", qi_section_edit),
              "delete_section": ("sections", qi_section_delete),
              "save_new_teachers": ("teachers", qi_teachers_save), "edit_teacher": ("teachers", qi_teacher_edit),
              "delete_teacher": ("teachers", qi_teacher_delete),
              "save_rooms": ("rooms", qi_rooms_save), "edit_room": ("rooms", qi_room_edit),
              "delete_room": ("rooms", qi_room_delete)}


def qi_context(tab="sections", draft=None):
    tt = get_tt()
    secs = query("SELECT * FROM sections ORDER BY grade, name")
    teachers_ = query("SELECT * FROM users WHERE role='teacher' ORDER BY id")
    rooms_ = sorted(query("SELECT * FROM rooms"), key=lambda r: natkey(r["name"]))
    tstats = {t: {"clusters": [], "sections": 0, "teachers": 0} for t in TRACKS}
    for t, spec_clusters in (("Academic", ACADEMIC_CLUSTERS), ("TechPro", TECHPRO_CLUSTERS)):
        tstats[t]["clusters"] = [dict(code=c[0], name=c[1], specs=c[2], room=c[3]) for c in spec_clusters]
    for s in secs:
        if s["track"] in tstats:
            tstats[s["track"]]["sections"] += 1
    t_tracks = {}
    for t in teachers_:
        t_tracks[t["id"]] = qi_tracks_of_spec(t["specialization"])
        for tr in t_tracks[t["id"]]:
            tstats[tr]["teachers"] += 1
    offered = section_form_data()["offered_clusters"]
    data = {"clusters": offered, "cats": CATS, "rtypes": rtype_options(), "maxrows": QI_MAX_ROWS,
            "existing": {"sections": [s["name"].lower() for s in secs],
                         "teachers": [qi_name_key(t["full_name"]) for t in teachers_],
                         "rooms": [r["name"].lower() for r in rooms_]},
            "draft": draft or {}, "tab": tab}
    return dict(tab=tab, data=data, all_secs=secs, teachers=teachers_, rooms=rooms_, tstats=tstats,
                t_tracks=t_tracks, offered_clusters=offered, approved=approval(), n_sched=len(sched_secs()),
                shifts=[k for k in sorted(tt, key=lambda k: tt[k][0][0]) if k != "MID"],
                tshift={t["id"]: teacher_shift(t, tt) for t in teachers_}, hours={k: shift_hours(tt, k) for k in tt},
                shift_of=SHIFT_OF, rtypes=rtype_options(), missing_types=missing_room_types(),
                track_of=qi_track_of)


@app.route("/admin/quick-input", methods=["GET", "POST"])
@login_required("admin")
def quick_input():
    """Central school set-up: sections, tracks (read-only), teachers and rooms. Everything saved here is stored in
    the database and is what the scheduling module (Generate) uses for the whole school year."""
    tab = request.args.get("tab", "sections")
    if request.method == "POST":
        f = request.form
        act = f.get("action")
        if act == "run":
            return redirect(url_for("auto_generate"))
        if act in QI_ACTIONS:
            tab, fn = QI_ACTIONS[act]
            try:
                ok, msgs = fn(f)
            except Exception:                           # never leave the admin with a blank error page
                db().rollback()
                app.logger.exception("Quick Input action %s failed", act)
                ok, msgs = False, ["Something went wrong and nothing was saved. Please try again."]
            for m in msgs:
                flash(m, "ok" if ok else "error")
            if ok:
                return redirect(url_for("quick_input", tab=tab) + "#" + tab)
            if act.startswith("save"):                  # keep what the admin typed so nothing has to be retyped
                draft = {"sections": dict(names=f.getlist("s_name"), grades=f.getlist("s_grade"),
                                          clusters=f.getlist("s_cluster")),
                         "teachers": dict(names=f.getlist("t_name"), cats=f.getlist("t_cat"), specs=f.getlist("t_spec")),
                         "rooms": dict(names=f.getlist("r_name"), types=f.getlist("r_type"))}[tab]
                return render_template("quick_input.html", **qi_context(tab, {tab: draft}))
            return redirect(url_for("quick_input", tab=tab) + "#" + tab)
        return redirect(url_for("quick_input"))
    return render_template("quick_input.html", **qi_context(tab))


def run_everything():
    """Assign teachers to every subject, then generate all class programs without conflicts."""
    secs = sched_secs()
    if not secs:
        return "Add at least one section first."
    ensure_room_types()
    q = match_quals()
    a, gv, left = autofill()
    ids = [s["id"] for s in secs]
    res = solve(ids, tries=60)
    apply_draft(res)
    clear_stale(res["sections"])
    sset("gen_draft", "")
    chk, lv = check_program(), validate_loading()
    msg = (f"Done. {gv} teacher assignment(s) made, {len(res['sessions'])} class periods placed in {len(ids)} section(s). ")
    bad_chk = blocking_program_issues(chk)
    if res["unplaced"] or left or bad_chk or lv["issues"]:
        bits = []
        if left:
            bits.append(f"{left} subject(s) have no qualified teacher with enough time in that shift")
        if res["unplaced"]:
            bits.append(f"{len(res['unplaced'])} subject(s) could not be fully scheduled")
        if bad_chk:
            bits.append(f"{len(bad_chk)} schedule conflict(s)")
        if lv["issues"]:
            bits.append(f"{len(lv['issues'])} loading problem(s)")
        return msg + "Needs attention: " + "; ".join(bits) + ". Open the Validation Center to see each one."
    return msg + "No overlapping times and no conflicts were found."


# ---------------------------------------------------------------- audit trail
AUDIT_LABELS = {
    "settings": {"timetable": "Changed the timetable, shifts and scheduling rules", "import_tt": "Imported the timetable from Excel", "reset_tt": "Reset the timetable",
                 None: "Saved school details"},
    "logo_upload": "Uploaded a school logo", "logo_remove": "Went back to the default school logo",
    "curriculum": {"reset": "Reset subject minutes to the starting values", "subject_save": "Added or edited a subject", "subject_delete": "Deleted a subject", None: "Saved subject offerings and time"},
    "sections": "Added a section", "section_edit": "Edited a section", "section_delete": "Deleted a section",
    "teachers": "Created a teacher account", "teacher_edit": "Edited a teacher", "teacher_delete": "Deleted a teacher account",
    "assignments": "Saved teacher details", "teacher_minutes": "Changed a teacher's time",
    "auto_rooms": {"edit": "Edited a room", "delete": "Deleted a room", "add": "Added a room", None: "Saved rooms"},
    "auto_quals": {"match": "Matched qualifications from specializations", None: "Saved teacher qualifications"},
    "auto_loading": {"autofill": "Auto-filled teacher loading", None: "Saved teacher loading of a section"},
    "quick_input": {"save_sections": "Registered sections (Quick Input)", "edit_section": "Edited a section (Quick Input)",
                    "delete_section": "Deleted a section (Quick Input)",
                    "save_new_teachers": "Registered teachers (Quick Input)", "edit_teacher": "Edited a teacher (Quick Input)",
                    "delete_teacher": "Deleted a teacher (Quick Input)",
                    "save_rooms": "Registered rooms (Quick Input)", "edit_room": "Edited a room (Quick Input)",
                    "delete_room": "Deleted a room (Quick Input)",
                    "run": "Assigned teachers and generated all class programs"},
    "auto_conflicts": {"approve": "Approved and locked the schedule", "reopen": "Reopened the approved schedule",
                       "move": "Moved a class period to fix a conflict"},
    "auto_generate": {"quick": "Ran quick setup", "regen": "Regenerated out-of-date sections", "generate": "Generated a draft class program",
                      "apply": "Applied the draft to the class programs", "discard": "Discarded the draft",
                      None: "Used the schedule generator"},
    "entry_add": "Added a class period", "entry_edit": "Edited a class period", "entry_delete": "Deleted a class period",
    "signup_requests": {"reject": "Rejected an account request", "reset_done": "Reset a teacher's password",
                        "reset_cancel": "Dismissed a password reset request", None: "Approved a teacher account request"},
    "reports": {"resolve": "Changed a problem report's status", "delete": "Deleted a problem report",
                "clear": "Cleared resolved problem reports", None: "Updated problem reports"},
    "users": {"add_admin": "Created an administrator account", "reset_pw": "Reset an account password",
              "delete_admin": "Deleted an administrator account", None: "Changed an account"},
    "account_settings": "Changed own account settings",
}
AUDIT_DETAIL_KEYS = ("name", "full_name", "username", "school_name", "term", "grade", "track", "cluster", "room")


def audit_event(user, action, detail=""):
    """Write one line of the audit trail. Passwords and other secrets are never recorded."""
    try:
        conn = db()
        conn.execute("INSERT INTO audit_log(at,user_id,who,role,action,detail,ip) VALUES(?,?,?,?,?,?,?)",
                     (ph_stamp(), user["id"] if user else None, user["full_name"] if user else "Not signed in",
                      user["role"] if user else "", action[:120], (detail or "")[:300], (request.remote_addr or "")[:45]))
        conn.commit()
    except Exception:
        pass


@app.after_request
def audit_trail(resp):
    try:
        if (request.method == "POST" and g.get("user") and resp.status_code < 400
                and request.endpoint in AUDIT_LABELS):
            label = AUDIT_LABELS[request.endpoint]
            if isinstance(label, dict):
                label = label.get(request.form.get("action")) or label.get(None)
            if label:
                failed = any(c == "error" for c, _m in (session.get("_flashes") or []))
                bits = [f"{k}={v}" for k, v in (request.view_args or {}).items()]
                bits += [f"{k}: {request.form.get(k)[:60]}" for k in AUDIT_DETAIL_KEYS if request.form.get(k)]
                audit_event(g.user, label + (" (not completed)" if failed else ""), "; ".join(bits))
    except Exception:
        pass
    return resp


# ---------------------------------------------------------------- user management
def next_admin_id():
    n = 0
    for r in query("SELECT teacher_id FROM users WHERE role='admin'"):
        m = re.search(r"(\d+)$", r["teacher_id"] or "")
        n = max(n, int(m.group(1)) if m else 0)
    return f"ADMIN-{n + 1:03d}"


@app.route("/admin/users", methods=["GET", "POST"])
@login_required("admin")
def users():
    """11 User Management: every account, what its role may do, and a way to add or reset them."""
    if request.method == "POST":
        f = request.form
        act = f.get("action")
        uid = f.get("uid", type=int)
        target = query("SELECT * FROM users WHERE id=?", (uid,), one=True) if uid else None
        if act == "add_admin":
            name, user, pw = clean(f.get("full_name")), clean(f.get("username"), 40), f.get("password", "")
            if not name or not user or len(pw) < 6:
                flash("Enter a name, a username and a password of at least 6 characters.", "error")
            elif query("SELECT 1 FROM users WHERE lower(username)=lower(?)", (user,), one=True):
                flash("That username is already in use.", "error")
            else:
                run("""INSERT INTO users(teacher_id,username,full_name,role,category,password_hash,
                                         intervention_min,ancillary_min) VALUES(?,?,?,?,?,?,0,0)""",
                    (next_admin_id(), user, name, "admin", None, generate_password_hash(pw)))
                flash(f"Administrator account created for {name}.", "ok")
        elif act == "reset_pw" and target:
            if target["id"] == g.user["id"]:
                flash("Change your own password in Settings.", "error")
            else:
                run("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(TEMP_PASSWORD), target["id"]))
                if target["role"] == "teacher":
                    notify(target["id"], "reset", f"Your password was reset by the administrator. Temporary password: "
                           f"{TEMP_PASSWORD} - please sign in and change it in Settings.", url_for("account_settings"))
                flash(f"{target['full_name']}'s password is now the temporary password {TEMP_PASSWORD}.", "ok")
        elif act == "delete_admin" and target and target["role"] == "admin":
            if target["id"] == g.user["id"]:
                flash("You cannot delete the account you are signed in with.", "error")
            elif query("SELECT COUNT(*) AS n FROM users WHERE role='admin'", one=True)["n"] < 2:
                flash("The last administrator account cannot be deleted.", "error")
            else:
                run("DELETE FROM users WHERE id=?", (target["id"],))
                flash("Administrator account deleted.", "ok")
        return redirect(url_for("users"))
    rows = query("SELECT * FROM users ORDER BY role, id")
    return render_template("users.html", rows=rows, admins=sum(1 for r in rows if r["role"] == "admin"),
                           teachers_n=sum(1 for r in rows if r["role"] == "teacher"), temp=TEMP_PASSWORD,
                           pending=query("SELECT COUNT(*) AS n FROM signup_requests", one=True)["n"])


ROLE_RIGHTS = [  # what each role can do, as the program enforces it
    ("Administrator", "ADMIN", [
        "Sees every module in the main navigation.",
        "Sets up the school, the offered subjects, sections, teachers, rooms and teacher loading.",
        "Generates, edits and validates class programs, and prints or downloads every report.",
        "Approves account requests, resets passwords and reads problem reports.",
        "Is the only role that can change a schedule."]),
    ("Grade 11 Teacher", "G11", [
        "Opens own Teacher's Program and the Grade 11 class programs the teacher is assigned to.",
        "Receives a notification when the administrator changes the program or assigns a section.",
        "Changes own password in Settings; can report a problem."]),
    ("Grade 12 Teacher", "G12", ["Same as a Grade 11 Teacher, for the Grade 12 class programs."]),
    ("MID Teacher", "MID", [
        "Same as a Grade 11 or Grade 12 Teacher, for both grade levels.",
        "A teacher becomes MID automatically when assigned in both grade levels, and goes back when only one remains."]),
]


@app.route("/admin/users/roles")
@login_required("admin")
def user_roles():
    counts = {r["category"] or "ADMIN": r["n"] for r in query(
        "SELECT category, COUNT(*) AS n FROM users GROUP BY category")}
    counts["ADMIN"] = query("SELECT COUNT(*) AS n FROM users WHERE role='admin'", one=True)["n"]
    return render_template("user_roles.html", roles=ROLE_RIGHTS, counts=counts)


@app.route("/admin/users/audit")
@login_required("admin")
def user_audit():
    q = request.args.get("q", "").strip()[:60]
    who = request.args.get("who", "")
    sql, args = "SELECT * FROM audit_log WHERE 1=1", []
    if who in ("admin", "teacher", ""):
        if who:
            sql += " AND role=?"
            args.append(who)
    if q:
        sql += " AND (lower(who) LIKE ? OR lower(action) LIKE ? OR lower(detail) LIKE ?)"
        args += [f"%{q.lower()}%"] * 3
    rows = query(sql + " ORDER BY id DESC LIMIT 300", args)
    total = query("SELECT COUNT(*) AS n FROM audit_log", one=True)["n"]
    return render_template("user_audit.html", rows=rows, q=q, who=who, total=total)


NEW_TEMPLATES = {
"auto_time.html": """{% extends "base.html" %}{% block title %}Time allocation{% endblock %}
{% block content %}<h1>Validation Center</h1>{{ subnav('validation') }}
{% set bad_subs = ta.subs|selectattr('bad')|list %}{% set over_secs = ta.secs|selectattr('pct', 'gt', 100)|list %}{% set over_t = ta.tch|selectattr('pct', 'gt', 100)|list %}
{% if not bad_subs and not over_secs and not over_t %}<div class="msg ok fitnote"><b>Everything fits.</b> Every subject has matching class periods in {{ ta.shifts|map(attribute='name')|join(', ') }}, and no section or teacher has more hours than the timetable holds.</div>
{% else %}<div class="msg error fitnote"><b>Some things do not fit:</b><ul class="issues">{% for x in bad_subs %}<li>{{ x.s.name }} has no matching run of periods in {{ x.bad|join(', ') }}. Change its minutes in Subject Management or the periods in School Setup.</li>{% endfor %}{% for x in over_secs %}<li>{{ x.sec.name }} needs {{ x.need|hrs }} but the {{ x.shift }} shift has only {{ x.cap|hrs }}.</li>{% endfor %}{% for x in over_t %}<li>{{ x.t.full_name }} is given {{ x.need|hrs }} but is available {{ x.cap|hrs }}.</li>{% endfor %}</ul></div>{% endif %}
<details class="card"><summary><b>Show the shifts and periods</b></summary><h3 style="margin-top:.8rem">Configured shifts and class periods</h3><div class="scroll"><table class="list"><thead><tr><th>Shift</th><th>Runs</th><th>Class time per day</th><th>Per week</th><th>Periods</th></tr></thead><tbody>
{% for s in ta.shifts %}<tr><td><b>{{ s.name }}</b></td><td>{{ s.start|t12 }} to {{ s.end|t12 }}</td><td>{{ s.day|hrs }}</td><td>{{ s.week|hrs }}</td><td>{% for a, b, k in s.periods %}<span class="pill">{{ a|t12 }}-{{ b|t12 }}{{ ' (recess)' if k == 'recess' }}</span> {% endfor %}</td></tr>{% endfor %}</tbody></table></div>
</details><details class="card"><summary><b>Show the weekly time of each subject</b></summary><h3 style="margin-top:.8rem">Required weekly time and matching periods</h3><div class="scroll"><table class="list"><thead><tr><th>Subject</th><th>Required per week</th><th>Meetings</th>{% for s in ta.shifts %}<th>Free periods per day: {{ s.name }}</th>{% endfor %}</tr></thead><tbody>
{% for x in ta.subs %}<tr><td>{{ x.s.name }}<p class="hint">{{ x.s.rtype }}</p></td><td>{{ x.s.weekly_min|hrs }}</td><td>{{ x.n }} x {{ x.lens|join(' / ') }} min</td>
{% for sh in ta.shifts %}<td class="{{ 'why' if sh.name in x.bad }}">{% for L, n in x.blocks[sh.name].items() %}{{ n }} slot{{ '' if n == 1 else 's' }} of {{ L }} min{% if not loop.last %}<br>{% endif %}{% endfor %}{% if sh.name in x.bad %}<br><b>No matching run of periods</b>{% endif %}</td>{% endfor %}</tr>
{% else %}<tr><td colspan="{{ 3 + ta.shifts|length }}" class="empty">No subjects yet.</td></tr>{% endfor %}</tbody></table></div>
</details><details class="card"><summary><b>Show the time of each section</b></summary><h3 style="margin-top:.8rem">Section time needed vs available</h3><div class="scroll"><table class="list"><thead><tr><th>Section</th><th>Shift</th><th>Needed</th><th>Available</th><th>Filled</th></tr></thead><tbody>
{% for x in ta.secs %}<tr><td>{{ x.sec.name }}</td><td>{{ x.shift }}</td><td>{{ x.need|hrs }}</td><td>{{ x.cap|hrs }}</td><td class="{{ 'why' if x.pct > 100 }}"><div class="bar"><i style="width:{{ [100, x.pct]|min }}%"></i></div>{{ x.pct }}%{{ ' - more than the timetable holds' if x.pct > 100 }}</td></tr>{% endfor %}</tbody></table></div>
</details><details class="card"><summary><b>Show the time of each teacher</b></summary><h3 style="margin-top:.8rem">Teacher time needed vs available (inside official time)</h3><div class="scroll"><table class="list"><thead><tr><th>Teacher</th><th>Official time</th><th>Assigned</th><th>Available</th><th>Filled</th></tr></thead><tbody>
{% for x in ta.tch %}<tr><td>{{ x.t.full_name }}</td><td>{{ x.window }}</td><td>{{ x.need|hrs }}</td><td>{{ x.cap|hrs }}</td><td class="{{ 'why' if x.pct > 100 }}"><div class="bar"><i style="width:{{ [100, x.pct]|min }}%"></i></div>{{ x.pct }}%</td></tr>{% endfor %}</tbody></table></div>
</details><div class="card"><h3>Find available time slots</h3><form method="get"><div class="formgrid">
<div><label for="find">For</label><select id="find" name="find"><optgroup label="Section">{% for s in secs %}<option value="section:{{ s.id }}" {{ 'selected' if q == 'section:' ~ s.id }}>{{ s.name }}</option>{% endfor %}</optgroup><optgroup label="Teacher">{% for t in tchs %}<option value="teacher:{{ t.id }}" {{ 'selected' if q == 'teacher:' ~ t.id }}>{{ t.full_name }}</option>{% endfor %}</optgroup><optgroup label="Room">{% for r in rooms_ %}<option value="room:{{ r.id }}" {{ 'selected' if q == 'room:' ~ r.id }}>{{ r.name }}</option>{% endfor %}</optgroup></select></div>
<div><label for="length">Class length (minutes)</label><input id="length" name="length" type="number" min="10" max="480" value="{{ L }}"></div>
<div class="fgbtn"><button type="submit">Show free slots</button></div></div></form>
{% if res %}<div class="scroll" style="margin-top:.8rem"><table class="list"><thead><tr><th>Day</th><th>Free {{ res.L }}-minute slots</th></tr></thead><tbody>{% for d in days %}<tr><td>{{ d }}</td><td>{% for s, e in res.free[d] %}<span class="pill">{{ ('%02d:%02d'|format(s // 60, s % 60))|t12 }}-{{ ('%02d:%02d'|format(e // 60, e % 60))|t12 }}</span> {% else %}<span class="hint">None</span>{% endfor %}</td></tr>{% endfor %}</tbody></table></div>{% endif %}</div>{% endblock %}""",

"auto_conflicts.html": """{% extends "base.html" %}{% block title %}Conflicts{% endblock %}
{% block content %}<h1>Validation Center</h1>{{ subnav('validation') }}
<div class="card" id="approval"><h3>Final approval</h3>{% if approval %}<p class="okt"><b>Approved and locked</b> by {{ approval.by }} on {{ approval.at|stamp12 }} ({{ approval.periods }} periods). Generating, editing periods, loading, rooms, curriculum and section changes are blocked.</p>
<form method="post" onsubmit="return confirm('Reopen the schedule? It will no longer be locked.')">{{ csrf_field() }}<input type="hidden" name="action" value="reopen"><button class="danger" type="submit">Reopen for corrections</button></form>
{% else %}<p>When there are no conflicts and the loading is complete, approve the schedule. Approving locks this version so nothing changes by accident.</p>
<form method="post" onsubmit="return confirm('Approve and lock this schedule?')">{{ csrf_field() }}<input type="hidden" name="action" value="approve"><button type="submit" {{ 'disabled' if chk.issues or lv.issues or not chk.rows }}>Approve schedule</button>{% if chk.issues or lv.issues or not chk.rows %} <span class="hint">{{ 'Nothing to approve yet.' if not chk.rows else 'Fix the problems below first.' }}</span>{% endif %}</form>{% endif %}</div>
<div class="kpis"><div class="kpi {{ 'bad' if chk.issues else 'ok' }}"><b>{{ chk.issues|length }}</b><span>schedule problems</span></div><div class="kpi"><b>{{ chk.warns|length }}</b><span>schedule warnings</span></div><div class="kpi {{ 'bad' if lv.issues else 'ok' }}"><b>{{ lv.issues|length }}</b><span>loading problems</span></div></div>
<div class="card"><h3>Class program problems</h3>{% if chk.entries|selectattr('sev', 'equalto', 'issue')|list %}<div class="scroll"><table data-tools="problems" class="list"><thead><tr><th data-ts="text" data-tf>Type</th><th>Details</th><th>Suggested fixes</th></tr></thead><tbody>
{% for x in chk.entries if x.sev == 'issue' %}<tr><td><span class="pill">{{ {'teacher':'Teacher clash','section':'Section clash','room':'Room clash','room-shift':'Room clash AM/PM','hours':'Incomplete hours','window':'Outside availability','shift':'Outside shift','roomtype':'Room type'}.get(x.kind, x.kind) }}</span></td><td class="why">{{ x.text }}</td><td>{% set sg = sugg.get(x.pid) %}{% if sg %}{% for o in sg.slots %}<form method="post" style="display:inline-block;margin:0 .3rem .3rem 0">{{ csrf_field() }}<input type="hidden" name="action" value="move"><input type="hidden" name="period" value="{{ sg.p.id }}"><input type="hidden" name="day" value="{{ o.day }}"><input type="hidden" name="start" value="{{ o.start }}"><input type="hidden" name="end" value="{{ o.end }}"><input type="hidden" name="room_id" value="{{ o.room.id if o.room else '' }}"><button class="plain small" type="submit">Move to {{ o.day[:3] }} {{ o.start|t12 }}</button></form>{% else %}<span class="hint">No free slot found.</span> {% endfor %}{% endif %}{% if x.pid %}<a class="btn plain small" href="{{ url_for('entry_edit', eid=x.pid) }}">Edit by hand</a>{% else %}<span class="hint">Regenerate in Schedule Generator</span>{% endif %}</td></tr>{% endfor %}</tbody></table></div>
{% else %}<p class="okt"><b>No double-booked teachers, sections or rooms (including AM/PM sharing), nobody outside their availability, and all required hours are met.</b></p>{% endif %}</div>
{% if chk.warns %}<div class="card"><h3>Warnings</h3><ul class="issues">{% for w in chk.warns %}<li>{{ w }}</li>{% endfor %}</ul></div>{% endif %}
<div class="card"><h3>Teacher loading validation</h3>{% if lv.issues %}<ul class="issues">{% for w in lv.issues %}<li class="why">{{ w }}</li>{% endfor %}</ul>{% else %}<p class="okt"><b>Teacher loading is complete and within limits.</b></p>{% endif %}
{% if lv.warns %}<h3>Loading warnings</h3><ul class="issues">{% for w in lv.warns %}<li>{{ w }}</li>{% endfor %}</ul>{% endif %}</div>{% endblock %}""",

"auto_reports.html": """{% extends "base.html" %}{% block title %}Reports{% endblock %}
{% block content %}<h1>Reports and Printing</h1>{{ subnav('reports') }}
{% if not approval %}<div class="msg notice"><strong>Draft.</strong> The schedule has not been approved yet, so these reports are drafts. Approve it in Validation Center for the final version.</div>{% endif %}
<div class="card"><h3>Download</h3><div class="scroll"><table class="list"><thead><tr><th>Report</th><th>Choose</th><th>Excel</th><th>PDF</th></tr></thead><tbody>
<tr><td>Class programs per section</td><td><select id="r_sections"><option value="">All sections</option>{% for s in secs %}<option value="{{ s.id }}">{{ s.name }}</option>{% endfor %}</select></td><td><a class="btn plain small" data-rep="sections" data-fmt="xlsx" href="#">Excel</a></td><td><a class="btn plain small" data-rep="sections" data-fmt="pdf" href="#">PDF</a></td></tr>
<tr><td>Teacher schedules</td><td><select id="r_teachers"><option value="">All teachers</option>{% for t in tchs %}<option value="{{ t.id }}">{{ t.full_name }}</option>{% endfor %}</select></td><td><a class="btn plain small" data-rep="teachers" data-fmt="xlsx" href="#">Excel</a></td><td><a class="btn plain small" data-rep="teachers" data-fmt="pdf" href="#">PDF</a></td></tr>
<tr><td>Room and laboratory programs</td><td><select id="r_rooms"><option value="">All rooms</option>{% for r in rooms_ %}<option value="{{ r.id }}">{{ r.name }}</option>{% endfor %}</select></td><td><a class="btn plain small" data-rep="rooms" data-fmt="xlsx" href="#">Excel</a></td><td><a class="btn plain small" data-rep="rooms" data-fmt="pdf" href="#">PDF</a></td></tr>
<tr><td>Room utilization report</td><td>-</td><td><a class="btn plain small" href="{{ url_for('auto_export', kind='utilization', fmt='xlsx') }}">Excel</a></td><td><a class="btn plain small" href="{{ url_for('auto_export', kind='utilization', fmt='pdf') }}">PDF</a></td></tr>
<tr><td>Teacher teaching-load summary</td><td>-</td><td><a class="btn plain small" href="{{ url_for('auto_export', kind='loads', fmt='xlsx') }}">Excel</a></td><td><a class="btn plain small" href="{{ url_for('auto_export', kind='loads', fmt='pdf') }}">PDF</a></td></tr></tbody></table></div>
<p class="hint">Excel and PDF need the packages openpyxl and reportlab (pip install openpyxl reportlab).</p></div>
<script>document.querySelectorAll('[data-rep]').forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();var k=a.dataset.rep,s=document.getElementById('r_'+k).value;location.href='/admin/export/'+k+'.'+a.dataset.fmt+(s?'?id='+s:'');});});</script>
<div class="card"><h3>Teacher teaching-load summary</h3><div class="scroll"><table data-tools="teachers" class="list"><thead><tr><th data-ts="text">Teacher</th><th>Official time</th><th data-ts="num">Classes handled</th><th data-ts="num">Assigned per week</th><th data-ts="num">Scheduled per week</th><th data-ts="text" data-tf>Status</th></tr></thead><tbody>
{% for x in lv.rows %}<tr><td>{{ x.t.full_name }}</td><td>{{ x.window }}</td><td>{{ x.nsec }}</td><td>{{ x.minutes|hrs }} of {{ lv.maxweek|hrs }}</td><td>{{ x.sched|hrs }}</td><td class="{{ 'okt' if x.status == 'OK' else 'why' }}">{{ x.status }}</td></tr>{% endfor %}</tbody></table></div></div>
<div class="card"><h3>Room utilization</h3><div class="scroll"><table data-tools="rooms" class="list"><thead><tr><th data-ts="text">Room</th><th data-ts="text" data-tf>Type</th>{% for n in ru.order %}<th>{{ n }}</th>{% endfor %}<th>Total</th><th>Used</th><th>Shared AM/PM</th></tr></thead><tbody>
{% for x in ru.rows %}<tr><td><a href="{{ url_for('auto_room', rid=x.r.id) }}">{{ x.r.name }}</a></td><td>{{ x.r.rtype }}</td>{% for n in ru.order %}<td>{{ x.by[n]|hrs }}</td>{% endfor %}<td>{{ x.total|hrs }}</td><td><div class="bar"><i style="width:{{ [100, x.pct]|min }}%"></i></div>{{ x.pct }}%</td><td>{{ 'Yes' if x.shared else 'No' }}</td></tr>{% endfor %}</tbody></table></div></div>{% endblock %}""",
}
TEMPLATES.update(NEW_TEMPLATES)

NEW2_TEMPLATES = {
"dashboard.html": r"""{% extends "base.html" %}{% block title %}Dashboard{% endblock %}
{% block content %}<h1 class="sr-only">Dashboard</h1>
<div class="dash-stats">
<div class="dstat"><span class="ic">{{ nav_icon('people') }}</span><b>{{ st.kpis.teachers }}</b><span class="l">Total Teachers</span></div>
<div class="dstat"><span class="ic">{{ nav_icon('school') }}</span><b>{{ st.kpis.sections }}</b><span class="l">Total Sections</span></div>
<div class="dstat"><span class="ic">{{ nav_icon('door') }}</span><b>{{ st.kpis.rooms }}</b><span class="l">Total Classrooms</span></div>
<div class="dstat"><span class="ic">{{ nav_icon('book') }}</span><b>{{ st.kpis.subjects }}</b><span class="l">Total Subjects</span><small>Core and offered clusters</small></div>
<div class="dstat"><span class="ic">{{ nav_icon('calendar') }}</span><b>{{ st.kpis.scheduled }}</b><span class="l">Generated Schedules</span><small>Sections with a class program</small></div>
<div class="dstat"><span class="ic">{{ nav_icon('table') }}</span><b>{{ st.kpis.periods }}</b><span class="l">Class Periods Placed</span></div>
<div class="dstat {{ 'bad' if st.kpis.conflicts else 'ok' }}"><span class="ic">{{ nav_icon('shieldcheck') }}</span><b>{{ st.kpis.conflicts }}</b><span class="l">Scheduling Conflicts</span><small>{{ 'Needs attention' if st.kpis.conflicts else 'None found' }}</small></div>
<div class="dstat {{ 'warn' if pending else '' }}"><span class="ic">{{ nav_icon('shield') }}</span><b>{{ pending }}</b><span class="l">Pending Registrations</span><small>Teacher accounts awaiting approval</small></div>
</div>
<div class="card"><h3>Recently Added Records</h3><div class="recent">
<div><h4>Sections</h4>{% for r in recent.sections %}<p>{{ r.name }}</p>{% else %}<p class="hint">None yet</p>{% endfor %}</div>
<div><h4>Teachers</h4>{% for r in recent.teachers %}<p>{{ r.full_name }}</p>{% else %}<p class="hint">None yet</p>{% endfor %}</div>
<div><h4>Rooms</h4>{% for r in recent.rooms %}<p>{{ r.name }} <span class="hint">{{ r.rtype }}</span></p>{% else %}<p class="hint">None yet</p>{% endfor %}</div></div></div>

<div class="dash-top"><div class="card"><div class="ring"><div class="pct" style="--p:{{ st.pct }}"><span>{{ st.pct }}%</span></div>
<div><h3 style="margin:0 0 .3rem">Setup progress</h3><p style="margin:0">{{ st.done }} of {{ st.total }} steps complete.</p>
{% if st.nxt %}<p style="margin:.4rem 0 0"><b>Next:</b> <a href="{{ url_for(st.nxt.ep) }}{{ st.nxt.anchor }}">Step {{ st.nxt.num }}: {{ st.nxt.title }}</a><br><span class="hint">{{ st.nxt.text }}</span></p>{% else %}<p class="okt" style="margin:.4rem 0 0"><b>Every step is complete.</b> Print or download the reports.</p>{% endif %}</div></div></div>
{% if st.alerts %}<div class="card"><h3>Alerts</h3>{% if st.alerts %}<ul class="alerts">{% for a in st.alerts %}<li class="{{ a.level }}"><span class="dot"></span><span class="t">{{ a.text }}</span><a class="btn plain small" href="{{ a.href }}">{{ a.label }}</a></li>{% endfor %}</ul>{% else %}<p class="okt"><b>No alerts. Nothing needs your attention.</b></p>{% endif %}</div>{% endif %}</div>
<h2>What to do</h2><div class="stepcards">{% for s in st.steps %}<div class="stepcard {{ 'done' if s.done else 'todo' }}"><span class="st">{{ 'Done' if s.done else 'To do' }}</span><b>{{ s.num }}. {{ s.title }}</b><small>{{ s.text }}</small></div>{% endfor %}</div>
{% if st.prog %}<h2>Progress by section</h2><div class="scroll"><table data-tools="sections" class="list"><thead><tr><th data-ts="text">Section</th><th data-ts="text" data-tf>Track and cluster</th><th data-ts="text">Teachers assigned</th><th data-ts="text">Scheduled</th></tr></thead><tbody>
{% for p in st.prog %}<tr><td><a href="{{ url_for('program', section=p.s.id) }}">{{ p.s.name }}</a></td><td>{{ p.s.track or 'Not set' }}{{ ' - ' ~ p.s.cluster if p.s.cluster }}</td><td class="{{ 'okt' if p.nsub and p.nload == p.nsub else 'why' }}">{{ p.nload }} of {{ p.nsub }} subjects</td><td><div class="bar"><i style="width:{{ p.pct }}%"></i></div><span class="hint">{{ p.got|hrs }} of {{ p.need|hrs }} ({{ p.pct }}%)</span></td></tr>
{% else %}<tr><td colspan="4" class="empty">No sections yet. Start with Section Management.</td></tr>{% endfor %}</tbody></table></div>{% endif %}{% endblock %}""",

"curriculum.html": r"""{% extends "base.html" %}{% block title %}Subject Management{% endblock %}
{% macro subj_json(s) %}{{ {'sid': s.id, 'name': s.name, 'code': s.code or '', 'kind': s.kind, 'track': s.track or '', 'weekly_min': s.weekly_min, 'session_min': s.session_min, 'rtype': s.rtype or 'Regular', 'grade': s.grade or 0, 'status': s.status, 'detail': s.detail or '', '_mode': 'edit', '_title': 'Edit subject', '_lock': (['kind', 'track'] + (['name', 'grade'] if not s.custom else [])), '_note': ('Subject name, type and track are fixed because sections and teachers refer to them. You can change the code, minutes, room and description.' if not s.custom else 'You added this subject, so every field can be changed.')}|tojson }}{% endmacro %}
{% macro edit_cell(s) %}<td class="editcell"><div class="row-acts"><button type="button" class="plain small" data-edit-dlg="subjdlg" data-json='{{ subj_json(s) }}' aria-label="Edit {{ s.name }}">Edit</button><button type="button" class="danger small" data-del-dlg data-sid="{{ s.id }}" data-name="{{ s.name }}" aria-label="Delete {{ s.name }}">Delete</button></div></td>{% endmacro %}
{% macro name_cell(s) %}<span class="cur-name">{{ s.name }}</span> <span class="newbadge" data-sid="{{ s.id }}" hidden>NEWLY ADDED</span>{% if s.custom %} <span class="pill ok">Added</span>{% endif %}{% if s.status != 'active' %} <span class="pill {{ 'bad' if s.status == 'archived' else 'warn' }}">{{ s.status|capitalize }}</span>{% endif %}{% endmacro %}
{% block content %}<div class="pagehead"><h1>Subject Management</h1><button type="button" data-edit-dlg="subjdlg" data-json='{{ {"sid": "", "name": "", "code": "", "kind": "core", "track": "Academic", "weekly_min": 120, "session_min": 60, "rtype": "Regular", "offered": 1, "detail": "", "_mode": "new", "_title": "Add subject", "_lock": [], "_note": "A new core subject is given to every section. A new cluster elective can be chosen for a section in Section Management."}|tojson }}'>+ Add subject</button></div>
<div class="cur-note">The built-in subjects follow the Strengthened Curriculum: their names stay fixed, but you can edit their code, minutes, room and description. Use <b>Add subject</b> for anything else. The <b>Room needed</b> list comes from the room types in <a href="{{ url_for('auto_rooms') }}#types">Room Management</a>.</div>
{% if missing_types %}<div class="cur-note" role="status">No room is registered yet for: <b>{{ missing_types|join(', ') }}</b>. Offered subjects that need these cannot be scheduled until a room of that type is registered in <a href="{{ url_for('quick_input', tab='rooms') }}#rooms">Quick Input</a>.</div>{% endif %}
{% if blocked %}<div class="card blocked" role="alert" id="blocked"><h3>{{ blocked.sub.name }} was not deleted</h3>
{% if blocked.deps %}<p>It cannot be permanently deleted because it is still used:</p><ul>{% for k, v in blocked.deps.items() %}<li><b>{{ k }}</b>: {{ v[:6]|join(', ') }}{{ ' and ' ~ (v|length - 6) ~ ' more' if v|length > 6 }}</li>{% endfor %}</ul>{% endif %}
{% if blocked.builtin %}<p>It is a built-in Strengthened Curriculum subject, which is restored at every start-up, so it can only be made inactive or archived.</p>{% endif %}
<p>Deactivate or archive it instead. It then disappears from new selections and new schedules, while existing programs and records are kept.</p>
<form method="post" class="btnrow" data-noconfirm>{{ csrf_field() }}<input type="hidden" name="action" value="subject_status"><input type="hidden" name="sid" value="{{ blocked.sub.id }}"><button type="submit" name="status" value="inactive">Deactivate</button><button type="submit" name="status" value="archived" class="plain">Archive</button></form></div>{% endif %}
<p class="hint" style="margin:.2rem 0 .6rem">{% if show_arch %}Showing archived subjects. <a href="{{ url_for('curriculum') }}">Hide archived</a>{% elif n_arch %}{{ n_arch }} archived subject(s) are hidden. <a href="{{ url_for('curriculum', archived=1) }}">Show archived</a>{% else %}Inactive subjects stay in the list; archived ones are hidden.{% endif %}</p>
<form method="post">{{ csrf_field() }}<input type="hidden" name="action" value="save">
<div class="card"><h3>Core Subjects <span class="hint">(every section, both grade levels)</span></h3><div class="scroll"><table data-tools="core subjects" class="list subj-t"><thead><tr><th data-ts="text">Code</th><th data-ts="text">Subject</th><th data-ts="num">Min per week</th><th data-ts="num">Min per meeting</th><th data-ts="text" data-tf>Room needed</th><th data-ts="num">Sections</th><th class="editth">Actions</th></tr></thead><tbody>
{% for s in core %}<tr><td>{{ s.code }}</td><td>{{ name_cell(s) }}{% if s.detail %}<span class="cur-spec">{{ s.detail }}</span>{% endif %}</td><td>{{ s.weekly_min }}<input type="hidden" name="wk_{{ s.id }}" value="{{ s.weekly_min }}"></td><td>{{ s.session_min }}<input type="hidden" name="se_{{ s.id }}" value="{{ s.session_min }}"></td><td>{{ s.rtype or 'Regular' }}<input type="hidden" name="rtype_{{ s.id }}" value="{{ s.rtype or 'Regular' }}"></td><td>{{ s.used }}</td>{{ edit_cell(s) }}</tr>
{% else %}<tr><td colspan="7" class="empty">No core subjects yet. Use Add subject.</td></tr>{% endfor %}</tbody></table></div></div>
{% for title, items, note in [('Academic Track Clusters', academic, ''), ('TechPro Track Clusters', techpro, 'The specializations in brackets are what teachers can be qualified in.')] %}
<div class="card"><h3>{{ title }}</h3>{% if note %}<p class="hint">{{ note }}</p>{% endif %}<div class="scroll"><table data-tools="clusters" class="list subj-t"><thead><tr><th data-ts="text" data-tf>Offered</th><th data-ts="text">Cluster</th><th data-ts="num">Min per week</th><th data-ts="num">Min per meeting</th><th data-ts="text" data-tf>Room needed</th><th data-ts="num">Sections</th><th class="editth">Actions</th></tr></thead><tbody>
{% for s in items %}<tr><td><input class="ck" type="checkbox" name="off_{{ s.id }}" value="1" {{ 'checked' if s.status == 'active' }} {{ 'disabled' if s.status == 'archived' }} aria-label="Offer {{ s.name }}"></td><td>{{ name_cell(s) }}{% if s.detail %}<span class="cur-spec">({{ s.detail }})</span>{% endif %}</td><td>{{ s.weekly_min }}<input type="hidden" name="wk_{{ s.id }}" value="{{ s.weekly_min }}"></td><td>{{ s.session_min }}<input type="hidden" name="se_{{ s.id }}" value="{{ s.session_min }}"></td><td>{{ s.rtype or 'Regular' }}<input type="hidden" name="rtype_{{ s.id }}" value="{{ s.rtype or 'Regular' }}"></td><td>{{ s.used }}</td>{{ edit_cell(s) }}</tr>
{% else %}<tr><td colspan="7" class="empty">No clusters in this track yet.</td></tr>{% endfor %}</tbody></table></div></div>{% endfor %}
<div class="btnrow"><button type="submit">Save subjects</button></div></form>
<form method="post" style="margin-top:1rem">{{ csrf_field() }}<input type="hidden" name="action" value="reset"><button class="plain" type="submit">Reset minutes and rooms to the starting values</button></form>

<dialog id="subjdlg" class="dlg" aria-labelledby="subjdlg-t"><form method="post" class="dlg-form" data-noconfirm novalidate>{{ csrf_field() }}<input type="hidden" name="action" value="subject_save"><input type="hidden" name="sid" value="">
<h3 id="subjdlg-t" data-title>Add subject</h3>
<div class="msg error" role="alert" id="subjerr" {% if not sf_err %}hidden{% endif %}>{{ sf_err }}</div>
<div class="dlg-grid">
<div data-when="new"><label for="sf_kind">Subject type</label><select id="sf_kind" name="kind"><option value="core">Core subject (every section)</option><option value="cluster">Cluster elective</option></select></div>
<div data-when="cluster"><label for="sf_track">Track</label><select id="sf_track" name="track"><option>Academic</option><option>TechPro</option></select></div>
<div><label for="sf_name">Subject name</label><input id="sf_name" name="name" maxlength="80" required></div>
<div><label for="sf_code">Code</label><input id="sf_code" name="code" maxlength="20" required></div>
<div><label for="sf_wk">Minutes per week</label><input id="sf_wk" type="number" name="weekly_min" min="30" max="2400" required></div>
<div><label for="sf_se">Minutes per meeting</label><input id="sf_se" type="number" name="session_min" min="10" max="480" required></div>
<div><label for="sf_rt">Room needed</label><select id="sf_rt" name="rtype">{% for r in rtypes %}<option>{{ r }}</option>{% endfor %}</select></div>
<div><label for="sf_gr">Grade level</label><select id="sf_gr" name="grade"><option value="0">Both grade levels</option><option value="11">Grade 11</option><option value="12">Grade 12</option></select></div>
<div data-when="edit"><label for="sf_st">Status</label><select id="sf_st" name="status"><option value="active">Active</option><option value="inactive">Inactive</option><option value="archived">Archived</option></select></div>
<div class="wide"><label for="sf_dt">Description <span class="hint">(optional)</span></label><input id="sf_dt" name="detail" maxlength="200"></div>
</div>
<p class="hint" data-note></p>
<div class="btnrow"><button type="submit">Save changes</button><button type="button" class="plain" data-close>Cancel</button></div>
</form></dialog>
<script>(function(){var d=document.getElementById('subjdlg'),k=d.querySelector('[name=kind]');
function sync(){var nw=d.getAttribute('data-mode')==='new',kind=k.value;
 d.querySelectorAll('[data-when]').forEach(function(x){var w=x.getAttribute('data-when');x.hidden=(w==='new'&&!nw)||(w==='cluster'&&kind!=='cluster')||(w==='edit'&&nw);});}
k.addEventListener('change',sync);d.addEventListener('dlg:fill',function(){document.getElementById('subjerr').hidden=true;sync();});
d.addEventListener('close',function(){document.getElementById('subjerr').hidden=true;});
d.querySelector('form').addEventListener('submit',function(e){var f=d.querySelector('form'),m=document.getElementById('subjerr'),msg='';
 if(!f.name.value.trim())msg='Enter the subject name.';else if(!f.code.value.trim())msg='Enter the subject code.';
 else if(!f.weekly_min.value||!f.session_min.value)msg='Enter the minutes per week and per meeting.';
 if(msg){e.preventDefault();m.textContent=msg;m.hidden=false;}});
{% if sf %}document.addEventListener('DOMContentLoaded',function(){window.dlgOpen('subjdlg',{{ sf|tojson }});{% if sf_err %}document.getElementById('subjerr').hidden=false;{% endif %}});{% endif %}})();</script>
<dialog id="deldlg" class="dlg" aria-labelledby="deldlg-t"><form method="post" class="dlg-form" data-noconfirm>{{ csrf_field() }}<input type="hidden" name="action" value="subject_delete"><input type="hidden" name="sid" value="">
<h3 id="deldlg-t">Delete subject</h3><p><b data-delname></b></p><p>Are you sure you want to delete this subject? This action may affect teacher assignments and section schedules.</p>
<div class="btnrow"><button type="button" class="plain" data-delcancel>Cancel</button><button type="submit" class="danger">Confirm Delete</button></div></form></dialog>
<div id="newsub" data-ids="{{ new_ids }}" hidden></div>
<style>.newbadge{display:inline-block;vertical-align:middle;margin-left:.35rem;padding:.05rem .45rem;border-radius:999px;background:#dff3e6;color:#176b3a;border:1px solid #b6e0c4;font-size:.68rem;font-weight:700;letter-spacing:.03em;line-height:1.4;white-space:nowrap}.newbadge[hidden]{display:none}.blocked{border-left:4px solid #b45309}.blocked ul{margin:.3rem 0 .6rem 1.1rem}</style>
<script>(function(){
var dd=document.getElementById('deldlg');
document.addEventListener('click',function(e){var b=e.target.closest('[data-del-dlg]');if(b){dd.querySelector('[name=sid]').value=b.getAttribute('data-sid');dd.querySelector('[data-delname]').textContent=b.getAttribute('data-name');dd.showModal();}
 if(e.target.closest('[data-delcancel]'))dd.close();});
document.querySelectorAll('#deldlg form,#subjdlg form').forEach(function(f){var sent=false;f.addEventListener('submit',function(e){if(sent){e.preventDefault();return;}sent=true;setTimeout(function(){f.querySelectorAll('button[type=submit]').forEach(function(x){x.disabled=true;x.textContent='Saving...';});},0);});});
/* NEWLY ADDED: temporary, in the browser only. A reload, back/forward or a visit from another page clears it. */
var KEY='newSubjectIds',ids=[],nav=(performance.getEntriesByType&&performance.getEntriesByType('navigation')[0])||{},same=false;
try{same=document.referrer&&new URL(document.referrer).pathname===location.pathname;}catch(e){}
try{if((nav.type||'navigate')==='navigate'&&same){ids=JSON.parse(sessionStorage.getItem(KEY)||'[]');}else{sessionStorage.removeItem(KEY);}}catch(e){ids=[];}
((document.getElementById('newsub').getAttribute('data-ids')||'').split(',')).filter(Boolean).forEach(function(x){x=Number(x);if(ids.indexOf(x)<0)ids.push(x);});
try{sessionStorage.setItem(KEY,JSON.stringify(ids));}catch(e){}
ids.forEach(function(i){document.querySelectorAll('.newbadge[data-sid="'+i+'"]').forEach(function(x){x.hidden=false;});});
})();</script>
{% endblock %}
""",

"settings.html": r"""{% extends "base.html" %}{% block title %}School Setup{% endblock %}
{% block content %}<h1>School Setup</h1>
<div class="card"><h3>School year, term and document details</h3><form method="post">{{ csrf_field() }}<input type="hidden" name="action" value="details"><div class="formgrid">
<div><label for="school_year">School year</label><input id="school_year" name="school_year" value="{{ school_year }}" pattern="[0-9]{4}-[0-9]{4}" required><p class="hint">Two consecutive years, like 2026-2027.</p></div>
<div><label for="term_name">Term</label><select id="term_name" name="term_name" required><option value="">Choose</option>{% for t in terms %}<option {{ 'selected' if t == term_name }}>{{ t }}</option>{% endfor %}</select><p class="hint">Printed as: {{ cfg.term }}</p></div>
{% for k, label in fields %}<div class="{{ 'wide' if k in ('school_name','school_address') }}"><label for="{{ k }}">{{ label }}</label><input id="{{ k }}" name="{{ k }}" value="{{ cfg[k] }}"></div>{% endfor %}
</div><p style="margin-top:1.2rem"><button type="submit">Save details</button></p></form></div>
<div class="card"><h3>School logo</h3><div class="logoedit"><img class="logoprev" src="{{ logo_url }}" alt="Current school logo"><div>
<form method="post" action="{{ url_for('logo_upload') }}" enctype="multipart/form-data">{{ csrf_field() }}<label for="logo">Replace the logo (PNG, JPG, GIF or WEBP, under 2 MB)</label><input id="logo" type="file" name="logo" accept="image/png,image/jpeg,image/gif,image/webp" required><p style="margin-top:.8rem"><button type="submit">Save logo</button></p></form>
{% if custom_logo %}<form method="post" action="{{ url_for('logo_remove') }}" onsubmit="return confirm('Go back to the default school logo?')">{{ csrf_field() }}<button class="danger">Use default logo</button></form>{% endif %}</div></div></div>
<div class="card" id="timetable"><h3>Timetable and shifts (time slots)</h3><p class="hint">Classes run Monday to Friday. Each shift has its own periods; mark breaks as recess. Class programs use AM for Grade 11 and PM for Grade 12 automatically.</p>
<div class="scroll"><table class="list"><thead><tr><th>Shift</th><th>Runs</th><th>Class periods</th><th>Class time per day</th><th>Per week</th></tr></thead><tbody>{% for s in shifts %}<tr><td><b>{{ s.name }}</b></td><td>{{ s.start|t12 }} to {{ s.end|t12 }}</td><td>{{ s.n }}</td><td>{{ s.day|hrs }}</td><td>{{ s.week|hrs }}</td></tr>{% endfor %}</tbody></table></div>
<div class="cur-note"><b>Import from Excel.</b> Fill in one row per period with the columns <b>Shift, Start, End, Type</b> (Type is class or recess). <a href="{{ url_for('tt_template') }}">Download the template</a> with the current timetable already filled in.
<form method="post" enctype="multipart/form-data" style="margin-top:.5rem">{{ csrf_field() }}<input type="hidden" name="action" value="import_tt"><input type="file" name="tt_file" accept=".xlsx" required> <button type="submit" class="small" data-noconfirm>Import time slots</button></form></div>
<form method="post" id="ttform" style="margin-top:1rem">{{ csrf_field() }}<input type="hidden" name="action" value="timetable">
<div id="ttedit"></div><p><button type="button" class="plain small" id="addshift">Add a shift</button></p>
<details><summary>Edit as text</summary><textarea class="tt" id="tt_text" name="tt_text" spellcheck="false">{{ tt_text }}</textarea></details>
<h4 style="margin:1rem 0 .3rem">Scheduling rules</h4><div class="formgrid"><div><label for="max_day">Daily teaching limit per teacher (minutes)</label><input id="max_day" name="max_day" type="number" min="60" max="720" value="{{ max_day }}"></div>
<div><label for="max_week">Weekly teaching limit per teacher (minutes)</label><input id="max_week" name="max_week" type="number" min="60" max="3000" value="{{ max_week }}"></div>
<div><label for="turnover">Laboratory turnover between classes (minutes)</label><input id="turnover" name="turnover" type="number" min="0" max="120" value="{{ turnover }}"></div></div>
<div class="btnrow"><button type="submit">Save timetable and rules</button></div></form>
<form method="post" style="margin-top:.6rem">{{ csrf_field() }}<input type="hidden" name="action" value="reset_tt"><button class="plain small" type="submit">Reset to the standard AM and PM shifts</button></form></div>
<script>(function(){
var ta=document.getElementById('tt_text'),box=document.getElementById('ttedit');if(!ta||!box)return;
var RE=/^\s*(\S+)\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*(class|recess|break)?\s*$/i,data=[];
function mn(v){var p=v.split(':');return (+p[0])*60+(+p[1]);}
function hh(n){return ('0'+Math.floor(n/60)).slice(-2)+':'+('0'+(n%60)).slice(-2);}
function parse(){data=[];var idx={};ta.value.split('\n').forEach(function(l){var m=RE.exec(l);if(!m||m[1].charAt(0)==='#')return;var n=m[1].toUpperCase();
 if(!(n in idx)){idx[n]=data.length;data.push({name:n,rows:[]});}
 data[idx[n]].rows.push({s:(+m[2])*60+(+m[3]),e:(+m[4])*60+(+m[5]),k:/recess|break/i.test(m[6]||'')?'recess':'class'});});}
function write(){var o=['# SHIFT start-end [recess]   (one line per period; the shift name is the first word)'];
 data.forEach(function(sh){sh.rows.forEach(function(r){o.push(sh.name+' '+hh(r.s)+'-'+hh(r.e)+(r.k==='recess'?' recess':''));});});ta.value=o.join('\n')+'\n';}
function el(t,c,h){var e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;}
function render(){box.innerHTML='';data.forEach(function(sh,si){var card=el('div','ttcard');card.appendChild(el('h4',null,'Shift '+sh.name));
 sh.rows.forEach(function(r,ri){var row=el('div','ttrow'),a=el('input'),b=el('input'),k=el('select'),x=el('button','plain x','Remove');
  a.type='time';a.value=hh(r.s);a.setAttribute('aria-label','Start');b.type='time';b.value=hh(r.e);b.setAttribute('aria-label','End');
  k.innerHTML='<option value="class">Class period</option><option value="recess">Recess or break</option>';k.value=r.k;x.type='button';
  a.addEventListener('change',function(){if(a.value){r.s=mn(a.value);write();}});
  b.addEventListener('change',function(){if(b.value){r.e=mn(b.value);write();}});
  k.addEventListener('change',function(){r.k=k.value;write();});
  x.addEventListener('click',function(){sh.rows.splice(ri,1);if(!sh.rows.length)data.splice(si,1);write();render();});
  row.appendChild(a);row.appendChild(el('span',null,'to'));row.appendChild(b);row.appendChild(k);row.appendChild(x);card.appendChild(row);});
 var add=el('button','plain small','Add period');add.type='button';
 add.addEventListener('click',function(){var l=sh.rows[sh.rows.length-1],s=l?l.e:360;sh.rows.push({s:s,e:s+60,k:'class'});write();render();});
 card.appendChild(add);box.appendChild(card);});}
document.getElementById('addshift').addEventListener('click',function(){var n=(prompt('Name of the new shift (one word, for example AM or PM):')||'').replace(/\s+/g,'').toUpperCase();
 if(!n)return;data.push({name:n,rows:[{s:360,e:420,k:'class'}]});write();render();});
ta.addEventListener('input',function(){parse();render();});parse();render();})();</script><div class="card" id="reset"><h3>Reset test data</h3>
<p>Use this before testing again with fresh data. It deletes only the records that administrators enter or generate:</p>
<ul class="resetlist"><li><b>{{ rc.teachers }}</b> teacher accounts (with their notifications, qualifications and loading)</li><li><b>{{ rc.sections }}</b> sections and their subject assignments</li><li><b>{{ rc.classes }}</b> generated class period records (every class program)</li><li><b>{{ rc.rooms }}</b> rooms <span class="hint">(optional, see below)</span></li><li><b>{{ rc.requests }}</b> pending account and password requests and unused codes</li></ul>
<p><b>Kept:</b> administrator accounts and passwords, school setup and timetable, email settings, the subject list (including subjects you added), reports and the audit trail. No table is dropped. This cannot be undone.</p>
<form method="post" data-confirm="Delete all test data listed above? This cannot be undone.">{{ csrf_field() }}<input type="hidden" name="action" value="reset_people">
<label class="chk"><input type="checkbox" name="with_rooms" value="1" checked><span>Also delete all registered rooms</span></label>
<label for="confirm_reset">Type DELETE to confirm</label><input id="confirm_reset" name="confirm" autocomplete="off" required>
<div class="btnrow"><button class="danger" type="submit">Reset test data</button></div></form></div>

{% endblock %}""",

"sections.html": r"""{% extends "base.html" %}{% from "macros.html" import adviser_picker with context %}{% block title %}Section Management{% endblock %}
{% block content %}<h1>Section Management</h1>
<div class="scroll"><table data-tools="sections" data-sortname class="list" id="sectab"><thead><tr><th data-ts="text">Section</th><th data-ts="num" data-tf>Grade</th><th data-ts="text" data-tf>Track and cluster</th><th data-ts="text" data-tf>Shift</th><th data-ts="text">Room</th><th data-ts="text">Adviser</th><th data-ts="text" data-tf>Loading</th><th></th></tr></thead><tbody>
{% for s in rows %}<tr data-find="{{ (s.name ~ ' ' ~ (s.room or '') ~ ' ' ~ (s.track or '') ~ ' ' ~ (s.cluster or '') ~ ' ' ~ (s.adviser or ''))|lower }}"><td data-tv="{{ s.name|shortsec }}"><a href="{{ url_for('program', section=s.id) }}">{{ s.name|shortsec }}</a></td><td>{{ s.grade }}</td>
<td data-tv="{{ (s.track ~ ' - ' ~ s.cluster) if s.track and s.cluster else 'Needs track and cluster' }}">{% if s.track and s.cluster %}{{ s.track }}<span class="cur-spec">{{ s.cluster }}</span>{% else %}<span class="pill new">Needs track and cluster</span>{% endif %}</td><td><b>{{ 'AM' if s.grade == 11 else 'PM' }}</b></td><td>{{ s.room or '-' }}</td><td>{{ s.adviser or '-' }}</td>
<td class="{{ 'okt' if s.nsub and s.nload == s.nsub else 'why' }}" data-tv="{{ 'Complete' if s.nsub and s.nload == s.nsub else 'Needs teachers' }}">{{ s.nload }} of {{ s.nsub }} subjects have a teacher</td>
<td><div class="row-acts"><a class="btn plain small" href="{{ url_for('section_edit', sid=s.id) }}" data-modal-href="{{ url_for('section_edit', sid=s.id) }}" data-modal-title="Edit section">Edit</a>
<form method="post" action="{{ url_for('section_delete', sid=s.id) }}" onsubmit="return confirm('Delete this section and its entire class program?')">{{ csrf_field() }}<button class="danger">Delete</button></form></div></td></tr>
{% else %}<tr><td colspan="8" class="empty">No sections yet. Register them in Quick Input.</td></tr>{% endfor %}</tbody></table></div>
{% endblock %}""",

"section_edit.html": r"""{% extends "base.html" %}{% from "macros.html" import back, adviser_picker with context %}{% block title %}Edit section{% endblock %}
{% block content %}<div class="titlerow">{{ back(url_for('sections'), 'Back to sections') }}<h1>Edit section</h1></div>
<div class="card"><form method="post" data-secform data-edit="1">{{ csrf_field() }}<div class="formgrid">
<div><label for="grade">Grade level</label><select id="grade" name="grade"><option value="11" {{ 'selected' if s and s.grade == 11 }}>11</option><option value="12" {{ 'selected' if s and s.grade == 12 }}>12</option></select></div>
<div><label for="name">Section name</label><input id="name" name="name" value="{{ (s.name|shortsec) if s else '' }}" required></div>
<div><label for="track">Track</label><select id="track" name="track"><option value="">Not set</option>{% for tr in tracks %}<option value="{{ tr }}" {{ 'selected' if s and s.track == tr }}>{{ tr }}</option>{% endfor %}</select></div>
<div><label for="cluster">Elective (cluster)</label><select id="cluster" name="cluster"><option value="">Not set</option>{% for tr in tracks %}<optgroup label="{{ tr }}">{% for c in offered_clusters[tr] %}<option value="{{ c }}" {{ 'selected' if s and s.cluster == c }}>{{ c }}</option>{% endfor %}{% if s and s.cluster and s.cluster in track_clusters[tr] and s.cluster not in offered_clusters[tr] %}<option value="{{ s.cluster }}" selected>{{ s.cluster }} (turned off)</option>{% endif %}</optgroup>{% endfor %}</select></div>
<div><label for="room">Home room</label><select id="room" name="room"><option value="">Not assigned</option>{% for r in room_opts %}<option value="{{ r.name }}" {{ 'selected' if s and s.room == r.name }} {{ 'disabled' if not r.free }}>{{ r.label }}{{ ' (unavailable: ' ~ r.why ~ ')' if not r.free }}</option>{% endfor %}</select><p class="hint" id="roomhint">{% if s and s.room and s.room not in room_opts|selectattr('free')|map(attribute='name') %}{{ s.room }} is no longer available for this grade level. Choose another room.{% elif not room_opts %}No classroom is registered yet. Register rooms in Quick Input first.{% elif not room_opts|selectattr('free')|list %}All {{ room_opts|length }} registered classroom(s) are in use for this grade level and shift.{% endif %}</p></div>
<div><label for="adv_q">Adviser</label>{{ adviser_picker(teachers, s.adviser_id if s else none) }}</div></div>
<script>(function(){document.querySelectorAll('form[data-secform]').forEach(function(f){var gr=f.querySelector('[name=grade]'),sf=f.querySelector('[name=shift]');if(!f.getAttribute('data-edit')&&gr&&sf)gr.addEventListener('change',function(){sf.value=gr.value==='12'?'PM':'AM';});var tr=f.querySelector('[name=track]'),cl=f.querySelector('[name=cluster]');if(!tr||!cl)return;
var all=[].map.call(cl.querySelectorAll('option'),function(o){return {v:o.value,t:o.textContent,g:o.parentNode.tagName==='OPTGROUP'?o.parentNode.label:''};});
var none=all.filter(function(x){return !x.g;})[0]||{v:'',t:'Not set'},groups=[];
all.forEach(function(x){if(x.g&&groups.indexOf(x.g)<0)groups.push(x.g);});
function mk(x){var o=document.createElement('option');o.value=x.v;o.textContent=x.t;return o;}
function build(){var t=tr.value,keep=cl.value;cl.innerHTML='';cl.appendChild(mk(none));
 groups.forEach(function(g){if(t&&g!==t)return;var host=cl;if(!t){host=document.createElement('optgroup');host.label=g;cl.appendChild(host);}
  all.filter(function(x){return x.g===g;}).forEach(function(x){host.appendChild(mk(x));});});
 cl.value=keep;if(cl.value!==keep)cl.value='';}
tr.addEventListener('change',build);
cl.addEventListener('change',function(){var x=all.filter(function(a){return a.v===cl.value&&a.g;})[0];if(x&&tr.value!==x.g){tr.value=x.g;build();cl.value=x.v;}});
var rm=f.querySelector('[name=room]'),gr=f.querySelector('[name=grade]'),hint=document.getElementById('roomhint'),rj=null;
function rooms(){if(!rj){try{rj=JSON.parse(document.getElementById('roomdata').textContent);}catch(e){rj={};}}var g=gr.value,list=rj[g]||[],keep=rm.value;rm.innerHTML='';var o=document.createElement('option');o.value='';o.textContent='Not assigned';rm.appendChild(o);
 var free=0;list.forEach(function(x){var p=document.createElement('option');p.value=x.name;p.textContent=x.free?x.label:x.label+' (unavailable: '+x.why+')';if(!x.free)p.disabled=true;else free++;rm.appendChild(p);});rm.value=keep;if(rm.value!==keep)rm.value='';
 hint.textContent=free?'':(list.length?'All '+list.length+' registered classroom(s) are in use for Grade '+g+'. Move the section that uses one, or register another room in Quick Input.':'No classroom is registered yet. Register rooms in Quick Input first.');}
if(rm&&gr&&hint){gr.addEventListener('change',rooms);}
build();});})();</script><script type="application/json" id="roomdata">{{ room_json|tojson }}</script><p class="hint">Only registered rooms that are open to the grade level and free at that shift are listed. The shift is automatic: Grade 11 is AM and Grade 12 is PM.</p><p class="hint">Changing the cluster replaces the cluster subject of this section. Its class program is then marked out of date.</p>
<div class="btnrow"><button type="submit">Save changes</button><a class="btn plain" href="{{ url_for('sections') }}">Cancel</a></div></form></div>{% endblock %}""",

"users.html": r"""{% extends "base.html" %}{% block title %}User Management{% endblock %}
{% block content %}<h1>User Management</h1>{{ subnav('users') }}
<details class="card"><summary>Add an administrator</summary><form method="post" style="margin-top:.8rem">{{ csrf_field() }}<input type="hidden" name="action" value="add_admin"><div class="formgrid">
<div><label for="full_name">Full name</label><input id="full_name" name="full_name" required></div><div><label for="username">Username</label><input id="username" name="username" required></div>
<div><label for="password">Password</label><input id="password" name="password" minlength="6" required></div><div><button type="submit" style="margin-top:.7rem">Create administrator</button></div></div></form></details>
<div class="scroll"><table data-tools="accounts" class="list"><thead><tr><th data-ts="text">Name</th><th data-ts="text">Username</th><th data-ts="text">ID</th><th data-ts="text" data-tf>Role</th><th></th></tr></thead><tbody>
{% for u in rows %}<tr><td>{{ u.full_name }}</td><td>{{ u.username }}</td><td>{{ u.teacher_id or '-' }}</td><td><span class="user-role {{ u.role }}">{{ 'Administrator' if u.role == 'admin' else cats.get(u.category, 'Teacher') }}</span></td>
<td><div class="row-acts">{% if u.role == 'teacher' %}<a class="btn plain small" href="{{ url_for('teacher_edit', tid=u.id) }}" data-modal-href="{{ url_for('teacher_edit', tid=u.id) }}" data-modal-title="Edit teacher">Edit</a>{% endif %}
{% if u.id != g.user.id %}<form method="post" onsubmit="return confirm('Set the password of {{ u.full_name }} to {{ temp }}?')">{{ csrf_field() }}<input type="hidden" name="action" value="reset_pw"><input type="hidden" name="uid" value="{{ u.id }}"><button class="plain small">Reset password</button></form>
{% if u.role == 'admin' %}<form method="post" onsubmit="return confirm('Delete this administrator account?')">{{ csrf_field() }}<input type="hidden" name="action" value="delete_admin"><input type="hidden" name="uid" value="{{ u.id }}"><button class="danger">Delete</button></form>{% endif %}{% else %}<span class="hint">You</span>{% endif %}</div></td></tr>{% endfor %}</tbody></table></div>{% endblock %}""",

"user_roles.html": r"""{% extends "base.html" %}{% block title %}Roles and permissions{% endblock %}
{% block content %}<h1>User Management</h1>{{ subnav('users') }}
<p style="color:var(--muted)">What each role can do. The program enforces these on every page.</p>
{% for name, key, rights in roles %}<div class="card"><h3>{{ name }} <span class="user-role {{ 'admin' if key == 'ADMIN' }}">{{ counts.get(key, 0) }} account(s)</span></h3><ul class="issues">{% for r in rights %}<li>{{ r }}</li>{% endfor %}</ul></div>{% endfor %}{% endblock %}""",

"user_audit.html": r"""{% extends "base.html" %}{% block title %}Audit trail{% endblock %}
{% block content %}<h1>User Management</h1>{{ subnav('users') }}
<form method="get" class="card"><div class="formgrid"><div><label for="q">Search</label><input id="q" name="q" value="{{ q }}" aria-label="Search"></div>
<div><label for="who">Role</label><select id="who" name="who"><option value="">All</option><option value="admin" {{ 'selected' if who == 'admin' }}>Administrators</option><option value="teacher" {{ 'selected' if who == 'teacher' }}>Teachers</option></select></div>
<div class="fgbtn"><button type="submit" data-noconfirm>Filter</button></div></div></form>
<div class="scroll"><table class="list"><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Detail</th></tr></thead><tbody>
{% for r in rows %}<tr><td>{{ r.at|stamp12 }}</td><td>{{ r.who }}{% if r.role %} <span class="user-role {{ r.role }}">{{ r.role }}</span>{% endif %}</td><td>{{ r.action }}</td><td class="hint">{{ r.detail or '' }}</td></tr>
{% else %}<tr><td colspan="4" class="empty">Nothing recorded yet.</td></tr>{% endfor %}</tbody></table></div>{% endblock %}""",

"teachers.html": r"""{% extends "base.html" %}{% from "macros.html" import tsearch, otime, durselect, specpick with context %}{% block title %}Teacher Management{% endblock %}
{% block content %}<h1>Teacher Management</h1>
{{ tsearch() }}
<form method="post" action="{{ url_for('assignments') }}">{{ csrf_field() }}<input type="hidden" name="action" value="save">
<div class="scroll"><table data-tools="teachers" data-nosearch data-sortname class="list assign tm"><thead><tr><th data-ts="text">Teacher</th><th data-ts="text" data-tf>Grade level handled</th><th data-ts="text">Specialization</th><th>Official time</th><th data-ts="num" data-tf>Teaching load</th><th class="editth">Edit</th></tr></thead><tbody>
{% for t in rows %}{% set k = t.id %}<tr class="arow" data-tid="{{ t.id }}" data-cat="{{ t.category }}" data-find="{{ (t.full_name ~ ' ' ~ t.teacher_id ~ ' ' ~ (t.specialization or '') ~ ' ' ~ (t.subject_area or ''))|lower }}">
<td data-tv="{{ t.full_name }}"><div class="tn">{{ tlabels.get(k) }}</div><input name="name_{{ k }}" value="{{ t.full_name }}" aria-label="Name of {{ tlabels.get(k) }}" required>
<p class="hint">{{ t.teacher_id }}<br><a href="{{ url_for('teacher_view', tid=k) }}">View program</a> &middot; <a href="{{ url_for('teacher_edit', tid=k) }}" data-modal-href="{{ url_for('teacher_edit', tid=k) }}" data-modal-title="Edit teacher">More details</a></p></td>
<td><select name="cat_{{ k }}" aria-label="Grade level handled by {{ tlabels.get(k) }}">{% for c, v in cats.items() %}<option value="{{ c }}" {{ 'selected' if c == t.category }}>{{ catname[c] }}</option>{% endfor %}</select></td>
<td>{{ specpick('spec_' ~ k, t.specialization, 'Specialization') }}</td>

<td>{{ otime('time_' ~ k, t.official_time, 'Official time of ' ~ tlabels.get(k)) }}</td>
<td data-tv="{{ summ[k].loads }}"><b>{{ summ[k].loads }}</b> section{{ '' if summ[k].loads == 1 else 's' }}<p class="hint">{{ summ[k].subs }} subject{{ '' if summ[k].subs == 1 else 's' }} &middot; {{ summ[k].asg_w|hrs }} per week</p></td>
<td class="editcell"><div class="row-acts"><button type="button" class="plain small rowedit" data-modal-href="{{ url_for('teacher_edit', tid=k) }}" data-modal-title="Edit teacher">Edit</button><span class="rowsave" hidden><button type="submit" class="small">Save</button><button type="button" class="plain small rowcancel">Cancel</button></span></div></td></tr>
{% else %}<tr><td colspan="6" class="empty">No teachers yet. Register them in Quick Input.</td></tr>{% endfor %}<tr id="tqnone" hidden><td colspan="6" class="empty">No teacher matches your search.</td></tr></tbody></table></div>
</form>
<script>(function(){
var rows=[].slice.call(document.querySelectorAll('tr.arow'));
function ctl(r){return [].slice.call(r.querySelectorAll('input,select,textarea'));}
/* Read-only view shows plain wrapped text, so nothing is cut off or needs scrolling. */
function setup(r){
r.querySelectorAll('td:not(.editcell)').forEach(function(td){
var ot=td.querySelector('.otime');
if(ot){ot.classList.add('vc');var sp=document.createElement('span');sp.className='vtext';sp.setAttribute('data-kind','otime');ot.parentNode.insertBefore(sp,ot);}
td.querySelectorAll('input,select,textarea').forEach(function(c){
if(c.type==='hidden'||c.closest('.otime')||c.closest('.specpick'))return;
c.classList.add('vc');var sp=document.createElement('span');sp.className='vtext';sp.__c=c;c.parentNode.insertBefore(sp,c);});});}
function refresh(r){r.querySelectorAll('.vtext').forEach(function(sp){var t='',mute=false;
if(sp.getAttribute('data-kind')==='otime'){var h=sp.parentNode.querySelector('input[data-official]');t=h?h.value:'';}
else{var c=sp.__c;if(c.tagName==='SELECT'){t=c.options[c.selectedIndex]?c.options[c.selectedIndex].text:'';}
else{t=c.value;if(!t&&c.placeholder){t=c.placeholder;mute=true;}}}
sp.textContent=t||'-';sp.classList.toggle('muted',mute||!t);});}
function lock(r,on){if(on)refresh(r);r.classList.toggle('rowview',on);r.classList.toggle('rowedit-on',!on);
ctl(r).forEach(function(c){c.disabled=on;});
r.querySelector('.rowedit').hidden=!on;r.querySelector('.rowsave').hidden=on;}
rows.forEach(function(r){setup(r);lock(r,true);
r.querySelector('.rowedit').addEventListener('click',function(){lock(r,false);var f=r.querySelector('input.vc:not([disabled]),textarea.vc:not([disabled])');if(f)f.focus();});
r.querySelector('.rowcancel').addEventListener('click',function(){
ctl(r).forEach(function(c){
if(c.tagName==='SELECT'){[].forEach.call(c.options,function(o){o.selected=o.defaultSelected;});}
else if(c.type==='checkbox'){c.checked=c.defaultChecked;}else{c.value=c.defaultValue;}
c.dispatchEvent(new Event('input',{bubbles:true}));c.dispatchEvent(new Event('change',{bubbles:true}));});
lock(r,true);});});
var AUTO={{ auto_hm|tojson }};
rows.forEach(function(r){var s=r.querySelector('select[name^="cat_"]');if(!s)return;var prev=s.value;
s.addEventListener('change',function(){var a=r.querySelector('.ot-from'),b=r.querySelector('.ot-to');if(!a||!b){prev=s.value;return;}
var o=AUTO[prev]||['',''],n=AUTO[s.value]||['',''];
if((!a.value&&!b.value)||(a.value===o[0]&&b.value===o[1])){a.value=n[0];b.value=n[1];a.dispatchEvent(new Event('input',{bubbles:true}));}
prev=s.value;});});
})();</script>{% endblock %}""",

"teacher_edit.html": r"""{% extends "base.html" %}{% from "macros.html" import back, otime, durselect, specpick with context %}{% block title %}Edit teacher{% endblock %}
{% block content %}<div class="titlerow">{{ back(url_for('teachers'), 'Back to teachers') }}<h1>Edit teacher details</h1></div>
<div class="card"><form method="post">{{ csrf_field() }}
<h3>Account</h3><div class="formgrid">
<div><label for="full_name">Full name</label><input id="full_name" name="full_name" value="{{ t.full_name }}" required></div>
<div><label for="teacher_num">Teacher ID</label><div class="tidfield"><span class="tidfix">T-</span><input id="teacher_num" name="teacher_num" type="number" min="1" step="1" value="{{ (t.teacher_id or 'T-')[2:] }}" required></div></div>
<div><label for="username">Username</label><input id="username" name="username" value="{{ t.username }}" required></div>
<div><label for="category">Teacher type</label><select id="category" name="category">{% for k, v in cats.items() %}<option value="{{ k }}" {{ 'selected' if k == t.category }}>{{ v }}</option>{% endfor %}</select></div></div>
<h3 style="margin-top:1.4rem">Teacher's program details</h3><div class="formgrid">
<div><label for="item">Item</label><input id="item" name="item" value="{{ t.item or '' }}"></div>
<div class="wide"><label>Official time (start to end)</label>{{ otime('official_time', t.official_time, 'Official time') }}</div>
<div class="wide"><label>Specialization (choose from the subject list)</label>{{ specpick('specialization', t.specialization) }}</div>
<div><label for="max_sections">Most sections this teacher can be given</label><input id="max_sections" name="max_sections" type="number" min="1" max="20" step="1" inputmode="numeric" value="{{ t.max_sections or '' }}"></div>
<div><label>Teaching load</label><p class="roval"><b>{{ tl.loads }}</b> section{{ '' if tl.loads == 1 else 's' }} &middot; {{ tl.subs }} subject{{ '' if tl.subs == 1 else 's' }}</p></div>
<div class="wide"><label>Ancillary (advisory class)</label><p class="roval">{{ anc }}</p></div>
<div><label>Intervention / Remediation time per day</label>{{ durselect('intervention_min', t.intervention_min or 0, 'Intervention time per day') }}</div>
<div><label>Ancillary / Adviser's time per day</label>{{ durselect('ancillary_min', t.ancillary_min or 0, 'Ancillary time per day') }}</div>
</div>
<div class="btnrow"><button type="submit">Save changes</button>
<a class="btn plain" href="{{ url_for('teachers') }}">Cancel</a></div></form></div><div class="card"><h3>Delete this teacher</h3><p class="hint">Their class periods and advisory become unassigned.</p><form method="post" action="{{ url_for('teacher_delete', tid=t.id) }}" onsubmit="return confirm('Delete this teacher account?')">{{ csrf_field() }}<button class="danger">Delete teacher account</button></form></div>{% endblock %}""",

"auto_loading.html": r"""{% extends "base.html" %}{% block title %}Teacher Load Summary{% endblock %}
{% block content %}<h1>Teacher Loading</h1>{{ subnav('loading') }}
<div class="scroll"><table data-tools="teachers" class="list"><thead><tr><th data-ts="text">Teacher</th><th>Official time</th><th data-ts="num">Classes handled</th><th data-ts="num">Different subjects</th><th data-ts="num">Assigned per week</th><th data-ts="text" data-tf>Status</th></tr></thead><tbody>
{% for x in lv.rows %}<tr><td>{{ tlabels.get(x.t.id) }} {{ x.t.full_name }}</td><td>{{ x.window }}</td><td>{{ x.nsec }}</td><td>{{ x.npre }}</td><td>{{ x.minutes|hrs }} of {{ lv.maxweek|hrs }}</td><td class="{{ 'okt' if x.status == 'OK' else 'why' }}">{{ x.status }}</td></tr>
{% else %}<tr><td colspan="6" class="empty">No teachers yet.</td></tr>{% endfor %}</tbody></table></div>{% endblock %}""",

"auto_generate.html": r"""{% extends "base.html" %}{% block title %}Schedule Generator{% endblock %}
{% block content %}<h1>Schedule Generator</h1>
<style>
.gen-steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:.8rem;margin:.6rem 0 1rem}
.gen-steps .gs{border:1px solid var(--line);border-radius:10px;padding:.8rem 1rem;background:#fff}
.gen-steps .gs b{display:block;color:var(--navy)}
.gen-banner{border-left:4px solid var(--ok);padding:.8rem 1rem;border-radius:8px;background:#fff;margin:.8rem 0;font-weight:700}
.gen-banner.bad{border-left-color:var(--bad)}
.gen-busy{position:fixed;inset:0;background:rgba(255,255,255,.88);display:none;align-items:center;justify-content:center;z-index:50;text-align:center;padding:1rem}
.gen-busy.on{display:flex}
.gen-busy .sp{width:42px;height:42px;border:4px solid var(--line);border-top-color:var(--blue);border-radius:50%;animation:gspin 1s linear infinite;margin:0 auto .8rem}
@keyframes gspin{to{transform:rotate(360deg)}}
.gen-fix td{vertical-align:top}
</style>
<div class="gen-steps"><div class="gs"><b>1. Complete the inputs</b>Sections and electives, teachers and their subjects, rooms. <a href="{{ url_for('quick_input') }}">Open Quick Input</a></div>
<div class="gs"><b>2. Validate</b>Checks everything. Changes nothing.</div>
<div class="gs"><b>3. Generate</b>Assigns teachers, rooms and times together and saves them.</div>
<div class="gs"><b>4. View results</b>Every section's program, teachers and rooms.</div></div>
{% if locked %}<div class="msg notice">The schedule is approved and locked. Reopen it in Validation Center (Final approval) before generating again.</div>{% endif %}
{% if stale %}<div class="msg notice">Changed since the programs were generated: <b>{{ stale|join(', ') }}</b>. Validate and generate again to refresh them.</div>{% endif %}
<div class="card"><h3 style="margin-top:0">Step 2. Validate</h3><p class="hint">Only checks the saved records. It does not create schedules, assign teachers or touch the current class programs.</p>
<form method="post" data-noconfirm>{{ csrf_field() }}<input type="hidden" name="action" value="validate"><button type="submit" data-busy="Validating...">VALIDATE ALL REQUIREMENTS</button></form>
{% if lv %}
{% if outdated %}<div class="msg notice" style="margin-top:.8rem">Records changed after this validation ({{ lv.when|stamp12 }}). Validate again before generating.</div>{% endif %}
<div class="kpis" style="margin-top:.8rem"><div class="kpi"><b>{{ lv.counts.sections }}</b><span>sections</span></div><div class="kpi"><b>{{ lv.counts.subjects }}</b><span>required subjects</span></div><div class="kpi"><b>{{ lv.counts.teachers }}</b><span>teachers</span></div><div class="kpi"><b>{{ lv.counts.rooms }}</b><span>rooms</span></div><div class="kpi"><b>{{ lv.counts.matches }}</b><span>qualified teacher matches</span></div><div class="kpi {{ 'bad' if lv.counts.missing else 'ok' }}"><b>{{ lv.counts.missing }}</b><span>missing requirements</span></div><div class="kpi {{ 'bad' if lv.counts.conflicts else 'ok' }}"><b>{{ lv.counts.conflicts }}</b><span>stored schedule conflicts</span></div><div class="kpi"><b>{{ lv.counts.unavailable }}</b><span>teachers without subjects</span></div></div>
{% if lv.ok %}<div class="gen-banner">ALL REQUIREMENTS VERIFIED. YOUR SYSTEM IS READY FOR CLASS PROGRAM GENERATION.</div>
{% else %}<div class="gen-banner bad">{{ lv.errors|length }} problem(s) must be fixed before generating.</div>
<div class="scroll"><table class="list gen-fix"><thead><tr><th>Module</th><th>Where</th><th>Problem</th><th>How to fix</th><th></th></tr></thead><tbody>
{% for e in lv.errors %}<tr><td>{{ e.module }}</td><td><b>{{ e.where }}</b></td><td class="why">{{ e.problem }}</td><td>{{ e.fix }}</td><td><a class="btn plain small" href="{{ url_for(e.ep) }}">Open</a></td></tr>{% endfor %}</tbody></table></div>{% endif %}
{% if lv.warnings %}<details style="margin-top:.6rem"><summary>{{ lv.warnings|length }} note(s)</summary><ul>{% for w in lv.warnings %}<li><b>{{ w.where }}</b>: {{ w.problem }} {{ w.fix }}</li>{% endfor %}</ul></details>{% endif %}
{% endif %}</div>
{% if complete and valid_now and not locked %}<div class="gen-banner">CLASS PROGRAMS ARE COMPLETE. Every section has its teachers and times and there are no conflicts. You do not need to generate again. Review the programs below, then approve them in Validation Center.</div>{% endif %}
<div class="card autocard"><h3 style="margin-top:0">Step 3. Generate</h3>{% if complete and valid_now and not locked %}<p class="hint">Only generate again if you changed something and want new class programs. The current programs are kept if generation fails.</p>{% else %}<p class="hint">Assigns teachers, rooms and time slots for every section in one step. Everything is saved together, or nothing is saved.</p>{% endif %}
<form method="post" id="genform" data-noconfirm>{{ csrf_field() }}<input type="hidden" name="action" value="generate"><input type="hidden" name="token" value="{{ token }}"><input type="hidden" name="confirm_overwrite" value="0" id="cov">
<button type="submit" id="genbtn" class="{{ 'plain' if complete and valid_now }}" {{ 'disabled' if not valid_now or locked }}>GENERATE ALL CLASS PROGRAMS AND ASSIGN TEACHERS</button></form>
{% if not valid_now and not locked %}<p class="why" style="margin-bottom:0">{{ 'Validate again: the records changed.' if outdated else 'Locked until validation passes. Click VALIDATE ALL REQUIREMENTS first.' }}</p>{% endif %}
{% if has_programs %}<p class="hint">Class programs already exist. You will be asked to confirm before they are replaced. If generation fails, they are kept unchanged.</p>{% endif %}</div>
<div class="gen-busy" id="genbusy" role="status" aria-live="polite"><div><div class="sp"></div><b>Generating class programs...</b><p class="hint">Matching teachers, assigning rooms, placing time slots, checking conflicts and saving. This can take up to a minute. Please do not close or reload this page.</p></div></div>
<script>(function(){var f=document.getElementById('genform');if(!f)return;var sent=false;
f.addEventListener('submit',function(e){if(sent){e.preventDefault();return;}
{% if has_programs %}if(!confirm('Replace the existing class programs of all sections? If generation fails, the current programs are kept.')){e.preventDefault();return;}document.getElementById('cov').value='1';{% endif %}
sent=true;document.getElementById('genbusy').classList.add('on');document.querySelectorAll('button').forEach(function(b){b.disabled=true;});setTimeout(function(){document.getElementById('cov').value=document.getElementById('cov').value;},0);});})();</script>
<div id="results">{% if lg %}<div class="gen-banner {{ '' if lg.ok else 'bad' }}">{{ lg.message }}{% if lg.ok %} <span class="hint">{{ lg.sections }} sections, {{ lg.placed }} class meetings, {{ lg.when|stamp12 }}</span>{% endif %}</div>
{% if lg.details %}<div class="card"><h3 style="margin-top:0">What needs attention</h3><ul>{% for d in lg.details %}<li class="why">{{ d }}</li>{% endfor %}</ul><p class="hint">Fix these in the modules above, then validate and generate again. The previous class programs were not changed.</p></div>{% endif %}{% endif %}
{% if has_programs %}<div class="card"><h3 style="margin-top:0">Step 4. Class programs</h3>
<form method="get"><label for="secsel">Section</label><select id="secsel" name="section" onchange="this.form.submit()">{% for s in secs if s.n %}<option value="{{ s.id }}" {{ 'selected' if s.id == sel }}>{{ s.name }} ({{ s.n }} meetings)</option>{% endfor %}</select></form>
<div class="scroll"><table class="list"><thead><tr><th>Day</th><th>Time</th><th>Subject</th><th>Teacher</th><th>Room</th></tr></thead><tbody>
{% for r in rows %}<tr><td>{{ r.day }}</td><td>{{ r.start|t12 }} to {{ r.end|t12 }}</td><td>{{ r.subject }}</td><td>{{ r.teacher or '-' }}</td><td>{{ r.room or '-' }}</td></tr>{% else %}<tr><td colspan="5" class="empty">No class periods for this section.</td></tr>{% endfor %}</tbody></table></div>
{% if sel %}<p><a class="btn plain small" href="{{ url_for('program', section=sel) }}">Open full class program</a></p>{% endif %}</div>
{% if room_notes %}<details class="card"><summary>{{ room_notes|length }} room note(s) (do not block anything)</summary><ul>{% for n in room_notes %}<li class="hint">{{ n }}</li>{% endfor %}</ul></details>{% endif %}
<div class="card"><h3 style="margin-top:0">Teacher workload</h3><div class="scroll"><table class="list"><thead><tr><th>Teacher</th><th>Sections</th><th>Weekly teaching</th><th>Limit</th></tr></thead><tbody>
{% for w in workload %}<tr><td>{{ w.name }}</td><td>{{ w.sections }}</td><td>{{ w.minutes|hrs }}</td><td class="{{ 'why' if w.minutes > maxweek }}">{{ maxweek|hrs }}{{ ' (exceeded)' if w.minutes > maxweek }}</td></tr>{% else %}<tr><td colspan="4" class="empty">No teacher has a class yet.</td></tr>{% endfor %}</tbody></table></div></div>{% endif %}</div>
{% endblock %}""",

"quick_input.html": r"""{% extends "base.html" %}{% from "macros.html" import specpick with context %}{% block title %}Quick Input{% endblock %}
{% block content %}<h1>Quick Input</h1>
<style>
.qi-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:.8rem;margin:1rem 0}
.qi-tile{display:flex;flex-direction:column;gap:.15rem;text-align:left;background:#fff;border:1px solid var(--line);border-radius:10px;padding:.9rem 1.1rem;cursor:pointer;font:inherit;color:var(--ink);box-shadow:none;transition:border-color .15s,box-shadow .15s}
.qi-tile:hover{border-color:var(--blue)}
.qi-tile.on{border-color:var(--blue);box-shadow:0 0 0 2px var(--tint) inset;background:var(--tint)}
.qi-tile .n{font-size:1.9rem;font-weight:700;color:var(--navy);line-height:1}
.qi-tile .l{font-weight:600}
.qi-tile small{color:var(--muted)}
.qi-panel{display:none}.qi-panel.on{display:block}
.qi-nojs .qi-panel{display:block}
.qi-bar{display:flex;flex-wrap:wrap;gap:.7rem 1rem;align-items:end;margin:.4rem 0 .8rem}
.qi-bar.qi-bar-t{display:grid;grid-template-columns:7.5rem minmax(11rem,15rem) minmax(15rem,1fr) auto;align-items:start}
.qi-bar.qi-bar-t>div{min-width:0}.qi-bar.qi-bar-t .qi-dspec{flex:none}
@media(max-width:820px){.qi-bar.qi-bar-t{grid-template-columns:1fr 1fr}.qi-bar.qi-bar-t .qi-dspec,.qi-bar.qi-bar-t .qi-apply{grid-column:1/-1}.qi-bar.qi-bar-t .qi-apply button{width:100%}}
@media(max-width:480px){.qi-bar.qi-bar-t{grid-template-columns:1fr}}
.qi-bar label{display:block;font-size:.85rem;font-weight:600;margin-bottom:.15rem}
.qi-bar input[type=number]{width:6.5rem}
.qi-grid{display:grid;gap:.5rem;margin:.6rem 0}
.qi-row{display:grid;grid-template-columns:2.2rem minmax(160px,2fr) repeat(var(--cols,2),minmax(130px,1fr)) 2.4rem;gap:.5rem;align-items:start;background:#fafbff;border:1px solid var(--line);border-radius:8px;padding:.5rem .6rem}
.qi-row.bad{border-color:var(--bad);background:#fff6f6}
.qi-row .no{color:var(--muted);font-weight:600;padding-top:.55rem;text-align:center}
.qi-row input,.qi-row select{width:100%;margin:0}
.qi-row .msg{grid-column:2/-1;color:var(--bad);font-size:.82rem;margin:0}
.qi-row .x{background:none;border:0;box-shadow:none;color:var(--bad);font-size:1.3rem;line-height:1;padding:.3rem;cursor:pointer}
.qi-row.t{grid-template-columns:2.2rem minmax(180px,2fr) minmax(150px,1fr) minmax(180px,1fr) 2.4rem}
.qi-sum{font-weight:600;margin:.4rem 0}.qi-sum.bad{color:var(--bad)}.qi-sum.ok{color:var(--ok)}
.qi-list td,.qi-list th{vertical-align:middle}
.qi-edit td{background:#f6f7ff}
.qi-edit .formgrid{margin:.2rem 0}
.qi-badge{display:inline-block;padding:.1rem .55rem;border-radius:999px;font-size:.78rem;font-weight:600;background:var(--tint);color:var(--navy)}
.qi-badge.tp{background:#fff3d6;color:#7a5600}
.qi-two{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1rem}
.qi-two ul{margin:.3rem 0 0 1.1rem;padding:0}
.qi-ro{background:#f4f5fb;border-radius:8px;padding:.6rem .9rem;margin:.6rem 0;color:var(--muted);font-size:.9rem}
.qi-acts{display:flex;gap:.4rem;flex-wrap:wrap}
.qi-acts form{margin:0}
@media(max-width:720px){.qi-row,.qi-row.t{grid-template-columns:1fr}.qi-row .no{text-align:left;padding-top:0}.qi-row .msg{grid-column:1}}
</style>
{% if approved %}<div class="msg error">The schedule is approved and locked. Reopen it in Validation Center to change Quick Input.</div>{% endif %}

<div class="qi-tiles" role="tablist" aria-label="Quick Input categories">
<button type="button" class="qi-tile" data-tab="sections" role="tab"><span class="n">{{ all_secs|length }}</span><span class="l">Sections</span><small>Grade 11 and 12 sections</small></button>
<button type="button" class="qi-tile" data-tab="tracks" role="tab"><span class="n">2</span><span class="l">Tracks</span><small>Academic and TechPro</small></button>
<button type="button" class="qi-tile" data-tab="teachers" role="tab"><span class="n">{{ teachers|length }}</span><span class="l">Teachers</span><small>With specializations</small></button>
<button type="button" class="qi-tile" data-tab="rooms" role="tab"><span class="n">{{ rooms|length }}</span><span class="l">Rooms</span><small>Available all school year</small></button>
</div>

<div id="qi-root" class="qi-nojs">

<!-- ======================= SECTIONS ======================= -->
<section class="qi-panel card" id="sections" data-panel="sections"><h3>Sections <span class="qi-badge">{{ all_secs|length }} registered</span></h3>
<p class="hint">Enter how many sections you need, then type each section name. Review the list and press Save All.</p>
<form method="post" id="f-sections" data-noconfirm data-kind="sections">{{ csrf_field() }}<input type="hidden" name="action" value="save_sections">
<div class="qi-bar"><div><label for="s_count">Number of sections</label><input type="number" id="s_count" min="0" max="{{ data.maxrows }}" value="0"></div>
<div><label for="s_dgrade">Grade for new rows</label><select id="s_dgrade"><option>11</option><option>12</option></select></div>
<div><label for="s_dcluster">Cluster for new rows</label><select id="s_dcluster"><option value="">Not set yet</option>{% for tr, lst in offered_clusters.items() %}<optgroup label="{{ tr }}">{% for c in lst %}<option>{{ c }}</option>{% endfor %}</optgroup>{% endfor %}</select></div>
<div><button type="button" class="plain" data-apply="sections">Apply to all rows</button></div></div>
<div class="qi-grid" data-grid="sections" style="--cols:2"></div>
<div class="qi-sum" data-sum="sections"></div>
<div class="btnrow"><button type="button" class="plain" data-more="sections">+ Add more</button> <button type="submit" data-save="sections" data-busy="Saving..." {{ 'disabled' if approved }}>Save All</button></div></form>

<h4 style="margin-top:1.4rem">Registered sections</h4>
<div class="scroll"><table data-tools="sections" class="list qi-list"><thead><tr><th data-ts="text">Section</th><th data-ts="num" data-tf>Grade</th><th data-ts="text" data-tf>Track</th><th data-ts="text" data-tf>Cluster</th><th data-tf>Class hours</th><th></th></tr></thead><tbody>
{% for s in all_secs %}<tr><td><b>{{ s.name }}</b></td><td>{{ s.grade }}</td><td>{% if s.track %}<span class="qi-badge {{ 'tp' if s.track == 'TechPro' }}">{{ s.track }}</span>{% else %}-{% endif %}</td><td>{{ s.cluster or 'Not set' }}</td><td>{{ s.shift or '-' }}</td>
<td><div class="qi-acts"><button type="button" class="plain small" data-edit="s{{ s.id }}" {{ 'disabled' if approved }}>Edit</button>
<form method="post" data-noconfirm data-confirm="Delete {{ s.name }} and its class program? This cannot be undone.">{{ csrf_field() }}<input type="hidden" name="action" value="delete_section"><input type="hidden" name="sid" value="{{ s.id }}"><button class="danger small" type="submit" {{ 'disabled' if approved }}>Delete</button></form></div></td></tr>
<tr class="qi-edit" id="edit-s{{ s.id }}" hidden><td colspan="6"><form method="post" data-noconfirm>{{ csrf_field() }}<input type="hidden" name="action" value="edit_section"><input type="hidden" name="sid" value="{{ s.id }}"><div class="formgrid">
<div><label>Section name</label><input name="name" value="{{ s.name|shortsec }}" maxlength="60" required></div>
<div><label>Grade</label><select name="grade"><option {{ 'selected' if s.grade == 11 }}>11</option><option {{ 'selected' if s.grade == 12 }}>12</option></select></div>
<div><label>Cluster</label><select name="cluster"><option value="">Not set yet</option>{% for tr, lst in offered_clusters.items() %}<optgroup label="{{ tr }}">{% for c in lst %}<option {{ 'selected' if c == s.cluster }}>{{ c }}</option>{% endfor %}</optgroup>{% endfor %}{% if s.cluster and track_of(s.cluster) and s.cluster not in offered_clusters.get(track_of(s.cluster), []) %}<option selected>{{ s.cluster }}</option>{% endif %}</select></div>
<div><button type="submit">Save changes</button> <button type="button" class="plain" data-cancel="s{{ s.id }}">Cancel</button></div></div></form></td></tr>
{% else %}<tr><td colspan="6" class="empty">No sections yet. Enter a number above to start.</td></tr>{% endfor %}</tbody></table></div></section>

<!-- ======================= TRACKS ======================= -->
<section class="qi-panel card" id="tracks" data-panel="tracks"><h3>Tracks <span class="qi-badge">2 classifications</span></h3>
<p class="hint">The Academic and TechPro tracks and their subject specializations are fixed by the Strengthened Curriculum. Sections pick a cluster (which sets the track) and teachers pick the subjects they can teach.</p>
<div class="qi-two">{% for tr in ('Academic', 'TechPro') %}<div class="card" style="margin:0"><h4 style="margin-top:0">{{ tr }} <span class="qi-badge {{ 'tp' if tr == 'TechPro' }}">{{ tstats[tr].sections }} section(s) &middot; {{ tstats[tr].teachers }} teacher(s)</span></h4>
<ul>{% for c in tstats[tr].clusters %}<li><b>{{ c.name }}</b>{% if c.specs %}<br><span class="hint">{{ c.specs|join(', ') }}</span>{% endif %}<br><span class="hint">Room type: {{ c.room }}</span></li>{% endfor %}</ul></div>{% endfor %}</div>
<div class="qi-ro"><b>Core subjects (both tracks):</b> {% for c, n in core_subjects %}{{ n.split(' (')[0] }}{{ ', ' if not loop.last }}{% endfor %}.<br>Change what is offered or how many minutes each subject gets in Subject Management.</div></section>

<!-- ======================= TEACHERS ======================= -->
<section class="qi-panel card" id="teachers" data-panel="teachers"><h3>Teachers <span class="qi-badge">{{ teachers|length }} registered</span></h3>
<p class="hint">Enter how many teachers to register, choose the grade level handled and the subjects once, press Apply to all rows, then type each full name. You can still change any single row.</p>
<form method="post" id="f-teachers" data-noconfirm data-kind="teachers">{{ csrf_field() }}<input type="hidden" name="action" value="save_new_teachers">
<div class="qi-bar qi-bar-t"><div><label for="t_count">Number of teachers</label><input type="number" id="t_count" min="0" max="{{ data.maxrows }}" value="0"></div>
<div><label for="t_dcat">Grade level handled for new rows</label><select id="t_dcat">{% for k, v in data.cats.items() %}<option value="{{ k }}">{{ v }}</option>{% endfor %}</select></div>
<div class="qi-dspec" id="t_dspec_box"><label>Subjects for new rows</label>{{ specpick('t_dspec', '', 'Subjects to teach', quick_groups) }}</div>
<div class="qi-apply"><label aria-hidden="true">&nbsp;</label><button type="button" class="plain" data-apply="teachers">Apply to all rows</button></div></div>
<div class="qi-grid" data-grid="teachers"></div>
<div class="qi-sum" data-sum="teachers"></div>
<div class="btnrow"><button type="button" class="plain" data-more="teachers">+ Add more</button> <button type="submit" data-save="teachers" data-busy="Saving..." {{ 'disabled' if approved }}>Save All</button></div></form>
<template id="tpl-spec">{{ specpick('t_spec', '', 'Subjects to teach', quick_groups) }}</template>

<h4 style="margin-top:1.4rem">Registered teachers</h4>
<div class="scroll"><table data-tools="teachers" class="list qi-list"><thead><tr><th data-ts="text">Teacher</th><th data-ts="text" data-tf>Grade level</th><th data-ts="text" data-tf>Track</th><th data-ts="text">Specialization</th><th data-tf>Class hours</th><th></th></tr></thead><tbody>
{% for t in teachers %}<tr><td><b>{{ t.full_name }}</b><br><span class="hint">{{ t.teacher_id }}</span></td><td>{{ cats.get(t.category, t.category or '-') }}</td>
<td>{% for tr in t_tracks[t.id] %}<span class="qi-badge {{ 'tp' if tr == 'TechPro' }}">{{ tr }}</span> {% else %}<span class="hint">Core only</span>{% endfor %}</td>
<td>{{ t.specialization or '-' }}</td><td>{{ tshift[t.id] or '-' }}</td>
<td><div class="qi-acts"><button type="button" class="plain small" data-edit="t{{ t.id }}" {{ 'disabled' if approved }}>Edit</button>
<form method="post" data-noconfirm data-confirm="Delete {{ t.full_name }}? Their class periods become unassigned.">{{ csrf_field() }}<input type="hidden" name="action" value="delete_teacher"><input type="hidden" name="tid" value="{{ t.id }}"><button class="danger small" type="submit" {{ 'disabled' if approved }}>Delete</button></form></div></td></tr>
<tr class="qi-edit" id="edit-t{{ t.id }}" hidden><td colspan="6"><form method="post" data-noconfirm>{{ csrf_field() }}<input type="hidden" name="action" value="edit_teacher"><input type="hidden" name="tid" value="{{ t.id }}"><div class="formgrid">
<div><label>Full name</label><input name="t_name" value="{{ t.full_name }}" maxlength="120" required></div>
<div><label>Grade level handled</label><select name="t_cat">{% for k, v in cats.items() %}<option value="{{ k }}" {{ 'selected' if k == t.category }}>{{ v }}</option>{% endfor %}</select></div>
<div><label>Class hours</label><select name="t_shift"><option value="">{{ 'Keep: ' ~ t.official_time if t.official_time else 'Automatic' }}</option>{% for s in shifts %}<option value="{{ s }}" {{ 'selected' if tshift[t.id] == s }}>{{ s }} ({{ hours[s] }})</option>{% endfor %}</select></div>
<div class="wide"><label>Specialization (subjects to teach)</label>{{ specpick('t_spec', t.specialization, 'Subjects to teach', quick_groups) }}</div>
<div><button type="submit">Save changes</button> <button type="button" class="plain" data-cancel="t{{ t.id }}">Cancel</button></div></div></form></td></tr>
{% else %}<tr><td colspan="6" class="empty">No teachers yet. Enter a number above to start.</td></tr>{% endfor %}</tbody></table></div></section>

<!-- ======================= ROOMS ======================= -->
<section class="qi-panel card" id="rooms" data-panel="rooms"><h3>Rooms <span class="qi-badge">{{ rooms|length }} registered</span></h3>
<p class="hint">Enter the total number of rooms in the whole school. Rooms are saved once and stay available for every scheduling run for the entire school year.</p>
<form method="post" id="f-rooms" data-noconfirm data-kind="rooms">{{ csrf_field() }}<input type="hidden" name="action" value="save_rooms">
<div class="qi-bar"><div><label for="r_count">Number of rooms</label><input type="number" id="r_count" min="0" max="{{ data.maxrows }}" value="0"></div>
<div><label for="r_dtype">Room type for new rows</label><select id="r_dtype">{% for t in data.rtypes %}<option>{{ t }}</option>{% endfor %}</select></div>
<div><button type="button" class="plain" data-apply="rooms">Apply to all rows</button></div></div>
<p class="hint">Room types are the kinds of rooms. Missing one? Add it in <a href="{{ url_for('auto_rooms') }}">Room Management</a> with Add room type.</p>
<div class="qi-grid" data-grid="rooms" style="--cols:1"></div>
<div class="qi-sum" data-sum="rooms"></div>
<div class="btnrow"><button type="button" class="plain" data-more="rooms">+ Add more</button> <button type="submit" data-save="rooms" data-busy="Saving..." {{ 'disabled' if approved }}>Save All</button></div></form>

<h4 style="margin-top:1.4rem">Registered rooms</h4>
<div class="scroll"><table data-tools="rooms" class="list qi-list"><thead><tr><th data-ts="text">Room</th><th data-ts="text" data-tf>Type</th><th data-ts="text" data-tf>Grade level</th><th data-ts="text" data-tf>Building</th><th data-ts="text" data-tf>Floor</th><th></th></tr></thead><tbody>
{% for r in rooms %}<tr><td><b>{{ r.name }}</b></td><td>{{ r.rtype }}</td><td>{{ {'11': 'Grade 11 only', '12': 'Grade 12 only'}.get(r.grade_access, 'Grades 11 and 12') }}</td><td>{{ r.building or '-' }}</td><td>{{ r.floor or '-' }}</td>
<td><div class="qi-acts"><button type="button" class="plain small" data-edit="r{{ r.id }}" {{ 'disabled' if approved }}>Edit</button>
<form method="post" data-noconfirm data-confirm="Delete {{ r.name }}? It is also removed from every class period that uses it.">{{ csrf_field() }}<input type="hidden" name="action" value="delete_room"><input type="hidden" name="rid" value="{{ r.id }}"><button class="danger small" type="submit" {{ 'disabled' if approved }}>Delete</button></form></div></td></tr>
<tr class="qi-edit" id="edit-r{{ r.id }}" hidden><td colspan="6"><form method="post" data-noconfirm>{{ csrf_field() }}<input type="hidden" name="action" value="edit_room"><input type="hidden" name="rid" value="{{ r.id }}"><div class="formgrid">
<div><label>Room name or number</label><input name="r_name" value="{{ r.name }}" maxlength="60" required></div>
<div><label>Room type</label><select name="r_type">{% for x in rtypes %}<option {{ 'selected' if x == r.rtype }}>{{ x }}</option>{% endfor %}</select></div>
<div><label>Grade level that can use it</label><select name="r_grade"><option value="Both" {{ 'selected' if (r.grade_access or 'Both') == 'Both' }}>Grades 11 and 12</option><option value="11" {{ 'selected' if r.grade_access == '11' }}>Grade 11 only</option><option value="12" {{ 'selected' if r.grade_access == '12' }}>Grade 12 only</option></select></div>
<div><button type="submit">Save changes</button> <button type="button" class="plain" data-cancel="r{{ r.id }}">Cancel</button></div></div></form></td></tr>
{% else %}<tr><td colspan="6" class="empty">No rooms yet. Enter a number above to start.</td></tr>{% endfor %}</tbody></table></div>
{% if missing_types %}<p class="hint">Subjects offered need these room types, which are not registered yet: {{ missing_types|join(', ') }}. Register a room of each of these types above so those subjects can be scheduled.</p>{% endif %}</section>

</div>

<div class="card" id="result"><h3>Generate the class programs</h3>
<p>When the sections, teachers and rooms are complete, open the Schedule Generator: validate everything, then generate all class programs and assign the teachers in one step.</p>
<a class="btn" href="{{ url_for('auto_generate') }}">Open the Schedule Generator</a>
</div>

<script type="application/json" id="qi-data">{{ data|tojson }}</script>
<script>(function(){
var D=JSON.parse(document.getElementById('qi-data').textContent),root=document.getElementById('qi-root');
root.classList.remove('qi-nojs');
var $=function(s,c){return(c||document).querySelector(s);},$$=function(s,c){return Array.prototype.slice.call((c||document).querySelectorAll(s));};
function el(tag,attrs,kids){var e=document.createElement(tag);for(var k in(attrs||{})){if(k==='text')e.textContent=attrs[k];else e.setAttribute(k,attrs[k]);}(kids||[]).forEach(function(c){e.appendChild(c);});return e;}
function nameKey(s){return s.replace(/[.,]/g,' ').toUpperCase().split(/\s+/).filter(Boolean).join(' ');}
function shortSec(s){return s.replace(/^\s*(?:grade\s*)?1[12]\s*[-\u2013]\s*|^\s*grade\s*1[12]\s+/i,'').trim();}

/* ---- tabs ---- */
function show(tab){if(!$('[data-panel="'+tab+'"]'))tab='sections';
 $$('.qi-panel').forEach(function(p){p.classList.toggle('on',p.dataset.panel===tab);});
 $$('.qi-tile').forEach(function(t){var on=t.dataset.tab===tab;t.classList.toggle('on',on);t.setAttribute('aria-selected',on);});}
$$('.qi-tile').forEach(function(t){t.addEventListener('click',function(){show(t.dataset.tab);history.replaceState(null,'','#'+t.dataset.tab);});});
show((location.hash||'').slice(1)||D.tab);

/* ---- edit / cancel rows ---- */
$$('[data-edit]').forEach(function(b){b.addEventListener('click',function(){var r=document.getElementById('edit-'+b.dataset.edit);r.hidden=!r.hidden;});});
$$('[data-cancel]').forEach(function(b){b.addEventListener('click',function(){document.getElementById('edit-'+b.dataset.cancel).hidden=true;});});

/* ---- the generated input fields ---- */
function setSpec(w,spec){var h=w.querySelector('input[type=hidden]');h.value=spec||'';var have=(spec||'').split(';').map(function(x){return x.trim();}).filter(Boolean);$$('.sp-list input[type=checkbox]',w).forEach(function(c){c.checked=have.indexOf(c.value)>-1;});var n=w.querySelector('.sp-count');if(n)n.textContent=have.length;var tx=w.querySelector('.sp-text');if(tx)tx.textContent=have.join(', ')||'-';}
function defaultSpec(){var h=document.querySelector('#t_dspec_box input[type=hidden]');return h?h.value:'';}
var dh=document.querySelector('#t_dspec_box input[type=hidden]');if(dh)dh.removeAttribute('name');   /* the default picker is never sent with the form */
var kinds={
 sections:{cols:3,fields:function(row,v){
  var gr=el('select',{name:'s_grade','aria-label':'Grade'});['11','12'].forEach(function(g){gr.appendChild(el('option',{text:g,value:g}));});gr.value=v.grade||$('#s_dgrade').value;
  var cl=el('select',{name:'s_cluster','aria-label':'Cluster'});cl.appendChild(el('option',{value:'',text:'Cluster: not set yet'}));
  Object.keys(D.clusters).forEach(function(tr){var og=el('optgroup',{label:tr});D.clusters[tr].forEach(function(c){og.appendChild(el('option',{text:c,value:c}));});cl.appendChild(og);});cl.value=(v.cluster===undefined?$('#s_dcluster').value:v.cluster)||'';
  return {name:el('input',{type:'text',name:'s_name',maxlength:60,'aria-label':'Section name'}),extra:[gr,cl],gr:gr};},
  key:function(r){var n=shortSec(r.querySelector('[name=s_name]').value);return n?(r.querySelector('[name=s_grade]').value+'-'+n).toLowerCase():'';},
  existing:D.existing.sections,label:'section'},
 teachers:{cols:3,fields:function(row,v){
  var ct=el('select',{name:'t_cat','aria-label':'Grade level handled'});Object.keys(D.cats).forEach(function(k){ct.appendChild(el('option',{value:k,text:D.cats[k]}));});ct.value=v.cat||$('#t_dcat').value||'G11';
  var tf=el('select',{'aria-label':'Show subjects for'});[['','All subjects'],['Academic','Academic subjects'],['TechPro','TechPro subjects']].forEach(function(o){tf.appendChild(el('option',{value:o[0],text:o[1]}));});
  var sp=document.getElementById('tpl-spec').content.cloneNode(true);var w=sp.querySelector('.specpick');
  setSpec(w,v.spec===undefined?defaultSpec():v.spec);
  tf.addEventListener('change',function(){$$('fieldset',w).forEach(function(fs){var lg=(fs.querySelector('legend')||{}).textContent||'',m=/^(Academic|TechPro)/.exec(lg);fs.hidden=!!(tf.value&&m&&m[1]!==tf.value);});});
  var box=el('div');box.appendChild(tf);box.appendChild(sp);
  return {name:el('input',{type:'text',name:'t_name',maxlength:120,'aria-label':'Teacher full name'}),extra:[ct,box]};},
  key:function(r){return nameKey(r.querySelector('[name=t_name]').value);},existing:D.existing.teachers,label:'teacher'},
 rooms:{cols:1,fields:function(row,v){
  var ty=el('select',{name:'r_type','aria-label':'Room type'});D.rtypes.forEach(function(t){ty.appendChild(el('option',{value:t,text:t}));});ty.value=v.type||$('#r_dtype').value||'Regular';
  return {name:el('input',{type:'text',name:'r_name',maxlength:60,'aria-label':'Room name'}),extra:[ty]};},
  key:function(r){return r.querySelector('[name=r_name]').value.trim().toLowerCase();},existing:D.existing.rooms,label:'room'}
};
var counts={sections:$('#s_count'),teachers:$('#t_count'),rooms:$('#r_count')};

function addRow(kind,v){var k=kinds[kind],grid=$('[data-grid="'+kind+'"]');if(grid.children.length>=D.maxrows)return;
 var row=el('div',{'class':'qi-row'+(kind==='teachers'?' t':'')}),f=k.fields(row,v||{});
 row.appendChild(el('span',{'class':'no',text:grid.children.length+1}));row.appendChild(f.name);f.extra.forEach(function(x){row.appendChild(x);});
 if(v&&v.name)f.name.value=v.name;
 var x=el('button',{type:'button','class':'x',title:'Remove this row','aria-label':'Remove this row',text:'\u00d7'});
 x.addEventListener('click',function(){row.remove();renumber(kind);});row.appendChild(x);
 row.appendChild(el('p',{'class':'msg',hidden:''}));
 grid.appendChild(row);validate(kind);}
function renumber(kind){$$('[data-grid="'+kind+'"] .qi-row').forEach(function(r,i){r.querySelector('.no').textContent=i+1;});counts[kind].value=$('[data-grid="'+kind+'"]').children.length;validate(kind);}
function resize(kind){var grid=$('[data-grid="'+kind+'"]'),want=Math.max(0,Math.min(D.maxrows,parseInt(counts[kind].value,10)||0));
 while(grid.children.length<want)addRow(kind);
 while(grid.children.length>want){var last=grid.lastElementChild;if(last.querySelector('[name$=_name]').value.trim()){counts[kind].value=grid.children.length;alert('The last row has a name in it. Remove that row with the \u00d7 button first.');break;}last.remove();}
 renumber(kind);}

function validate(kind){var k=kinds[kind],rows=$$('[data-grid="'+kind+'"] .qi-row'),seen={},filled=0,problems=0;
 rows.forEach(function(r){var key=k.key(r),msg=r.querySelector('.msg'),err='';r.classList.remove('bad');msg.hidden=true;
  var raw=r.querySelector('[name$=_name]').value.trim();
  if(raw){filled++;if(kind==='sections'&&!shortSec(raw))err='Enter a section name.';else if(seen[key])err='Duplicate: this '+k.label+' is typed more than once.';else if(k.existing.indexOf(key)>-1)err='Already registered: '+raw+'.';}
  if(key)seen[key]=1;
  if(err){problems++;r.classList.add('bad');msg.textContent=err;msg.hidden=false;}});
 var sum=$('[data-sum="'+kind+'"]'),btn=$('[data-save="'+kind+'"]');
 sum.className='qi-sum '+(problems?'bad':filled?'ok':'');
 sum.textContent=problems?problems+' problem(s) to fix before saving.':filled?filled+' '+k.label+(filled>1?'s':'')+' ready to save. Review the list, then press Save All.':'';
 var frm=document.getElementById('f-'+kind),blank=rows.length-filled;if(frm)frm.setAttribute('data-confirm','Save '+filled+' '+k.label+(filled>1?'s':'')+' to the database?'+(blank?' ('+blank+' empty row(s) will be skipped.)':''));
 if(btn&&!btn.hasAttribute('data-locked'))btn.disabled=!!problems||!filled;
 return {problems:problems,filled:filled};}

Object.keys(kinds).forEach(function(kind){
 var grid=$('[data-grid="'+kind+'"]'),form=document.getElementById('f-'+kind),btn=$('[data-save="'+kind+'"]');
 if(btn&&btn.disabled&&!btn.closest('form').querySelector('.qi-row'))btn.setAttribute('data-locked',btn.disabled?'1':'');
 counts[kind].addEventListener('input',function(){resize(kind);});
 $('[data-more="'+kind+'"]').addEventListener('click',function(){addRow(kind);counts[kind].value=grid.children.length;});
 grid.addEventListener('input',function(){validate(kind);});grid.addEventListener('change',function(){validate(kind);});
 form.addEventListener('submit',function(e){var r=validate(kind);if(r.problems||!r.filled)e.preventDefault();});
 var dr=(D.draft||{})[kind];
 if(dr){var names=dr.names||[];names.forEach(function(n,i){var v={name:n};if(kind==='sections'){v.grade=(dr.grades||[])[i];v.cluster=(dr.clusters||[])[i];}if(kind==='teachers'){v.cat=(dr.cats||[])[i];v.spec=(dr.specs||[])[i];}if(kind==='rooms'){v.type=(dr.types||[])[i];}addRow(kind,v);});counts[kind].value=grid.children.length;}
 validate(kind);
});
var apT=$('[data-apply="teachers"]');if(apT)apT.addEventListener('click',function(){var cat=$('#t_dcat').value,sp=defaultSpec();$$('[data-grid="teachers"] .qi-row').forEach(function(r){var c=r.querySelector('[name=t_cat]');if(c)c.value=cat;if(sp){var w=r.querySelector('.specpick');if(w)setSpec(w,sp);}});validate('teachers');});
var apR=$('[data-apply="rooms"]');if(apR)apR.addEventListener('click',function(){var ty=$('#r_dtype').value;$$('[data-grid="rooms"] .qi-row').forEach(function(r){var c=r.querySelector('[name=r_type]');if(c)c.value=ty;});validate('rooms');});
var ap=$('[data-apply="sections"]');if(ap)ap.addEventListener('click',function(){$$('[data-grid="sections"] .qi-row').forEach(function(r){r.querySelector('[name=s_grade]').value=$('#s_dgrade').value;r.querySelector('[name=s_cluster]').value=$('#s_dcluster').value;});validate('sections');});

/* ---- subject picker (same behaviour as the rest of the system; also covers rows added by JavaScript) ---- */
document.addEventListener('change',function(e){var c=e.target;if(!c||c.type!=='checkbox')return;var w=c.closest?c.closest('.specpick'):null;if(!w)return;
 var h=w.querySelector('input[type=hidden]'),v=[];$$('.sp-list input[type=checkbox]',w).forEach(function(x){if(x.checked)v.push(x.value);});
 h.value=v.join('; ');var n=w.querySelector('.sp-count');if(n)n.textContent=v.length;var t=w.querySelector('.sp-text');if(t)t.textContent=v.length?v.join(', '):'-';});
})();</script>{% endblock %}""",

}
TEMPLATES.update(NEW2_TEMPLATES)

app.jinja_loader = DictLoader(TEMPLATES)

_init_lock = acquire_init_lock()  # tables are created when the program starts
init_db()
init_auto_db()
migrate_curriculum()
seed_room_types()


def backfill_official_times():
    """One time: teachers with no official time get the shift of their grade level (AM, PM or MID)."""
    conn = raw_connect()
    try:
        if conn.execute("SELECT 1 FROM settings WHERE k='auto_official_v1'").fetchone():
            return
        row = conn.execute("SELECT v FROM settings WHERE k='tt_text'").fetchone()
        tt = parse_tt((row["v"] if row else "") or DEFAULT_TT) or parse_tt(DEFAULT_TT)
        for r in conn.execute("SELECT id, category FROM users WHERE role='teacher' "
                              "AND COALESCE(official_time,'')=''").fetchall():
            hours = auto_official(r["category"], tt)
            if hours:
                conn.execute("UPDATE users SET official_time=? WHERE id=?", (hours, r["id"]))
        conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('auto_official_v1','1')")
        conn.commit()
    finally:
        conn.close()


backfill_official_times()


def auto_build(tries=30):
    """One click for the administrator: register the rooms the sections need, match teacher
    qualifications, give every subject a qualified teacher, and place all of it in the class programs
    without any clash of teacher, section or room."""
    for sec in sched_secs():
        register_room(sec["room"])
    ensure_room_types()
    match_quals()
    added, given, left = autofill()
    ids = [x["id"] for x in sched_secs()]
    best = None
    for rnd in range(6):
        d = solve(ids, tries=tries, seed=rnd)
        if best is None or len(d["unplaced"]) < len(best["unplaced"]):
            best = d
        if not best["unplaced"]:
            break
        autofill(overwrite=True, jitter=60 * (rnd + 1))  # try a different teacher spread if something did not fit
    if best:
        apply_draft(best)
        clear_stale(ids)
    chk = check_program()
    return dict(sections=len(ids), placed=len(best["sessions"]) if best else 0,
                unplaced=len(best["unplaced"]) if best else 0, left=left, issues=len(chk["issues"]))


TEST_SECTIONS = [  # name, track, cluster
    ("Theology", "Academic", "ASSH"), ("Governance", "Academic", "ASSH"), ("Literature", "Academic", "ASSH"),
    ("Dalton", "Academic", "STEM"), ("Bookkeeping", "Academic", "BE"), ("Demography", "Academic", "ASSH"),
    ("Pascal", "Academic", "STEM"), ("Administration", "Academic", "BE"), ("Corporation", "Academic", "BE"),
    ("History", "Academic", "ASSH"), ("Einstein", "Academic", "STEM"), ("Archeology", "Academic", "ASSH"),
    ("Newton", "Academic", "STEM"), ("Piston", "TechPro", "ASET"), ("Cook", "TechPro", "HT"),
    ("Pastry", "TechPro", "AFBFI"), ("Apple", "TechPro", "ICT"), ("Edison", "TechPro", "IND"),
    ("Android", "TechPro", "ICT"), ("Wallace", "Academic", "STEM"), ("Galilei", "Academic", "STEM"),
    ("Valve", "TechPro", "ASET"),
]
TEST_FIRST = ["Maria", "Jose", "Ana", "Juan", "Carlo", "Liza", "Mark", "Grace", "Paolo", "Joy", "Rico", "Nina", "Ramon",
              "Jessa", "Allan", "Marites", "Noel", "Cherry", "Dennis", "Lorna", "Arnel", "Divina", "Efren", "Gina",
              "Harold", "Imelda", "Jun", "Karen", "Leo", "Mylene", "Nestor", "Olivia", "Pedro", "Queenie", "Rolando",
              "Sheila", "Tomas", "Ursula", "Vicente", "Wilma"]
TEST_LAST = ["Santos", "Reyes", "Cruz", "Bautista", "Ocampo", "Garcia", "Mendoza", "Torres", "Flores", "Villanueva",
             "Ramos", "Aquino", "Castillo", "Navarro", "Domingo", "Soriano", "Fernandez", "Lim", "Aguilar", "Manalo",
             "Pascual", "Estrada", "Salazar", "Dizon", "Mercado", "Rivera", "Valdez", "Tolentino", "Gonzales", "Enriquez"]


def seed_test_data_once():
    """One time: 22 test sections (Academic and TechPro) and 60 test teachers with random subjects, then
    let the system assign the teachers and build every class program."""
    try:
        with app.app_context(), app.test_request_context():
            if query("SELECT 1 FROM settings WHERE k='testdata_v1'", one=True):
                return
            rnd = random.Random(2026)
            cl_name = {c[0]: c[1] for c in ACADEMIC_CLUSTERS + TECHPRO_CLUSTERS}
            # 60 teachers: two random core subjects each; elective clusters are shared out so that every
            # cluster has more qualified teachers than it has sections
            pairs = [(a, b) for i, a in enumerate(CORE_NAMES) for b in CORE_NAMES[i + 1:]] * 4
            rnd.shuffle(pairs)
            quota = (["ASSH"] * 8 + ["STEM"] * 8 + ["BE"] * 5 + ["ASET"] * 4 + ["ICT"] * 4 + ["HT"] * 3 + ["AFBFI"] * 3
                     + ["IND"] * 3)
            quota += [rnd.choice(list(cl_name)) for _ in range(12)]
            rnd.shuffle(quota)
            quota += [None] * (60 - len(quota))
            pw = generate_password_hash("teacher123")
            made, names = [], set()
            for n in range(60):
                while True:
                    full = f"{rnd.choice(TEST_FIRST)} {rnd.choice(TEST_LAST)}"
                    if full not in names:
                        names.add(full)
                        break
                parts = full.split()
                user = (parts[0] + "." + parts[-1]).lower()
                if query("SELECT 1 FROM users WHERE lower(username)=?", (user,), one=True):
                    continue
                spec = list(pairs[n]) + ([cl_name[quota[n]]] if quota[n] else [])
                codes = [c for c, nm in CORE_SUBJECTS if nm in spec] + ([quota[n]] if quota[n] else [])
                run("""INSERT INTO users(teacher_id,username,full_name,role,category,password_hash,item,
                                         specialization,subject_area,official_time,intervention_min,ancillary_min)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (f"T-{2001 + n}", user, full, "teacher", "G11", pw, ["Teacher I", "Teacher II", "Teacher III"][n % 3],
                     SPEC_SEP.join(spec), " / ".join(codes), "6:00 AM - 3:00 PM", 60, 0))
                made.append(query("SELECT id FROM users WHERE username=?", (user,), one=True)["id"])
            rnd.shuffle(made)
            rooms = [f"Room {n}" for n in list(range(201, 213)) + list(range(301, 313)) + list(range(401, 413))]
            for i, (nm, track, code) in enumerate(TEST_SECTIONS):
                name = f"11-{nm}"
                if query("SELECT 1 FROM sections WHERE name=?", (name,), one=True):
                    continue
                room = rooms[i]
                b, fl = room_place(room)
                conn = db()
                cur = conn.execute("INSERT INTO sections(name,grade,track,room,building,floor,adviser_id,cluster) "
                                   "VALUES(?,?,?,?,?,?,?,?)", (name, 11, track, room, b, fl, made[i] if i < len(made) else None,
                                                               cl_name[code]))
                conn.commit()
                sync_section_subjects(cur.lastrowid)
            run("INSERT OR REPLACE INTO settings(k,v) VALUES('testdata_v1','1')")
            auto_build()
    except Exception as exc:  # never stop the site from starting
        print("Test data was not loaded:", exc)


def clear_all_data_once():
    """One time only: remove every teacher, section, class program, room and request so the school can
    start from an empty system. Administrator accounts, the curriculum and the school setup are kept."""
    try:
        with app.app_context():
            if query("SELECT 1 FROM settings WHERE k='cleared_v2'", one=True):
                return
            conn = db()
            conn.execute("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE role='teacher')")
            for t in ("classes", "section_subjects", "loads", "teacher_subjects", "sections", "rooms",
                      "signup_requests", "reset_requests"):
                conn.execute(f"DELETE FROM {t}")
            conn.execute("DELETE FROM users WHERE role='teacher'")
            conn.execute("DELETE FROM settings WHERE k LIKE 'upd_%' OR k LIKE 'tmins_%' OR k IN "
                         "('gen_draft','stale_sections','approved_at','approved_by','approved_periods','example_loaded')")
            conn.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('cleared_v2','1')")
            conn.commit()
    except Exception as exc:  # never stop the site from starting
        print("Data was not cleared:", exc)


clear_all_data_once()


def clear_test_data_once():
    """Optional, for a fresh start on deploy: set CLEAR_TEST_DATA=1 and the test data is cleared one time (the
    same as Settings > Reset test data). Remove the variable afterwards."""
    if os.environ.get("CLEAR_TEST_DATA") != "1":
        return
    try:
        with app.app_context():
            if query("SELECT 1 FROM settings WHERE k='cleared_v3'", one=True):
                return
            clear_test_data(with_rooms=True)
            run("INSERT OR REPLACE INTO settings(k,v) VALUES('cleared_v3','1')")
    except Exception as exc:
        print("Test data was not cleared:", exc)


clear_test_data_once()
if os.environ.get("SEED_TEST_DATA") == "1":   # demo teachers/sections only when explicitly requested
    seed_test_data_once()


with app.app_context():  # a section that has no class program yet gets the fixed starting program
    for _s in sched_secs():
        build_default_program(_s["id"])
    _c = db()
    for _tbl, _col in (("sections", "room"), ("rooms", "name")):
        for _i, _nm, _b, _f in _c.execute(f"SELECT id, {_col}, building, floor FROM {_tbl}").fetchall():
            _nb, _nf = room_place(_nm)
            if _nb and (_nb != _b or _nf != _f):
                _c.execute(f"UPDATE {_tbl} SET building=?, floor=? WHERE id=?", (_nb, _nf, _i))
    _c.commit()


release_init_lock(_init_lock)

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", 5000)), debug=False)
