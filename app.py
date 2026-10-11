
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import sqlite3
from datetime import datetime, date, timedelta

app = Flask(__name__)
app.secret_key = "change-this-before-deployment"
DATABASE = "medimate.db"


# ---------------- DATABASE ----------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                dose TEXT NOT NULL,
                times TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS dose_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                medicine_id INTEGER NOT NULL,
                scheduled_date TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                status TEXT DEFAULT 'Pending',
                UNIQUE(medicine_id, scheduled_date, scheduled_time)
            )
        """)


# ---------------- VALIDATION ----------------

def valid_times(times):
    if not times:
        return False

    parsed = []

    try:
        for value in times.split(","):
            value = value.strip()
            datetime.strptime(value, "%H:%M")

            if value in parsed:
                return False

            parsed.append(value)

    except ValueError:
        return False

    return bool(parsed)


# ---------------- DOSE SCHEDULE ----------------

def get_schedule(target_date=None):
    now = datetime.now()
    target_date = target_date or date.today().isoformat()

    with get_db() as conn:
        medicines = conn.execute(
            "SELECT * FROM medicines ORDER BY name"
        ).fetchall()

        for med in medicines:
            for time in med["times"].split(","):
                time = time.strip()

                if not time:
                    continue

                conn.execute("""
                    INSERT OR IGNORE INTO dose_records
                    (medicine_id, scheduled_date, scheduled_time)
                    VALUES (?, ?, ?)
                """, (med["id"], target_date, time))

        rows = conn.execute("""
            SELECT d.*, m.name, m.dose
            FROM dose_records d
            JOIN medicines m ON m.id = d.medicine_id
            WHERE d.scheduled_date = ?
            ORDER BY d.scheduled_time
        """, (target_date,)).fetchall()

    schedule = []

    for row in rows:
        item = dict(row)
        item["display_status"] = item["status"]

        try:
            scheduled = datetime.strptime(
                item["scheduled_date"] + " " + item["scheduled_time"],
                "%Y-%m-%d %H:%M"
            )

            if (
                target_date == date.today().isoformat()
                and item["status"] == "Pending"
                and now > scheduled + timedelta(minutes=30)
            ):
                item["display_status"] = "Overdue"

        except ValueError:
            pass

        schedule.append(item)

    return schedule


def get_stats(schedule):
    total = len(schedule)
    taken = sum(
        item["status"] == "Taken" for item in schedule
    )
    missed = sum(
        item["status"] == "Missed" for item in schedule
    )
    overdue = sum(
        item["display_status"] == "Overdue" for item in schedule
    )
    pending = sum(
        item["status"] == "Pending"
        and item["display_status"] != "Overdue"
        for item in schedule
    )

    return {
        "total": total,
        "taken": taken,
        "missed": missed,
        "overdue": overdue,
        "pending": pending,
        "adherence": round(taken / total * 100) if total else 0
    }


# ---------------- HOME ----------------

@app.route("/")
def index():
    schedule = get_schedule()

    with get_db() as conn:
        medicines = conn.execute(
            "SELECT * FROM medicines ORDER BY name"
        ).fetchall()

    return render_template(
        "index.html",
        schedule=schedule,
        medicines=medicines,
        stats=get_stats(schedule)
    )


# ---------------- ADD MEDICINE ----------------

@app.route("/add", methods=["POST"])
def add_medicine():
    name = request.form.get("name", "").strip()
    dose = request.form.get("dose", "").strip()
    times = request.form.get("times", "").strip()

    if not name or not dose or not valid_times(times):
        flash("Enter a medicine name, dose and valid unique times (HH:MM).")
        return redirect(url_for("index"))

    times = ",".join(
        sorted(
            [t.strip() for t in times.split(",")],
            key=lambda t: datetime.strptime(t, "%H:%M")
        )
    )

    with get_db() as conn:
        duplicate = conn.execute("""
            SELECT id FROM medicines
            WHERE LOWER(name) = LOWER(?)
              AND LOWER(dose) = LOWER(?)
              AND times = ?
        """, (name, dose, times)).fetchone()

        if duplicate:
            flash("This exact medicine schedule already exists.")
            return redirect(url_for("index"))

        conn.execute("""
            INSERT INTO medicines (name, dose, times)
            VALUES (?, ?, ?)
        """, (name, dose, times))

    flash("Medicine added successfully.")
    return redirect(url_for("index"))


# ---------------- EDIT MEDICINE ----------------

@app.route("/edit/<int:medicine_id>", methods=["GET", "POST"])
def edit_medicine(medicine_id):
    with get_db() as conn:
        medicine = conn.execute(
            "SELECT * FROM medicines WHERE id = ?",
            (medicine_id,)
        ).fetchone()

        if medicine is None:
            return "Medicine not found.", 404

        if request.method == "GET":
            return render_template("edit_medicine.html", medicine=medicine)

        name = request.form.get("name", "").strip()
        dose = request.form.get("dose", "").strip()
        times = request.form.get("times", "").strip()

        if not name or not dose or not valid_times(times):
            flash("Enter valid medicine details and times.")
            return redirect(url_for("edit_medicine", medicine_id=medicine_id))

        times = ",".join(
            sorted(
                [t.strip() for t in times.split(",")],
                key=lambda t: datetime.strptime(t, "%H:%M")
            )
        )

        duplicate = conn.execute("""
            SELECT id FROM medicines
            WHERE LOWER(name) = LOWER(?)
              AND LOWER(dose) = LOWER(?)
              AND times = ?
              AND id != ?
        """, (name, dose, times, medicine_id)).fetchone()

        if duplicate:
            flash("Another medicine already has these details.")
            return redirect(url_for("edit_medicine", medicine_id=medicine_id))

        old_times = set(medicine["times"].split(","))
        new_times = set(times.split(","))

        conn.execute("""
            UPDATE medicines
            SET name = ?, dose = ?, times = ?
            WHERE id = ?
        """, (name, dose, times, medicine_id))

        # Remove obsolete future records when scheduled times change.
        removed_times = old_times - new_times

        for time in removed_times:
            conn.execute("""
                DELETE FROM dose_records
                WHERE medicine_id = ?
                  AND scheduled_time = ?
                  AND scheduled_date >= ?
                  AND status = 'Pending'
            """, (medicine_id, time, date.today().isoformat()))

    flash("Medicine updated successfully.")
    return redirect(url_for("index"))


# ---------------- DELETE MEDICINE ----------------

@app.route("/delete/<int:medicine_id>", methods=["POST"])
def delete_medicine(medicine_id):
    with get_db() as conn:
        conn.execute(
            "DELETE FROM dose_records WHERE medicine_id = ?",
            (medicine_id,)
        )
        result = conn.execute(
            "DELETE FROM medicines WHERE id = ?",
            (medicine_id,)
        )

        if result.rowcount == 0:
            return "Medicine not found.", 404

    flash("Medicine and its dose records were deleted.")
    return redirect(url_for("index"))


# ---------------- UPDATE DOSE STATUS ----------------

def update_dose_status(dose_id, new_status):
    with get_db() as conn:
        result = conn.execute("""
            UPDATE dose_records
            SET status = ?
            WHERE id = ? AND scheduled_date = ?
              AND status = 'Pending'
        """, (new_status, dose_id, date.today().isoformat()))

    return result.rowcount


@app.route("/taken/<int:dose_id>", methods=["POST"])
def mark_taken(dose_id):
    update_dose_status(dose_id, "Taken")
    return redirect(url_for("index"))


@app.route("/missed/<int:dose_id>", methods=["POST"])
def mark_missed(dose_id):
    update_dose_status(dose_id, "Missed")
    return redirect(url_for("index"))


# ---------------- DOSE HISTORY ----------------

@app.route("/history")
def history():
    with get_db() as conn:
        records = conn.execute("""
            SELECT d.*, m.name, m.dose
            FROM dose_records d
            JOIN medicines m ON m.id = d.medicine_id
            ORDER BY d.scheduled_date DESC, d.scheduled_time DESC
        """).fetchall()

    # JSON history endpoint; does not require a new HTML template.
    return jsonify([dict(row) for row in records])


# ---------------- CAREGIVER ----------------

@app.route("/caregiver")
def caregiver():
    schedule = get_schedule()

    return render_template(
        "caregiver.html",
        schedule=schedule,
        stats=get_stats(schedule)
    )


# ---------------- MEDIMATE ASSISTANT ----------------

@app.route("/assistant", methods=["POST"])
def assistant():
    data = request.get_json(silent=True) or {}
    question = data.get("question", "")

    if not isinstance(question, str):
        return jsonify({"answer": "Please enter a text question."}), 400

    question = question.strip().lower()

    if not question:
        return jsonify({"answer": "Please enter a question."}), 400

    if "miss" in question and "dose" in question or any(
        phrase in question for phrase in [
            "forgot dose", "forgot my medicine", "forgot to take",
            "missed my medicine", "missed my medication"
        ]
    ):
        answer = (
            "If you may have missed a dose, check the patient leaflet "
            "or contact your doctor or pharmacist for advice specific "
            "to your medicine. Do not take an extra dose unless the "
            "official instructions or a qualified healthcare professional "
            "tell you to."
        )

    elif "side effect" in question or "adverse effect" in question:
        answer = (
            "Side effects depend on the medicine and the person taking it. "
            "Check the official patient leaflet and ask your doctor or "
            "pharmacist about symptoms that concern you. Seek urgent help "
            "for severe or rapidly worsening symptoms."
        )

    elif any(phrase in question for phrase in [
        "what is", "used for", "purpose of", "meaning of"
    ]):
        answer = (
            "For reliable information about what a medicine is used for, "
            "check its official patient leaflet or ask your pharmacist "
            "or doctor. I should not guess medicine information."
        )

    else:
        answer = (
            "I don't have enough verified information to answer safely. "
            "Please consult your doctor or pharmacist for advice specific "
            "to your medicine. Do not change your prescribed treatment "
            "based on this demo assistant."
        )

    return jsonify({"answer": answer})


# ---------------- START APPLICATION ----------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
