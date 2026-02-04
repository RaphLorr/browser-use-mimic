import os
import logging
from collections import deque
import sys

from bubus.service import EventBus
from bubus.models import BaseEvent

logger = logging.getLogger(__name__)


def apply_eventbus_memory_warning_threshold(default_mb: int = 500) -> None:
    """
    Monkeypatch EventBus memory warning threshold.
    """
    threshold_mb = int(os.getenv("EVENTBUS_MEMORY_WARNING_MB", str(default_mb)))

    def _check_total_memory_usage(self: EventBus) -> None:  # type: ignore[override]
        total_bytes = 0
        bus_details: list[tuple[str, int, int, int]] = []

        for bus in list(EventBus.all_instances):
            try:
                bus_bytes = 0

                for event in bus.event_history.values():
                    bus_bytes += sys.getsizeof(event)
                    if hasattr(event, "__dict__"):
                        for attr_value in event.__dict__.values():
                            if isinstance(attr_value, (str, bytes, list, dict)):
                                bus_bytes += sys.getsizeof(attr_value)

                if bus.event_queue:
                    if hasattr(bus.event_queue, "_queue"):
                        queue: deque[BaseEvent] = bus.event_queue._queue  # type: ignore[attr-defined]
                        for event in queue:
                            bus_bytes += sys.getsizeof(event)
                            if hasattr(event, "__dict__"):
                                for attr_value in event.__dict__.values():
                                    if isinstance(attr_value, (str, bytes, list, dict)):
                                        bus_bytes += sys.getsizeof(attr_value)

                total_bytes += bus_bytes
                bus_details.append(
                    (bus.name, bus_bytes, len(bus.event_history), bus.event_queue.qsize() if bus.event_queue else 0)
                )
            except Exception:
                continue

        total_mb = total_bytes / (1024 * 1024)

        if total_mb > threshold_mb:
            details: list[str] = []
            for name, bytes_used, history_size, queue_size in sorted(bus_details, key=lambda x: x[1], reverse=True):
                mb = bytes_used / (1024 * 1024)
                if mb > 0.1:
                    details.append(f"  - {name}: {mb:.1f}MB (history={history_size}, queue={queue_size})")

            warning_msg = (
                f"\\n⚠️  WARNING: Total EventBus memory usage is {total_mb:.1f}MB (>{threshold_mb}MB limit)\\n"
                f"Active EventBus instances: {len(EventBus.all_instances)}\\n"
            )
            if details:
                warning_msg += "Memory breakdown:\\n" + "\\n".join(details[:5])
                if len(details) > 5:
                    warning_msg += f"\\n  ... and {len(details) - 5} more"

            warning_msg += "\\nConsider:\\n"
            warning_msg += "  - Reducing max_history_size\\n"
            warning_msg += "  - Clearing completed EventBus instances with stop(clear=True)\\n"
            warning_msg += "  - Reducing event payload sizes\\n"

            logger.warning(warning_msg)

    EventBus._check_total_memory_usage = _check_total_memory_usage  # type: ignore[method-assign]
