import requests
from fastapi import FastAPI

app = FastAPI(title="Payment Service")

USER_SERVICE_URL = "http://user-service"


@app.post("/payments/charge")
def charge(user_id: str, amount: float):
    user = requests.get(f"{USER_SERVICE_URL}/users/{user_id}").json()
    return {"status": "charged", "user": user["name"], "amount": amount}


@app.get("/payments/{id}")
def get_payment(id: str):
    return {"id": id, "amount": 99.99, "status": "completed"}
