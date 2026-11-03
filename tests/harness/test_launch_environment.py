from studio_client.harness.probe import launch_environment


def test_launch_environment_preserves_windows_variables_case_insensitively() -> None:
    source = {
        "SYSTEMDRIVE": "C:",
        "SYSTEMROOT": "C:/Windows",
        "programdata": "C:/ProgramData",
        "Path": "C:/bin",
        "APPDATA": "C:/isolated/config",
        "STUDIO_CLIENT_MACHINE_TOKEN": "daemon-secret",
        "OPENCODE_PERMISSION": '{"external_directory":"allow"}',
        "AWS_SECRET_ACCESS_KEY": "cloud-secret",
    }
    assert launch_environment(source) == {
        "SYSTEMDRIVE": "C:",
        "SYSTEMROOT": "C:/Windows",
        "programdata": "C:/ProgramData",
        "Path": "C:/bin",
        "APPDATA": "C:/isolated/config",
    }
