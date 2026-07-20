---
description: Four-agent parallel code review of the local diff, adapted from Anthropic's code-review plugin
argument-hint: [base-branch]
allowed-tools: Bash(git diff:*), Bash(git status:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git log:*), Read, Grep, Glob, Agent, TodoWrite, ReportFindings
---

Provide a code review for the local working diff. This is adapted from Anthropic's `/code-review` plugin (by Boris Cherny) for local use: it reviews the diff on disk instead of a GitHub PR, and reports results directly instead of posting PR comments. Model choice (Sonnet/Opus/etc.) is not part of this design — every subagent below inherits whatever model is currently active. Don't assign or request a specific model for any agent.

The four review roles and the validator are defined as standalone subagent types so they're reusable and independently maintainable:
- `review-claudemd-compliance` (agents 1 + 2 — invoke twice, in parallel, redundantly)
- `review-bug-scan` (agent 3)
- `review-security-logic` (agent 4)
- `review-issue-validator` (step 5 — invoke once per candidate issue)

**Agent assumptions (applies to all subagents launched below):**
- All tools are functional and will work without error. Do not test tools or make exploratory calls.
- Only call a tool if it is required to complete the task. Every tool call should have a clear purpose.

Follow these steps precisely:

1. Determine the base branch: use `$ARGUMENTS` if provided, otherwise `main`. Run `git status`, `git diff <base>...HEAD`, plus uncommitted changes via `git diff` and `git diff --staged`, to build the full set of changes to review. If there is no diff at all, stop and report "No changes to review."

2. List file paths (not contents) for all relevant CLAUDE.md files: the root CLAUDE.md if it exists, and any CLAUDE.md files in directories containing changed files. If none exist, note that and continue — the compliance agents will simply have nothing to check.

3. Summarize the changes (what changed and why, inferred from the diff and recent commit messages). This summary is passed to every subagent below for context on intent.

4. Launch 4 subagents in parallel, each given the diff and the step-3 summary:
   - Two `review-claudemd-compliance` agents (redundant, independent runs)
   - One `review-bug-scan` agent
   - One `review-security-logic` agent

   Each returns a plain list of candidate issues (file:line, description, reason flagged).

5. For every candidate issue returned by the bug-scan and security-logic agents (not the CLAUDE.md agents — those are already scoped tightly enough to trust directly, matching the upstream design), launch one `review-issue-validator` subagent per issue, in parallel, passing it that single issue plus the step-3 summary. Each validator returns CONFIRMED or REJECTED.

6. Build the final issue list: all CLAUDE.md-compliance findings from step 4, plus only the bug/security findings that came back CONFIRMED in step 5. Drop everything else.

7. Call `ReportFindings` once with the final list, most severe first (security/logic bugs before CLAUDE.md style violations). If the list is empty, call it with an empty array — do not pad it with anything speculative.

Use this list when evaluating candidate issues in steps 4-6 (these are false positives — do NOT flag or confirm them):

- Pre-existing issues not introduced by this diff
- Something that appears to be a bug but is actually correct
- Pedantic nitpicks a senior engineer would not flag
- Issues a linter would already catch
- General code quality concerns (e.g. lack of test coverage, general hardening suggestions) unless explicitly required in CLAUDE.md
- Issues mentioned in CLAUDE.md but explicitly silenced in the code (e.g. a lint-ignore comment)

Notes:
- Create a todo list before starting, tracking steps 1-7.
- Use file:line references so findings are easy to jump to.
