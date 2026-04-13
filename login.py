from flask import render_template, request, redirect, session
from db_config import mysql

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

    # 🔴 THIS LINE IS THE MOST IMPORTANT
    return render_template('login.html')