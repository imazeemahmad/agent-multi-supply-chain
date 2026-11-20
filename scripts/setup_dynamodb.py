#!/usr/bin/env python3
"""
DynamoDB Setup Script for Supply Chain Agents

This script loads sample data into the DynamoDB tables for the
Bedrock AgentCore supply chain management system.
Tables are pre-created by the CDK stack.

Usage:
    python scripts/setup_dynamodb.py
"""
"""
Concept
The setup_dynamodb.py script provisions the data layer by loading Amazon DynamoDB tables 
with sample records that the agents depend on for decision-making. 
This provisioning is a prerequisite step; agents require pre-populated data to perform tasks 
such as stock monitoring, order tracking, and demand forecasting.
"""

import boto3
import json
from decimal import Decimal
import csv
import os
import sys
import argparse
import time
from datetime import datetime
from botocore.exceptions import ClientError


class DynamoDBSetup:
    """Handles DynamoDB table creation and data loading."""
    
    def __init__(self, region='us-east-1'):
        """
        Initialize the setup handler.
        
        Args:
            region: AWS region
        """
        self.region = region
        self.dynamodb = boto3.resource('dynamodb', region_name=region)
        self.dynamodb_client = boto3.client('dynamodb', region_name=region)
        
        # Table configurations
        self.tables = {
            'supply-chain-inventory': {
                'KeySchema': [
                    {'AttributeName': 'product_id', 'KeyType': 'HASH'}
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'product_id', 'AttributeType': 'S'}
                ],
                'BillingMode': 'PAY_PER_REQUEST'
            },
            'supply-chain-orders': {
                'KeySchema': [
                    {'AttributeName': 'order_id', 'KeyType': 'HASH'}
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'order_id', 'AttributeType': 'S'},
                    {'AttributeName': 'status', 'AttributeType': 'S'}
                ],
                'GlobalSecondaryIndexes': [
                    {
                        'IndexName': 'status-index',
                        'KeySchema': [
                            {'AttributeName': 'status', 'KeyType': 'HASH'}
                        ],
                        'Projection': {'ProjectionType': 'ALL'}
                    }
                ],
                'BillingMode': 'PAY_PER_REQUEST'
            },
            'supply-chain-sales': {
                'KeySchema': [
                    {'AttributeName': 'product_id', 'KeyType': 'HASH'},
                    {'AttributeName': 'date', 'KeyType': 'RANGE'}
                ],
                'AttributeDefinitions': [
                    {'AttributeName': 'product_id', 'AttributeType': 'S'},
                    {'AttributeName': 'date', 'AttributeType': 'S'}
                ],
                'BillingMode': 'PAY_PER_REQUEST'
            }
        }
    
    def create_table(self, table_name, config):
        """
        Create a DynamoDB table.
        
        Args:
            table_name: Name of the table to create
            config: Table configuration dictionary
            
        Returns:
            True if successful, False otherwise
        """
        print(f"\nCreating table: {table_name}")
        
        try:
            # Check if table already exists
            existing_tables = self.dynamodb_client.list_tables()['TableNames']
            if table_name in existing_tables:
                print(f"  ⚠️  Table {table_name} already exists")
                
                # Wait for table to be active
                table = self.dynamodb.Table(table_name)
                table.wait_until_exists()
                print(f"  ✓ Table {table_name} is active")
                return True
            
            # Create the tableaws s3 ls
            table = self.dynamodb.create_table(
                TableName=table_name,
                **config
            )
            
            # Wait for table to be created
            print(f"  Waiting for table {table_name} to be created...")
            table.wait_until_exists()
            
            print(f"  ✓ Table {table_name} created successfully")
            return True
        
        except ClientError as e:
            print(f"  ✗ Error creating table {table_name}: {e.response['Error']['Message']}")
            return False
        except Exception as e:
            print(f"  ✗ Unexpected error creating table {table_name}: {str(e)}")
            return False
    
    def create_all_tables(self):
        """Create all required DynamoDB tables."""
        print("\n" + "="*70)
        print("CREATING DYNAMODB TABLES")
        print("="*70)
        
        success = True
        for table_name, config in self.tables.items():
            if not self.create_table(table_name, config):
                success = False
        
        if success:
            print("\n✓ All tables created successfully")
        else:
            print("\n⚠️  Some tables failed to create")
        
        return success
    
    def load_inventory_data(self):
        """Load inventory data from sample-data/inventory_data.json."""
        print("\n" + "="*70)
        print("LOADING INVENTORY DATA")
        print("="*70)
        
        # Get path to sample data
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_file = os.path.join(script_dir, '..', 'sample-data', 'inventory_data.json')
        
        if not os.path.exists(data_file):
            print(f"  ✗ Data file not found: {data_file}")
            return False
        
        try:
            # Load data from file (parse floats as Decimal for DynamoDB)
            with open(data_file, 'r') as f:
                data = json.load(f, parse_float=Decimal)
            
            table = self.dynamodb.Table('supply-chain-inventory')
            
            # Insert each inventory item
            for item in data['inventory']:
                # Transform data to match our schema
                inventory_item = {
                    'product_id': item['sku'],
                    'product_name': item['product_name'],
                    'current_stock': item['quantity'],
                    'reorder_point': item['reorder_point'],
                    'reorder_quantity': item['max_stock'] - item['reorder_point'],
                    'unit_cost': str(item['unit_cost']),
                    'supplier_id': item['supplier'],
                    'warehouse': item['warehouse'],
                    'location': item['location']
                }
                
                table.put_item(Item=inventory_item)
                print(f"  ✓ Loaded inventory for {item['sku']}: {item['product_name']}")
            
            print(f"\n✓ Loaded {len(data['inventory'])} inventory items")
            return True
        
        except Exception as e:
            print(f"  ✗ Error loading inventory data: {str(e)}")
            return False
    
    def load_orders_data(self):
        """Load orders data from sample-data/orders.json."""
        print("\n" + "="*70)
        print("LOADING ORDERS DATA")
        print("="*70)
        
        # Get path to sample data
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_file = os.path.join(script_dir, '..', 'sample-data', 'orders.json')
        
        if not os.path.exists(data_file):
            print(f"  ✗ Data file not found: {data_file}")
            return False
        
        try:
            # Load data from file
            with open(data_file, 'r') as f:
                data = json.load(f, parse_float=Decimal)
            
            table = self.dynamodb.Table('supply-chain-orders')
            
            # Insert each order
            for order in data['orders']:
                # Transform data to match our schema
                order_item = {
                    'order_id': order['order_id'],
                    'customer_id': order['customer_id'],
                    'order_date': order['order_date'],
                    'status': order['status'],
                    'items': order['items'],
                    'total_amount': str(order['total_amount']),
                    'shipping': order['shipping']
                }
                
                table.put_item(Item=order_item)
                print(f"  ✓ Loaded order {order['order_id']}: {order['status']}")
            
            print(f"\n✓ Loaded {len(data['orders'])} orders")
            return True
        
        except Exception as e:
            print(f"  ✗ Error loading orders data: {str(e)}")
            return False
    
    def load_sales_data(self):
        """Load sales history from sample-data/sales_history.csv."""
        print("\n" + "="*70)
        print("LOADING SALES DATA")
        print("="*70)
        
        # Get path to sample data
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_file = os.path.join(script_dir, '..', 'sample-data', 'sales_history.csv')
        
        if not os.path.exists(data_file):
            print(f"  ✗ Data file not found: {data_file}")
            return False
        
        try:
            table = self.dynamodb.Table('supply-chain-sales')
            
            # Read CSV file
            with open(data_file, 'r') as f:
                reader = csv.DictReader(f)
                count = 0
                
                for row in reader:
                    # Transform data to match our schema
                    sales_item = {
                        'product_id': row['sku'],
                        'date': row['date'],
                        'quantity_sold': int(row['quantity_sold']),
                        'revenue': str(row['revenue'])
                    }
                    
                    table.put_item(Item=sales_item)
                    count += 1
                
                print(f"  ✓ Loaded {count} sales records")
            
            print(f"\n✓ Sales data loaded successfully")
            return True
        
        except Exception as e:
            print(f"  ✗ Error loading sales data: {str(e)}")
            return False
    
    def load_all_data(self):
        """Load all sample data into DynamoDB tables."""
        print("\n" + "="*70)
        print("LOADING SAMPLE DATA")
        print("="*70)
        
        success = True
        
        if not self.load_inventory_data():
            success = False
        
        if not self.load_orders_data():
            success = False
        
        if not self.load_sales_data():
            success = False
        
        if success:
            print("\n" + "="*70)
            print("✓ ALL DATA LOADED SUCCESSFULLY")
            print("="*70)
        else:
            print("\n" + "="*70)
            print("⚠️  SOME DATA FAILED TO LOAD")
            print("="*70)
        
        return success
    
    def delete_all_tables(self):
        """Delete all tables (for cleanup)."""
        print("\n" + "="*70)
        print("DELETING DYNAMODB TABLES")
        print("="*70)
        print("⚠️  WARNING: This will delete all tables and data!")
        
        confirm = input("Type 'DELETE' to confirm: ")
        if confirm != 'DELETE':
            print("Deletion cancelled.")
            return False
        
        for table_name in self.tables.keys():
            try:
                table = self.dynamodb.Table(table_name)
                table.delete()
                print(f"  ✓ Deleted table: {table_name}")
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print(f"  ⚠️  Table {table_name} does not exist")
                else:
                    print(f"  ✗ Error deleting table {table_name}: {e.response['Error']['Message']}")
        
        print("\n✓ Table deletion complete")
        return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Load sample data into DynamoDB tables for supply chain agents'
    )
    
    args = parser.parse_args()
    
    # Create setup handler
    setup = DynamoDBSetup(region='us-east-1')
    
    try:
        # Load data into existing tables (tables are created by CDK stack)
        if not setup.load_all_data():
            print("\n✗ Failed to load data")
            sys.exit(1)
        
        print("\n" + "="*70)
        print("SETUP COMPLETE!")
        print("="*70)
        print("\nNext Steps:")
        print("  1. Build container images:")
        print("     ./setup-codebuild.sh")
        print("")
        print("  2. Deploy agents:")
        print("     python scripts/deploy_agents.py")
        print("")
        print("="*70)
        
        sys.exit(0)
    
    except KeyboardInterrupt:
        print("\n\nSetup interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nSetup failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
