# AIMS Field — Release Notes

- **Version:** 0.4.0
- **Build:** 9
- **Release Date:** August 1, 2026

## What's New
- SLOC Workspaces: every operational surface — inventories, shortages, and reports — is now scoped to your current SLOC, with no cross-SLOC leakage.
- Planner calendar supports multi-date selection, so an Inventory Event can be scheduled across several days at once.
- Importing a Serial Number List now seeds the Inventory Event's FROM from the list's "TO:".

## Bug Fixes
- Inventory card second line now always shows the unit, never the equipment (includes a data migration).
- Shortage and SRH filters list each holder exactly once (distinct by person).

## Known Issues
- None reported.
