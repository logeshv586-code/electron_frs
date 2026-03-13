import requests
import json
import os

# Base URL for the API
BASE_URL = "http://localhost:8000"

# Sample token (replace with a valid one if needed for authentication)
# Alternatively, mock the request scope in the backend for testing
TOKEN = "YOUR_TOKEN_HERE"

def test_attendance_pdf():
    print("Testing Attendance PDF export...")
    url = f"{BASE_URL}/api/events/attendance/export-pdf"
    # Note: This requires the server to be running and authenticated if middleware is active
    # For a unit-like test, we could call the function directly if imported
    print(f"URL: {url}")
    # response = requests.get(url, headers={"Authorization": f"Bearer {TOKEN}"})
    # if response.status_code == 200:
    #     with open("test_attendance.pdf", "wb") as f:
    #         f.write(response.content)
    #     print("PDF exported successfully to test_attendance.pdf")
    # else:
    #     print(f"Failed to export PDF: {response.status_code}")

def test_employee_pdf():
    print("Testing Employee PDF export...")
    url = f"{BASE_URL}/api/events/employees/export-pdf"
    print(f"URL: {url}")

if __name__ == "__main__":
    test_attendance_pdf()
    test_employee_pdf()
