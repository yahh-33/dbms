from flask import render_template, session, redirect
from db_config import mysql

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect('/login')
    
    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM equipment")
    equipment = cur.fetchall()

    cur.execute("SELECT * FROM transactions")
    logs = cur.fetchall()
    
    cur.close()

    return render_template('admin_dashboard.html', equipment=equipment, logs=logs)