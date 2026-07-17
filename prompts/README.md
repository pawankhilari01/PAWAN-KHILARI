# Prompt Library

Versioned, testable prompts for every EDT Platform agent. Prompts are **data**, not
code: they are loaded by agents at runtime (keyed by `agent` + `version`), evaluated in
CI with **promptfoo** (see `docs/16-evaluation-framework.md`), and rolled back
independently of code.

## Conventions
- One YAML file per agent: `prompts/<phase>/<agent>.yaml`.
- Each file carries `system` (role/instructions), `task_template` (user turn with
  `{{placeholders}}`), `output_schema_ref`, `version`, and `eval` cases.
- Claude best practices: explicit role, XML tags for structure, request step-by-step
  reasoning, force self-critique + confidence scoring, and explicit refusal/escalation.
- Placeholders are filled from `AgentInput` (`{{task}}`, `{{upstream}}`, `{{constraints}}`).
- Never hard-code secrets or PII example data in prompts.

## Layout
```
prompts/
├── discover/     # problem_discovery, persona_builder, ...
├── define/       # root_cause, how_might_we, ...
├── ideate/       # scamper, triz, first_principles, ...
├── prototype/    # prd_generator, api_designer, ...
├── validate/     # go_no_go, roi, roadmap, ...
└── crosscutting/ # supervisor, critic, reflection, ...
```

The 12 fully-specified agents in `docs/11-agent-specifications.md` contain the
canonical long-form prompts; the YAML files here are the machine-loaded source of truth.
