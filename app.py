from flask import Flask, render_template, request, redirect, session, flash, g
from datetime import datetime, timedelta
import sqlite3
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

DATABASE = os.path.join(os.path.dirname(__file__), 'sports.db')

app = Flask(__name__)
app.secret_key = "secretkey"


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row   # rows accessible by index OR column name
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Create all tables if they don't exist and seed a default admin."""
    db = sqlite3.connect(DATABASE)
    cur = db.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT    NOT NULL,
            email    TEXT    UNIQUE NOT NULL,
            password TEXT    NOT NULL,
            role     TEXT    DEFAULT 'student',
            department TEXT,
            year     TEXT,
            contact  TEXT
        );

        CREATE TABLE IF NOT EXISTS equipment (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            total_qty     INTEGER NOT NULL,
            available_qty INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            equipment_id    INTEGER NOT NULL,
            issue_time      TEXT    NOT NULL,
            expected_return TEXT,
            return_time     TEXT,
            status          TEXT    DEFAULT 'issued',
            fine            INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS reservations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER NOT NULL,
            equipment_id     INTEGER NOT NULL,
            reservation_time TEXT    NOT NULL,
            expected_return  TEXT,
            created_at       TEXT    DEFAULT (datetime('now', 'localtime')),
            status           TEXT    DEFAULT 'reserved'
        );
    """)
    # Seed a default admin account (admin@sports.com / admin123) if none exists
    cur.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO users(name, email, password, role, department, year, contact)
            VALUES(?, ?, ?, 'admin', 'Admin', '0', '0000000000')
        """, ('Admin', 'admin@sports.com', 'admin123'))
    db.commit()
    # Migration: add expected_return to reservations if it doesn't exist yet
    try:
        cur.execute("ALTER TABLE reservations ADD COLUMN expected_return TEXT")
        db.commit()
    except Exception:
        pass  # column already exists
    db.close()


# Initialise database once at startup
init_db()


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email']
        password = request.form['password']

        cur = get_db().cursor()
        cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
        user = cur.fetchone()

        if user:
            session['user_id'] = user[0]
            session['role']    = user[4]

            if user[4] == 'admin':
                return redirect('/admin_dashboard')
            else:
                return redirect('/student_dashboard')
        else:
            return "Invalid login"

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form

        db  = get_db()
        cur = db.cursor()
        cur.execute("SELECT * FROM users WHERE email=?", (data['email'],))
        user = cur.fetchone()

        if user:
            return "Email already registered. <a href='/register'>Try again</a>"

        if data['password'] != data['confirm_password']:
            return "Passwords do not match. <a href='/register'>Try again</a>"

        try:
            cur.execute("""
                INSERT INTO users(name, email, password, role, department, year, contact)
                VALUES(?, ?, ?, 'student', ?, ?, ?)
            """, (
                data['name'],
                data['email'],
                data['password'],
                data['department'],
                data['year'],
                data['contact'],
            ))
            db.commit()
            return redirect('/login')
        except Exception as e:
            return f"Registration failed: {str(e)} <a href='/register'>Try again</a>"

    return render_template('register.html')


# ---------------------------------------------------------------------------
# Student dashboard
# ---------------------------------------------------------------------------

@app.route('/student_dashboard')
def student_dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    cur = get_db().cursor()

    # Available equipment
    cur.execute("SELECT * FROM equipment")
    equipment = cur.fetchall()

    # Borrowed items with elapsed / remaining hours (SQLite julianday arithmetic)
    cur.execute("""
        SELECT t.id, e.name, t.issue_time, t.expected_return, t.status,
               CAST((julianday('now','localtime') - julianday(t.issue_time)) * 24 AS INTEGER) AS hours_elapsed,
               ROUND((julianday(t.expected_return) - julianday('now','localtime')) * 24, 1)   AS hours_remaining
        FROM transactions t
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.user_id = ? AND t.status = 'issued'
        ORDER BY t.issue_time DESC
    """, (user_id,))
    borrowed_items = cur.fetchall()

    # Fines / late returns
    cur.execute("""
        SELECT t.id, e.name, t.return_time, t.fine, t.expected_return, t.issue_time
        FROM transactions t
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.user_id = ? AND (t.status = 'late' OR t.fine > 0)
        ORDER BY t.return_time DESC
    """, (user_id,))
    user_fines = cur.fetchall()
    total_fine = sum(row[3] if row[3] else 0 for row in user_fines)

    # Upcoming reservations
    cur.execute("""
        SELECT r.id, e.name, r.reservation_time, r.status
        FROM reservations r
        JOIN equipment e ON r.equipment_id = e.id
        WHERE r.user_id = ? AND r.status = 'reserved'
        ORDER BY r.reservation_time ASC
    """, (user_id,))
    upcoming_reservations = cur.fetchall()

    min_datetime = datetime.now().strftime('%Y-%m-%dT%H:%M')

    return render_template('student_dashboard.html',
                           equipment=equipment,
                           borrowed_items=borrowed_items,
                           user_fines=user_fines,
                           total_fine=total_fine,
                           upcoming_reservations=upcoming_reservations,
                           min_datetime=min_datetime)


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')

    cur = get_db().cursor()

    cur.execute("SELECT * FROM equipment")
    equipment = cur.fetchall()

    cur.execute("""
        SELECT t.id, u.name AS user_name, e.name AS equipment_name,
               t.issue_time, t.return_time, t.status, t.fine, u.email,
               CAST((julianday('now','localtime') - julianday(t.issue_time)) * 24 AS INTEGER) AS hours_elapsed
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN equipment e ON t.equipment_id = e.id
        ORDER BY t.issue_time DESC
    """)
    logs = cur.fetchall()

    # Overdue > 24 h
    cur.execute("""
        SELECT t.id, u.name AS user_name, u.email, e.name AS equipment_name,
               t.issue_time,
               ROUND((julianday('now','localtime') - julianday(t.issue_time)) * 24, 1)        AS hours_elapsed,
               CAST(julianday('now','localtime') - julianday(t.issue_time) AS INTEGER)         AS days_elapsed,
               ROUND((julianday(t.expected_return) - julianday('now','localtime')) * 24, 1)   AS hours_remaining,
               t.fine
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.status = 'issued'
          AND (julianday('now','localtime') - julianday(t.issue_time)) * 24 > 24
        ORDER BY t.issue_time DESC
    """)
    overdue_items = cur.fetchall()

    # Late returns with fines
    cur.execute("""
        SELECT t.id, u.name AS user_name, u.email, e.name AS equipment_name,
               t.issue_time, t.return_time, t.fine,
               CAST(julianday(t.return_time) - julianday(t.issue_time) AS INTEGER) AS days_borrowed
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.status = 'late'
        ORDER BY t.return_time DESC
    """)
    late_returns = cur.fetchall()

    # Users with items > 7 days overdue
    cur.execute("""
        SELECT DISTINCT u.id, u.name, u.email
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE t.status = 'issued'
          AND (julianday('now','localtime') - julianday(t.issue_time)) > 7
    """)
    users_with_severe_overdue = cur.fetchall()

    return render_template('admin_dashboard.html',
                           equipment=equipment,
                           logs=logs,
                           overdue_items=overdue_items,
                           late_returns=late_returns,
                           users_with_severe_overdue=users_with_severe_overdue)


# ---------------------------------------------------------------------------
# Equipment management
# ---------------------------------------------------------------------------

@app.route('/add_equipment', methods=['POST'])
def add_equipment():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')

    name = request.form['name']
    qty  = request.form['qty']

    try:
        db  = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO equipment(name, total_qty, available_qty)
            VALUES(?, ?, ?)
        """, (name, qty, qty))
        db.commit()
        return redirect('/admin_dashboard')
    except Exception as e:
        return f"Error adding equipment: {str(e)} <a href='/admin_dashboard'>Back</a>"


# ---------------------------------------------------------------------------
# Borrow / Reserve / Return
# ---------------------------------------------------------------------------

@app.route('/issue/<int:id>', methods=['POST'])
def issue(id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id         = session['user_id']
    expected_return = datetime.now() + timedelta(hours=24)
    expected_return_str = expected_return.strftime('%Y-%m-%d %H:%M:%S')
    now_str         = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db  = get_db()
    cur = db.cursor()

    try:
        cur.execute("SELECT name, available_qty FROM equipment WHERE id=?", (id,))
        equipment = cur.fetchone()

        if not equipment:
            flash('Equipment not found')
            return redirect('/student_dashboard')

        if equipment[1] <= 0:
            flash(f'{equipment[0]} is not available for borrowing')
            return redirect('/student_dashboard')

        cur.execute("""
            SELECT id FROM transactions
            WHERE user_id=? AND equipment_id=? AND status='issued'
        """, (user_id, id))
        if cur.fetchone():
            flash(f'You already have {equipment[0]} borrowed')
            return redirect('/student_dashboard')

        cur.execute("UPDATE equipment SET available_qty = available_qty - 1 WHERE id=?", (id,))
        cur.execute("""
            INSERT INTO transactions(user_id, equipment_id, issue_time, expected_return, status, fine)
            VALUES(?, ?, ?, ?, 'issued', 0)
        """, (user_id, id, now_str, expected_return_str))
        db.commit()
        issue_time_display = datetime.now().strftime("%d %b %Y %H:%M")
        flash(f'✅ {equipment[0]} borrowed! Issued: {issue_time_display} — Return by: {expected_return.strftime("%d %b %Y %H:%M")} (24 h limit)')
        return redirect('/student_dashboard')

    except Exception as e:
        db.rollback()
        flash(f'Error borrowing equipment: {str(e)}')
        return redirect('/student_dashboard')


@app.route('/reserve/<int:id>', methods=['POST'])
def reserve(id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id          = session['user_id']
    reservation_time = request.form.get('reservation_time')

    if not reservation_time:
        flash('Please choose a future date and time to reserve.')
        return redirect('/student_dashboard')

    try:
        reservation_datetime = datetime.fromisoformat(reservation_time)
    except ValueError:
        flash('Invalid reservation date/time format.')
        return redirect('/student_dashboard')

    if reservation_datetime <= datetime.now():
        flash('Reservation must be for a future date and time.')
        return redirect('/student_dashboard')

    db  = get_db()
    cur = db.cursor()
    try:
        cur.execute("""
            SELECT id FROM reservations
            WHERE user_id=? AND equipment_id=? AND status='reserved'
        """, (user_id, id))
        if cur.fetchone():
            flash('You already have a reservation for this equipment. Cancel it first if you want to book a different slot.')
            return redirect('/student_dashboard')

        cur.execute("""
            SELECT COUNT(*) FROM reservations
            WHERE equipment_id=? AND reservation_time=? AND status='reserved'
        """, (id, reservation_datetime.strftime('%Y-%m-%d %H:%M:%S')))
        reserved_count = cur.fetchone()[0]

        cur.execute("SELECT total_qty FROM equipment WHERE id=?", (id,))
        equipment = cur.fetchone()

        if not equipment:
            flash('Equipment not found.')
            return redirect('/student_dashboard')

        if reserved_count >= equipment[0]:
            flash('This equipment is already fully reserved for the selected time.')
            return redirect('/student_dashboard')

        expected_return_dt  = reservation_datetime + timedelta(hours=24)
        expected_return_str = expected_return_dt.strftime('%Y-%m-%d %H:%M:%S')
        cur.execute("""
            INSERT INTO reservations(user_id, equipment_id, reservation_time, expected_return, status)
            VALUES(?, ?, ?, ?, 'reserved')
        """, (user_id, id, reservation_datetime.strftime('%Y-%m-%d %H:%M:%S'), expected_return_str))
        db.commit()
        flash(f'Reservation confirmed! Pick up on {reservation_datetime.strftime("%d %b %H:%M")} — return by {expected_return_dt.strftime("%d %b %H:%M")}.')
    except Exception as e:
        db.rollback()
        flash(f'Error creating reservation: {str(e)}')

    return redirect('/student_dashboard')


@app.route('/cancel_reservation/<int:id>', methods=['POST'])
def cancel_reservation(id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    db  = get_db()
    cur = db.cursor()

    try:
        cur.execute("""
            SELECT id FROM reservations
            WHERE id=? AND user_id=? AND status='reserved'
        """, (id, user_id))
        if not cur.fetchone():
            flash('Reservation not found or already cancelled.')
            return redirect('/student_dashboard')

        cur.execute("UPDATE reservations SET status='cancelled' WHERE id=?", (id,))
        db.commit()
        flash('Reservation cancelled successfully.')
    except Exception as e:
        db.rollback()
        flash(f'Error cancelling reservation: {str(e)}')

    return redirect('/student_dashboard')


@app.route('/return/<int:id>')
def return_item(id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    db  = get_db()
    cur = db.cursor()

    try:
        cur.execute("""
            SELECT expected_return, equipment_id, status, issue_time
            FROM transactions
            WHERE id=? AND user_id=?
        """, (id, user_id))
        transaction = cur.fetchone()

        if not transaction:
            flash('Transaction not found or access denied')
            return redirect('/student_dashboard')

        if transaction[2] != 'issued':
            flash('This item has already been returned')
            return redirect('/student_dashboard')

        issue_time = datetime.fromisoformat(transaction[3])
        now        = datetime.now()
        fine       = 0
        status     = 'returned'

        hours_elapsed = (now - issue_time).total_seconds() / 3600
        if hours_elapsed > 24:
            overtime_hours = hours_elapsed - 24
            fine   = int(overtime_hours * 10)
            status = 'late'
            flash(f'Late return! {overtime_hours:.1f} hours overtime. Fine: ₹{fine}')

        cur.execute("""
            UPDATE transactions
            SET return_time=?, status=?, fine=?
            WHERE id=?
        """, (now.strftime('%Y-%m-%d %H:%M:%S'), status, fine, id))

        cur.execute("""
            UPDATE equipment
            SET available_qty = available_qty + 1
            WHERE id=?
        """, (transaction[1],))

        db.commit()

        if fine == 0:
            flash('Item returned successfully on time')

        return redirect('/student_dashboard')

    except Exception as e:
        db.rollback()
        flash(f'Error returning item: {str(e)}')
        return redirect('/student_dashboard')


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@app.route('/reports')
def reports():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')

    cur = get_db().cursor()

    cur.execute("""
        SELECT e.name, COUNT(*) AS count
        FROM transactions t
        JOIN equipment e ON t.equipment_id = e.id
        GROUP BY t.equipment_id, e.name
        ORDER BY count DESC
    """)
    most_used = cur.fetchall()

    cur.execute("""
        SELECT u.name, e.name, t.fine, t.expected_return, t.return_time
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.status = 'late'
        ORDER BY t.return_time DESC
    """)
    late = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM transactions")
    total_transactions = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM transactions WHERE status='issued'")
    active_borrowings = cur.fetchone()[0]

    return render_template('reports.html',
                           most_used=most_used,
                           late=late,
                           total_transactions=total_transactions,
                           active_borrowings=active_borrowings)


# ---------------------------------------------------------------------------
# Email notifications (stub — enable SMTP section to actually send)
# ---------------------------------------------------------------------------

def send_email_notification(user_email, user_name, days_overdue, items_list):
    try:
        sender_email    = "your_email@gmail.com"
        sender_password = "your_app_password"

        subject = f"⚠️ URGENT: {user_name}, Your Equipment Return is {days_overdue} Days Overdue"

        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <div style="background-color: #ffebee; padding: 20px; border-radius: 8px; border-left: 4px solid #f44336;">
                    <h2 style="color: #f44336;">URGENT: Equipment Return Notice</h2>
                    <p>Dear <strong>{user_name}</strong>,</p>
                    <p>Your borrowed equipment is now <strong>{days_overdue} days overdue</strong>.</p>
                    <p><strong>Please return the following items immediately:</strong></p>
                    <ul style="color: #333;">
        """
        for item in items_list:
            html_body += f"<li>{item}</li>"
        html_body += """
                    </ul>
                    <p style="color: #f44336; font-weight: bold;">Fines are accumulating daily!</p>
                    <p>Please contact the admin if you have any questions.</p>
                </div>
            </body>
        </html>
        """

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = sender_email
        msg['To']      = user_email
        msg.attach(MIMEText(html_body, 'html'))

        print(f"Email notification prepared for {user_name} ({user_email})")
        # Uncomment to actually send:
        # server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        # server.login(sender_email, sender_password)
        # server.send_message(msg)
        # server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False


@app.route('/send_overdue_notifications')
def send_overdue_notifications():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')

    cur = get_db().cursor()
    cur.execute("""
        SELECT DISTINCT u.id, u.name, u.email, GROUP_CONCAT(e.name) AS items
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.status = 'issued'
          AND (julianday('now','localtime') - julianday(t.issue_time)) > 7
        GROUP BY u.id, u.name, u.email
    """)
    severe_overdue_users = cur.fetchall()

    notification_count = 0
    for user in severe_overdue_users:
        user_id, user_name, user_email, items = user[0], user[1], user[2], user[3]

        cur.execute("""
            SELECT MAX(CAST(julianday('now','localtime') - julianday(t.issue_time) AS INTEGER))
            FROM transactions t
            WHERE t.user_id = ? AND t.status = 'issued'
        """, (user_id,))
        days_overdue = cur.fetchone()[0]

        items_list = items.split(',') if items else []
        if send_email_notification(user_email, user_name, days_overdue, items_list):
            notification_count += 1

    flash(f'Sent {notification_count} email notification(s) to users with severely overdue items (>7 days)')
    return redirect('/admin_dashboard')


# ---------------------------------------------------------------------------
# Student fines page
# ---------------------------------------------------------------------------

@app.route('/student_fines')
def student_fines():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    cur = get_db().cursor()

    cur.execute("""
        SELECT t.id, e.name, t.issue_time, t.return_time, t.fine, t.status
        FROM transactions t
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.user_id = ? AND (t.status = 'late' OR t.fine > 0)
        ORDER BY t.return_time DESC
    """, (user_id,))
    fines = cur.fetchall()
    total_fine = sum(row[4] if row[4] else 0 for row in fines)

    return render_template('student_fines.html', fines=fines, total_fine=total_fine)


# ---------------------------------------------------------------------------
# Demo Data Seeder
# ---------------------------------------------------------------------------

@app.route('/seed_demo')
def seed_demo():
    """Populate the DB with realistic student activity for demonstration."""
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')

    db  = get_db()
    cur = db.cursor()
    now = datetime.now()

    def fmt(dt):
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    # ── Get equipment IDs (auto-seed sports gear if empty) ────────────────
    cur.execute("SELECT id, name, available_qty FROM equipment")
    all_eq = cur.fetchall()
    if not all_eq:
        default_gear = [
            ('Cricket Ball',      10, 10),
            ('Cricket Bat',        5,  5),
            ('Football',           6,  6),
            ('Basketball',         4,  4),
            ('Badminton Racket',   8,  8),
            ('Volleyball',         4,  4),
            ('Tennis Racket',      6,  6),
            ('Table Tennis Bat',  10, 10),
        ]
        for name, total, avail in default_gear:
            cur.execute(
                "INSERT INTO equipment(name,total_qty,available_qty) VALUES(?,?,?)",
                (name, total, avail)
            )
        db.commit()
        cur.execute("SELECT id, name, available_qty FROM equipment")
        all_eq = cur.fetchall()

    # ── Wipe old demo students & their data ────────────────────────────────
    cur.execute("SELECT id FROM users WHERE role='student'")
    old_ids = [r[0] for r in cur.fetchall()]
    if old_ids:
        placeholders = ','.join('?' * len(old_ids))
        cur.execute(f"DELETE FROM transactions  WHERE user_id IN ({placeholders})", old_ids)
        cur.execute(f"DELETE FROM reservations  WHERE user_id IN ({placeholders})", old_ids)
        cur.execute(f"DELETE FROM users         WHERE id       IN ({placeholders})", old_ids)

    # Reset all available_qty to total_qty
    cur.execute("UPDATE equipment SET available_qty = total_qty")

    # ── Create demo students ───────────────────────────────────────────────
    demo_students = [
        ('Arjun Sharma',  'arjun@college.edu',  'pass123', 'Computer Science', '3rd Year', '9876543210'),
        ('Priya Nair',    'priya@college.edu',   'pass123', 'Mechanical',       '2nd Year', '9845678901'),
        ('Ravi Kumar',    'ravi@college.edu',    'pass123', 'Electrical',       '4th Year', '9823456789'),
        ('Sneha Pillai',  'sneha@college.edu',   'pass123', 'Civil',            '1st Year', '9812345678'),
        ('Kiran Mehta',   'kiran@college.edu',   'pass123', 'Chemical',         '3rd Year', '9801234567'),
    ]
    sids = []
    for s in demo_students:
        cur.execute("""
            INSERT INTO users(name,email,password,role,department,year,contact)
            VALUES(?,?,?,'student',?,?,?)
        """, s)
        sids.append(cur.lastrowid)

    eq   = [r[0] for r in all_eq]          # list of equipment ids
    eqn  = len(eq)

    # ── Seed TRANSACTIONS ─────────────────────────────────────────────────
    # Each tuple: (student_idx, eq_idx_offset, issue_hrs_ago, return_hrs_ago_or_None, status, fine)
    txns = [
        # Active borrows — varying urgency
        (0, 0,  2,    None,  'issued',   0),    # OK  — 22 h remaining
        (1, 1,  10,   None,  'issued',   0),    # OK  — 14 h remaining
        (2, 2,  19,   None,  'issued',   0),    # WARNING — 5 h remaining
        (3, 3,  22,   None,  'issued',   0),    # CRITICAL — 2 h remaining
        (4, 4,  26,   None,  'issued',   0),    # OVERDUE — 2 h late
        (0, 1,  36,   None,  'issued',   0),    # OVERDUE — 12 h late
        # Returned on time (historical)
        (1, 0,  -48,  -30,   'returned', 0),
        (2, 1,  -72,  -52,   'returned', 0),
        (3, 2,  -96,  -78,   'returned', 0),
        # Late returns with fines
        (4, 0,  -48,  -10,   'late',  160),    # returned 38 h after issue → 14h overtime → ₹140
        (2, 3,  -72,  -24,   'late',  280),    # returned 48 h after issue → 24h overtime → ₹240
    ]

    for s_idx, eq_off, issue_ago, ret_ago, status, fine in txns:
        sid  = sids[s_idx % len(sids)]
        eid  = eq[eq_off % eqn]

        # Positive ago = hours in the past.  Negative ago = hours in the FUTURE (for historical, we shifted sign above with negative meaning hours from now going further back)
        issue_time      = now - timedelta(hours=abs(issue_ago)) if issue_ago >= 0 else now + timedelta(hours=abs(issue_ago))
        expected_return = issue_time + timedelta(hours=24)
        return_time     = (now - timedelta(hours=abs(ret_ago))) if ret_ago is not None else None

        cur.execute("""
            INSERT INTO transactions(user_id,equipment_id,issue_time,expected_return,return_time,status,fine)
            VALUES(?,?,?,?,?,?,?)
        """, (sid, eid, fmt(issue_time), fmt(expected_return),
              fmt(return_time) if return_time else None, status, fine))

        # Reduce available stock for active borrows
        if status == 'issued':
            cur.execute(
                "UPDATE equipment SET available_qty = MAX(0, available_qty - 1) WHERE id=?",
                (eid,)
            )

    # ── Seed RESERVATIONS ─────────────────────────────────────────────────
    reservations = [
        (0, 0,  26),   # Arjun  — picks up tomorrow (~26 h from now)
        (2, 1,  50),   # Ravi   — day after tomorrow
        (4, 2,  74),   # Kiran  — 3 days from now
    ]
    for s_idx, eq_off, pickup_hrs in reservations:
        sid         = sids[s_idx % len(sids)]
        eid         = eq[eq_off % eqn]
        res_time    = now + timedelta(hours=pickup_hrs)
        exp_return  = res_time + timedelta(hours=24)
        cur.execute("""
            INSERT INTO reservations(user_id,equipment_id,reservation_time,expected_return,status)
            VALUES(?,?,?,?,'reserved')
        """, (sid, eid, fmt(res_time), fmt(exp_return)))

    db.commit()
    flash(
        f'Demo data seeded! {len(demo_students)} students, {len(txns)} transactions, '
        f'{len(reservations)} reservations created. Login: arjun@college.edu / pass123'
    )
    return redirect('/admin_dashboard')


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True)