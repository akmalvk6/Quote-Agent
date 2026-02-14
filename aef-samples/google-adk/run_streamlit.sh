#!/bin/bash

# Start Streamlit app
echo "🚀 Starting Smart Quoting Agent Streamlit UI..."
echo "🔗 Open your browser to: http://localhost:8501"
echo ""
cd /workspaces/agentx-hackathon-DC-Pros/aef-samples/google-adk
streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
