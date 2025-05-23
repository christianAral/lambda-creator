import sys
import subprocess
import boto3
import snowflake.snowpark as snowpark

def make_snowflake_service(service_name:str) -> None:
    '''
    Creates a Snowflake service account with an associated RSA key pair, 
    stores the private key in AWS Secrets Manager, and configures Snowflake 
    user and role permissions.

    Args:
        service_name (str): The name of the service account. Must start with 'svc_'.

    Raises:
        ValueError: If the service name does not start with 'svc_'.
        subprocess.SubprocessError: If key generation or cleanup fails.
        botocore.exceptions.BotoCoreError: If storing the secret in AWS fails.
        snowflake.snowpark.exceptions.SnowparkClientException: If Snowflake operations fail.

    Returns:
        None
    '''
    
    if not service_name.lower().startswith('svc_'):
        raise ValueError(f'{service_name=} is not allowed! Analytics dept requires service account names to start with `svc_`')
    try:
        # Create Private Key
        subprocess.run(
            [
                'ssh-keygen',
                '-t','rsa',
                '-b','2048',
                '-m','PKCS8',
                '-f', f'{service_name}.p8',
                '-N', '',
                '-q'
            ],
            check=True,
            timeout=2
        )

        # Create Public Key
        stdout = subprocess.run(
            [
                'ssh-keygen',
                '-e',
                '-m','PKCS8',
                '-f',f'{service_name}.p8'
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=2
        ).stdout
        pubkey = ''.join(stdout.splitlines()[1:-1])

        # Save private key to AWS
        with open(f'{service_name}.p8','r') as f:
            aws_client = boto3.client('secretsmanager')
            aws_client.create_secret(
                Name=f'sf/{service_name}',
                SecretString=''.join(f.readlines())
            )

        # Login to snowflake and assume admin role
        session = snowpark.Session.builder.config('connection_name','myconnection').create()
        session.use_role('accountadmin')

        # Create snowflake role
        session.sql(f'create role {service_name}').collect()

        # Create snowflake user
        session.sql(f'''
            CREATE USER {service_name}
            TYPE=SERVICE
            DEFAULT_ROLE={service_name}
            NETWORK_POLICY = open_ip_policy;
        ''').collect()

        # Assign RSA key to user
        session.sql(f'''
            ALTER USER {service_name}
            SET RSA_PUBLIC_KEY={pubkey!r};
        ''').collect()

        # Assign snowflake role to user
        session.sql(f'''
            GRANT ROLE {service_name} to USER {service_name};
        ''').collect()

        # Assign snowflake role to master service accounts role
        session.sql(f'''
            GRANT ROLE {service_name} to ROLE SERVICE_ACCOUNTS;
        ''').collect()

        # Close snowflake session
        session.close()

    finally:
        # Clean Up Directory
        subprocess.run(
            [
                'rm', 
                '-f', 
                f'{service_name}.p8.pub',
                f'{service_name}.p8',
            ],
            check=True,
            timeout=2
        )
        
    return None

if __name__ == "__main__":
    make_snowflake_service(sys.argv[1])