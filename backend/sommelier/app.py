from fastapi import FastAPI

app = FastAPI(title="Sommelier")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
