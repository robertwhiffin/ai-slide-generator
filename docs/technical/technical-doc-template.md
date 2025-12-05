# Technical Overview Template

Use this playbook whenever we need a new technical explainer (backend, frontend, pipelines, etc.). It captures the style of the current `docs/technical/*.md` pages—short, structured, and practical for both engineers and AI coding assistants.

---

## 1. Document Goals
- **Audience:** humans and AI agents who need a fast mental model of a subsystem.
- **Tone:** confident, concise, objective. Explain “what + how + why” without fluff.
- **Scope:** summarize current behavior and interfaces; skip historical context unless it matters operationally.

---

## 2. Recommended Outline
1. **Title + One-Line Summary**  
   Set expectations (e.g., “Backend System Overview – FastAPI/LangChain architecture and slide-editing flow”).
2. **Stack / Entry Points**  
   List main technologies, boot files, environment assumptions.
3. **Architecture Snapshot**  
   Text diagram or bullets explaining how major components connect.
4. **Key Concepts / Data Contracts**  
   Small code snippets or tables for critical types, request/response shapes, invariants.
5. **Component Responsibilities**  
   Table mapping files/modules → responsibilities → APIs touched.
6. **State/Data Flow**  
   Numbered steps for the main user or request journey.
7. **Interfaces / API Table**  
   REST or function signature summary for quick reference.
8. **Operational Notes**  
   Error handling, logging, tracing, configuration, testing hooks.
9. **Extension Guidance**  
   Bullet list of “how to add X” or “things to watch”.
10. **Cross-References**  
    Link to other docs (frontend/backend/HTML pipeline) so the set stays coherent.

Feel free to reorder or collapse sections if a subsystem is tiny; the goal is clarity, not ceremony.

---

## 3. Writing Principles
- **Lead with outcomes:** explain what the system does before diving into internals.
- **Use tables for mappings** (modules → responsibilities, endpoints → usage) to keep scanning fast.
- **Include small code snippets** only when they clarify contracts (e.g., TypeScript interfaces, JSON payloads).
- **Call out invariants** (contiguous selection, `.slide` wrapper requirement, etc.) so readers know what must never break.
- **Highlight integration points** (frontend ↔ backend APIs, script synchronization, MLflow tracing) to anchor cross-component reasoning.
- **Reference current files/paths** using backticks (`src/api/...`) so readers can jump into the repo quickly.

---

## 4. Process Checklist
1. **Gather facts:** skim relevant code, logs, configs, and tests until you can narrate the flow end-to-end.
2. **Draft outline:** pick sections from the template above that best fit the feature.
3. **Write concise sections:** keep paragraphs short; prefer lists and tables.
4. **Add cross-links:** reference existing docs (`docs/technical/...`) whenever behavior overlaps.
5. **Review for freshness:** ensure details (endpoints, env vars, feature flags) match the repo’s current state.
6. **Commit guidance:** if behavior changed, remember to update the README and linked technical docs before committing (per `.cursor/rules/readme-summary.mdc`).

---

## 5. When to Extend vs. Create New
- **Extend existing docs** if you are refining the same subsystem.
- **Create a new doc** when introducing a major feature area (e.g., deployment pipeline, analytics subsystem) and link it from the README + relevant sections.

---

## 6. Example References
- `docs/technical/frontend-overview.md` – UI/state patterns and backend touchpoints.
- `docs/technical/backend-overview.md` – FastAPI, LangChain, agent lifecycle.
- `docs/technical/slide-parser-and-script-management.md` – HTML parsing + script reconciliation flow.

Use them as inspiration for formatting, level of detail, and tone.

---

Following this template keeps the documentation set consistent, ensures AI assistants have reliable context, and makes it easy for contributors to orient themselves quickly. Update this file whenever we evolve our doc style or add new required sections.

