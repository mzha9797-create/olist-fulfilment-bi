-- Analytical views consumed by run_etl.py

CREATE VIEW vw_seller_performance AS WITH seller_orders AS (
    SELECT DISTINCT
        seller_id,
        order_id
    FROM order_items
),

operational AS (
    SELECT
        so.seller_id,

        COUNT(*) AS associated_orders,

        SUM(o.eligible_on_time) AS eligible_orders,

        SUM(
            CASE
                WHEN o.eligible_on_time = 1
                 AND o.on_time_delivery = 0
                THEN 1
                ELSE 0
            END
        ) AS late_orders,

        ROUND(
            AVG(
                CASE
                    WHEN o.eligible_on_time = 1
                    THEN o.on_time_delivery
                END
            ) * 100,
            2
        ) AS on_time_rate_pct,

        ROUND(
            AVG(
                CASE
                    WHEN o.eligible_delivery_days = 1
                    THEN o.delivery_days
                END
            ),
            2
        ) AS avg_delivery_days,

        ROUND(
            AVG(
                CASE
                    WHEN o.eligible_processing_time = 1
                    THEN o.processing_days
                END
            ),
            2
        ) AS avg_processing_days,

        ROUND(
            AVG(
                CASE
                    WHEN o.eligible_transit_time = 1
                    THEN o.transit_days
                END
            ),
            2
        ) AS avg_transit_days

    FROM seller_orders so

    JOIN orders o
        ON so.order_id = o.order_id

    GROUP BY so.seller_id
),

commercial AS (
    SELECT
        seller_id,

        COUNT(*) AS item_lines,

        COUNT(DISTINCT order_id) AS item_associated_orders,

        ROUND(SUM(price), 2) AS item_value,

        ROUND(SUM(freight_value), 2) AS freight_value,

        ROUND(
            SUM(freight_value)
            / NULLIF(SUM(price), 0) * 100,
            2
        ) AS freight_to_item_value_pct

    FROM order_items

    GROUP BY seller_id
)

SELECT
    s.seller_id,
    s.seller_city,
    s.seller_state,

    o.associated_orders,
    o.eligible_orders,
    o.late_orders,
    o.on_time_rate_pct,
    o.avg_delivery_days,
    o.avg_processing_days,
    o.avg_transit_days,

    c.item_lines,
    c.item_value,
    c.freight_value,
    c.freight_to_item_value_pct

FROM sellers s

LEFT JOIN operational o
    ON s.seller_id = o.seller_id

LEFT JOIN commercial c
    ON s.seller_id = c.seller_id;

CREATE VIEW vw_category_performance AS WITH category_orders AS (
    SELECT DISTINCT
        p.category_display,
        oi.order_id
    FROM order_items oi
    JOIN products p
        ON oi.product_id = p.product_id
),

operational AS (
    SELECT
        co.category_display,

        COUNT(*) AS associated_orders,

        SUM(o.eligible_on_time) AS eligible_orders,

        SUM(
            CASE
                WHEN o.eligible_on_time = 1
                 AND o.on_time_delivery = 0
                THEN 1
                ELSE 0
            END
        ) AS late_orders,

        ROUND(
            AVG(
                CASE
                    WHEN o.eligible_on_time = 1
                    THEN o.on_time_delivery
                END
            ) * 100,
            2
        ) AS on_time_rate_pct,

        ROUND(
            AVG(
                CASE
                    WHEN o.eligible_delivery_days = 1
                    THEN o.delivery_days
                END
            ),
            2
        ) AS avg_delivery_days,

        ROUND(
            AVG(
                CASE
                    WHEN o.eligible_processing_time = 1
                    THEN o.processing_days
                END
            ),
            2
        ) AS avg_processing_days,

        ROUND(
            AVG(
                CASE
                    WHEN o.eligible_transit_time = 1
                    THEN o.transit_days
                END
            ),
            2
        ) AS avg_transit_days

    FROM category_orders co

    JOIN orders o
        ON co.order_id = o.order_id

    GROUP BY co.category_display
),

commercial AS (
    SELECT
        p.category_display,

        COUNT(*) AS item_lines,

        COUNT(DISTINCT oi.order_id) AS item_associated_orders,

        COUNT(DISTINCT oi.product_id) AS distinct_products,

        ROUND(SUM(oi.price), 2) AS item_value,

        ROUND(SUM(oi.freight_value), 2) AS freight_value,

        ROUND(
            SUM(oi.freight_value)
            / NULLIF(SUM(oi.price), 0) * 100,
            2
        ) AS freight_to_item_value_pct

    FROM order_items oi

    JOIN products p
        ON oi.product_id = p.product_id

    GROUP BY p.category_display
),

physical AS (
    SELECT
        category_display,

        COUNT(*) AS catalog_products,

        ROUND(AVG(product_weight_g), 2) AS avg_product_weight_g

    FROM products

    GROUP BY category_display
)

SELECT
    c.category_display,

    c.distinct_products,
    p.catalog_products,

    o.associated_orders,
    o.eligible_orders,
    o.late_orders,
    o.on_time_rate_pct,

    o.avg_delivery_days,
    o.avg_processing_days,
    o.avg_transit_days,

    c.item_lines,
    c.item_value,
    c.freight_value,
    c.freight_to_item_value_pct,

    p.avg_product_weight_g

FROM commercial c

LEFT JOIN operational o
    ON c.category_display = o.category_display

LEFT JOIN physical p
    ON c.category_display = p.category_display;

CREATE VIEW vw_state_delivery_performance AS SELECT
    c.customer_state,

    COUNT(*) AS total_orders,

    SUM(o.eligible_on_time) AS eligible_orders,

    SUM(
        CASE
            WHEN o.eligible_on_time = 1
             AND o.on_time_delivery = 0
            THEN 1
            ELSE 0
        END
    ) AS late_orders,

    ROUND(
        AVG(
            CASE
                WHEN o.eligible_on_time = 1
                THEN o.on_time_delivery
            END
        ) * 100,
        2
    ) AS on_time_rate_pct,

    ROUND(
        AVG(
            CASE
                WHEN o.eligible_delivery_days = 1
                THEN o.delivery_days
            END
        ),
        2
    ) AS avg_delivery_days,

    ROUND(
        AVG(
            CASE
                WHEN o.eligible_processing_time = 1
                THEN o.processing_days
            END
        ),
        2
    ) AS avg_processing_days,

    ROUND(
        AVG(
            CASE
                WHEN o.eligible_transit_time = 1
                THEN o.transit_days
            END
        ),
        2
    ) AS avg_transit_days

FROM orders o

JOIN customers c
    ON o.customer_id = c.customer_id

GROUP BY c.customer_state;