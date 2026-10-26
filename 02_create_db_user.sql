-- Run this in MySQL Workbench as root/admin after 01_schema.sql.
-- The account is limited to the ExamAI Python database.
CREATE USER IF NOT EXISTS 'examai_app'@'localhost' IDENTIFIED BY 'examai_app_2026';
CREATE USER IF NOT EXISTS 'examai_app'@'%' IDENTIFIED BY 'examai_app_2026';
ALTER USER 'examai_app'@'localhost' IDENTIFIED BY 'examai_app_2026';
ALTER USER 'examai_app'@'%' IDENTIFIED BY 'examai_app_2026';
GRANT ALL PRIVILEGES ON examai_python.* TO 'examai_app'@'localhost';
GRANT ALL PRIVILEGES ON examai_python.* TO 'examai_app'@'%';
FLUSH PRIVILEGES;
SELECT 'ExamAI app database user ready' AS status, 'examai_app' AS username,
       'examai_python' AS db_name;
