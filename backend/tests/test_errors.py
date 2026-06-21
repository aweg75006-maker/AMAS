def test_session_not_found_error_shape(client):
    response = client.get(
        "/api/sessions/not-exist",
        headers={"X-Request-ID": "test-session-not-found"},
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "test-session-not-found"

    body = response.json()
    assert body["error"]["code"] == "SESSION_NOT_FOUND"
    assert body["error"]["message"] == "会话不存在"
    assert body["error"]["request_id"] == "test-session-not-found"
    assert body["error"]["details"]["session_id"] == "not-exist"


def test_upload_too_many_files_error_shape(client):
    files = [
        ("files", (f"f{i}.pdf", b"x", "application/pdf"))
        for i in range(6)
    ]
    response = client.post(
        "/api/upload",
        files=files,
        headers={"X-Request-ID": "test-too-many-files"},
    )

    assert response.status_code == 400
    assert response.headers["X-Request-ID"] == "test-too-many-files"

    body = response.json()
    assert body["error"]["code"] == "TOO_MANY_FILES"
    assert body["error"]["request_id"] == "test-too-many-files"
    assert body["error"]["details"] == {
        "max_files": 5,
        "actual_files": 6,
    }


def test_upload_rejects_unsupported_extension(client):
    response = client.post(
        "/api/upload",
        files=[("files", ("note.txt", b"hello", "text/plain"))],
        headers={"X-Request-ID": "test-unsupported-extension"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert body["error"]["request_id"] == "test-unsupported-extension"


def test_upload_rejects_unsupported_content_type(client):
    response = client.post(
        "/api/upload",
        files=[("files", ("report.pdf", b"%PDF-1.4", "text/plain"))],
        headers={"X-Request-ID": "test-unsupported-content-type"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_CONTENT_TYPE"
    assert body["error"]["request_id"] == "test-unsupported-content-type"


def test_generated_request_id_is_returned(client):
    response = client.get("/api/sessions/not-exist")

    assert response.status_code == 404
    assert response.headers.get("X-Request-ID")
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
