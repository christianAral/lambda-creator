import requests

def requests_get_example():
    url = 'https://1.1.1.1'
    resp = requests.get(url)
    return resp.status_code