import requests

resp = requests.post(
    "http://localhost:5001/start",
    json={"class_id": "CSC4400", "name": "Week X – Test"},
    timeout=5
)
print(resp.json())
