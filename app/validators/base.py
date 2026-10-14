from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd


@dataclass
class ValidationResult:
    check_name: str
    status: str           # "pass" | "fail" | "warn" | "skipped"
    severity: str         # "error" (blocks publish) | "warning" | "info"
    details: Dict[str, Any] = field(default_factory=dict)
    message: Optional[str] = None


class BaseValidator(ABC):
    @abstractmethod
    def run(self, df: pd.DataFrame, config: Dict[str, Any]) -> ValidationResult:
        """Run the check against *df* using *config* and return a ValidationResult."""
