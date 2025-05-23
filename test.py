import sys
sys.path.append('src')
import src.lambda_handler

if __name__ == '__main__':
    # Test the lambda_handler function
    event = {}
    context = {}
    response = src.lambda_handler.lambda_handler(event, context)
    print(response)