class NotFound(Exception):
    """A requested row does not exist."""


class InvalidTransition(Exception):
    """An experiment/plan status change that is not allowed."""


class NeedsResolution(Exception):
    """Insights were requested for a product without a usable Qloo entity match."""


class StockCommitmentConflict(Exception):
    """One or more SKUs are already committed to another active experiment."""

    def __init__(self, skus: list[str]):
        self.skus = sorted(set(skus))
        super().__init__("Stock is already committed to another approved or running experiment: " + ", ".join(self.skus))
