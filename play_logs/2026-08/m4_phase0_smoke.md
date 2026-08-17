# M4 Demo smoke · 2026-08-03

- zero-LLM one-beat: free_stage_card_ryuya_prologue.json → ok, issues_n=0, has_surface=true
- zero-LLM one-beat: free_stage_card_tiananmen_v2.json → ok, issues_n=0, has_surface=true
- command: python scratch/m4_demo_smoke.py → M4_SMOKE_PASS
- verify: python scripts/verify.py --quick → PASS 12 / FAIL 0 / SKIP 166
- four pillars: 12/12
- old tag: archive/pre-move-2026-08-03 (already present)
- note: copy web/config.json from old repo yourself (gitignored; not committed)
