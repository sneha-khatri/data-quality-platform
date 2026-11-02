# AI-Ready Data Quality & Duplicate Record Management Platform

A Python full-stack web application (Flask + SQLite) that helps organizations import, validate, clean, compare and manage records such as customer, employee and vendor data.

## Problem
Organizations keep data across multiple systems. Over time it collects duplicate records, missing fields, inconsistent formats and conflicting values. This hurts reporting, decisions and operational efficiency.

## Features
- **CSV import** of records (name, email, phone, address, city)
- **Validation** of missing fields, invalid email, invalid phone and inconsistent formatting
- **Data-quality score** (0-100) for every record, plus a dashboard with overall statistics
- **Cleaning suggestions** (standardised names, lowercase emails, 10-digit phones) applied only after user approval
- **Duplicate detection** using fuzzy name matching with email/phone comparison, with merge or reject decisions
- **Manual editing** to fill in missing or wrong values
- **Correction history** (audit log): what changed, old and new value, who did it and when
- **Role-based access**: admin, reviewer (can approve and merge) and viewer (read-only)
- **Export** of the cleaned data as CSV

## Tech Stack
Python, Flask, SQLite, HTML/CSS (Jinja2 templates)

## Setup
```bash
git clone https://github.com/sneha-khatri/data-quality-platform.git
cd data-quality-platform
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 in your browser.

## Demo Logins
| Username | Password | Role |
|----------|----------|------|
| admin | admin123 | Admin |
| reviewer | review123 | Reviewer |
| viewer | view123 | Viewer (read-only) |

## How to Try It
1. Log in as `admin`.
2. Go to **Import** and upload `sample_data.csv`.
3. Check **Records** for quality scores and suggested fixes, then approve or edit them.
4. Open **Duplicates** to merge or reject suspected duplicate pairs.
5. See **History** for the full change log, and **Export** to download the cleaned data.

## Project Structure
```
app.py            Flask app: routes, validation, scoring, duplicate detection
templates/        HTML pages (dashboard, records, duplicates, history, ...)
sample_data.csv   Sample dataset with intentional errors and duplicates
requirements.txt  Python dependencies
```

## Future Scope
- ML-based duplicate matching (TF-IDF / embeddings)
- Support for Excel files and database connectors
- Configurable validation rules and scoring weights
