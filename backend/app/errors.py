class NotFound(Exception):
    """A requested row does not exist."""


class InvalidTransition(Exception):
    """An experiment/plan status change that is not allowed."""


class NeedsResolution(Exception):
    """Insights were requested for a product without a usable Qloo entity match."""


class ConstraintViolation(Exception):
    """An experiment breaks the retailer's hard rules (margin, discount, budget, stock)."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("The experiment breaks your rules: " + " ".join(self.reasons))


class DuplicateExperiment(Exception):
    """The same strategy from the same plan already has an open experiment."""
