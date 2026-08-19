from app.services.smart_upload import analyze_filename, choose_latest, choose_primary, extract_version


def test_version_patterns():
    cases = {
        "POSID-1.5.0.exe": "1.5.0",
        "POSID-v1.5.0.exe": "1.5.0",
        "POSID_1.5.0.zip": "1.5.0",
        "POSID Setup 1.5.0.exe": "1.5.0",
        "NuniTrack-v0.9.1.apk": "0.9.1",
        "POSID-final.exe": None,
    }
    for name, expected in cases.items():
        assert extract_version(name) == expected


def test_type_detection():
    assert analyze_filename("POSID-Setup-1.5.0.exe").file_type == "Windows Installer"
    assert analyze_filename("NuniTrack-v0.9.1.apk").file_type == "Android App"
    assert analyze_filename("POSID-1.5.0-source.zip").file_type == "Source Code"
    assert analyze_filename("README.md").file_type == "Documentation"


def test_latest_prefers_stable():
    assert choose_latest(["1.4.0", "1.5.0", "1.6.0-beta1"]) == "1.5.0"
    assert choose_latest(["1.5.0", "1.5.1"]) == "1.5.1"


def test_primary_download():
    items = [
        ("POSID-source-1.5.0.zip", "Source Code"),
        ("POSID-Portable-1.5.0.zip", "Portable"),
        ("POSID-Setup-1.5.0.exe", "Windows Installer"),
    ]
    assert choose_primary(items) == "POSID-Setup-1.5.0.exe"
