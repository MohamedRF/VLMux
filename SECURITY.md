# Security policy

VLMux is pre-release software and its Windows executor can generate real mouse and keyboard input.
Please report suspected vulnerabilities to MohamedRF through a
[private GitHub security advisory](https://github.com/MohamedRF/VLMux/security/advisories/new)
rather than opening a public issue.

Screen captures may contain credentials or personal data. Runtime captures are sent to the model
provider URL the user explicitly configures; standalone screenshot and observe commands stay
local. Use a local provider with `--offline` when screen data must not leave the machine. Never
include API keys, authorization headers, screenshots, or other secrets in logs, issues, or test
fixtures.
