FIELDS: dict = {}
def get_connection_field(plugin_id, field_name, default=None):
    return FIELDS.get(field_name, default)
