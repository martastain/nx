from nx.logging import LoggerConfiguration, init_logger


def initialize(
    logger_configuration: LoggerConfiguration | None = None,
    standalone: bool = False,
) -> None:
    """Initialize the configuration for the package."""
    if standalone:
        from nx.config import ConfigModel, ConfigProxy  # noqa: PLC0415

        _config_proxy = ConfigProxy[ConfigModel]()
        _config_proxy.initialize(ConfigModel, "NX")

    if logger_configuration is None:
        logger_configuration = {}
    init_logger(**logger_configuration)
