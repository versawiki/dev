"""Ontology + taxonomy seed files.

The contents of `aec_starter_taxonomy.yaml` are loaded by the schema provisioner
(M1-BE-03) when a new tenant's first ingestion run determines the corpus is
AEC-shaped. See `docs/architecture/v1.md` §1.4 and DECISIONS.md
("Starter taxonomy = AEC lifted from the project-docs-* MCPs").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SEEDS_DIR = Path(__file__).parent


def load_aec_starter_taxonomy() -> dict[str, Any]:
    """Load the AEC starter taxonomy YAML as a dict."""
    with open(SEEDS_DIR / "aec_starter_taxonomy.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


__all__ = ["SEEDS_DIR", "load_aec_starter_taxonomy"]
