"""
Explicit development fixtures.

These IDs are NOT LGD village codes.
No population, crop, competition or infrastructure claims are made.
Replace with verified source records during ingestion.
"""

DEMO_VILLAGES = [
    {
        "id": "demo-nashik-a",
        "name": "Demo village A",
        "district": "Nashik",
        "state": "Maharashtra",
        "lgd_code": None,
        "is_demo": True,
        "source": "Development fixture — not verified geography",
    },
    {
        "id": "demo-nashik-b",
        "name": "Demo village B",
        "district": "Nashik",
        "state": "Maharashtra",
        "lgd_code": None,
        "is_demo": True,
        "source": "Development fixture — not verified geography",
    },
    {
        "id": "demo-jalgaon-a",
        "name": "Demo village A",
        "district": "Jalgaon",
        "state": "Maharashtra",
        "lgd_code": None,
        "is_demo": True,
        "source": "Development fixture — not verified geography",
    },
    {
        "id": "demo-jalgaon-b",
        "name": "Demo village B",
        "district": "Jalgaon",
        "state": "Maharashtra",
        "lgd_code": None,
        "is_demo": True,
        "source": "Development fixture — not verified geography",
    },
]

VILLAGE_BY_ID = {village["id"]: village for village in DEMO_VILLAGES}
