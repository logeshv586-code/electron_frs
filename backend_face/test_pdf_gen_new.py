import requests
import os

BASE_URL = "http://localhost:8005/api/events/export"

def test_endpoint(name, url):
    print(f"Testing {name}...")
    try:
        # We expect 401 if unauthenticated, which is GOOD (means the route exists)
        # If it returns 404, the route is missing.
        # If it returns 405, the method is wrong (shadowing).
        response = requests.get(url)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print(f"Success! PDF content received.")
        elif response.status_code == 401:
            print(f"Success! Route exists but requires authentication.")
        else:
            print(f"Unexpected status: {response.status_code}")
            if response.status_code == 405:
                print("ERROR: 405 Method Not Allowed - Shadowing issue persists!")
    except Exception as e:
        print(f"Error: {e}")
    print("-" * 30)

if __name__ == "__main__":
    endpoints = [
        ("Dashboard PDF", f"{BASE_URL}/dashboard-pdf"),
        ("Attendance PDF", f"{BASE_URL}/attendance-pdf"),
        ("Employee PDF", f"{BASE_URL}/employees-pdf"),
        ("Aggregate Attendance PDF", f"{BASE_URL}/attendance-aggregate-pdf?start_date=2024-01-01&end_date=2024-01-07")
    ]
    
    for name, url in endpoints:
        test_endpoint(name, url)
