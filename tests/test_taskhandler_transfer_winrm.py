# pylint: skip-file
# ruff: noqa: E501 T201
import os
import random
import tempfile
import threading

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


# def create_remote_file(winrm_client, file_path, content="test content"):
#     """Helper function to create a file on the remote Windows machine using Ansible's approach."""
#     import base64

#     import xmltodict

#     # Ensure directory exists
#     remote_dir = "\\".join(file_path.split("\\")[:-1])

#     # PowerShell script that reads base64 from stdin pipeline and writes to file
#     ps_script = f"""
# $input | ForEach-Object {{
#     if (!(Test-Path '{remote_dir}')) {{
#         New-Item -ItemType Directory -Path '{remote_dir}' -Force | Out-Null
#     }}
#     $bytes = [System.Convert]::FromBase64String($_)
#     [System.IO.File]::WriteAllBytes('{file_path}', $bytes)
# }}
# """

#     ps_command = f'powershell.exe -Command "{ps_script}"'

#     shell_id = winrm_client.open_shell()
#     try:
#         # Run the command
#         command_id = winrm_client.run_command(shell_id, ps_command)

#         # Send base64-encoded content via stdin using the proper WinRM method
#         # Build the SOAP message for sending input (Ansible's _winrm_send_input approach)
#         rq = {
#             "env:Envelope": winrm_client._get_soap_header(
#                 resource_uri="http://schemas.microsoft.com/wbem/wsman/1/windows/shell/cmd",
#                 action="http://schemas.microsoft.com/wbem/wsman/1/windows/shell/Send",
#                 shell_id=shell_id,
#             )
#         }
#         stream = (
#             rq["env:Envelope"]
#             .setdefault("env:Body", {})
#             .setdefault("rsp:Send", {})
#             .setdefault("rsp:Stream", {})
#         )
#         stream["@Name"] = "stdin"
#         stream["@CommandId"] = command_id
#         # The content needs to be base64 encoded once for the SOAP transport
#         stream["#text"] = base64.b64encode(content.encode())
#         stream["@End"] = "true"

#         winrm_client.send_message(xmltodict.unparse(rq))

#         # Get the output
#         stdout, stderr, return_code = winrm_client.get_command_output(
#             shell_id, command_id
#         )

#         if return_code != 0:
#             raise Exception(
#                 f"Failed to create file (rc={return_code}): {stderr.decode()}"
#             )

#     finally:
#         winrm_client.close_shell(shell_id)


def create_remote_file(winrm_client, file_path, content="test content"):
    """Helper function to create a file on the remote Windows machine."""
    import base64

    # Ensure directory exists
    remote_dir = "\\".join(file_path.split("\\")[:-1])

    # Encode content as base64
    encoded_content = base64.b64encode(content.encode()).decode()

    # Simple single-line PowerShell
    ps_script = (
        "$remoteDirVar = $args[0]; "
        "$filePathVar = $args[1]; "
        "$encodedContent = $args[2]; "
        "if (!(Test-Path $remoteDirVar)) { "
        "  New-Item -ItemType Directory -Path $remoteDirVar -Force | Out-Null "
        "}; "
        "$bytes = [System.Convert]::FromBase64String($encodedContent); "
        "[System.IO.File]::WriteAllBytes($filePathVar, $bytes)"
    )

    ps_command = f"powershell.exe -Command \"& {{ {ps_script} }} '{remote_dir}' '{file_path}' '{encoded_content}'\""

    shell_id = winrm_client.open_shell()
    try:
        command_id = winrm_client.run_command(shell_id, ps_command)
        stdout, stderr, return_code = winrm_client.get_command_output(
            shell_id, command_id
        )

        if return_code != 0:
            raise Exception(
                f"Failed to create file (rc={return_code}): {stderr.decode()}"
            )

    finally:
        winrm_client.close_shell(shell_id)


def check_remote_file_exists(winrm_client, file_path):
    """Helper function to check if a file exists on the remote Windows machine."""
    ps_script = "$filePath = $args[0]; Test-Path $filePath"
    ps_command = f"powershell.exe -Command \"& {{ {ps_script} }} '{file_path}'\""

    shell_id = winrm_client.open_shell()
    try:
        command_id = winrm_client.run_command(shell_id, ps_command)
        stdout, _, return_code = winrm_client.get_command_output(shell_id, command_id)

        if return_code == 0:
            return "True" in stdout.decode()
        return False
    finally:
        winrm_client.close_shell(shell_id)


def get_remote_file_content(winrm_client, file_path):
    """Helper function to read file content from remote Windows machine."""
    import base64

    # Use argument-based approach that we know works
    ps_script = (
        "$filePath = $args[0]; "
        "$content = [System.IO.File]::ReadAllBytes($filePath); "
        "[System.Convert]::ToBase64String($content)"
    )
    ps_command = f"powershell.exe -Command \"& {{ {ps_script} }} '{file_path}'\""

    shell_id = winrm_client.open_shell()
    try:
        command_id = winrm_client.run_command(shell_id, ps_command)
        stdout, stderr, return_code = winrm_client.get_command_output(
            shell_id, command_id
        )

        if return_code == 0 and stdout:
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


def test_winrm_filewatch_no_error(credentials, remote_test_dir):
    """Test filewatch that times out without error when no files found."""
    # Create transfer definition with filewatch and error=False
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": credentials["hostname"],
            "directory": f"{remote_test_dir}\\src",
            "fileRegex": ".*nofileexists.*\\.txt",
            "fileWatch": {"timeout": 1},
            "error": False,
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
    }

    # Run transfer - should succeed even though no files found
    transfer_obj = transfer.Transfer(
        None, "winrm-filewatch-no-error", transfer_definition
    )
    assert transfer_obj.run()


def test_winrm_filewatch_with_counts(
    credentials, winrm_client, remote_test_dir, local_test_dir
):
    """Test filewatch with count conditionals."""
    # Create test files on remote
    create_remote_file(
        winrm_client, f"{remote_test_dir}\\src\\counts_watch1.txt", "test1234"
    )
    create_remote_file(
        winrm_client, f"{remote_test_dir}\\src\\counts_watch2.txt", "test1234"
    )

    # Create transfer definition with filewatch and count conditionals
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": credentials["hostname"],
            "directory": f"{remote_test_dir}\\src",
            "fileRegex": "counts_watch[0-9]\\.txt",
            "fileWatch": {"timeout": 5},
            "conditionals": {
                "count": {
                    "minCount": 2,
                    "maxCount": 2,
                },
                "checkDuringFilewatch": True,
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
    transfer_obj = transfer.Transfer(
        None, "winrm-filewatch-counts", transfer_definition
    )
    assert transfer_obj.run()

    # Verify files were transferred
    assert os.path.exists(f"{local_test_dir}/dest/counts_watch1.txt")
    assert os.path.exists(f"{local_test_dir}/dest/counts_watch2.txt")


def test_winrm_filewatch_counts_error(
    credentials, winrm_client, remote_test_dir, local_test_dir
):
    """Test filewatch with count conditionals that should fail."""
    from opentaskpy import exceptions

    # Test 1: Create only 1 file when minCount is 2
    create_remote_file(
        winrm_client, f"{remote_test_dir}\\src\\counts_watch_error1.txt", "test1234"
    )

    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": credentials["hostname"],
            "directory": f"{remote_test_dir}\\src",
            "fileRegex": "counts_watch_error[0-9]\\.txt",
            "fileWatch": {"timeout": 5},
            "conditionals": {
                "count": {
                    "minCount": 2,
                    "maxCount": 2,
                },
                "checkDuringFilewatch": True,
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

    # Run transfer - should fail due to minCount not met
    transfer_obj = transfer.Transfer(
        None, "winrm-filewatch-counts-error-min", transfer_definition
    )
    with pytest.raises(exceptions.RemoteFileNotFoundError):
        transfer_obj.run()

    # Test 2: Create 3 files when maxCount is 2
    create_remote_file(
        winrm_client, f"{remote_test_dir}\\src\\counts_watch_error2.txt", "test1234"
    )
    create_remote_file(
        winrm_client, f"{remote_test_dir}\\src\\counts_watch_error3.txt", "test1234"
    )

    # Run transfer - should fail due to maxCount exceeded
    transfer_obj = transfer.Transfer(
        None, "winrm-filewatch-counts-error-max", transfer_definition
    )
    with pytest.raises(exceptions.RemoteFileNotFoundError):
        transfer_obj.run()


def test_winrm_filewatch_delayed_file_creation(
    credentials, winrm_client, remote_test_dir, local_test_dir
):
    """Test filewatch that waits for a file to appear during the watch period."""
    # First verify that filewatch fails when file doesn't exist
    transfer_definition = {
        "type": "transfer",
        "source": {
            "hostname": credentials["hostname"],
            "directory": f"{remote_test_dir}\\src",
            "fileRegex": "delayed_file\\.txt",
            "fileWatch": {"timeout": 15},  # Wait up to 15 seconds
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

    # Helper function to create the file after a delay
    def create_delayed_file():
        import time

        time.sleep(1)  # Small delay to ensure transfer has started
        create_remote_file(
            winrm_client,
            f"{remote_test_dir}\\src\\delayed_file.txt",
            "delayed content",
        )
        print(f"Created delayed file at {remote_test_dir}\\src\\delayed_file.txt")

    # Start a thread that will create the file after 5 seconds
    t = threading.Timer(5, create_delayed_file)
    t.start()

    # Run transfer - should succeed because file will be created during filewatch
    transfer_obj = transfer.Transfer(
        None, "winrm-filewatch-delayed", transfer_definition
    )
    assert transfer_obj.run()

    # Wait for thread to complete
    t.join()

    # Verify file was transferred
    assert os.path.exists(f"{local_test_dir}/dest/delayed_file.txt")
    with open(f"{local_test_dir}/dest/delayed_file.txt") as f:
        assert f.read() == "delayed content"
