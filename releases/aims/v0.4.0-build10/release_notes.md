# AIMS Field — Release Notes

- **Version:** 0.4.0
- **Build:** 10
- **Release Date:** August 2, 2026

## What's New
- New Commander and Supply dashboards driven by one Operational Metrics Engine, so every number shares a single definition: a Commander Live View with live serial accountability, and a Supply "Inventory Metrics" review surface (six Findings tiles) with Shortages as a drill-down.
- Home is now a Working-Scope dashboard: choose All SLOCs or a single SLOC, with badges that represent the primary unit of work — no separate Inventory Event switcher.
- Clearer SLOC Inventory architecture: explicit SLOC → Inventory Event → BOM selection, with the Inventory Event as the execution boundary.
- Live Replication now pairs devices with discovery + PIN authorization and an app-wide approval prompt.
- iOS and iPadOS 16 support.

## Bug Fixes
- Fixed an imported event that could be stranded in the wrong Workspace (0-of-0 regression).
- Live Replication handshake reliability fix.

## Known Issues
- None reported.
