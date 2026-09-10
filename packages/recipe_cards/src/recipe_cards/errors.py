"""Failures a caller can correct, as distinct from faults it cannot.

A tool that raises gives the model a generic failure and no way forward. When
the recipe itself is what is wrong — a step too long for its panel, say — the
model can fix it and try again, so the tool answers with what is wrong and what
to change instead of raising.

Anything the model cannot act on, such as a missing bucket or a denied
permission, still raises: retrying that only wastes a turn.
"""

from __future__ import annotations


class ContentTooLong(ValueError):
    """Recipe text does not fit the space the layout gives it.

    Carries the field to shorten and by roughly how much, so the correction is
    a specific edit rather than a guess.
    """

    def __init__(self, field: str, detail: str, suggestion: str) -> None:
        super().__init__(detail)
        self.field = field
        self.detail = detail
        self.suggestion = suggestion

    def as_tool_result(self, attempt: int, max_attempts: int) -> dict[str, object]:
        """Describe the failure in the terms the model needs to act on it."""
        remaining = max(0, max_attempts - attempt)
        return {
            "status": "needs_correction" if remaining else "failed",
            "retryable": bool(remaining),
            "field": self.field,
            "problem": self.detail,
            "fix": self.suggestion,
            "attempts_remaining": remaining,
            "next_step": (
                f"Shorten {self.field} as described and call render_recipe_card again "
                "with the corrected recipe and the same run_id returned in this result."
                if remaining
                else "No attempts remain. Report the problem rather than retrying."
            ),
        }
