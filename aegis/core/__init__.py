"""Core foundation app for the Enterprise Platform.

Owns tenancy, platform identity, RBAC, tenant context/scoping, and audit. All
other platform domains (people, identity/credentials, badging, hardware) build
on the abstractions defined here in later phases.
"""
