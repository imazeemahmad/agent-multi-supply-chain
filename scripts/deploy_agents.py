#!/usr/bin/env python3
"""
Deployment Script for Amazon Bedrock AgentCore Agents

This script automates the deployment of all supply chain management agents
to Amazon Bedrock AgentCore Runtime. It creates agent runtimes with the
appropriate container images and configuration.

Usage:
    python deploy_agents.py [--region REGION]

Arguments:
    --region  AWS region (default: us-east-1)

Example:
    python deploy_agents.py --region us-west-2

Note: This script assumes container images have already been pushed to ECR
      using the build_and_push.sh script.
"""
"""
Concept
The deploy_agents.py script registers and launches the supply chain agents on Amazon Bedrock AgentCore Runtime. 
The script first deploys specialist agents and then the orchestrator agent that coordinates them, 
providing the orchestrator agent the references to each specialist agent ID.
"""

import boto3
import os
import time
import sys
import argparse
import json
from botocore.exceptions import ClientError


class AgentDeployer:
    """Handles deployment of agents to Bedrock AgentCore."""
    
    def __init__(self, region='us-east-1', role_arn=None):
        """
        Initialize the deployer.
        
        Args:
            region: AWS region
            role_arn: Pre-created IAM role ARN for AgentCore Runtime agents
        """
        self.region = region
        self.role_arn = role_arn
        
        # Initialize AWS clients
        session = boto3.Session(region_name=region)
        self.bedrock_agentcore = session.client('bedrock-agentcore-control')
        self.sts = session.client('sts')
        
        # Get account information
        self.account_id = self.sts.get_caller_identity()['Account']
        self.ecr_registry = f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com"
        
        # DynamoDB table names
        self.inventory_table = 'supply-chain-inventory'
        self.orders_table = 'supply-chain-orders'
        self.sales_table = 'supply-chain-sales'
        
        # Agent configurations
        self.agents = {
            'inventory': {
                'name': 'supply_chain_inventory_agent',
                'description': 'Monitors inventory levels and creates purchase orders',
                'image': f'{self.ecr_registry}/supply-chain-inventory-agent:latest',
                'env_vars': {
                    'AWS_DEFAULT_REGION': self.region,
                    'INVENTORY_TABLE': self.inventory_table,
                    'ORDERS_TABLE': self.orders_table
                }
            },
            'forecasting': {
                'name': 'supply_chain_forecasting_agent',
                'description': 'Analyzes sales data and forecasts demand',
                'image': f'{self.ecr_registry}/supply-chain-forecasting-agent:latest',
                'env_vars': {
                    'AWS_DEFAULT_REGION': self.region,
                    'SALES_TABLE': self.sales_table,
                    'INVENTORY_TABLE': self.inventory_table
                }
            },
            'tracking': {
                'name': 'supply_chain_tracking_agent',
                'description': 'Tracks orders and assesses delivery risks',
                'image': f'{self.ecr_registry}/supply-chain-tracking-agent:latest',
                'env_vars': {
                    'AWS_DEFAULT_REGION': self.region,
                    'ORDERS_TABLE': self.orders_table
                }
            },
            'orchestrator': {
                'name': 'supply_chain_orchestrator_agent',
                'description': 'Coordinates multi-agent workflows',
                'image': f'{self.ecr_registry}/supply-chain-orchestrator-agent:latest',
                'env_vars': {
                    'AWS_DEFAULT_REGION': self.region
                }  # Will be populated with specialist agent IDs
            }
        }
    
    def get_or_create_agent_role(self, agent_key):
        """
        Get the pre-created IAM role for AgentCore Runtime agents.
        
        Args:
            agent_key: Key identifying the agent (unused, kept for compatibility)
            
        Returns:
            IAM role ARN
        """
        if not self.role_arn:
            raise ValueError(
                "No role ARN provided. Pass --role-arn with the AgentCoreRuntimeRoleArn "
                "from the CDK stack outputs."
            )
        print(f"  Using pre-created IAM role: {self.role_arn}")
        return self.role_arn
    
    def find_existing_agent(self, agent_name):
        """
        Find an existing agent runtime by name.
        
        Args:
            agent_name: Name of the agent to find
            
        Returns:
            Agent runtime ID if found, None otherwise
        """
        try:
            # List all agent runtimes and find matching name
            response = self.bedrock_agentcore.list_agent_runtimes()
            
            for agent in response.get('agentRuntimes', []):
                if agent.get('agentRuntimeName') == agent_name:
                    return agent.get('agentRuntimeId')
            
            return None
        
        except Exception as e:
            print(f"  Warning: Could not list agent runtimes: {str(e)}")
            return None
    
    def create_agent_runtime(self, agent_key, config):
        """
        Create an AgentCore Runtime for an agent.
        
        Args:
            agent_key: Key identifying the agent (inventory, forecasting, etc.)
            config: Agent configuration dictionary
            
        Returns:
            Agent runtime ID
        """
        print(f"\n{'='*70}")
        print(f"Creating {agent_key.upper()} agent runtime...")
        print(f"{'='*70}")
        print(f"Name: {config['name']}")
        print(f"Description: {config['description']}")
        print(f"Image: {config['image']}")
        
        if config.get('env_vars'):
            print(f"Environment Variables:")
            for key, value in config['env_vars'].items():
                print(f"  {key}: {value}")
        
        try:
            # Get or create IAM role for the agent
            role_arn = self.get_or_create_agent_role(agent_key)
            print(f"IAM Role: {role_arn}")
            
            # Prepare the create_agent_runtime request
            request_params = {
                'agentRuntimeName': config['name'],
                'description': config['description'],
                'agentRuntimeArtifact': {
                    'containerConfiguration': {
                        'containerUri': config['image']
                    }
                },
                'roleArn': role_arn,
                'networkConfiguration': {
                    'networkMode': 'PUBLIC'  # PUBLIC mode for internet access
                },
                'protocolConfiguration': {
                    'serverProtocol': 'HTTP'  # AgentCore Runtime uses HTTP
                }
            }
            
            # Add environment variables if present
            if config.get('env_vars'):
                request_params['environmentVariables'] = config['env_vars']
            
            print(f"\nCalling bedrock-agentcore-control.create_agent_runtime()...")
            response = self.bedrock_agentcore.create_agent_runtime(**request_params)
            
            agent_runtime_id = response['agentRuntimeId']
            agent_runtime_arn = response['agentRuntimeArn']
            status = response['status']
            
            print(f"\n✓ Created {agent_key} agent runtime")
            print(f"  Runtime ID: {agent_runtime_id}")
            print(f"  Runtime ARN: {agent_runtime_arn}")
            print(f"  Status: {status}")
            
            # Wait for the agent to be ready
            if status not in ['ACTIVE', 'READY']:
                self.wait_for_agent_ready(agent_runtime_id)
            
            return agent_runtime_id, agent_runtime_arn
        
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            if error_code == 'ConflictException':
                print(f"\n⚠️  Agent runtime '{config['name']}' already exists")
                print(f"  Attempting to find existing agent...")
                
                # Try to find the existing agent
                existing_id = self.find_existing_agent(config['name'])
                if existing_id:
                    print(f"  ✓ Found existing agent: {existing_id}")
                    # Get the ARN for the existing agent
                    try:
                        response = self.bedrock_agentcore.get_agent_runtime(agentRuntimeId=existing_id)
                        existing_arn = response.get('agentRuntimeArn', '')
                        return existing_id, existing_arn
                    except:
                        return existing_id, ''
                else:
                    print(f"\n✗ Could not find existing agent")
                    print(f"  Please delete the existing agent or use a different name")
                    raise
            
            print(f"\n✗ Error creating {agent_key} agent:")
            print(f"  Code: {error_code}")
            print(f"  Message: {error_message}")
            
            if error_code == 'AccessDeniedException':
                print(f"  Check IAM permissions for bedrock-agentcore:CreateAgentRuntime")
            
            raise
        
        except Exception as e:
            print(f"\n✗ Unexpected error creating {agent_key} agent: {str(e)}")
            raise
    
    def wait_for_agent_ready(self, agent_runtime_id, max_wait=300):
        """
        Wait for agent runtime to be ready.
        
        Args:
            agent_runtime_id: ID of the agent runtime
            max_wait: Maximum time to wait in seconds
            
        Returns:
            True if agent is ready, raises exception otherwise
        """
        print(f"\nWaiting for agent {agent_runtime_id} to be ready...")
        
        start_time = time.time()
        while time.time() - start_time < max_wait:
            try:
                response = self.bedrock_agentcore.get_agent_runtime(
                    agentRuntimeId=agent_runtime_id
                )
                status = response['status']
                
                if status in ['ACTIVE', 'READY']:
                    print(f"✓ Agent {agent_runtime_id} is ready (status: {status})")
                    return True
                elif status == 'FAILED':
                    failure_reason = response.get('failureReason', 'Unknown')
                    raise Exception(
                        f"Agent {agent_runtime_id} failed to deploy. Reason: {failure_reason}"
                    )
                else:
                    print(f"  Status: {status} (waiting...)")
                
                time.sleep(10)
            
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print(f"  Agent not found yet (waiting...)")
                    time.sleep(10)
                else:
                    raise
        
        raise Exception(
            f"Agent {agent_runtime_id} did not become ready within {max_wait} seconds"
        )
    
    def ensure_service_linked_role(self):
        """
        Ensure all AgentCore service-linked roles exist.
        
        CreateAgentRuntime requires two SLRs:
        - Network: network.bedrock-agentcore.amazonaws.com
        - Identity: runtime-identity.bedrock-agentcore.amazonaws.com
        
        See: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/service-linked-roles.html
        """
        iam_client = boto3.client('iam', region_name=self.region)
        
        service_names = [
            'network.bedrock-agentcore.amazonaws.com',
            'runtime-identity.bedrock-agentcore.amazonaws.com',
        ]
        
        created_any = False
        for service_name in service_names:
            try:
                iam_client.create_service_linked_role(
                    AWSServiceName=service_name
                )
                print(f"  ✓ Created service-linked role for {service_name}")
                created_any = True
            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_msg = e.response['Error'].get('Message', '')
                if error_code == 'InvalidInput' and 'has been taken' in error_msg:
                    print(f"  ✓ Service-linked role for {service_name} already exists")
                elif error_code == 'AccessDeniedException':
                    print(f"  ⚠ No permission to create SLR for {service_name}")
                    print(f"    Ensure the CDK stack is redeployed with updated IAM permissions.")
                else:
                    print(f"  ⚠ Could not create SLR for {service_name}: {error_msg}")
        
        if created_any:
            print("  Waiting for IAM propagation (15s)...")
            time.sleep(15)

    def deploy_all_agents(self):
        """
        Deploy all agents in the correct order.
        
        Returns:
            Dictionary mapping agent keys to runtime info (ID and ARN)
        """
        print("\n" + "="*70)
        print("AMAZON BEDROCK AGENTCORE DEPLOYMENT")
        print("="*70)
        print(f"Region: {self.region}")
        print(f"Account: {self.account_id}")
        print(f"ECR Registry: {self.ecr_registry}")
        print("="*70)
        
        # Ensure service-linked role exists before deploying agents
        print("\n[0/2] Ensuring service-linked role exists...")
        self.ensure_service_linked_role()
        
        agent_info = {}
        
        # Deploy specialist agents first
        print("\n[1/2] Deploying specialist agents...")
        for agent_key in ['inventory', 'forecasting', 'tracking']:
            try:
                runtime_id, runtime_arn = self.create_agent_runtime(agent_key, self.agents[agent_key])
                agent_info[agent_key] = {
                    'id': runtime_id,
                    'arn': runtime_arn
                }
                time.sleep(2)  # Brief pause between deployments
            except Exception as e:
                print(f"\n✗ Failed to deploy {agent_key} agent: {str(e)}")
                print("\nDeployment aborted. Please fix the error and try again.")
                sys.exit(1)
        
        # Deploy orchestrator with specialist agent IDs
        print("\n[2/2] Deploying orchestrator agent...")
        self.agents['orchestrator']['env_vars'] = {
            'INVENTORY_AGENT_ID': agent_info['inventory']['id'],
            'FORECAST_AGENT_ID': agent_info['forecasting']['id'],
            'TRACKING_AGENT_ID': agent_info['tracking']['id']
        }
        
        try:
            runtime_id, runtime_arn = self.create_agent_runtime(
                'orchestrator',
                self.agents['orchestrator']
            )
            agent_info['orchestrator'] = {
                'id': runtime_id,
                'arn': runtime_arn
            }
        except Exception as e:
            print(f"\n✗ Failed to deploy orchestrator agent: {str(e)}")
            print("\nDeployment aborted. Please fix the error and try again.")
            sys.exit(1)
        
        # Print summary
        self.print_deployment_summary(agent_info)
        
        # Save agent info to file
        self.save_agent_info(agent_info)
        
        return agent_info
    
    def print_deployment_summary(self, agent_info):
        """Print deployment summary."""
        print("\n" + "="*70)
        print("DEPLOYMENT COMPLETE!")
        print("="*70)
        print("\nAgent Runtime Information:")
        print("-"*70)
        for agent_key, info in agent_info.items():
            print(f"  {agent_key.capitalize():15}")
            print(f"    ID:  {info['id']}")
            print(f"    ARN: {info['arn']}")
        print("="*70)
        
        print("\nNext Steps:")
        print("  1. Test the deployed agents:")
        print("     python scripts/test_deployed.py")
        print("")
        print("  2. View agent logs in CloudWatch:")
        print(f"     https://console.aws.amazon.com/cloudwatch/home?region={self.region}")
        print("")
        print("  3. Monitor agent performance:")
        print("     Check the GenAI Observability dashboard in CloudWatch")
        print("")
        print("="*70)
    
    def save_agent_info(self, agent_info):
        """Save agent information to a file for later use."""
        # Save to scripts/ directory so the Streamlit UI can find it
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_file = os.path.join(script_dir, 'agent_ids.json')
        
        with open(output_file, 'w') as f:
            json.dump({
                'region': self.region,
                'account_id': self.account_id,
                'agents': agent_info,
                'deployed_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }, f, indent=2)
        
        print(f"\n✓ Agent information saved to: {output_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Deploy supply chain agents to Amazon Bedrock AgentCore'
    )
    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )
    parser.add_argument(
        '--role-arn',
        help='IAM role ARN for AgentCore Runtime (auto-discovered from stack if not provided)'
    )
    
    args = parser.parse_args()
    
    # Auto-discover role ARN from CDK stack if not provided
    role_arn = args.role_arn
    if not role_arn:
        try:
            cfn = boto3.client('cloudformation', region_name=args.region)
            stacks = cfn.list_stacks(StackStatusFilter=['CREATE_COMPLETE', 'UPDATE_COMPLETE'])
            for stack in stacks['StackSummaries']:
                if stack['StackName'].startswith('LabStack-') and stack['StackName'].endswith('-0'):
                    response = cfn.describe_stacks(StackName=stack['StackName'])
                    outputs = response['Stacks'][0].get('Outputs', [])
                    for output in outputs:
                        if output['OutputKey'] == 'AgentCoreRuntimeRoleArn':
                            role_arn = output['OutputValue']
                            print(f"Auto-discovered role ARN: {role_arn}")
                            break
                    break
        except Exception as e:
            print(f"Warning: Could not auto-discover role ARN: {e}")
    
    if not role_arn:
        print("Error: --role-arn is required. Get it from the CDK stack output 'AgentCoreRuntimeRoleArn'.")
        sys.exit(1)
    
    deployer = AgentDeployer(region=args.region, role_arn=role_arn)
    
    try:
        agent_info = deployer.deploy_all_agents()
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\nDeployment interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nDeployment failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
