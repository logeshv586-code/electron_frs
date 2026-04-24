from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from .companies import (
    create_company, get_company, update_company, delete_company, list_companies
)

router = APIRouter(prefix="/companies", tags=["companies"])

class CreateCompanyRequest(BaseModel):
    name: str
    company_id: Optional[str] = None
    address: Optional[str] = ""

class UpdateCompanyRequest(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None

@router.post("/")
async def create_company_endpoint(request: CreateCompanyRequest, request_obj: Request):
    current_user = request_obj.scope.get("user")
    if not current_user or current_user["role"] != "SuperAdmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can manage companies")
    
    try:
        company = create_company(name=request.name, company_id=request.company_id)
        if request.address:
            company = update_company(company["id"], {"address": request.address}) or company
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "Company created successfully", "company": company}

@router.get("/")
async def list_companies_endpoint(request: Request):
    current_user = request.scope.get("user")
    if not current_user or current_user["role"] != "SuperAdmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can manage companies")
    
    companies = list_companies()
    return {"companies": companies}

@router.get("/{company_id}")
async def get_company_endpoint(company_id: str, request: Request):
    current_user = request.scope.get("user")
    if not current_user or current_user["role"] != "SuperAdmin":
        # Allow company admins to see their own company? 
        # For now, stick to SuperAdmin as per requirements for "Companies" tab
        raise HTTPException(status_code=403, detail="Only SuperAdmin can manage companies")
    
    company = get_company(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"company": company}

@router.put("/{company_id}")
async def update_company_endpoint(company_id: str, request: UpdateCompanyRequest, request_obj: Request):
    current_user = request_obj.scope.get("user")
    if not current_user or current_user["role"] != "SuperAdmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can manage companies")
    
    updates = request.dict(exclude_unset=True)
    try:
        company = update_company(company_id, updates)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "Company updated successfully", "company": company}

@router.delete("/{company_id}")
async def delete_company_endpoint(company_id: str, request: Request):
    current_user = request.scope.get("user")
    if not current_user or current_user["role"] != "SuperAdmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can manage companies")
    
    if delete_company(company_id):
        return {"message": "Company deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Company not found")
