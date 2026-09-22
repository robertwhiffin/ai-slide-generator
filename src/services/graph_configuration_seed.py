"""Static required-smoke catalogue installed with Graph Version 1."""

REQUIRED_SMOKE_PAYLOADS: dict[str, dict[str, object]] = {
    "architect": {
        "session_id": "synthetic-architect",
        "conversation": [
            {"role": "user", "content": "Create a three-slide demo roadmap."}
        ],
        "message": "Create a three-slide demo roadmap.",
        "current_deck_spec": None,
        "committed_slide_count": 0,
        "previous_deck_review": None,
        "available_design_contract": None,
        "template_sections": [],
        "resolved_style": "Synthetic demo style",
        "design_system_library": [],
    },
    "data_analyst": {
        "session_id": "synthetic-data-analyst",
        "data_request": "Summarize synthetic quarterly revenue of 10, 12, and 15.",
        "deck_purpose": "Demonstrate synthetic growth",
    },
    "builder": {
        "session_id": "synthetic-builder",
        "turn_id": "synthetic-turn",
        "initiated_by": "system:bootstrap",
        "position": 1,
        "slide_spec": {
            "position": 1,
            "title": "Synthetic roadmap",
            "purpose": "Show three phases",
        },
        "assumes": [],
        "hands_off": ["Phase 2 follows Phase 1"],
        "design_contract": {"design_system_id": None, "template_id": None},
        "resolved_data": {"facts": [], "figures": [], "sources": []},
        "section_html": "<section><h1>Roadmap</h1></section>",
        "section_css": ".slide { width: 1280px; height: 720px; }",
        "resolved_style": "Synthetic demo style",
        "design_system_active": False,
    },
    "build_reviewer": {
        "position": 1,
        "slide_spec": {
            "position": 1,
            "title": "Synthetic roadmap",
            "purpose": "Show three phases",
        },
        "resolved_style": "Synthetic demo style",
        "section_css": ".slide { width: 1280px; height: 720px; }",
        "resolved_data": {"facts": [], "figures": [], "sources": []},
        "html": "<div class='slide'><h1>Synthetic roadmap</h1></div>",
        "scripts": "",
        "deck_brief": {
            "purpose": "Demonstrate a synthetic roadmap",
            "audience": "Demo audience",
        },
    },
    "fixer": {
        "position": 1,
        "finding": {
            "criterion": "content_overflow",
            "message": "Synthetic title overflows",
        },
        "html": "<div class='slide'><h1>Synthetic roadmap title</h1></div>",
        "scripts": "",
        "slide_spec": {
            "position": 1,
            "title": "Synthetic roadmap",
            "purpose": "Show three phases",
        },
        "resolved_style": "Synthetic demo style",
        "section_css": ".slide { width: 1280px; height: 720px; }",
    },
    "fix_reviewer": {
        "position": 1,
        "finding": {
            "criterion": "content_overflow",
            "message": "Synthetic title overflows",
        },
        "change_summary": "Reduced the synthetic title size",
        "html": "<div class='slide'><h1 class='small'>Synthetic roadmap</h1></div>",
        "scripts": "",
        "slide_spec": {
            "position": 1,
            "title": "Synthetic roadmap",
            "purpose": "Show three phases",
        },
        "resolved_style": "Synthetic demo style",
        "section_css": ".slide { width: 1280px; height: 720px; }",
    },
    "deck_reviewer": {
        "session_id": "synthetic-deck-reviewer",
        "narrative_arc": ["Context", "Decision", "Action"],
        "call_to_action": "Approve the synthetic roadmap",
        "slide_count": 2,
        "slides": [
            {
                "position": 1,
                "html": "<div class='slide'><h1>Context</h1></div>",
            },
            {
                "position": 2,
                "html": "<div class='slide'><h1>Action</h1></div>",
            },
        ],
    },
}
