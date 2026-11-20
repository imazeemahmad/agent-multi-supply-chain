"""
Inventory Management Agent Runtime for Amazon Bedrock AgentCore.

Uses Amazon Nova to understand user intent, extract parameters,
and generate natural language responses. DynamoDB provides the
inventory and order data.
"""

import os
import re
import json
import uuid
import boto3
from datetime import datetime
from decimal import Decimal
from botocore.exceptions import ClientError

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bedrock_agentcore import BedrockAgentCoreApp
from agents.nova_helper import call_nova, call_nova_json

app = BedrockAgentCoreApp()

region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
dynamodb = boto3.resource('dynamodb', region_name=region)

INVENTORY_TABLE = os.environ.get('INVENTORY_TABLE', 'supply-chain-inventory')
ORDERS_TABLE = os.environ.get('ORDERS_TABLE', 'supply-chain-orders')

INTENT_SYSTEM_PROMPT = """You are an intent classifier for an inventory management agent.
Given a user message, determine the action and extract parameters.

Available actions:
- check_inventory: Check stock levels for a specific product or all products
- create_purchase_order: Create a purchase order to restock a product
- update_stock: Adjust inventory quantity for a product

Respond with ONLY valid JSON:
{
  "action": "check_inventory|create_purchase_order|update_stock",
  "product_id": "SKU-001 or null if not specified",
  "quantity": null or integer if specified
}"""

RESPONSE_SYSTEM_PROMPT = """You are a helpful inventory management assistant.
Given the user's request and the data retrieved from the inventory system,
generate a clear, conversational response. Include relevant numbers and
recommendations. Be concise but thorough."""


# ── DynamoDB operations ──────────────────────────────────────────────

def get_inventory_item(product_id):
    """Get a single inventory item."""
    try:
        table = dynamodb.Table(INVENTORY_TABLE)
        response = table.get_item(Key={'product_id': product_id})
        return response.get('Item')
    except ClientError as e:
        return None


def scan_all_inventory():
    """Scan all inventory items."""
    try:
        table = dynamodb.Table(INVENTORY_TABLE)
        response = table.scan()
        return response.get('Items', [])
    except ClientError:
        return []


def create_purchase_order(product_id, quantity=None):
    """Create a purchase order in DynamoDB."""
    item = get_inventory_item(product_id)
    if not item:
        return {"error": f"Product {product_id} not found"}

    if quantity is None:
        quantity = int(item.get('reorder_quantity', 100))

    unit_cost = float(item.get('unit_cost', 0))
    total_cost = unit_cost * quantity
    order_id = f"PO-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"

    orders_table = dynamodb.Table(ORDERS_TABLE)
    orders_table.put_item(Item={
        'order_id': order_id,
        'order_type': 'purchase',
        'product_id': product_id,
        'product_name': item.get('product_name', product_id),
        'quantity': quantity,
        'unit_cost': str(unit_cost),
        'total_cost': str(total_cost),
        'supplier_id': item.get('supplier_id', 'N/A'),
        'status': 'pending',
        'created_at': datetime.now().isoformat(),
        'warehouse': item.get('warehouse', 'N/A')
    })

    return {
        "order_id": order_id,
        "product_id": product_id,
        "product_name": item.get('product_name'),
        "quantity": quantity,
        "unit_cost": unit_cost,
        "total_cost": total_cost,
        "supplier_id": item.get('supplier_id'),
        "status": "pending"
    }


def update_stock(product_id, quantity_change):
    """Update stock level for a product."""
    item = get_inventory_item(product_id)
    if not item:
        return {"error": f"Product {product_id} not found"}

    current = int(item['current_stock'])
    new_stock = current + quantity_change
    if new_stock < 0:
        return {"error": f"Cannot reduce below 0. Current: {current}, change: {quantity_change}"}

    table = dynamodb.Table(INVENTORY_TABLE)
    table.update_item(
        Key={'product_id': product_id},
        UpdateExpression='SET current_stock = :s',
        ExpressionAttributeValues={':s': new_stock}
    )

    return {
        "product_id": product_id,
        "product_name": item.get('product_name'),
        "previous_stock": current,
        "change": quantity_change,
        "new_stock": new_stock,
        "reorder_point": int(item.get('reorder_point', 0)),
        "needs_reorder": new_stock <= int(item.get('reorder_point', 0))
    }


# ── Agent handler ────────────────────────────────────────────────────

@app.entrypoint
def inventory_agent_handler(request):
    """Handle inventory requests using Nova for intent detection and response generation."""
    prompt = request.get("prompt", "")
    if not prompt:
        return {"error": "No prompt provided"}

    # Step 1: Ask Nova to determine intent and extract parameters
    intent = call_nova_json(prompt, INTENT_SYSTEM_PROMPT)

    if not intent:
        # Fallback: treat as a general inventory check
        intent = {"action": "check_inventory", "product_id": None, "quantity": None}

    action = intent.get("action", "check_inventory")
    product_id = intent.get("product_id")
    quantity = intent.get("quantity")

    # Step 2: Execute the action against DynamoDB
    if action == "check_inventory":
        if product_id:
            data = get_inventory_item(product_id)
            if not data:
                data = {"error": f"Product {product_id} not found"}
        else:
            items = scan_all_inventory()
            data = {"products": items, "total_count": len(items)}

    elif action == "create_purchase_order":
        if not product_id:
            data = {"error": "Product ID required to create a purchase order"}
        else:
            data = create_purchase_order(product_id, quantity)

    elif action == "update_stock":
        if not product_id or quantity is None:
            data = {"error": "Product ID and quantity required to update stock"}
        else:
            data = update_stock(product_id, quantity)

    else:
        data = {"error": f"Unknown action: {action}"}

    # Step 3: Ask Nova to generate a natural response from the data
    context = f"User request: {prompt}\nAction taken: {action}\nData: {json.dumps(data, default=str)}"
    response_text = call_nova(context, RESPONSE_SYSTEM_PROMPT)

    if not response_text:
        response_text = f"Here's what I found: {json.dumps(data, default=str)}"

    return {
        "response": response_text,
        "agent": "inventory-management",
        "action": action
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
