# pylint: skip-file
import json
import logging
import os
import random
import re
import shutil

import opentaskpy.otflogging
import pytest
from dotenv import load_dotenv
from opentaskpy.config.loader import ConfigLoader
from opentaskpy.taskhandlers import batch, execution
from pytest_shell import fs

os.environ["OTF_LOG_LEVEL"] = "DEBUG"

# Create a task definition
ipconfig_task_definition = {
    "type": "execution",
    "hostname": "",
    "command": "ipconfig /all",
    "protocol": {
        "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
        "server_cert_validation": "ignore",
        "credentials": {"transport": ""},
    },
}

# Create a variable with a random number
RANDOM = random.randint(10000, 99999)


@pytest.fixture(scope="function")
def write_dummy_variables_file(tmpdir):
    # Write a nested variable to the global variables file
    json_obj = {
        "test": "{{ SOME_VARIABLE }}6",
        "SOME_VARIABLE": "{{ SOME_VARIABLE2 }}5",
        "SOME_VARIABLE2": "test1234",
        "NESTED_VAR_LEVEL_0": {
            "NESTED_VAR_LEVEL_1": {"NESTED_VAR_LEVEL_2": "nested_test1234"},
            "nested_variable_MIXED_CASE": "nested_mixed_case_test1234",
        },
    }

    fs.create_files(
        [
            {f"{tmpdir}/variables.json.j2": {"content": json.dumps(json_obj)}},
        ]
    )

    # Unset any environment variables overrides
    if "OTF_VARIABLES_FILE" in os.environ:
        del os.environ["OTF_VARIABLES_FILE"]


@pytest.fixture(scope="function")
def credentials():
    # Use .env to read in the credentials
    if "GITHUB_ACTIONS" not in os.environ:
        # Load contents of .env into environment
        # Get the current directory
        current_dir = os.path.dirname(os.path.realpath(__file__))
        load_dotenv(dotenv_path=f"{current_dir}/../.env")

        return {
            "hostname": os.getenv("WINRM_HOSTNAME"),
            "username": os.getenv("WINRM_USERNAME"),
            "password": os.getenv("WINRM_PASSWORD"),
            "certificate": os.getenv("WINRM_CERTIFICATE_FILE"),
            "key": os.getenv("WINRM_KEY_FILE"),
        }


def test_run_winrm_execution_ntlm(credentials):

    # Copy the task definition
    ipconfig_via_ntlm_task_definition = ipconfig_task_definition.copy()

    # Update the task definition with the ARN of the function we just created
    ipconfig_via_ntlm_task_definition["hostname"] = credentials["hostname"]
    ipconfig_via_ntlm_task_definition["protocol"]["credentials"]["username"] = (
        credentials["username"]
    )
    ipconfig_via_ntlm_task_definition["protocol"]["credentials"]["password"] = (
        credentials["password"]
    )
    ipconfig_via_ntlm_task_definition["protocol"]["credentials"]["transport"] = "ntlm"

    # Create the execution object
    execution_obj = execution.Execution(
        None, "winrm-ntlm", ipconfig_via_ntlm_task_definition
    )

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    os.environ["OTF_LOG_LEVEL"] = "DEBUG"

    # Create a handler to capture log messages
    log_messages = []

    class LogCaptureHandler(logging.Handler):
        def emit(self, record):
            log_messages.append(record.getMessage())

    # Add the log capture handler to the logger
    logger.addHandler(LogCaptureHandler())

    # Validate that the logged output include the IP address of the host by capturing the stderr
    assert execution_obj.run()

    found_ip = False
    for log_message in log_messages:
        if re.search(credentials["hostname"], log_message):
            found_ip = True

    assert found_ip


def test_run_winrm_execution_cert(credentials):

    # Copy the task definition
    ipconfig_via_cert_task_definition = ipconfig_task_definition.copy()

    # Update the task definition with the ARN of the function we just created
    ipconfig_via_cert_task_definition["hostname"] = credentials["hostname"]

    ipconfig_via_cert_task_definition["protocol"]["credentials"]["username"] = (
        credentials["username"]
    )

    with open(credentials["key"]) as key_file:
        ipconfig_via_cert_task_definition["protocol"]["credentials"][
            "cert_key_pem"
        ] = key_file.read()

    with open(credentials["certificate"]) as cert_file:
        ipconfig_via_cert_task_definition["protocol"]["credentials"][
            "cert_pem"
        ] = cert_file.read()

    ipconfig_via_cert_task_definition["protocol"]["credentials"][
        "transport"
    ] = "certificate"

    # Create the execution object
    execution_obj = execution.Execution(
        None, "winrm-ntlm", ipconfig_via_cert_task_definition
    )

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    os.environ["OTF_LOG_LEVEL"] = "DEBUG"

    # Create a handler to capture log messages
    log_messages = []

    class LogCaptureHandler(logging.Handler):
        def emit(self, record):
            log_messages.append(record.getMessage())

    # Add the log capture handler to the logger
    logger.addHandler(LogCaptureHandler())

    # Validate that the logged output include the IP address of the host by capturing the stderr
    assert execution_obj.run()

    found_ip = False
    for log_message in log_messages:
        if re.search(credentials["hostname"], log_message):
            found_ip = True

    assert found_ip


def test_winrm_execution_timeout_kill(tmpdir, write_dummy_variables_file, credentials):
    """Test that WinRM execution timeout properly kills the remote process."""
    # Create a task definition that pings localhost 100 times (will take ~100 seconds)
    # Using ping is better than Start-Sleep as it creates a visible cmd.exe process
    # that we can clearly see in the process list
    sleep_task_definition = {
        "type": "execution",
        "hostname": credentials["hostname"],
        "command": "ping -n 100 127.0.0.1",
        "directory": "C:\\",
        "protocol": {
            "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
            "server_cert_validation": "ignore",
            "credentials": {
                "transport": "ntlm",
                "username": credentials["username"],
                "password": credentials["password"],
            },
        },
    }

    # Create a batch definition with a timeout
    timeout_batch_definition = {
        "type": "batch",
        "tasks": [
            {
                "order_id": 1,
                "task_id": "ping-100-winrm",
                "timeout": 10,  # 10 second timeout
            }
        ],
    }

    # Create a temporary task config file for the sleep task
    try:
        # Create the config directory structure
        cfg_dir = os.path.join(tmpdir, "cfg", "execution")
        os.makedirs(cfg_dir, exist_ok=True)

        # Write the task definition to a file
        task_file = os.path.join(cfg_dir, "ping-100-winrm.json")
        with open(task_file, "w") as f:
            json.dump(sleep_task_definition, f)

        # Create a config loader
        config_loader = ConfigLoader(tmpdir)

        test_id = random.randint(10000, 99999)
        os.environ["OTF_LOG_RUN_PREFIX"] = f"test_winrm_timeout_{test_id}"

        # Create the batch object
        batch_obj = batch.Batch(
            None,
            f"winrm-timeout-test-{test_id}",
            timeout_batch_definition,
            config_loader,
        )

        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)

        # Create a handler to capture log messages
        log_messages = []

        class LogCaptureHandler(logging.Handler):
            def emit(self, record):
                log_messages.append(record.getMessage())

        # Add the log capture handler to the logger
        handler = LogCaptureHandler()
        logger.addHandler(handler)

        # Run the batch - should fail due to timeout
        assert not batch_obj.run()

        # Remove the handler
        logger.removeHandler(handler)

        # Check that we captured the PID in the logs
        found_pid = False
        found_timeout = False
        found_kill = False

        for log_message in log_messages:
            if "Found remote PID:" in log_message:
                found_pid = True
            if "has timed out" in log_message:
                found_timeout = True
            if "Killing remote process" in log_message:
                found_kill = True

        assert found_pid, "PID should have been captured from remote output"
        assert found_timeout, "Task should have timed out"
        assert found_kill, "Kill method should have been called"

        # Check the log files
        log_file_name_batch = opentaskpy.otflogging._define_log_file_name(
            f"winrm-timeout-test-{test_id}", "B"
        )
        log_file_name_task = opentaskpy.otflogging._define_log_file_name(
            "ping-100-winrm", "E"
        )

        # Both should exist with _failed status
        assert os.path.exists(log_file_name_batch.replace("_running", "_failed"))
        assert os.path.exists(log_file_name_task.replace("_running", "_failed"))

        # Check the batch log contains timeout message
        with open(
            log_file_name_batch.replace("_running", "_failed"), encoding="utf-8"
        ) as f:
            batch_log = f.read()
            assert "Task 1 (ping-100-winrm) has timed out" in batch_log

        # Ensure the task was actually pinging when it was killed, and wasn't failing
        # to connect or something else.
        with open(
            log_file_name_task.replace("_running", "_failed"), encoding="utf-8"
        ) as f:
            task_log = f.read()
            assert "Pinging 127.0.0.1 with " in task_log

    finally:
        # Clean up temp directory
        shutil.rmtree(tmpdir, ignore_errors=True)

        # Clean up environment
        if "OTF_LOG_RUN_PREFIX" in os.environ:
            del os.environ["OTF_LOG_RUN_PREFIX"]
