Supply Chain Multi-Agent System UI
===================================

A Streamlit interface for interacting with AWS Bedrock AgentCore agents.

Setup:
------
1. Install dependencies:
   pip install -r requirements.txt

2. Ensure AWS credentials are configured:
   - AWS CLI configured with credentials
   - Or environment variables set (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)

3. Run the application:
   streamlit run app.py

Features:
---------
- Select from 4 agents: Inventory, Forecasting, Tracking, Orchestrator
- Chat interface with conversation history
- Example prompts for each agent
- Real-time agent responses from AWS Bedrock AgentCore

Usage:
------
1. Select an agent from the sidebar
2. Type your question or click an example prompt
3. View the agent's response in the chat
4. Continue the conversation or switch agents
