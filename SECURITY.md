# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Open a private security
advisory on this repository (Security tab, "Report a vulnerability") with the steps to
reproduce and the impact you expect.

## Scope

The guards in `kit/hooks/` are seatbelts for AI coding agents, not a sandbox. Their
known blind spots are listed in the header of `kit/hooks/guard.py` and asserted as
accepted residuals in the harnesses. A way past a guard that is NOT in that list is in
scope and welcome.

## Secrets

This repository holds no credentials. The secret scan (`kit/hooks/secret-scan.sh`) runs
in every gate; a tracked credential-shaped file fails it.
