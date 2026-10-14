from fastapi import FastAPI
import psycopg2
import os

app = FastAPI()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:password@db:5432/appdb"
)

@app.get("/")
def root():
    return {"message": "FastAPI container works"}

@app.get("/db-test")
def test_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        result = cur.fetchone()
        conn.close()
        return {"database": "connected", "result": result}
    except Exception as e:
        return {"database": "connection failed", "error": str(e)}