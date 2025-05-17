from nx.logging import LoggerConfiguration, init_logger


def initialize(
    logger_configuration: LoggerConfiguration | None = None,
) -> None:
    """Initialize the configuration for the package."""

    if logger_configuration is None:
        logger_configuration = {}
    init_logger(**logger_configuration)
