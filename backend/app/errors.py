class NotFound(Exception):
    """A requested row does not exist."""


class InvalidTransition(Exception):
    """An experiment/plan status change that is not allowed."""


class NeedsResolution(Exception):
    """Insights were requested for a product without a usable Qloo entity match."""
