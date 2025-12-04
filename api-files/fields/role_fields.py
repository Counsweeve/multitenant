from typing import List, Optional
from pydantic import BaseModel

class AuthorizedPersonEntity(BaseModel):
    """被授权人实体"""
    id: str
    account: str
    role: str
    name: str
    tenant_id: str


class ResourceEntity(BaseModel):
    """资源实体"""
    id: str
    name: str
    type: str  # 'model' 或 'dataset'
    description: Optional[str] = None


class AuthorizedResourceEntity(BaseModel):
    """已授权资源实体"""
    id: str
    name: str
    type: str
    description: Optional[str] = None


class UnauthorizedResourceEntity(BaseModel):
    """未授权资源实体"""
    id: str
    name: str
    type: str
    description: Optional[str] = None


class AuthorizedPersonListResponse(BaseModel):
    """被授权人列表响应"""
    authorized_persons: List[AuthorizedPersonEntity]
    total: int
    page: int
    page_size: int


class ResourceAuthorizationResponse(BaseModel):
    """资源授权响应"""
    authorized_resources: List[AuthorizedResourceEntity]
    unauthorized_resources: List[UnauthorizedResourceEntity]
    resource_type: str  # 'model' 或 'dataset'


class ResourceAuthorizationRequest(BaseModel):
    """资源授权请求"""
    role_id: str
    resource_type: str  # 'model' 或 'dataset'
    authorized_resource_ids: List[str]
    unauthorized_resource_ids: List[str]


class AuthorizedPersonSearchRequest(BaseModel):
    """被授权人搜索请求"""
    email: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    page: int = 1
    page_size: int = 10
