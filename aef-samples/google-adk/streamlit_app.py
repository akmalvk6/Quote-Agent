"""
Smart Quoting Agent - Streamlit Web UI
---------------------------------------
Web interface for the Smart Quoting Agent using Google ADK framework.
"""

import streamlit as st
import asyncio
import json
import pandas as pd
from pathlib import Path
import uuid
from datetime import datetime
import os

# Import the agent components
from simple_agent import (
    smart_agent, session_service, runner, APP_NAME, USER_ID, 
    types, OUT_DIR, PRODUCTS_CSV, HISTORY_CSV
)

# Configure Streamlit page
st.set_page_config(
    page_title="Smart Quoting Agent",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
    }
    .quote-card {
        border: 1px solid #ddd;
        border-radius: 10px;
        padding: 1rem;
        margin: 1rem 0;
        background: #f8f9fa;
    }
    .success-message {
        background: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 5px;
        padding: 0.75rem;
        color: #155724;
    }
    .error-message {
        background: #f8d7da;
        border: 1px solid #f5c6cb;
        border-radius: 5px;
        padding: 0.75rem;
        color: #721c24;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'quote_count' not in st.session_state:
    st.session_state.quote_count = 0

# Header
st.markdown("""
<div class="main-header">
    <h1>🎯 Smart Quoting Agent</h1>
    <p>AI-powered quote generation with Google ADK & LLM Gateway</p>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("📊 Dashboard")
    
    # Product catalog
    st.subheader("📦 Available Products")
    if PRODUCTS_CSV.exists():
        df = pd.read_csv(PRODUCTS_CSV)
        for _, row in df.iterrows():
            st.write(f"• **{row['name']}** - ${row['unit_price']:,} ({row['tier']})")
    
    st.divider()
    
    # Quote statistics
    st.subheader("📈 Statistics")
    quote_files = list(OUT_DIR.glob("*.json"))
    st.metric("Total Quotes", len(quote_files))
    st.metric("Session Quotes", st.session_state.quote_count)
    
    st.divider()
    
    # Recent quotes
    st.subheader("📋 Recent Quotes")
    if quote_files:
        for file in sorted(quote_files, key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
            try:
                with open(file, 'r') as f:
                    quote_data = json.load(f)
                st.write(f"**{quote_data['quote_id']}**")
                st.write(f"Customer: {quote_data['customer']}")
                st.write(f"Total: ${quote_data['total']:,}")
                st.write("---")
            except Exception as e:
                st.write(f"Error reading {file.name}")
    else:
        st.write("No quotes yet")

# Main content area
col1, col2 = st.columns([2, 1])

with col1:
    st.header("💬 Chat with Agent")
    
    # Chat interface
    chat_container = st.container()
    
    # Display chat history
    with chat_container:
        for message in st.session_state.chat_history:
            if message["role"] == "user":
                st.write(f"**You:** {message['content']}")
            else:
                st.write(f"**Agent:** {message['content']}")
            st.write("---")
    
    # Initialize default value for input
    if 'input_value' not in st.session_state:
        st.session_state.input_value = ""
    
    # Chat input with default value from session state
    user_input = st.text_area(
        "Enter your quote request:",
        value=st.session_state.input_value,
        placeholder="e.g., 'Create a quote for 120 Office Chairs for ABC Corp, preferred customer'",
        height=100,
        key="user_input_area"
    )
    
    col_send, col_clear = st.columns([1, 1])
    
    with col_send:
        if st.button("📤 Send Request", type="primary"):
            if user_input.strip():
                # Add user message to history
                st.session_state.chat_history.append({
                    "role": "user",
                    "content": user_input,
                    "timestamp": datetime.now()
                })
                
                # Process with agent
                with st.spinner("🤖 Agent is processing your request..."):
                    try:
                        # Run the agent asynchronously
                        async def process_request():
                            unique_session_id = f"streamlit_{uuid.uuid4().hex[:8]}"
                            await session_service.create_session(
                                app_name=APP_NAME, 
                                user_id=USER_ID, 
                                session_id=unique_session_id
                            )
                            
                            user_content = types.Content(
                                role="user", 
                                parts=[types.Part(text=user_input)]
                            )
                            
                            response_text = ""
                            async for e in runner.run_async(
                                user_id=USER_ID, 
                                session_id=unique_session_id, 
                                new_message=user_content
                            ):
                                if e.is_final_response() and e.content and e.content.parts:
                                    response_text = e.content.parts[0].text
                            
                            return response_text
                        
                        # Run the async function
                        response = asyncio.run(process_request())
                        
                        if response:
                            # Add agent response to history
                            st.session_state.chat_history.append({
                                "role": "agent",
                                "content": response,
                                "timestamp": datetime.now()
                            })
                            
                            # Check if a new quote was created
                            current_quotes = list(OUT_DIR.glob("*.json"))
                            if len(current_quotes) > len(quote_files):
                                st.session_state.quote_count += 1
                                st.success("✅ New quote generated successfully!")
                        else:
                            st.error("❌ No response from agent")
                            
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
                        st.session_state.chat_history.append({
                            "role": "agent",
                            "content": f"Error processing request: {str(e)}",
                            "timestamp": datetime.now()
                        })
                
                # Clear input and rerun to update chat
                st.session_state.input_value = ""
                st.rerun()
    
    with col_clear:
        if st.button("🗑️ Clear Chat"):
            st.session_state.chat_history = []
            st.rerun()

with col2:
    st.header("⚡ Quick Actions")
    
    # Predefined prompts
    st.subheader("🔧 Sample Requests")
    
    sample_prompts = [
        "Create a quote for 120 Office Chairs for ABC Corp, preferred customer",
        "I need 50 Conference Tables for XYZ Ltd, regular customer",
        "Quote for 25 Developer Desks for TechStart Inc",
        "Need 100 Visitor Stools for MegaCorp, preferred customer"
    ]
    
    for i, prompt in enumerate(sample_prompts):
        if st.button(f"📝 {prompt[:30]}...", key=f"sample_{i}"):
            st.session_state.input_value = prompt
            st.rerun()
    
    st.divider()
    
    # File explorer
    st.subheader("📁 Quote Files")
    
    quote_files = list(OUT_DIR.glob("*.json"))
    if quote_files:
        selected_file = st.selectbox(
            "Select a quote to view:",
            options=[f.name for f in sorted(quote_files, key=lambda x: x.stat().st_mtime, reverse=True)],
            key="file_selector"
        )
        
        if selected_file:
            file_path = OUT_DIR / selected_file
            try:
                with open(file_path, 'r') as f:
                    quote_data = json.load(f)
                
                st.markdown(f"""
                <div class="quote-card">
                    <h4>Quote ID: {quote_data['quote_id']}</h4>
                    <p><strong>Customer:</strong> {quote_data['customer']}</p>
                    <p><strong>Total:</strong> ${quote_data['total']:,}</p>
                    <p><strong>Items:</strong></p>
                    <ul>
                """, unsafe_allow_html=True)
                
                for item in quote_data['items']:
                    st.markdown(f"""
                        <li>{item['qty']}x {item['name']} @ ${item.get('unit_price', 0):,} = ${item.get('total', 0):,}</li>
                    """, unsafe_allow_html=True)
                
                st.markdown(f"""
                    </ul>
                    <p><strong>Terms:</strong> {quote_data['terms']}</p>
                </div>
                """, unsafe_allow_html=True)
                
                # Download button
                st.download_button(
                    label="📥 Download Quote JSON",
                    data=json.dumps(quote_data, indent=2),
                    file_name=f"{quote_data['quote_id']}.json",
                    mime="application/json"
                )
                
            except Exception as e:
                st.error(f"Error reading quote file: {e}")
    else:
        st.info("No quote files found. Generate some quotes to see them here!")

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666; padding: 1rem;">
    <p>🤖 Powered by Google ADK Framework & LLM Gateway | 📧 Integrated with n8n Email Notifications</p>
</div>
""", unsafe_allow_html=True)
