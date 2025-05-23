import os, boto3, fnmatch, re, json

def lambda_handler(event, context):
    manifest = json.loads(event.get("body","{}"))

    manifest = update_manifest(manifest)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "event": event,
            }
        ),
        
    }

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

def update_manifest(manifest) -> dict:

    lambda_name = manifest['lambda_name']
    repo_arn = manifest['repository_arn']
    arn_parts =  repo_arn.split(':')
    region_name = arn_parts[3]
    account_id = arn_parts[4]

    if 'lambda_arn' not in manifest:
        manifest['lambda_arn'] = f"arn:aws:lambda:{region_name}:{account_id}:function:{lambda_name.replace('/','_')}"

    if 'role_arn' not in manifest:
        manifest['role_arn'] = f"arn:aws:iam::{account_id}:role/lambda/{lambda_name.lower()}"

    props = {
        "description": "",
        "timeout": 30,
        "memory": 128,
        "ephemeral_storage": 512,
    }

    for k,v in props.items():
        manifest[k] = manifest.get(k) or v

    valid_policy, policy_issues = validate_lambda_policy(manifest.get('policy'))

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