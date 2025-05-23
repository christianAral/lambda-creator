import boto3
import json

def secrets_manager_retreival():
    client = boto3.client('secretsmanager')
    resp = client.get_secret_value(SecretId='dummy/secret')
    return json.loads(resp['SecretString'])