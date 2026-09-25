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
