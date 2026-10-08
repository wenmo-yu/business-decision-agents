"""经营知识子智能体配置。"""

from app.agent.prompts import sub_agents_content
from app.tools.ragflow_tools import create_ask_delete, get_assistant_list

knowledge_base_agent = {
    "name": sub_agents_content["knowledge_base"]["name"],
    "description": sub_agents_content["knowledge_base"]["description"],
    "system_prompt": sub_agents_content["knowledge_base"]["system_prompt"],
    "tools": [get_assistant_list, create_ask_delete],
}
