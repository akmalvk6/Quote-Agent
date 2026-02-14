"""
Smart Quoting Agent - Debugging Version
Let's see what's happening step by step
"""

import openai
import json
import os

# Setup
os.environ["OPENAI_API_BASE"] = "http://localhost:4000"
os.environ["OPENAI_API_KEY"] = "sk-TE5BPNfSh4IOCNpW3I5EDQ"

client = openai.OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ["OPENAI_API_BASE"]
)

# Simple test function
def test_function(name: str) -> str:
    """A simple test function"""
    return f"Hello {name}! This is a test response."

# Tool schema
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "test_function",
        "description": "A simple test function",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name to greet"
                }
            },
            "required": ["name"]
        }
    }
}

def debug_test():
    print("🧪 Testing tool calls with LiteLLM...")
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant with access to tools. Always use the test_function when greeting someone."},
        {"role": "user", "content": "Please greet John using your tool"}
    ]
    
    try:
        print("📤 Sending request...")
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=messages,
            tools=[TOOL_SCHEMA],
            tool_choice="auto"
        )
        
        print(f"📨 Response received: {response}")
        
        message = response.choices[0].message
        print(f"🔍 Message: {message}")
        
        if message.tool_calls:
            print(f"🛠️ Tool calls found: {len(message.tool_calls)}")
            for tool_call in message.tool_calls:
                print(f"   Tool: {tool_call.function.name}")
                print(f"   Args: {tool_call.function.arguments}")
                print(f"   ID: {tool_call.id}")
                
                # Execute tool
                args = json.loads(tool_call.function.arguments)
                result = test_function(**args)
                print(f"   Result: {result}")
                
                # Add messages
                messages.append(message)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
            
            print("📤 Sending follow-up request...")
            final_response = client.chat.completions.create(
                model="gemini-2.5-flash",
                messages=messages
            )
            
            print(f"📨 Final response: {final_response}")
            
            if final_response.choices:
                final_content = final_response.choices[0].message.content
                print(f"✅ Final content: {final_content}")
            else:
                print("❌ No final response choices")
                
        else:
            print("❌ No tool calls found")
            print(f"Direct response: {message.content}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_test()