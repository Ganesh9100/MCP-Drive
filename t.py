{"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Not Acceptable: Client must accept text/event-stream"}}
import requests
import json
import sys

# CONFIGURATION
URL = "http://127.0.0.1:8000/mcp"

def print_result(test_name, success, details):
    icon = "✅" if success else "❌"
    print(f"\n{icon} {test_name}")
    print(f"   Status: {details['status']}")
    print(f"   Response: {details['body']}")
    print("-" * 40)

def test_get_handshake():
    """Test 1: Standard SSE Handshake (GET request)"""
    print(f"Testing GET request to {URL}...")
    headers = {
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache"
    }
    try:
        # stream=True prevents hanging on an infinite stream
        response = requests.get(URL, headers=headers, stream=True, timeout=5)
        
        # We just read the first chunk to see if it worked
        chunk = next(response.iter_content(chunk_size=128), b"")
        response.close()
        
        success = response.status_code == 200
        return success, {
            "status": response.status_code, 
            "body": chunk.decode('utf-8')[:100] + "..." # Show first 100 chars
        }
    except Exception as e:
        return False, {"status": "Error", "body": str(e)}

def test_post_rpc():
    """Test 2: JSON-RPC over POST (How your Streamlit app tries to connect)"""
    print(f"Testing POST request to {URL}...")
    headers = {
        "Accept": "text/event-stream", 
        "Content-Type": "application/json"
    }
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 1
    }
    
    try:
        response = requests.post(URL, headers=headers, json=payload, stream=True, timeout=5)
        
        # Attempt to read response
        try:
            if response.headers.get('content-type') == 'application/json':
                body = response.json()
            else:
                chunk = next(response.iter_content(chunk_size=128), b"")
                body = chunk.decode('utf-8')
        except:
            body = "<Could not read body>"

        response.close()
        
        success = response.status_code == 200
        return success, {
            "status": response.status_code, 
            "body": str(body)[:100]
        }
    except Exception as e:
        return False, {"status": "Error", "body": str(e)}

if __name__ == "__main__":
    print(f"🔍 Diagnostic for MCP Server at {URL}\n" + "="*40)
    
    # Run Test 1
    get_success, get_details = test_get_handshake()
    print_result("Test 1: GET Handshake", get_success, get_details)
    
    # Run Test 2
    post_success, post_details = test_post_rpc()
    print_result("Test 2: POST Request", post_success, post_details)

    print("\n📢 DIAGNOSIS:")
    if get_success and post_success:
        print("🚀 GREAT! Both methods work. Your Streamlit issue is likely caching or async loop conflicts.")
    elif get_success and not post_success:
        print("⚠️ PARTIAL: Your server ONLY accepts GET requests.")
        print("   Action: You MUST update check_server_status in Streamlit to use requests.get().")
    elif not get_success and not post_success:
        print("💀 CRITICAL: Server is unreachable or crashing.")
        print("   Action: Check if 'python order_server.py' is running.")
