"""

Smart Quoting Agent 
---------------------------------------
Runs using Google ADK framework with LLM Gateway integration.
Auto-creates mock product + quote data and generates professional quotes.
"""

import asyncio, os, uuid, json, csv
from pathlib import Path
import pandas as pd
import openai
from typing import AsyncGenerator, Any
from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.runners import Runner, types
from google.adk.sessions import InMemorySessionService

# === Environment / constants ===
os.environ["OPENAI_API_BASE"] = "http://localhost:4000"
os.environ["OPENAI_API_KEY"]  = "sk-TE5BPNfSh4IOCNpW3I5EDQ"

APP_NAME   = "smart_quote_app"
USER_ID    = "user_demo"
SESSION_ID = "session_demo"
MODEL_NAME = "gemini-2.5-flash"

# Custom LLM class that bridges Google ADK with LLM Gateway
class LLMGatewayModel(BaseLlm):
    """Custom LLM that uses OpenAI client to call Gemini through LLM Gateway"""
    
    def __init__(self, model_name: str = MODEL_NAME):
        # Initialize with required model field for BaseLlm
        super().__init__(model=model_name)
        self._model_name = model_name  # Store model name privately
        self._client = openai.AsyncOpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ["OPENAI_API_BASE"]
        )
        # Store tool functions for execution (will be set later)
        self._tools_map = None
    
    def _get_tools_map(self):
        """Get tools map, initializing if needed"""
        if self._tools_map is None:
            try:
                self._tools_map = {
                    "price_lookup": globals()["price_lookup"],
                    "discount_calculator": globals()["discount_calculator"],
                    "historical_match": globals()["historical_match"],
                    "quote_generator": globals()["quote_generator"]
                }
                print(f"🔧 [DEBUG] Tools map initialized with: {list(self._tools_map.keys())}")
            except KeyError as e:
                print(f"❌ [DEBUG] Tool function not found: {e}")
                self._tools_map = {}
        return self._tools_map
    
    async def generate_content_async(self, llm_request, **kwargs) -> AsyncGenerator[Any, None]:
        """Convert ADK request to OpenAI format and stream back response"""
        try:
            print(f"🔄 [DEBUG] generate_content_async called")
            
            # Convert ADK format to OpenAI messages
            messages = []
            
            for content in llm_request.contents:
                if content.role == "user":
                    messages.append({"role": "user", "content": content.parts[0].text})
                elif content.role == "model":
                    messages.append({"role": "assistant", "content": content.parts[0].text})
                elif content.role == "system":
                    messages.append({"role": "system", "content": content.parts[0].text})
            
            print(f"📨 [DEBUG] Converted {len(messages)} messages")
            
            # Handle tools if present
            tools = None
            if hasattr(llm_request, 'tools') and llm_request.tools:
                tools = []
                print(f"🔧 Converting {len(llm_request.tools)} tools to OpenAI format")
                for tool in llm_request.tools:
                    # Convert ADK tool format to OpenAI format
                    func_decl = tool.function_declarations[0]
                    openai_tool = {
                        "type": "function",
                        "function": {
                            "name": func_decl.name,
                            "description": func_decl.description,
                            "parameters": func_decl.parameters if hasattr(func_decl, 'parameters') else {}
                        }
                    }
                    tools.append(openai_tool)
                    print(f"   • {func_decl.name}: {func_decl.description}")
            else:
                print("⚠️  No tools found in request")
            
            # Make request to LLM Gateway (non-streaming for compatibility)
            openai_kwargs = {
                "model": self._model_name,
                "messages": messages,
                "stream": False  # Disable streaming for now to get complete response
            }
            if tools:
                openai_kwargs["tools"] = tools
                openai_kwargs["tool_choice"] = "auto"
            
            print(f"🌐 [DEBUG] Making request to LLM Gateway with {len(tools) if tools else 0} tools")
            response = await self._client.chat.completions.create(**openai_kwargs)
            print(f"✅ [DEBUG] Got response from LLM Gateway")
            
            # Check if LLM wants to call tools
            choice = response.choices[0] if response.choices else None
            if choice and choice.message.tool_calls:
                print(f"🔧 LLM requested {len(choice.message.tool_calls)} tool calls")
                tools_map = self._get_tools_map()
                
                # Add assistant message with tool calls to conversation
                messages.append({
                    "role": "assistant", 
                    "content": choice.message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function", 
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                        } for tc in choice.message.tool_calls
                    ]
                })
                
                # Execute each tool call
                for tool_call in choice.message.tool_calls:
                    func_name = tool_call.function.name
                    try:
                        func_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError as e:
                        print(f"❌ Failed to parse tool arguments: {e}")
                        func_args = {}
                    
                    print(f"🛠️ Executing {func_name} with args: {func_args}")
                    
                    if func_name in tools_map:
                        try:
                            result = tools_map[func_name](**func_args)
                            print(f"✅ Tool {func_name} result: {result}")
                        except Exception as tool_error:
                            result = {"error": str(tool_error)}
                            print(f"❌ Tool {func_name} error: {result}")
                            import traceback
                            print(f"📍 Tool error traceback: {traceback.format_exc()}")
                    else:
                        result = {"error": f"Unknown tool: {func_name}"}
                        print(f"❌ Unknown tool: {func_name}")
                    
                    # Add tool response to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result)
                    })
                
                # Make another call with tool results
                print(f"🔄 [DEBUG] Making follow-up request with tool results")
                response = await self._client.chat.completions.create(
                    model=self._model_name,
                    messages=messages,
                    stream=False
                )
                print(f"✅ [DEBUG] Got follow-up response")
            else:
                print("ℹ️ [DEBUG] No tool calls requested by LLM")

            # Create ADK-compatible response object
            class ADKUsageMetadata:
                def __init__(self, openai_usage):
                    self.prompt_token_count = openai_usage.prompt_tokens
                    self.candidates_token_count = openai_usage.completion_tokens
                    self.total_token_count = openai_usage.total_tokens
                    
            class ADKFinishReason:
                def __init__(self, openai_finish_reason):
                    self.value = openai_finish_reason or "stop"
                    
            class ADKPart:
                def __init__(self, text):
                    self.text = text
                    
            class ADKContent:
                def __init__(self, text):
                    self.parts = [ADKPart(text)] if text else []
                    
            class ADKResponse:
                """Response wrapper to match Google ADK expected format"""
                def __init__(self, openai_response):
                    self.usage_metadata = ADKUsageMetadata(openai_response.usage)
                    
                    # Handle choices
                    if openai_response.choices:
                        choice = openai_response.choices[0]
                        self.finish_reason = ADKFinishReason(choice.finish_reason)
                        self.content = ADKContent(choice.message.content)
                    else:
                        self.finish_reason = ADKFinishReason("stop")
                        self.content = ADKContent("")
                    
                    # Additional attributes expected by Google ADK
                    self.partial = False
                
                def model_dump(self, exclude_none=True):
                    """Pydantic-style model_dump method expected by Google ADK"""
                    result = {
                        'usage_metadata': {
                            'prompt_token_count': self.usage_metadata.prompt_token_count,
                            'candidates_token_count': self.usage_metadata.candidates_token_count,
                            'total_token_count': self.usage_metadata.total_token_count
                        },
                        'finish_reason': self.finish_reason.value,
                        'content': {
                            'parts': [{'text': part.text} for part in self.content.parts]
                        },
                        'partial': self.partial
                    }
                    
                    if exclude_none:
                        result = {k: v for k, v in result.items() if v is not None}
                    
                    return result
                
                def __str__(self):
                    return self.content.parts[0].text if self.content.parts else ""
            
            # Yield the complete response
            yield ADKResponse(response)
                    
        except Exception as e:
            print(f"LLM Gateway Error: {e}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            
            # Return a simple error response
            class ErrorResponse:
                def __init__(self, text):
                    self.content = text
                    self.usage_metadata = None
                    self.tool_calls = None
                    
                def __str__(self):
                    return self.content
            
            yield ErrorResponse(f"Error: {str(e)}")

DATA_DIR   = Path("data")
# Ensure n8n can find the files - use the exact path n8n monitors
OUT_DIR    = Path("/workspaces/agentx-hackathon-DC-Pros/n8n/local-files/quotes")
DATA_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

PRODUCTS_CSV = DATA_DIR / "products.csv"
HISTORY_CSV  = DATA_DIR / "historical_quotes.csv"
LOG_CSV      = DATA_DIR / "quotes_log.csv"

# === Auto-create mock datasets (tiny but realistic) ===
def ensure_data():
    if not PRODUCTS_CSV.exists():
        pd.DataFrame([
            {"sku":"CH-100","name":"Office Chair","unit_price":1500,"tier":"standard"},
            {"sku":"TB-200","name":"Conference Table","unit_price":12000,"tier":"premium"},
            {"sku":"DS-300","name":"Developer Desk","unit_price":8000,"tier":"standard"},
            {"sku":"ST-400","name":"Visitor Stool","unit_price":900,"tier":"basic"},
        ]).to_csv(PRODUCTS_CSV, index=False)

    if not HISTORY_CSV.exists():
        pd.DataFrame([
            {"quote_id":"Q001","customer":"ABC Corp","product":"Office Chair",
             "qty":100,"unit_price":1400,"total":140000,"accepted":"Yes","notes":"bulk discount"},
            {"quote_id":"Q002","customer":"XYZ Ltd","product":"Conference Table",
             "qty":10,"unit_price":11000,"total":110000,"accepted":"No","notes":"requested warranty"},
        ]).to_csv(HISTORY_CSV, index=False)

ensure_data()

# === Tool functions with proper type annotations ===
def price_lookup(product_name: str) -> dict:
    """Return product info by fuzzy match.
    
    Args:
        product_name: Name of the product to search for
        
    Returns:
        Dictionary with product information or error message
    """
    df = pd.read_csv(PRODUCTS_CSV)
    # Make search more flexible - try partial matches and different variations
    search_terms = [
        product_name.lower(),
        product_name.lower().replace('chairs', 'chair'),
        product_name.lower().replace('tables', 'table'),
        product_name.lower().replace('desks', 'desk')
    ]
    
    for term in search_terms:
        hits = df[df["name"].str.lower().str.contains(term)]
        if not hits.empty:
            row = hits.iloc[0].to_dict()
            return {"found":True, **row}
    
    return {"found":False,"message":f"No product matching '{product_name}'. Available products: {', '.join(df['name'].tolist())}"}

def discount_calculator(unit_price: float, qty: int, customer_type: str = "regular") -> dict:
    """Calculate tiered discounts.
    
    Args:
        unit_price: Price per unit
        qty: Quantity
        customer_type: Type of customer ("regular" or "preferred")
        
    Returns:
        Dictionary with discount percentage and total price
    """
    disc = 0.1 if qty>=100 else 0.05 if qty>=50 else 0.0
    if customer_type=="preferred": disc += 0.05
    total = unit_price*qty*(1-disc)
    return {"discount_pct":disc, "total":total}

def historical_match(product_name: str, top_k: int = 2) -> list:
    """Return top k historical quotes mentioning the product.
    
    Args:
        product_name: Name of the product to search for
        top_k: Maximum number of historical quotes to return
        
    Returns:
        List of historical quote records
    """
    df = pd.read_csv(HISTORY_CSV)
    hits = df[df["product"].str.lower().str.contains(product_name.lower())]
    return hits.head(top_k).to_dict(orient="records")

def quote_generator(customer: str, items_json: str, terms: str = "Standard T&C apply.") -> dict:
    """Compose & save quote JSON.
    
    Args:
        customer: Customer name
        items_json: JSON string of items list, e.g. '[{"name":"Chair","qty":10,"unit_price":1500,"total":15000}]'
        terms: Terms and conditions
        
    Returns:
        Dictionary with quote information including quote ID
    """
    try:
        items = json.loads(items_json) if items_json else []
    except json.JSONDecodeError:
        return {"error": "Invalid items_json format. Expected JSON array string."}
    
    qid = f"Q-{uuid.uuid4().hex[:6].upper()}"
    subtotal = sum(i.get("unit_price", 0) * i.get("qty", 0) for i in items)
    total = sum(i.get("total", 0) for i in items)
    quote = {"quote_id": qid, "customer": customer, "items": items,
             "subtotal": subtotal, "total": total, "terms": terms}
    
    with open(OUT_DIR / f"{qid}.json", "w") as f: 
        json.dump(quote, f, indent=2)
    
    with open(LOG_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["quote_id", "customer", "total"])
        if f.tell() == 0: 
            w.writeheader()
        w.writerow({"quote_id": qid, "customer": customer, "total": total})
    
    return quote

# === Google ADK Agent Setup ===
tools = [price_lookup, discount_calculator, historical_match, quote_generator]

smart_agent = LlmAgent(
    model=LLMGatewayModel(model_name=MODEL_NAME),
    name="Smart_Quoting_Agent",
    description="Agent that generates sales quotes from requests using LLM Gateway.",
    instruction="""
You are a Smart Quoting Agent. You have these exact tools available:
- price_lookup(product_name: str) -> dict
- discount_calculator(unit_price: float, qty: int, customer_type: str = "regular") -> dict  
- historical_match(product_name: str, top_k: int = 2) -> list
- quote_generator(customer: str, items_json: str, terms: str = "Standard T&C apply.") -> dict

FOR ANY QUOTE REQUEST:
Step 1: Call price_lookup("product name") to get pricing
Step 2: Call discount_calculator(price, quantity, "regular" or "preferred") 
Step 3: Call quote_generator(customer_name, '[{"name":"product","qty":N,"unit_price":P,"total":T}]')

DO NOT generate formatted quotes as text. You MUST use the quote_generator tool to save quotes to files.

Example: For "5 chairs for TestCorp":
1. price_lookup("Office Chair") 
2. discount_calculator(1500, 5, "regular")
3. quote_generator("TestCorp", '[{"name":"Office Chair","qty":5,"unit_price":1500,"total":7500}]')

Always use tools. Never skip tools.
""",
    tools=tools,
    output_key="quote_response"
)

session_service = InMemorySessionService()
runner = Runner(agent=smart_agent, app_name=APP_NAME, session_service=session_service)

# === Google ADK Runner Implementation ===
async def run_agent_async(prompt: str):
    """Run the Google ADK agent with the given prompt"""
    print(f"\n🤖 Processing: {prompt}")
    
    try:
        # Use a unique session ID for each request to avoid conflicts
        unique_session_id = f"{SESSION_ID}_{uuid.uuid4().hex[:8]}"
        
        await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=unique_session_id)
        user_content = types.Content(role="user", parts=[types.Part(text=prompt)])
        final = None
        
        async for e in runner.run_async(user_id=USER_ID, session_id=unique_session_id, new_message=user_content):
            if e.is_final_response() and e.content and e.content.parts:
                final = e.content.parts[0].text
                
        print(f"\n✅ Response: {final or 'No response'}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        print(f"📍 Traceback: {traceback.format_exc()}")


# === Simple Test Function ===
def test_quote_generator_directly():
    """Test quote_generator function directly to verify it works"""
    print("\n🧪 === Testing quote_generator directly ===")
    test_items = '[{"name":"Office Chair","qty":5,"unit_price":1500,"total":7500}]'
    result = quote_generator("Test Direct Corp", test_items, "Direct test terms")
    print(f"Direct test result: {result}")
    
    # Check if file was created
    quote_files = list(OUT_DIR.glob("*.json"))
    print(f"Files in quotes directory: {[f.name for f in quote_files]}")
    return len(quote_files) > 0

# === Demo ===
async def main():
    print("\n🎯 === Smart Quoting Agent Demo (Google ADK + LLM Gateway) ===")
    print("📦 Available products:")
    df = pd.read_csv(PRODUCTS_CSV)
    for _, row in df.iterrows():
        print(f"   • {row['name']} (${row['unit_price']}) - {row['tier']}")
    
    print(f"\n📁 Quotes will be saved to: {OUT_DIR.absolute()}")
    
    # First test the quote_generator function directly
    direct_test_works = test_quote_generator_directly()
    print(f"Direct test result: {'✅ PASSED' if direct_test_works else '❌ FAILED'}")
    
    if not direct_test_works:
        print("❌ quote_generator function itself is not working. Stopping tests.")
        return
    
    print("\n--- Demo 1: Generate quote ---")
    await run_agent_async("Create a quote for 120 Office Chairs for ABC Corp, preferred customer.")
    
    # Check if files were created after each demo
    quote_files = list(OUT_DIR.glob("*.json"))
    print(f"\n📄 Quote files created so far: {len(quote_files)}")
    for file in quote_files:
        print(f"   • {file.name}")
        # Show first few lines of the file
        try:
            with open(file, 'r') as f:
                content = json.load(f)
                print(f"     Customer: {content.get('customer', 'N/A')}")
                print(f"     Items: {len(content.get('items', []))}")
        except Exception as e:
            print(f"     Error reading file: {e}")
    
    print("\n--- Demo 2: Ask for missing info ---")
    await run_agent_async("Need chairs and desks but didn't decide quantities.")
    
    print("\n--- Demo 3: Complete workflow ---")
    await run_agent_async("I need 50 Conference Tables for XYZ Ltd, they are a regular customer. Please create a complete quote with discounts.")
    
    # Final check
    quote_files = list(OUT_DIR.glob("*.json"))
    print(f"\n📄 Total quote files created: {len(quote_files)}")
    for file in quote_files:
        print(f"   • {file.name}")

if __name__ == "__main__":
    asyncio.run(main())