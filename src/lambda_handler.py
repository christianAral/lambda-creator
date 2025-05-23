import json

from examples.requests_examples import requests_get_example
from examples.boto3_examples import secrets_manager_retreival
from examples.snowflake_examples import snowpark_example

def lambda_handler(event, context):

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "requests_status": requests_get_example(),
                "aws_secrets_example": secrets_manager_retreival(),
                "snowpark_example": snowpark_example(),
                "event": event,
            }
        )
    }