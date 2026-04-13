from flask import session, request, redirect, flash
from db_config import mysql
from datetime import datetime, timedelta

@app.route('/issue/<int:id>', methods=['POST'])
def issue(id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']

    cur = mysql.connection.cursor()

    try:
        # Check if equipment exists and is available
        cur.execute("SELECT name, available_qty FROM equipment WHERE id=%s", (id,))
        equipment = cur.fetchone()

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

        if existing:
            flash(f'You already have {equipment[0]} borrowed')
            return redirect('/student_dashboard')

        # Reduce available quantity
        cur.execute("UPDATE equipment SET available_qty = available_qty - 1 WHERE id=%s", (id,))

        # Insert transaction with automatic 24-hour return time (calculated in SQL)
        cur.execute("""
        INSERT INTO transactions(user_id,equipment_id,issue_time,expected_return,status,fine)
        VALUES(%s,%s,NOW(),DATE_ADD(NOW(), INTERVAL 24 HOUR),'issued',0)
        """, (user_id, id))

        mysql.connection.commit()
        
        # Fetch the expected return time from database for display
        cur.execute("SELECT expected_return FROM transactions WHERE user_id=%s AND equipment_id=%s AND status='issued' ORDER BY issue_time DESC LIMIT 1", (user_id, id))
        result = cur.fetchone()
        expected_return_time = result[0] if result else datetime.now() + timedelta(hours=24)
        
        flash(f'Successfully borrowed {equipment[0]}. Return by {expected_return_time.strftime("%Y-%m-%d %H:%M") if hasattr(expected_return_time, "strftime") else expected_return_time}')
        return redirect('/student_dashboard')

    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error borrowing equipment: {str(e)}')
        return redirect('/student_dashboard')
    finally:
        cur.close()

        # Insert transaction
        cur.execute("""
        INSERT INTO transactions(user_id,equipment_id,issue_time,expected_return,status,fine)
        VALUES(%s,%s,NOW(),%s,'issued',0)
        """, (user_id, id, expected_return_str))

        mysql.connection.commit()
        flash(f'Successfully borrowed {equipment[0]}')
        return redirect('/student_dashboard')

    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error borrowing equipment: {str(e)}')
        return redirect('/student_dashboard')
    finally:
        cur.close()