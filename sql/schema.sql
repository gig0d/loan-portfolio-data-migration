-- Shared SQLite / MySQL 8.0.16+ schema. The loader selects InnoDB on MySQL.
-- Money is stored in integer cents, never floating point.
CREATE TABLE IF NOT EXISTS customers (
    customer_id VARCHAR(64) NOT NULL PRIMARY KEY,
    full_name VARCHAR(200) NOT NULL,
    email VARCHAR(254) NOT NULL,
    country_code VARCHAR(2) NOT NULL,
    date_of_birth DATE NOT NULL,
    CONSTRAINT uq_customers_email UNIQUE (email)
);

CREATE TABLE IF NOT EXISTS loans (
    loan_id VARCHAR(64) NOT NULL PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL,
    principal_amount_cents BIGINT NOT NULL,
    start_date DATE NOT NULL,
    status VARCHAR(6) NOT NULL,
    CONSTRAINT fk_loans_customer FOREIGN KEY (customer_id)
        REFERENCES customers (customer_id),
    CONSTRAINT ck_loans_amount CHECK (
        principal_amount_cents > 0 AND principal_amount_cents <= 9000000000000000
    ),
    CONSTRAINT ck_loans_status CHECK (status IN ('active', 'closed')),
    CONSTRAINT ck_loans_customer_present CHECK (customer_id <> ''),
    CONSTRAINT uq_loans_customer_loan UNIQUE (customer_id, loan_id)
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id VARCHAR(64) NOT NULL PRIMARY KEY,
    loan_id VARCHAR(64) NOT NULL,
    amount_cents BIGINT NOT NULL,
    payment_date DATE NOT NULL,
    CONSTRAINT fk_payments_loan FOREIGN KEY (loan_id) REFERENCES loans (loan_id),
    CONSTRAINT ck_payments_amount CHECK (
        amount_cents > 0 AND amount_cents <= 9000000000000000
    ),
    CONSTRAINT ck_payments_loan_present CHECK (loan_id <> ''),
    CONSTRAINT uq_payments_loan_payment UNIQUE (loan_id, payment_id)
);
