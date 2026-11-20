#!/usr/bin/env python3
"""
Testing Script for Deployed Amazon Bedrock AgentCore Agents

This script tests agents deployed to Amazon Bedrock AgentCore by invoking them
via the InvokeAgentRuntime API. It runs a comprehensive test suite and
reports results.

Usage:
    python test_deployed.py [--region REGION] [--agent-ids-file FILE]

Arguments:
    --region          AWS region (default: us-east-1)
    --agent-ids-file  Path to agent_ids.json file (default: agent_ids.json)

Example:
    python test_deployed.py --region us-west-2

Note: This script requires agent_ids.json file created by deploy_agents.py
"""

import boto3
import json
import uuid
import sys
import os
import argparse
import time
from botocore.exceptions import ClientError


class AgentTester:
    """Handles testing of deployed agents."""
    
    def __init__(self, region='us-east-1'):
        """
        Initialize the tester.
        
        Args:
            region: AWS region
        """
        self.region = region
        
        # Initialize AWS client
        session = boto3.Session(region_name=region)
        self.bedrock_agentcore = session.client('bedrock-agentcore')
        
        # Test cases for each agent
        self.test_cases = {
            'inventory': [
                {
                    'name': 'Check inventory for product SKU-001',
                    'prompt': 'Check inventory for product SKU-001',
                    'expected_keywords': ['inventory', 'stock', 'SKU-001']
                },
                {
                    'name': 'Check inventory for product SKU-002',
                    'prompt': 'What is the current stock level for product SKU-002?',
                    'expected_keywords': ['stock', 'SKU-002']
                },
                {
                    'name': 'Create purchase order',
                    'prompt': 'Create a purchase order for product SKU-003 with quantity 100',
                    'expected_keywords': ['purchase', 'order', 'SKU-003']
                }
            ],
            'forecasting': [
                {
                    'name': 'Get sales history',
                    'prompt': 'Get sales history for product SKU-001',
                    'expected_keywords': ['sales', 'history', 'SKU-001']
                },
                {
                    'name': 'Forecast demand',
                    'prompt': 'Forecast demand for product SKU-001 for next 7 days',
                    'expected_keywords': ['forecast', 'demand', 'SKU-001']
                },
                {
                    'name': 'Analyze sales trends',
                    'prompt': 'Analyze sales trends for product SKU-002',
                    'expected_keywords': ['sales', 'trend', 'SKU-002']
                }
            ],
            'tracking': [
                {
                    'name': 'Get order status',
                    'prompt': 'Get status of order ORD-001',
                    'expected_keywords': ['order', 'status', 'ORD']
                },
                {
                    'name': 'Track order',
                    'prompt': 'Track order ORD-002',
                    'expected_keywords': ['order', 'ORD']
                },
                {
                    'name': 'Assess delivery risk',
                    'prompt': 'Assess delivery risks for all orders',
                    'expected_keywords': ['delivery', 'risk']
                }
            ],
            'orchestrator': [
                {
                    'name': 'Multi-agent workflow - inventory and orders',
                    'prompt': 'Check inventory levels and create purchase orders for low stock items',
                    'expected_keywords': ['inventory', 'purchase', 'order']
                },
                {
                    'name': 'Multi-agent workflow - forecast and risk',
                    'prompt': 'Forecast demand and assess order risks',
                    'expected_keywords': ['forecast', 'risk']
                },
                {
                    'name': 'Comprehensive status report',
                    'prompt': 'Provide a comprehensive supply chain status report',
                    'expected_keywords': ['supply', 'chain', 'status']
                }
            ]
        }
    
    def test_agent_deployed(self, agent_arn, test_case):
        """
        Test a deployed agent via InvokeAgentRuntime API.
        
        Args:
            agent_arn: ARN of the agent runtime
            test_case: Test case dictionary with prompt and expected keywords
            
        Returns:
            Dictionary with test results
        """
        session_id = str(uuid.uuid4())
        
        try:
            print(f"    Invoking agent: {agent_arn}")
            print(f"    Session ID: {session_id}")
            print(f"    Prompt: {test_case['prompt']}")
            
            # Prepare the payload - bedrock_agentcore expects {"input": {"prompt": "..."}}
            payload = json.dumps({
                'input': {
                    'prompt': test_case['prompt']
                }
            })
            
            print(f"    Payload: {payload}")
            
            # Invoke the agent runtime
            response = self.bedrock_agentcore.invoke_agent_runtime(
                agentRuntimeArn=agent_arn,
                runtimeSessionId=session_id,
                payload=payload.encode('utf-8')
            )
            
            # Debug: print response structure
            print(f"    Response keys: {list(response.keys())}")
            print(f"    Status code: {response.get('statusCode', 'N/A')}")
            print(f"    Content type: {response.get('contentType', 'N/A')}")
            
            # Extract response - it's in the 'response' field as a StreamingBody
            response_text = ""
            if 'response' in response:
                response_data = response['response']
                print(f"    Response type: {type(response_data)}")
                
                # If it's a StreamingBody, read it
                if hasattr(response_data, 'read'):
                    response_bytes = response_data.read()
                    response_text = response_bytes.decode('utf-8')
                # If it's bytes, decode it
                elif isinstance(response_data, bytes):
                    response_text = response_data.decode('utf-8')
                # If it's a string, use it directly
                elif isinstance(response_data, str):
                    response_text = response_data
                # If it's a dict, convert to JSON
                elif isinstance(response_data, dict):
                    response_text = json.dumps(response_data, indent=2)
                else:
                    print(f"    Unexpected response type: {type(response_data)}")
            else:
                print(f"    No 'response' in response object")
            
            print(f"    Response: {response_text[:200]}...")  # Show first 200 chars
            
            # Print full response for debugging
            print(f"\n    Full Response:")
            print(f"    {'-'*66}")
            if response_text:
                print(f"    {response_text}")
            else:
                print(f"    (EMPTY RESPONSE)")
            print(f"    {'-'*66}")
            print(f"    Response length: {len(response_text)} characters")
            
            # Check for expected keywords
            keywords_found = [
                kw for kw in test_case.get('expected_keywords', [])
                if kw.lower() in response_text.lower()
            ]
            
            return {
                'success': True,
                'response': response_text,
                'keywords_found': keywords_found,
                'error': None
            }
        
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            print(f"    ✗ Error: {error_code} - {error_message}")
            
            return {
                'success': False,
                'response': None,
                'keywords_found': [],
                'error': f"{error_code}: {error_message}"
            }
        
        except Exception as e:
            print(f"    ✗ Error: {str(e)}")
            
            return {
                'success': False,
                'response': None,
                'keywords_found': [],
                'error': str(e)
            }
    
    def run_test_suite(self, agents):
        """
        Run comprehensive test suite against deployed agents.
        
        Args:
            agents: Dictionary mapping agent keys to agent info (id and arn)
            
        Returns:
            Dictionary with test results
        """
        print("\n" + "="*70)
        print("AMAZON BEDROCK AGENTCORE - AGENT TESTING")
        print("="*70)
        print(f"Region: {self.region}")
        print(f"Testing {len(agents)} agents")
        print("="*70)
        
        all_results = {}
        
        for agent_key, agent_info in agents.items():
            print(f"\n{'='*70}")
            print(f"Testing {agent_key.upper()} Agent")
            print(f"{'='*70}")
            print(f"Agent ARN: {agent_info['arn']}")
            
            if agent_key not in self.test_cases:
                print(f"  ⚠️  No test cases defined for {agent_key}")
                continue
            
            agent_results = []
            
            for i, test_case in enumerate(self.test_cases[agent_key], 1):
                print(f"\n  Test {i}/{len(self.test_cases[agent_key])}: {test_case['name']}")
                
                result = self.test_agent_deployed(agent_info['arn'], test_case)
                result['test_name'] = test_case['name']
                agent_results.append(result)
                
                if result['success']:
                    print(f"    ✓ Test passed")
                    if result['keywords_found']:
                        print(f"    Keywords found: {', '.join(result['keywords_found'])}")
                else:
                    print(f"    ✗ Test failed: {result['error']}")
                
                time.sleep(1)  # Brief pause between tests
            
            all_results[agent_key] = agent_results
        
        # Print summary
        self.print_test_summary(all_results)
        
        return all_results
    
    def print_test_summary(self, results):
        """Print test summary."""
        print(f"\n{'='*70}")
        print("TEST SUMMARY")
        print(f"{'='*70}")
        
        total_tests = 0
        total_passed = 0
        
        for agent_key, agent_results in results.items():
            passed = sum(1 for r in agent_results if r['success'])
            total = len(agent_results)
            total_tests += total
            total_passed += passed
            
            status = "✓" if passed == total else "✗"
            print(f"{status} {agent_key.capitalize():15} {passed}/{total} tests passed")
        
        print(f"{'-'*70}")
        success_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
        print(f"Overall: {total_passed}/{total_tests} tests passed ({success_rate:.1f}%)")
        print(f"{'='*70}")
    
    def save_test_results(self, results):
        """Save test results to a file."""
        output_file = 'test_results.json'
        
        with open(output_file, 'w') as f:
            json.dump({
                'region': self.region,
                'tested_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'results': results
            }, f, indent=2)
        
        print(f"\n✓ Test results saved to: {output_file}")


def load_agent_ids(file_path):
    """Load agent information from file."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            return data.get('agents', {})
    except FileNotFoundError:
        print(f"Error: Agent IDs file not found: {file_path}")
        print("Please run deploy_agents.py first to create the file.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in file: {file_path}")
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Test deployed supply chain agents on Amazon Bedrock AgentCore'
    )
    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )
    parser.add_argument(
        '--agent-ids-file',
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent_ids.json'),
        help='Path to agent_ids.json file'
    )
    
    args = parser.parse_args()
    
    # Load agent information
    agents = load_agent_ids(args.agent_ids_file)
    
    if not agents:
        print("Error: No agent information found in file")
        sys.exit(1)
    
    # Create tester and run tests
    tester = AgentTester(region=args.region)
    
    try:
        results = tester.run_test_suite(agents)
        
        # Exit with error code if any tests failed
        all_passed = all(
            all(r['success'] for r in agent_results)
            for agent_results in results.values()
        )
        
        sys.exit(0 if all_passed else 1)
    
    except KeyboardInterrupt:
        print("\n\nTesting interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nTesting failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
