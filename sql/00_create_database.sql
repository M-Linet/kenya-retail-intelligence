-- 00_create_database.sql
-- Run once while connected to the default "postgres" database:
--   psql -U postgres -d postgres -f sql/00_create_database.sql
-- Creates an empty analytical database for the fictional Savanna Fresh Supermarkets chain.

DROP DATABASE IF EXISTS retail_intel;
CREATE DATABASE retail_intel
    WITH ENCODING = 'UTF8'
    TEMPLATE = template0;
