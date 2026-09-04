import requests

BASE_URL = "https://api.fda.gov/drug/label.json"
PAGE_SIZE = 1000


def fetch_page(skip=0, limit=PAGE_SIZE):
    response = requests.get(BASE_URL, params={"limit": limit, "skip": skip})
    response.raise_for_status()
    return response.json()["results"]


def fetch_all(max_records=1000):
    skip = 0
    while skip < max_records:
        results = fetch_page(skip=skip)
        if not results:
            break
        for record in results:
            yield record
        skip += PAGE_SIZE
