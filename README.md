[![PyPi](https://img.shields.io/pypi/v/otf-addons-winrm.svg)](https://pypi.org/project/otf-addons-winrm/)
![unittest status](https://github.com/adammcdonagh/otf-addons-winrm/actions/workflows/test.yml/badge.svg)
[![License](https://img.shields.io/github/license/adammcdonagh/otf-addons-winrm.svg)](https://github.com/adammcdonagh/otf-addons-winrm/blob/master/LICENSE)
[![Issues](https://img.shields.io/github/issues/adammcdonagh/otf-addons-winrm.svg)](https://github.com/adammcdonagh/otf-addons-winrm/issues)
[![Stars](https://img.shields.io/github/stars/adammcdonagh/otf-addons-winrm.svg)](https://github.com/adammcdonagh/otf-addons-winrm/stargazers)

<h1>otf-addons-winrm</h1>

- [Transfers](#transfers)
    - [Supported features](#supported-features)
    - [Configuration](#configuration)
    - [Transfer Process](#transfer-process)
    - [Limitations](#limitations)
- [Configuration](#configuration-1)
- [Executions](#executions)
  - [Example Configuration with NTLM auth](#example-configuration-with-ntlm-auth)
    - [Example Configuration with Certificate-Based Authentication](#example-configuration-with-certificate-based-authentication)
  - [Usage with Batches and Timeouts](#usage-with-batches-and-timeouts)
  - [Important Points](#important-points)
- [WinRM Configuration](#winrm-configuration)
  - [Prerequisites - Create Local User (Windows Server)](#prerequisites---create-local-user-windows-server)
  - [Option 1: Username/Password Authentication (NTLM/Basic)](#option-1-usernamepassword-authentication-ntlmbasic)
    - [Step 1: Configure WinRM on Windows Server](#step-1-configure-winrm-on-windows-server)
    - [Step 2: Python Client Configuration](#step-2-python-client-configuration)
  - [Option 2: Certificate-Based Authentication](#option-2-certificate-based-authentication)
    - [Step 1: Generate Client Certificate (Linux/Dev Container)](#step-1-generate-client-certificate-linuxdev-container)
    - [Step 2: Configure WinRM on Windows Server](#step-2-configure-winrm-on-windows-server)
    - [Step 3: Python Client Configuration](#step-3-python-client-configuration)
  - [Troubleshooting](#troubleshooting)

This repository contains addons to allow integration with Windows machines using WinRM via [Open Task Framework (OTF)](https://github.com/adammcdonagh/open-task-framework)

Open Task Framework (OTF) is a Python based framework to make it easy to run predefined file transfers and scripts/commands on remote machines.

# Transfers

WinRM transfers allow you to move files to/from Windows machines using PowerShell commands over WinRM.

### Supported features

- Push files to Windows machines or pull files from Windows machines using base64 encoding
- Monitor directories for new files matching patterns
- File watch/transfer with file size and age constraints
- `move`, `rename`, and `delete` actions after successful transfer
- Automatically creates destination directories if they don't exist
- Create empty files (useful for completion flags like `.fin` files)
- Transfer to multiple destinations in sequence
- Support for both `push` (from source) and `pull` (to destination) operations

### Configuration

JSON configs for transfers can be defined as follows:

```json
{
  "type": "transfer",
  "source": {
    "hostname": "192.168.1.199",
    "directory": "C:\\data\\source",
    "fileRegex": ".*\\.txt",
    "conditionals": {
      "size": {
        "gt": 10,
        "lt": 1048576
      },
      "age": {
        "gt": 60,
        "lt": 86400
      }
    },
    "postCopyAction": {
      "action": "move",
      "destination": "C:\\data\\archive"
    },
    "protocol": {
      "name": "opentaskpy.addons.winrm.remotehandlers.transfer.WinRMTransfer",
      "server_cert_validation": "ignore",
      "credentials": {
        "transport": "ntlm",
        "username": "otf",
        "password": "YourSecurePassword",
        "port": 5986
      }
    }
  },
  "destination": [
    {
      "hostname": "192.168.1.200",
      "directory": "C:\\data\\dest",
      "transferType": "push",
      "permissions": {
        "group": "Users"
      }
    }
  ]
}
```

### Transfer Process

WinRM transfers work differently from traditional protocols:

1. File listing - Uses PowerShell `Get-ChildItem` to list and filter files
2. File transfer:
   - Push - Reads local file, sends via PowerShell to remote machine, uploading chunk-by-chunk
   - Pull - Reads remote file via PowerShell, base64 encodes it, sends back and decodes locally
3. Post-copy actions - Uses PowerShell cmdlets like `Move-Item`, `Rename-Item`, and `Remove-Item`
4. Directory operations - Uses `New-Item` with `-ItemType Directory` to create directories

### Limitations

- Limited permission management compared to native protocols. This does not take into account any ownership. The files are transferred as the user passed in the task definition.
- Each file transfer requires a separate WinRM session/connection.

# Configuration

JSON configs for transfers can be defined as follows:

# Executions

WinRM executions allow you to run PowerShell commands and scripts on remote Windows machines. The execution handler connects via WinRM (Windows Remote Management) and executes commands in a PowerShell session.

This addon supports both NTLM/Basic authentication and certificate-based authentication.

## Example Configuration with NTLM auth

```json
{
  "type": "execution",
  "hostname": "192.168.1.199",
  "directory": "C:\\temp",
  "command": "Get-ChildItem | Out-String",
  "protocol": {
    "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
    "server_cert_validation": "ignore",
    "credentials": {
      "transport": "ntlm",
      "username": "otf",
      "password": "YourSecurePassword",
      "port": 5986
    }
  }
}
```

The above example will:

1. Connect to the Windows host at `192.168.1.199` using NTLM authentication
2. Change to the `C:\temp` directory
3. Execute the PowerShell command `Get-ChildItem | Out-String`
4. Log all output to the OTF logs

### Example Configuration with Certificate-Based Authentication

```json
{
  "type": "execution",
  "hostname": "192.168.1.199",
  "directory": "C:\\scripts",
  "command": ".\\my-script.ps1 -Parameter Value",
  "protocol": {
    "name": "opentaskpy.addons.winrm.remotehandlers.winrm.WinRMExecution",
    "server_cert_validation": "ignore",
    "credentials": {
      "transport": "certificate",
      "username": "otf",
      "cert_pem": "{{ lookup('file', path='/path/to/winrm.crt') }}",
      "cert_key_pem": "{{ lookup('file', path='/path/to/winrm.key') }}",
      "port": 5986
    }
  }
}
```

## Usage with Batches and Timeouts

When used within a batch task, you can specify a timeout to automatically terminate long-running commands:

```json
{
  "type": "batch",
  "tasks": [
    {
      "order_id": 1,
      "task_id": "windows-backup",
      "timeout": 300
    }
  ]
}
```

The timeout will:

- Kill the PowerShell process and any child processes it spawned
- Allow the batch to continue or fail based on the `continue_on_fail` setting
- Log the termination for debugging purposes

## Important Points

- Commands are executed in PowerShell, so you can use PowerShell syntax and cmdlets
- The `directory` attribute changes the working directory before executing the command
- WinRM uses a polling mechanism with a 20-second operation timeout for output, as such when a kill/timeout occurs, there may be up to a 20-second delay before the thread exits cleanly

# WinRM Configuration

For basic WinRM setup you can follow the steps below. It's not recommended to use self-signed certificates in production.

This can be set up on a Windows 10/11 machine too for easily testing on a local machine.

## Prerequisites - Create Local User (Windows Server)

```powershell
# Run as Administrator on Windows Server
New-LocalUser -Name "otf" -Password (ConvertTo-SecureString "YourSecurePassword" -AsPlainText -Force)
Add-LocalGroupMember -Group "Administrators" -Member "otf"
```

## Option 1: Username/Password Authentication (NTLM/Basic)

### Step 1: Configure WinRM on Windows Server

```powershell
# Run as Administrator
# Quick configuration
winrm quickconfig -force

# Enable Basic authentication (required for HTTPS with username/password)
winrm set winrm/config/service/auth @{Basic="true"}

# Enable NTLM authentication (default, recommended for local accounts)
winrm set winrm/config/service/auth @{Ntlm="true"}

# For local admin accounts on workgroup machines, disable UAC remote restrictions
New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
    -Name LocalAccountTokenFilterPolicy -Value 1 -PropertyType DWORD -Force

# Create self-signed certificate for HTTPS listener
$cert = New-SelfSignedCertificate -DnsName "localhost" -CertStoreLocation "cert:\LocalMachine\My" -NotAfter (Get-Date).AddYears(5)
$thumbprint = $cert.Thumbprint

# Create HTTPS listener
winrm create winrm/config/Listener?Address=*+Transport=HTTPS "@{Hostname=`"localhost`";CertificateThumbprint=`"$thumbprint`"}"

# Verify configuration
winrm get winrm/config
winrm enumerate winrm/config/listener
```

### Step 2: Python Client Configuration

```python
from winrm.protocol import Protocol

p = Protocol(
    endpoint="https://192.168.1.199:5986/wsman",
    transport="ntlm",  # Use 'ntlm' for local accounts, 'basic' also works over HTTPS
    username="otf",    # Or ".\\otf" or "HOSTNAME\\otf" for explicit local account
    password="YourSecurePassword",
    server_cert_validation="ignore",  # Use "validate" in production with proper certs
)
```

## Option 2: Certificate-Based Authentication

### Step 1: Generate Client Certificate (Linux/Dev Container)

```bash
# Generate private key
openssl genrsa -out winrm.key 2048

# Generate self-signed certificate (valid for 365 days)
openssl req -new -x509 -key winrm.key -out winrm.crt -days 365 -subj "/CN=otf"

# Optional: View certificate thumbprint (needed for mapping)
openssl x509 -in winrm.crt -noout -fingerprint -sha1
```

### Step 2: Configure WinRM on Windows Server

```powershell
# Run as Administrator
# Quick configuration
winrm quickconfig -force

# Create self-signed certificate for HTTPS listener
$cert = New-SelfSignedCertificate -DnsName "localhost" -CertStoreLocation "cert:\LocalMachine\My" -NotAfter (Get-Date).AddYears(5)
$thumbprint = $cert.Thumbprint

# Create HTTPS listener
winrm create winrm/config/Listener?Address=*+Transport=HTTPS "@{Hostname=`"localhost`";CertificateThumbprint=`"$thumbprint`"}"

# Enable certificate authentication
Set-Item WSMan:\localhost\Service\Auth\Certificate -Value $true

# Import client certificate to Trusted Root store (copy winrm.crt to Windows first)
Import-Certificate -FilePath "C:\path\to\winrm.crt" -CertStoreLocation Cert:\LocalMachine\Root

# Import client certificate to TrustedPeople store
$clientCert = Import-Certificate -FilePath "C:\path\to\winrm.crt" -CertStoreLocation Cert:\LocalMachine\TrustedPeople

# Map certificate to local user account
New-Item -Path WSMan:\localhost\ClientCertificate `
    -Subject "otf" `
    -URI * `
    -Issuer $clientCert.Thumbprint `
    -Credential (Get-Credential otf) `
    -Force

# Verify certificate mapping
Get-ChildItem WSMan:\localhost\ClientCertificate
```

### Step 3: Python Client Configuration

```python
from winrm.protocol import Protocol

p = Protocol(
    endpoint="https://192.168.1.199:5986/wsman",
    transport="certificate",
    cert_key_pem="winrm.key",
    cert_pem="winrm.crt",
    server_cert_validation="ignore",  # Use "validate" in production with proper certs
)
```

## Troubleshooting

- **InvalidCredentialsError** - Ensure the correct authentication method is enabled and `LocalAccountTokenFilterPolicy` is set for local admin accounts
- **Connection refused** - Check Windows Firewall allows port 5986 (HTTPS) or 5985 (HTTP)
- **Certificate errors** - Verify client certificate is imported to both `Root` (if using a self-signed cert) and `TrustedPeople` stores and properly mapped to user
- **Username formats** - Try different formats: `otf`, `.\\otf`, or `HOSTNAME\\otf`
