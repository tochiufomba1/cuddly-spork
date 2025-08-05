#!/bin/bash

# Exit on any error
set -e

# Run database migrations
.venv/bin/flask db upgrade

# Run your data initialization script
.venv/bin/python init_db.py