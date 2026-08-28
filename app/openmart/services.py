from __future__ import annotations

import hashlib
import os
import re
import uuid

from flask import current_app
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.models import db
from .models import OpenmartUser, OpenmartWorkspace


DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000004")


def seed_demo_user():
    """Create an explicitly configured development seed account idempotently."""
    if not current_app.config.get("OPENMART_SEED_ENABLED", False):
        return None
    email = str(current_app.config.get("OPENMART_SEED_EMAIL") or os.getenv("OPENMART_SEED_EMAIL", "")).strip().lower()
    password = str(current_app.config.get("OPENMART_SEED_PASSWORD") or os.getenv("OPENMART_SEED_PASSWORD", ""))
    if not email or not password:
        current_app.logger.warning("Openmart seed account was enabled without credentials; no account was created")
        return None
    display_name = str(current_app.config.get("OPENMART_SEED_DISPLAY_NAME") or "Openmart Demo").strip()
    workspace_name = str(current_app.config.get("OPENMART_SEED_WORKSPACE") or "Openmart Demo").strip()
    existing = OpenmartUser.query.filter_by(email=email, deleted_at=None).first()
    if existing:
        return existing
    workspace = OpenmartWorkspace.query.filter_by(id=DEFAULT_WORKSPACE_ID, deleted_at=None).first()
    if workspace is None:
        workspace = OpenmartWorkspace(id=DEFAULT_WORKSPACE_ID, name=workspace_name, plan="free", credits_balance=200, default_country="US")
        db.session.add(workspace)
    user = OpenmartUser(
        workspace=workspace,
        email=email,
        display_name=display_name,
        password_hash=generate_password_hash(password),
        role="owner",
        is_active=True,
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        user = OpenmartUser.query.filter_by(email=email, deleted_at=None).first()
        if user is None:
            raise
    return user


RAW_BUSINESSES = [
    ("om_001", "Austin Taco Company", "Restaurant", "Austin", "TX", "1200 S Congress Ave", "austintacoco.com", "+1 512 555 0101", 4.8, 1240, 42, 3200000, "Maria Alvarez", "Owner"),
    ("om_002", "Lone Star Plumbing", "Plumber", "Austin", "TX", "4102 Burnet Rd", "lonestarplumbing.com", "+1 512 555 0102", 4.7, 486, 18, 2100000, "Robert Chen", "Owner / Master Plumber"),
    ("om_003", "Smile Bright Dental", "Dentist", "Chicago", "IL", "450 N Michigan Ave", "smilebrightchicago.com", "+1 312 555 0143", 4.9, 692, 24, 4300000, "Sarah Jenkins", "Founder & Lead Dentist"),
    ("om_004", "Golden Gate Auto Repair", "Auto Repair", "San Francisco", "CA", "890 Valencia St", "goldengateauto.com", "+1 415 555 0188", 4.6, 821, 17, 2700000, "Michael Rodriguez", "General Manager"),
    ("om_005", "Downtown Legal Partners", "Law Firm", "New York", "NY", "120 Broadway", "downtownlegal.nyc", "+1 212 555 0121", 4.7, 225, 39, 8400000, "Elena Martinez", "Managing Partner"),
    ("om_006", "Bella Vita Restaurant", "Restaurant", "Miami Beach", "FL", "100 Ocean Dr", "bellavitamiami.com", "+1 305 555 0199", 4.8, 1850, 31, 5100000, "James O'Connor", "Owner & Executive Chef"),
    ("om_007", "Seattle Tech Solutions", "IT Services", "Seattle", "WA", "400 Pine St", "seattletech.io", "+1 206 555 0177", 4.5, 118, 26, 6200000, "Marcus Johnson", "CEO"),
    ("om_008", "Denver Landscape Pros", "Landscaper", "Denver", "CO", "1500 Colorado Blvd", "denverlandscapes.com", "+1 303 555 0134", 4.9, 412, 13, 1900000, "Amanda Lewis", "Owner"),
    ("om_009", "Phoenix Family Chiropractic", "Chiropractor", "Phoenix", "AZ", "200 E Camelback Rd", "phoenixchiro.com", "+1 602 555 0155", 4.8, 536, 9, 1500000, "David Kim", "Clinic Director"),
    ("om_010", "Atlanta Logistics Group", "Logistics", "Atlanta", "GA", "3000 Peachtree Rd", "atllogistics.net", "+1 404 555 0166", 4.4, 204, 67, 12800000, "Maria Garcia", "Operations Director"),
    ("om_011", "Boston Heritage Real Estate", "Real Estate", "Boston", "MA", "150 Boylston St", "bostonheritage.com", "+1 617 555 0122", 4.7, 341, 22, 6900000, "Robert Taylor", "Principal Broker"),
    ("om_012", "Vegas Event Planners", "Event Planning", "Las Vegas", "NV", "3000 Las Vegas Blvd", "vegasevents.com", "+1 702 555 0188", 4.9, 277, 12, 1800000, "Jennifer Wu", "Founder"),
    ("om_013", "Portland Organic Grocers", "Grocery", "Portland", "OR", "1000 W Burnside St", "portlandorganic.com", "+1 503 555 0144", 4.6, 975, 46, 7300000, "Thomas Brown", "Store Manager"),
    ("om_014", "Dallas Fitness Center", "Gym", "Dallas", "TX", "2000 McKinney Ave", "dallasfitness.net", "+1 214 555 0133", 4.7, 728, 21, 2800000, "Lisa Patel", "Owner"),
    ("om_015", "Nashville Sound Studios", "Recording Studio", "Nashville", "TN", "100 Music Square E", "nashvillesound.com", "+1 615 555 0111", 4.9, 184, 8, 1300000, "William Clark", "Studio Manager"),
    ("om_016", "Detroit Manufacturing Co", "Manufacturing", "Detroit", "MI", "500 Woodward Ave", "detroitmfg.com", "+1 313 555 0190", 4.3, 96, 82, 21400000, "Rachel Green", "Plant Manager"),
    ("om_017", "Sunrise Bakery & Cafe", "Bakery", "San Francisco", "CA", "456 Ocean Ave", "sunrisebakery.com", "+1 415 555 0123", 4.8, 1104, 14, 2300000, "Sofia Jenkins", "Owner"),
    ("om_018", "Metro Beauty Salon", "Hair Salon", "Los Angeles", "CA", "720 Melrose Ave", "metrobeautysalon.com", "+1 213 555 0789", 4.7, 663, 16, 2600000, "Emma Rodriguez", "Owner"),
    ("om_019", "Peak Heating & Cooling", "HVAC", "Denver", "CO", "2200 Blake St", "peakhvac.com", "+1 303 555 0179", 4.9, 889, 34, 5900000, "Noah Williams", "President"),
    ("om_020", "Urban Roof & Solar", "Roofing", "Phoenix", "AZ", "3100 N Central Ave", "urbanroofsolar.com", "+1 602 555 0168", 4.6, 443, 29, 7200000, "Olivia Davis", "Co-founder"),
    ("om_021", "Cali Coast Dentistry", "Dentist", "Los Angeles", "CA", "850 Wilshire Blvd", "calicoast.com", "+1 310 555 0456", 4.6, 517, 28, 5100000, "Marcus Johnson", "Founder"),
    ("om_022", "Bay Area Orthodontics", "Orthodontist", "Oakland", "CA", "1900 Broadway", "bayortho.com", "+1 510 555 0789", 4.9, 605, 12, 3900000, "Sarah Williams", "Practice Manager"),
    ("om_023", "Coral Gables Bistro", "Restaurant", "Miami", "FL", "155 Miracle Mile", "coralgablesbistro.com", "+1 305 555 0234", 4.6, 738, 25, 4200000, "Ana Lopez", "Owner"),
    ("om_024", "Brickell Sushi House", "Restaurant", "Miami", "FL", "88 SW 7th St", "brickellsushi.com", "+1 305 555 0312", 4.9, 1321, 33, 6700000, "Ken Tanaka", "Managing Partner"),
]


CATALOG = [
    {
        "external_id": row[0], "name": row[1], "category": row[2], "city": row[3], "region": row[4],
        "street": row[5], "website": f"https://{row[6]}", "phone": row[7], "rating": row[8],
        "review_count": row[9], "employee_count": row[10], "revenue_estimate": row[11],
        "owner_name": row[12], "owner_title": row[13], "domain": row[6], "country": "US", "postal_code": "",
    }
    for row in RAW_BUSINESSES
]


def search_catalog(query: str, location: str, filters: dict, limit: int):
    query_terms = [term[:-1] if term.endswith("s") and len(term) > 3 else term for term in re.split(r"\W+", query.lower()) if len(term) > 1]
    location_terms = [term for term in re.split(r"\W+", location.lower()) if len(term) > 1]
    minimum_rating = float(filters.get("minimumRating", 0) or 0)
    minimum_reviews = int(filters.get("minimumReviews", 0) or 0)
    maximum_employees = int(filters.get("maximumEmployees", 0) or 0)
    matches = []
    for business in CATALOG:
        haystack = f"{business['name']} {business['category']}".lower()
        place = f"{business['city']} {business['region']} {business['country']}".lower()
        if query_terms and not all(term in haystack for term in query_terms):
            continue
        if location_terms and not all(term in place for term in location_terms):
            continue
        if business["rating"] < minimum_rating or business["review_count"] < minimum_reviews:
            continue
        if maximum_employees and business["employee_count"] > maximum_employees:
            continue
        matches.append(business)
    if not matches and query_terms:
        matches = [business for business in CATALOG if any(term in f"{business['name']} {business['category']}".lower() for term in query_terms)]
    return matches[:limit]


def enrichment_for(business):
    domain = business.website.replace("https://", "").replace("http://", "").split("/", 1)[0]
    first = re.sub(r"[^a-z]", "", business.owner_name.lower().split(" ", 1)[0]) or "owner"
    return {
        "company_email": f"info@{domain}",
        "owner_email": f"{first}@{domain}",
        "owner_phone": business.phone,
    }


def key_hash(value: str):
    return hashlib.sha256(value.encode()).hexdigest()
