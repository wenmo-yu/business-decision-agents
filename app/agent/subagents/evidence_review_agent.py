"""证据审查子智能体配置。"""

from app.agent.prompts import sub_agents_content
from app.tools.evidence_tools import evaluate_evidence

evidence_review_agent = {
    "name": sub_agents_content["evidence_review"]["name"],
    "description": sub_agents_content["evidence_review"]["description"],
    "system_prompt": sub_agents_content["evidence_review"]["system_prompt"],
    "tools": [evaluate_evidence],
}
