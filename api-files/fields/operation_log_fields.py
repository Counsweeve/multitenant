from flask_restx import fields

system_operation_log_fields = {
    'id': fields.String(description='日志ID'),
    'account_email': fields.String(description='操作人邮箱'),
    'action': fields.String(description='操作类型'),
    'action_name': fields.String(description='操作类型名称'),
    'content': fields.Raw(description='操作内容详情'),
    'description': fields.String(description='操作描述'),
    'ip_address': fields.String(description='操作IP地址'),
    'created_at': fields.DateTime(description='操作时间'),
}

system_operation_log_list_fields = {
    'logs': fields.List(fields.Nested(system_operation_log_fields), description='日志列表'),
    'total': fields.Integer(description='总记录数'),
    'page': fields.Integer(description='当前页码'),
    'page_size': fields.Integer(description='总页数'),
}

system_operation_log_statistics_fields = {
    'action_stats': fields.List(fields.Raw, description='按操作类型统计'),
    'date_stats': fields.List(fields.Raw, description='按日期统计'),
}
