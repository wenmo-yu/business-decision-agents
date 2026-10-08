"""市场情报子智能体配置。"""

from app.agent.prompts import sub_agents_content
from app.tools.tavily_tool import internet_search

network_search_agent = {
    "name": sub_agents_content["market_intelligence"]["name"],
    "description": sub_agents_content["market_intelligence"]["description"],
    "system_prompt": sub_agents_content["market_intelligence"]["system_prompt"],
    "tools": [internet_search],
}
