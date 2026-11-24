# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| `main` | Yes |
| Older releases | No; upgrade to the latest release. |

## Reporting a vulnerability

Please do not report exploitable vulnerabilities in public issues. Use
[GitHub Security Advisories](https://github.com/Krishna27Singh/scout/security/advisories/new)
for private reporting, or email
[krishnasingh97857@gmail.com](mailto:krishnasingh97857@gmail.com) with a
description, impact, and steps to reproduce.

Maintainers aim to acknowledge reports within **5 business days**, provide an
initial triage within **10 business days**, and share status updates at least
weekly while the issue is being investigated.

Never commit `.env`, `DATABASE_URL`, `GITHUB_TOKEN`, Groq/Gemini API keys, or
other credentials. If a secret is exposed, revoke or rotate it immediately and
report the incident privately.
