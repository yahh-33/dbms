from flask import Flask, render_template, request, redirect, session, flash
from db_config import mysql
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = "secretkey"

# MySQL Config
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '1214'
app.config['MYSQL_DB'] = 'sports_db'

mysql.init_app(app)

_db_initialized = False

def init_reservations_table():
    global _db_initialized
    if _db_initialized:
        return
    cur = mysql.connection.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reservations (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        equipment_id INT NOT NULL,
        reservation_time DATETIME NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(20) DEFAULT 'reserved',
        INDEX(user_id),
        INDEX(equipment_id)
    )
    """)
    mysql.connection.commit()
    cur.close()
    _db_initialized = True


@app.before_request
def setup_database():
    init_reservations_table()


# 👉 ADD ROUTES HERE 👇

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# 👉 Your other routes (login, register, dashboard, etc.)
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s AND password=%s", (email, password))
        user = cur.fetchone()

        if user:
            session['user_id'] = user[0]
            session['role'] = user[4]

            if user[4] == 'admin':
                return redirect('/admin_dashboard')
            else:
                return redirect('/student_dashboard')
        else:
            return "Invalid login"

    return render_template('login.html')


@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        data = request.form

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", (data['email'],))
        user = cur.fetchone()

        if user:
            return "Email already registered. <a href='/register'>Try again</a>"

        # Check if passwords match
        if data['password'] != data['confirm_password']:
            return "Passwords do not match. <a href='/register'>Try again</a>"

        try:
            cur.execute("""
            INSERT INTO users(name,email,password,role,department,year,contact)
            VALUES(%s,%s,%s,'student',%s,%s,%s)
            """, (
                data['name'],
                data['email'],
                data['password'],
                data['department'],
                data['year'],
                data['contact']
            ))
            mysql.connection.commit()
            cur.close()
            return redirect('/login')
        except Exception as e:
            return f"Registration failed: {str(e)} <a href='/register'>Try again</a>"

    return render_template('register.html')


@app.route('/student_dashboard')
def student_dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    
    user_id = session['user_id']
    print(f"DEBUG: Student dashboard for user_id: {user_id}")
    
    cur = mysql.connection.cursor()
    
    # Get available equipment
    cur.execute("SELECT * FROM equipment")
    equipment = cur.fetchall()
    print(f"DEBUG: Available equipment: {len(equipment)} items")
    for eq in equipment:
        print(f"  Equipment {eq[0]}: {eq[1]}, Available: {eq[3]}")
    
    # Get user's borrowed items with time calculations (precise to minutes)
    cur.execute("""
        SELECT t.id, e.name, t.issue_time, t.expected_return, t.status,
               TIMESTAMPDIFF(HOUR, t.issue_time, NOW()) as hours_elapsed,
               ROUND(TIMESTAMPDIFF(MINUTE, NOW(), t.expected_return) / 60.0, 1) as hours_remaining
        FROM transactions t
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.user_id = %s AND t.status = 'issued'
        ORDER BY t.issue_time DESC
    """, (user_id,))
    borrowed_items = cur.fetchall()
    print(f"DEBUG: Borrowed items for user {user_id}: {len(borrowed_items)} items")
    for item in borrowed_items:
        print(f"  Item {item[0]}: {item[1]}, Status: {item[4]}")
    
    # Get user's fines/penalties
    cur.execute("""
        SELECT t.id, e.name, t.return_time, t.fine, t.expected_return, t.issue_time
        FROM transactions t
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.user_id = %s AND (t.status = 'late' OR t.fine > 0)
        ORDER BY t.return_time DESC
    """, (user_id,))
    user_fines = cur.fetchall()
    total_fine = sum(fine[3] if fine[3] else 0 for fine in user_fines)

    # Get user's upcoming reservations
    cur.execute("""
        SELECT r.id, e.name, r.reservation_time, r.status
        FROM reservations r
        JOIN equipment e ON r.equipment_id = e.id
        WHERE r.user_id = %s AND r.status = 'reserved'
        ORDER BY r.reservation_time ASC
    """, (user_id,))
    upcoming_reservations = cur.fetchall()
    cur.close()

    min_datetime = datetime.now().strftime('%Y-%m-%dT%H:%M')

    return render_template('student_dashboard.html', equipment=equipment, borrowed_items=borrowed_items, 
                         user_fines=user_fines, total_fine=total_fine,
                         upcoming_reservations=upcoming_reservations,
                         min_datetime=min_datetime)


@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')
    
    cur = mysql.connection.cursor()

    # Get equipment
    cur.execute("SELECT * FROM equipment")
    equipment = cur.fetchall()

    # Get detailed transactions with user and equipment names
    cur.execute("""
        SELECT t.id, u.name as user_name, e.name as equipment_name, 
               t.issue_time, t.return_time, t.status, t.fine, u.email,
               TIMESTAMPDIFF(HOUR, t.issue_time, NOW()) as hours_elapsed
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN equipment e ON t.equipment_id = e.id
        ORDER BY t.issue_time DESC
    """)
    logs = cur.fetchall()

    # Get overdue items (more than 24 hours)
    cur.execute("""
        SELECT t.id, u.name as user_name, u.email, e.name as equipment_name, 
               t.issue_time, ROUND(TIMESTAMPDIFF(MINUTE, t.issue_time, NOW()) / 60.0, 1) as hours_elapsed,
               TIMESTAMPDIFF(DAY, t.issue_time, NOW()) as days_elapsed,
               ROUND(TIMESTAMPDIFF(MINUTE, NOW(), t.expected_return) / 60.0, 1) as hours_remaining,
               t.fine
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.status = 'issued' AND TIMESTAMPDIFF(HOUR, t.issue_time, NOW()) > 24
        ORDER BY t.issue_time DESC
    """)
    overdue_items = cur.fetchall()
    
    # Get late returns with fines
    cur.execute("""
        SELECT t.id, u.name as user_name, u.email, e.name as equipment_name, 
               t.issue_time, t.return_time, t.fine,
               TIMESTAMPDIFF(DAY, t.issue_time, t.return_time) as days_borrowed
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.status = 'late'
        ORDER BY t.return_time DESC
    """)
    late_returns = cur.fetchall()
    
    # Get users with very late items (>7 days overdue)
    cur.execute("""
        SELECT DISTINCT u.id, u.name, u.email
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE t.status = 'issued' AND TIMESTAMPDIFF(DAY, t.issue_time, NOW()) > 7
    """)
    users_with_severe_overdue = cur.fetchall()
    
    cur.close()

    return render_template('admin_dashboard.html', 
                         equipment=equipment, 
                         logs=logs, 
                         overdue_items=overdue_items,
                         late_returns=late_returns,
                         users_with_severe_overdue=users_with_severe_overdue)


@app.route('/add_equipment', methods=['POST'])
def add_equipment():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')
    
    name = request.form['name']
    qty = request.form['qty']

    try:
        cur = mysql.connection.cursor()
        cur.execute("""
        INSERT INTO equipment(name,total_qty,available_qty)
        VALUES(%s,%s,%s)
        """,(name,qty,qty))
        mysql.connection.commit()
        cur.close()
        return redirect('/admin_dashboard')
    except Exception as e:
        return f"Error adding equipment: {str(e)} <a href='/admin_dashboard'>Back</a>"


@app.route('/issue/<int:id>', methods=['POST'])
def issue(id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    
    # Set expected return to 24 hours from now
    expected_return = datetime.now() + timedelta(hours=24)
    expected_return_str = expected_return.strftime('%Y-%m-%d %H:%M:%S')

    print(f"DEBUG: Borrow request for equipment ID {id} by user {user_id} with automatic 24-hour return time: {expected_return_str}")  # Debug print

    cur = mysql.connection.cursor()

    try:
        # Check if equipment exists and is available
        cur.execute("SELECT name, available_qty FROM equipment WHERE id=%s", (id,))
        equipment = cur.fetchone()
        print(f"DEBUG: Equipment found: {equipment}")  # Debug print

        if not equipment:
            flash('Equipment not found')
            return redirect('/student_dashboard')

        if equipment[1] <= 0:
            flash(f'{equipment[0]} is not available for borrowing')
            return redirect('/student_dashboard')

        # Check if user already has this equipment borrowed
        cur.execute("""
            SELECT id FROM transactions
            WHERE user_id=%s AND equipment_id=%s AND status='issued'
        """, (user_id, id))
        existing = cur.fetchone()
        print(f"DEBUG: Existing borrow check: {existing}")  # Debug print

        if existing:
            flash(f'You already have {equipment[0]} borrowed')
            return redirect('/student_dashboard')

        # Reduce available quantity
        cur.execute("UPDATE equipment SET available_qty = available_qty - 1 WHERE id=%s", (id,))
        print(f"DEBUG: Updated equipment quantity for ID {id}")  # Debug print

        # Insert transaction
        cur.execute("""
        INSERT INTO transactions(user_id,equipment_id,issue_time,expected_return,status,fine)
        VALUES(%s,%s,NOW(),%s,'issued',0)
        """, (user_id, id, expected_return_str))
        print(f"DEBUG: Inserted transaction for user {user_id}, equipment {id}")  # Debug print

        mysql.connection.commit()
        print("DEBUG: Transaction committed successfully")  # Debug print
        flash(f'Successfully borrowed {equipment[0]}. Return by {expected_return.strftime("%Y-%m-%d %H:%M")}')
        return redirect('/student_dashboard')

    except Exception as e:
        mysql.connection.rollback()
        print(f"DEBUG: Error during borrowing: {str(e)}")  # Debug print
        flash(f'Error borrowing equipment: {str(e)}')
        return redirect('/student_dashboard')
    finally:
        cur.close()


@app.route('/reserve/<int:id>', methods=['POST'])
def reserve(id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
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

    cur = mysql.connection.cursor()
    try:
        # Prevent duplicate reservations for the same equipment by the same student
        cur.execute("""
            SELECT id FROM reservations
            WHERE user_id=%s AND equipment_id=%s AND status='reserved'
        """, (user_id, id))
        existing_reservation = cur.fetchone()

        if existing_reservation:
            flash('You already have a reservation for this equipment. Cancel it first if you want to book a different slot.')
            return redirect('/student_dashboard')

        # Check reservation capacity for that equipment
        cur.execute("""
            SELECT COUNT(*)
            FROM reservations
            WHERE equipment_id=%s AND reservation_time=%s AND status='reserved'
        """, (id, reservation_datetime))
        reserved_count = cur.fetchone()[0]

        cur.execute("SELECT total_qty FROM equipment WHERE id=%s", (id,))
        equipment = cur.fetchone()

        if not equipment:
            flash('Equipment not found.')
            return redirect('/student_dashboard')

        if reserved_count >= equipment[0]:
            flash('This equipment is already fully reserved for the selected time.')
            return redirect('/student_dashboard')

        cur.execute("""
            INSERT INTO reservations(user_id,equipment_id,reservation_time,status)
            VALUES(%s,%s,%s,'reserved')
        """, (user_id, id, reservation_datetime))
        mysql.connection.commit()
        flash('Reservation created successfully. Please pick up your equipment at the reserved time.')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error creating reservation: {str(e)}')
    finally:
        cur.close()

    return redirect('/student_dashboard')


@app.route('/cancel_reservation/<int:id>', methods=['POST'])
def cancel_reservation(id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    cur = mysql.connection.cursor()

    try:
        cur.execute("""
            SELECT id FROM reservations
            WHERE id=%s AND user_id=%s AND status='reserved'
        """, (id, user_id))
        reservation = cur.fetchone()

        if not reservation:
            flash('Reservation not found or already cancelled.')
            return redirect('/student_dashboard')

        cur.execute("""
            UPDATE reservations
            SET status='cancelled'
            WHERE id=%s
        """, (id,))
        mysql.connection.commit()
        flash('Reservation cancelled successfully.')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error cancelling reservation: {str(e)}')
    finally:
        cur.close()

    return redirect('/student_dashboard')


@app.route('/return/<int:id>')
def return_item(id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    cur = mysql.connection.cursor()

    try:
        # Get transaction and verify ownership
        cur.execute("""
            SELECT expected_return, equipment_id, status, issue_time
            FROM transactions
            WHERE id=%s AND user_id=%s
        """, (id, user_id))
        transaction = cur.fetchone()

        if not transaction:
            flash('Transaction not found or access denied')
            return redirect('/student_dashboard')

        if transaction[2] != 'issued':
            flash('This item has already been returned')
            return redirect('/student_dashboard')

        expected_return = transaction[0]
        equipment_id = transaction[1]
        issue_time = transaction[3]

        now = datetime.now()
        fine = 0
        status = 'returned'

        # Calculate fine if late (after 24 hours from issue time)
        if isinstance(expected_return, str):
            expected_return = datetime.fromisoformat(expected_return.replace('T', ' '))
        if isinstance(issue_time, str):
            issue_time = datetime.fromisoformat(issue_time.replace('T', ' '))

        # Check if returned after 24 hours from issue time
        time_diff = now - issue_time
        hours_elapsed = time_diff.total_seconds() / 3600  # Convert to hours

        if hours_elapsed > 24:
            # Calculate fine: ₹10 per hour after 24 hours
            overtime_hours = hours_elapsed - 24
            fine = int(overtime_hours * 10)
            status = 'late'
            flash(f'Late return! {overtime_hours:.1f} hours overtime. Fine: ₹{fine}')

        # Update transaction
        cur.execute("""
        UPDATE transactions
        SET return_time=NOW(), status=%s, fine=%s
        WHERE id=%s
        """, (status, fine, id))

        # Increase available quantity
        cur.execute("""
        UPDATE equipment
        SET available_qty = available_qty + 1
        WHERE id=%s
        """, (equipment_id,))

        mysql.connection.commit()

        if fine == 0:
            flash('Item returned successfully on time')
        else:
            flash(f'Item returned with fine: ₹{fine}')

        return redirect('/student_dashboard')

    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error returning item: {str(e)}')
        return redirect('/student_dashboard')
    finally:
        cur.close()


@app.route('/reports')
def reports():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')
    
    cur = mysql.connection.cursor()

    # Most used equipment with names
    cur.execute("""
    SELECT e.name, COUNT(*) as count 
    FROM transactions t
    JOIN equipment e ON t.equipment_id = e.id
    GROUP BY t.equipment_id, e.name
    ORDER BY count DESC
    """)
    most_used = cur.fetchall()

    # Late returns with user and equipment names
    cur.execute("""
    SELECT u.name, e.name, t.fine, t.expected_return, t.return_time
    FROM transactions t
    JOIN users u ON t.user_id = u.id
    JOIN equipment e ON t.equipment_id = e.id
    WHERE t.status='late'
    ORDER BY t.return_time DESC
    """)
    late = cur.fetchall()

    # Total transactions
    cur.execute("SELECT COUNT(*) FROM transactions")
    total_transactions = cur.fetchone()[0]

    # Active borrowings
    cur.execute("SELECT COUNT(*) FROM transactions WHERE status='issued'")
    active_borrowings = cur.fetchone()[0]

    cur.close()

    return render_template('reports.html', 
                         most_used=most_used, 
                         late=late, 
                         total_transactions=total_transactions,
                         active_borrowings=active_borrowings)


def send_email_notification(user_email, user_name, days_overdue, items_list):
    """Send email notification for overdue items (> 7 days)"""
    try:
        # Email configuration - Update these with your email settings
        sender_email = "your_email@gmail.com"
        sender_password = "your_app_password"  # Use app-specific password
        
        # Create email message
        subject = f"⚠️ URGENT: {user_name}, Your Equipment Return is {days_overdue} Days Overdue"
        
        # HTML body
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
                    <p style="margin-top: 20px;">Please contact the admin if you have any questions.</p>
                    <p>Thank you!</p>
                </div>
            </body>
        </html>
        """
        
        # Create message object
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = user_email
        
        # Attach HTML part
        msg.attach(MIMEText(html_body, 'html'))
        
        # Note: Email sending requires SMTP configuration
        # For local testing, this function can be modified to log instead
        print(f"Email notification prepared for {user_name} ({user_email})")
        print(f"Subject: {subject}")
        print(f"Days overdue: {days_overdue}")
        
        # Uncomment to enable actual email sending:
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
    """Send email notifications to users with severely overdue items (>7 days)"""
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')
    
    cur = mysql.connection.cursor()
    
    # Get users with items overdue more than 7 days
    cur.execute("""
        SELECT DISTINCT u.id, u.name, u.email, GROUP_CONCAT(e.name) as items
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.status = 'issued' AND TIMESTAMPDIFF(DAY, t.issue_time, NOW()) > 7
        GROUP BY u.id, u.name, u.email
    """)
    severe_overdue_users = cur.fetchall()
    
    notification_count = 0
    for user in severe_overdue_users:
        user_id, user_name, user_email, items = user
        days_overdue = None
        
        # Get days overdue for this user
        cur.execute("""
            SELECT MAX(TIMESTAMPDIFF(DAY, t.issue_time, NOW()))
            FROM transactions t
            WHERE t.user_id = %s AND t.status = 'issued'
        """, (user_id,))
        days_overdue = cur.fetchone()[0]
        
        items_list = items.split(',') if items else []
        
        if send_email_notification(user_email, user_name, days_overdue, items_list):
            notification_count += 1
    
    cur.close()
    
    flash(f'Sent {notification_count} email notification(s) to users with severely overdue items (>7 days)')
    return redirect('/admin_dashboard')


@app.route('/student_fines')
def student_fines():
    """Display student's fines and penalties"""
    if 'user_id' not in session:
        return redirect('/login')
    
    user_id = session['user_id']
    
    cur = mysql.connection.cursor()
    
    # Get student's fines
    cur.execute("""
        SELECT t.id, e.name, t.issue_time, t.return_time, t.fine, t.status
        FROM transactions t
        JOIN equipment e ON t.equipment_id = e.id
        WHERE t.user_id = %s AND (t.status = 'late' OR t.fine > 0)
        ORDER BY t.return_time DESC
    """, (user_id,))
    fines = cur.fetchall()
    
    total_fine = sum(fine[4] if fine[4] else 0 for fine in fines)
    
    cur.close()
    
    return render_template('student_fines.html', fines=fines, total_fine=total_fine)


# 👉 ALWAYS KEEP THIS AT THE END
if __name__ == '__main__':
    app.run(debug=True)