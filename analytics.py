@app.route('/reports')
def reports():
    cur = mysql.connection.cursor()

    # Most used equipment
    cur.execute("""
    SELECT equipment_id, COUNT(*) as count 
    FROM transactions 
    GROUP BY equipment_id 
    ORDER BY count DESC
    """)
    most_used = cur.fetchall()

    # Late returns
    cur.execute("SELECT * FROM transactions WHERE status='late'")
    late = cur.fetchall()

    return render_template('reports.html', most_used=most_used, late=late)