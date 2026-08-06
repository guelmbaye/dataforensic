#!/usr/bin/env python3
"""Build the deterministic DataHub context graph used by the fixture provider.

The same graph can be emitted into a real DataHub instance with
`datahub/seed/emit_demo_graph.py`, so URNs are identical in fixture mode and in
live mode. Run:

    python datahub/seed/build_graph.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "showcase-ecommerce-demo.json"

DAY = "2026-03-11"


def ts(hhmm: str) -> str:
    return f"{DAY}T{hhmm}:00Z"


# --- owners -----------------------------------------------------------------
ERP_TEAM = {
    "urn": "urn:li:corpGroup:erp-platform",
    "name": "ERP Platform",
    "type": "DATAOWNER",
    "email": "erp-platform@example.com",
}
DATA_PLATFORM = {
    "urn": "urn:li:corpGroup:data-platform",
    "name": "Data Platform",
    "type": "TECHNICAL_OWNER",
    "email": "data-platform@example.com",
}
ANALYTICS_ENG = {
    "urn": "urn:li:corpGroup:analytics-engineering",
    "name": "Analytics Engineering",
    "type": "DATAOWNER",
    "email": "analytics-eng@example.com",
}
ML_PLATFORM = {
    "urn": "urn:li:corpGroup:ml-platform",
    "name": "ML Platform",
    "type": "DATAOWNER",
    "email": "ml-platform@example.com",
}
TAXI_OPS = {
    "urn": "urn:li:corpGroup:mobility-data",
    "name": "Mobility Data",
    "type": "DATAOWNER",
    "email": "mobility-data@example.com",
}
FINANCE_TEAM = {
    "urn": "urn:li:corpGroup:finance-systems",
    "name": "Finance Systems",
    "type": "BUSINESS_OWNER",
    "email": "finance-systems@example.com",
}
CLINICAL_DATA = {
    "urn": "urn:li:corpGroup:clinical-data",
    "name": "Clinical Data",
    "type": "DATAOWNER",
    "email": "clinical-data@example.com",
}

# --- URNs -------------------------------------------------------------------
ERP_ORDERS = "urn:li:dataset:(urn:li:dataPlatform:postgres,erp.public.orders,PROD)"
RAW_ORDERS_S3 = "urn:li:dataset:(urn:li:dataPlatform:s3,ecommerce/raw/orders,PROD)"
ORDERS_RAW = "urn:li:dataset:(urn:li:dataPlatform:snowflake,ECOMMERCE.RAW.ORDERS_RAW,PROD)"
ORDERS_ENRICHED = (
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,ECOMMERCE.ANALYTICS.ORDERS_ENRICHED,PROD)"
)
SALES_DAILY = "urn:li:dataset:(urn:li:dataPlatform:snowflake,ECOMMERCE.ANALYTICS.SALES_DAILY,PROD)"
REVENUE_BY_REGION = (
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,ECOMMERCE.ANALYTICS.REVENUE_BY_REGION,PROD)"
)
FINANCE_CLOSE = (
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,ECOMMERCE.FINANCE.MONTHLY_CLOSE,PROD)"
)
CUSTOMER_FEATURES = (
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,ECOMMERCE.ML.CUSTOMER_FEATURES,PROD)"
)
DASH_REVENUE = "urn:li:dashboard:(looker,revenue_overview)"
DASH_EXEC = "urn:li:dashboard:(powerbi,executive_kpi)"
DASH_REGIONAL = "urn:li:dashboard:(tableau,regional_sales)"
ML_CHURN = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_propensity,PROD)"
ML_DEMAND = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,demand_forecast,PROD)"

JOB_INGEST = "urn:li:dataJob:(urn:li:dataFlow:(spark,erp_ingestion,PROD),extract_orders)"
JOB_LOAD = "urn:li:dataJob:(urn:li:dataFlow:(spark,erp_ingestion,PROD),load_orders_raw)"
JOB_ENRICH = "urn:li:dataJob:(urn:li:dataFlow:(dbt,ecommerce_analytics,PROD),orders_enriched)"
JOB_SALES = "urn:li:dataJob:(urn:li:dataFlow:(dbt,ecommerce_analytics,PROD),sales_daily)"
JOB_REGION = "urn:li:dataJob:(urn:li:dataFlow:(dbt,ecommerce_analytics,PROD),revenue_by_region)"
JOB_FEATURES = "urn:li:dataJob:(urn:li:dataFlow:(spark,ml_features,PROD),customer_features)"

# nyc-taxi
TAXI_RAW = "urn:li:dataset:(urn:li:dataPlatform:s3,nyc-taxi/raw/trips,PROD)"
TAXI_CLEAN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,NYC_TAXI.STAGING.TRIPS_CLEAN,PROD)"
TAXI_DAILY = "urn:li:dataset:(urn:li:dataPlatform:snowflake,NYC_TAXI.ANALYTICS.TRIPS_DAILY,PROD)"
TAXI_DASH = "urn:li:dashboard:(looker,taxi_operations)"
JOB_TAXI_INGEST = "urn:li:dataJob:(urn:li:dataFlow:(spark,nyc_taxi,PROD),ingest_trips)"
JOB_TAXI_CLEAN = "urn:li:dataJob:(urn:li:dataFlow:(spark,nyc_taxi,PROD),clean_trips)"
JOB_TAXI_DAILY = "urn:li:dataJob:(urn:li:dataFlow:(dbt,nyc_taxi,PROD),trips_daily)"

# healthcare
ADMISSIONS = "urn:li:dataset:(urn:li:dataPlatform:postgres,healthcare.public.patient_admissions,PROD)"
PATIENT_360 = "urn:li:dataset:(urn:li:dataPlatform:snowflake,HEALTHCARE.ANALYTICS.PATIENT_360,PROD)"
CARE_DASH = "urn:li:dashboard:(tableau,care_operations)"
JOB_PATIENT = "urn:li:dataJob:(urn:li:dataFlow:(dbt,healthcare,PROD),patient_360)"


def dataset(
    urn: str,
    name: str,
    platform: str,
    description: str,
    owners: list[dict],
    fields: list[tuple[str, str, bool, str]],
    domain: str,
    tags: list[str],
    terms: list[str] | None = None,
    criticality: str = "MEDIUM",
) -> dict:
    return {
        "urn": urn,
        "type": "DATASET",
        "name": name,
        "platform": platform,
        "env": "PROD",
        "description": description,
        "domain": domain,
        "tags": tags,
        "glossary_terms": terms or [],
        "owners": owners,
        "criticality": criticality,
        "schema": {
            "version": 1,
            "fields": [
                {"path": p, "type": t, "nullable": n, "description": d}
                for p, t, n, d in fields
            ],
        },
    }


def consumer(
    urn: str, entity_type: str, name: str, platform: str, owners: list[dict], domain: str,
    tags: list[str], criticality: str = "MEDIUM", description: str = ""
) -> dict:
    return {
        "urn": urn,
        "type": entity_type,
        "name": name,
        "platform": platform,
        "env": "PROD",
        "description": description,
        "domain": domain,
        "tags": tags,
        "glossary_terms": [],
        "owners": owners,
        "criticality": criticality,
    }


ENTITIES: list[dict] = [
    # ---------------- ecommerce chain ----------------
    dataset(
        ERP_ORDERS,
        "erp.public.orders",
        "postgres",
        "Operational order table replicated from the ERP system.",
        [ERP_TEAM],
        [
            ("order_id", "varchar", False, "Order identifier"),
            ("customer_id", "varchar", False, "Customer identifier"),
            ("order_ts", "timestamp", False, "Order creation timestamp"),
            ("gross_amount", "numeric", False, "Gross order amount"),
            ("discount_value", "numeric", True, "Discount applied (renamed from discount_amount)"),
            ("currency", "varchar", False, "ISO currency code"),
            ("status", "varchar", False, "Order status"),
        ],
        "Finance",
        ["Tier1", "Source"],
        ["Revenue"],
        "HIGH",
    ),
    dataset(
        RAW_ORDERS_S3,
        "ecommerce/raw/orders",
        "s3",
        "Raw landing zone for ERP order extracts.",
        [DATA_PLATFORM],
        [
            ("payload", "string", False, "Raw JSON payload"),
            ("ingested_at", "timestamp", False, "Ingestion timestamp"),
        ],
        "Finance",
        ["Raw"],
    ),
    dataset(
        ORDERS_RAW,
        "ECOMMERCE.RAW.ORDERS_RAW",
        "snowflake",
        "Raw order records loaded into the warehouse.",
        [DATA_PLATFORM],
        [
            ("order_id", "varchar", False, "Order identifier"),
            ("customer_id", "varchar", False, "Customer identifier"),
            ("order_ts", "timestamp", False, "Order creation timestamp"),
            ("gross_amount", "number", False, "Gross order amount"),
            ("discount_value", "number", True, "Discount value from source"),
            ("currency", "varchar", False, "ISO currency code"),
        ],
        "Finance",
        ["Raw"],
    ),
    dataset(
        ORDERS_ENRICHED,
        "ECOMMERCE.ANALYTICS.ORDERS_ENRICHED",
        "snowflake",
        "Enriched orders with net amounts, used by every revenue model.",
        [DATA_PLATFORM, ANALYTICS_ENG],
        [
            ("order_id", "varchar", False, "Order identifier"),
            ("customer_id", "varchar", False, "Customer identifier"),
            ("order_ts", "timestamp", False, "Order creation timestamp"),
            ("gross_amount", "number", False, "Gross order amount"),
            ("discount_amount", "number", True, "Discount mapped from the source system"),
            ("net_amount", "number", True, "gross_amount - discount_amount"),
            ("region", "varchar", True, "Customer region"),
        ],
        "Finance",
        ["Tier1", "Certified"],
        ["Revenue", "Net Revenue"],
        "HIGH",
    ),
    dataset(
        SALES_DAILY,
        "ECOMMERCE.ANALYTICS.SALES_DAILY",
        "snowflake",
        "Daily sales aggregate powering the revenue metric.",
        [ANALYTICS_ENG],
        [
            ("sales_date", "date", False, "Aggregation date"),
            ("orders_count", "number", False, "Number of orders"),
            ("gross_revenue", "number", False, "Gross revenue"),
            ("net_revenue", "number", False, "Net revenue after discounts"),
            ("region", "varchar", True, "Region"),
        ],
        "Finance",
        ["Tier1", "Certified", "Finance"],
        ["Revenue"],
        "CRITICAL",
    ),
    dataset(
        REVENUE_BY_REGION,
        "ECOMMERCE.ANALYTICS.REVENUE_BY_REGION",
        "snowflake",
        "Revenue split by region.",
        [ANALYTICS_ENG],
        [
            ("region", "varchar", False, "Region"),
            ("sales_date", "date", False, "Date"),
            ("net_revenue", "number", False, "Net revenue"),
        ],
        "Finance",
        ["Certified"],
        ["Revenue"],
        "HIGH",
    ),
    dataset(
        FINANCE_CLOSE,
        "ECOMMERCE.FINANCE.MONTHLY_CLOSE",
        "snowflake",
        "Monthly financial close input.",
        [FINANCE_TEAM],
        [
            ("period", "varchar", False, "Accounting period"),
            ("net_revenue", "number", False, "Net revenue"),
            ("discounts", "number", True, "Total discounts"),
        ],
        "Finance",
        ["Tier1", "SOX", "Finance"],
        ["Revenue"],
        "CRITICAL",
    ),
    dataset(
        CUSTOMER_FEATURES,
        "ECOMMERCE.ML.CUSTOMER_FEATURES",
        "snowflake",
        "Customer level feature table used by ML models.",
        [ML_PLATFORM],
        [
            ("customer_id", "varchar", False, "Customer identifier"),
            ("lifetime_net_value", "number", True, "Lifetime net value"),
            ("avg_discount_rate", "number", True, "Average discount rate"),
            ("orders_90d", "number", True, "Orders in the last 90 days"),
        ],
        "Machine Learning",
        ["Feature"],
        ["Net Revenue"],
        "HIGH",
    ),
    consumer(DASH_REVENUE, "DASHBOARD", "Revenue Overview", "looker", [ANALYTICS_ENG], "Finance", ["Tier1", "Executive"], "HIGH", "Daily revenue dashboard."),
    consumer(DASH_EXEC, "DASHBOARD", "Executive KPI", "powerbi", [ANALYTICS_ENG], "Finance", ["Tier1", "Executive"], "CRITICAL", "Executive KPI board."),
    consumer(DASH_REGIONAL, "DASHBOARD", "Regional Sales", "tableau", [ANALYTICS_ENG], "Sales", ["Certified"], "MEDIUM", "Regional sales dashboard."),
    consumer(ML_CHURN, "MLMODEL", "churn_propensity", "mlflow", [ML_PLATFORM], "Machine Learning", ["Tier1"], "HIGH", "Churn propensity model."),
    consumer(ML_DEMAND, "MLMODEL", "demand_forecast", "mlflow", [ML_PLATFORM], "Machine Learning", ["Certified"], "HIGH", "Demand forecasting model."),
    # ---------------- nyc-taxi chain ----------------
    dataset(
        TAXI_RAW,
        "nyc-taxi/raw/trips",
        "s3",
        "Raw taxi trip files.",
        [TAXI_OPS],
        [("trip_id", "string", False, "Trip id"), ("pickup_ts", "timestamp", False, "Pickup")],
        "Mobility",
        ["Raw"],
    ),
    dataset(
        TAXI_CLEAN,
        "NYC_TAXI.STAGING.TRIPS_CLEAN",
        "snowflake",
        "Cleaned taxi trips.",
        [TAXI_OPS],
        [
            ("trip_id", "varchar", False, "Trip id"),
            ("pickup_ts", "timestamp", False, "Pickup"),
            ("fare_amount", "number", True, "Fare"),
        ],
        "Mobility",
        ["Staging"],
    ),
    dataset(
        TAXI_DAILY,
        "NYC_TAXI.ANALYTICS.TRIPS_DAILY",
        "snowflake",
        "Daily taxi trip aggregate.",
        [TAXI_OPS],
        [
            ("trip_date", "date", False, "Date"),
            ("trips", "number", False, "Trip count"),
            ("revenue", "number", True, "Fare revenue"),
        ],
        "Mobility",
        ["Tier1", "Certified"],
        [],
        "HIGH",
    ),
    consumer(TAXI_DASH, "DASHBOARD", "Taxi Operations", "looker", [TAXI_OPS], "Mobility", ["Tier1"], "HIGH", "Operations dashboard."),
    # ---------------- healthcare chain ----------------
    dataset(
        ADMISSIONS,
        "healthcare.public.patient_admissions",
        "postgres",
        "Patient admission records from the hospital information system.",
        [CLINICAL_DATA],
        [
            ("admission_id", "varchar", False, "Admission id"),
            ("patient_id", "varchar", False, "Patient id"),
            ("admitted_at", "timestamp", False, "Admission timestamp"),
            ("diagnosis_code", "varchar", True, "ICD-10 diagnosis code"),
            ("discharge_at", "timestamp", True, "Discharge timestamp"),
        ],
        "Healthcare",
        ["Tier1", "PII", "Source"],
        [],
        "HIGH",
    ),
    dataset(
        PATIENT_360,
        "HEALTHCARE.ANALYTICS.PATIENT_360",
        "snowflake",
        "Consolidated patient view used by clinical operations.",
        [CLINICAL_DATA],
        [
            ("patient_id", "varchar", False, "Patient id"),
            ("last_admission_at", "timestamp", True, "Last admission"),
            ("primary_diagnosis", "varchar", True, "Primary diagnosis"),
            ("readmission_risk", "number", True, "Readmission risk score"),
        ],
        "Healthcare",
        ["Tier1", "PII", "Certified"],
        [],
        "CRITICAL",
    ),
    consumer(CARE_DASH, "DASHBOARD", "Care Operations", "tableau", [CLINICAL_DATA], "Healthcare", ["Tier1", "PII"], "HIGH", "Clinical operations dashboard."),
]


def edge(up: str, down: str, via: str | None = None, kind: str = "TRANSFORMED") -> dict:
    return {"upstream": up, "downstream": down, "via": via, "type": kind}


LINEAGE = [
    edge(ERP_ORDERS, RAW_ORDERS_S3, JOB_INGEST, "COPY"),
    edge(RAW_ORDERS_S3, ORDERS_RAW, JOB_LOAD, "COPY"),
    edge(ORDERS_RAW, ORDERS_ENRICHED, JOB_ENRICH),
    edge(ORDERS_ENRICHED, SALES_DAILY, JOB_SALES),
    edge(ORDERS_ENRICHED, CUSTOMER_FEATURES, JOB_FEATURES),
    edge(SALES_DAILY, REVENUE_BY_REGION, JOB_REGION),
    edge(SALES_DAILY, FINANCE_CLOSE, JOB_REGION),
    edge(SALES_DAILY, DASH_REVENUE, None, "CONSUMED"),
    edge(SALES_DAILY, DASH_EXEC, None, "CONSUMED"),
    edge(SALES_DAILY, DASH_REGIONAL, None, "CONSUMED"),
    edge(CUSTOMER_FEATURES, ML_CHURN, None, "CONSUMED"),
    edge(CUSTOMER_FEATURES, ML_DEMAND, None, "CONSUMED"),
    # nyc-taxi
    edge(TAXI_RAW, TAXI_CLEAN, JOB_TAXI_CLEAN),
    edge(TAXI_CLEAN, TAXI_DAILY, JOB_TAXI_DAILY),
    edge(TAXI_DAILY, TAXI_DASH, None, "CONSUMED"),
    # healthcare
    edge(ADMISSIONS, PATIENT_360, JOB_PATIENT),
    edge(PATIENT_360, CARE_DASH, None, "CONSUMED"),
]

CHANGES = [
    {
        "timestamp": ts("10:02"),
        "entity_urn": ERP_ORDERS,
        "type": "SCHEMA_CHANGE",
        "operation": "MODIFY",
        "summary": "field renamed: discount_amount -> discount_value",
        "details": {
            "field": "discount_amount",
            "from_field": "discount_amount",
            "to_field": "discount_value",
            "semantic_version": "2.0.0",
            "backward_incompatible": True,
        },
    },
    {
        "timestamp": ts("09:40"),
        "entity_urn": ORDERS_ENRICHED,
        "type": "DOCUMENTATION",
        "operation": "MODIFY",
        "summary": "documentation updated by analytics-engineering",
        "details": {},
    },
]

ASSERTIONS = [
    {
        "asset_urn": SALES_DAILY,
        "name": "sales_daily_freshness",
        "type": "FRESHNESS",
        "status": "PASS",
        "observed_at": ts("10:15"),
        "detail": "Refreshed within the 60 minute SLA",
    },
    {
        "asset_urn": SALES_DAILY,
        "name": "sales_daily_row_count",
        "type": "VOLUME",
        "status": "PASS",
        "observed_at": ts("10:15"),
        "detail": "Row count within the expected range",
    },
    {
        "asset_urn": ORDERS_ENRICHED,
        "name": "orders_enriched_freshness",
        "type": "FRESHNESS",
        "status": "PASS",
        "observed_at": ts("10:12"),
        "detail": "Refreshed within the 60 minute SLA",
    },
]

GRAPH = {
    "name": "showcase-ecommerce-demo",
    "description": (
        "Deterministic DataHub context graph used by DATAFORENSIC AI when no live "
        "DataHub is reachable. Mirrors the structure of the official "
        "showcase-ecommerce, nyc-taxi and healthcare datapacks."
    ),
    "generated_for": "DATAFORENSIC AI",
    "platforms": [
        "postgres", "s3", "snowflake", "dbt", "spark", "looker", "powerbi", "tableau", "mlflow",
    ],
    "entities": ENTITIES,
    "lineage": LINEAGE,
    "changes": CHANGES,
    "assertions": ASSERTIONS,
}


def main() -> None:
    OUT.write_text(json.dumps(GRAPH, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(ENTITIES)} entities, {len(LINEAGE)} lineage edges)")


if __name__ == "__main__":
    main()
