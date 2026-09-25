# Progress — builder owner session ID (#258)

Base: c040dbde087e1c9ff4bc07656b74b3d09aa06300

- [x] Measure (driver /tmp/builder-owner-id/test_measure_roles.py): builder first + retry carry session_id, root_session_id, actor_session_id (owner value in both cases). Others as before.
- [x] RED: TestTheBuilderPromptCarriesNoSessionIdentifier x2 fail on owner ID in builder call 0.
- [x] Fix: nodes.py builder_node filters _MODEL_EXCLUDED_SESSION_KEYS from skill_payload; record built from full payload.
- [x] GREEN: test_graph_nodes.py 144 passed.
- [x] Mutation proof: 5 mutants, all RED, restored from db09dbfd0
- [x] Gates: unit = 6 baseline failures; PG 26+14+4 passed, 0 skips; ruff +1 F811 (existing pattern)
- [ ] Report: report.md NOT written -- the harness refused the file write from a subagent; report content returned in the handback instead
- [x] Adapted TestARealTurn root/actor test to observe the assembly context (it read the leaked payload); SkillStub records context IDs.

## Controller record — 2026-09-25
Commits `c040dbde0..6194289163`: db09dbfd0 (session keys out of builder model payload), 7b2e7b550 (#262 test reads trace via assembly context), 1ef742ecc (UnknownAgentKeyError on the production loader — from the #259 retrospective review finding I-1, a #261 regression), 71eb4038e (builder model payload = positive allowlist of slide content; drops initiated_by, turn_id, graph_release_id), 6194289163 (drops design_contract). Implementer reports were returned inline (harness refused subagent report writes); the controller keeps them in the session transcript, summarised here.
User decisions: remove the owner's session ID from the builder prompt; nothing session- or user-specific reaches the builder (includes `initiated_by`).
Ruling: `design_contract` removed (session-derived row IDs the model cannot use; no builder instruction, prompt block or output field references it — grep confirmed). `position` kept (BuilderOutput.position required; instructions take it "from the brief"). Cost if wrong: none observed for design_contract; position is duplicated in slide_spec.
Implementer gates at 6194289163: focused 187 (graph) / 349 (graph + runtime); full tests/unit 6 failed (baseline nodes and causes) / 5886 passed / 110 skipped; PG persisted_runtime_failures 7, mixed_release_collaboration_acceptance 26, mixed_release_creation 14, shared_deck_mutation_lifecycle 4, zero skips. Mutations: session/identity keys re-added A1-A8 each RED 2 (owner, contributor); U1 removing the unknown-role check RED 3.
Parked for #267: `src/services/graph_configuration_seed.py:23-35` synthetic builder smoke-case payload still carries `session_id` and `design_contract`; #267's test-run path must hand the builder the same allowlisted payload as production, or the seed must be aligned there (it is bootstrap-hashed material, so not changed here).
