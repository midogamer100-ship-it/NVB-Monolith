#!/bin/sh
# Runs once, on first initialisation of the compose PostgreSQL volume.
# Creates the least-privilege application role `nvb_app`. The schema is owned
# by `nvb_owner` (POSTGRES_USER), which is used only for migrations/seed.
set -eu

: "${NVB_APP_DB_PASSWORD:?NVB_APP_DB_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_pw="$NVB_APP_DB_PASSWORD" <<'SQL'
CREATE ROLE nvb_app LOGIN PASSWORD :'app_pw' CONNECTION LIMIT 80;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE nvb FROM PUBLIC;
GRANT CONNECT ON DATABASE nvb TO nvb_app;
GRANT USAGE ON SCHEMA public TO nvb_app;
ALTER DEFAULT PRIVILEGES FOR ROLE nvb_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nvb_app;
ALTER DEFAULT PRIVILEGES FOR ROLE nvb_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO nvb_app;
SQL
