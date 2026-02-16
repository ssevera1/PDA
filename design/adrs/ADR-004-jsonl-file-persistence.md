# ADR-004: JSONL File Persistence Over Database

**Status:** Accepted
**Date:** 2025-01-15
**Deciders:** Project maintainer

## Context

PDAgent needs to persist completed call records for audit, review, and historical reference. Each record contains the call metadata (caller, location, duration) and the AI-generated summary. The persistence mechanism must be:

- Reliable (no lost records)
- Simple to deploy (no external services)
- Queryable for basic review
- Compatible with Docker volume mounts

Options considered:

1. **JSONL file** (JSON Lines - one JSON object per line)
2. **SQLite** embedded database
3. **PostgreSQL** managed database
4. **Cloud storage** (S3, GCS)

## Decision

Use **JSONL (JSON Lines) file persistence** at `data/call_history.jsonl`:

- Each completed call appends a single JSON object as one line
- Writes are protected by a `threading.Lock()` for thread safety
- The `data/` directory is created at application startup
- In Docker, the directory is mounted as a volume for persistence across container restarts
- Fields are sanitized and size-limited before writing (call_sid: 50, caller: 200, summary: 5000 chars)

## Consequences

### Positive

- **Zero dependencies** - No database driver, no connection pooling, no migrations, no schema management. Uses Python's built-in `json` and file I/O.
- **Append-only simplicity** - Write path is a single `file.write(json.dumps(record) + "\n")`. No INSERT statements, no ORM, no transaction management.
- **Human-readable** - Records can be inspected with `cat`, `tail -f`, `jq`, or any text editor. No database client needed for debugging.
- **Easy backup** - Copy one file. No database dumps, no pg_dump, no point-in-time recovery complexity.
- **Docker-friendly** - Single volume mount at `/app/data`. No database container, no networking, no initialization scripts.
- **Streamable** - Can `tail -f` the file to watch calls in real-time. Can pipe through `jq` for ad-hoc queries.

### Negative

- **No querying** - Cannot efficiently search by caller, date range, or summary content without reading the entire file. Mitigated by low volume (personal assistant receives few calls per day).
- **No indexing** - Linear scan for any lookup operation. At personal-use volumes (<1000 records/year), this is not a practical limitation.
- **No concurrent writers** - Thread lock serializes writes. Not an issue for a single-process application but would block in a multi-worker deployment.
- **No schema enforcement** - Field types and required fields are enforced in code, not by the storage layer. A bug could write malformed records.
- **No automatic rotation** - File grows indefinitely. At ~500 bytes per record and <1000 calls per year, the file would be <500KB/year. Manual rotation or archival may be needed after years of use.

### Trade-offs Accepted

The trade-off is **queryability and structure for operational simplicity**. A database would provide indexing, querying, and schema enforcement but at the cost of an external dependency, deployment complexity, and operational overhead. For a personal assistant receiving a handful of calls per day, the JSONL file provides all the durability needed with none of the overhead.

## Alternatives Rejected

| Alternative | Why Rejected |
|-------------|-------------|
| **SQLite** | Reasonable alternative. Provides querying and schema enforcement with minimal overhead. Rejected because it adds ORM/driver complexity without proportional benefit at personal-use volumes. Would be a good migration target if query needs arise. |
| **PostgreSQL** | Massively over-engineered for <1000 records/year. Requires a managed database service ($7-15/month), connection pooling, migrations, and operational monitoring. Appropriate for multi-tenant SaaS, not a personal assistant. |
| **S3/Cloud Storage** | Adds cloud provider dependency and API latency to the write path. Useful for archival but not primary persistence. Could be added as a secondary sink in the notification dispatcher if cloud backup is desired. |
