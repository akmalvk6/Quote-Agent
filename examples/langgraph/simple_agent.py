"""
Simple Agent with LangGraph
A reference implementation showing how to create an agent with custom tools.
"""

import os
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage

# --- Constants ---
OPENAI_API_KEY = "sk-TE5BPNfSh4IOCNpW3I5EDQ"
OPENAI_API_BASE = "http://localhost:4000"
MODEL_NAME = "gemini-2.5-flash"

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
os.environ["OPENAI_API_BASE"] = OPENAI_API_BASE


# --- Tool Definitions ---

@tool
def calculator(operation: str, a: float, b: float) -> float:
    """
    Performs basic arithmetic operations.
    
    Args:
        operation: The operation to perform ('add', 'subtract', 'multiply', 'divide')
        a: First number
        b: Second number
    
    Returns:
        The result of the operation
    """
    print(f"[Tool Call] calculator(operation='{operation}', a={a}, b={b})")
    
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    elif operation == "divide":
        if b == 0:
            raise ValueError("Cannot divide by zero")
        result = a / b
    else:
        raise ValueError(f"Unknown operation: {operation}")
    
    print(f"[Tool Result] {result}")
    return result


@tool
def text_analyzer(text: str, analysis_type: str) -> dict:
    """
    Analyzes text and returns statistics.
    
    Args:
        text: The text to analyze
        analysis_type: Type of analysis ('word_count', 'char_count', 'word_list')
    
    Returns:
        Dictionary containing the analysis results
    """
    print(f"[Tool Call] text_analyzer(text='{text[:50]}...', analysis_type='{analysis_type}')")
    
    if analysis_type == "word_count":
        result = {"word_count": len(text.split())}
    elif analysis_type == "char_count":
        result = {"char_count": len(text)}
    elif analysis_type == "word_list":
        words = text.split()
        result = {"words": words, "unique_words": len(set(words))}
    else:
        raise ValueError(f"Unknown analysis type: {analysis_type}")
    
    print(f"[Tool Result] {result}")
    return result


# --- Agent Configuration ---

tools = [
    calculator,
    text_analyzer,
]

# Create and configure the LLM
llm = ChatOpenAI(
    model=MODEL_NAME,
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_API_BASE
)

# System prompt for the agent
system_prompt = """You are a helpful assistant with access to tools for calculations and text analysis.

When asked to perform calculations, use the calculator tool.
When asked to analyze text, use the text_analyzer tool.

Be concise and clear in your responses. Always use the appropriate tool when available
rather than trying to compute answers yourself."""

# Create the agent (without state_modifier as it's not supported in this version)
simple_agent = create_react_agent(llm, tools=tools)


# --- Agent Interaction Functions ---

def run_agent(query: str, verbose: bool = True) -> str:
    """
    Run the agent with a query.
    
    Args:
        query: The question or prompt to send to the agent
        verbose: Whether to print detailed output
    
    Returns:
        The agent's response as a string
    """
    if verbose:
        print(f"\n>>> Query: {query}")
    
    # Include system prompt in the messages
    from langchain_core.messages import SystemMessage
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=query)
    ]
    response = simple_agent.invoke({"messages": messages})
    
    # Extract the final response
    final_message = response["messages"][-1]
    final_response = final_message.content
    
    if verbose:
        print(f"<<< Response: {final_response}\n")
    
    return final_response


# --- Example Usage ---

def main():
    """Example usage of the simple agent."""
    print("=" * 60)
    print("Simple Agent Demo (LangGraph)")
    print("=" * 60)
    
    # Example 1: Calculator tool
    print("\n--- Example 1: Using Calculator Tool ---")
    run_agent("What is 45 multiplied by 23?")
    
    # Example 2: Text analyzer tool
    print("\n--- Example 2: Using Text Analyzer Tool ---")
    run_agent("How many words are in this sentence: 'The quick brown fox jumps over the lazy dog'?")
    
    # Example 3: Complex calculation
    print("\n--- Example 3: Complex Calculation ---")
    run_agent("If I have 100 dollars and spend 25% of it, then add 50 dollars, how much do I have?")
    
    # Example 4: No tools needed
    print("\n--- Example 4: General Knowledge (No Tools) ---")
    run_agent("What is the capital of France?")


if __name__ == "__main__":
    main()
