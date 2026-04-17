# AGENTS.md - Interface package

## Ownership
Human-facing interface for incidents: Slack bot stubs for diagnosis posting and approval callbacks.

## Responsibilities
- Implement Slack interface stubs (Socket Mode) for MVP.
- Provide formatting helpers for posting diagnosis/triage summaries.
- Provide a mechanism for human approval callback to unblock the agent loop.
- Align approval flow with `REQUIRE_APPROVAL` behavior in the agent (pause until approved).

## Files
- `slack_bot.py` (placeholder for Slack Socket Mode implementation)
- `approval.py` (placeholder for approval callback handling)

