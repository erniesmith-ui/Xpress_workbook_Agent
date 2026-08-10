"""Authoritative constants for the fixed Xpress workbook and upload portal."""

SPREADSHEET_ID = "1FnviDn1Bq3aAn--nS4BUAeenzfKob2hXbjWOT5eNUA8"
HEADER_ROW = 6
DATA_START_ROW = 7
PRIMARY_TABLE_CAPACITY = 100
PARSER_VERSION = "2026.08.08.156"

LOCATIONS = ("Grandlake", "Eufaula", "OKC", "Central Crossing", "Toons Table Rock")

MANAGED_SHEETS = (
    "Dashboard",
    "Builder Import",
    "Ready to Order",
    "On Order",
    "Master Tracker",
    "Post-Order Change Log",
    "Lists",
    "Model Catalog",
    "Option Catalog",
    "Google Sheets Guide",
    "Official Model Check",
    "Builder Verification",
    "Upload Debug",
    *LOCATIONS,
)

ACTIVE_STAGES = ("Builder Import", "Ready to Order", "On Order")
ORDER_STATUSES = {
    "On Order",
    "Submitted to Xpress",
    "Confirmed",
    "Scheduled",
    "In Production",
    "Built",
    "Shipped",
    "Received",
    "Cancelled",
}
READY_STATUSES = {"Ready to Order", "Hold"}
REQUIRED_BUILDER_FIELDS = (
    "Location",
    "Build Status",
    "Sales Status",
    "Boat Page",
    "Model / Length",
    "Engine",
    "Trailer",
    "Build MSRP",
)
PORTAL_PAYLOAD_FIELDS = {
    "location",
    "manager",
    "salesStatus",
    "batchCustomerName",
    "batchExpectedCount",
    "batchDateNeeded",
    "batchFileData",
    "batchFileName",
    "batchMimeType",
    "batchDetectedText",
    "verifiedPreviewKeys",
    "builds",
}
MSRP_REVIEW_TOLERANCE = 50.0
EXACT_RECONCILIATION_TOLERANCE = 1.0

