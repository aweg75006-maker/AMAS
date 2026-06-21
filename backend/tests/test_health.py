def test_health_endpoint_reports_metadata_backend(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["metadata"]["backend"] in {"redis", "postgres"}
    assert "dsn" not in str(body).lower()
    assert "123456" not in str(body)
