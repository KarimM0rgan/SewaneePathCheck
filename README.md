# PathCheck — Sewanee Academic Program Overlap Checker

A Flask + SQL web application that helps Sewanee students, advisors, and department chairs check course overlap between any combination of majors and minors.

Built as the CS284 (Database Design with Web Applications) final project
by Karim Morgan and Safae Berhenich.

---

## What it does

Sewanee's academic policy limits students to two overlapping courses between any two programs. PathCheck automates this check.

**Three views, three users:**

- **Student** — Select any two programs from a dropdown. The app returns a full overlap report (direct overlaps, course equivalencies, and a pass/fail verdict against the two-course limit) with differentiated logic for major-major vs. major-minor combinations.

- **Advisor** — A read-only dashboard listing every program pair across Sewanee's catalog that exceeds two shared core courses, sorted by overlap severity. Useful for flagging known conflict pairs before advising sessions.

- **Department Chair** — Filter by department to see "hot courses" — courses that appear as core requirements in three or more programs. Useful for scheduling and curriculum review.

---

## Technical overview

**Database (MySQL, 8 tables)**
departments → courses ← major_requirements → majors ← minor_requirements → minors
equivalencies (course-to-course sub rules)
catalog_sources (provenance tracking)

Foreign keys enforced throughout. Equivalencies table captures cases where two different course codes satisfy the same requirement (e.g., cross-listed courses), allowing the overlap checker to catch non-obvious conflicts.

**ETL pipeline (`catalog_programs.py`)**

A URL-list crawler that fetches each program's catalog page, parses visible text using a custom `HTMLParser` (no external parsing libraries), extracts course codes via regex (`[A-Z]{2,5}\s+\d{3}[A-Z]?`), classifies them as
core/elective/alternative by context, and inserts them into MySQL. Outputs a `catalog_loader_report.txt` with per-program scrape counts and a validation pass against minimum expected row counts.

**Flask app (`app.py`)**

Five routes. Overlap queries use parameterized SQL with multi-table JOINs, UNIONs, correlated subqueries, and `GROUP_CONCAT`/`HAVING` for the advisor and department-chair aggregations. Dynamic table name selection handles the
shared query logic across major and minor requirement tables.

**Stack:** Python 3.12, Flask 3.1, MySQLdb (mysqlclient), Jinja2, plain CSS

---

## Authors

Karim Morgan ([@KarimM0rgan](https://github.com/KarimM0rgan)) and Safae Berhenich — Sewanee CS284, Spring 2026
