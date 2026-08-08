"""Enterprise Platform (working internal package name: ``aegis``).

This package is deliberately self-contained. Nothing under ``aegis`` may import
from Beacon's own apps (``finance``, ``wlj``, ``products``, ``website``) except
through explicitly approved provider/authentication seams. Beacon is only the
temporary incubator/host; it is not the product. See
``docs/architecture/ENTERPRISE_PLATFORM_ARCHITECTURE_PROPOSAL.md``.
"""
