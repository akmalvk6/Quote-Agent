#!/bin/bash

# Start Streamlit app
echo "🚀 Starting Smart Quoting Agent Streamlit UI..."
echo "🔗 Open your browser to: http://localhost:8501"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT/src"

streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
