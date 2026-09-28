from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AccountViewSet, UploadReportView

router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="account")

urlpatterns = router.urls + [
    path("portfolio/upload_report/", UploadReportView.as_view(), name="portfolio-upload-report"),
]

