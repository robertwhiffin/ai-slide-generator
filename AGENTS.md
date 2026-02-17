<!-- PRPM_MANIFEST_START -->

<skills_system priority="1">
<usage>
When users ask you to perform tasks, check if any of the available skills below can help complete the task more effectively. Skills provide specialized capabilities and domain knowledge.

How to use skills (loaded into main context):
- Use the <path> from the skill entry below
- Invoke: Bash("cat <path>")
- The skill content will load into your current context
- Example: Bash("cat .openskills/backend-architect/SKILL.md")

Usage notes:
- Skills share your context window
- Do not invoke a skill that is already loaded in your context
</usage>

<available_skills>

<skill activation="lazy">
<name>skill-using-superpowers</name>
<description>Use when starting any conversation - establishes mandatory workflows for finding and using skills, including using Read tool before announcing usage, following brainstorming before coding, and creating TodoWrite todos for checklists</description>
<path>.openskills/skill-using-superpowers/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-brainstorming</name>
<description>Use when creating or developing anything, before writing code or implementation plans - refines rough ideas into fully-formed designs through structured Socratic questioning, alternative exploration, and incremental validation</description>
<path>.openskills/skill-brainstorming/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-writing-plans</name>
<description>Use when design is complete and you need detailed implementation tasks for engineers with zero codebase context - creates comprehensive implementation plans with exact file paths, complete code examples, and verification steps assuming engineer has minimal domain knowledge</description>
<path>.openskills/skill-writing-plans/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-executing-plans</name>
<description>Use when partner provides a complete implementation plan to execute in controlled batches with review checkpoints - loads plan, reviews critically, executes tasks in batches, reports for review between batches</description>
<path>.openskills/skill-executing-plans/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-test-driven-development</name>
<description>Use when implementing any feature or bugfix, before writing implementation code - write the test first, watch it fail, write minimal code to pass; ensures tests actually verify behavior by requiring failure first</description>
<path>.openskills/skill-test-driven-development/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-systematic-debugging</name>
<description>Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes - four-phase framework (root cause investigation, pattern analysis, hypothesis testing, implementation) that ensures understanding before attempting solutions</description>
<path>.openskills/skill-systematic-debugging/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-requesting-code-review</name>
<description>Use when completing tasks, implementing major features, or before merging to verify work meets requirements - dispatches code-reviewer subagent to review implementation against plan or requirements before proceeding</description>
<path>.openskills/skill-requesting-code-review/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-receiving-code-review</name>
<description>Use when receiving code review feedback, before implementing suggestions, especially if feedback seems unclear or technically questionable - requires technical rigor and verification, not performative agreement or blind implementation</description>
<path>.openskills/skill-receiving-code-review/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-verification-before-completion</name>
<description>Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always</description>
<path>.openskills/skill-verification-before-completion/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-using-git-worktrees</name>
<description>Use when starting feature work that needs isolation from current workspace or before executing implementation plans - creates isolated git worktrees with smart directory selection and safety verification</description>
<path>.openskills/skill-using-git-worktrees/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-subagent-driven-development</name>
<description>Use when executing implementation plans with independent tasks in the current session - dispatches fresh subagent for each task with code review between tasks, enabling fast iteration with quality gates</description>
<path>.openskills/skill-subagent-driven-development/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-dispatching-parallel-agents</name>
<description>Use when facing 3+ independent failures that can be investigated without shared state or dependencies - dispatches multiple Claude agents to investigate and fix independent problems concurrently</description>
<path>.openskills/skill-dispatching-parallel-agents/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-root-cause-tracing</name>
<description>Use when errors occur deep in execution and you need to trace back to find the original trigger - systematically traces bugs backward through call stack, adding instrumentation when needed, to identify source of invalid data or incorrect behavior</description>
<path>.openskills/skill-root-cause-tracing/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-defense-in-depth</name>
<description>Use when invalid data causes failures deep in execution, requiring validation at multiple system layers - validates at every layer data passes through to make bugs structurally impossible</description>
<path>.openskills/skill-defense-in-depth/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-condition-based-waiting</name>
<description>Use when tests have race conditions, timing dependencies, or inconsistent pass/fail behavior - replaces arbitrary timeouts with condition polling to wait for actual state changes, eliminating flaky tests from timing guesses</description>
<path>.openskills/skill-condition-based-waiting/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-testing-anti-patterns</name>
<description>Use when writing or changing tests, adding mocks, or tempted to add test-only methods to production code - prevents testing mock behavior, production pollution with test-only methods, and mocking without understanding dependencies</description>
<path>.openskills/skill-testing-anti-patterns/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-testing-skills-with-subagents</name>
<description>Use when creating or editing skills, before deployment, to verify they work under pressure and resist rationalization - applies RED-GREEN-REFACTOR cycle to process documentation by running baseline without skill, writing to address failures, iterating to close loopholes</description>
<path>.openskills/skill-testing-skills-with-subagents/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-writing-skills</name>
<description>Use when creating new skills, editing existing skills, or verifying skills work before deployment - applies TDD to process documentation by testing with subagents before writing, iterating until bulletproof against rationalization</description>
<path>.openskills/skill-writing-skills/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-sharing-skills</name>
<description>Use when you&apos;ve developed a broadly useful skill and want to contribute it upstream via pull request - guides process of branching, committing, pushing, and creating PR to contribute skills back to upstream repository</description>
<path>.openskills/skill-sharing-skills/SKILL.md</path>
</skill>

<skill activation="lazy">
<name>skill-finishing-a-development-branch</name>
<description>Use when implementation is complete, all tests pass, and you need to decide how to integrate the work - guides completion of development work by presenting structured options for merge, PR, or cleanup</description>
<path>.openskills/skill-finishing-a-development-branch/SKILL.md</path>
</skill>

</available_skills>
</skills_system>

<!-- PRPM_MANIFEST_END -->
