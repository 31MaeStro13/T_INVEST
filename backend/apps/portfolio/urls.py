from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AccountViewSet, DBStatsView, UploadReportView

router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="account")

urlpatterns = router.urls + [
    path("portfolio/upload_report/", UploadReportView.as_view(), name="portfolio-upload-report"),
    path("portfolio/db_stats/", DBStatsView.as_view(), name="portfolio-db-stats"),
]
