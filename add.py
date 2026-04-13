@app.route('/add_equipment', methods=['POST'])
def add_equipment():
    name = request.form['name']
    qty = request.form['qty']

    cur = mysql.connection.cursor()

    cur.execute("""
    INSERT INTO equipment(name,total_qty,available_qty)
    VALUES(%s,%s,%s)
    """,(name,qty,qty))

    mysql.connection.commit()
    return redirect('/admin_dashboard')