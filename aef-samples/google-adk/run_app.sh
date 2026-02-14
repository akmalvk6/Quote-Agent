#!/bin/bash

echo "🚀 Starting Smart Quoting Agent Streamlit UI..."
echo ""
echo "📁 Working directory: $(pwd)"
echo "🔗 The app will be available at: http://localhost:8501"
echo "🔧 Make sure your LLM Gateway is running on port 4000"
echo ""

# Navigate to the correct directory
cd /workspaces/agentx-hackathon-DC-Pros/aef-samples/google-adk

# Check if streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "📦 Installing Streamlit..."
    pip install streamlit
fi

# Run the Streamlit app
echo "🎯 Launching Smart Quoting Agent UI..."
streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
