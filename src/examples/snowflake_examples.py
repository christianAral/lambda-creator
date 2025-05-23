import tempfile
import boto3
import snowflake.snowpark as snowpark

def snowpark_example():
    svc_name = 'svc_example'
    session = create_snowpark_session(svc_name)
    user, role = get_current_user_and_role(session)
    session.close()
    return f"User: {user}, Role: {role}"

def create_snowpark_session(svc_name) -> snowpark.Session:
    # Retrieve the private key from AWS Secrets Manager
    client = boto3.client('secretsmanager')
    private_key = client.get_secret_value(SecretId=f'sf/{svc_name}')['SecretString']
    
    # Create a temporary file for the private key (auto-deletes after exiting the `with` block)
    with tempfile.NamedTemporaryFile(delete=True) as temp_key_file:
        temp_key_file.write(private_key.encode())
        temp_key_file.flush()  # Ensure the file is written before Snowflake reads it

        # Create Snowpark session using the temporary key file
        session = (
        snowpark.Session.builder
            .configs({
                "account":"jva07313.us-east-1",
                "user":svc_name,
                "private_key_file":temp_key_file.name
            })
            .create()
        )
    return session

def get_current_user_and_role(session: snowpark.Session) -> snowpark.Row:
    return session.sql("SELECT CURRENT_USER(), CURRENT_ROLE()").collect()[0]