#!/bin/bash
set -e

cd /app

# Create local-override.yml if missing (required by config loader)
touch app/config/local-override.yml

# Install dependencies
uv venv /opt/venv --quiet
uv pip install --python /opt/venv/bin/python -r requirements.txt --quiet

# Install and start MySQL
DEBIAN_FRONTEND=noninteractive apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mysql-server mysql-client > /dev/null 2>&1 || true
mysqld --user=mysql --datadir=/var/lib/mysql &
sleep 3

# Create database and user
mysql -u root -e "CREATE DATABASE IF NOT EXISTS celts; CREATE USER IF NOT EXISTS 'celts_user'@'%' IDENTIFIED BY 'password'; GRANT ALL PRIVILEGES ON *.* TO 'celts_user'@'%'; FLUSH PRIVILEGES;"

# Run migrations and load test data
cd /app/database
APP_ENV=testing PATH=/opt/venv/bin:$PATH bash migrate_db.sh no-backup
APP_ENV=testing /opt/venv/bin/python base_data.py
APP_ENV=testing /opt/venv/bin/python test_data.py
cd /app
