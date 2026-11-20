"""
Shared helper for invoking Amazon Nova foundation model.

Provides a simple interface for agents to use Nova for:
- Intent detection and parameter extraction
- Natural language response generation


Concept
The nova_helper.py script provides the shared interface that all agents use to
communicate with the Amazon Nova foundation model through Amazon Bedrock. 
Instead of each agent writing its own API call, an agent imports this helper for consistent, reusable model invocation
"""

import os
import json
import boto3
import logging

logger = logging.getLogger(__name__)

region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
bedrock_runtime = boto3.client('bedrock-runtime', region_name=region)

MODEL_ID = 'global.amazon.nova-2-lite-v1:0'


def call_nova(user_message, system_prompt, temperature=0.3, max_tokens=1024):
    """
    Call Amazon Nova and return the text response.

    Args:
        user_message: The user's input
        system_prompt: Instructions for the model
        temperature: Sampling temperature (lower = more deterministic)
        max_tokens: Maximum response length

    Returns:
        Response text string
    """
    request_body = {
        "messages": [
            {"role": "user", "content": [{"text": user_message}]}
        ],
        "system": [{"text": system_prompt}],
        "inferenceConfig": {
            "max_new_tokens": max_tokens,
            "temperature": temperature,
        }
    }

    try:
        response = bedrock_runtime.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(request_body)
        )
        body = json.loads(response['body'].read())
        return body['output']['message']['content'][0]['text']
    except Exception as e:
        logger.error(f"Nova invocation failed: {e}")
        return None


def call_nova_json(user_message, system_prompt, temperature=0.1):
    """
    Call Nova and parse the response as JSON.

    The system prompt should instruct the model to respond with valid JSON only.

    Args:
        user_message: The user's input
        system_prompt: Instructions (must request JSON output)
        temperature: Low default for deterministic structured output

    Returns:
        Parsed dict, or None on failure
    """
    raw = call_nova(user_message, system_prompt, temperature=temperature, max_tokens=512)
    if not raw:
        return None

    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse Nova JSON response: {text[:200]}")
        return None
