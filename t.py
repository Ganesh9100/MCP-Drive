{"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Not Acceptable: Client must accept text/event-stream"}}

@st.cache_data(ttl=30)
def check_server_status():
    """Check if the MCP server is running using proper MCP protocol"""
    # Try both localhost and 127.0.0.1
    urls_to_try = [
        "http://127.0.0.1:8000/mcp",
        "http://localhost:8000/mcp"
    ]
    
    for url in urls_to_try:
        try:
            # MCP servers (SSE) expect a GET request with this specific header
            # to verify the connection is possible.
            headers = {
                "Accept": "text/event-stream",
                "Content-Type": "application/json"
            }
            
            # We use stream=True to avoid hanging while waiting for infinite events
            response = requests.get(url, headers=headers, stream=True, timeout=5)
            
            # If we get a 200 OK, the server is ready to talk SSE
            if response.status_code == 200:
                # Close the connection immediately since we just wanted to check status
                response.close()
                return "Running"
            
            # Some servers might return 405 (Method Not Allowed) if they expect 
            # a different handshake, but usually 200 means success for SSE.
            
        except requests.exceptions.ConnectionError:
            continue
        except Exception as e:
            print(f"Status check error for {url}: {e}")
            continue
    
    return "Offline"
