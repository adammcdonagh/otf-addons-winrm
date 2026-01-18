# ruff: noqa: T201, D100
from winrm.protocol import Protocol

p = Protocol(
    endpoint="https://192.168.1.199:5986/wsman",
    transport="certificate",
    cert_key_pem="winrm.key",
    cert_pem="winrm.crt",
    username="otf",
    server_cert_validation="ignore",
)
shell_id = p.open_shell()
command_id = p.run_command(shell_id, "ipconfig", ["/all"])
std_out, std_err, status_code = p.get_command_output(shell_id, command_id)
print(std_out)
print(std_err)
p.cleanup_command(shell_id, command_id)
p.close_shell(shell_id)
