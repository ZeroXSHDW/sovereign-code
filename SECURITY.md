# Security

Sovereign Code is local-first by design: it binds Ollama and the LiteLLM gateway
to `127.0.0.1`, never calls a cloud API, and sends no telemetry. There is no
network attack surface from the application itself.

## Reporting a vulnerability

If you find a security issue, please report it privately rather than opening a
public issue. Open a draft security advisory on GitHub:

**Security → Advisories → New draft security advisory**

or email the maintainer. Include a short description, steps to reproduce, and
the affected version.

## Scope

- Anything that lets the loopback-only gateway or Ollama be reached from other
  hosts, or that injects untrusted input into the shell, is in scope.
- The local browser operator never solves CAPTCHAs or spoofs identity; bypassing
  its safety rails (URL policy, secret-field refusal, destructive-action
  confirmation) is treated as a vulnerability.
