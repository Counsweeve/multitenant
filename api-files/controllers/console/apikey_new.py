import logging
from datetime import datetime

from flask_login import current_user
from flask import request
from flask_restx import Resource, fields, marshal_with

from . import api
from .wraps import account_initialization_required, setup_required
from services.api_key_service import ApiKeyService
from services.errors.api_key import (
    ApiKeyNotFoundError,
    ApiKeyExpiredError,
    ApiKeyInactiveError,
    InvalidResourceTypeError,
    DuplicateApiKeyError
)

logger = logging.getLogger(__name__)

api_key_fields = {
    'id': fields.String,
    'key': fields.String,
    'resource_type': fields.String,
    'resource_id': fields.String,
    'resource_name': fields.String,
    'validity_type': fields.String,
    'start_date': fields.DateTime,
    'end_date': fields.DateTime,
    'authorized_person': fields.String,
    'description': fields.String,
    'is_active': fields.Boolean,
    'status': fields.String,
    'created_by': fields.String,
    'created_at': fields.DateTime,
    'updated_at': fields.DateTime,
}

resource_fields = {
    'id': fields.String,
    'name': fields.String,
    'description': fields.String,
}

class ApiKeyListApi(Resource):

    @account_initialization_required
    @setup_required
    def get(self):

        try:
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 10, type=int)
            resource_type = request.args.get('resource_type')
            resource_name = request.args.get('resource_name')
            authorized_person = request.args.get('authorized_person')
            status = request.args.get('status')

            tenant_id = current_user.current_tenant_id

            api_key_service = ApiKeyService()
            pagination = api_key_service.get_api_keys(
                tenant_id=tenant_id,
                page=page,
                per_page=per_page,
                resource_type=resource_type,
                resource_name=resource_name,
                authorized_person=authorized_person,
                status=status
            )

            return {
                'result': 'success',
                'data': [api_key.to_dict() for api_key in pagination.items],
                'total': pagination.total
            }
        except Exception as e:
            logger.exception("Failed to get API keys list")
            return {'error': str(e)}, 500

    @account_initialization_required
    @setup_required
    def post(self):

        try:
            data = request.get_json()
            required_fields = ['resource_type', 'resource_id', 'resource_name', 'validity_type', 'authorized_person']

            for field in required_fields:
                if field not in data:
                    return {'error': f'Missing required field: {field}'}, 400

            start_date = None
            end_date = None
            if data.get('start_date'):
                start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00'))
            if data.get('end_date'):
                end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00'))

            tenant_id = current_user.current_tenant_id
            api_key_service = ApiKeyService()
            api_key = api_key_service.create_api_key(api_key_service,
                tenant_id=tenant_id,
                resource_type=data['resource_type'],
                resource_id=data['resource_id'],
                resource_name=data['resource_name'],
                validity_type=data['validity_type'],
                start_date=start_date,
                end_date=end_date,
                authorized_person=data['authorized_person'],
                description=data.get('description', ''),
                created_by=current_user.id
            )

            return api_key.to_dict()
        except InvalidResourceTypeError as e:
            return {'error': str(e)}, 400
        except DuplicateApiKeyError as e:
            return {'error': str(e)}, 409
        except Exception as e:
            logger.exception("Failed to create API key")
            return {'error': str(e)}, 500

class ApiKeyApi(Resource):

    @account_initialization_required
    @setup_required
    def get(self, api_key_id):

        try:
            tenant_id = current_user.current_tenant_id
            api_key_service = ApiKeyService()
            api_key = api_key_service.get_api_key(tenant_id=tenant_id, api_key_id=api_key_id)
            return api_key.to_dict()
        except ApiKeyNotFoundError as e:
            return {'error': str(e)}, 404
        except Exception as e:
            logger.exception("Failed to get API key")
            return {'error': str(e)}, 500

    @account_initialization_required
    @setup_required
    def put(self, api_key_id):

        try:
            data = request.get_json()
            tenant_id = current_user.current_tenant_id

            api_key_service = ApiKeyService()
            api_key = api_key_service.update_api_key(
                tenant_id=tenant_id,
                api_key_id=api_key_id,
                **data
            )
            return api_key.to_dict()
        except ApiKeyNotFoundError as e:
            return {'error': str(e)}, 404
        except Exception as e:
            logger.exception("Failed to update API key")
            return {'error': str(e)}, 500

    @account_initialization_required
    @setup_required
    def delete(self, api_key_id):
        try:
            tenant_id = current_user.current_tenant_id
            api_key_service = ApiKeyService()
            api_key_service.delete_api_key(tenant_id=tenant_id, api_key_id=api_key_id)
            return {'result': 'success'}
        except ApiKeyNotFoundError as e:
            return {'error': str(e)}, 404
        except Exception as e:
            logger.exception("Failed to delete API key")
            return {'error': str(e)}, 500

class ApiKeyToggleApi(Resource):

    @account_initialization_required
    @setup_required
    def post(self, api_key_id):
        try:
            tenant_id = current_user.current_tenant_id
            api_key_service = ApiKeyService()
            api_key = api_key_service.toggle_api_key_status(api_key_service, tenant_id, api_key_id)
            return api_key.to_dict()
        except ApiKeyNotFoundError as e:
            return {'error': str(e)}, 404
        except Exception as e:
            logger.exception("Failed to toggle API key status")
            return {'error': str(e)}, 500

class ApiKeyResourceApi(Resource):

    @account_initialization_required
    @setup_required
    def get(self):
        try:
            resource_type = request.args.get('resource_type')
            if not resource_type:
                return {'error': 'resource_type parameter is required'}, 400
            tenant_id = current_user.current_tenant_id
            api_key_service = ApiKeyService()
            resources = api_key_service.get_resources_for_selection(api_key_service,tenant_id, resource_type)
            return {
                'result': 'success',
                'data': resources
            }
        except InvalidResourceTypeError as e:
            return {'error': str(e)}, 400
        except Exception as e:
            logger.exception("Failed to get resources")
            return {'error': str(e)}, 500

class ApiKeyCopyApi(Resource):

    @account_initialization_required
    @setup_required
    def post(self, api_key_id):

        try:
            tenant_id = current_user.current_tenant_id
            api_key_service = ApiKeyService()
            api_key = api_key_service.get_api_key(api_key_service, tenant_id, api_key_id)
            return {
                'result': 'success',
                'id': api_key.id,
                'key': api_key.key,
                'message': 'Click to show full key and copy to clipboard'
            }, 200
        except ApiKeyNotFoundError as e:
            return {'error': str(e)}, 404
        except Exception as e:
            logger.exception("Failed to copy API key")
            return {'error': str(e)}, 500

# API路由注册
api.add_resource(ApiKeyListApi, "/api-keys")
api.add_resource(ApiKeyApi, "/api-keys/<string:key_id>")
api.add_resource(ApiKeyToggleApi, "/api-keys/<string:key_id>/toggle")
api.add_resource(ApiKeyResourceApi, "/api-keys/resources")
api.add_resource(ApiKeyCopyApi, "/api-keys/<string:key_id>/copy")
