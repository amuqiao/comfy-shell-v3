import logging

from app.core.config import AppSettings
from app.core.context import get_request_id, get_trace_id


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        record.trace_id = get_trace_id()
        record.method = getattr(record, "method", "-")
        record.path = getattr(record, "path", "-")
        record.operation_id = getattr(record, "operation_id", "-")
        record.status = getattr(record, "status", "-")
        record.duration_ms = getattr(record, "duration_ms", "-")
        record.error_code = getattr(record, "error_code", "-")
        return True


def configure_logging(settings: AppSettings) -> None:
    level = getattr(logging, settings.observability.log_level)
    handler = logging.StreamHandler()
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s service=%(name)s request_id=%(request_id)s trace_id=%(trace_id)s "
            "method=%(method)s path=%(path)s operation_id=%(operation_id)s status=%(status)s "
            "duration_ms=%(duration_ms)s error_code=%(error_code)s %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)
