import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import uuid
from datetime import datetime
from .storage import load_json, atomic_write_json
import re

COMPANIES_FILE = Path("data/auth/companies.json")

def ensure_companies_file():
    COMPANIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not COMPANIES_FILE.exists():
        atomic_write_json(COMPANIES_FILE, {})

def get_companies() -> Dict[str, Any]:
    ensure_companies_file()
    return load_json(COMPANIES_FILE, {})

def save_companies(companies: Dict[str, Any]):
    atomic_write_json(COMPANIES_FILE, companies)

def normalize_company_id(company_id: str) -> str:
    """Stable tenant key used for folders, settings, users, and licenses."""
    normalized = (company_id or "").strip().lower()
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^a-z0-9_-]", "", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-_")
    if not normalized:
        raise ValueError("Company ID is required")
    return normalized

def _normalize_company_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()

def create_company(name: str, company_id: Optional[str] = None) -> Dict[str, Any]:
    companies = get_companies()
    clean_name = re.sub(r"\s+", " ", (name or "").strip())
    if not clean_name:
        raise ValueError("Company name is required")
    
    # If no ID provided, we could still generate one, but plan says slug is provided
    # or auto-generated in frontend. Let's ensure it's unique.
    cid = normalize_company_id(company_id) if company_id else str(uuid.uuid4())
    
    if cid in companies:
        raise ValueError(f"Company ID {cid} already exists")

    wanted_name = _normalize_company_name(clean_name)
    if any(_normalize_company_name(c.get("name", "")) == wanted_name for c in companies.values()):
        raise ValueError(f"Company name {clean_name} already exists")
    
    company_data = {
        "id": cid,
        "name": clean_name,
        "created_at": datetime.now().isoformat()
    }
    companies[cid] = company_data
    save_companies(companies)
    return company_data

def get_company(company_id: str) -> Optional[Dict[str, Any]]:
    companies = get_companies()
    try:
        return companies.get(normalize_company_id(company_id))
    except ValueError:
        return None

def list_companies() -> List[Dict[str, Any]]:
    return sorted(get_companies().values(), key=lambda c: (c.get("name", "").lower(), c.get("id", "")))

def update_company(company_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    companies = get_companies()
    company_id = normalize_company_id(company_id)
    if company_id not in companies:
        return None
    
    company = companies[company_id]
    allowed_updates = ["name", "address"]
    for key, value in updates.items():
        if key in allowed_updates:
            if key == "name":
                clean_name = re.sub(r"\s+", " ", (value or "").strip())
                if not clean_name:
                    raise ValueError("Company name is required")
                wanted_name = _normalize_company_name(clean_name)
                if any(cid != company_id and _normalize_company_name(c.get("name", "")) == wanted_name for cid, c in companies.items()):
                    raise ValueError(f"Company name {clean_name} already exists")
                company[key] = clean_name
            else:
                company[key] = value
            
    save_companies(companies)
    return company

def delete_company(company_id: str) -> bool:
    companies = get_companies()
    try:
        company_id = normalize_company_id(company_id)
    except ValueError:
        return False
    if company_id not in companies:
        return False
    
    # Cascading Cleanup (Users, Tokens, Settings, Physical Data)
    from .cleanup_utils import cleanup_company_data
    cleanup_company_data(company_id)
    
    if company_id in companies: # Re-check in case cleanup modified it or just to be safe
        del companies[company_id]
        save_companies(companies)
    return True
