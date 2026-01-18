# PowerShell script for WinRM file upload
# Reads base64-encoded file content from stdin and writes to destination file
# Based on Ansible's winrm_put_file.ps1

[CmdletBinding()]
param (
    [Parameter(Mandatory)]
    [string]
    $Path,

    [Parameter(ValueFromPipeline)]
    [string]
    $InputObject
)

begin {
    $ErrorActionPreference = "Stop"

    # Ensure the directory exists
    $dest_dirname = [System.IO.Path]::GetDirectoryName($Path)
    if (!(Test-Path -LiteralPath $dest_dirname -PathType Container)) {
        New-Item -Path $dest_dirname -ItemType Directory -Force | Out-Null
    }

    $fd = [System.IO.File]::Create($Path)
    $bytes_written = 0
}

process {
    $bytes = [System.Convert]::FromBase64String($InputObject)
    $fd.Write($bytes, 0, $bytes.Length)
    $bytes_written += $bytes.Length
}

end {
    $fd.Dispose()
    "Wrote $bytes_written bytes to $Path"
}
