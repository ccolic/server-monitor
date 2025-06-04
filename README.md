# Server Monitor

A flexible monitoring daemon for servers and endpoints.

## Features

- **Multiple Check Types**: HTTP/HTTPS, TCP, TLS certificate checks
- **Concurrent Monitoring**: Monitor multiple endpoints concurrently
- **Configurable Alerts**: Email and webhook notifications
- **Data Storage**: PostgreSQL and SQLite support
- **Flexible Configuration**: YAML-based configuration
- **Docker Support**: Run in a containerized environment

## Installation

### From PyPI (Not available yet)

```bash
pip install server-monitor
```

### From Source

```bash
# Clone the repository
git clone https://github.com/yourusername/server-monitor.git
cd server-monitor

# Install the package
pip install -e .
```

### Using Docker

```bash
docker pull ghcr.io/yourusername/server-monitor:latest
```

## Configuration

Create a configuration file based on the example:

```bash
# Copy the example configuration
cp config.yaml.example config.yaml

# Edit the configuration to match your needs
editor config.yaml
```

Or generate a sample configuration:

```bash
server-monitor generate-config --output config.yaml
```

### Configuration Format

The configuration file is in YAML format and has the following structure:

```yaml
global:
  log_level: INFO
  log_file: server-monitor.log
  max_concurrent_checks: 10
  
  # Email notification settings
  email_notifications:
    enabled: true
    events:
      - both  # can be 'failure', 'recovery', or 'both'
    smtp:
      host: smtp.example.com
      port: 587
      username: user@example.com
      password: "your-password"
      use_tls: true
      from_email: monitor@example.com
    recipients:
      - alerts@example.com
    subject_template: "Monitor Alert: {endpoint_name} - {status}"
  
  # Webhook notification settings
  webhook_notifications:
    enabled: true
    events:
      - failure
    webhook:
      url: https://hooks.slack.com/services/your/webhook/url
      method: POST
      headers:
        Content-Type: application/json
      timeout: 30
      
  # Database settings
  database:
    type: sqlite  # can be 'sqlite' or 'postgresql'
    database: monitor.db
    # For PostgreSQL:
    # type: postgresql
    # host: localhost
    # port: 5432
    # database: monitor
    # username: postgres
    # password: "your-password"

# Endpoints to monitor
endpoints:
  - name: Example Website
    type: http
    interval: 60  # seconds
    enabled: true
    http:
      url: https://example.com
      method: GET
      timeout: 30
      expected_status: 200
      content_match: Example Domain
      follow_redirects: true
  
  # More endpoints...
```

## Usage

### Start Monitoring

```bash
server-monitor start config.yaml
```

### Check Status

```bash
server-monitor status config.yaml
```

### Generate Sample Configuration

```bash
server-monitor generate-config --output config.yaml
```

### Using Docker

```bash
# Mount your configuration file
docker run -v $(pwd)/config.yaml:/app/config.yaml \
           -v $(pwd)/data:/app/data \
           ghcr.io/yourusername/server-monitor:latest
```

## Check Types

### HTTP/HTTPS Checks

Monitors HTTP endpoints for:
- Status codes
- Response time
- Content matching (plain text or regex)
- Redirects
- SSL verification

```yaml
http:
  url: https://example.com
  method: GET
  headers:
    Authorization: Bearer token
  timeout: 30
  expected_status: 200
  content_match: Example Domain
  content_regex: false
  follow_redirects: true
  verify_ssl: true
```

### TCP Checks

Monitors TCP ports for connectivity:

```yaml
tcp:
  host: db.example.com
  port: 5432
  timeout: 10
```

### TLS Certificate Checks

Monitors SSL/TLS certificates for validity and expiration:

```yaml
tls:
  host: example.com
  port: 443
  timeout: 30
  cert_expiry_warning_days: 30
```

## Development

### Setup Development Environment

```bash
# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev]"

# Set up pre-commit hooks
pre-commit install
```

### Run Tests

```bash
pytest
```

## License

MIT License
