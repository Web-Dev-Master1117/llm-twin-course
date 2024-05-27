from abc import ABC, abstractmethod

from langchain.prompts import PromptTemplate
from pydantic import BaseModel


class BasePromptTemplate(ABC, BaseModel):
    @abstractmethod
    def create_template(self, *args) -> PromptTemplate:
        pass


class QueryExpansionTemplate(BasePromptTemplate):
    prompt: str = """You are an AI language model assistant. Your task is to generate {to_expand_to_n}
    different versions of the given user question to retrieve relevant documents from a vector
    database. By generating multiple perspectives on the user question, your goal is to help
    the user overcome some of the limitations of the distance-based similarity search.
    Provide these alternative questions seperated by '{separator}'.
    Original question: {question}"""

    @property
    def separator(self) -> str:
        return "#next-question#"

    def create_template(self, to_expand_to_n: int) -> PromptTemplate:
        return PromptTemplate(
            template=self.prompt,
            input_variables=["question"],
            partial_variables={
                "separator": self.separator,
                "to_expand_to_n": to_expand_to_n,
            },
        )


class SelfQueryTemplate(BasePromptTemplate):
    prompt: str = """You are an AI language model assistant. Your task is to extract information from a user question.
    The required information that needs to be extracted is the user or author id. 
    Your response should consists of only the extracted id (e.g. 1345256), nothing else.
    User question: {question}"""

    def create_template(self) -> PromptTemplate:
        return PromptTemplate(template=self.prompt, input_variables=["question"])


class RerankingTemplate(BasePromptTemplate):
    prompt: str = """You are an AI language model assistant. Your task is to rerank passages related to a query
    based on their relevance. 
    The most relevant passages should be put at the beginning. 
    You should only pick at max {keep_top_k} passages.
    The provided and reranked documents are separated by '{separator}'.
    
    The following are passages related to this query: {question}.
    
    Passages: 
    {passages}
    """

    def create_template(self, keep_top_k: int) -> PromptTemplate:
        return PromptTemplate(
            template=self.prompt,
            input_variables=["question", "passages"],
            partial_variables={"keep_top_k": keep_top_k, "separator": self.separator},
        )

    @property
    def separator(self) -> str:
        return "\n#next-document#\n"


class InferenceTemplate(BasePromptTemplate):
    simple_prompt: str = """You are an AI language model assistant. Your task is to generate a cohesive and concise response to the user question.
    Question: {question}
    """

    rag_prompt: str = """ You are a specialist in technical content writing. Your task is to create technical content based on a user query given a specific context 
    with additional information consisting of the user's previous writings and his knowledge.
    
    Here is a list of steps that you need to follow in order to solve this task:
    Step 1: You need to analyze the user provided query : {question}
    Step 2: You need to analyze the provided context and how the information in it relates to the user question: {context}
    Step 3: Generate the content keeping in mind that it needs to be as cohesive and concise as possible related to the subject presented in the query and similar to the users writing style and knowledge presented in the context.
    """

    def create_template(self, enable_rag: bool = True) -> PromptTemplate:
        if enable_rag is True:
            return PromptTemplate(
                template=self.rag_prompt, input_variables=["question", "context"]
            )

        return PromptTemplate(template=self.simple_prompt, input_variables=["question"])


class LLMEvaluationTemplate(BasePromptTemplate):
    prompt: str = """
        You are an AI assistant and your task is to evaluate the output generated by another LLM.
        You need to follow these steps:
        Step 1: Analyze the user query: {query}
        Step 2: Analyze the response: {output}
        Step 3: Evaluate the generated response based on the following criteria and provide a score from 1 to 5 along with a brief justification for each criterion:

        Evaluation:
        Relevance - [score]
        [1 sentence justification why relevance = score]
        Coherence - [score]
        [1 sentence justification why coherence = score]
        Conciseness - [score]
        [1 sentence justification why conciseness = score]
    """

    def create_template(self) -> PromptTemplate:
        return PromptTemplate(template=self.prompt, input_variables=["query", "output"])


class RAGEvaluationTemplate(BasePromptTemplate):
    prompt: str = """You are an AI assistant and your task is to evaluate the output generated by another LLM.
    The other LLM generates writing content based on a user query and a given context.
    The given context is comprised of custom data produces by a user that consists of posts, articles or code fragments.
    Here is a list of steps you need to follow in order to solve this task:
    Step 1: You need to analyze the user query : {query}
    Step 2: You need to analyze the given context: {contex}
    Step 3: You need to analyze the generated output: {output}
    Step 4: Generate the evaluation
    When doing the evaluation step you need to take the following into consideration the following:
    -The evaluation needs to have some sort of metrics.
    -The generated content needs to be evaluated based on the writing similarity form the context.
    -The generated content needs to be evaluated based on it's coherence and conciseness related to the given query and context.
    -The generated content needs to be evaluate based on how well it represents the user knowledge extracted from the context."""

    def create_template(self) -> PromptTemplate:
        return PromptTemplate(
            template=self.prompt, input_variables=["query", "context", "output"]
        )
