from app.security import hash_password, verify_password


def test_password_hash():
    encoded = hash_password("admin1234")
    assert verify_password("admin1234", encoded)
    assert not verify_password("wrong", encoded)
