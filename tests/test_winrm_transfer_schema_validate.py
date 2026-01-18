# pylint: skip-file
# ruff: noqa: E501
import pytest
from opentaskpy.config.schemas import validate_transfer_json


@pytest.fixture(scope="function")
def valid_protocol_definition_ntlm():
    return {
        "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMTransfer",
        "credentials": {
            "username": "otf",
            "password": "test_password",
            "transport": "ntlm",
        },
    }


@pytest.fixture(scope="function")
def valid_source_ntlm(valid_protocol_definition_ntlm):
    return {
        "hostname": "192.168.1.199",
        "directory": "C:\\data\\source",
        "fileRegex": ".*\\.txt",
        "protocol": valid_protocol_definition_ntlm,
    }


@pytest.fixture(scope="function")
def valid_destination(valid_protocol_definition_ntlm):
    return {
        "hostname": "192.168.1.200",
        "directory": "C:\\data\\dest",
        "protocol": valid_protocol_definition_ntlm,
    }


def test_winrm_transfer_basic(
    valid_protocol_definition_ntlm, valid_source_ntlm, valid_destination
):
    json_data = {
        "type": "transfer",
        "source": valid_source_ntlm,
        "destination": [valid_destination],
    }

    assert validate_transfer_json(json_data)


def test_winrm_transfer_with_conditionals(
    valid_protocol_definition_ntlm, valid_source_ntlm, valid_destination
):
    json_data = {
        "type": "transfer",
        "source": {
            **valid_source_ntlm,
            "conditionals": {
                "size": {"gt": 10, "lt": 1048576},
                "age": {"gt": 60, "lt": 86400},
            },
        },
        "destination": [valid_destination],
        "protocol": valid_protocol_definition_ntlm,
    }

    assert validate_transfer_json(json_data)


def test_winrm_transfer_with_post_copy_action(
    valid_protocol_definition_ntlm, valid_source_ntlm, valid_destination
):
    json_data = {
        "type": "transfer",
        "source": {
            **valid_source_ntlm,
            "postCopyAction": {"action": "move", "destination": "C:\\data\\archive"},
        },
        "destination": [valid_destination],
    }

    assert validate_transfer_json(json_data)


def test_winrm_transfer_with_file_watch(valid_protocol_definition_ntlm):
    json_data = {
        "type": "transfer",
        "source": {
            "hostname": "192.168.1.199",
            "directory": "C:\\data\\source",
            "fileRegex": ".*\\.txt",
            "fileWatch": {
                "timeout": 300,
                "directory": "C:\\data\\source",
                "fileRegex": ".*\\.txt",
            },
            "protocol": valid_protocol_definition_ntlm,
        },
    }

    assert validate_transfer_json(json_data)


def test_winrm_transfer_multiple_destinations(
    valid_protocol_definition_ntlm, valid_source_ntlm, valid_destination
):
    dest2 = {
        "hostname": "192.168.1.201",
        "directory": "C:\\data\\dest2",
        "transferType": "pull",
        "protocol": valid_protocol_definition_ntlm,
    }

    json_data = {
        "type": "transfer",
        "source": valid_source_ntlm,
        "destination": [valid_destination, dest2],
    }

    assert validate_transfer_json(json_data)


def test_winrm_transfer_with_rename(valid_source_ntlm, valid_destination):
    json_data = {
        "type": "transfer",
        "source": valid_source_ntlm,
        "destination": [
            {
                **valid_destination,
                "rename": {"pattern": "^(.*)\\.txt$", "sub": "\\1-processed.txt"},
            }
        ],
    }

    assert validate_transfer_json(json_data)


def test_winrm_transfer_missing_required_fields(valid_protocol_definition_ntlm):
    # Missing source
    json_data = {
        "type": "transfer",
        "destination": [
            {
                "hostname": "192.168.1.200",
                "directory": "C:\\dest",
                "protocol": valid_protocol_definition_ntlm,
            }
        ],
    }
    assert not validate_transfer_json(json_data)

    # Missing destination and no file or filewatch
    json_data = {
        "type": "transfer",
        "source": {
            "hostname": "192.168.1.199",
            "directory": "C:\\source",
            "protocol": {
                "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMTransfer",
                "credentials": {
                    "username": "otf",
                    "password": "test",
                    "transport": "ntlm",
                },
            },
        },
    }
    assert not validate_transfer_json(json_data)


def test_winrm_transfer_invalid_post_copy_action(valid_source_ntlm, valid_destination):
    json_data = {
        "type": "transfer",
        "source": {
            **valid_source_ntlm,
            "postCopyAction": {
                "action": "invalid_action",
                "destination": "C:\\archive",
            },
        },
        "destination": [valid_destination],
    }

    assert not validate_transfer_json(json_data)


def test_winrm_transfer_invalid_transfer_type(valid_source_ntlm, valid_destination):
    json_data = {
        "type": "transfer",
        "source": valid_source_ntlm,
        "destination": [{**valid_destination, "transferType": "invalid_type"}],
    }

    assert not validate_transfer_json(json_data)
