"""Stable data-layer error types."""

from __future__ import annotations


class DataLayerError(Exception):
    code = "data_layer_error"
    status_code = 500
    retryable = False

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class DataSourceNotFound(DataLayerError):
    code = "data_source_not_found"
    status_code = 404


class DataSourceDisabled(DataLayerError):
    code = "data_source_disabled"
    status_code = 409


class ConnectionFailed(DataLayerError):
    code = "connection_failed"
    status_code = 502
    retryable = True


class QueryRejected(DataLayerError):
    code = "query_rejected"
    status_code = 422


class QueryTimeout(DataLayerError):
    code = "query_timeout"
    status_code = 504
    retryable = True


class MetadataNotSynced(DataLayerError):
    code = "metadata_not_synced"
    status_code = 409


class SnapshotNotFound(DataLayerError):
    code = "snapshot_not_found"
    status_code = 404


class TableNotFound(DataLayerError):
    code = "table_not_found"
    status_code = 404


class ColumnNotFound(DataLayerError):
    code = "column_not_found"
    status_code = 404


class DataSourceNameConflict(DataLayerError):
    code = "data_source_name_conflict"
    status_code = 409


class SyncFailed(DataLayerError):
    code = "sync_failed"
    status_code = 502
    retryable = True
