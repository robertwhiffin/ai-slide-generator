"""Verification corpus excludes asset-search tool results (dsv2 battery F4).

The judge's source corpus was built from EVERY ``role=tool`` /
``message_type=tool_result`` message. In design-system sessions the only tool
that runs is ``search_brand_assets``, so numeric claims were "verified" against
brand-asset filename listings — 21/26 battery slides came back
unknown/"Review suggested" purely from the wrong corpus. Asset lookups
(``search_images``, ``search_brand_assets``) return layout handles, not source
data; they must never feed the judge. When nothing data-bearing remains, the
route keeps its honest "No source data available" path.

All fixtures synthetic.
"""

import pytest

from src.api.routes.verification import _build_verification_corpus


def _tool_result(content: str, tool_name: str | None) -> dict:
    metadata = {"tool_name": tool_name} if tool_name is not None else None
    return {
        "role": "tool",
        "message_type": "tool_result",
        "content": content,
        "metadata": metadata,
    }


# Digit-rich so the insufficient-source heuristic cannot be what filters it:
# only the corpus exclusion can keep this away from the judge.
_ASSET_LISTING = (
    "Found 18 brand asset(s):\n"
    "- acme-logo-primary.svg ({{ds-asset:108}})\n"
    "- acme-lockup-dark.svg ({{ds-asset:212}})\n"
    "- acme-illustration-hero.png ({{ds-asset:305}})"
)
_IMAGE_LISTING = "Found 3 image(s): chart-q1.png (id 7), team-photo.jpg (id 12)"
_GENIE_ROWS = "region,revenue\nEMEA,1200000\nAMER,1500000"


class TestBuildVerificationCorpus:
    def test_asset_search_results_are_excluded(self):
        messages = [
            _tool_result(_ASSET_LISTING, "search_brand_assets"),
            _tool_result(_IMAGE_LISTING, "search_images"),
        ]
        assert _build_verification_corpus(messages) == ""

    def test_data_bearing_results_are_kept(self):
        messages = [
            _tool_result(_ASSET_LISTING, "search_brand_assets"),
            _tool_result(_GENIE_ROWS, "genie_query"),
        ]
        corpus = _build_verification_corpus(messages)
        assert _GENIE_ROWS in corpus
        assert "acme-logo-primary" not in corpus

    def test_results_without_tool_metadata_are_kept(self):
        """Older rows persisted before tool_name metadata existed keep flowing
        to the judge — exclusion is strictly name-based."""
        messages = [_tool_result(_GENIE_ROWS, None)]
        assert _build_verification_corpus(messages) == _GENIE_ROWS

    def test_non_tool_messages_and_blank_results_ignored(self):
        messages = [
            {"role": "user", "content": "make slides", "metadata": None},
            {"role": "assistant", "content": "ok", "metadata": None},
            _tool_result("   ", "genie_query"),
            _tool_result(_GENIE_ROWS, "genie_query"),
            _tool_result(_GENIE_ROWS, "vector_search"),
        ]
        assert _build_verification_corpus(messages) == f"{_GENIE_ROWS}\n---\n{_GENIE_ROWS}"


class TestVerifySlideRouteWithAssetOnlySession:
    @pytest.mark.asyncio
    async def test_asset_only_session_takes_no_source_path_without_judge(self, monkeypatch):
        from src.api.routes import verification as verification_route

        class FakeSessionManager:
            def __init__(self):
                self.saved = None

            def get_session(self, session_id):
                return {"genie_conversation_id": None}

            def get_slide_deck(self, session_id):
                return {"slides": [{"html": "<div>Revenue grew 40% to 1.2M</div>"}]}

            def get_messages(self, session_id):
                return [_tool_result(_ASSET_LISTING, "search_brand_assets")]

            def save_verification(self, session_id, content_hash, result):
                self.saved = result

            def get_experiment_id(self, session_id):
                return None

        fake_manager = FakeSessionManager()
        monkeypatch.setattr(
            verification_route, "get_session_manager", lambda: fake_manager
        )

        judge_calls = []

        async def fake_judge(**kwargs):
            judge_calls.append(kwargs)
            raise AssertionError("judge must not run for asset-only sessions")

        monkeypatch.setattr(verification_route, "evaluate_with_judge", fake_judge)

        response = await verification_route.verify_slide(
            0, verification_route.VerifySlideRequest(session_id="synthetic-session")
        )

        assert judge_calls == []
        assert response.rating == "unknown"
        assert "No source data available" in response.explanation
        assert fake_manager.saved is not None
        assert fake_manager.saved["rating"] == "unknown"
