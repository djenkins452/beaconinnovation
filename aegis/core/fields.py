"""Primary-key identifier strategy for the Enterprise Platform.

Decision (approved 2026-08-07): use UUIDv4 for Phase 0, following the
repository's established pattern. UUID generation is centralized here so the
strategy can be changed in exactly one place later (e.g. UUIDv7 for index
locality) without touching every model. Do not call ``uuid.uuid4`` directly in
models — always use :func:`new_uuid`.
"""
import uuid


def new_uuid():
    """Return a new primary-key UUID (currently v4)."""
    return uuid.uuid4()
