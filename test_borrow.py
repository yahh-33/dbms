import requests
from datetime import datetime, timedelta

# Flask app is running on localhost:5000
base_url = 'http://127.0.0.1:5000'

# Create a session to maintain cookies
session = requests.Session()

def test_borrowing():
    print("Testing borrowing functionality...")

    # Use a fixed email to avoid creating duplicates
    test_email = 'test@student.com'

    # First, try to login with existing user
    login_data = {
        'email': test_email,
        'password': 'testpass'
    }

    print("Attempting login with existing user...")
    response = session.post(f'{base_url}/login', data=login_data)
    print(f"Login response status: {response.status_code}")
    print(f"Login response URL: {response.url}")

    if 'student_dashboard' not in response.url:
        print("User doesn't exist, registering...")
        # Register the user
        register_data = {
            'name': 'Test Student',
            'email': test_email,
            'password': 'testpass',
            'confirm_password': 'testpass',
            'department': 'CS',
            'year': '2024',
            'contact': '1234567890'
        }

        response = session.post(f'{base_url}/register', data=register_data)
        print(f"Register response status: {response.status_code}")

        # Now login
        response = session.post(f'{base_url}/login', data=login_data)
        print(f"Login response status: {response.status_code}")
        print(f"Login response URL: {response.url}")

        if 'student_dashboard' not in response.url:
            print("Login failed after registration!")
            print(response.text[:500])
            return

    print("Login successful!")

    # Now try to borrow equipment (ID 1 - Football)
    # Set expected return to 2 hours from now
    expected_return = (datetime.now() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')

    borrow_data = {
        'expected_return': expected_return
    }

    print(f"Attempting to borrow Football with return time: {expected_return}")
    response = session.post(f'{base_url}/issue/1', data=borrow_data)
    print(f"Borrow response status: {response.status_code}")
    print(f"Borrow response URL: {response.url}")

    # Check if redirect back to student_dashboard
    if 'student_dashboard' in response.url:
        print("Borrow request processed (redirected back to dashboard)")
        # Check the dashboard content for flash messages
        dashboard_response = session.get(f'{base_url}/student_dashboard')
        content = dashboard_response.text

        # Check for flash messages
        if 'Successfully borrowed' in content:
            print("✅ SUCCESS: Found success message in dashboard")
        elif 'Error borrowing' in content:
            print("❌ ERROR: Found error message in dashboard")
        else:
            print("⚠️  WARNING: No flash message found")

        # Check if borrowed items table has content
        if 'You haven\'t borrowed any items yet' in content:
            print("❌ ISSUE: Still shows 'no borrowed items' message")
        elif 'Football' in content and 'borrowed' in content.lower():
            print("✅ SUCCESS: Football appears in borrowed items")
        else:
            print("⚠️  UNCLEAR: Borrowed items section exists but content unclear")

        # Check if available equipment shows reduced quantity
        if 'Available: 3' in content:
            print("✅ SUCCESS: Equipment availability shows 3 (reduced from 4)")
        else:
            print("❌ ISSUE: Equipment availability not updated in UI")

        print("\nDashboard content snippet around borrowed items:")
        # Find the borrowed items section
        start = content.find('<h3>My Borrowed Items</h3>')
        if start != -1:
            end = content.find('<h3>Available Equipment</h3>', start)
            if end != -1:
                borrowed_section = content[start:end]
                print(borrowed_section[:800])
            else:
                print("Could not find equipment section")
        else:
            print("Could not find borrowed items section")
    else:
        print("Unexpected redirect!")
        print(response.text[:500])

if __name__ == "__main__":
    test_borrowing()