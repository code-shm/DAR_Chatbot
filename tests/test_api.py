from fastapi.testclient import TestClient

import server.main as srv


class StubBot:
    def answer(self, message, history, source="both"):
        return {"answer": f"stub answer to: {message} [1]",
                "sources": [{"n": 1, "title": "T", "url": "https://x", "source": source
                             if source != "both" else "darglobal", "type": "page"}],
                "mode": "mock"}


def client(monkeypatch):
    monkeypatch.setattr(srv, "bot", lambda: StubBot())
    return TestClient(srv.app)


def test_health(monkeypatch):
    r = client(monkeypatch).get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_chat_roundtrip(monkeypatch):
    r = client(monkeypatch).post("/api/chat", json={
        "message": "What projects does DarGlobal have?",
        "history": [{"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"}],
        "source": "darglobal"})
    assert r.status_code == 200
    body = r.json()
    assert "stub answer" in body["answer"]
    assert body["sources"][0]["url"].startswith("https://")


def test_chat_validation(monkeypatch):
    c = client(monkeypatch)
    assert c.post("/api/chat", json={"message": ""}).status_code == 422
    assert c.post("/api/chat", json={"message": "x", "source": "evil"}).status_code == 422


def test_refresh_requires_token(monkeypatch):
    assert client(monkeypatch).post("/api/admin/refresh").status_code == 401


def test_suggestions(monkeypatch):
    r = client(monkeypatch).get("/api/suggestions")
    assert len(r.json()["suggestions"]) >= 5
