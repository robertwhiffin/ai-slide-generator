"""Unit tests for the ``search_brand_assets`` tool (Phase 2 reset).

The tool is the agentic, on-demand path to a design system's brand IMAGE assets:
it wraps ``design_system_service.search_assets``, bound to a ``design_system_id``
via closure (mirroring ``build_genie_tool``), and returns JSON rows carrying a
ready-to-use ``{{ds-asset:ID}}`` handle. All fixtures are SYNTHETIC.
"""
import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _make_ds(session, *, name, assets):
    from src.database.models.design_system import DesignSystem, DesignSystemAsset

    ds = DesignSystem(name=name)
    for a in assets:
        ds.assets.append(DesignSystemAsset(**a))
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


def _img(kind, filename):
    return {"kind": kind, "filename": filename, "mime": "image/svg+xml",
            "data": b"<svg/>", "size_bytes": 6}


def _patched_db(session):
    """Patch the call-time ``get_db_session`` import to yield our test session."""
    @contextmanager
    def _cm():
        yield session

    return patch("src.core.database.get_db_session", _cm)


class TestBuildDsAssetTool:
    def test_tool_name_and_schema(self, session):
        from src.services.tools import build_ds_asset_tool

        ds = _make_ds(session, name="Acme", assets=[_img("logo", "logo.svg")])
        tool = build_ds_asset_tool(ds.id)
        assert tool.name == "search_brand_assets"
        assert set(tool.args.keys()) == {"query", "kind"}

    def test_returns_ds_asset_handles(self, session):
        from src.services.tools import build_ds_asset_tool

        ds = _make_ds(session, name="Acme", assets=[_img("logo", "acme-logo.svg")])
        tool = build_ds_asset_tool(ds.id)
        with _patched_db(session):
            out = json.loads(tool.func())
        assert out["assets"]
        row = out["assets"][0]
        logo = ds.assets[0]
        assert row["id"] == logo.id
        assert row["kind"] == "logo"
        assert row["filename"] == "acme-logo.svg"
        # ready-to-use handle carrying the real DB id
        assert ("{{ds-asset:%d}}" % logo.id) in row["usage"]

    def test_bound_to_design_system_via_closure(self, session):
        """Each tool is bound to ITS design system's id — results never leak."""
        from src.services.tools import build_ds_asset_tool

        ds1 = _make_ds(session, name="A", assets=[_img("logo", "a.svg")])
        ds2 = _make_ds(session, name="B", assets=[_img("logo", "b.svg")])
        tool1 = build_ds_asset_tool(ds1.id)
        tool2 = build_ds_asset_tool(ds2.id)
        with _patched_db(session):
            out1 = json.loads(tool1.func())
            out2 = json.loads(tool2.func())
        assert {r["filename"] for r in out1["assets"]} == {"a.svg"}
        assert {r["filename"] for r in out2["assets"]} == {"b.svg"}

    def test_filters_passed_through(self, session):
        from src.services.tools import build_ds_asset_tool

        ds = _make_ds(session, name="Acme",
                      assets=[_img("logo", "logo.svg"), _img("icon", "icon.svg")])
        tool = build_ds_asset_tool(ds.id)
        with _patched_db(session):
            out_kind = json.loads(tool.func(kind="icon"))
            out_query = json.loads(tool.func(query="LOGO"))
        assert {r["filename"] for r in out_kind["assets"]} == {"icon.svg"}
        assert {r["filename"] for r in out_query["assets"]} == {"logo.svg"}

    def test_empty_ds_returns_graceful_message(self, session):
        from src.services.tools import build_ds_asset_tool

        ds = _make_ds(session, name="Empty", assets=[])
        tool = build_ds_asset_tool(ds.id)
        with _patched_db(session):
            out = json.loads(tool.func())
        assert out["assets"] == []
        assert "No brand assets" in out["message"]

    def test_fonts_not_returned(self, session):
        from src.services.tools import build_ds_asset_tool

        ds = _make_ds(session, name="Acme", assets=[
            _img("logo", "logo.svg"),
            {"kind": "font", "filename": "brand.woff2", "mime": "font/woff2",
             "data": b"f", "size_bytes": 1},
        ])
        tool = build_ds_asset_tool(ds.id)
        with _patched_db(session):
            out = json.loads(tool.func())
        assert "brand.woff2" not in {r["filename"] for r in out["assets"]}

    def test_description_carries_literal_token_and_trigger(self, session):
        from src.services.tools import build_ds_asset_tool

        ds = _make_ds(session, name="Acme", assets=[_img("logo", "logo.svg")])
        tool = build_ds_asset_tool(ds.id)
        # Tool descriptions do NOT pass through the system-prompt brace-escape, so
        # the literal {{ds-asset:ID}} token must be written directly.
        assert "{{ds-asset:ID}}" in tool.description
        assert "brand" in tool.description.lower()
        assert "not invent" in tool.description.lower()

    def test_filename_html_escaped_in_usage(self, session):
        """A crafted filename with HTML metacharacters must be escaped in the
        returned HTML snippet, so copying it can't inject markup. The raw filename
        data field is preserved unescaped (it is data, not HTML)."""
        from src.services.tools import build_ds_asset_tool

        evil = '"><img onerror=alert(1)>.svg'
        ds = _make_ds(session, name="Acme", assets=[_img("logo", evil)])
        tool = build_ds_asset_tool(ds.id)
        with _patched_db(session):
            out = json.loads(tool.func())
        row = out["assets"][0]
        usage = row["usage"]
        # raw metacharacters do NOT appear unescaped in the HTML snippet
        assert '"><img onerror=' not in usage
        assert "&lt;img onerror=" in usage  # '<' escaped
        assert "&quot;&gt;" in usage         # '">' escaped
        # the filename DATA field is preserved raw
        assert row["filename"] == evil


def test_contract_and_handles_survive_brace_escape():
    """End-to-end: the compiled ASSET CONTRACT flows in as system-prompt block #2,
    passes through agent.py's blind brace-escape, and renders back with a LITERAL
    {{ds-asset:ID}} (so the model emits a token the resolver will substitute)."""
    from langchain_core.prompts import ChatPromptTemplate

    from src.core.prompt_modules import build_generation_system_prompt
    from src.services.design_system_compiler import _ASSET_CONTRACT

    compiled = "SLIDE VISUAL STYLE: X\n\n" + _ASSET_CONTRACT
    system = build_generation_system_prompt(slide_style=compiled)

    # Replicate agent.py::_create_prompt: blind brace-escape then f-string render.
    escaped = system.replace("{", "{{").replace("}", "}}")
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", escaped),
            ("placeholder", "{chat_history}"),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )
    msgs = prompt.format_messages(chat_history=[], input="hi", agent_scratchpad=[])
    system_text = msgs[0].content
    assert "{{ds-asset:ID}}" in system_text  # literal handle survived round-trip
    assert "search_brand_assets" in system_text
