---
name: sql-code-review
description: 'Universal SQL code review assistant for DBA AI. Performs comprehensive security, performance, and code quality analysis. Specialized in T-SQL (SQL Server) but applicable to all SQL databases. Focuses on SQL injection prevention, SARGability, indexing, and anti-pattern detection.'
---

# SQL Code Review Skill

Perform a thorough SQL code review focusing on security, performance, maintainability, and database-specific best practices (T-SQL / SQL Server).

## 🔒 Security Analysis

### SQL Injection Prevention
- **Parameterized Queries**: Verify that all user inputs are handled via parameters.
- **Dynamic SQL**: Avoid string concatenation in `sp_executesql` or `EXEC`. If required, use `QUOTENAME()` for identifiers.
- **Surface Area**: Minimize the use of xp_cmdshell, OLE features, and cross-database queries.

### Access Control & Permissions
- **Principle of Least Privilege**: Ensure scripts use minimal required permissions.
- **Schema Ownership**: Validate that objects are created in the correct schema (e.g., `dbo`, `sales`).

## ⚡ Performance Optimization

### SARGability (Search ARGumentable)
- Avoid using functions on columns in the `WHERE` or `JOIN` clauses.
- **Bad**: `WHERE YEAR(OrderDate) = 2024`
- **Good**: `WHERE OrderDate >= '2024-01-01' AND OrderDate < '2025-01-01'`

### Indexing Strategy
- **Missing Indexes**: Check if columns used in filters or joins are likely to need indexes.
- **Implicit Conversions**: Avoid data type mismatches that prevent index usage (e.g., comparing `VARCHAR` to `NVARCHAR`).

### Query Quality
- **SELECT \***: Always specify column names to reduce IO and network traffic.
- **Joins**: Prefer `INNER JOIN` over `WHERE` clause joins. Avoid unintentional Cartesian products.
- **Set-based vs Procedural**: Prefer set-based operations over cursors or RBAR (Row By Agonizing Row) processing.

## 🛠️ Code Quality & Maintainability

### Formatting & Style
- Consistent capitalization (keywords in `UPPERCASE`).
- Indentation for nested queries and `JOIN` conditions.
- Semicolons as statement terminators.

### Naming Conventions
- Avoid reserved words as identifiers.
- Consistent naming (e.g., `CamelCase` or `snake_case` according to project standards).
- Schema-prefixed object names (e.g., `dbo.MyTable` instead of just `MyTable`).

## 📊 SQL Server Specifics
- Use `DATETIME2` instead of `DATETIME` for better precision and range.
- Use `NVARCHAR(MAX)` only when truly necessary.
- Use `TRY...CATCH` for error handling in stored procedures and DML scripts.
- Consider `TABLOCK` for large bulk inserts if appropriate.

## 🗄️ T-SQL Migration Script Patterns

### DDL Scripts (CREATE TABLE, ALTER TABLE)
- **Schema qualification**: Always prefix objects with schema (`dbo.TableName`, not bare `TableName`).
- **IDENTITY**: Integer PKs intended as auto-increment must declare `IDENTITY(1,1)`. Without it, every INSERT must provide the value manually and re-runs will cause PK violations.
- **NULL / NOT NULL**: Columns are NULLable by default. Declare `NOT NULL` explicitly for required fields.
- **Idempotency**: Use existence checks so the script can run safely more than once:
  - CREATE: `IF OBJECT_ID('dbo.TableName', 'U') IS NULL CREATE TABLE dbo.TableName (...)`
  - DROP: `IF OBJECT_ID('dbo.TableName', 'U') IS NOT NULL DROP TABLE dbo.TableName`
  - ADD COLUMN: `IF COL_LENGTH('dbo.TableName', 'ColumnName') IS NULL ALTER TABLE dbo.TableName ADD ...`
- **NVARCHAR vs VARCHAR**: Use `NVARCHAR` when the column may store Unicode characters (names, descriptions, free text).

### DML Scripts (INSERT, UPDATE, DELETE)
- **TRY/CATCH**: Wrap DML in `BEGIN TRY / END TRY BEGIN CATCH / END CATCH` to handle errors gracefully.
- **Transactions**: Use `BEGIN TRANSACTION / COMMIT / ROLLBACK` for multi-statement DML to guarantee atomicity.
- **Schema qualification**: Always use `dbo.TableName`, not bare `TableName`.
- **Duplicate guard**: For seed/reference INSERTs, check existence before inserting to ensure idempotency:
  - `IF NOT EXISTS (SELECT 1 FROM dbo.TableName WHERE Id = 1) INSERT INTO dbo.TableName ...`

### Rollback Scripts
- **Idempotency**: Always guard DROP statements with `IF OBJECT_ID`:
  - `IF OBJECT_ID('dbo.TableName', 'U') IS NOT NULL DROP TABLE dbo.TableName`
- DROP TABLE, DROP PROCEDURE, TRUNCATE, DELETE are expected and correct in rollback scripts.
