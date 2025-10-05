# pylint: skip-file
import pytest
from opentaskpy.config.schemas import validate_execution_json


@pytest.fixture(scope="function")
def valid_protocol_definition_ntlm():
    return {
        "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
        "credentials": {
            "username": "otf",
            "password": "test_password",
            "transport": "ntlm",
        },
    }


@pytest.fixture(scope="function")
def valid_protocol_definition_certificate():
    return {
        "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
        "credentials": {
            "username": "otf",
            "transport": "certificate",
            "cert_pem": "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
            "cert_key_pem": (
                "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----"
            ),
        },
    }


@pytest.fixture(scope="function")
def valid_execution_ntlm(valid_protocol_definition_ntlm):
    return {
        "hostname": "192.168.1.199",
        "directory": "C:\\temp",
        "command": "Get-ChildItem",
        "protocol": valid_protocol_definition_ntlm,
    }


@pytest.fixture(scope="function")
def valid_execution_certificate(valid_protocol_definition_certificate):
    return {
        "hostname": "192.168.1.199",
        "directory": "C:\\scripts",
        "command": ".\\test.ps1",
        "protocol": valid_protocol_definition_certificate,
    }


def test_winrm_ntlm_basic(valid_execution_ntlm):
    json_data = {
        "type": "execution",
    }
    # Append properties from valid_execution_ntlm onto json_data
    json_data.update(valid_execution_ntlm)

    assert validate_execution_json(json_data)

    # Add server_cert_validation
    json_data["protocol"]["server_cert_validation"] = "ignore"
    assert validate_execution_json(json_data)

    # Change to validate
    json_data["protocol"]["server_cert_validation"] = "validate"
    assert validate_execution_json(json_data)

    # Add custom port
    json_data["protocol"]["credentials"]["port"] = 5985
    assert validate_execution_json(json_data)

    # Remove password (should fail for ntlm)
    del json_data["protocol"]["credentials"]["password"]
    assert not validate_execution_json(json_data)


def test_winrm_certificate_auth(valid_execution_certificate):
    json_data = {
        "type": "execution",
    }
    json_data.update(valid_execution_certificate)

    assert validate_execution_json(json_data)

    # Add server_cert_validation
    json_data["protocol"]["server_cert_validation"] = "ignore"
    assert validate_execution_json(json_data)

    # Remove cert_pem (should fail)
    del json_data["protocol"]["credentials"]["cert_pem"]
    assert not validate_execution_json(json_data)


def test_winrm_basic_auth(valid_execution_ntlm):
    json_data = {
        "type": "execution",
    }
    json_data.update(valid_execution_ntlm)

    # Change transport to basic
    json_data["protocol"]["credentials"]["transport"] = "basic"
    assert validate_execution_json(json_data)

    # Change to ssl
    json_data["protocol"]["credentials"]["transport"] = "ssl"
    assert validate_execution_json(json_data)


def test_winrm_missing_required_fields(valid_execution_ntlm):
    json_data = {
        "type": "execution",
    }
    json_data.update(valid_execution_ntlm)

    # Remove hostname (should fail)
    del json_data["hostname"]
    assert not validate_execution_json(json_data)

    # Restore hostname, remove command (should fail)
    json_data["hostname"] = "192.168.1.199"
    del json_data["command"]
    assert not validate_execution_json(json_data)

    # Restore command, remove protocol (should fail)
    json_data["command"] = "Get-ChildItem"
    del json_data["protocol"]
    assert not validate_execution_json(json_data)


def test_winrm_invalid_transport():
    json_data = {
        "type": "execution",
        "hostname": "192.168.1.199",
        "command": "Get-ChildItem",
        "protocol": {
            "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
            "credentials": {
                "username": "otf",
                "password": "test",
                "transport": "invalid_transport",
            },
        },
    }

    assert not validate_execution_json(json_data)


def test_winrm_optional_directory(valid_execution_ntlm):
    json_data = {
        "type": "execution",
    }
    json_data.update(valid_execution_ntlm)

    # Remove directory (should still be valid as it's optional)
    del json_data["directory"]
    assert validate_execution_json(json_data)


def test_winrm_certificate_missing_cert():
    """Test that certificate transport requires cert_pem."""
    json_data = {
        "type": "execution",
        "hostname": "192.168.1.199",
        "command": "Get-ChildItem",
        "protocol": {
            "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
            "credentials": {
                "username": "otf",
                "transport": "certificate",
                # Missing cert_pem and cert_key_pem
            },
        },
    }

    assert not validate_execution_json(json_data)


def test_winrm_certificate_missing_key():
    """Test that certificate transport requires cert_key_pem."""
    json_data = {
        "type": "execution",
        "hostname": "192.168.1.199",
        "command": "Get-ChildItem",
        "protocol": {
            "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
            "credentials": {
                "username": "otf",
                "transport": "certificate",
                "cert_pem": (
                    "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----"
                ),
                # Missing cert_key_pem
            },
        },
    }

    assert not validate_execution_json(json_data)


def test_winrm_ntlm_missing_password():
    """Test that ntlm transport requires password."""
    json_data = {
        "type": "execution",
        "hostname": "192.168.1.199",
        "command": "Get-ChildItem",
        "protocol": {
            "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
            "credentials": {
                "username": "otf",
                "transport": "ntlm",
                # Missing password
            },
        },
    }

    assert not validate_execution_json(json_data)


def test_winrm_basic_missing_password():
    """Test that basic transport requires password."""
    json_data = {
        "type": "execution",
        "hostname": "192.168.1.199",
        "command": "Get-ChildItem",
        "protocol": {
            "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
            "credentials": {
                "username": "otf",
                "transport": "basic",
                # Missing password
            },
        },
    }

    assert not validate_execution_json(json_data)


def test_winrm_ssl_missing_password():
    """Test that ssl transport requires password."""
    json_data = {
        "type": "execution",
        "hostname": "192.168.1.199",
        "command": "Get-ChildItem",
        "protocol": {
            "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
            "credentials": {
                "username": "otf",
                "transport": "ssl",
                # Missing password
            },
        },
    }

    assert not validate_execution_json(json_data)
