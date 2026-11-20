#Mock implementation of Bedrock AgentCore Runtime for local testing and development.# Mock implementation of bedrock-agentcore SDK
# This is a stub for the Amazon Bedrock AgentCore SDK

"""
Amazon Bedrock AgentCore SDK (Mock Implementation)

This module provides a mock implementation of the bedrock-agentcore SDK
for local development and testing purposes.
"""

__version__ = "1.2.0"

import json
from typing import Callable, Dict, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading


class BedrockAgentCoreApp:
    """
    Main application class for wrapping agent functions with Bedrock AgentCore.
    
    This class provides:
    - @app.entrypoint decorator for agent functions
    - HTTP server with /invocations and /ping endpoints
    - Request/response handling
    """
    
    def __init__(self):
        self._entrypoint_handler = None
        self._server = None
        
    def entrypoint(self, func: Callable) -> Callable:
        """
        Decorator to mark a function as the agent entrypoint.
        
        The decorated function should accept a request dict and return a response dict.
        
        Example:
            @app.entrypoint
            def my_agent_handler(request):
                prompt = request.get("prompt", "")
                # Process prompt...
                return {"response": result}
        """
        self._entrypoint_handler = func
        return func
    
    def run(self, host: str = "localhost", port: int = 8080):
        """
        Start the HTTP server for local testing.
        
        The server exposes:
        - POST /invocations - Main agent invocation endpoint
        - GET /ping - Health check endpoint
        
        Args:
            host: Host to bind to (default: localhost)
            port: Port to bind to (default: 8080)
        """
        if not self._entrypoint_handler:
            raise RuntimeError("No entrypoint handler defined. Use @app.entrypoint decorator.")
        
        handler_class = self._create_handler_class()
        self._server = HTTPServer((host, port), handler_class)
        
        print(f"Starting Bedrock AgentCore local server on {host}:{port}")
        print(f"Endpoints:")
        print(f"  - POST http://{host}:{port}/invocations")
        print(f"  - GET  http://{host}:{port}/ping")
        
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")
            self._server.shutdown()
    
    def _create_handler_class(self):
        """Create HTTP request handler class with access to entrypoint handler."""
        entrypoint_handler = self._entrypoint_handler
        
        class AgentRequestHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                """Handle POST requests to /invocations endpoint."""
                if self.path == "/invocations":
                    try:
                        # Read request body
                        content_length = int(self.headers.get('Content-Length', 0))
                        body = self.rfile.read(content_length)
                        request_data = json.loads(body.decode('utf-8'))
                        
                        # Extract input from request
                        input_data = request_data.get("input", {})
                        
                        # Call entrypoint handler
                        response_data = entrypoint_handler(input_data)
                        
                        # Send response
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({"output": response_data}).encode('utf-8'))
                    
                    except Exception as e:
                        # Send error response
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        error_response = {
                            "error": str(e),
                            "type": type(e).__name__
                        }
                        self.wfile.write(json.dumps(error_response).encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()
            
            def do_GET(self):
                """Handle GET requests to /ping endpoint."""
                if self.path == "/ping":
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "healthy"}).encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()
            
            def log_message(self, format, *args):
                """Override to customize logging."""
                print(f"[{self.log_date_time_string()}] {format % args}")
        
        return AgentRequestHandler


# Export main class
__all__ = ['BedrockAgentCoreApp']
