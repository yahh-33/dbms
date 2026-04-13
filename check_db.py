from flask import Flask
from flask_mysqldb import MySQL
import os

app = Flask(__name__)

# Database configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '1214'
app.config['MYSQL_DB'] = 'sports_db'

mysql = MySQL(app)

def check_database():
    with app.app_context():
        cur = mysql.connection.cursor()

        # Check users
        cur.execute("SELECT * FROM users")
        users = cur.fetchall()
        print(f"Users ({len(users)}):")
        for user in users:
            print(f"  ID: {user[0]}, Name: {user[1]}, Email: {user[2]}, Role: {user[4]}")

        # Check equipment
        cur.execute("SELECT * FROM equipment")
        equipment = cur.fetchall()
        print(f"\nEquipment ({len(equipment)}):")
        for eq in equipment:
            print(f"  ID: {eq[0]}, Name: {eq[1]}, Total: {eq[2]}, Available: {eq[3]}")

        # Check transactions
        cur.execute("SELECT * FROM transactions")
        transactions = cur.fetchall()
        print(f"\nTransactions ({len(transactions)}):")
        for tx in transactions:
            print(f"  ID: {tx[0]}, User: {tx[1]}, Equipment: {tx[2]}, Status: {tx[5]}, Fine: {tx[6]}")

        cur.close()

if __name__ == "__main__":
    check_database()