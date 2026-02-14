# AgentX Hackathon - Smart Quoting Agent Architecture

## 1. Introduction

This document describes the architectural design for the Smart Quoting Agent project, a comprehensive AI-powered quote generation system using Google ADK framework, LLM Gateway integration, n8n workflow automation, and Streamlit web interface.

---

## 2. Logical Architecture

```mermaid
graph TD
    U[User] -->|Web UI| ST[Streamlit Frontend]
    U -->|Chat Interface| N8N[n8n Chat Trigger]
    ST -->|Python Calls| ADK[Google ADK Agent]
    N8N -->|AI Agent| GEMINI[Google Gemini LLM]
    ADK -->|Tool Calls| TOOLS[Quote Tools]
    ADK -->|LLM Requests| GW[LLM Gateway]
    GW -->|OpenAI API| GEMINI
    TOOLS -->|File I/O| FS[File System]
    FS -->|JSON Files| MON[n8n File Monitor]
    MON -->|Email| SMTP[Email Notifications]
    
    subgraph TOOLS [Quote Generation Tools]
        T1[price_lookup]
        T2[discount_calculator]
        T3[historical_match]
        T4[quote_generator]
    end
    
    subgraph FS [Data Storage]
        CSV[Product/History CSV]
        JSON[Quote JSON Files]
        LOG[Quote Logs]
    end
```

- **Streamlit Frontend:** Web-based UI for interactive quote generation
- **Google ADK Agent:** Core AI agent using Google's Agent Development Kit
- **LLM Gateway:** Proxy service for LLM API calls (localhost:4000)
- **Quote Tools:** Specialized functions for pricing, discounts, and quote generation
- **n8n Workflow:** Automation for file monitoring and email notifications
- **File System:** CSV data storage and JSON quote output

---

## 3. Physical Architecture

```mermaid
flowchart LR
    Browser[User Browser] --> ST2[Streamlit App :8501]
    N8N_UI[n8n UI] --> N8N_WF[n8n Workflow Engine]
    
    ST2 --> AGT[Smart Agent Process]
    N8N_WF --> AGT
    AGT --> GW2[LLM Gateway :4000]
    GW2 --> GEMINI2[Google Gemini API]
    
    AGT --> DATA[Local File System]
    N8N_WF -->|Monitor| DATA
    N8N_WF -->|Send| EMAIL[SMTP Email Service]
    
    subgraph DEV_CONTAINER [Dev Container Environment]
        ST2
        AGT
        GW2
        DATA
        N8N_WF
    end
```

- **Dev Container:** Debian-based development environment with all dependencies
- **Streamlit App:** Web interface running on port 8501
- **LLM Gateway:** Local proxy service on port 4000
- **File System:** Local storage for quotes and data files
- **n8n Workflow:** Automated monitoring and notification system
- **External APIs:** Google Gemini LLM service

---

## 4. Deployment Architecture

```mermaid
flowchart TB
    DEV[Dev Container] -->|Development| LOCAL[Local Services]
    
    subgraph LOCAL [Local Development Environment]
        ST3[Streamlit UI<br/>Port 8501]
        GW3[LLM Gateway<br/>Port 4000]
        AGT3[Smart Agent<br/>Python Process]
        N8N3[n8n Workflows<br/>Automation]
        FS3[File System<br/>Quotes & Data]
    end
    
    LOCAL -->|API Calls| CLOUD[Cloud Services]
    
    subgraph CLOUD [External Cloud Services]
        GEMINI3[Google Gemini API]
        SMTP3[SMTP Email Service]
    end
    
    N8N3 -->|Email Notifications| SMTP3
    GW3 -->|LLM Requests| GEMINI3
```

- **Development Environment:** All services run locally in dev container
- **Local File Storage:** Quotes and data stored in workspace filesystem
- **Cloud Integration:** External APIs for LLM and email services
- **Automated Workflows:** n8n handles file monitoring and notifications

---

## 5. Components and Technologies

| Component | Technology | Purpose | Port/Location |
|-----------|------------|---------|---------------|
| **Frontend UI** | Streamlit | Interactive web interface | :8501 |
| **AI Agent** | Google ADK + Python | Core quote generation logic | Python process |
| **LLM Gateway** | OpenAI-compatible proxy | LLM API abstraction | :4000 |
| **LLM Service** | Google Gemini 2.5 Flash | Large language model | Cloud API |
| **Workflow Engine** | n8n | Automation and monitoring | Workflow process |
| **Data Storage** | CSV + JSON files | Product catalog and quotes | File system |
| **Email Service** | SMTP | Quote notifications | Cloud SMTP |
| **Development** | Dev Container | Debian-based environment | Container |

---

## 6. Data Flow

### Quote Generation Process:

1. **User Input:** Request via Streamlit UI or n8n chat
2. **Agent Processing:** Google ADK agent processes request
3. **Tool Execution:** Sequential tool calls:
   - `price_lookup()` - Get product pricing
   - `discount_calculator()` - Calculate discounts
   - `quote_generator()` - Create and save quote
4. **File Creation:** JSON quote file saved to filesystem
5. **Monitoring:** n8n detects new quote files
6. **Notification:** Email sent with quote details

### File Structure:
```
/workspaces/agentx-hackathon-DC-Pros/
├── aef-samples/google-adk/
│   ├── simple_agent.py          # Core agent logic
│   ├── streamlit_app.py         # Web UI
│   ├── data/
│   │   ├── products.csv         # Product catalog
│   │   ├── historical_quotes.csv
│   │   └── quotes_log.csv
│   └── quotes/                  # Generated quote files
├── n8n/
│   └── workflows/
│       └── smart-quote-monitor.json
└── quotes/                      # Quote output directory
```

---

## 7. Integration Points

### **Google ADK Integration:**
- Custom `LLMGatewayModel` class bridges ADK with LLM Gateway
- Tool functions registered with ADK framework
- Session management for conversation context

### **LLM Gateway Integration:**
- OpenAI-compatible API format
- Async request handling
- Tool call detection and execution

### **n8n Integration:**
- File system monitoring via command execution
- Email template processing
- Workflow static data for tracking processed files

### **Streamlit Integration:**
- Real-time chat interface
- File browser and download functionality
- Session state management for conversation history

---

## 8. Security and Configuration

- **API Keys:** Managed via environment variables
- **File Permissions:** Controlled access to quote directories
- **HTTPS:** SSL/TLS for external API communications
- **Email Security:** SMTP authentication for notifications

---

## 9. Scalability Considerations

- **Async Processing:** Non-blocking LLM requests
- **File-based Storage:** Simple and reliable for development
- **Modular Tools:** Easy to extend with additional quote functions
- **Workflow Automation:** n8n handles background processing

---

## 10. Development Workflow

1. **Code Changes:** Edit agent logic or UI components
2. **Testing:** Run agent directly or via Streamlit
3. **Quote Generation:** Tools create JSON files automatically
4. **Monitoring:** n8n workflows detect and process new quotes
5. **Notifications:** Email alerts sent for new quotes

---

## 11. Contact

For architectural questions or development support, contact the AgentX Hackathon team.
