"""TAXII 2.1 ingest sub-package (PR #9 Phase 1.3b).

Fetches STIX 2.1 envelopes from pre-configured TAXII collections,
extracts actionable object types, normalizes into staging rows, and
writes with ON CONFLICT dedup. Reuses ``worker.ingest.staging_writer``
and the DQ sink infrastructure from PR #7/PR #8.
"""
