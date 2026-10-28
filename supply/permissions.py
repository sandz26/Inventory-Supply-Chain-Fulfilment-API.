from rest_framework.permissions import BasePermission

from supply.models import User


def is_admin(user):
    return bool(user and user.is_authenticated and user.role == User.Role.ADMIN)


class IsAdminRole(BasePermission):
    message = "This is an admin action."

    def has_permission(self, request, view):
        return is_admin(request.user)


class IsOwnerOrAdmin(BasePermission):
    message = "You can only change your own orders."

    def has_object_permission(self, request, view, obj):
        if is_admin(request.user):
            return True
        return obj.requested_by_id == request.user.id
