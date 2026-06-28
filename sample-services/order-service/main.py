import requests
from fastapi import FastAPI

app = FastAPI(title="Order Service")

USER_SERVICE_URL = "http://user-service"
PAYMENT_SERVICE_URL = "http://payment-service"


@app.post("/orders/create")
def create_order(user_id: str, items: list):
    user = requests.get(f"{USER_SERVICE_URL}/users/{user_id}").json()
    charge = requests.post(
        f"{PAYMENT_SERVICE_URL}/payments/charge",
        json={"user_id": user_id, "amount": len(items) * 10.0},
    ).json()
    return {"order_id": "ord-001", "user": user["name"], "charge": charge}


@app.get("/orders/{id}")
def get_order(id: str):
    return {"id": id, "status": "shipped", "items": ["widget-a", "widget-b"]}
