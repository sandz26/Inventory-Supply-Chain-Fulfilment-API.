"""One error shape for every API response, so clients can branch on a code."""

from rest_framework.views import exception_handler

_CODES = {
    400: "validation_error",
    401: "not_authenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
}


def _message(data):
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        return str(data["detail"])
    if isinstance(data, list):
        return str(data[0]) if data else "Request could not be completed."
    return "Some fields need another look."


def _details(data):
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        return None
    return data


def api_exception_handler(exc, context):
    # Clients always read error.code. Whatever DRF built sits under details.
    response = exception_handler(exc, context)
    if response is None:
        return None
    response.data = {
        "error": {
            "code": _CODES.get(response.status_code, "error"),
            "message": _message(response.data),
            "details": _details(response.data),
        }
    }
    return response
