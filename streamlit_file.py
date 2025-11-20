import streamlit as st
import asyncio
import json
from pathlib import Path
import os
from datetime import datetime
import requests
import threading
from concurrent.futures import ThreadPoolExecutor

# PyVegas imports (Assuming these are correctly installed and configured)
try:
    from pyvegas.core import get_settings, get_logger
    from pyvegas.langx.llm import VegasChatVertexAI
    PYVEGAS_AVAILABLE = True
except ImportError:
    PYVEGAS_AVAILABLE = False
    class MockLLM:
        def bind_tools(self, tools): return self
        def __init__(self, *args, **kwargs): pass
        async def ainvoke(self, messages): return {"content": "Mock LLM response: Please install PyVegas and set up your environment to enable the real agent."}
    VegasChatVertexAI = MockLLM

# MCP and LangChain imports
try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain.agents import create_agent
    LANGCHAIN_MCP_AVAILABLE = True
except ImportError:
    LANGCHAIN_MCP_AVAILABLE = False

from dotenv import load_dotenv, find_dotenv

# --- PyVegas Standard Initialization (Only if available) ---
if PYVEGAS_AVAILABLE:
    try:
        os.environ["ENVIRONMENT"] = os.getenv("ENVIRONMENT", "dev")
        os.environ["VEGAS_API_KEY"] = os.getenv("VEGAS_API_KEY", "")
        
        settings = get_settings()
        logger = get_logger(__name__)
        logger.info(f"Settings loaded successfully for environment: {settings.ENVIRONMENT}")
    except Exception as e:
        st.error(f"Failed to initialize PyVegas settings: {e}")
        st.stop()
else:
    st.warning("PyVegas library not found. Using a mock LLM. Agent functionality will be limited.")

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

# --- Session State Initialization ---
if "conversation_history" not in st.session_state:
    st.session_state.conversation_history = []
if "mcp_client" not in st.session_state:
    st.session_state.mcp_client = None
if "tools" not in st.session_state:
    st.session_state.tools = []
if "agent" not in st.session_state:
    st.session_state.agent = None
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
    """Runs an async coroutine on the dedicated thread pool."""
    loop = st.session_state.async_loop
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    # The result() call is what blocks the Streamlit thread until the async task is done
    return future.result(timeout=timeout)

# --- MCP Configuration (CRITICAL CHANGE) ---
# Changed 'transport' from 'streamable_http' to 'http' to resolve the 'Not Acceptable: Client must accept text/event-stream' error.
MCP_CONFIG = {
    "orders": {
        "url": "http://127.0.0.1:8000/mcp",  # Match the exact server URL
        "transport": "http", # <-- FIX: Use standard http
    }
}

# --- Initialization Functions ---

def check_server_status():
    """Check if the MCP server is running by attempting an MCP tools/list request."""
    url = MCP_CONFIG["orders"]["url"]
    
    try:
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
        
        if mcp_response.status_code == 200:
            json_response = mcp_response.json()
            if "jsonrpc" in json_response and ("result" in json_response or "error" in json_response):
                return "Running"
        
    except requests.exceptions.ConnectionError:
        return "Offline (Connection Refused)"
    except requests.exceptions.Timeout:
        return "Offline (Timeout)"
    except Exception:
        return "Offline (Error)"
    
    return "Offline (Invalid Response)"


async def _get_mcp_client_tools(mcp_config: dict):
    """Async core function to fetch tools."""
    if not LANGCHAIN_MCP_AVAILABLE:
        raise ImportError("LangChain MCP adapter not available.")
    client = MultiServerMCPClient(mcp_config)
    # This is the line that makes an async network call to the server
    tools = await client.get_tools()
    return client, tools


def initialize_mcp_client():
    """Initialize MCP client and tools using persistent event loop."""
    try:
        # Use run_async to execute the async part on the background loop
        return run_async(_get_mcp_client_tools(MCP_CONFIG))
    except Exception as e:
        print(f"Error in initialize_mcp_client: {e}")
        return None, []


def initialize_agent(tools):
    """Initialize the LangChain agent with PyVegas LLM."""
    if not LANGCHAIN_MCP_AVAILABLE:
        st.error("LangChain MCP adapter not available. Cannot initialize agent.")
        return None
    
    try:
        print(f"Initializing agent with {len(tools)} tools")
        
        # LLM initialization
        llm = VegasChatVertexAI(
            usecase_name="ganeshtest",
            context_name="ganeshtestprompt",
        ).bind_tools(tools=tools)
        
        print("LLM created and tools bound successfully")
        
        # System prompt
        system_prompt = (
            "You are an orders management customer support agent. "
            "Give detailed responses — include all the details you have about the customer's order(s). "
            "If the customer wants to cancel the order, ask for a specific order_id to cancel. You can cancel only if only if the order is in the ORDERED status. You should politely prevent cancellation for other statuses like DISPATCHED, CANCELLED, DELIVERED, or IN_TRANSIT."
            "Answer follow-ups. This conversation persists across turns and only exits when the user types 'exit' or 'quit'."
        )
        
        print("System prompt prepared")
        
        # Agent creation
        agent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=system_prompt,
        )
        
        print("Agent created successfully")
        
        st.session_state.system_prompt = system_prompt
        
        return agent
    except Exception as e:
        error_msg = f"Failed to initialize agent: {e}"
        print(error_msg)
        st.error(error_msg)
        import traceback
        st.code(traceback.format_exc())
        return None

# --- Chat & History Management ---

def display_chat_history():
    """Display the conversation history"""
    for message in st.session_state.conversation_history:
        if message["role"] == "user":
            with st.chat_message("user"):
                st.write(message["content"])
        elif message["role"] == "assistant":
            with st.chat_message("assistant"):
                st.write(message["content"])

async def _invoke_agent(agent, history):
    """The actual async agent invocation."""
    resp = await agent.ainvoke({"messages": history})
    
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
        assistant_text = "<No content returned by agent. Check agent logs for errors.>"
        
    return assistant_text

def process_user_message(user_input: str):
    """Prepares history and runs the async agent invocation."""
    if not st.session_state.agent:
        return "Agent not initialized. Please check server connection in the sidebar."
    
    agent = st.session_state.agent
    system_prompt = st.session_state.system_prompt
    
    # Build history for invocation (including system prompt for the agent's context)
    history = list(st.session_state.conversation_history)
    if system_prompt and (not history or history[0].get("role") != "system"):
        history.insert(0, {"role": "system", "content": system_prompt})
    history.append({"role": "user", "content": user_input})

    try:
        # Run the async invocation on the dedicated loop
        assistant_text = run_async(_invoke_agent(agent, history))
    except Exception as e:
        # Log error details
        import traceback
        st.error(f"Error during agent invocation: {e}")
        st.code(traceback.format_exc())
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
    else:
        st.warning("No saved history file found.")

# --- Main Application ---

def main():
    """Main Streamlit application"""
    
    st.title("🛒 Order Management Chatbot")
    st.markdown("---")
    
    # Sidebar for connection and conversation management
    with st.sidebar:
        st.header("🌐 MCP Server Status")
        current_status = check_server_status()
        if current_status == "Running":
            st.success(f"Status: **{current_status}** at {MCP_CONFIG['orders']['url']}")
        else:
            st.error(f"Status: **{current_status}**")
            st.info("Ensure the server is running in a separate terminal: `python order_server.py`")

        st.markdown("---")
        
        # Initialize/Refresh connection
        if st.button("Initialize/Refresh Connection"):
            with st.spinner("Initializing MCP connection and Agent..."):
                try:
                    # Clear cache on purpose before attempting connection
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
                            st.success("🎉 All systems ready! You can now chat.")
                        else:
                            st.error("❌ Could not initialize agent")
                    else:
                        st.error("❌ Could not connect to MCP server or retrieve tools.")
                        
                except Exception as e:
                    st.error(f"❌ Connection failed during initialization: {e}")
        
        st.markdown("---")
        
        # Conversation management
        st.header("💾 Conversation History")
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
    
    # Display connection status
    if not st.session_state.agent:
        st.warning("⚠️ Agent is **not** ready. Initialize connection in the sidebar to enable order lookup/cancellation.")
    else:
        st.info(f"✅ Agent ready with {len(st.session_state.tools)} MCP tools.")
    
    # Chat container
    chat_container = st.container()
    
    # Display chat history
    with chat_container:
        display_chat_history()
    
    # Chat input
    if user_input := st.chat_input("Type your message here..."):
        with st.chat_message("user"):
            st.write(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response = process_user_message(user_input)
                st.write(response)

    # Sample questions - always visible
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
                # Process the sample question as if it was typed
                with st.chat_message("user"):
                    st.write(question)
                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        response = process_user_message(question)
                        st.write(response)
                # Rerun to update the history instantly
                st.rerun()

    # Available Tools section
    if st.session_state.tools:
        st.markdown("---")
        with st.expander("🛠️ Available MCP Tools"):
            st.success(f"✅ {len(st.session_state.tools)} tools loaded")
            
            for i, tool in enumerate(st.session_state.tools):
                tool_name = getattr(tool, 'name', f'Tool {i+1}')
                tool_desc = getattr(tool, 'description', 'No description available')
                
                with st.expander(f"**{tool_name}**"):
                    st.write(tool_desc)
                    
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
