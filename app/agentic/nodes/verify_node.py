import re

from app.agentic.states import GraphState


def create_verify_node():
    async def node_verify(state: GraphState) -> dict:
        historical_ids = {
            f"E{index}"
            for index, _ in enumerate(state.get("retrieval_evidence", []), start=1)
        }
        current_ids = {
            f"C{index}"
            for index, _ in enumerate(state.get("current_evidence", []), start=1)
        }
        evidence_ids = historical_ids | current_ids
        combined = "\n".join(
            [state.get("analyst_report", ""), state.get("coach_advice", "")]
        )
        cited_ids = set(re.findall(r"\b[CE]\d+\b", combined))
        unknown_citations = sorted(cited_ids - evidence_ids)
        claim_lines = [
            line.strip()
            for line in state.get("coach_advice", "").splitlines()
            if line.strip() and not line.strip().startswith(("**", "#")) and re.search(
                r"建议|说明|问题|需要|应当|必须|应该|表明|显示|意味着|导致|because|should|must|\d+(?:\.\d+)?%",
                line,
                re.I,
            )
        ]
        uncited_claims = [line for line in claim_lines if not re.search(r"\[[CE]\d+\]", line)]
        current_claims = [
            line.strip()
            for line in state.get("coach_advice", "").splitlines()
            if line.strip() and re.search(r"本场|本局|当前比赛|当前 Demo|R\d+", line, re.I)
        ]
        current_claims_without_current_evidence = [
            line for line in current_claims if not re.search(r"\[C\d+\]", line)
        ] if current_ids else []
        missing_outputs = [
            name for name in ("analyst_report", "coach_advice")
            if not str(state.get(name, "")).strip()
        ]
        return {
            "verification_report": {
                "status": "needs_review" if (
                    unknown_citations or uncited_claims or current_claims_without_current_evidence
                    or missing_outputs
                ) else "pass",
                "evidence_count": len(evidence_ids),
                "current_evidence_count": len(current_ids),
                "historical_evidence_count": len(historical_ids),
                "cited_evidence_ids": sorted(cited_ids & evidence_ids),
                "cited_current_evidence_ids": sorted(cited_ids & current_ids),
                "cited_historical_evidence_ids": sorted(cited_ids & historical_ids),
                "unknown_citations": unknown_citations,
                "uncited_claim_count": len(uncited_claims),
                "current_claims_without_current_evidence": len(current_claims_without_current_evidence),
                "missing_outputs": missing_outputs,
            }
        }

    return node_verify
