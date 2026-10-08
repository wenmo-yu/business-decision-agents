"""经营问数助手：通过服务边界复用独立的 Text-to-SQL 项目。"""

from app.agent.prompts import sub_agents_content
from app.tools.commerce_analytics_tool import commerce_analytics_query

database_query_agent = {
    "name": sub_agents_content["commerce_analytics"]["name"],
    "description": sub_agents_content["commerce_analytics"]["description"],
    "system_prompt": sub_agents_content["commerce_analytics"]["system_prompt"],
    "tools": [commerce_analytics_query],
}
