class BenchmarkError(Exception):
    """Base class for benchmark contract and execution errors."""


class ContractError(BenchmarkError):
    """Raised when a task, answer, oracle, or score violates its contract."""


class TaskNotFoundError(BenchmarkError):
    """Raised when a task identifier cannot be resolved."""


class PolicyError(BenchmarkError):
    """Raised when a bundle or execution violates benchmark policy."""
