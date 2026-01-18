# pylint: disable=no-name-in-module
"""Windows remote handler."""

import base64
import glob
import logging
import ntpath
import os
import random
import re
import tempfile

import opentaskpy.otflogging
import xmltodict
from opentaskpy.remotehandlers.remotehandler import (
    RemoteExecutionHandler,
    RemoteTransferHandler,
)
from winrm.exceptions import WinRMOperationTimeoutError
from winrm.protocol import Protocol  # pylint: disable=no-name-in-module


class WinRMBase:
    """Base class for WinRM handlers providing shared authentication logic."""

    winrm_protocol_client: Protocol
    _cert_file: tempfile._TemporaryFileWrapper | None = None
    _key_file: tempfile._TemporaryFileWrapper | None = None
    spec: dict
    remote_host: str

    def _initialize_winrm_client(self) -> None:
        """Initialize the WinRM protocol client based on spec configuration."""
        # Determine the kwargs for the WinRM client based on the options passed in the spec
        kwargs = {}
        kwargs["endpoint"] = (
            f"https://{self.spec['hostname']}:{self.spec['protocol']['credentials'].get('port', '5986')}/wsman"
        )
        kwargs["username"] = self.spec["protocol"]["credentials"]["username"]
        kwargs["transport"] = self.spec["protocol"]["credentials"]["transport"]
        kwargs["server_cert_validation"] = self.spec["protocol"].get(
            "server_cert_validation", "validate"
        )

        # Handle password-based authentication (ntlm, basic, ssl)
        if self.spec["protocol"]["credentials"]["transport"] in [
            "ntlm",
            "basic",
            "ssl",
        ]:
            kwargs["password"] = self.spec["protocol"]["credentials"]["password"]

        # Handle certificate-based authentication
        if self.spec["protocol"]["credentials"]["transport"] == "certificate":
            cert_data = self.spec["protocol"]["credentials"]["cert_pem"]
            key_data = self.spec["protocol"]["credentials"]["cert_key_pem"]

            # Create temporary files that persist for the life of this object
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, suffix=".pem"
            ) as cert_file:
                cert_file.write(cert_data.encode())
                cert_file.flush()
                self._cert_file = cert_file

            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, suffix=".pem"
            ) as key_file:
                key_file.write(key_data.encode())
                key_file.flush()
                self._key_file = key_file

            kwargs["cert_pem"] = self._cert_file.name
            kwargs["cert_key_pem"] = self._key_file.name

        self.winrm_protocol_client = Protocol(**kwargs)

    def _cleanup_temp_files(self) -> None:
        """Clean up temporary certificate files."""
        if self._cert_file:
            self._cert_file.close()
        if self._key_file:
            self._key_file.close()


class WinRMTransfer(WinRMBase, RemoteTransferHandler):
    """WinRM remote transfer handler.

    Allows file transfers to/from Windows machines via WinRM.
    """

    TASK_TYPE = "T"

    def __init__(self, spec: dict):
        """Initialise the WinRMTransfer handler.

        Args:
            spec (dict): The spec for the transfer.
        """
        self.spec = spec
        self.remote_host = spec["hostname"]

        self.logger = opentaskpy.otflogging.init_logging(
            __name__, spec["task_id"], self.TASK_TYPE
        )

        self._initialize_winrm_client()

        super().__init__(spec)

    def list_files(
        self,
        directory: str | None = None,
        file_pattern: str | None = None,
    ) -> dict:
        """List files in a directory with optional filtering.

        Args:
            directory (str): Directory to list files from
            file_pattern (str): File pattern to match (PowerShell wildcard syntax)

        Returns:
            dict: Dictionary of files with path as key and metadata as value
        """
        if directory is None:
            directory = str(self.spec.get("directory", "."))
        if file_pattern is None:
            file_pattern = str(self.spec.get("fileRegex", "*"))

        # Escape single quotes in the pattern for PowerShell
        safe_pattern = file_pattern.replace("'", "''")
        safe_directory = directory.replace("'", "''")

        # Build PowerShell command that worked
        ps_script = (
            "$dir = $args[0]; "
            "$pattern = $args[1]; "
            "Get-ChildItem -Path $dir -File | Where-Object { $_.Name -match $pattern } | ForEach-Object { "
            "  $age_seconds = [int]((Get-Date) - $_.LastWriteTime).TotalSeconds; "
            "  $size_bytes = [long]$_.Length; "
            "  Write-Host ($_.Name + '|' + $_.FullName + '|' + $size_bytes + '|' + $age_seconds) "
            "}"
        )

        ps_command = f"powershell.exe -Command \"& {{ {ps_script} }} '{safe_directory}' '{safe_pattern}'\""

        shell_id = self.winrm_protocol_client.open_shell()
        try:
            command_id = self.winrm_protocol_client.run_command(shell_id, ps_command)
            stdout, stderr, return_code = self.winrm_protocol_client.get_command_output(
                shell_id, command_id
            )

            if return_code != 0:
                self.logger.error(
                    f"[{self.remote_host}] Failed to list files: {stderr.decode('utf-8', errors='replace')}"
                )
                return {}

            files = {}
            for line in stdout.decode("utf-8", errors="replace").strip().split("\n"):
                if "|" in line:
                    _, full_path, size_str, age_str = line.split("|", 3)
                    try:
                        size = int(size_str)
                        age = int(age_str)

                        # OTF doesn't support backslashes in file keys, so convert to forward slashes
                        full_path = full_path.replace("\\", "/")

                        files[full_path] = {
                            "size": size,
                            "modified_time": age,
                        }
                    except (ValueError, IndexError):
                        continue

            return files

        finally:
            self.winrm_protocol_client.close_shell(shell_id)

    def pull_file(self, remote_file: str, local_file: str) -> bool:
        """Pull a file from the remote Windows machine.

        Args:
            remote_file (str): Remote file path
            local_file (str): Local file path

        Returns:
            bool: True if successful
        """
        # For WinRM, we need to read the file content and write it locally
        # This is less efficient than SCP but works over WinRM

        ps_script = f"try {{ $content = Get-Content -Path '{remote_file}' -Raw -Encoding Byte; [System.Convert]::ToBase64String($content) }} catch {{ Write-Error $_.Exception.Message; exit 1 }}"
        ps_command = f'powershell.exe -Command "{ps_script}"'

        shell_id = self.winrm_protocol_client.open_shell()
        try:
            command_id = self.winrm_protocol_client.run_command(shell_id, ps_command)
            stdout, stderr, return_code = self.winrm_protocol_client.get_command_output(
                shell_id, command_id
            )

            if return_code != 0:
                self.logger.error(
                    f"[{self.remote_host}] Failed to read remote file: {stderr.decode('utf-8', errors='replace')}"
                )
                return False

            # Decode base64 content and write to local file
            try:

                file_content = base64.b64decode(stdout.decode("utf-8").strip())
                with open(local_file, "wb") as f:
                    f.write(file_content)
                return True
            except Exception as e:
                self.logger.error(
                    f"[{self.remote_host}] Failed to write local file: {e}"
                )
                return False

        finally:
            self.winrm_protocol_client.close_shell(shell_id)

    def push_file(self, local_file: str, remote_file: str) -> bool:
        """Push a file to the remote Windows machine using Ansible's stdin approach.

        Args:
            local_file (str): Local file path
            remote_file (str): Remote file path

        Returns:
            bool: True if successful
        """
        self.logger.info(
            f"[{self.remote_host}] Pushing file: {local_file} -> {remote_file}"
        )

        # Read local file
        try:
            with open(local_file, "rb") as f:
                file_content = f.read()
            self.logger.info(
                f"[{self.remote_host}] Read {len(file_content)} bytes from {local_file}"
            )
        except Exception as e:
            self.logger.error(f"[{self.remote_host}] Failed to read local file: {e}")
            return False

        # Load the PowerShell script from disk (Ansible's approach)
        ps_script_path = os.path.join(os.path.dirname(__file__), "winrm_put_file.ps1")
        try:
            with open(ps_script_path, encoding="utf-8") as f:
                ps_script = f.read()
        except Exception as e:
            self.logger.error(
                f"[{self.remote_host}] Failed to load PowerShell script: {e}"
            )
            return False

        # Invoke the script with -Path parameter, reading data from pipeline
        # Use -EncodedCommand to avoid quote/brace escaping issues (Ansible's pattern via _encode_script)
        full_command = f"$input | & {{ {ps_script} }} -Path '{remote_file}'"

        # Encode as UTF-16LE then base64 for -EncodedCommand
        command_bytes = full_command.encode("utf-16-le")
        encoded_command = base64.b64encode(command_bytes).decode("ascii")

        ps_command = f"powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded_command}"

        shell_id = self.winrm_protocol_client.open_shell()
        try:
            # Run the command
            command_id = self.winrm_protocol_client.run_command(shell_id, ps_command)

            # Send base64-encoded file content via stdin using SOAP message (Ansible's approach)
            # Chunk the data (250KB chunks like Ansible)
            chunk_size = 250 * 1024
            offset = 0
            chunk_count = 0

            with open(local_file, "rb") as in_file:
                while True:
                    chunk = in_file.read(chunk_size)
                    if not chunk:
                        break

                    chunk_count += 1
                    offset += len(chunk)

                    # Base64 encode the chunk and add newline (Ansible does this)
                    b64_data = base64.b64encode(chunk).decode("utf-8") + "\r\n"

                    # Build SOAP message for sending stdin data
                    rq = {
                        "env:Envelope": self.winrm_protocol_client._get_soap_header(  # pylint: disable=protected-access
                            resource_uri="http://schemas.microsoft.com/wbem/wsman/1/windows/shell/cmd",
                            action="http://schemas.microsoft.com/wbem/wsman/1/windows/shell/Send",
                            shell_id=shell_id,
                        )
                    }
                    stream = (
                        rq["env:Envelope"]
                        .setdefault("env:Body", {})
                        .setdefault("rsp:Send", {})
                        .setdefault("rsp:Stream", {})
                    )
                    stream["@Name"] = "stdin"
                    stream["@CommandId"] = command_id
                    stream["#text"] = base64.b64encode(b64_data.encode())

                    # Mark the last chunk with End=true
                    is_last = in_file.tell() == len(file_content)
                    if is_last:
                        stream["@End"] = "true"

                    self.winrm_protocol_client.send_message(xmltodict.unparse(rq))

            self.logger.info(
                f"[{self.remote_host}] Sent {chunk_count} chunk(s) totaling {offset} bytes via stdin"
            )

            # Get command output
            stdout, stderr, return_code = self.winrm_protocol_client.get_command_output(
                shell_id, command_id
            )

            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            # Log output if not blank
            if stdout_str:
                self.logger.info(
                    f"[{self.remote_host}] PowerShell stdout: {stdout_str}"
                )
            if stderr_str:
                self.logger.warning(
                    f"[{self.remote_host}] PowerShell stderr: {stderr_str}"
                )

            if return_code != 0:
                self.logger.error(
                    f"[{self.remote_host}] Failed to write remote file (return code {return_code}): {stderr_str}"
                )
                return False

            self.logger.info(
                f"[{self.remote_host}] Successfully pushed file to {remote_file}"
            )
            return True

        except Exception as e:
            self.logger.error(f"[{self.remote_host}] Exception pushing file: {e}")
            return False

        finally:
            self.winrm_protocol_client.close_shell(shell_id)

    def move_file(self, src: str, dst: str) -> bool:
        """Move a file on the remote machine.

        Args:
            src (str): Source file path
            dst (str): Destination file path

        Returns:
            bool: True if successful
        """
        # Convert forward slashes to backslashes for Windows paths
        src_win = src.replace("/", "\\")
        dst_win = dst.replace("/", "\\")

        # Ensure destination directory exists before moving
        dst_dir = ntpath.dirname(dst_win)
        ps_script = (
            f"if (!(Test-Path '{dst_dir}')) {{ New-Item -ItemType Directory -Path '{dst_dir}' -Force | Out-Null }}; "
            f"Move-Item -Path '{src_win}' -Destination '{dst_win}' -Force"
        )
        ps_command = f'powershell.exe -Command "{ps_script}"'

        shell_id = self.winrm_protocol_client.open_shell()
        try:
            command_id = self.winrm_protocol_client.run_command(shell_id, ps_command)
            stdout, stderr, return_code = self.winrm_protocol_client.get_command_output(
                shell_id, command_id
            )

            if return_code != 0:
                self.logger.error(
                    f"[{self.remote_host}] STDOUT: {stdout.decode('utf-8', errors='replace')}"
                )
                self.logger.error(
                    f"[{self.remote_host}] Failed to move file from {src_win} to {dst_win}: {stderr.decode('utf-8', errors='replace')}"
                )
                return False

            return True

        finally:
            self.winrm_protocol_client.close_shell(shell_id)

    def delete_file(self, remote_file: str) -> bool:
        """Delete a file on the remote machine.

        Args:
            remote_file (str): Remote file path

        Returns:
            bool: True if successful
        """
        # Convert forward slashes to backslashes for Windows paths
        remote_file_win = remote_file.replace("/", "\\")

        ps_script = f"Remove-Item -Path '{remote_file_win}' -Force"
        ps_command = f'powershell.exe -Command "{ps_script}"'

        shell_id = self.winrm_protocol_client.open_shell()
        try:
            command_id = self.winrm_protocol_client.run_command(shell_id, ps_command)
            stdout, stderr, return_code = self.winrm_protocol_client.get_command_output(
                shell_id, command_id
            )

            if return_code != 0:
                self.logger.error(
                    f"[{self.remote_host}] STDOUT: {stdout.decode('utf-8', errors='replace')}"
                )
                self.logger.error(
                    f"[{self.remote_host}] Failed to delete file: {stderr.decode('utf-8', errors='replace')}"
                )
                return False

            return True

        finally:
            self.winrm_protocol_client.close_shell(shell_id)

    def create_directory_if_not_exists(self, remote_directory: str) -> bool:
        """Create a directory on the remote machine if it doesn't exist.

        Args:
            remote_directory (str): Remote directory path

        Returns:
            bool: True if successful
        """
        ps_script = f"if (!(Test-Path '{remote_directory}')) {{ New-Item -ItemType Directory -Path '{remote_directory}' -Force | Out-Null }}"
        ps_command = f'powershell.exe -Command "{ps_script}"'

        shell_id = self.winrm_protocol_client.open_shell()
        try:
            command_id = self.winrm_protocol_client.run_command(shell_id, ps_command)
            stdout, stderr, return_code = self.winrm_protocol_client.get_command_output(
                shell_id, command_id
            )

            if return_code != 0:
                self.logger.error(
                    f"[{self.remote_host}] STDOUT: {stdout.decode('utf-8', errors='replace')}"
                )
                self.logger.error(
                    f"[{self.remote_host}] Failed to create directory: {stderr.decode('utf-8', errors='replace')}"
                )
                return False

            return True

        finally:
            self.winrm_protocol_client.close_shell(shell_id)

    def touch_file(self, remote_file: str) -> bool:
        """Create an empty file on the remote machine.

        Args:
            remote_file (str): Remote file path

        Returns:
            bool: True if successful
        """
        ps_script = f"New-Item -ItemType File -Path '{remote_file}' -Force | Out-Null"
        ps_command = f'powershell.exe -Command "{ps_script}"'

        shell_id = self.winrm_protocol_client.open_shell()
        try:
            command_id = self.winrm_protocol_client.run_command(shell_id, ps_command)
            stdout, stderr, return_code = self.winrm_protocol_client.get_command_output(
                shell_id, command_id
            )

            if return_code != 0:
                self.logger.error(
                    f"[{self.remote_host}] STDOUT: {stdout.decode('utf-8', errors='replace')}"
                )
                self.logger.error(
                    f"[{self.remote_host}] Failed to touch file: {stderr.decode('utf-8', errors='replace')}"
                )
                return False

            return True

        finally:
            self.winrm_protocol_client.close_shell(shell_id)

    def get_file_size(self, remote_file: str) -> int:
        """Get the size of a remote file.

        Args:
            remote_file (str): Remote file path

        Returns:
            int: File size in bytes, or -1 if error
        """
        ps_script = f"(Get-Item '{remote_file}').Length"
        ps_command = f'powershell.exe -Command "{ps_script}"'

        shell_id = self.winrm_protocol_client.open_shell()
        try:
            command_id = self.winrm_protocol_client.run_command(shell_id, ps_command)
            stdout, stderr, return_code = self.winrm_protocol_client.get_command_output(
                shell_id, command_id
            )

            if return_code != 0:
                self.logger.error(
                    f"[{self.remote_host}] Failed to get file size: {stderr.decode('utf-8', errors='replace')}"
                )
                return -1

            try:
                return int(stdout.decode("utf-8").strip())
            except (ValueError, AttributeError):
                return -1

        finally:
            self.winrm_protocol_client.close_shell(shell_id)

    def get_file_age(self, remote_file: str) -> int:
        """Get the age of a remote file in seconds.

        Args:
            remote_file (str): Remote file path

        Returns:
            int: File age in seconds, or -1 if error
        """
        ps_script = (
            f"[int]((Get-Date) - (Get-Item '{remote_file}').LastWriteTime).TotalSeconds"
        )
        ps_command = f'powershell.exe -Command "{ps_script}"'

        shell_id = self.winrm_protocol_client.open_shell()
        try:
            command_id = self.winrm_protocol_client.run_command(shell_id, ps_command)
            stdout, stderr, return_code = self.winrm_protocol_client.get_command_output(
                shell_id, command_id
            )

            if return_code != 0:
                self.logger.error(
                    f"[{self.remote_host}] Failed to get file age: {stderr.decode('utf-8', errors='replace')}"
                )
                return -1

            try:
                return int(stdout.decode("utf-8").strip())
            except (ValueError, AttributeError):
                return -1

        finally:
            self.winrm_protocol_client.close_shell(shell_id)

    def supports_direct_transfer(self) -> bool:
        """Return False, as WinRM does not support direct transfers."""
        return False

    def transfer_files(
        self,
    ) -> int:
        """Transfer files to a remote location.

        Args:
            files (list[str]): The files to transfer.
            remote_spec (dict): The remote spec for the transfer.
            dest_remote_handler (dict | None): The destination remote handler.

        Returns:
            int: 0 if successful, 1 if not.
        """
        self.logger.error(
            "Direct transfer between remote systems is not supported by WinRM."
        )
        return 1

    def push_files_from_worker(
        self, local_staging_directory: str, file_list: dict | None = None
    ) -> int:
        """Push files from the worker to the remote location.

        Args:
            local_staging_directory (str): The local staging directory.
            file_list (dict | None): The list of files to transfer. Defaults to None.

        Returns:
            int: 0 if successful, 1 if not.
        """
        result = 0

        if file_list:
            files = list(file_list.keys())
        else:
            # Get list of files in local_staging_directory
            files = glob.glob(f"{local_staging_directory}/*")

        for file in files:
            # Handle any rename that might be specified in the spec
            remote_file = file
            if "rename" in self.spec:
                rename_regex = self.spec["rename"]["pattern"]
                rename_sub = self.spec["rename"]["sub"]

                remote_file = re.sub(rename_regex, rename_sub, file)
                self.logger.info(
                    f"[{self.spec['hostname']}] Renaming file to {remote_file}"
                )

            local_file = os.path.join(local_staging_directory, os.path.basename(file))
            # Use ntpath.join for Windows remote paths
            remote_file = ntpath.join(
                self.spec["directory"], os.path.basename(remote_file)
            )

            if not self.push_file(local_file, remote_file):
                result = 1
        return result

    def pull_files_to_worker(
        self, files: list[str], local_staging_directory: str
    ) -> int:
        """Pull files from the remote location to the worker.

        Args:
            files (list[str]): The files to pull.
            local_staging_directory (str): The local staging directory.

        Returns:
            int: 0 if successful, 1 if not.
        """
        result = 0
        os.makedirs(local_staging_directory, exist_ok=True)
        for remote_file in files:
            local_file = os.path.join(
                local_staging_directory, os.path.basename(remote_file)
            )
            if not self.pull_file(remote_file, local_file):
                result = 1
        return result

    def pull_files(self, files: list[str]) -> int:  # noqa: ARG002
        """Pull files from the remote location to the destination system.

        Args:
            files (list[str]): The files to pull.

        Returns:
            int: 0 if successful, 1 if not.
        """
        self.logger.error(
            "Direct pull between remote systems is not supported by WinRM."
        )
        return 1

    def move_files_to_final_location(self, files: dict) -> int:
        """Move files to their final location.

        Args:
            files (dict): The files to move.

        Returns:
            int: 0 if successful, 1 if not.
        """
        result = 0
        for src, _ in files.items():
            # Use ntpath.join for Windows remote paths
            dst = ntpath.join(self.spec["directory"], os.path.basename(src))
            if not self.move_file(src, dst):
                result = 1
        return result

    def handle_post_copy_action(self, files: list[str]) -> int:
        """Handle any post copy actions.

        Args:
            files (list[str]): The files to act on.

        Returns:
            int: 0 if successful, 1 if not.
        """
        result = 0
        action = self.spec.get("postCopyAction", {}).get("action")
        if action == "delete":
            for file in files:
                if not self.delete_file(file):
                    result = 1
        elif action == "move":
            destination = self.spec["postCopyAction"].get("destination")
            for file in files:
                # Use ntpath.join for Windows remote paths
                dst = ntpath.join(destination, os.path.basename(file))
                if not self.move_file(file, dst):
                    result = 1
        return result


class WinRMExecution(WinRMBase, RemoteExecutionHandler):
    """WinRM remote execution handler.

    Allows execution of commands on a remote Windows machine via WinRM.
    """

    TASK_TYPE = "E"

    remote_pid: int | None = None
    _kill_requested: bool = False
    _shell_id: str | None = None
    _command_id: str | None = None

    def tidy(self) -> None:
        """Tidy up."""
        if self._cert_file:
            self._cert_file.close()
        if self._key_file:
            self._key_file.close()
        return

    def __init__(self, spec: dict):
        """Initialise the WinRMExecution handler.

        Args:
            spec (dict): The spec for the execution.
        """
        self.spec = spec
        self.remote_host = spec["hostname"]
        self.random = random.randint(
            100000, 999999
        )  # Random number used to make sure when we kill stuff, we always kill the right thing
        self._kill_requested = False
        self._shell_id = None
        self._command_id = None

        self.logger = opentaskpy.otflogging.init_logging(
            __name__, spec["task_id"], self.TASK_TYPE
        )

        self._initialize_winrm_client()

        super().__init__(spec)

    def _get_child_processes(self, parent_pid: int) -> list:
        """Get the child processes of a given PID on Windows.

        Args:
            parent_pid (int): The PID of the parent process

        Returns:
            list: A list of child PIDs
        """
        children = []

        # Open a shell to query child processes
        shell_id = self.winrm_protocol_client.open_shell()

        try:
            # Use WMIC to get child processes
            command = f"wmic process where (ParentProcessId={parent_pid}) get ProcessId"
            command_id = self.winrm_protocol_client.run_command(shell_id, command)
            stdout, _, return_code = self.winrm_protocol_client.get_command_output(
                shell_id, command_id
            )

            if return_code == 0 and stdout:
                # Parse the output to get PIDs
                lines = stdout.strip().split("\n")
                for line in lines[1:]:  # Skip header
                    line = line.strip()
                    if line and line.isdigit():
                        child_pid = int(line)
                        self.logger.debug(
                            f"[{self.remote_host}] Found child process with PID: {child_pid}"
                        )
                        children.append(child_pid)
                        # Recurse to find children of this child
                        children.extend(self._get_child_processes(child_pid))
        finally:
            self.winrm_protocol_client.close_shell(shell_id)

        return children

    def kill(self) -> None:
        """Kill the remote process.

        IMPORTANT: The way the killing works will result in an error from OTF saying that the thread
        is still running after the kill. This is because we need to wait up to 20 seconds for the
        WinRMOperationTimeoutError to be raised, at which point the kill request can be processed.
        """
        self._kill_requested = True

        if self.remote_pid is None:
            self.logger.warning(f"[{self.remote_host}] No remote PID to kill")
            return

        self.logger.info(f"[{self.remote_host}] Killing remote process")

        # Get all child processes
        children = self._get_child_processes(self.remote_pid)
        children.append(self.remote_pid)

        self.logger.info(
            f"[{self.remote_host}] Found {len(children)} process(es) to kill - {children}"
        )

        # Kill all processes using taskkill
        shell_id = self.winrm_protocol_client.open_shell()

        try:
            for pid in children:
                command = f"taskkill /F /PID {pid}"
                self.logger.info(
                    f"[{self.remote_host}] Killing remote process with command: {command}"
                )
                command_id = self.winrm_protocol_client.run_command(shell_id, command)
                _, stderr, return_code = self.winrm_protocol_client.get_command_output(
                    shell_id, command_id
                )

                if return_code != 0:
                    self.logger.warning(
                        f"[{self.remote_host}] Failed to kill PID {pid}: {stderr.decode('utf-8', errors='replace') if stderr else 'Unknown error'}"
                    )
        finally:
            self.winrm_protocol_client.close_shell(shell_id)

        # Also send terminate signal to the command if we have the IDs
        if self._shell_id and self._command_id:
            try:
                self.logger.info(
                    f"[{self.remote_host}] Sending terminate signal to command {self._command_id}"
                )
                self.winrm_protocol_client.cleanup_command(
                    self._shell_id, self._command_id
                )
            except Exception as e:
                self.logger.warning(
                    f"[{self.remote_host}] Failed to cleanup command: {e}"
                )

    def _process_output_chunk(  # pylint: disable=too-many-positional-arguments
        self,
        stdout: bytes,
        stderr: bytes,
        stdout_buffer: list,
        stderr_buffer: list,
        pid_captured: bool,
    ) -> bool:
        """Process a chunk of output from the remote command.

        Args:
            stdout: stdout bytes from the command
            stderr: stderr bytes from the command
            stdout_buffer: buffer to append stdout to
            stderr_buffer: buffer to append stderr to
            pid_captured: whether PID has already been captured

        Returns:
            bool: True if PID was captured in this chunk
        """
        # Decode and process stdout
        if stdout:
            # Decode bytes to string for processing
            stdout_str = stdout.decode("utf-8", errors="replace")
            stdout_buffer.append(stdout)

            # Log each line and check for PID token if not yet captured
            for line in stdout_str.splitlines():
                log_stdout(line, self.remote_host, self.logger)

                # Only try to capture PID if we haven't already
                if not pid_captured:
                    regex = f"__OTF_TOKEN__(\\d+)_{self.random}__"
                    pid_search = re.search(regex, line)
                    if pid_search:
                        self.remote_pid = int(pid_search.group(1))
                        self.logger.info(
                            f"[{self.remote_host}] Found remote PID: {self.remote_pid}"
                        )
                        pid_captured = True

        # Collect stderr
        if stderr:
            stderr_buffer.append(stderr)

        return pid_captured

    def _build_powershell_command(self) -> str:
        """Build the PowerShell command with PID token.

        Returns:
            str: The complete PowerShell command string
        """
        directory = self.spec.get("directory", ".")
        user_command = self.spec["command"]

        # Build PowerShell command that outputs the PID token first, then runs the user command
        token_num = str(self.random)
        ps_command = (
            "Write-Host __OTF_TOKEN__$([System.Diagnostics.Process]::GetCurrentProcess().Id)_"
            + token_num
            + "__; "
        )

        if directory and directory != ".":
            ps_command += f"cd '{directory}'; "

        ps_command += user_command

        return f'powershell.exe -Command "{ps_command}"'

    def execute(self) -> bool:
        """Execute the remote command.

        Returns:
            bool: True if the command was executed successfully, False otherwise
        """
        try:
            # Open the shell
            shell_id = self.winrm_protocol_client.open_shell()
            self._shell_id = shell_id
            self.logger.info(f"[{self.remote_host}] Opened shell with ID: {shell_id}")

            # Build and log the command
            command = self._build_powershell_command()
            self.logger.info(f"[{self.remote_host}] Executing command: {command}")

            # Run the command
            command_id = self.winrm_protocol_client.run_command(shell_id, command)
            self._command_id = command_id
            self.logger.info(f"[{self.remote_host}] Run command with ID: {command_id}")

            # Get the output using the raw method in a loop to capture PID early
            stdout_buffer: list[bytes] = []
            stderr_buffer: list[bytes] = []
            command_done = False
            pid_captured = False

            self.logger.info("### START OF REMOTE OUTPUT ###")

            while not command_done and not self._kill_requested:
                try:
                    stdout, stderr, return_code, command_done = (
                        self.winrm_protocol_client.get_command_output_raw(
                            shell_id, command_id
                        )
                    )

                    # Process the output chunk
                    pid_captured = self._process_output_chunk(
                        stdout, stderr, stdout_buffer, stderr_buffer, pid_captured
                    )

                except WinRMOperationTimeoutError:
                    # This is expected for long-running processes, continue polling
                    # Also check if kill was requested
                    if self._kill_requested:
                        # The following is flagged as unreachable by mypy because it doesn't
                        # understand that get_command_output_raw is blocking for up to 20 seconds,
                        # during which time kill may have been requested from another thread
                        self.logger.info(  # type: ignore[unreachable]
                            f"[{self.remote_host}] Kill requested, exiting polling loop"
                        )
                        break

                    # Log that we're continuing to poll (debug level)
                    self.logger.log(
                        11,
                        f"[{self.remote_host}] Polling for output (operation timeout, continuing...)",
                    )

            # Check if we exited due to kill request
            if self._kill_requested:
                self.logger.info(
                    f"[{self.remote_host}] Command execution interrupted by kill request"
                )
                # Don't try to cleanup - the processes have already been killed via taskkill
                # Attempting cleanup will fail with "The parameter is incorrect" since the
                # shell/command are already terminated

            # Log stderr if present
            stderr_combined = b"".join(stderr_buffer)
            if stderr_combined and len(stderr_combined.strip()) > 0:
                stderr_str = stderr_combined.decode("utf-8", errors="replace")
                self.logger.info(
                    f"[{self.remote_host}] Remote stderr returned:\n{stderr_str}"
                )

            self.logger.info("### END OF REMOTE OUTPUT ###")
            self.logger.info(f"[{self.remote_host}] Command return code: {return_code}")

            # Close the shell
            self.winrm_protocol_client.close_shell(shell_id)
            self._shell_id = None
            self._command_id = None

            # If kill was requested, return False
            if self._kill_requested:
                return False

            if return_code != 0:
                self.logger.error(
                    f"[{self.remote_host}] Command failed with return code: {return_code}"
                )
                return False

            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error(f"[{self.remote_host}] Exception caught: {e}")
            return False


def log_stdout(line: str, hostname: str, logger: logging.Logger) -> None:
    """Log the stdout from a remote command in a nice format.

    Args:
        line (str): A line from the stdout
        hostname (str): The hostname of the remote host
        logger (logging.Logger): The logger to use
    """
    logger.info(f"[{hostname}] REMOTE OUTPUT: {line}")
