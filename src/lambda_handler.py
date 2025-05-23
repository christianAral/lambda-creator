import os, boto3, fnmatch, re, json

def lambda_handler(event, context):
    manifest = json.loads(event.get("body","{}"))

    manifest = create_manifest(manifest)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "event": event,
            }
        ),
        
    }, manifest

def sanitize(lambda_name: str) -> str:
    """
    Converts a string into an ARN-safe Lambda function name.
    - Keeps only letters, numbers, hyphens, and underscores.
    - Truncates to 64 characters.
    - Replaces sequences of invalid characters with a single underscore.
    - Strips leading/trailing underscores or hyphens.
    """
    # Replace invalid characters with underscore
    sanitized = re.sub(r'[^A-Za-z0-9_-]+', '_', lambda_name)
    # Remove leading/trailing underscores/hyphens
    sanitized = sanitized.strip('_-')
    # Truncate to 57 chars (ARN limit after suffixes)
    return sanitized[:57]

def validate_lambda_policy(policy):
    errors = []
    allowed_iam_patterns = ["iam:Get*", "iam:List*"]
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):  # single statement object
        statements = [statements]

    for idx, stmt in enumerate(statements):
        actions = stmt.get("Action", [])
        resources = stmt.get("Resource", [])
        if isinstance(actions, str):
            actions = [actions]
        if isinstance(resources, str):
            resources = [resources]

        for action in actions:
            # 1. IAM actions check (except Get/List)
            if action.lower().startswith("iam:"):
                if not any(fnmatch.fnmatch(action, pat) for pat in allowed_iam_patterns):
                    errors.append(
                        f"Statement {idx}: IAM action '{action}' is not permitted (only iam:Get*/iam:List* allowed)."
                    )

            # 2. secretsmanager:GetSecretValue must have fully-qualified (no wildcard) ARNs
            if action == "secretsmanager:GetSecretValue":
                for res in resources:
                    if "*" in res:
                        errors.append(
                            f"Statement {idx}: 'secretsmanager:GetSecretValue' action must use fully-qualified resource ARNs, not wildcards."
                        )

            # 3. lambda:InvokeFunction must have fully-qualified (no wildcard) ARNs
            if action == "lambda:InvokeFunction":
                for res in resources:
                    if "*" in res:
                        errors.append(
                            f"Statement {idx}: 'lambda:InvokeFunction' action must use fully-qualified resource ARNs, not wildcards."
                        )
    return len(errors) == 0, errors

def create_manifest(manifest) -> dict:

    if 'lambda_name' not in manifest:
        manifest['lambda_name'] = os.path.split(os.getcwd())[-1]

    manifest['lambda_name'] = sanitize(manifest['lambda_name'])

    if any(prop not in manifest for prop in ['lambda_arn','role_arn','repository_uri']):
        sts_client = boto3.client('sts')
        account_id = sts_client.get_caller_identity()['Account']
        region_name = sts_client.meta.region_name

    if 'lambda_arn' not in manifest:
        manifest['lambda_arn'] = f"arn:aws:lambda:{region_name}:{account_id}:function:{manifest['lambda_name']}-lambda"

    if 'role_arn' not in manifest:
        manifest['role_arn'] = f"arn:aws:iam::{account_id}:role/{manifest['lambda_name']}-lambda"

    if 'repository_arn' not in manifest:
        manifest['role_arn'] = f"arn:aws:ecr:{region_name}:{account_id}:repository/{manifest['lambda_name']}-lambda"

    manifest['role_arn'] = manifest['role_arn'].lower()
    manifest['repository_arn'] = manifest['repository_uri'].lower()

    props = {
        "description": "",
        "timeout": 30,
        "memory": 128,
        "ephemeral_storage": 512,
    }

    for k,v in props.items():
        manifest[k] = manifest.get(k) or v

    valid_policy, policy_issues = validate_lambda_policy(manifest['policy'])

    if not valid_policy:
        raise PermissionError(f"Requested policies were not permitted {policy_issues}")

    logs_a, logs_b = manifest['lambda_arn'].split(":function:")
    logs_a = logs_a.replace("lambda", "logs") + ":*"
    logs_b = f"{logs_a[:-1]}log-group:/aws/lambda/{logs_b}:*"
    manifest['logs_policy'] = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "logs:CreateLogGroup",
                "Resource": logs_a
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": [
                    logs_b
                ]
            }
        ]
    }

    return manifest