"""Core business logic for slide generation."""

from .chatbot import Chatbot

try:
    from .chatbot_langchain import ChatbotLangChain
    __all__ = ["Chatbot", "ChatbotLangChain"]
except ImportError:
    # LangChain dependencies not available
    __all__ = ["Chatbot"]

