"""
Order Tracking Agent Runtime for Amazon Bedrock AgentCore.

Uses Amazon Nova to understand tracking requests and generate
insights from order data stored in DynamoDB.
"""

import os
import json
import boto3
from datetime import datetime
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bedrock_agentcore import BedrockAgentCoreApp
from agents.nova_helper import call_nova, call_nova_json

app = BedrockAgentCoreApp()

region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
dynamodb = boto3.resource('dynamodb', region_name=region)

ORDERS_TABLE = os.environ.get('ORDERS_TABLE', 'supply-chain-orders')

INTENT_SYSTEM_PROMPT = """You are an intent classifier for an order tracking agent.
Given a user message, determine the action and extract parameters.

Available actions:
- track_order: Get detailed status of a specific order
- assess_risks: Assess delivery risks across all active orders
- list_orders: List orders, optionally filtered by status

Respond with ONLY valid JSON:
{
  "action": "track_order|assess_risks|list_orders",
  "order_id": "ORD-001 or null if not specified",
  "status_filter": "pending|in_transit|delayed|delivered or null"
}"""

RESPONSE_SYSTEM_PROMPT = """You are an order tracking specialist.
Given the user's request and the order data, generate a clear,
actionable response. Highlight risks, delays, and recommendations.
Be concise and prioritize the most important information."""


# ── DynamoDB operations ──────────────────────────────────────────────

def get_order(order_id):
    """Get a single order."""
    try:
        table = dynamodb.Table(ORDERS_TABLE)
        response = table.get_item(Key={'order_id': order_id})
        return response.get('Item')
    except ClientError:
        return None


def scan_all_orders():
    """Scan all orders."""
    try:
        table = dynamodb.Table(ORDERS_TABLE)
        response = table.scan()
        return response.get('Items', [])
    except ClientError:
        return []


def get_risk_assessment():
    """Assess delivery risks across all orders."""
    orders = scan_all_orders()
    if not orders:
        return {"error": "No orders found"}

    today = datetime.now().date()
    high_risk, medium_risk, low_risk, completed = [], [], [], []

    for order in orders:
        status = order.get('status', '').lower()
        if status == 'delivered':
            completed.append(order.get('order_id'))
            continue
        if status == 'delayed':
            high_risk.append({"order_id": order['order_id'], "reason": order.get('shipping', {}).get('delay_reason', 'Unknown')})
            continue

        est = order.get('shipping', {}).get('estimated_delivery')
        if est:
            try:
                days_until = (datetime.strptime(est, '%Y-%m-%d').date() - today).days
                entry = {"order_id": order['order_id'], "est_delivery": est, "days_until": days_until}
                if days_until < 0:
                    high_risk.append(entry)
                elif days_until <= 2:
                    medium_risk.append(entry)
                else:
                    low_risk.append(entry)
            except ValueError:
                low_risk.append({"order_id": order['order_id']})
        else:
            low_risk.append({"order_id": order['order_id']})

    return {
        "total_orders": len(orders),
        "completed": len(completed),
        "high_risk": high_risk,
        "medium_risk": medium_risk,
        "low_risk_count": len(low_risk),
    }


# ── Agent handler ────────────────────────────────────────────────────

@app.entrypoint
def tracking_agent_handler(request):
    """Handle tracking requests using Nova for intent detection and response generation."""
    prompt = request.get("prompt", "")
    if not prompt:
        return {"error": "No prompt provided"}

    # Step 1: Intent detection
    intent = call_nova_json(prompt, INTENT_SYSTEM_PROMPT)
    if not intent:
        intent = {"action": "assess_risks", "order_id": None, "status_filter": None}

    action = intent.get("action", "assess_risks")
    order_id = intent.get("order_id")
    status_filter = intent.get("status_filter")

    # Step 2: Gather data
    if action == "track_order":
        if not order_id:
            data = {"error": "Please specify an order ID to track."}
        else:
            order = get_order(order_id)
            data = order if order else {"error": f"Order {order_id} not found"}

    elif action == "list_orders":
        orders = scan_all_orders()
        if status_filter:
            orders = [o for o in orders if o.get('status', '').lower() == status_filter.lower()]
        data = {
            "filter": status_filter or "all",
            "count": len(orders),
            "orders": [{"order_id": o['order_id'], "status": o.get('status'), "type": o.get('order_type', 'customer')} for o in orders[:15]]
        }

    else:  # assess_risks
        data = get_risk_assessment()

    # Step 3: Generate natural response
    context = f"User request: {prompt}\nAction: {action}\nData: {json.dumps(data, default=str)}"
    response_text = call_nova(context, RESPONSE_SYSTEM_PROMPT)

    if not response_text:
        response_text = f"Here's what I found: {json.dumps(data, default=str)}"

    return {
        "response": response_text,
        "agent": "order-tracking",
        "action": action
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
