"""
IntentFrame Demo Tests — post-compromise containment validation.

See README.md in this directory for the full guide, attack matrix, and results.

Security test suites (require supervisor with attack executor profile):
- test_attacks:            Attacks 1-6  (foundation prompt injection)
- test_advanced_attacks:   Attacks 7-14 (encoding, crescendo, unicode, etc.)
- test_redteam_attacks:    Attacks 15-24 (expert-level, payloads in data fields)
- test_transitive_injection_live: AE → Guardian trust boundary (live LLM)

Pipeline and component tests:
- test_ai_analysis:        AI Analysis Engine only
- test_ai_pipeline:        Full pipeline (Analysis + Guardian + Executor)
- test_adapters:           Executor adapter tests
- test_domain_hardening:   Domain constraint tests
- test_executor:           Executor service tests

Test infrastructure:
- stub_pipeline_agent:     Agent-agnostic test harness (not an LLM)
- invoice_attack_pipeline: Orchestration (policy, workspace, sandbox setup)
- policy_loader:           Loads shared test_policy.yaml into UserPolicy

Run from repo root:
  EXECUTOR_CONFIG=demo/config/executor_attacks.yaml python -m supervisor.main start
  python demo/tests/test_attacks.py
  python demo/tests/test_redteam_attacks.py 15 17
"""
