"""LLM prompt templates for the skill writer.

The system prompt locks the LLM's role and the privacy contract. The
user prompt is fed ONLY aggregated, anonymized inputs (`SignatureGroup`
fields). Raw tenant text never reaches it.

The prompts are intentionally explicit about the privacy boundary even
though the LLM has no way to reach customer data: the static checker
pipeline is the operational enforcement, but a co-operative LLM
produces fewer rejections, which is cheaper and faster.
"""

from __future__ import annotations

from .aggregator import SignatureGroup


SKILL_WRITER_SYSTEM_PROMPT = """\
You are versawiki's skill writer.

Your job: read an aggregated, anonymized cross-tenant signal and produce
a short Markdown skill that future ingestions can apply to documents in
the same domain.

HARD CONSTRAINTS — your output WILL be rejected by an automatic privacy
checker if it violates any of these:

  1. Do NOT mention any customer name, person name, organization name,
     project name, product name, vendor name, file name, file path, URL,
     email address, or phone number. None of these are in your input —
     and they must not appear in your output either.
  2. Do NOT include raw numerics. Use the bucket labels you see in the
     input (e.g. "11-50", "201-1000"), never literal counts.
  3. Do NOT quote or paraphrase document text. The skill is a
     *generalizable pattern* description, not an excerpt of any tenant's
     content.
  4. Use only members of the controlled vocabulary you see in the input.
     If you describe a relationship, name it the way the input names it
     ("references", "supersedes", etc.).
  5. Output ONLY the markdown body. Do not include a title (the system
     provides one), do not include front-matter, do not wrap in code
     fences.

STYLE: be terse and operational. The reader of a versawiki skill is
another LLM running on tenant data, not a human. Three to eight
paragraphs is plenty. Bullet lists for enumerations.
"""


def build_user_prompt(group: SignatureGroup) -> str:
    """Produce the user prompt for the LLM.

    The fields fed here are all from `SignatureGroup` — they are
    `Literal`-vocabulary strings, bucket labels, counts-of-distinct-things,
    and a confidence mean. There is no raw tenant string.
    """

    lines = [
        f"Domain: {group.domain}",
        f"Kind: {group.kind}",
        f"Distinct tenants observed: {group.distinct_tenants}",
        f"Total observations: {group.observation_count}",
        f"Mean per-observation confidence: {group.mean_confidence:.2f}",
        "",
        "Recurring shape fingerprints (each line is one fingerprint):",
    ]
    if group.shape_examples:
        for s in group.shape_examples:
            lines.append(f"  - {s}")
    else:
        lines.append("  - (none)")
    lines.extend(
        [
            "",
            "Write the markdown body now. Follow the hard constraints in",
            "the system prompt. Do not include a title.",
        ]
    )
    return "\n".join(lines)
