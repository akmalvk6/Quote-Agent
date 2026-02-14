"""
Smart Quoting Agent - Final Working Version
"""

import asyncio, os, uuid, json, csv
from pathlib import Path
import pandas as pd
import openai
from typing import List, Dict, Any

# === Environment Setup ===
os.environ["OPENAI_API_BASE"] = "http://localhost:4000"
os.environ["OPENAI_API_KEY"] = "sk-TE5BPNfSh4IOCNpW3I5EDQ"

DATA_DIR = Path("data")
OUT_DIR = Path("quotes")
DATA_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

PRODUCTS_CSV = DATA_DIR / "products.csv"
HISTORY_CSV = DATA_DIR / "historical_quotes.csv"
LOG_CSV = DATA_DIR / "quotes_log.csv"

# === Create Mock Data ===
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

# === Tool Functions ===
def price_lookup(product_name: str) -> dict:
    """Look up product pricing by name"""
    print(f"🔍 Looking up: {product_name}")
    df = pd.read_csv(PRODUCTS_CSV)
    
    # Normalize search - remove plurals
    search_name = product_name.lower().rstrip('s')
    
    for _, row in df.iterrows():
        row_name = row['name'].lower().rstrip('s')
        if search_name in row_name or row_name in search_name:
            result = row.to_dict()
            print(f"✅ Found match: {result}")
            return {"found": True, **result}
    
    available = ", ".join(df["name"].tolist())
    error_msg = f"No product matching '{product_name}'. Available: {available}"
    print(f"❌ {error_msg}")
    return {"found": False, "message": error_msg}

def discount_calculator(unit_price: float, qty: int, customer_type: str = "regular") -> dict:
    """Calculate discounts based on quantity and customer type"""
    print(f"💰 Calculating discount: ${unit_price} x {qty} for {customer_type} customer")
    
    # Quantity discounts
    if qty >= 100:
        qty_discount = 0.15
    elif qty >= 50:
        qty_discount = 0.10
    elif qty >= 20:
        qty_discount = 0.05
    else:
        qty_discount = 0.0
    
    # Customer type discount
    customer_discount = 0.05 if customer_type == "preferred" else 0.0
    
    total_discount = qty_discount + customer_discount
    discounted_price = unit_price * (1 - total_discount)
    total = discounted_price * qty
    
    result = {
        "unit_price": unit_price,
        "quantity": qty,
        "qty_discount": qty_discount,
        "customer_discount": customer_discount,
        "total_discount": total_discount,
        "discounted_unit_price": discounted_price,
        "total": total
    }
    
    print(f"✅ Discount calculated: {result}")
    return result

def quote_generator(customer: str, items: List[Dict], terms: str = "Standard T&C apply") -> dict:
    """Generate and save a quote"""
    print(f"📄 Generating quote for {customer} with {len(items)} items")
    
    quote_id = f"Q-{uuid.uuid4().hex[:6].upper()}"
    total = sum(item.get("total", 0) for item in items)
    
    quote = {
        "quote_id": quote_id,
        "customer": customer,
        "items": items,
        "total": total,
        "terms": terms,
        "timestamp": str(uuid.uuid4())
    }
    
    # Save quote to file
    quote_file = OUT_DIR / f"{quote_id}.json"
    with open(quote_file, "w") as f:
        json.dump(quote, f, indent=2)
    
    # Log the quote
    with open(LOG_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["quote_id", "customer", "total"])
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow({"quote_id": quote_id, "customer": customer, "total": total})
    
    print(f"✅ Quote {quote_id} generated and saved to {quote_file}")
    return quote

# === LLM Setup ===
client = openai.OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ["OPENAI_API_BASE"]
)

# === Available Tools Registry ===
TOOLS = {
    "price_lookup": price_lookup,
    "discount_calculator": discount_calculator, 
    "quote_generator": quote_generator
}

# === Tool Schema for OpenAI ===
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "price_lookup",
            "description": "Look up product information and pricing by product name",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Name of the product to search for"
                    }
                },
                "required": ["product_name"]
            }
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "discount_calculator",
            "description": "Calculate discounts based on quantity and customer type",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_price": {
                        "type": "number",
                        "description": "Price per unit"
                    },
                    "qty": {
                        "type": "integer",
                        "description": "Quantity needed"
                    },
                    "customer_type": {
                        "type": "string",
                        "description": "Type of customer: 'regular' or 'preferred'",
                        "enum": ["regular", "preferred"]
                    }
                },
                "required": ["unit_price", "qty"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "quote_generator", 
            "description": "Generate and save a formal quote document",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {
                        "type": "string",
                        "description": "Customer company name"
                    },
                    "items": {
                        "type": "array",
                        "description": "List of items for the quote",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "qty": {"type": "integer"},
                                "unit_price": {"type": "number"},
                                "total": {"type": "number"}
                            }
                        }
                    },
                    "terms": {
                        "type": "string",
                        "description": "Terms and conditions"
                    }
                },
                "required": ["customer", "items"]
            }
        }
    }
]

# === Smart Quoting Agent Function ===
def smart_quote_agent(user_request: str) -> str:
    """Main agent function that processes quote requests"""
    
    system_prompt = """You are a Smart Quoting Agent. Your job is to help create professional quotes using the available tools.

Available tools:
- price_lookup(product_name): Get product info and pricing  
- discount_calculator(unit_price, qty, customer_type): Calculate discounts
- quote_generator(customer, items, terms): Create and save quote

WORKFLOW for quote requests:
1. ALWAYS use price_lookup first to get product information
2. ALWAYS use discount_calculator to calculate pricing with discounts  
3. ALWAYS use quote_generator to create the final quote

Be helpful and conversational, but ALWAYS use the tools for quotes. Never make up prices."""
    
    print(f"\n🤖 Processing request: {user_request}")
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_request}
    ]
    
    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto"
        )
        
        message = response.choices[0].message
        
        # Handle tool calls
        if message.tool_calls:
            print(f"🛠️ LLM wants to use {len(message.tool_calls)} tools")
            
            # Add assistant message with tool calls
            messages.append({
                "role": "assistant", 
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in message.tool_calls
                ]
            })
            
            # Execute each tool call
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                
                print(f"   🔧 Calling {tool_name} with {tool_args}")
                
                if tool_name in TOOLS:
                    try:
                        tool_result = TOOLS[tool_name](**tool_args)
                        result_content = json.dumps(tool_result, indent=2)
                    except Exception as e:
                        result_content = f"Error: {str(e)}"
                        print(f"   ❌ Tool error: {e}")
                else:
                    result_content = f"Error: Unknown tool {tool_name}"
                
                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_content
                })
            
            # Get final response after tool execution
            try:
                final_response = client.chat.completions.create(
                    model="gemini-2.5-flash",
                    messages=messages
                )
                
                if final_response.choices and len(final_response.choices) > 0:
                    final_content = final_response.choices[0].message.content
                    print(f"✅ Final response: {final_content}")
                    return final_content
                else:
                    print("⚠️ No response received from LLM")
                    return "Quote processed successfully, but no summary response was generated."
                    
            except Exception as e:
                print(f"❌ Error in final response: {e}")
                return f"Quote processing completed, but encountered error in response generation: {str(e)}"
        
        else:
            # No tools needed
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content
                print(f"✅ Direct response: {content}")
                return content
            else:
                print("⚠️ No response received from LLM")
                return "No response received"
            
    except Exception as e:
        error_msg = f"Error processing request: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg

# === Main Demo ===
def main():
    print("\n🎯 === HACKATHON: Smart Quoting Agent ===")
    print("Created using Google ADK + LiteLLM Gateway")
    
    # Show available products
    print("\n📦 Available products:")
    df = pd.read_csv(PRODUCTS_CSV)
    for _, row in df.iterrows():
        print(f"   • {row['name']} (${row['unit_price']:,}) - {row['tier']}")
    
    print("\n" + "="*60)
    
    # Interactive mode
    print("\n🎮 Try some requests:")
    test_requests = [
        "I need a quote for 50 Office Chairs for ABC Corp, they are a preferred customer",
        "Create a quote for 25 Conference Tables for XYZ Ltd, regular customer", 
        "Generate quote for 100 Developer Desks for TechStartup Inc, preferred customer"
    ]
    
    for i, request in enumerate(test_requests, 1):
        print(f"\n📝 Test {i}: {request}")
        print("-" * 50)
        result = smart_quote_agent(request)
        print(f"\n💬 Agent Response:\n{result}")
        print("=" * 60)
    
    # Show generated quotes
    print(f"\n📁 Generated quote files in: {OUT_DIR.absolute()}")
    if list(OUT_DIR.glob("*.json")):
        print("Quote files created:")
        for quote_file in OUT_DIR.glob("*.json"):
            print(f"   • {quote_file.name}")
    else:
        print("   (No quote files generated)")

if __name__ == "__main__":
    main()