from flask import request, redirect, session
from db_config import mysql

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