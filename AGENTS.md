# Local project instructions

- Keep public code and sanitized summaries separate from ignored credentials/data/logs.
- Use only the pinned public upstream source; do not import private application code.
- Default tests are dummy-only. Do not create actual keys, OAuth clients/grants or connect provider accounts without explicit authorization for those resources.
- Do not restore or recreate stopped internal-HTTP boundary probes. They are absent from this repository by design.
- Do not alter global Docker/security settings, stop unrelated containers or delete volumes.
- Before publication, inspect tracked files and full local Git history for secrets, personal identifiers and large/generated artifacts.
- Do not overwrite existing workspaces. Keep a reversible rollback when relocating this lab's own resources.
