
import streamlit as st
import asyncio
import json
from pathlib import Path
import os
from datetime import datetime
import pandas as pd
import requests
import threading
from concurrent.futures import ThreadPoolExecutor

# PyVegas imports
from pyvegas.core import get_settings, get_logger
from pyvegas.langx.llm import VegasChatVertexAI

# MCP and LangChain imports
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from dotenv import load_dotenv, find_dotenv

# --- PyVegas Standard Initialization ---
try:
    os.environ["ENVIRONMENT"] = os.getenv("ENVIRONMENT", "dev")
    os.environ["VEGAS_API_KEY"] = os.getenv("VEGAS_API_KEY", "")
    
    settings = get_settings()
    logger = get_logger(__name__)
    logger.info(f"Settings loaded successfully for environment: {settings.ENVIRONMENT}")
except Exception as e:
    st.error(f"Failed to initialize PyVegas settings: {e}")
    st.stop()

# Load environment variables
env_path = find_dotenv()
if not env_path:
    root_env = Path(__file__).resolve().parent / ".env"
    if root_env.exists():
        env_path = str(root_env)

if env_path:
    load_dotenv(env_path)

# Streamlit configuration
st.set_page_config(
    page_title="Order Management Chat",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if "conversation_history" not in st.session_state:
    st.session_state.conversation_history = []
if "mcp_client" not in st.session_state:
    st.session_state.mcp_client = None
if "tools" not in st.session_state:
    st.session_state.tools = []
if "agent" not in st.session_state:
    st.session_state.agent = None
if "server_status" not in st.session_state:
    st.session_state.server_status = "Unknown"
if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = None
# Persistent asyncio loop (one per Streamlit session)
if "async_loop" not in st.session_state:
    st.session_state.async_loop = asyncio.new_event_loop()
    def _loop_runner(loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()
    t = threading.Thread(target=_loop_runner, args=(st.session_state.async_loop,), daemon=True)
    t.start()
    st.session_state.async_loop_thread = t

# Unified async runner using the persistent loop
def run_async(coro, timeout: int = 120):
    loop = st.session_state.async_loop
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)

# MCP Configuration - try localhost first, fallback to 127.0.0.1
MCP_CONFIG = {
    "orders": {
        "url": "http://127.0.0.1:8000/mcp",  # Match the exact server URL
        "transport": "streamable_http",
    }
}

@st.cache_data(ttl=30)
def check_server_status():
    """Check if the MCP server is running using proper MCP protocol"""
    # Try both localhost and 127.0.0.1 to be safe
    urls_to_try = [
        "http://127.0.0.1:8000/mcp",
        "http://localhost:8000/mcp"
    ]
    
    for url in urls_to_try:
        try:
            # First, try a simple HTTP GET to see if the server responds
            base_url = url.replace('/mcp', '')
            response = requests.get(base_url, timeout=20)
            if response.status_code in [200, 404, 405]:  # Server is responding
                # Now try a proper MCP tools/list request
                mcp_response = requests.post(
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {}
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=3
                )
                
                # Check if we get a valid JSON-RPC response
                if mcp_response.status_code == 200:
                    try:
                        json_response = mcp_response.json()
                        # Valid MCP response should have jsonrpc and either result or error
                        if "jsonrpc" in json_response and ("result" in json_response or "error" in json_response):
                            return "Running"
                    except json.JSONDecodeError:
                        continue
                        
        except Exception:
            continue
    
    return "Offline"

def initialize_mcp_client():
    """Initialize MCP client and tools using persistent event loop."""
    try:
        async def get_mcp_client_tools(mcp_config: dict):
            client = MultiServerMCPClient(mcp_config)
            tools = await client.get_tools()
            return client, tools
        return run_async(get_mcp_client_tools(MCP_CONFIG))
    except Exception as e:
        print(f"Error in initialize_mcp_client: {e}")
        return None, []

def initialize_agent(tools):
    """Initialize the LangChain agent with PyVegas LLM - exact same pattern as CLI version"""
    try:
        print(f"Initializing agent with {len(tools)} tools")
        
        # Exact same LLM initialization as CLI version
        llm = VegasChatVertexAI(
            usecase_name="ganeshtest",
            context_name="ganeshtestprompt",
        ).bind_tools(tools=tools)
        
        print("LLM created and tools bound successfully")
        
        # Exact same system prompt as CLI version
        system_prompt = (
            "You are an orders management customer support agent. "
            "Give detailed responses — include all the details you have about the customer's order(s). "
            "If the customer wants to cancel the order, ask for a specific order_id to cancel. You can cancel only if only if the order is in the ORDERED status. You should politely prevent cancellation for other statuses like DISPATCHED, CANCELLED, DELIVERED, or IN_TRANSIT."
            "Answer follow-ups. This conversation persists across turns and only exits when the user types 'exit' or 'quit'."
        )
        
        print("System prompt prepared")
        
        # Exact same agent creation as CLI version
        agent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=system_prompt,
        )
        
        print("Agent created successfully")
        
        # Store system prompt for conversation history management
        st.session_state.system_prompt = system_prompt
        
        return agent
    except Exception as e:
        error_msg = f"Failed to initialize agent: {e}"
        print(error_msg)
        st.error(error_msg)
        # Show more details for debugging
        import traceback
        st.code(traceback.format_exc())
        return None

def display_chat_history():
    """Display the conversation history"""
    for i, message in enumerate(st.session_state.conversation_history):
        if message["role"] == "user":
            with st.chat_message("user"):
                st.write(message["content"])
        elif message["role"] == "assistant":
            with st.chat_message("assistant"):
                st.write(message["content"])

def process_user_message(user_input: str):
    """Process user message using background loop; avoid accessing st.session_state inside coroutine."""
    ensure_session_state()
    if not st.session_state.agent:
        return "Agent not initialized. Please check server connection."
    agent = st.session_state.agent
    system_prompt = st.session_state.system_prompt
    # Build history for invocation
    history = list(st.session_state.conversation_history)
    if system_prompt and (not history or history[0].get("role") != "system"):
        history.insert(0, {"role": "system", "content": system_prompt})
    history.append({"role": "user", "content": user_input})

    async def _invoke(a, h):
        resp = await a.ainvoke({"messages": h})
        assistant_text = None
        if isinstance(resp, dict):
            msgs = resp.get("messages")
            if isinstance(msgs, list) and msgs:
                last = msgs[-1]
                assistant_text = (
                    (last.get("content") if isinstance(last, dict) else None)
                    or getattr(last, "content", None)
                    or resp.get("content")
                    or resp.get("text")
                )
        elif isinstance(resp, str):
            assistant_text = resp
        if not assistant_text:
            assistant_text = "<no content returned by agent>"
        return assistant_text

    try:
        assistant_text = run_async(_invoke(agent, history))
    except Exception as e:
        return f"Error processing message: {e}"

    # Commit turns after successful response
    st.session_state.conversation_history.append({"role": "user", "content": user_input, "timestamp": datetime.now().isoformat()})
    st.session_state.conversation_history.append({"role": "assistant", "content": assistant_text, "timestamp": datetime.now().isoformat()})
    return assistant_text

def save_conversation_history():
    """Save conversation history to file"""
    history_file = Path("streamlit_chat_history.json")
    try:
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(st.session_state.conversation_history, f, indent=2, ensure_ascii=False)
        st.success("Conversation saved successfully!")
    except Exception as e:
        st.error(f"Failed to save conversation: {e}")

def load_conversation_history():
    """Load conversation history from file"""
    history_file = Path("streamlit_chat_history.json")
    if history_file.exists():
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                st.session_state.conversation_history = json.load(f)
            st.success("Conversation history loaded!")
        except Exception as e:
            st.error(f"Failed to load conversation: {e}")

# Helper to ensure required session keys exist (robust against reruns)
def ensure_session_state():
    defaults = {
        "conversation_history": [],
        "mcp_client": None,
        "tools": [],
        "agent": None,
        "server_status": "Unknown",
        "system_prompt": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def main():
    """Main Streamlit application"""
    # Ensure session state is properly initialized
    ensure_session_state()
    
    st.title("🛒 Order Management Chatbot")
    st.markdown("---")
    
    # Sidebar for connection and conversation management
    with st.sidebar:
        # Initialize/Refresh connection - non-blocking
        if st.button("Initialize/Refresh Connection"):
            with st.spinner("Initializing MCP connection..."):
                try:
                    # Clear cache first
                    st.cache_data.clear()
                    
                    st.info("Connecting to MCP server...")
                    client, tools = initialize_mcp_client()
                    
                    if client and tools:
                        st.session_state.mcp_client = client
                        st.session_state.tools = tools
                        st.success(f"✅ Connected to MCP server, found {len(tools)} tools")
                        
                        st.info("Initializing AI agent...")
                        # Initialize agent
                        agent = initialize_agent(tools)
                        if agent:
                            st.session_state.agent = agent
                            st.success("✅ Agent initialized successfully!")
                            st.success("🎉 All systems ready! You can now chat with the agent.")
                        else:
                            st.error("❌ Could not initialize agent")
                    else:
                        st.error("❌ Could not connect to MCP server")
                        st.error("Make sure the server is running: `python order_server.py`")
                        
                except Exception as e:
                    st.error(f"❌ Connection failed: {e}")
                    st.error("Check if MCP server is running and accessible")
        
        st.markdown("---")
        
        # Conversation management
        st.header("💾 Conversation")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Save Chat"):
                save_conversation_history()
        with col2:
            if st.button("Load Chat"):
                load_conversation_history()
        
        if st.button("Clear Chat"):
            st.session_state.conversation_history = []
            st.rerun()
    
    # Main chat interface
    st.header("💬 Chat with Order Support Agent")
    
    # Display connection status - but don't block conversation
    if not st.session_state.agent:
        st.info("ℹ️ To use MCP tools, please initialize connection in the sidebar. You can still chat without tools.")
    else:
        st.success("✅ Agent ready with MCP tools")
    
    # Chat container
    chat_container = st.container()
    
    # Display chat history
    with chat_container:
        display_chat_history()
    
    # Chat input - ALWAYS enabled for better UX
    if user_input := st.chat_input("Type your message here..."):
        with st.chat_message("user"):
            st.write(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                if st.session_state.agent:
                    response = process_user_message(user_input)
                else:
                    response = (
                        "I'm ready to help with your order management questions! "
                        "However, I don't currently have access to the order database tools. "
                        "Please initialize the connection in the sidebar to access order information. "
                        "\n\nIn the meantime, I can help you understand:\n"
                        "- How to check order status\n"
                        "- Order cancellation policies\n"
                        "- General order management questions\n"
                        "\nWhat would you like to know about order management?"
                    )
                st.write(response)

    # Sample questions - some work without tools
    st.markdown("---")
    st.header("💡 Sample Questions")
    
    cols = st.columns(2)
    for i, question in enumerate([
        "What is the order status of cust_1?",
        "I want to cancel my order. My customer ID is cust_2 and order ID is ord_002",
        "How does order cancellation work?",
        "What order statuses are there?"
    ]):
        with cols[i % 2]:
            if st.button(question, key=f"sample_{i}"):
                with st.chat_message("user"):
                    st.write(question)
                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        if st.session_state.agent:
                            response = process_user_message(question)
                        else:
                            # Provide helpful responses based on question type
                            if "cancel" in question.lower():
                                response = (
                                    "Order cancellation is typically only allowed when an order is in 'ORDERED' status. "
                                    "Orders that are DISPATCHED, IN_TRANSIT, DELIVERED, or already CANCELLED cannot be cancelled. "
                                    "To cancel an order, I would need your customer ID and order ID, and access to the order database."
                                )
                            elif "status" in question.lower():
                                response = (
                                    "Order statuses typically include: ORDERED, DISPATCHED, IN_TRANSIT, DELIVERED, and CANCELLED. "
                                    "To check specific order status, I would need access to the order database tools."
                                )
                            else:
                                response = (
                                    "I'd be happy to help with that! To access specific order information, "
                                    "please initialize the MCP connection in the sidebar first."
                                )
                        st.write(response)
                st.rerun()

    # Available Tools section (bottom right)
    if st.session_state.tools:
        st.markdown("---")
        with st.expander("🛠️ Available MCP Tools"):
            st.success(f"✅ {len(st.session_state.tools)} tools loaded")
            
            for i, tool in enumerate(st.session_state.tools):
                tool_name = getattr(tool, 'name', f'Tool {i+1}')
                tool_desc = getattr(tool, 'description', 'No description available')
                
                with st.expander(f"**{tool_name}**"):
                    st.write(tool_desc)
                    
                    # Show tool parameters if available
                    if hasattr(tool, 'args_schema') and tool.args_schema:
                        st.write("**Parameters:**")
                        try:
                            schema = tool.args_schema.schema() if hasattr(tool.args_schema, 'schema') else {}
                            properties = schema.get('properties', {})
                            for param_name, param_info in properties.items():
                                param_type = param_info.get('type', 'unknown')
                                param_desc = param_info.get('description', 'No description')
                                st.write(f"- `{param_name}` ({param_type}): {param_desc}")
                        except Exception:
                            st.write("Parameter details not available")

if __name__ == "__main__":
    main()
