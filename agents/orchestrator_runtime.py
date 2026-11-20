"""
Orchestrator Agent Runtime for Amazon Bedrock AgentCore.

Uses Amazon Nova to route requests to specialist agents and
synthesize their responses into a unified answer. Supports
multi-agent invocation for complex queries.
"""
"""
Concept
The orchestrator_runtime.py script provides the coordinating orchestrator agent. 
This agent does not perform supply chain tasks itself but decides which specialist agents to invoke 
and combines their responses into a single answer. 
In this practice solution, the orchestrator agent uses Amazon Nova for both routing decisions and response synthesis.
"""

import os
import json
import uuid
import boto3

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bedrock_agentcore import BedrockAgentCoreApp
from agents.nova_helper import call_nova, call_nova_json

app = BedrockAgentCoreApp()

region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
bedrock_agentcore = boto3.client('bedrock-agentcore', region_name=region)

ROUTING_SYSTEM_PROMPT = """You are a routing agent for a supply chain management system.
Given a user message, decide which specialist agent(s) should handle it.

Available agents:
- inventory: Manages stock levels, checks inventory, creates purchase orders, updates quantities
- forecasting: Analyzes sales history, forecasts demand, identifies trends
- tracking: Tracks orders, monitors delivery status, assesses delivery risks
- supplier: Finds suppliers for products, compares supplier ratings, retrieves supplier details

A request may need one or multiple agents. For example:
- "Check inventory for SKU-001" → ["inventory"]
- "Forecast demand and check stock for SKU-001" → ["forecasting", "inventory"]
- "Which supplier provides SKU-001?" → ["supplier"]
- "Give me a full supply chain overview" → ["inventory", "forecasting", "tracking", "supplier"]

Respond with ONLY valid JSON:
{
  "agents": ["inventory", "forecasting", "tracking", "supplier"],
  "reasoning": "brief explanation of why these agents were selected"
}"""

SYNTHESIS_SYSTEM_PROMPT = """You are a supply chain management coordinator.
You received responses from specialist agents. Synthesize them into a single,
coherent response for the user. Connect insights across agents where relevant.
For example, if inventory is low and demand is increasing, highlight that risk.
Be conversational, concise, and actionable."""


def invoke_specialist(agent_id, prompt, session_id):
    """Invoke a specialist agent via AgentCore Runtime API."""
    try:
        account_id = boto3.client('sts').get_caller_identity()['Account']
        payload = json.dumps({'input': {'prompt': prompt}})

        response = bedrock_agentcore.invoke_agent_runtime(
            agentRuntimeArn=f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{agent_id}",
            runtimeSessionId=session_id,
            payload=payload.encode('utf-8')
        )

        if 'response' in response:
            data = response['response']
            if hasattr(data, 'read'):
                body = json.loads(data.read().decode('utf-8'))
                return body.get('output', {}).get('response', json.dumps(body))
            return str(data)
        return "No response received"
    except Exception as e:
        return f"Error: {str(e)}"


AGENT_ID_MAP = {
    'inventory': os.environ.get('INVENTORY_AGENT_ID'),
    'forecasting': os.environ.get('FORECAST_AGENT_ID'),
    'tracking': os.environ.get('TRACKING_AGENT_ID'),
    'supplier': os.environ.get('SUPPLIER_AGENT_ID'),
}


@app.entrypoint
def orchestrator_handler(request):
    """
    Route requests to specialist agents using Nova for intelligent routing,
    then synthesize responses into a unified answer.
    """
    prompt = request.get("prompt", "")
    if not prompt:
        return {"error": "No prompt provided"}

    session_id = request.get("session_id", str(uuid.uuid4()))

    # Step 1: Ask Nova which agents should handle this request
    routing = call_nova_json(prompt, ROUTING_SYSTEM_PROMPT)

    if not routing or 'agents' not in routing:
        # Fallback: invoke all agents
        routing = {"agents": ["inventory", "forecasting", "tracking"], "reasoning": "fallback"}

    target_agents = routing['agents']
    invoked_agents = []
    agent_responses = {}

    # Step 2: Invoke each selected specialist agent
    for agent_key in target_agents:
        agent_id = AGENT_ID_MAP.get(agent_key)
        if not agent_id:
            agent_responses[agent_key] = f"{agent_key} agent not configured"
            continue

        response = invoke_specialist(agent_id, prompt, session_id)
        agent_responses[agent_key] = response
        invoked_agents.append(agent_key)

    # Step 3: Ask Nova to synthesize all responses into one coherent answer
    synthesis_input = f"User request: {prompt}\n\n"
    for agent_key, resp in agent_responses.items():
        synthesis_input += f"--- {agent_key.upper()} AGENT ---\n{resp}\n\n"

    final_response = call_nova(synthesis_input, SYNTHESIS_SYSTEM_PROMPT)

    if not final_response:
        # Fallback: concatenate responses
        parts = [f"**{k.capitalize()} Agent:**\n{v}" for k, v in agent_responses.items()]
        final_response = "\n\n".join(parts)

    return {
        "response": final_response,
        "agent": "orchestrator",
        "session_id": session_id,
        "invoked_agents": invoked_agents,
        "routing_reasoning": routing.get('reasoning', '')
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
