# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| main (pre-1.0) | Best effort |

## Reporting a vulnerability

**Do not** open a public GitHub issue for security vulnerabilities.

Please report privately to the maintainers (contact channel TBD when public repo is created). Include:

- Description of the issue and impact
- Steps to reproduce
- Affected components (agent / gateway / web shell)

We aim to acknowledge reports within 7 days.

## Scope

In scope:

- Authentication bypass on Gateway WebSocket or `/files`
- Sandbox escape or path allowlist bypass
- HITL bypass for CRITICAL tools
- Prompt injection leading to unauthorized tool execution

Out of scope (unless combined with above):

- Social engineering of end users
- Compromise of third-party LLM API keys stored in user config
- Denial of service without demonstrated exploit chain

## Safe harbor

Good-faith security research that follows this policy will not be pursued legally, subject to maintainer discretion.
