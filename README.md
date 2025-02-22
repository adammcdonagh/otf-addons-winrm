[![PyPi](https://img.shields.io/pypi/v/otf-addons-winrm.svg)](https://pypi.org/project/otf-addons-winrm/)
![unittest status](https://github.com/adammcdonagh/otf-addons-winrm/actions/workflows/test.yml/badge.svg)
[![Coverage](https://img.shields.io/codecov/c/github/adammcdonagh/otf-addons-winrm.svg)](https://codecov.io/gh/adammcdonagh/otf-addons-winrm)
[![License](https://img.shields.io/github/license/adammcdonagh/otf-addons-winrm.svg)](https://github.com/adammcdonagh/otf-addons-winrm/blob/master/LICENSE)
[![Issues](https://img.shields.io/github/issues/adammcdonagh/otf-addons-winrm.svg)](https://github.com/adammcdonagh/otf-addons-winrm/issues)
[![Stars](https://img.shields.io/github/stars/adammcdonagh/otf-addons-winrm.svg)](https://github.com/adammcdonagh/otf-addons-winrm/stargazers)

This repository contains addons to allow integration with Windows machines using WinRM via [Open Task Framework (OTF)](https://github.com/adammcdonagh/open-task-framework)

Open Task Framework (OTF) is a Python based framework to make it easy to run predefined file transfers and scripts/commands on remote machines.


# Transfers


### Supported features

- Plain file watch
- File watch/transfer with file size and age constraints
- `move`, `rename` & `delete` post copy actions
- Touching empty files after transfer. e.g. `.fin` files used as completion flags
- Touching empty files as an execution

# Configuration

JSON configs for transfers can be defined as follows:


# Executions

