-- NVB PostgreSQL roles and database (run as the postgres superuser):
--   read -rsp 'nvb_owner password: ' OWNER_PW; echo
--   read -rsp 'nvb_app password: ' APP_PW; echo
--   sudo -u postgres psql -v owner_pw="$OWNER_PW" -v app_pw="$APP_PW" -f postgresql-setup.sql
-- (psql quotes the values safely via :'var' below.)
--
--   nvb_owner : owns the database and schema; used ONLY for migrations, seed
--               and the guarded reset command.
--   nvb_app   : the running application; data manipulation only (no DDL).

\set ON_ERROR_STOP on

CREATE ROLE nvb_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE nvb_app   LOGIN PASSWORD :'app_pw' CONNECTION LIMIT 80;

CREATE DATABASE nvb OWNER nvb_owner ENCODING 'UTF8' TEMPLATE template0;
REVOKE ALL ON DATABASE nvb FROM PUBLIC;
GRANT CONNECT ON DATABASE nvb TO nvb_owner, nvb_app;

\connect nvb

-- Only the owner may create objects in the public schema.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO nvb_owner;
GRANT USAGE ON SCHEMA public TO nvb_app;

-- Tables and sequences created later by nvb_owner (via Alembic) are
-- automatically usable - but not alterable - by nvb_app.
ALTER DEFAULT PRIVILEGES FOR ROLE nvb_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nvb_app;
ALTER DEFAULT PRIVILEGES FOR ROLE nvb_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO nvb_app;
