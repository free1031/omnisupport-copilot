-- Separate legacy course fixtures from the product tenant before capstone bootstrap.
-- Capstone ingest writes tenant_id explicitly, so no existing Week01-Week14 row is deleted.

ALTER TABLE customer_dim
    ALTER COLUMN tenant_id SET DEFAULT 'course-legacy';

ALTER TABLE ticket_fact
    ALTER COLUMN tenant_id SET DEFAULT 'course-legacy';

UPDATE ticket_fact
SET tenant_id = 'course-legacy'
WHERE data_release_id IS DISTINCT FROM 'data-capstone-v1';

UPDATE customer_dim customer
SET tenant_id = 'course-legacy'
WHERE NOT EXISTS (
    SELECT 1
    FROM ticket_fact ticket
    WHERE ticket.customer_id = customer.customer_id
      AND ticket.data_release_id = 'data-capstone-v1'
);
