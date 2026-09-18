from django.urls import path
from .views import SetUserTokenView, TriggerSyncView, UserStatusView

urlpatterns = [
    path("users/status/", UserStatusView.as_view(), name="user-status"),
    path("users/token/", SetUserTokenView.as_view(), name="user-token"),
    path("users/sync/", TriggerSyncView.as_view(), name="user-sync"),
]
