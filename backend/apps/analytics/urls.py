from django.urls import path
from .views import (
    AccountAnalyticsView,
    ConsolidatedAnalyticsView,
    AccountChartView,
    ConsolidatedChartView,
)

urlpatterns = [
    path("analytics/consolidated/", ConsolidatedAnalyticsView.as_view(), name="consolidated-analytics"),
    path("analytics/consolidated/chart/", ConsolidatedChartView.as_view(), name="consolidated-chart"),
    path("analytics/<int:account_id>/", AccountAnalyticsView.as_view(), name="account-analytics"),
    path("analytics/<int:account_id>/chart/", AccountChartView.as_view(), name="account-chart"),
]
