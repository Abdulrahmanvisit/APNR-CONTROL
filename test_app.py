import io

import app
from anpr import clean_plate_text


app.app.config.update(TESTING=True, SECRET_KEY="test-secret")


def test_clean_plate_text_removes_ocr_noise():
    assert clean_plate_text(" ab-c_12!\n") == "ABC12"


def test_protected_routes_redirect_anonymous_users():
    client = app.app.test_client()

    assert client.get("/scan").status_code == 302
    assert client.get("/watchlist").status_code == 302
    assert client.get("/logs").status_code == 302
    assert client.get("/logs/export").status_code == 302


def test_watchlist_write_requires_admin():
    client = app.app.test_client()
    with client.session_transaction() as session:
        session["user"] = "operator"
        session["role"] = "Operator"

    response = client.post(
        "/watchlist/add",
        data={"plate_number": "ABC123", "status": "Blocked"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/watchlist")


def test_watchlist_edit_and_delete_require_admin():
    client = app.app.test_client()
    with client.session_transaction() as session:
        session["user"] = "operator"
        session["role"] = "Operator"

    edit_response = client.post(
        "/watchlist/ABC123/edit",
        data={"status": "Allowed", "notes": "Updated"},
    )
    delete_response = client.post("/watchlist/ABC123/delete")

    assert edit_response.status_code == 302
    assert delete_response.status_code == 302
    assert edit_response.headers["Location"].endswith("/watchlist")
    assert delete_response.headers["Location"].endswith("/watchlist")


def test_upload_extension_is_checked_before_saving():
    client = app.app.test_client()
    with client.session_transaction() as session:
        session["user"] = "operator"
        session["role"] = "Operator"

    response = client.post(
        "/scan",
        data={"plate_image": (io.BytesIO(b"not an image"), "plate.exe")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/scan")


def test_operator_cannot_open_admin_workspace():
    client = app.app.test_client()
    with client.session_transaction() as session:
        session["user"] = "operator"
        session["role"] = "Operator"

    response = client.get("/admin/dashboard")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/watchlist")


def test_unknown_credentials_do_not_create_a_session():
    client = app.app.test_client()
    response = client.post("/login", data={"username": "not-a-user", "password": "wrong"})

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "user" not in session
