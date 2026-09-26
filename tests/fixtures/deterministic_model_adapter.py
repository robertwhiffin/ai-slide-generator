"""Deterministic ``AgentModelAdapter`` double for the #267 test-run path.

It lives in ``tests/fixtures`` and never in ``src/`` (#267 Correction 26), so no
test double ships in the product.  ``FAKE_OUTPUTS`` is the one table of minimal
valid outputs per role; ``test_agent_runtime.py`` and
``test_persisted_agent_runtime.py`` import it rather than keeping copies that
could drift.

The fake mirrors ``with_structured_output``: on success it answers with an
instance of the *composed* schema it was handed, so it cannot prove that an
unvalidated object passes straight through.  Whether an output is valid is
decided only by ``AgentSchemaRegistry.validate_output`` inside the runtime
(#267 Correction 35); nothing here re-validates.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from src.services.agent_runtime import (
    AgentModelConfiguration,
    ModelProviderUnavailableError,
    report_model_token_usage,
)

#: One minimal valid output per model-driven role (moved verbatim from the
#: ``VALID_OUTPUT_VALUES`` tables of the two runtime suites).
FAKE_OUTPUTS: dict[str, dict[str, Any]] = {
    "architect": {"intent": "discuss", "message": "an answer"},
    "data_analyst": {
        "outcome": "success",
        "synthesis": "a finding",
        "sources": ["warehouse.sales"],
    },
    "builder": {"position": 3, "html": "<section></section>"},
    "build_reviewer": {"slide_index": 2, "verdict": "clean"},
    "fixer": {"position": 3, "html": "<section></section>", "changed": False},
    "fix_reviewer": {"slide_index": 2, "verdict": "clean"},
    "deck_reviewer": {},
}


def fake_output(agent_key: str, **extra: Any) -> dict[str, Any]:
    """A fresh, mutable copy of the role's fake output, with ``extra`` merged in."""
    return {**copy.deepcopy(FAKE_OUTPUTS[agent_key]), **extra}


#: A blank ``diagnostic_notes`` item: the registry rejects it as an invalid
#: optional field when the overlay selects it, and as undeclared when it does not.
INVALID_OPTIONAL_FIELD = {"diagnostic_notes": ["  "]}

FakeAdapterMode = Literal[
    "success",
    "provider_unavailable",
    "invalid_optional_field",
    "provider_parse_error",
    "structured_output_unsupported",
    "pause",
]


class _PermissiveProviderOutput(BaseModel):
    """A provider result that ignored the bound schema (``extra="allow"``)."""

    model_config = ConfigDict(extra="allow")


class _ParseProbe(BaseModel):
    count: int


@dataclass(frozen=True)
class FakeModelCall:
    agent_key: str
    schema: type[BaseModel]
    prompt: str
    configuration: AgentModelConfiguration


class DeterministicFakeModelAdapter:
    """Answer every role deterministically, or fail in one named way.

    Modes:

    * ``success`` — ``schema.model_validate(FAKE_OUTPUTS[agent_key])``;
    * ``provider_unavailable`` — raise ``ModelProviderUnavailableError``, as the
      production adapter does for every provider failure;
    * ``invalid_optional_field`` — return the valid output plus a blank
      ``diagnostic_notes`` item, bypassing the bound schema, so only the
      runtime's ``validate_output`` can reject it;
    * ``provider_parse_error`` — raise a pydantic ``ValidationError``, as a
      structured-output parser does on a malformed response;
    * ``structured_output_unsupported`` — raise ``NotImplementedError``, as a
      chat model without structured-output support does at binding;
    * ``pause`` — set ``entered``, then block until ``release`` is set (for the
      no-lock-across-the-model-call proofs), then answer as ``success``.

    ``calls`` records ``(agent_key, schema, prompt, configuration)`` for every
    invocation, before any failure.

    ``usage=(input_tokens, output_tokens)`` makes a call that reaches the
    provider (every mode but ``provider_unavailable`` and
    ``structured_output_unsupported``) report that usage through the runtime's
    ``report_model_token_usage`` seam, as the real provider's callback does.
    """

    def __init__(
        self,
        *,
        mode: FakeAdapterMode = "success",
        entered: threading.Event | None = None,
        release: threading.Event | None = None,
        pause_timeout: float = 10.0,
        usage: tuple[int | None, int | None] | None = None,
    ) -> None:
        if mode == "pause" and (entered is None or release is None):
            raise ValueError("pause mode needs both an entered and a release event")
        self.mode = mode
        self.entered = entered
        self.release = release
        self.pause_timeout = pause_timeout
        self.usage = usage
        self.calls: list[FakeModelCall] = []

    def invoke(
        self,
        *,
        agent_key: str,
        configuration: AgentModelConfiguration,
        schema: type[BaseModel],
        prompt: str,
    ) -> BaseModel:
        self.calls.append(FakeModelCall(agent_key, schema, prompt, configuration))
        if self.mode == "provider_unavailable":
            raise ModelProviderUnavailableError("pinned model provider unavailable")
        if self.mode == "structured_output_unsupported":
            raise NotImplementedError("structured output is not supported")
        if self.usage is not None:
            report_model_token_usage(input_tokens=self.usage[0], output_tokens=self.usage[1])
        if self.mode == "provider_parse_error":
            _ParseProbe.model_validate({"count": "not-an-int"})
        if self.mode == "invalid_optional_field":
            return _PermissiveProviderOutput.model_validate(
                fake_output(agent_key, **INVALID_OPTIONAL_FIELD)
            )
        if self.mode == "pause":
            assert self.entered is not None and self.release is not None
            self.entered.set()
            if not self.release.wait(self.pause_timeout):
                raise TimeoutError("the paused fake adapter was never released")
        return schema.model_validate(fake_output(agent_key))


__all__ = [
    "FAKE_OUTPUTS",
    "INVALID_OPTIONAL_FIELD",
    "DeterministicFakeModelAdapter",
    "FakeAdapterMode",
    "FakeModelCall",
    "fake_output",
]
