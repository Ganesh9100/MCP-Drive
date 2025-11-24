# MCP-Drive
This Repo consist of all codes related to MCP
<!-- MCP Core Concept -->
<section>
  <h2>Model Context Protocol (MCP) — Quick Overview</h2>

  <h3>🔌 MCP Server</h3>
  <ul>
    <li>Servers are lightweight programs that expose specific capabilities through the protocol.</li>
    <li>The server’s primary job is to expose information (tools, resources, and prompts) to the client.</li>
  </ul>

  <h3>💡 MCP Client</h3>
  <ul>
    <li>MCP clients maintain a <strong>1-to-1 connection</strong> with MCP servers.</li>
    <li>The client’s job is to discover resources and find tools.</li>
    <li>When the client uses a tool (a function provided by the server), the client invokes that tool and executes the required data/operation.</li>
  </ul>

  <h3>🏠 Host</h3>
  <ul>
    <li>Clients run inside a host (e.g., Claude Desktop or Claude AI).</li>
    <li>The host is an LLM application that wants to access data or functionality through MCP.</li>
    <li>The host is responsible for storing and maintaining all clients and their connections to MCP servers.</li>
  </ul>
</section>
