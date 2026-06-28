from fastapi import FastAPI

app = FastAPI(title="User Service")


@app.get("/users/{id}")
def get_user(id: str):
    return {"id": id, "name": "Alice", "email": "alice@example.com"}


@app.get("/users/profile")
def get_profile():
    return {"id": "me", "name": "Alice", "email": "alice@example.com"}
