# PF-Prototype — agent instructions

This project is designed in Penpot through the **Penpot AI Kit** vendored at
`.penpot-ai-kit/` (read-only — do not edit inside it).

## Before any Penpot work

1. Read `.penpot-ai-kit/AGENTS.md` (house rules) and the router
   `.penpot-ai-kit/skills/penpot-router/SKILL.md`.
2. Follow the kit's doctrine: **tokens before everything** (never hardcode),
   **flex/grid layouts only** (no absolute `x`/`y` for UI), bind **semantic**
   tokens, and **never one-shot** — one logical step per `execute_code` call,
   then `export_shape` and look at it before the checkpoint.

## This instance is Penpot 2.16.0 — required workarounds

- **Never mutate variants** (`createVariantFromComponents`, `setVariantProperty`,
  `addVariant`, …) — it corrupts the file and silently hangs all saves. Build
  each state as a standalone Board, `createComponent` one at a time, named
  `Component / State`; the user converts them to variants in the UI later.
- **Padding token bindings fail** → bind gaps normally; mirror padding as
  resolved numbers (record the exception).
- **`font.applyToText()` corrupts `fontId`** → set `text.fontId`, `fontFamily`,
  `fontVariantId`, `fontWeight` directly from the `Font` object.
- **`applyToken` is async (~100 ms)** → chunk ~25–40 shapes per call and verify
  in a later call; treat bindings as sticky.
- **New token sets are inactive** → `addSet({ name })` takes an object;
  `set.toggleActive()`; reference tokens fail if their target set is inactive.
- **Every new Board is born with an opaque white fill** → clear structural
  boards (`board.fills = []`); bind surface boards to a `color.bg.*` token.
- **No `waitForLayoutUpdate`** (added in 2.17) → read layout geometry in a later
  call.
- **`fill` sizing can record `flipX = true`** → run a `clearFlip` sweep after
  building fill-sized sections.
- **8-digit hex is `#RRGGBBAA` (RGBA)** — NOT ARGB. `#FB718533` = rose at 20%
  alpha; `#33FB7185` mis-reads as `#33FB71`. Use RGBA order for alpha tints.
- **Every font family ships a single weight (400)** in this instance — do NOT
  rely on font weight for hierarchy; use size / colour / spacing instead.
  `font.weight.*` semantic tokens stay for when heavier weights are installed.
- **Token paths cannot nest through a token** — a token may not be a prefix of
  another (`text.size.body` + `text.size.body.sm` fails). Use sibling leaves
  (`text.size.body`, `text.size.secondary`; `color.bg.surface`, `color.bg.raised`;
  `color.status.*` for foreground, `color.tint.*` for alpha backgrounds).

## Design system

- Light/dark are modeled as token modes, not duplicate frames:
  `primitives` → `semantic` (mode-invariant: spacing/radius/type) →
  `modes/light` + `modes/dark` (same colour names, different values). The
  **user** switches themes in Penpot's Tokens panel; the plugin cannot preview
  the switch.
- Keep the current dark/cyan identity for now, encoded as `primitives` so it can
  be re-themed later.

## Working agreement

- Suggest → apply-with-review; stop at checkpoints after each phase/section.
- Desktop screens first, then mobile (Android 360×800).
