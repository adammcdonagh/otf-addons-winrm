# pylint: skip-file
# ruff: noqa: E501
import os
import random
import tempfile

import pytest
from dotenv import load_dotenv
from opentaskpy.taskhandlers import transfer
from winrm.protocol import Protocol

os.environ["OTF_NO_LOG"] = "1"
os.environ["OTF_LOG_LEVEL"] = "DEBUG"


@pytest.fixture(scope="function")
def credentials():
    """Load WinRM credentials from .env file."""
    if "GITHUB_ACTIONS" not in os.environ:
        current_dir = os.path.dirname(os.path.realpath(__file__))
        load_dotenv(dotenv_path=f"{current_dir}/../.env")

    return {
        "hostname": os.getenv("WINRM_HOSTNAME"),
        "username": os.getenv("WINRM_USERNAME"),
        "password": os.getenv("WINRM_PASSWORD"),
    }


@pytest.fixture(scope="function")
def winrm_client(credentials):
    """Create a WinRM client for test setup/teardown."""
    client = Protocol(
        endpoint=f"https://{credentials['hostname']}:5986/wsman",
        transport="ntlm",
        username=credentials["username"],
        password=credentials["password"],
        server_cert_validation="ignore",
    )
    return client


@pytest.fixture(scope="function")
def remote_test_dir(winrm_client):
    """Create a temporary directory on the Windows machine for testing."""
    test_dir = f"C:\\temp\\otf_test_{random.randint(10000, 99999)}"

    # Create the directory structure
    shell_id = winrm_client.open_shell()
    try:
        create_command = f"""New-Item -ItemType Directory -Path '{test_dir}\\src' -Force | Out-Null
                New-Item -ItemType Directory -Path '{test_dir}\\dest' -Force | Out-Null
                New-Item -ItemType Directory -Path '{test_dir}\\archive' -Force | Out-Null
        """
        ps_command = f'powershell.exe -Command "{create_command}"'
        command_id = winrm_client.run_command(shell_id, ps_command)
        _, _, return_code = winrm_client.get_command_output(shell_id, command_id)

        if return_code != 0:
            raise Exception(f"Failed to create test directory: {test_dir}")
    finally:
        winrm_client.close_shell(shell_id)

    yield test_dir

    # Cleanup - remove the directory
    shell_id = winrm_client.open_shell("powershell")
    try:
        ps_command = f"Remove-Item -Path '{test_dir}' -Recurse -Force"
        command_id = winrm_client.run_command(shell_id, ps_command)
        winrm_client.get_command_output(shell_id, command_id)
    finally:
        winrm_client.close_shell(shell_id)


@pytest.fixture(scope="function")
def local_test_dir():
    """Create a temporary local directory for testing."""
    temp_dir = tempfile.mkdtemp(prefix="otf_winrm_test_")
    os.makedirs(f"{temp_dir}/src", exist_ok=True)
    os.makedirs(f"{temp_dir}/dest", exist_ok=True)

    yield temp_dir

    # Cleanup
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


def create_remote_file(winrm_client, file_path, content="test content"):
    """Helper function to create a file on the remote Windows machine."""
    import base64

    encoded_content = base64.b64encode(content.encode()).decode()

    # Ensure directory exists
    remote_dir = "\\".join(file_path.split("\\")[:-1])

    shell_id = winrm_client.open_shell("powershell")
    try:
        create_command = f"""
        if (!(Test-Path '{remote_dir}')) {{
            New-Item -ItemType Directory -Path '{remote_dir}' -Force | Out-Null
        }}
        $content = [System.Convert]::FromBase64String('{encoded_content}')
        [System.IO.File]::WriteAllBytes('{file_path}', $content)
        """
        ps_command = f'powershell.exe -Command "{create_command}"'
        command_id = winrm_client.run_command(shell_id, ps_command)
        _, stderr, return_code = winrm_client.get_command_output(shell_id, command_id)

        if return_code != 0:
            raise Exception(f"Failed to create file: {stderr.decode()}")
    finally:
        winrm_client.close_shell(shell_id)


def check_remote_file_exists(winrm_client, file_path):
    """Helper function to check if a file exists on the remote Windows machine."""
    shell_id = winrm_client.open_shell("powershell")
    try:
        create_command = f"Test-Path '{file_path}'"
        ps_command = f'powershell.exe -Command "{create_command}"'
        command_id = winrm_client.run_command(shell_id, ps_command)
        stdout, _, return_code = winrm_client.get_command_output(shell_id, command_id)

        if return_code == 0:
            return "True" in stdout.decode()
        return False
    finally:
        winrm_client.close_shell(shell_id)


def get_remote_file_content(winrm_client, file_path):
    """Helper function to read file content from remote Windows machine."""
    shell_id = winrm_client.open_shell("powershell")
    try:
        create_command = f"""
        $content = Get-Content -Path '{file_path}' -Raw -Encoding Byte
        [System.Convert]::ToBase64String($content)
        """
        ps_command = f'powershell.exe -Command "{create_command}"'
        command_id = winrm_client.run_command(shell_id, ps_command)
        stdout, _, return_code = winrm_client.get_command_output(shell_id, command_id)

        if return_code == 0:
            import base64

            return base64.b64decode(stdout.decode().strip()).decode()
        return None
    finally:
        winrm_client.close_shell(shell_id)


def test_winrm_pull_basic(credentials, winrm_client, remote_test_dir, local_test_dir):
    """Test pulling a file from Windows to local system."""
    # Create a test file on the remote system
    remote_file = f"{remote_test_dir}\\src\\test_pull.txt"
    # THIUS DOES NOT APPEAR TO ACTUALLY BE CREATING THE FILE, only the directoryme
    create_remote_file(winrm_client, remote_file, "test content for pull")

    # Create transfer definition
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": credentials["hostname"],
            "directory": f"{remote_test_dir}\\src",
            "fileRegex": "test_pull\\.txt",
            "protocol": {
                "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMTransfer",
                "server_cert_validation": "ignore",
                "credentials": {
                    "transport": "ntlm",
                    "username": credentials["username"],
                    "password": credentials["password"],
                },
            },
        },
        "destination": [
            {
                "hostname": "localhost",
                "directory": f"{local_test_dir}/dest",
                "protocol": {"name": "local"},
            }
        ],
    }

    # Create and run transfer
    transfer_obj = transfer.Transfer(None, "winrm-pull-basic", transfer_definition)
    assert transfer_obj.run()

    # Verify file was transferred
    local_file = f"{local_test_dir}/dest/test_pull.txt"
    assert os.path.exists(local_file)

    with open(local_file) as f:
        assert f.read() == "test content for pull"


def test_winrm_push_basic(credentials, winrm_client, remote_test_dir, local_test_dir):
    """Test pushing a file from local system to Windows."""
    # Create a local test file
    local_file = f"{local_test_dir}/src/test_push.txt"
    with open(local_file, "w") as f:
        f.write("test content for push")

    # Create transfer definition
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": "localhost",
            "directory": f"{local_test_dir}/src",
            "fileRegex": "test_push\\.txt",
            "protocol": {"name": "local"},
        },
        "destination": [
            {
                "hostname": credentials["hostname"],
                "directory": f"{remote_test_dir}\\dest",
                "protocol": {
                    "name": (
                        "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMTransfer"
                    ),
                    "server_cert_validation": "ignore",
                    "credentials": {
                        "transport": "ntlm",
                        "username": credentials["username"],
                        "password": credentials["password"],
                    },
                },
            }
        ],
    }

    # Create and run transfer
    transfer_obj = transfer.Transfer(None, "winrm-push-basic", transfer_definition)
    assert transfer_obj.run()

    # Verify file was transferred
    remote_file = f"{remote_test_dir}\\dest\\test_push.txt"
    assert check_remote_file_exists(winrm_client, remote_file)

    content = get_remote_file_content(winrm_client, remote_file)
    assert content == "test content for push"


def test_winrm_pull_with_pca_move(
    credentials, winrm_client, remote_test_dir, local_test_dir
):
    """Test pulling a file with post-copy action (move)."""
    # Create test file on remote
    remote_file = f"{remote_test_dir}\\src\\test_pca_move.txt"
    create_remote_file(winrm_client, remote_file, "test pca move content")

    # Create transfer definition with PCA
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": credentials["hostname"],
            "directory": f"{remote_test_dir}\\src",
            "fileRegex": "test_pca_move\\.txt",
            "postCopyAction": {
                "action": "move",
                "destination": f"{remote_test_dir}\\archive",
            },
            "protocol": {
                "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMTransfer",
                "server_cert_validation": "ignore",
                "credentials": {
                    "transport": "ntlm",
                    "username": credentials["username"],
                    "password": credentials["password"],
                },
            },
        },
        "destination": [
            {
                "hostname": "localhost",
                "directory": f"{local_test_dir}/dest",
                "protocol": {"name": "local"},
            }
        ],
    }

    # Run transfer
    transfer_obj = transfer.Transfer(None, "winrm-pca-move", transfer_definition)
    assert transfer_obj.run()

    # Verify file was transferred
    assert os.path.exists(f"{local_test_dir}/dest/test_pca_move.txt")

    # Verify source file was moved to archive
    assert not check_remote_file_exists(winrm_client, remote_file)
    assert check_remote_file_exists(
        winrm_client, f"{remote_test_dir}\\archive\\test_pca_move.txt"
    )


def test_winrm_pull_with_pca_delete(
    credentials, winrm_client, remote_test_dir, local_test_dir
):
    """Test pulling a file with post-copy action (delete)."""
    # Create test file on remote
    remote_file = f"{remote_test_dir}\\src\\test_pca_delete.txt"
    create_remote_file(winrm_client, remote_file, "test pca delete content")

    # Create transfer definition with PCA
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": credentials["hostname"],
            "directory": f"{remote_test_dir}\\src",
            "fileRegex": "test_pca_delete\\.txt",
            "postCopyAction": {
                "action": "delete",
            },
            "protocol": {
                "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMTransfer",
                "server_cert_validation": "ignore",
                "credentials": {
                    "transport": "ntlm",
                    "username": credentials["username"],
                    "password": credentials["password"],
                },
            },
        },
        "destination": [
            {
                "hostname": "localhost",
                "directory": f"{local_test_dir}/dest",
                "protocol": {"name": "local"},
            }
        ],
    }

    # Run transfer
    transfer_obj = transfer.Transfer(None, "winrm-pca-delete", transfer_definition)
    assert transfer_obj.run()

    # Verify file was transferred
    assert os.path.exists(f"{local_test_dir}/dest/test_pca_delete.txt")

    # Verify source file was deleted
    assert not check_remote_file_exists(winrm_client, remote_file)


def test_winrm_pull_with_conditionals(
    credentials, winrm_client, remote_test_dir, local_test_dir
):
    """Test pulling files with size and age conditionals."""
    # Create test files with different sizes
    small_file = f"{remote_test_dir}\\src\\test_small.txt"
    large_file = f"{remote_test_dir}\\src\\test_large.txt"

    create_remote_file(winrm_client, small_file, "small")  # 5 bytes
    create_remote_file(winrm_client, large_file, "x" * 100)  # 100 bytes

    # Create transfer definition with size conditionals
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": credentials["hostname"],
            "directory": f"{remote_test_dir}\\src",
            "fileRegex": "test_.*\\.txt",
            "conditionals": {
                "size": {
                    "gt": 10,  # Greater than 10 bytes
                    "lt": 200,  # Less than 200 bytes
                }
            },
            "protocol": {
                "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMTransfer",
                "server_cert_validation": "ignore",
                "credentials": {
                    "transport": "ntlm",
                    "username": credentials["username"],
                    "password": credentials["password"],
                },
            },
        },
        "destination": [
            {
                "hostname": "localhost",
                "directory": f"{local_test_dir}/dest",
                "protocol": {"name": "local"},
            }
        ],
    }

    # Run transfer
    transfer_obj = transfer.Transfer(None, "winrm-conditionals", transfer_definition)
    assert transfer_obj.run()

    # Verify only large file was transferred (meets size conditions)
    assert not os.path.exists(f"{local_test_dir}/dest/test_small.txt")
    assert os.path.exists(f"{local_test_dir}/dest/test_large.txt")


def test_winrm_push_with_rename(
    credentials, winrm_client, remote_test_dir, local_test_dir
):
    """Test pushing a file with destination rename."""
    # Create local test file
    local_file = f"{local_test_dir}/src/test_rename.txt"
    with open(local_file, "w") as f:
        f.write("test rename content")

    # Create transfer definition with rename
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": "localhost",
            "directory": f"{local_test_dir}/src",
            "fileRegex": "test_rename\\.txt",
            "protocol": {"name": "local"},
        },
        "destination": [
            {
                "hostname": credentials["hostname"],
                "directory": f"{remote_test_dir}\\dest",
                "rename": {
                    "pattern": "rename",
                    "sub": "RENAMED",
                },
                "protocol": {
                    "name": (
                        "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMTransfer"
                    ),
                    "server_cert_validation": "ignore",
                    "credentials": {
                        "transport": "ntlm",
                        "username": credentials["username"],
                        "password": credentials["password"],
                    },
                },
            }
        ],
    }

    # Run transfer
    transfer_obj = transfer.Transfer(None, "winrm-rename", transfer_definition)
    assert transfer_obj.run()

    # Verify file was transferred with new name
    assert check_remote_file_exists(
        winrm_client, f"{remote_test_dir}\\dest\\test_RENAMED.txt"
    )


def test_winrm_pull_multiple_files(
    credentials, winrm_client, remote_test_dir, local_test_dir
):
    """Test pulling multiple files matching a pattern."""
    # Create multiple test files on remote
    for i in range(1, 4):
        remote_file = f"{remote_test_dir}\\src\\multi_{i}.txt"
        create_remote_file(winrm_client, remote_file, f"content {i}")

    # Create transfer definition
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": credentials["hostname"],
            "directory": f"{remote_test_dir}\\src",
            "fileRegex": "multi_.*\\.txt",
            "protocol": {
                "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMTransfer",
                "server_cert_validation": "ignore",
                "credentials": {
                    "transport": "ntlm",
                    "username": credentials["username"],
                    "password": credentials["password"],
                },
            },
        },
        "destination": [
            {
                "hostname": "localhost",
                "directory": f"{local_test_dir}/dest",
                "protocol": {"name": "local"},
            }
        ],
    }

    # Run transfer
    transfer_obj = transfer.Transfer(None, "winrm-multi", transfer_definition)
    assert transfer_obj.run()

    # Verify all files were transferred
    for i in range(1, 4):
        assert os.path.exists(f"{local_test_dir}/dest/multi_{i}.txt")


def test_winrm_create_dest_directory(
    credentials, winrm_client, remote_test_dir, local_test_dir
):
    """Test that destination directory is created if it doesn't exist."""
    # Create local test file
    local_file = f"{local_test_dir}/src/test_create_dir.txt"
    with open(local_file, "w") as f:
        f.write("test create dir content")

    # Use a non-existent destination directory
    new_dest_dir = f"{remote_test_dir}\\new_dest_{random.randint(1000, 9999)}"

    # Create transfer definition
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": "localhost",
            "directory": f"{local_test_dir}/src",
            "fileRegex": "test_create_dir\\.txt",
            "protocol": {"name": "local"},
        },
        "destination": [
            {
                "hostname": credentials["hostname"],
                "directory": new_dest_dir,
                "createDirectoryIfNotExists": True,
                "protocol": {
                    "name": (
                        "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMTransfer"
                    ),
                    "server_cert_validation": "ignore",
                    "credentials": {
                        "transport": "ntlm",
                        "username": credentials["username"],
                        "password": credentials["password"],
                    },
                },
            }
        ],
    }

    # Run transfer
    transfer_obj = transfer.Transfer(None, "winrm-create-dir", transfer_definition)
    assert transfer_obj.run()

    # Verify file was transferred and directory was created
    assert check_remote_file_exists(
        winrm_client, f"{new_dest_dir}\\test_create_dir.txt"
    )
