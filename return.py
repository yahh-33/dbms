from flask import session, redirect, flash
from db_config import mysql
from datetime import datetime

@app.route('/return/<int:id>')
def return_item(id):
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    cur = mysql.connection.cursor()

    try:
        # Get transaction and verify ownership
        cur.execute("""
            SELECT expected_return, equipment_id, status
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

        now = datetime.now()
        fine = 0
        status = 'returned'

        # Calculate fine if late
        if isinstance(expected_return, str):
            expected_return = datetime.fromisoformat(expected_return.replace('T', ' '))

        if now > expected_return:
            # Calculate days late
            days_late = (now - expected_return).days
            fine = max(50, days_late * 10)  # Minimum 50, or 10 per day late
            status = 'late'

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

        if fine > 0:
            flash(f'Item returned late. Fine: ₹{fine}')
        else:
            flash('Item returned successfully')

        return redirect('/student_dashboard')

    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error returning item: {str(e)}')
        return redirect('/student_dashboard')
    finally:
        cur.close()