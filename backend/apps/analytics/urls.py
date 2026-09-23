from django.urls import path
from .views import AccountAnalyticsView, ConsolidatedAnalyticsView

urlpatterns = [
    path("analytics/consolidated/", ConsolidatedAnalyticsView.as_view(), name="consolidated-analytics"),
    path("analytics/<int:account_id>/", AccountAnalyticsView.as_view(), name="account-analytics"),
]
