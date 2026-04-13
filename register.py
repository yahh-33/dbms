from flask import render_template, request, redirect
from db_config import mysql

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