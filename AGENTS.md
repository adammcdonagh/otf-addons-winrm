# WinRM Addon for Open Task Framework (OTF)

## Project Overview

This is a Windows Remote Management (WinRM) addon for the Open Task Framework (OTF). It enables remote execution and file transfer operations on Windows machines via WinRM protocol, providing a PowerShell-based alternative to traditional protocols like SSH/SCP for Windows environments.

## Architecture

### Core Components

The addon is structured around two main handler classes:

#### 1. **WinRMTransfer** (RemoteTransferHandler)

Implements file transfer operations to/from Windows machines via WinRM using base64 encoding.

**Key Methods:**

- `list_files()` - Lists files in a directory with pattern matching and optional conditionals (size/age filtering)
- `pull_file()` - Downloads a file from remote Windows machine to local system
- `push_file()` - Uploads a file from local system to remote Windows machine
- `move_file()` - Moves a file on the remote machine
- `delete_file()` - Deletes a file on the remote machine
- `create_directory_if_not_exists()` - Creates directories on remote machine
- `touch_file()` - Creates empty files on remote machine
- `get_file_size()` - Retrieves file size in bytes
- `get_file_age()` - Retrieves file age in seconds

**Abstract Method Implementations:**

- `supports_direct_transfer()` - Returns `False` (WinRM requires staging)
- `transfer_files()` - Direct remote-to-remote transfers not supported
- `push_files_from_worker()` - Pushes files from local staging to remote
- `pull_files_to_worker()` - Pulls files from remote to local staging
- `pull_files()` - Remote-to-remote pull not supported
- `move_files_to_final_location()` - Moves files to final destination directory
- `handle_post_copy_action()` - Handles post-copy actions (delete, move, rename)

#### 2. **WinRMExecution** (RemoteExecutionHandler)

Implements command execution on remote Windows machines via WinRM.

**Key Methods:**

- `execute()` - Executes PowerShell commands on remote machine with output capture and PID tracking
- `kill()` - Terminates remote process and all child processes using taskkill
- `_build_powershell_command()` - Constructs PowerShell commands with PID token for tracking
- `_process_output_chunk()` - Processes command output in chunks, extracting PID from token
- `_get_child_processes()` - Recursively retrieves child process IDs using WMIC

#### 3. **WinRMBase**

Shared base class providing common authentication and client initialization logic.

**Key Methods:**

- `_initialize_winrm_client()` - Sets up WinRM Protocol client with authentication
- `_cleanup_temp_files()` - Cleans up temporary certificate files

### Authentication Methods

Supports multiple WinRM authentication mechanisms:

- **NTLM** - Windows native authentication
- **Basic** - Username/password authentication
- **SSL** - Secure SSL authentication
- **Certificate** - Client certificate-based authentication with PEM files

Configuration via credentials in the protocol spec:

```json
{
  "transport": "ntlm|basic|ssl|certificate",
  "username": "domain\\username",
  "password": "password (for ntlm/basic/ssl)",
  "cert_pem": "certificate PEM (for certificate auth)",
  "cert_key_pem": "key PEM (for certificate auth)",
  "port": 5986
}
```

## Technical Implementation Details

### PowerShell Integration

All operations use PowerShell wrapped in `powershell.exe -Command` for proper execution:

- File operations use base64 encoding for safe binary file transfer
- Commands are executed via WinRM shells
- Output is captured and processed in chunks
- Process IDs are tracked using special tokens (`__OTF_TOKEN__PID_RANDOM__`)

### File Transfer Process

1. **Push (Local → Remote):**

   - Read local file as binary
   - Base64 encode the content
   - Execute PowerShell on remote machine to create directory and write file
   - Remote machine decodes base64 and writes binary content

2. **Pull (Remote → Local):**
   - Execute PowerShell on remote machine to read file as binary
   - Remote machine base64 encodes content
   - Local system receives encoded output and decodes
   - Write decoded binary to local filesystem

### Process Execution

1. Open WinRM shell on remote machine
2. Build PowerShell command with PID token
3. Execute command and stream output
4. Parse output for PID token to track process
5. Handle process termination by killing process tree
6. Close WinRM shell

## Directory Structure

```
/workspaces/otf-addons-winrm/
├── src/opentaskpy/addons/winrm/
│   ├── remotehandlers/
│   │   ├── __init__.py
│   │   ├── winrm.py (WinRMTransfer, WinRMExecution, WinRMBase)
│   │   └── (other protocol implementations)
│   ├── config/
│   │   └── schemas/
│   │       ├── transfer/
│   │       │   └── winrm/
│   │       │       ├── protocol.json (authentication schema)
│   │       │       └── winrm.json (transfer configuration schema)
│   │       └── execution/
│   │           └── winrm/ (execution schemas)
│   └── __init__.py
├── tests/
│   ├── test_winrm_transfer_schema_validate.py
│   ├── test_taskhandler_transfer_winrm.py
│   └── (other test files)
├── README.md (user documentation)
└── AGENTS.md (this file)
```

## Key Design Patterns

### 1. Staging Pattern for File Transfers

WinRM doesn't support direct transfers, so files are staged:

- **Push**: Local file → Remote staging directory → Final location
- **Pull**: Remote file → Local staging directory → Final location

### 2. PID Tracking via Special Tokens

Commands output a token with the process ID: `__OTF_TOKEN__12345_999999__`
This enables tracking and killing of processes from the execution layer.

### 3. Shared Authentication

Both Transfer and Execution handlers inherit from `WinRMBase` to share authentication logic and avoid duplication.

### 4. Error Handling with Logging

All operations log to a task-specific logger with hostname prefixes for debugging in multi-machine scenarios.

## Configuration Examples

### Transfer Configuration

```json
{
  "type": "transfer",
  "source": {
    "hostname": "192.168.1.199",
    "directory": "C:\\data\\source",
    "fileRegex": ".*\\.txt",
    "protocol": {
      "name": "opentaskpy.addons.winrm.remotehandlers.transfer.WinRMTransfer",
      "server_cert_validation": "ignore",
      "credentials": {
        "transport": "ntlm",
        "username": "DOMAIN\\user",
        "password": "password",
        "port": 5986
      }
    }
  },
  "destination": [
    {
      "hostname": "192.168.1.200",
      "directory": "C:\\data\\dest"
    }
  ]
}
```

### Execution Configuration

```json
{
  "type": "execution",
  "hostname": "192.168.1.199",
  "directory": "C:\\Scripts",
  "command": "Get-ChildItem | Select-Object Name",
  "protocol": {
    "name": "opentaskpy.addons.winrm.remotehandlers.execution.WinRMExecution",
    "server_cert_validation": "ignore",
    "credentials": {
      "transport": "ntlm",
      "username": "DOMAIN\\user",
      "password": "password",
      "port": 5986
    }
  }
}
```

## Limitations

- **Performance**: Base64 encoding/decoding adds ~33% overhead for large files
- **Binary Handling**: All files treated as binary for safe transfer
- **Direct Transfers**: No direct remote-to-remote transfers supported (must proxy through local machine)
- **Permission Management**: Limited to basic Windows permission operations
- **Concurrent Operations**: Each operation requires a separate WinRM session
- **Large Files**: May timeout with default WinRM settings - chunking strategy recommended for files >100MB

### Known Linting Warnings (Expected)

The following unused argument warnings are expected because methods must match abstract method signatures from the parent class:

- `transfer_files()` - Arguments `files`, `remote_spec`, `dest_remote_handler` unused (method returns error as direct transfer not supported)
- `pull_files()` - Argument `files` unused (method returns error)
- `push_files_from_worker()` - Argument `file_list` unused (uses directory listing instead)

## Testing

### Test Files

- `test_winrm_transfer_schema_validate.py` - Schema validation tests for transfer configuration
- `test_taskhandler_transfer_winrm.py` - Integration tests for transfer operations

### Test Requirements

- Requires `.env` file with WinRM credentials:
  - `WINRM_HOSTNAME` - Target Windows machine IP/hostname
  - `WINRM_USERNAME` - Windows username
  - `WINRM_PASSWORD` - Windows password

### Test Fixtures

- `credentials()` - Loads credentials from environment
- `winrm_client()` - Creates WinRM client for setup/teardown
- `remote_test_dir()` - Creates temporary test directories on Windows
- `local_test_dir()` - Creates temporary local test directories
- Helper functions for file creation and verification on Windows:
  - `create_remote_file()` - Creates files on Windows via WinRM
  - `check_remote_file_exists()` - Checks file existence
  - `get_remote_file_content()` - Reads file content

## Dependencies

### External Packages

- `pywinrm` - WinRM protocol implementation
- `opentaskpy` - Core OTF framework
- `python-dotenv` - Environment variable loading for tests

### Framework Integration

- Inherits from `RemoteTransferHandler` and `RemoteExecutionHandler` abstract classes
- Uses OTF logging system (`opentaskpy.otflogging`)
- Integrates with OTF's schema validation system

## Common Issues & Troubleshooting

### Issue: PowerShell Commands Not Executing

**Solution**: Ensure commands are wrapped in `powershell.exe -Command "..."` as the WinRM protocol requires explicit PowerShell invocation.

### Issue: File Transfer Failures

**Solution**: Check that base64 encoding/decoding is working correctly. Large files may experience timeouts - consider chunking strategy.

### Issue: Process Killing Timeout

**Solution**: Kill operation waits up to 20 seconds for WinRM timeout. This is expected behavior; OTF may report thread still running after kill is initiated.

### Issue: Certificate Validation

**Solution**: Set `"server_cert_validation": "ignore"` for self-signed certificates in development environments.

## Future Enhancements

- Chunked file transfer for large files
- Parallel multi-file transfers
- Compression support for transfer optimization
- Direct remote-to-remote transfer support via intermediate WinRM calls
- Windows Event Log integration for execution tracking

## Best Practices for Development

### PowerShell Command Construction

- **Always** wrap PowerShell scripts in `powershell.exe -Command "..."`
- Use single-line commands or semicolon-separated statements
- Escape double quotes within the command string
- Handle errors with try/catch blocks in PowerShell

### WinRM Session Management

- Each operation opens/closes a shell - this is intentional for isolation
- Shell IDs should be stored for cleanup during kill operations
- Connection errors should be retried with exponential backoff

### File Path Handling

- Windows uses backslashes (`\`) - ensure proper escaping in PowerShell strings
- Use `os.path.join()` for local paths, string concatenation for remote Windows paths
- Test with UNC paths (`\\server\share\file.txt`)
- Use ntpath.join for Windows remote paths

### Authentication Best Practices

- Certificate files are created temporarily and cleaned up
- Passwords should be retrieved from secure storage (not hardcoded)
- Support for domain accounts: `DOMAIN\username` format

## Code Review Checklist

When reviewing WinRM code changes:

- [ ] All PowerShell commands wrapped in `powershell.exe -Command`
- [ ] Error handling with try/catch in PowerShell scripts
- [ ] Shell cleanup in finally blocks
- [ ] Proper logging with hostname prefixes
- [ ] Base64 encoding/decoding for binary files
- [ ] Path escaping for Windows paths
- [ ] Return code checking for all WinRM operations
- [ ] Abstract method signatures match parent class exactly
