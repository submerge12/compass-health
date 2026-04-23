# AGENTS.md

Project-specific guidance for Codex when working in this repository.

## Interaction Design Principles

User experience is the highest standard for all products, taking priority over technical preferences, code cleanliness, and architectural elegance. The backend can be complex, but every layer the user touches must feel seamless.

This is not just about the GUI — CLI, conversational interactions, Skill, and system feedback are all part of the interaction experience. The following principles apply to all interfaces:

- **Design for goals, not features.** First ask, "What is the user trying to accomplish?" and then decide how to implement it. Do not add features just because they are technically possible.
- **Do not make the user think.** Interactions should be self-explanatory. If something requires a manual to use, the design has failed.
- **The system should take on the complexity.** Automate what can be automated, infer what can be inferred, and never make the user do in three steps what could be done in one.
- **Progressive disclosure.** Show the essentials first, and reveal details only when needed. Do not dump every option on the user at once.
- **Feedback should guide action.** Do not just report problems ("Connection failed"); guide the next step instead ("Retrying now, expected to recover in 5 seconds").
