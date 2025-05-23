import boto3, fnmatch, re, json, time
from typing import List, Tuple

def lambda_handler(event, context):
    manifest = json.loads(event.get("body","{}"))

    manifest = update_manifest(manifest)

    create_or_update_role(manifest)
    create_or_update_lambda(manifest)

    return {
        "statusCode": 200,
        "body": "Deployment Successful",
        
    }

def validate_lambda_policy(policy) -> Tuple[int, List[str]]:
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

    manifest['trust_policy'] = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "lambda.amazonaws.com"
                },
                "Action": "sts:AssumeRole",
                "Condition": {
                    "ArnLike": {
                    "AWS:SourceArn": manifest['lambda_arn']
                    }
                }
            }
        ]
    }

    return manifest

def create_or_update_role(manifest) -> None:
    iam_client = boto3.client('iam')

    paginator = iam_client.get_paginator('list_roles')
    existing_roles = [role['Arn'] for page in paginator.paginate() for role in page['Roles']]

    remote_role = next(iter(r for r in existing_roles if r.lower() == manifest['role_arn'].lower()),None)

    role_arn = remote_role or manifest['role_arn']
    Path, RoleName = re.match(r'.+\:role(\/.*\/)(.+)',role_arn).groups()

    if not remote_role:
        # Create the role
        print(f"Role: {role_arn} doesn't exist yet and will be created")
        iam_client.create_role(
            Path=Path,
            RoleName=RoleName,
            AssumeRolePolicyDocument=json.dumps(manifest['trust_policy']),
        )
    else: 
        print(f"Role: {role_arn} already exists and will be updated")
        iam_client.update_assume_role_policy(
            RoleName=RoleName,
            PolicyDocument=json.dumps(manifest['trust_policy'])
        )
        manifest['role_arn'] = role_arn # Update the role_arn in manifest so lambda has case-sensitive role name

    # Remove all inline policies
    inline_policies = iam_client.list_role_policies(RoleName=RoleName)['PolicyNames']
    for policy_name in inline_policies:
        iam_client.delete_role_policy(RoleName=RoleName, PolicyName=policy_name)
        print(f"Deleted inline policy: {policy_name}")

    # Attach the logging policy
    iam_client.put_role_policy(
        RoleName=RoleName,
        PolicyName='logging_policy',
        PolicyDocument=json.dumps(manifest['logs_policy'])
    )
    print("Attached logging policy")

    # Attach other policies
    policy = manifest.get('policy')
    if policy:
        iam_client.put_role_policy(
            RoleName=RoleName,
            PolicyName='permissions_policy',
            PolicyDocument=json.dumps(policy)
        )
        print("Attached permissions policy")

def wait_for_lambda_update(lambda_client, function_name:str, delay:int=2, max_attempts:int=30):
    for attempt in range(max_attempts):
        resp = lambda_client.get_function_configuration(FunctionName=function_name)
        status = resp['LastUpdateStatus']
        if status == 'Successful':
            return
        elif status == 'Failed':
            raise Exception(f"Lambda update failed: {resp.get('LastUpdateStatusReason', 'unknown')}")
        time.sleep(delay)
    raise TimeoutError("Timed out waiting for Lambda to finish updating.")

def get_most_recent_image_uri(repository_arn:str) -> str:
    ecr_client = boto3.client('ecr')
    region, account_id, repository_name = re.match(r'.+ecr\:(.+)\:(\d+)\:repository\/(.+)',repository_arn).groups()
    response = ecr_client.describe_images(repositoryName=repository_name)
    image_details = response['imageDetails']
    # Sort by pushedAt (descending)
    latest_image = sorted(image_details, key=lambda x: x['imagePushedAt'], reverse=True)[0]
    latest_tag = latest_image['imageTags'][0]  # Take the first tag
    return f"{account_id}.dkr.ecr.{region}.amazonaws.com/{repository_name}:{latest_tag}"

def create_or_update_lambda(manifest) -> None:
    lambda_client = boto3.client('lambda')

    paginator = lambda_client.get_paginator('list_functions')
    existing_functions = [fn['FunctionArn'] for page in paginator.paginate() for fn in page['Functions']]

    remote_function = next(iter(r for r in existing_functions if r.lower() == manifest['lambda_arn'].lower()),None)

    function_arn = remote_function or manifest['lambda_arn']

    image_uri = get_most_recent_image_uri(manifest['repository_arn'])

    if not remote_function:
        # Create the role
        print(f"Function: {function_arn} doesn't exist yet and will be created")
        lambda_client.create_function(
                FunctionName=function_arn,
                Role=manifest['role_arn'],
                Code={'ImageUri': image_uri},
                PackageType='Image',
                Description=manifest['description'],
                MemorySize=manifest['memory'],
                Timeout=manifest['timeout'],
                EphemeralStorage={
                    'Size': manifest['ephemeral_storage']
                },
                Publish=True
            )
    else: 
        print(f"Function: {function_arn} already exists and will be updated")
        lambda_client.update_function_configuration(
            FunctionName=function_arn,
            Role=manifest['role_arn'],
            Description=manifest['description'],
            MemorySize=manifest['memory'],
            Timeout=manifest['timeout'],
            EphemeralStorage={
                'Size': manifest['ephemeral_storage']
            },
        )
        
        wait_for_lambda_update(lambda_client, function_arn)
        
        lambda_client.update_function_code(
            FunctionName=function_arn,
            ImageUri=image_uri,
            Publish=True,
        )