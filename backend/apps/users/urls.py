from django.urls import path

from .views import (
    ActivateTokenView,
    SetUserTokenView,
    SetUserTypeView,
    ToggleAlertsView,
    TokensListView,
    TriggerSyncView,
    UserStatusView,
)

urlpatterns = [
    path("users/status/", UserStatusView.as_view(), name="user-status"),
    path("users/set_type/", SetUserTypeView.as_view(), name="user-set-type"),
    path("users/token/", SetUserTokenView.as_view(), name="user-token"),
    path("users/sync/", TriggerSyncView.as_view(), name="user-sync"),
    path("users/toggle_alerts/", ToggleAlertsView.as_view(), name="user-toggle-alerts"),
    path("tokens/", TokensListView.as_view(), name="tokens-list"),
    path("tokens/<int:token_id>/activate/", ActivateTokenView.as_view(), name="token-activate"),
]
