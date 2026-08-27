"""Portable contract suite for the agent-launcher package.

Target-owned adaptation of the portable half of the upstream
``tests/test_launcher_contract.py`` at the pinned revision
(infiquetra-claude-plugins#777). The upstream tests that assert premises of
``infiquetra-claude-plugins`` itself (Orchestrate ingestion, Orchestrate's
dependency declaration, the root Claude marketplace) stayed upstream with the
dropped file; every test here resolves the launcher from the package root via
``parents[1]`` rather than a fixed repository depth.
"""
