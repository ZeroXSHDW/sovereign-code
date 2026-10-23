"""Trust gate for Hugging Face repositories before they are imported.

A GGUF file from an unknown uploader runs on the Mac with the user's data in
reach of its outputs, so a repository must clear three checks before import:
a licence the project recognises, a minimum of public use, and no gating or
privacy that would stop the import from being reproducible. The gate reports
its reasons; the caller decides whether to override it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Licences whose terms allow local use and redistribution of the weights.
PERMISSIVE_LICENCES = frozenset(
    {
        "apache-2.0",
        "mit",
        "bsd-2-clause",
        "bsd-3-clause",
        "isc",
        "mpl-2.0",
        "gemma",
        "llama3",
        "llama3.1",
        "llama3.2",
        "qwen",
        "cc-by-4.0",
    }
)
MIN_DOWNLOADS = 1000


@dataclass(frozen=True)
class Assessment:
    trusted: bool
    reasons: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return "trusted" if self.trusted else "; ".join(self.reasons)


def assess(
    *,
    license: str,
    downloads: int,
    gated: str = "",
    private: bool = False,
) -> Assessment:
    reasons: list[str] = []
    licence = (license or "").strip().lower()
    if not licence:
        reasons.append("no licence declared")
    elif licence not in PERMISSIVE_LICENCES:
        reasons.append(f"licence '{licence}' is not on the permissive list")
    if downloads < MIN_DOWNLOADS:
        reasons.append(f"{downloads} downloads is below {MIN_DOWNLOADS}")
    if gated:
        reasons.append(f"gated repository ({gated})")
    if private:
        reasons.append("private repository")
    return Assessment(trusted=not reasons, reasons=reasons)
