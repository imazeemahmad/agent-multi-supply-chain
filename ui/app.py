"""
Supply Chain Multi-Agent System UI

A Streamlit interface for interacting with Amazon Bedrock AgentCore agents.
"""

import streamlit as st
import boto3
import json
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="Supply Chain Agent System",
    page_icon="📦",
    layout="wide"
)

# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'session_id' not in st.session_state:
    import uuid
    st.session_state.session_id = str(uuid.uuid4())  # UUID is 36 characters

# AWS Configuration
st.sidebar.header("Configuration")
REGION = st.sidebar.text_input("AWS Region", value="us-east-1")

# Load agent ARNs from config file
@st.cache_data
def load_agent_config():
    """Load agent ARNs from agent_ids.json file."""
    import os
    config_path = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'agent_ids.json')
    
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return None

agent_config = load_agent_config()

# Debug info
try:
    sts = boto3.client('sts', region_name=REGION)
    account_id = sts.get_caller_identity()['Account']
    st.sidebar.success(f"✓ Connected to AWS Account: {account_id}")
    
    if agent_config:
        st.sidebar.success(f"✓ Loaded {len(agent_config.get('agents', {}))} agent configurations")
    else:
        st.sidebar.warning("⚠️ Agent config not found. Run deploy_agents.py first.")
except Exception as e:
    st.sidebar.error(f"✗ AWS Connection Error: {str(e)}")

# Agent ARNs (load from config or environment)
AGENTS = {
    "Inventory Management": {
        "name": "supply_chain_inventory_agent",
        "description": "Check stock levels, create purchase orders",
        "icon": "📦"
    },
    "Demand Forecasting": {
        "name": "supply_chain_forecasting_agent",
        "description": "Analyze sales trends, forecast demand",
        "icon": "📈"
    },
    "Order Tracking": {
        "name": "supply_chain_tracking_agent",
        "description": "Track orders, assess delivery risks",
        "icon": "🚚"
    },
    "Supplier Management": {
        "name": "supply_chain_supplier_agent",
        "description": "Find suppliers, compare ratings, get contact details",
        "icon": "🏭"
    },
    "Orchestrator": {
        "name": "supply_chain_orchestrator_agent",
        "description": "Coordinate multiple agents for complex workflows",
        "icon": "🎯"
    }
}


def get_agent_arn(agent_name, region):
    """Get the agent ARN from the config file."""
    if not agent_config:
        return None
    
    agents = agent_config.get('agents', {})
    
    # Map display names to config keys
    name_mapping = {
        "supply_chain_inventory_agent": "inventory",
        "supply_chain_forecasting_agent": "forecasting",
        "supply_chain_tracking_agent": "tracking",
        "supply_chain_supplier_agent": "supplier",
        "supply_chain_orchestrator_agent": "orchestrator"
    }
    
    config_key = name_mapping.get(agent_name)
    if config_key and config_key in agents:
        return agents[config_key].get('arn')
    
    return None


def invoke_agent(agent_arn, prompt, session_id, region):
    """Invoke an agent and return the response."""
    try:
        client = boto3.client('bedrock-agentcore', region_name=region)
        
        # Prepare payload
        payload = json.dumps({
            'input': {
                'prompt': prompt
            }
        })
        
        # Invoke agent
        response = client.invoke_agent_runtime(
            agentRuntimeArn=agent_arn,
            runtimeSessionId=session_id,
            payload=payload.encode('utf-8')
        )
        
        # Extract response
        if 'response' in response:
            response_data = response['response']
            if hasattr(response_data, 'read'):
                response_bytes = response_data.read()
                response_json = json.loads(response_bytes.decode('utf-8'))
                
                if 'output' in response_json and 'response' in response_json['output']:
                    return response_json['output']['response']
                else:
                    return json.dumps(response_json, indent=2)
        
        return "No response received"
    
    except Exception as e:
        return f"Error: {str(e)}"


# Header
st.title("📦 Supply Chain Multi-Agent System")
st.markdown("Interact with AI agents to manage your supply chain operations")

# Sidebar - Agent Selection
st.sidebar.header("Select Agent")
selected_agent = st.sidebar.radio(
    "Choose an agent:",
    list(AGENTS.keys()),
    format_func=lambda x: f"{AGENTS[x]['icon']} {x}"
)

st.sidebar.markdown("---")
st.sidebar.markdown(f"**{AGENTS[selected_agent]['description']}**")

# Example prompts
st.sidebar.markdown("---")
st.sidebar.subheader("Example Prompts")

if selected_agent == "Inventory Management":
    examples = [
        "Check inventory for product SKU-001",
        "Show all low stock items",
        "Create a purchase order for SKU-003"
    ]
elif selected_agent == "Demand Forecasting":
    examples = [
        "Forecast demand for SKU-001",
        "Analyze sales trends",
        "Show sales history for SKU-002"
    ]
elif selected_agent == "Order Tracking":
    examples = [
        "Track order ORD-001",
        "Assess delivery risks",
        "Show all delayed orders"
    ]
elif selected_agent == "Supplier Management":
    examples = [
        "Which supplier provides SKU-001?",
        "Get details for supplier SUPP-002",
        "Compare all suppliers by rating"
    ]
else:  # Orchestrator
    examples = [
        "Check inventory and create purchase orders for low stock",
        "Forecast demand and assess order risks",
        "Provide a comprehensive supply chain status report"
    ]

for example in examples:
    if st.sidebar.button(example, key=f"example_{example}"):
        # Store the prompt to be processed
        st.session_state['pending_prompt'] = example
        st.session_state['pending_agent'] = selected_agent
        st.rerun()

# Main chat interface
st.markdown("---")

# Check if there's a pending prompt from example button
if 'pending_prompt' in st.session_state:
    prompt = st.session_state.pop('pending_prompt')
    agent = st.session_state.pop('pending_agent')
    
    # Add user message
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
        "agent": agent
    })
    
    # Get agent response
    agent_name = AGENTS[agent]["name"]
    agent_arn = get_agent_arn(agent_name, REGION)
    
    if agent_arn:
        response = invoke_agent(
            agent_arn,
            prompt,
            st.session_state.session_id,
            REGION
        )
        
        # Add assistant message
        st.session_state.messages.append({
            "role": "assistant",
            "content": response
        })
    else:
        error_msg = f"Agent '{agent_name}' not found. Please ensure agents are deployed."
        st.session_state.messages.append({
            "role": "assistant",
            "content": error_msg
        })
    
    st.rerun()

# Display chat history
for message in st.session_state.messages:
    if message["role"] == "user":
        with st.chat_message("user"):
            st.markdown(f"**To {message['agent']}:** {message['content']}")
    else:
        with st.chat_message("assistant"):
            st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Ask the agent..."):
    # Add user message
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
        "agent": selected_agent
    })
    
    # Display user message
    with st.chat_message("user"):
        st.markdown(f"**To {selected_agent}:** {prompt}")
    
    # Get agent response
    with st.chat_message("assistant"):
        with st.spinner(f"Asking {selected_agent}..."):
            agent_name = AGENTS[selected_agent]["name"]
            agent_arn = get_agent_arn(agent_name, REGION)
            
            if agent_arn:
                response = invoke_agent(
                    agent_arn,
                    prompt,
                    st.session_state.session_id,
                    REGION
                )
                st.markdown(response)
                
                # Add assistant message
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response
                })
            else:
                error_msg = f"Agent '{agent_name}' not found. Please ensure agents are deployed."
                st.error(error_msg)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_msg
                })

# Clear chat button
if st.sidebar.button("Clear Chat History"):
    st.session_state.messages = []
    import uuid
    st.session_state.session_id = str(uuid.uuid4())
    st.rerun()

# Footer
st.sidebar.markdown("---")
st.sidebar.caption(f"Session ID: {st.session_state.session_id}")
