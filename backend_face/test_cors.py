import requests

url = "http://localhost:8005/api/events/dashboard/export-pdf"
# We don't have a valid token here, but we can see if it returns 401 or 405
headers = {
    "Authorization": "Bearer test_token",
    "Origin": "http://localhost:3000",
    "Access-Control-Request-Method": "GET"
}

print("Testing GET...")
try:
    response = requests.get(url, headers=headers)
    print(f"Status: {response.status_code}")
except Exception as e:
    print(f"Error: {e}")

print("\nTesting OPTIONS...")
try:
    response = requests.options(url, headers=headers)
    print(f"Status: {response.status_code}")
    print(f"Allow Header: {response.headers.get('Allow')}")
except Exception as e:
    print(f"Error: {e}")
