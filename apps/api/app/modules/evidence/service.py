"""M07 claim-to-source projection (R21-R23).

No approved corpus is registered (content/corpus is disabled), so the evidence
list is always empty; possible explanations are the model's general medical knowledge (ADR-015). No outbound gateway
exists in this build; nothing is fetched from the network.
"""
from __future__ import annotations

from typing import Any

from app.core.security import SessionInfo
from app.modules.guidance.service import readable_guidance


def case_sources(ctx, session: SessionInfo, case_id: str) -> dict[str, Any]:
    with ctx.db.read() as conn:
        guidance = readable_guidance(conn, session, case_id)
    return {"claims": guidance["claims"], "evidence": []}
