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
- Use `TRY...CATCH` for error handling in stored procedures.
- Consider `TABLOCK` for large bulk inserts if appropriate.

## 🎯 Review Output Format

### Summary Assessment
- **Security Score**: [1-10]
- **Performance Score**: [1-10]
- **Maintainability Score**: [1-10]

### Findings Details
For each issue found, provide:
1. **[PRIORITY] [CATEGORY]: [Description]**
2. **Location**: Object name and approximate line.
3. **Risk/Impact**: Technical explanation.
4. **Recommendation**: Specific fix with code.

---
*Derived from github/awesome-copilot SQL Code Review Skill.*
