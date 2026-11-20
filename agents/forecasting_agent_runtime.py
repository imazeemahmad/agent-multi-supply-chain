"""
Demand Forecasting Agent Runtime for Amazon Bedrock AgentCore.

Uses Amazon Nova to understand forecasting requests and generate
insights from sales history stored in DynamoDB.
"""

import os
import json
import boto3
from datetime import datetime, timedelta
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bedrock_agentcore import BedrockAgentCoreApp
from agents.nova_helper import call_nova, call_nova_json

app = BedrockAgentCoreApp()

region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
dynamodb = boto3.resource('dynamodb', region_name=region)

SALES_TABLE = os.environ.get('SALES_TABLE', 'supply-chain-sales')
INVENTORY_TABLE = os.environ.get('INVENTORY_TABLE', 'supply-chain-inventory')

INTENT_SYSTEM_PROMPT = """You are an intent classifier for a demand forecasting agent.
Given a user message, determine the action and extract parameters.

Available actions:
- forecast_demand: Predict future demand for a product
- analyze_trends: Analyze historical sales trends

Respond with ONLY valid JSON:
{
  "action": "forecast_demand|analyze_trends",
  "product_id": "SKU-001 or null if not specified",
  "days": integer number of days to forecast or analyze (default 7 for forecast, 30 for trends)
}"""

RESPONSE_SYSTEM_PROMPT = """You are a demand forecasting analyst.
Given the user's request and the sales/inventory data, generate a clear
analytical response. Include trends, recommendations, and actionable insights.
Use numbers to support your analysis. Be concise but insightful."""


# ── DynamoDB operations ──────────────────────────────────────────────

def get_sales_history(product_id, days=30):
    """Get sales history for a product."""
    try:
        table = dynamodb.Table(SALES_TABLE)
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        response = table.query(
            KeyConditionExpression=Key('product_id').eq(product_id) &
                                   Key('date').gte(start_date)
        )
        return response.get('Items', [])
    except ClientError:
        return []


def get_inventory_item(product_id):
    """Get inventory info for a product."""
    try:
        table = dynamodb.Table(INVENTORY_TABLE)
        response = table.get_item(Key={'product_id': product_id})
        return response.get('Item')
    except ClientError:
        return None


def compute_forecast_data(product_id, forecast_days=7):
    """Gather sales history and inventory data for forecasting."""
    sales = get_sales_history(product_id, days=30)
    inventory = get_inventory_item(product_id)

    if not sales:
        return {"error": f"No sales history found for {product_id}"}

    quantities = [int(s['quantity_sold']) for s in sales]
    revenues = [float(s['revenue']) for s in sales]
    total_qty = sum(quantities)
    total_rev = sum(revenues)
    days_count = len(sales)
    avg_daily = total_qty / days_count if days_count else 0

    # Simple trend: compare first half vs second half
    mid = days_count // 2
    if mid > 0:
        first_avg = sum(quantities[:mid]) / mid
        second_avg = sum(quantities[mid:]) / (days_count - mid)
        if second_avg > first_avg * 1.1:
            trend = "increasing"
        elif second_avg < first_avg * 0.9:
            trend = "decreasing"
        else:
            trend = "stable"
    else:
        trend = "stable"

    result = {
        "product_id": product_id,
        "product_name": inventory.get('product_name', product_id) if inventory else product_id,
        "history_days": days_count,
        "total_units_sold": total_qty,
        "total_revenue": round(total_rev, 2),
        "avg_daily_sales": round(avg_daily, 1),
        "min_daily": min(quantities),
        "max_daily": max(quantities),
        "trend": trend,
        "forecast_days": forecast_days,
        "forecasted_units": int(avg_daily * forecast_days),
        "forecasted_revenue": round((total_rev / days_count) * forecast_days, 2) if days_count else 0,
    }

    if inventory:
        current_stock = int(inventory.get('current_stock', 0))
        result["current_stock"] = current_stock
        result["stock_covers_forecast"] = current_stock >= result["forecasted_units"]
        if not result["stock_covers_forecast"]:
            result["shortage"] = result["forecasted_units"] - current_stock

    return result


def compute_trends_data(product_id=None):
    """Gather trend data across one or all products."""
    if product_id:
        sales = get_sales_history(product_id, days=30)
        if not sales:
            return {"error": f"No sales data for {product_id}"}
        quantities = [int(s['quantity_sold']) for s in sales]
        revenues = [float(s['revenue']) for s in sales]
        return {
            "product_id": product_id,
            "days_analyzed": len(sales),
            "total_units": sum(quantities),
            "total_revenue": round(sum(revenues), 2),
            "avg_daily_units": round(sum(quantities) / len(sales), 1),
            "avg_daily_revenue": round(sum(revenues) / len(sales), 2),
        }

    # All products
    inv_table = dynamodb.Table(INVENTORY_TABLE)
    products = inv_table.scan().get('Items', [])
    summaries = []
    for p in products:
        pid = p['product_id']
        sales = get_sales_history(pid, days=30)
        if sales:
            rev = sum(float(s['revenue']) for s in sales)
            summaries.append({
                "product_id": pid,
                "product_name": p.get('product_name', pid),
                "total_units": sum(int(s['quantity_sold']) for s in sales),
                "total_revenue": round(rev, 2),
            })
    summaries.sort(key=lambda x: x['total_revenue'], reverse=True)
    return {"products_analyzed": len(summaries), "summaries": summaries}


# ── Agent handler ────────────────────────────────────────────────────

@app.entrypoint
def forecasting_agent_handler(request):
    """Handle forecasting requests using Nova for intent detection and response generation."""
    prompt = request.get("prompt", "")
    if not prompt:
        return {"error": "No prompt provided"}

    # Step 1: Intent detection
    intent = call_nova_json(prompt, INTENT_SYSTEM_PROMPT)
    if not intent:
        intent = {"action": "analyze_trends", "product_id": None, "days": 30}

    action = intent.get("action", "analyze_trends")
    product_id = intent.get("product_id")
    days = intent.get("days", 7 if action == "forecast_demand" else 30)

    # Step 2: Gather data
    if action == "forecast_demand":
        if not product_id:
            data = {"error": "Please specify a product ID to forecast demand."}
        else:
            data = compute_forecast_data(product_id, days)
    else:
        data = compute_trends_data(product_id)

    # Step 3: Generate natural response
    context = f"User request: {prompt}\nAction: {action}\nData: {json.dumps(data, default=str)}"
    response_text = call_nova(context, RESPONSE_SYSTEM_PROMPT)

    if not response_text:
        response_text = f"Here's the analysis: {json.dumps(data, default=str)}"

    return {
        "response": response_text,
        "agent": "demand-forecasting",
        "action": action
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
