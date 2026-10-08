"""
大模型初始化模块

负责从 .env 中读取模型配置，并创建项目统一复用的模型对象
后续主智能体和子智能体都从这里导入 model，避免在多个文件里重复加载环境变量
"""

import os

from dotenv import find_dotenv, load_dotenv
from langchain.chat_models import init_chat_model

# find_dotenv 会从当前目录向上查找 .env，适合脚本和 Web 服务从不同入口启动的场景
load_dotenv(find_dotenv())

# 使用 OpenAI 兼容协议接入模型；具体模型名由 .env 中的 LLM_QWEN_MAX 控制
model = init_chat_model(
    # 使用默认模型名保证未创建 .env 时 API 仍可启动；真正调用前仍需配置 API Key。
    model=os.getenv("LLM_QWEN_MAX", "qwen-max"),
    model_provider="openai",
    api_key=os.getenv("OPENAI_API_KEY", "not-configured"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)
