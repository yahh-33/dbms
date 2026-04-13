from flask import render_template, session, redirect
from db_config import mysql

@app.route('/student_dashboard')
def student_dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM equipment")
    equipment = cur.fetchall()
    cur.close()

    return render_template('student_dashboard.html', equipment=equipment)