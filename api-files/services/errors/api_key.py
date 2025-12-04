class ApiKeyError(Exception):
    """Base API key error"""
    pass


class ApiKeyNotFoundError(ApiKeyError):
    """API key not found error"""
    pass


class ApiKeyExpiredError(ApiKeyError):
    """API key expired error"""
    pass


class ApiKeyInactiveError(ApiKeyError):
    """API key inactive error"""
    pass


class InvalidResourceTypeError(ApiKeyError):
    """Invalid resource type error"""
    pass


class DuplicateApiKeyError(ApiKeyError):
    """Duplicate API key error"""
    pass
