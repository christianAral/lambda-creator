# Local Development Setup

## AWS Environment

### Overview

Boto3 has the ability to use an access key and secret ID that are stored in environment varialbes. The steps below outline how to generate and store these environment variables.

### Steps

1. From AWS console, create an access key + secret ID for your individual user. This is sensitive information and will enable anyone with access to act as you within AWS. Do not share these credentials!
2. Open up a terminal window on your local machine and edit the contents of the `~/.bashrc` or `~/.zshrc` file to include several lines for your AWS credentials.

```bash
export AWS_ACCESS_KEY_ID=<your-access-key>
export AWS_SECRET_ACCESS_KEY=<your-secret-id>
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
```

3. If your IDE is open, restart it for environment variables to stick

## Snowflake Environment

### Overview

The `snowflake-snowpark-python` package allows automated login for both user and service account types. By generating an RSA keypair and setting the public RSA key for a snowflake user, a connections.toml file can be used to streamline the login process

### Steps

1. Create Directory if not exists

```zsh
mkdir -p ~/.snowflake
```

2. Change Directory

```zsh
cd ~/.snowflake
```

3. Create Private Key

```zsh
ssh-keygen -t rsa -b 2048 -m PKCS8 -f svc_<name>.p8
```

4. Create Public Key

```zsh
ssh-keygen -e -m PKCS8 -f svc_<name>.p8 > svc_<name>.pub
```

5. Create a `connections.toml` file file in the current working directory with the contents below

```toml
[myconnection]
account = "jva07313.us-east-1"
user = "<YOUR_USERNAME>"
private_key_file = "/Users/<HOMEDIRECTORY>/.snowflake/snowflake.p8"
```

6. Upload Public Key

```SQL
USE ROLE ACCOUNTADMIN;
ALTER USER <YOUR_USERNAME> SET RSA_PUBLIC_KEY='MIIB...';
```

7. Query Snowflake from python

```python
from snowflake.snowpark import Session
session = Session.builder.config('connection_name','myconnection').create()

resp = session.sql('SELECT * FROM TABLE').collect()

session.close()
```

# Enable Interfacing with Snowflake

## Overview

Deployed images can read and write to snowflake via the `snowflake-snowpark-python` package. A basic summary of steps is below:

1. Generate RSA keypair and assign to snowflake user
2. Save private key to AWS secrets manager with key prefix `sf/`
3. Create dedicated Snowflake user and role
4. Assign `secretsmanager:GetSecretValue` permission to image execution role for the specified resource

The first three steps above can be largely automated with the included `keygen.py` provided a user has `ACCOUNTADMIN` role in Snowflake. Run the script with `python ./keygen.py <service_name>`.

### Requirements

- Local user must have Snowflake credential saved in `~/.snowflake/connections.toml`.

# AWS GitHub CI/CD Role One-Time Setup

## Overview

The `arn:aws:iam::473958445471:role/github-cicd` role has already been created in VaynerMedia's AWS instance and gives permission to login from the `VaynerMedia-NY` organization. Steps are included below as an example but are not required for future setups.

## Steps

1. Create a github actions OIDC trust policy.
2. Attach inline policy for permissions to enable read + write to AWS ECR.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:DescribeRepositories",
        "ecr:CreateRepository",
        "ecr:BatchGetImage",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:GetAuthorizationToken",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "*"
    }
  ]
}
```

3. Attach additional managed policies for whatever resources will be hosting your image e.g. aws managed policy `AWSLambda_FullAccess`.
