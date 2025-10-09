
from RestSample.apiapp import router as RestSample
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(RestSample)
client = TestClient(app)


def test_read_main():
    print("test_read_main")
    response = client.get("/RestSample/")
    assert response.status_code == 200
    assert response.json() == {"Path": "/RestSample/"}


if __name__ == "__main__":
    test_read_main()
