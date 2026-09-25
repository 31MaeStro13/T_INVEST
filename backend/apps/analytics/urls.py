from django.urls import path
from .views import (
    AccountAnalyticsView,
    ConsolidatedAnalyticsView,
    AccountChartView,
    ConsolidatedChartView,
    AskAIAuditorView,
)

urlpatterns = [
    path("analytics/consolidated/", ConsolidatedAnalyticsView.as_view(), name="consolidated-analytics"),
    path("analytics/consolidated/chart/", ConsolidatedChartView.as_view(), name="consolidated-chart"),
    path("analytics/ask_ai/", AskAIAuditorView.as_view(), name="ask-ai"),
    path("analytics/<int:account_id>/", AccountAnalyticsView.as_view(), name="account-analytics"),
    path("analytics/<int:account_id>/chart/", AccountChartView.as_view(), name="account-chart"),
]

