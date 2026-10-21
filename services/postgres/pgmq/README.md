# pgmq (vendored)

The PostgreSQL extension **pgmq** v1.13.0 (https://github.com/pgmq/pgmq, commit 32c075bb6dbed66a303d1a792393c93e36c09a97).
License: PostgreSQL License (see `LICENSE`).

- `pgmq.control` - copied unchanged from `pgmq-extension/pgmq.control` of the tag `v1.13.0`
- `pgmq--1.13.0.sql` - copied unchanged from `pgmq-extension/sql/pgmq.sql` (the project's own `make` does the same copy)

The extension is pure SQL/PL-pgSQL, so installing it means putting these two files into the
`extension` folder of PostgreSQL (see the Dockerfile). To update: take the two files from a newer tag and change the
version in the file name and in the Dockerfile.
