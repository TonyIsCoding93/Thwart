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
        limit = min(PAGE_SIZE, max_records - skip)
        results = fetch_page(skip=skip, limit=limit)
        if not results:
            break
        for record in results:
            yield record
        skip += len(results)
