from dotenv import load_dotenv
from langchain.globals import set_verbose
from rag.retriever import VectorRetriever

from utils.logging import get_logger

set_verbose(False)

logger = get_logger(__name__)

if __name__ == "__main__":
    load_dotenv()
    query = """
        I am author_4.
        
        Could you please draft a LinkedIn post discussing RAG systems?
        I'm particularly interested in how RAG works and how it is integrated with vector DBs and large language models (LLMs).
        """
    retriever = VectorRetriever(query=query)
    hits = retriever.retrieve_top_k(k=6, to_expand_to_n_queries=3)

    reranked_hits = retriever.rerank(documents=hits, keep_top_k=3)
    
    logger.info("Reranked hits:")
    for rank, hit in enumerate(reranked_hits):
        logger.info(f"{rank}: {hit[:100]}...")
