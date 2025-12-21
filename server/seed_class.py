import requests

url = "http://localhost:5001/api/classes"

payload = {
    "id": "CSC4400",
    "name": "Software Testing",
    "platform_link": "https://meet.google.com/ibk-ageg-wew"
}

try:
    r = requests.post(url, json=payload, timeout=5)
    r.raise_for_status()
    print("Response:", r.json())
except Exception as e:
    print("Error:", e)
