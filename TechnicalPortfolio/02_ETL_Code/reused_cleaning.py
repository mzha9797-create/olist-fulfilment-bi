# MBI807 Olist cleaning and metric eligibility rules.
# Annotated Olist data quality and cleaning
# Editable export of all 50 non-empty notebook code cells.
# Run from the packaged folder; run audit_run.py for the packaged SQLite loading workflow.

# %% Step 1
# Load pandas and NumPy, then locate the packaged raw datasets. Set the project root
# from the script location or the notebook working directory.
from pathlib import Path
import os
import pandas as pd
import numpy as np

# Display tabular diagnostics in either a notebook or an ordinary Python run.
try:
    from IPython.display import display
except ImportError:
    def display(value):
        print(value)

# Legacy MySQL branches remain disabled. The submitted workflow loads SQLite through run_etl.py.
# Run audit_run.py to rebuild the packaged SQLite database.
LOAD_TO_MYSQL = False
_start = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
_candidates = [_start.parent / "04_Data_Examples", _start, *_start.parents]
PROJECT_ROOT = next((p for p in _candidates if (p / "03_Raw_Dataset").is_dir()), None)
if PROJECT_ROOT is None:
    raise FileNotFoundError("Run this code from within the TechnicalPortfolio package.")
DATA_DIR = PROJECT_ROOT / "03_Raw_Dataset"
print("Project root:", PROJECT_ROOT)
print("Olist data folder:", DATA_DIR)
print("Folder exists:", DATA_DIR.exists())

# %% Step 2
# Read the order, item and customer source tables. These source tables are kept
# unchanged; cleaning uses separate copies.
orders = pd.read_csv(DATA_DIR / "olist_orders_dataset.csv")
order_items = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv")
customers = pd.read_csv(DATA_DIR / "olist_customers_dataset.csv")

print("Orders shape:", orders.shape)
print("Order items shape:", order_items.shape)
print("Customers shape:", customers.shape)

# %% Step 3
# Inspect order column types, missing values and repeated order IDs before creating
# derived measures.
print("=== ORDERS INFO ===")
print(orders.info())

print("\n=== MISSING VALUES IN ORDERS ===")
print(orders.isna().sum())

print("\n=== DUPLICATED ROWS IN ORDERS ===")
print(orders.duplicated().sum())

# %% Step 4
# Count delivered orders with no actual delivery timestamp. Such records cannot support
# an observed delivery-duration KPI.
delivered_missing_date = orders[
    (orders["order_status"] == "delivered") &
    (orders["order_delivered_customer_date"].isna())
]

print("Delivered orders missing delivery date:")
print(delivered_missing_date.shape[0])

delivered_missing_date.head(10)

# %% Step 5
# Check the intended primary keys: order_id, customer_id, and the composite (order_id,
# order_item_id).
print("=== ORDERS KEY CHECK ===")
print("Rows:", len(orders))
print("Unique order_id:", orders["order_id"].nunique())
print("Duplicate order_id:", orders["order_id"].duplicated().sum())

print("\n=== CUSTOMERS KEY CHECK ===")
print("Rows:", len(customers))
print("Unique customer_id:", customers["customer_id"].nunique())
print("Duplicate customer_id:", customers["customer_id"].duplicated().sum())

print("\n=== ORDER ITEMS KEY CHECK ===")
print("Rows:", len(order_items))
print(
    "Duplicate order_id + order_item_id:",
    order_items.duplicated(subset=["order_id", "order_item_id"]).sum()
)

# %% Step 6
# Repeat the key checks retained from the original exploratory notebook. This cell does
# not change data.
print("=== ORDERS KEY CHECK ===")
print("Rows:", len(orders))
print("Unique order_id:", orders["order_id"].nunique())
print("Duplicate order_id:", orders["order_id"].duplicated().sum())

print("\n=== CUSTOMERS KEY CHECK ===")
print("Rows:", len(customers))
print("Unique customer_id:", customers["customer_id"].nunique())
print("Duplicate customer_id:", customers["customer_id"].duplicated().sum())

print("\n=== ORDER ITEMS KEY CHECK ===")
print("Rows:", len(order_items))
print(
    "Duplicate order_id + order_item_id:",
    order_items.duplicated(subset=["order_id", "order_item_id"]).sum()
)

# %% Step 7
# Check foreign keys from items to orders and from orders to customers before joining
# tables.
items_without_order = order_items[
    ~order_items["order_id"].isin(orders["order_id"])
]

orders_without_customer = orders[
    ~orders["customer_id"].isin(customers["customer_id"])
]

print("Order items without matching order:", len(items_without_order))
print("Orders without matching customer:", len(orders_without_customer))

# %% Step 8
# Parse the five order timestamps. Unparseable values become missing timestamps for
# later eligibility checks.
# Historical working CSVs had lost seconds before the original analysis.
# The restored raw CSVs retain full seconds. Explicitly floor to minutes here
# to reproduce the existing clean data and Power BI results. This is a
# compatibility choice, not a claim that source timestamps lack seconds.
date_columns = [
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date"
]

for col in date_columns:
    orders[col] = pd.to_datetime(orders[col], errors="coerce").dt.floor("min")

orders[date_columns].dtypes

# %% Step 9
# Create a working copy of orders so that all original order records remain available.
orders_clean = orders.copy()

# %% Step 10
# Calculate elapsed delivery days from purchase to customer receipt, retaining
# fractional days.
orders_clean["delivery_days"] = (
    orders_clean["order_delivered_customer_date"]
    - orders_clean["order_purchase_timestamp"]
).dt.total_seconds() / 86400

# %% Step 11
# Calculate delay in calendar days by normalizing actual and estimated receipt dates to
# midnight.
orders_clean["delay_days"] = (
    orders_clean["order_delivered_customer_date"].dt.normalize()
    - orders_clean["order_estimated_delivery_date"].dt.normalize()
).dt.days

# %% Step 12
# Set a nullable on-time flag for delivered orders with actual and estimated dates.
# Missing evidence remains unknown, not late.
eligible_delivery = (
    (orders_clean["order_status"] == "delivered")
    & orders_clean["order_delivered_customer_date"].notna()
    & orders_clean["order_estimated_delivery_date"].notna()
)

orders_clean["on_time_delivery"] = pd.Series(
    pd.NA,
    index=orders_clean.index,
    dtype="boolean"
)

orders_clean.loc[eligible_delivery, "on_time_delivery"] = (
    orders_clean.loc[eligible_delivery, "delay_days"] <= 0
)

# %% Step 13
# Inspect the preliminary on-time flags and delivery/delay distributions. Final KPI
# eligibility is defined later.
print("Total orders:", len(orders_clean))
print("Eligible delivered orders:", eligible_delivery.sum())
print("\nOn-time delivery:")
print(orders_clean["on_time_delivery"].value_counts(dropna=False))

print("\nDelivery days summary:")
print(orders_clean.loc[eligible_delivery, "delivery_days"].describe())

print("\nDelay days summary:")
print(orders_clean.loc[eligible_delivery, "delay_days"].describe())

# %% Step 14
# Explore the preliminary on-time rate and unusual delivery durations. This diagnostic
# is not the final dashboard denominator.
on_time_rate = (
    orders_clean.loc[eligible_delivery, "on_time_delivery"].mean() * 100
)

print(f"On-time delivery rate: {on_time_rate:.2f}%")

print("\nDelivered orders:", (orders_clean["order_status"] == "delivered").sum())
print("Eligible delivered orders:", eligible_delivery.sum())

print("\nNegative delivery days:")
print(
    (orders_clean.loc[eligible_delivery, "delivery_days"] < 0).sum()
)

print("\nVery long delivery > 90 days:")
print(
    (orders_clean.loc[eligible_delivery, "delivery_days"] > 90).sum()
)

print("\nVery late > 60 days:")
print(
    (orders_clean.loc[eligible_delivery, "delay_days"] > 60).sum()
)

print("\nVery early > 60 days:")
print(
    (orders_clean.loc[eligible_delivery, "delay_days"] < -60).sum()
)

# %% Step 15
# Show the shortest and longest delivery observations for manual review; no records are
# removed.
extreme_delays = orders_clean.loc[
    eligible_delivery,
    [
        "order_id",
        "order_purchase_timestamp",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
        "delivery_days",
        "delay_days"
    ]
].sort_values("delay_days")

display(extreme_delays.head(10))
display(extreme_delays.tail(10))

# %% Step 16
# Check the order of purchase, approval, carrier handoff, customer receipt and estimated
# delivery timestamps.
checks = {
    "approved_before_purchase": (
        orders_clean["order_approved_at"]
        < orders_clean["order_purchase_timestamp"]
    ),

    "carrier_before_purchase": (
        orders_clean["order_delivered_carrier_date"]
        < orders_clean["order_purchase_timestamp"]
    ),

    "delivered_before_purchase": (
        orders_clean["order_delivered_customer_date"]
        < orders_clean["order_purchase_timestamp"]
    ),

    "delivered_before_carrier": (
        orders_clean["order_delivered_customer_date"]
        < orders_clean["order_delivered_carrier_date"]
    ),

    "estimated_before_purchase": (
        orders_clean["order_estimated_delivery_date"]
        < orders_clean["order_purchase_timestamp"]
    )
}

print("=== TEMPORAL LOGIC CHECKS ===")

for name, condition in checks.items():
    print(f"{name}: {condition.sum()}")

# %% Step 17
# Flag extreme observations for review: delivery above 90 days, or delay outside -60 to
# +60 days. These flags do not automatically exclude records.
suspicious_orders = orders_clean.loc[
    (
        (orders_clean["delivery_days"] > 90)
        | (orders_clean["delay_days"] > 60)
        | (orders_clean["delay_days"] < -60)
    ),
    [
        "order_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
        "delivery_days",
        "delay_days"
    ]
]

print("Suspicious / extreme records:", len(suspicious_orders))

display(
    suspicious_orders
    .sort_values("delay_days")
    .head(10)
)

display(
    suspicious_orders
    .sort_values("delay_days")
    .tail(10)
)

# %% Step 18
# Measure overlap between temporal anomalies and extreme observations to avoid counting
# the same issue twice.
carrier_before_purchase = (
    orders_clean["order_delivered_carrier_date"]
    < orders_clean["order_purchase_timestamp"]
)

delivered_before_carrier = (
    orders_clean["order_delivered_customer_date"]
    < orders_clean["order_delivered_carrier_date"]
)

extreme_flag = (
    (orders_clean["delivery_days"] > 90)
    | (orders_clean["delay_days"] > 60)
    | (orders_clean["delay_days"] < -60)
)

print("Carrier before purchase:", carrier_before_purchase.sum())
print("Delivered before carrier:", delivered_before_carrier.sum())
print("Extreme records:", extreme_flag.sum())

print(
    "Carrier-before-purchase AND extreme:",
    (carrier_before_purchase & extreme_flag).sum()
)

print(
    "Delivered-before-carrier AND extreme:",
    (delivered_before_carrier & extreme_flag).sum()
)

print(
    "Both temporal anomalies:",
    (carrier_before_purchase & delivered_before_carrier).sum()
)

# %% Step 19
# Persist quality flags alongside each order. Preserve flagged records rather than
# silently dropping them.
orders_clean["flag_carrier_before_purchase"] = carrier_before_purchase
orders_clean["flag_delivered_before_carrier"] = delivered_before_carrier

orders_clean["flag_extreme_delivery"] = extreme_flag

orders_clean["flag_missing_delivery_date"] = (
    (orders_clean["order_status"] == "delivered")
    & orders_clean["order_delivered_customer_date"].isna()
)

orders_clean["flag_temporal_error"] = (
    orders_clean["flag_carrier_before_purchase"]
    | orders_clean["flag_delivered_before_carrier"]
)

print("Temporal error records:")
print(orders_clean["flag_temporal_error"].value_counts())

print("\nExtreme delivery records:")
print(orders_clean["flag_extreme_delivery"].value_counts())

print("\nDelivered but missing delivery date:")
print(orders_clean["flag_missing_delivery_date"].value_counts())

# %% Step 20
# Define separate eligibility masks for delivery duration, on-time delivery, processing
# and transit. Each KPI requires its own dates and a nonnegative interval.
# Eligibility rule for delivery duration
orders_clean["eligible_delivery_days"] = (
    (orders_clean["order_status"] == "delivered")
    & orders_clean["order_purchase_timestamp"].notna()
    & orders_clean["order_delivered_customer_date"].notna()
    & (
        orders_clean["order_delivered_customer_date"]
        >= orders_clean["order_purchase_timestamp"]
    )
)

# Eligibility rule for on-time delivery KPI
orders_clean["eligible_on_time"] = (
    orders_clean["eligible_delivery_days"]
    & orders_clean["order_estimated_delivery_date"].notna()
)

# Eligibility rule for purchase-to-carrier processing time
orders_clean["eligible_processing_time"] = (
    orders_clean["order_purchase_timestamp"].notna()
    & orders_clean["order_delivered_carrier_date"].notna()
    & (
        orders_clean["order_delivered_carrier_date"]
        >= orders_clean["order_purchase_timestamp"]
    )
)

# Eligibility rule for carrier-to-customer transit time
orders_clean["eligible_transit_time"] = (
    orders_clean["order_delivered_carrier_date"].notna()
    & orders_clean["order_delivered_customer_date"].notna()
    & (
        orders_clean["order_delivered_customer_date"]
        >= orders_clean["order_delivered_carrier_date"]
    )
)

print("Eligible delivery days:", orders_clean["eligible_delivery_days"].sum())
print("Eligible on-time KPI:", orders_clean["eligible_on_time"].sum())
print("Eligible processing time:", orders_clean["eligible_processing_time"].sum())
print("Eligible transit time:", orders_clean["eligible_transit_time"].sum())

# %% Step 21
# Calculate processing and transit durations only when their respective eligibility
# masks pass; otherwise store a missing value.
orders_clean["processing_days"] = np.where(
    orders_clean["eligible_processing_time"],
    (
        orders_clean["order_delivered_carrier_date"]
        - orders_clean["order_purchase_timestamp"]
    ).dt.total_seconds() / 86400,
    np.nan
)

orders_clean["transit_days"] = np.where(
    orders_clean["eligible_transit_time"],
    (
        orders_clean["order_delivered_customer_date"]
        - orders_clean["order_delivered_carrier_date"]
    ).dt.total_seconds() / 86400,
    np.nan
)

print("Processing time summary:")
print(orders_clean["processing_days"].describe())

print("\nTransit time summary:")
print(orders_clean["transit_days"].describe())

# %% Step 22
# Build a compact quality summary containing original volume, duplicate checks, anomaly
# counts and the final on-time denominator.
quality_summary = pd.DataFrame({
    "check": [
        "Total orders",
        "Duplicate order_id",
        "Delivered missing delivery date",
        "Carrier before purchase",
        "Delivered before carrier",
        "Temporal error records",
        "Extreme delivery records",
        "Eligible on-time orders"
    ],
    "count": [
        len(orders_clean),
        orders_clean["order_id"].duplicated().sum(),
        orders_clean["flag_missing_delivery_date"].sum(),
        orders_clean["flag_carrier_before_purchase"].sum(),
        orders_clean["flag_delivered_before_carrier"].sum(),
        orders_clean["flag_temporal_error"].sum(),
        orders_clean["flag_extreme_delivery"].sum(),
        orders_clean["eligible_on_time"].sum()
    ]
})

quality_summary

# %% Step 23
# Inspect item prices, freight values and customer completeness before exporting the
# clean tables.
print("=== ORDER ITEMS QUALITY CHECK ===")

print("Rows:", len(order_items))
print("Columns:", len(order_items.columns))
print("Duplicate full rows:", order_items.duplicated().sum())

print("\nMissing values:")
print(order_items.isna().sum())

print("\nComposite key duplicates:")
print(
    order_items.duplicated(
        subset=["order_id", "order_item_id"]
    ).sum()
)


print("\n=== CUSTOMERS QUALITY CHECK ===")

print("Rows:", len(customers))
print("Columns:", len(customers.columns))
print("Duplicate full rows:", customers.duplicated().sum())

print("\nMissing values:")
print(customers.isna().sum())

print("\nDuplicate customer_id:")
print(customers["customer_id"].duplicated().sum())

print("\nUnique customer_unique_id:")
print(customers["customer_unique_id"].nunique())

# %% Step 24
# Reload customer IDs and postal prefixes as strings to preserve the original
# characters, including leading zeroes.
customers_clean = pd.read_csv(
    DATA_DIR / "olist_customers_dataset.csv",
    dtype={
        "customer_id": "string",
        "customer_unique_id": "string",
        "customer_zip_code_prefix": "string",
        "customer_city": "string",
        "customer_state": "string"
    }
)

print(customers_clean.dtypes)
print()
print(customers_clean.head())

# %% Step 25
# Copy item rows and parse the shipping deadline without changing order-item grain,
# prices or freight values.
# Match the historical minute-level shipping deadline used by this report.
# Full source precision remains preserved in 03_Raw_Dataset.
order_items_clean = order_items.copy()

order_items_clean["shipping_limit_date"] = pd.to_datetime(
    order_items_clean["shipping_limit_date"],
    errors="coerce"
).dt.floor("min")

print(order_items_clean.dtypes)

print(
    "\nMissing shipping_limit_date:",
    order_items_clean["shipping_limit_date"].isna().sum()
)

print(
    "Duplicate composite key:",
    order_items_clean.duplicated(
        subset=["order_id", "order_item_id"]
    ).sum()
)

# %% Step 26
# Confirm the three main clean-table row counts before export.
print("=== FINAL CLEAN TABLE VALIDATION ===")

print("\nORDERS")
print("Rows:", len(orders_clean))
print("Unique order_id:", orders_clean["order_id"].nunique())

print("\nORDER ITEMS")
print("Rows:", len(order_items_clean))
print(
    "Unique composite keys:",
    order_items_clean[
        ["order_id", "order_item_id"]
    ].drop_duplicates().shape[0]
)

print("\nCUSTOMERS")
print("Rows:", len(customers_clean))
print("Unique customer_id:", customers_clean["customer_id"].nunique())
print(
    "Unique actual customers:",
    customers_clean["customer_unique_id"].nunique()
)

# %% Step 27
# Export the clean orders, items, customers and quality summary as CSV. The portable
# edition defaults to a separate reproduced-output folder.
CLEAN_DIR = Path(os.environ.get("MBI807_CLEAN_OUTPUT", str(PROJECT_ROOT / "clean")))
CLEAN_DIR.mkdir(parents=True, exist_ok=True)

orders_clean.to_csv(
    CLEAN_DIR / "orders_clean.csv",
    index=False
)

order_items_clean.to_csv(
    CLEAN_DIR / "order_items_clean.csv",
    index=False
)

customers_clean.to_csv(
    CLEAN_DIR / "customers_clean.csv",
    index=False
)

quality_summary.to_csv(
    CLEAN_DIR / "data_quality_summary.csv",
    index=False
)

print("Files exported to:")
print(CLEAN_DIR)

for file in sorted(CLEAN_DIR.glob("*.csv")):
    print(file.name)

# %% Step 28
# Optional MySQL connection: request a password interactively only when LOAD_TO_MYSQL is
# enabled. No credentials are embedded in this file.
if LOAD_TO_MYSQL:
    from getpass import getpass
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL

    mysql_password = getpass("Enter MySQL root password: ")

    connection_url = URL.create(
        "mysql+pymysql",
        username="root",
        password=mysql_password,
        host="localhost",
        port=3306,
        database="mbi807b_olist"
    )

    engine = create_engine(connection_url)

    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT DATABASE(), VERSION();")
        ).fetchone()

    print("Connected successfully.")
    print("Database:", result[0])
    print("MySQL version:", result[1])
else:
    print("MySQL step 28 skipped: LOAD_TO_MYSQL is False.")

# %% Step 29
# Convert delay days to a nullable integer for the SQL INT column. This changes
# representation, not the calendar-day calculation.
# Prepare nullable integer field for MySQL INT
orders_clean["delay_days"] = (
    orders_clean["delay_days"]
    .round()
    .astype("Int64")
)

print(orders_clean["delay_days"].dtype)
print(orders_clean.shape)
print(order_items_clean.shape)
print(customers_clean.shape)

# %% Step 30
# Optional database check: inspect existing row counts before loading. The original
# workflow requires coordinated SQL table creation and Python loading.
if LOAD_TO_MYSQL:
    from sqlalchemy import text

    with engine.connect() as connection:
        for table in ["customers", "orders", "order_items"]:
            count = connection.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

            print(f"{table}: {count}")
else:
    print("MySQL step 30 skipped: LOAD_TO_MYSQL is False.")

# %% Step 31
# Optional append load of customers, orders and items. Run only against the correctly
# prepared empty tables; repeating an append is not a refresh.
if LOAD_TO_MYSQL:
    print("Loading customers...")

    customers_clean.to_sql(
        "customers",
        con=engine,
        if_exists="append",
        index=False,
        chunksize=5000
    )

    print("Customers loaded.")

    print("Loading orders...")

    orders_clean.to_sql(
        "orders",
        con=engine,
        if_exists="append",
        index=False,
        chunksize=5000
    )

    print("Orders loaded.")

    print("Loading order_items...")

    order_items_clean.to_sql(
        "order_items",
        con=engine,
        if_exists="append",
        index=False,
        chunksize=5000
    )

    print("Order items loaded.")

    print("All tables loaded successfully.")
else:
    print("MySQL step 31 skipped: LOAD_TO_MYSQL is False.")

# %% Step 32
# Optional database check: confirm row counts after loading the three main tables.
if LOAD_TO_MYSQL:
    with engine.connect() as connection:
        customers_count = connection.execute(
            text("SELECT COUNT(*) FROM customers")
        ).scalar()

        orders_count = connection.execute(
            text("SELECT COUNT(*) FROM orders")
        ).scalar()

        items_count = connection.execute(
            text("SELECT COUNT(*) FROM order_items")
        ).scalar()

    print("MYSQL VALIDATION")
    print("Customers:", customers_count)
    print("Orders:", orders_count)
    print("Order items:", items_count)
else:
    print("MySQL step 32 skipped: LOAD_TO_MYSQL is False.")

# %% Step 33
# Read the seller dimension with seller IDs and postal prefixes as strings.
sellers = pd.read_csv(
    DATA_DIR / "olist_sellers_dataset.csv",
    dtype={
        "seller_id": "string",
        "seller_zip_code_prefix": "string",
        "seller_city": "string",
        "seller_state": "string"
    }
)

print("Sellers shape:", sellers.shape)
print("\nMissing values:")
print(sellers.isna().sum())

print("\nDuplicate seller_id:")
print(sellers["seller_id"].duplicated().sum())

print("\nUnique seller_id:")
print(sellers["seller_id"].nunique())

# %% Step 34
# Check that every item seller_id exists in the seller dimension.
items_without_seller = order_items_clean[
    ~order_items_clean["seller_id"].isin(sellers["seller_id"])
]

print("Order items without matching seller:", len(items_without_seller))

# %% Step 35
# Create and export the seller clean table without removing source sellers.
sellers_clean = sellers.copy()

sellers_clean.to_csv(
    CLEAN_DIR / "sellers_clean.csv",
    index=False
)

print("Sellers rows:", len(sellers_clean))
print("Unique seller_id:", sellers_clean["seller_id"].nunique())
print("Exported:", CLEAN_DIR / "sellers_clean.csv")

# %% Step 36
# Optional append load of sellers. Create the seller table first and add its item
# foreign key only after the dimension is populated.
if LOAD_TO_MYSQL:
    sellers_clean.to_sql(
        "sellers",
        con=engine,
        if_exists="append",
        index=False,
        chunksize=5000
    )

    print("Sellers loaded.")
else:
    print("MySQL step 36 skipped: LOAD_TO_MYSQL is False.")

# %% Step 37
# Optional database check: verify the number of loaded sellers.
if LOAD_TO_MYSQL:
    with engine.connect() as connection:
        sellers_count = connection.execute(
            text("SELECT COUNT(*) FROM sellers")
        ).scalar()

    print("MySQL sellers:", sellers_count)
else:
    print("MySQL step 37 skipped: LOAD_TO_MYSQL is False.")

# %% Step 38
# Read products and the category translation lookup, then inspect keys and missing
# values.
products = pd.read_csv(
    DATA_DIR / "olist_products_dataset.csv",
    dtype={
        "product_id": "string",
        "product_category_name": "string"
    }
)

category_translation = pd.read_csv(
    DATA_DIR / "product_category_name_translation.csv",
    dtype={
        "product_category_name": "string",
        "product_category_name_english": "string"
    }
)

print("=== PRODUCTS ===")
print("Shape:", products.shape)

print("\nMissing values:")
print(products.isna().sum())

print("\nDuplicate product_id:")
print(products["product_id"].duplicated().sum())

print("\nUnique product_id:")
print(products["product_id"].nunique())


print("\n=== CATEGORY TRANSLATION ===")
print("Shape:", category_translation.shape)

print("\nMissing values:")
print(category_translation.isna().sum())

print("\nDuplicate Portuguese category:")
print(
    category_translation["product_category_name"]
    .duplicated()
    .sum()
)

# %% Step 39
# Left-join translations to products so that products with missing translations remain
# in the dataset.
products_with_category = products.merge(
    category_translation,
    on="product_category_name",
    how="left"
)

unmatched_categories = products_with_category[
    products_with_category["product_category_name"].notna()
    & products_with_category["product_category_name_english"].isna()
]

print(
    "Products with Portuguese category but no English translation:",
    len(unmatched_categories)
)

print(
    "Products with missing category:",
    products["product_category_name"].isna().sum()
)

# %% Step 40
# Identify untranslated non-missing Portuguese category labels for explicit fallback
# handling.
print("Unmatched Portuguese categories:")

print(
    unmatched_categories["product_category_name"]
    .value_counts()
)

print(
    "\nUnique unmatched categories:",
    unmatched_categories["product_category_name"].nunique()
)

# %% Step 41
# Create category_display using English, then Portuguese, then unknown. Flag missing
# category and physical dimensions without inventing measurements.
products_clean = products_with_category.copy()

products_clean["category_display"] = (
    products_clean["product_category_name_english"]
    .fillna(products_clean["product_category_name"])
    .fillna("unknown")
)

products_clean["flag_missing_category"] = (
    products_clean["product_category_name"].isna()
)

products_clean["flag_missing_dimensions"] = (
    products_clean[
        [
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm"
        ]
    ]
    .isna()
    .any(axis=1)
)

print("Products:", len(products_clean))

print(
    "Missing original category:",
    products_clean["flag_missing_category"].sum()
)

print(
    "Missing dimensions:",
    products_clean["flag_missing_dimensions"].sum()
)

print(
    "Missing final category display:",
    products_clean["category_display"].isna().sum()
)

# %% Step 42
# Check that every item product_id exists in the product dimension.
items_without_product = order_items_clean[
    ~order_items_clean["product_id"].isin(
        products_clean["product_id"]
    )
]

print(
    "Order items without matching product:",
    len(items_without_product)
)

# %% Step 43
# Correct the source spelling of the name-length and description-length column names to
# match the SQL schema.
products_clean = products_clean.rename(
    columns={
        "product_name_lenght": "product_name_length",
        "product_description_lenght": "product_description_length"
    }
)

# %% Step 44
# Arrange product columns in the documented SQL loading order; preserve the quality
# flags.
products_clean = products_clean[
    [
        "product_id",
        "product_category_name",
        "product_category_name_english",
        "category_display",
        "product_name_length",
        "product_description_length",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
        "flag_missing_category",
        "flag_missing_dimensions"
    ]
]

# %% Step 45
# Write an intermediate product export retained from the original notebook; the final
# typed export below supersedes it.
products_clean.to_csv(
    CLEAN_DIR / "products_clean.csv",
    index=False
)

print("Products exported:", len(products_clean))
print(CLEAN_DIR / "products_clean.csv")

# %% Step 46
# Convert product lengths, dimensions, photo counts and weight to nullable integers for
# their SQL column types.
numeric_product_columns = [
    "product_name_length",
    "product_description_length",
    "product_photos_qty",
    "product_weight_g",
    "product_length_cm",
    "product_height_cm",
    "product_width_cm"
]

for col in numeric_product_columns:
    products_clean[col] = (
        products_clean[col]
        .round()
        .astype("Int64")
    )

print(products_clean.dtypes)

# %% Step 47
# Write the final product CSV after integer conversion. Null physical measurements
# remain null.
products_clean.to_csv(
    CLEAN_DIR / "products_clean.csv",
    index=False
)

print("Products re-exported:", len(products_clean))

# %% Step 48
# Optional database check: inspect existing product rows before an append load.
if LOAD_TO_MYSQL:
    with engine.connect() as connection:
        products_count = connection.execute(
            text("SELECT COUNT(*) FROM products")
        ).scalar()

    print("Products currently in MySQL:", products_count)
else:
    print("MySQL step 48 skipped: LOAD_TO_MYSQL is False.")

# %% Step 49
# Optional append load of products. Populate this dimension before adding the product
# foreign key to existing item rows.
if LOAD_TO_MYSQL:
    products_clean.to_sql(
        "products",
        con=engine,
        if_exists="append",
        index=False,
        chunksize=5000
    )

    print("Products loaded.")
else:
    print("MySQL step 49 skipped: LOAD_TO_MYSQL is False.")

# %% Step 50
# Optional database check: verify the number of loaded products.
if LOAD_TO_MYSQL:
    with engine.connect() as connection:
        products_count = connection.execute(
            text("SELECT COUNT(*) FROM products")
        ).scalar()

    print("MySQL products:", products_count)
else:
    print("MySQL step 50 skipped: LOAD_TO_MYSQL is False.")
