# Use an AWS Lambda base image for Python
FROM public.ecr.aws/lambda/python:3.11

# Set the working directory inside the container
WORKDIR /var/task

# Copy the Python application files to the root of /var/task
COPY src/ .  
COPY requirements.txt ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Ensure Python can find the module
ENV PYTHONPATH="/var/task:${PYTHONPATH}"

# Command to run the Lambda function
CMD ["lambda_handler.lambda_handler"]
