import re

from app.agentic.states import GraphState


def create_verify_node():
    async def node_verify(state: GraphState) -> dict:
        evidence_ids = {
            f"E{index}"
            for index, _ in enumerate(state.get("retrieval_evidence", []), start=1)
        }
        combined = "\n".join(
            [state.get("analyst_report", ""), state.get("coach_advice", "")]
        )
        cited_ids = set(re.findall(r"\bE\d+\b", combined))
        unknown_citations = sorted(cited_ids - evidence_ids)
        claim_lines = [
            line.strip()
            for line in state.get("coach_advice", "").splitlines()
            if line.strip() and re.search(r"建议|说明|问题|需要|应当|because|should|must", line, re.I)
        ]
        uncited_claims = [line for line in claim_lines if not re.search(r"\[E\d+\]", line)]
        return {
            "verification_report": {
                "status": "needs_review" if unknown_citations or uncited_claims else "pass",
                "evidence_count": len(evidence_ids),
                "cited_evidence_ids": sorted(cited_ids & evidence_ids),
                "unknown_citations": unknown_citations,
                "uncited_claim_count": len(uncited_claims),
            }
        }

    return node_verify
