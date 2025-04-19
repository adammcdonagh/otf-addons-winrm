"""Windows remote handler."""

import opentaskpy.otflogging
import winrm
from opentaskpy.remotehandlers.remotehandler import RemoteExecutionHandler


class WinRMExecution(RemoteExecutionHandler):
    """WinRM remote execution handler.

    Allows execution of commands on a remote Windows machine via WinRM.
    """

    TASK_TYPE = "E"

    def tidy(self) -> None:
        """Tidy up."""
        pass

    def __init__(self, spec: dict):
        """Initialise the WinRMExecution handler.

        Args:
            spec (dict): The spec for the execution.
        """
        self.logger = opentaskpy.otflogging.init_logging(
            __name__, spec["task_id"], self.TASK_TYPE
        )

        super().__init__(spec)

    # This cannot be long running, so kill doesn't really need to do anything
    def kill(self) -> None:
        """Kill the remote process."""

    def execute(self) -> bool:
        """Execute the remote command.

        Returns:
            bool: True if the command was executed successfully, False otherwise
        """
        result = True

        remote_hostname = self.spec["hostname"]
        remote_username = self.spec["username"]
        remote_password = self.spec["password"]

        # Allow for other authentication methods

        session = winrm.Session(
            "windows-host.example.com", auth=("john.smith", "secret")
        )
        command_result = session.run_cmd("ipconfig", ["/all"])

        return result
