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
