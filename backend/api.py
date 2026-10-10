from fastapi import FastAPI
from fastapi import status


app = FastAPI()

@app.get("/health_check", status_code=status.HTTP_200_OK)
async def root():
    return {"Response": "OK"}