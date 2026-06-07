from graphiti_core import Graphiti
from graphiti_core.llm_client.openai_client import OpenAIClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from openai import AsyncOpenAI

# =========================================================
# CONFIG
# =========================================================

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_API_KEY = "ollama"
LLM_MODEL = "qwen2.5:3b"
EMBED_MODEL = "nomic-embed-text"

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "friday123"

# =========================================================
# CLIENT
# =========================================================


def get_graphiti() -> Graphiti:
    ollama_async_client = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key=OLLAMA_API_KEY)

    llm_config = LLMConfig(
        api_key=OLLAMA_API_KEY,
        model=LLM_MODEL,
        base_url=OLLAMA_BASE_URL,
        small_model=LLM_MODEL,
    )

    llm_client = OpenAIClient(config=llm_config)

    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            embedding_model=EMBED_MODEL,
            api_key=OLLAMA_API_KEY,
            base_url=OLLAMA_BASE_URL,
        )
    )

    reranker = OpenAIRerankerClient(config=llm_config)

    return Graphiti(
        uri=NEO4J_URI,
        user=NEO4J_USER,
        password=NEO4J_PASSWORD,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=reranker,
    )
