import requests
import json

# Simulirani GitHub webhook payload
payload = {
    "ref": "refs/heads/main",
    "repository": {
        "full_name": "c4ps63/TestRepo"  
    },
    "pusher": {
        "name": "Test User"
    },
    "commits": [
        {
            "id": "65f52c2900191143efeacfb3ed2ff54e212322ce",  
            "message": "[86c6t8m47] Dodao test 2"
        }
    ]
}

response = requests.post(
    'http://localhost:5000/webhook',
    json=payload
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")