-- Create the SEPARATE aegis Enterprise Platform database for local dev/test.
--
-- It is kept isolated from Beacon's `default` database by PlatformRouter; this
-- script only provisions an empty database (the application runs migrations).
-- Runs once, automatically, on a fresh docker-compose volume. Dev/test only.
CREATE DATABASE beacon_platform;
