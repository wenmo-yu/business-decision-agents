"""经营知识子智能体配置。"""

from app.agent.prompts import sub_agents_content
from app.tools.knowledge_tools import search_internal_knowledge

knowledge_base_agent = {
    "name": sub_agents_content["knowledge_base"]["name"],
    "description": sub_agents_content["knowledge_base"]["description"],
    "system_prompt": sub_agents_content["knowledge_base"]["system_prompt"],
    "tools": [search_internal_knowledge],
}
