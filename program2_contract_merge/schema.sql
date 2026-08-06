-- Reference schema for the signed-contract hash record table.
--
-- Program 2 creates this automatically at startup (db.ensure_schema) using
-- whatever POSTGRES_SCHEMA/POSTGRES_TABLE are configured, so running this
-- file by hand is optional - it's here for review, manual provisioning in
-- an environment where the app's DB role can't run DDL, or as a reference
-- if you rename the schema/table via config.
--
-- This file uses the default names (public.signed_contracts). If you've
-- set POSTGRES_SCHEMA/POSTGRES_TABLE to something else, substitute those
-- names here too - or just let the app create it, since it always matches
-- config automatically.

CREATE TABLE IF NOT EXISTS public.signed_contracts (
    id             BIGSERIAL PRIMARY KEY,
    account_number TEXT NOT NULL,
    file_path      TEXT NOT NULL,
    sha256_hash    CHAR(64) NOT NULL,
    captured_at    TIMESTAMPTZ,        -- when Stripe captured the signature
    saved_at       TIMESTAMPTZ NOT NULL, -- when Program 2 saved the PDF
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now() -- when this row was inserted
);

CREATE INDEX IF NOT EXISTS signed_contracts_account_number_idx
    ON public.signed_contracts (account_number);

CREATE INDEX IF NOT EXISTS signed_contracts_sha256_hash_idx
    ON public.signed_contracts (sha256_hash);
