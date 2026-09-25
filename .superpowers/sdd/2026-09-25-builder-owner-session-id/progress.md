# Progress — builder owner session ID (#258)

Base: c040dbde087e1c9ff4bc07656b74b3d09aa06300

- [x] Measure (driver /tmp/builder-owner-id/test_measure_roles.py): builder first + retry carry session_id, root_session_id, actor_session_id (owner value in both cases). Others as before.
- [x] RED: TestTheBuilderPromptCarriesNoSessionIdentifier x2 fail on owner ID in builder call 0.
- [x] Fix: nodes.py builder_node filters _MODEL_EXCLUDED_SESSION_KEYS from skill_payload; record built from full payload.
- [x] GREEN: test_graph_nodes.py 144 passed.
- [ ] Mutation proof
- [ ] Gates
- [ ] Report
