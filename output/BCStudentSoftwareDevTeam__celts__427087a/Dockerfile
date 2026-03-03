FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN ln -sf /usr/bin/python3 /usr/bin/python
# Clone repo and checkout specific commit
RUN git clone https://github.com/BCStudentSoftwareDevTeam/celts.git /app && \
    cd /app && (git checkout 427087a16da529939eb6d8f528a72bed8d2b4ad3 --quiet 2>/dev/null || \
    (git fetch --depth=1 origin 427087a16da529939eb6d8f528a72bed8d2b4ad3 && git checkout 427087a16da529939eb6d8f528a72bed8d2b4ad3 --quiet))
WORKDIR /app

# Install dependencies
RUN touch /app/app/config/local-override.yml && uv venv /opt/venv --quiet && uv pip install --python /opt/venv/bin/python -r requirements.txt --quiet && DEBIAN_FRONTEND=noninteractive apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mysql-server mysql-client > /dev/null 2>&1; mysqld --user=mysql --datadir=/var/lib/mysql & sleep 3 && mysql -u root -e "CREATE DATABASE IF NOT EXISTS celts; CREATE USER IF NOT EXISTS 'celts_user'@'%' IDENTIFIED BY 'password'; GRANT ALL PRIVILEGES ON *.* TO 'celts_user'@'%'; FLUSH PRIVILEGES;" && cd /app/database && APP_ENV=testing PATH=/opt/venv/bin:$PATH bash migrate_db.sh no-backup && APP_ENV=testing /opt/venv/bin/python base_data.py && APP_ENV=testing /opt/venv/bin/python test_data.py && cd /app

# Default command: run tests
CMD ["bash", "-c", "cd /app && APP_ENV=testing /opt/venv/bin/python -m pytest --tb=short -q --ignore=tests/mail_test.py --ignore=tests/ui --ignore=database -m "unit or integration""]
