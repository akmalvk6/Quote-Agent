#!/usr/bin/env python3
"""
Test script for the Smart Quoting Agent
"""

import asyncio
import sys
sys.path.insert(0, '.')

from simple_agent import run_agent_async, session_service, APP_NAME

async def test_quoting_agent():
    """Test all features of the smart quoting agent"""
    
    print("🚀 Testing Smart Quoting Agent for Hackathon")
    print("=" * 60)
    
    # Create test session
    test_user = "hackathon_tester"
    test_session = "test_session_001"
    
    try:
        await session_service.create_session(
            app_name=APP_NAME, 
            user_id=test_user, 
            session_id=test_session
        )
        print(f"✅ Session created: {test_session}")
    except:
        print(f"📝 Session already exists: {test_session}")
    
    # Test cases for the smart quoting agent
    test_cases = [
        {
            "name": "Price Lookup Test",
            "query": "What's the price for a laptop computer?",
            "expected_tool": "price_lookup"
        },
        {
            "name": "Discount Calculation Test", 
            "query": "Calculate a 15% discount on $1000",
            "expected_tool": "discount_calculator"
        },
        {
            "name": "Quote Generation Test",
            "query": "Generate a quote for 5 laptops with 10% bulk discount",
            "expected_tool": "generate_quote"
        },
        {
            "name": "Customer Info Test",
            "query": "Look up customer information for John Smith",
            "expected_tool": "customer_lookup"
        },
        {
            "name": "Complex Quote Test",
            "query": "I need a quote for 3 laptops and 2 monitors for ABC Corp with standard business discount",
            "expected_tool": "multiple tools"
        }
    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n🧪 Test {i}: {test['name']}")
        print(f"Query: {test['query']}")
        print("-" * 40)
        
        try:
            response = await run_agent_async(test['query'])
            
            if response:
                print(f"✅ Response received")
                print(f"📝 Content: {response}")
            else:
                print("❌ No response received")
                
        except Exception as e:
            print(f"❌ Error in test {i}: {str(e)}")
        
        print("\n" + "="*60)
    
    print("\n🎯 Hackathon Demo Complete!")

if __name__ == "__main__":
    asyncio.run(test_quoting_agent())