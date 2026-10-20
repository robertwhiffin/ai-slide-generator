# Tellr

Tellr creates and edits slide decks through a versioned agent graph. This glossary
names the graph-configuration concepts that must remain distinct in product language,
code, and persistence.

## Language

**Agent Definition**:
The versioned instructions, model settings, output-schema overlay, and prompt-assembly rules for one model-driven graph role.
_Avoid_: Agent config, prompt config, skill config

**Graph Node**:
A named role in the execution graph. A Graph Node may use an Agent Definition or may be deterministic, as Foreman is.
_Avoid_: Agent, when the node does not invoke a model

**Graph Draft**:
The single shared, mutable candidate assembled from edits to one or more Agent Definitions.
_Avoid_: Draft release, unpublished release

**Graph Release**:
An immutable published set containing the exact Agent Definition revision used by every model-driven Graph Node.
_Avoid_: Prompt release, agent release

**Graph Version**:
The human-facing, monotonically increasing ordinal assigned to a Graph Release.
_Avoid_: Database ID, Agent Definition revision

**Conversation Pin**:
The Graph Release selected when a conversation is created and retained for that conversation's lifetime.
_Avoid_: Current version, latest version

**Agent Test Case**:
A named, versioned synthetic input and assembly context for exercising one Agent Definition in isolation.
_Avoid_: Graph test, evaluation dataset

**Agent Test Run**:
The immutable result of executing one Agent Test Case against one exact Agent Definition hash.
_Avoid_: Graph run, conversation turn

**Rollback**:
Publication of a new Graph Release whose definitions restore a selected historical Graph Release.
_Avoid_: Reopen, revert in place

**Slide Number**:
The 1-based number a user sees and says. It is the slide's place in presentation order among the deck's current slides, and it changes when a slide before it is inserted, deleted or moved.
_Avoid_: Position, index

**Slide Position**:
The 0-based identity of a slide: `SlideSpec.position` and the slide row's `position`. `target_positions` and builder briefs are keyed on it. Routes keep it contiguous from 0, but the graph maps Slide Numbers through `src/domain/slide_numbering.py` instead of assuming that.
_Avoid_: Slide number, list index

**Slide Reference**:
A phrase naming existing slides by number or ordinal ("slide 2", "slides 4-6", "the last slide"). `src/domain/slide_numbering.py` resolves it to Slide Positions before the architect runs. It does not decide the intent, and an indefinite ordinal ("a final slide") is not one.
_Avoid_: Slide context (the monolith's UI selection)

**Slide Insertion**:
An edit whose revised spec has more slides than the deck. New slides go where the user asked, later slides take a higher Slide Position and Slide Number (by the number of slides inserted before them) but keep their identity and records, and only new and revised slides are built. `architect_node` derives it by aligning the revised spec to the current one (`src/domain/slide_alignment.py`), never from the model's targets, and refuses when the alignment is ambiguous.
_Avoid_: Add intent, build

**Pending Slide**:
The placeholder row an insertion commits at a new Slide Position until its slide lands. It reads "New slide — not built yet." If the build fails it becomes the failed placeholder.
_Avoid_: Blank slide
