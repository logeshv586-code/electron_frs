import requests

url = "http://localhost:8005/api/events/dashboard/export-pdf"
try:
    response = requests.get(url)
    print(f"Status Code: {response.status_code}")
    print(f"Headers: {dict(response.headers)}")
    print(f"Body: {response.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
