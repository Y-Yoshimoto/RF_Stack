
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rest_sample.apiapp import router as rest_sample_router

app = FastAPI()
app.include_router(rest_sample_router)
client = TestClient(app)


def test_read_main():
    print("test_read_main")
    response = client.get("/RestSample/")
    assert response.status_code == 200
    assert response.json() == {"Path": "/RestSample/"}


if __name__ == "__main__":
    test_read_main()
