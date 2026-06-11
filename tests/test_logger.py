import nx
from nx.initialize import initialize


def test_logger() -> None:
    initialize(standalone=True)
    nx.config.log_stack = False
    nx.log.info("Hello, world!")

    with nx.log.contextualize(user_id=123, action="test"):
        nx.log.warning("This is a warning with context.")

    nx.config.log_stack = True

    try:
        raise ValueError("This is a test error.")
    except Exception:
        nx.log.traceback("An error occurred.")

    nx.log.log_mode = "json"

    nx.log.info("This is a JSON log message.", extra="extra_value")
