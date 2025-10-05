# pylint: disable=no-name-in-module
"""Windows remote handler."""

import logging
import random
import re
import tempfile

import opentaskpy.otflogging
from opentaskpy.remotehandlers.remotehandler import RemoteExecutionHandler
from winrm.exceptions import WinRMOperationTimeoutError
from winrm.protocol import Protocol


class WinRMExecution(RemoteExecutionHandler):
    """WinRM remote execution handler.

    Allows execution of commands on a remote Windows machine via WinRM.
    """

    TASK_TYPE = "E"

    winrm_protocol_client: Protocol
    _cert_file: tempfile._TemporaryFileWrapper | None = None
    _key_file: tempfile._TemporaryFileWrapper | None = None
    remote_pid: int | None = None
    remote_host: str
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

        super().__init__(spec)

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
        if (
            self.spec["protocol"]["credentials"]["transport"] == "ntlm"
            or self.spec["protocol"]["credentials"]["transport"] == "basic"
            or self.spec["protocol"]["credentials"]["transport"] == "ssl"
        ):
            kwargs["password"] = self.spec["protocol"]["credentials"]["password"]
        if self.spec["protocol"]["credentials"]["transport"] == "certificate":
            # Decode base64 certificate and key data and write to temporary files
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
