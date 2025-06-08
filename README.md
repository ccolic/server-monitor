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
  log_max_bytes: 5242880  # 5 MB
  log_backup_count: 3
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
      connection_method: starttls  # Options: 'starttls', 'ssl', or 'plain'
      # Connection Method Examples:
      # For STARTTLS (common ports: 587, 25):
      #   connection_method: starttls
      #   port: 587
      #
      # For Direct SSL/TLS (common ports: 465):
      #   connection_method: ssl
      #   port: 465
      #
      # For Plain/Unsecured (not recommended):
      #   connection_method: plain
      #   port: 25
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

## Enhanced Notification Features

The monitoring system includes advanced notification features to reduce alert fatigue and ensure you're only notified when necessary:

### Failure Threshold
- **`failure_threshold`**: Set the number of consecutive failures required before sending an alert
- Default: `1` (alert on first failure)
- Example: Set to `3` to only alert after 3 consecutive check failures

### Repeated Alert Suppression
- **`suppress_repeated`**: Prevent repeated notifications for the same ongoing failure
- Default: `true`
- When enabled, only the first notification is sent when the threshold is reached
- Recovery notifications are always sent regardless of this setting

### Notification Behavior
1. **First failure**: Endpoint goes down → Count consecutive failures
2. **Threshold reached**: Send notification after X consecutive failures
3. **Ongoing failure**: Suppress further notifications (if `suppress_repeated: true`)
4. **Recovery**: Always send recovery notification and reset failure count
5. **Future failures**: Start counting from 1 again

### Example Configuration

```yaml
global:
  email_notifications:
    enabled: true
    events: [both]
    failure_threshold: 3      # Alert after 3 consecutive failures
    suppress_repeated: true   # Don't repeat alerts for same failure
    # ... smtp configuration

  webhook_notifications:
    enabled: true
    events: [failure]
    failure_threshold: 2      # Alert after 2 consecutive failures
    suppress_repeated: true   # Don't repeat alerts for same failure
    # ... webhook configuration
```

This configuration will:
- Send email alerts after 3 consecutive failures
- Send webhook alerts after 2 consecutive failures
- Not send repeated failure notifications
- Always send recovery notifications

## Endpoint-Specific Notification Overrides

You can override notification settings for individual endpoints while inheriting global SMTP/webhook configurations. This allows you to:

- Send critical alerts to different recipients
- Use different failure thresholds per endpoint
- Customize notification behavior for specific services
- Maintain a single global SMTP configuration

### Inheritance Behavior

Endpoint configurations **inherit** from global settings and only override the fields you specify:

- **SMTP settings** are always inherited from global configuration
- **Recipients, thresholds, and behavior** can be overridden per endpoint
- **Missing fields** automatically use global defaults

### Email Override Examples

```yaml
global:
  email_notifications:
    enabled: true
    smtp:
      host: smtp.example.com
      # ... complete SMTP configuration
    recipients: ["team@example.com"]
    failure_threshold: 3
    events: [both]

endpoints:
  - name: Critical API
    type: http
    # ... endpoint configuration
    email_notifications:
      enabled: true
      recipients: ["oncall@example.com", "cto@example.com"]  # Override recipients
      failure_threshold: 1                                   # Alert immediately
      # Inherits: smtp, events, suppress_repeated, subject_template

  - name: Background Service
    type: http
    # ... endpoint configuration
    email_notifications:
      enabled: true
      events: [failure]                    # Only notify on failures
      suppress_repeated: false             # Allow repeated notifications
      subject_template: "🔧 Service Issue: {endpoint_name}"
      # Inherits: smtp, recipients, failure_threshold

  - name: Development Environment
    type: http
    # ... endpoint configuration
    email_notifications:
      enabled: false  # Disable notifications for this endpoint
```

### Webhook Override Examples

```yaml
global:
  webhook_notifications:
    enabled: true
    webhook:
      url: https://hooks.slack.com/services/team/general
      # ... webhook configuration
    events: [both]
    failure_threshold: 2

endpoints:
  - name: Production API
    type: http
    # ... endpoint configuration
    webhook_notifications:
      enabled: true
      webhook:
        url: https://hooks.slack.com/services/team/alerts  # Different Slack channel
        headers:
          Content-Type: application/json
          X-Priority: high
      failure_threshold: 1                                 # Alert immediately
      # Inherits: method, timeout, events, suppress_repeated

  - name: Monitoring Endpoint
    type: http
    # ... endpoint configuration
    webhook_notifications:
      enabled: true
      events: [recovery]           # Only notify on recovery
      failure_threshold: 5         # Less sensitive
      # Inherits: webhook configuration, suppress_repeated
```

### Validation Rules

- **Global configurations** must be complete (include all required fields like SMTP settings and recipients)
- **Endpoint overrides** can be partial and will inherit missing fields from global configuration
- **At least one notification method** (global email or webhook) must be configured if endpoint overrides are used
- **Endpoint overrides without global configuration** will fail validation

## Environment Variables

To securely store sensitive information, set the following environment variables:

- `SMTP_USERNAME`: Your SMTP username.
- `SMTP_PASSWORD`: Your SMTP password.

These variables will override the values in `config.yaml`.

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

## Usage Examples

### Start Monitoring

```bash
server-monitor start config.yaml
```

### Check Status

```bash
server-monitor status config.yaml --output json
```

### Health Check

The health check endpoint is used for Docker container monitoring. It returns "OK" if the application is running correctly.

```bash
server-monitor health
```

## Metrics and Monitoring

Server Monitor provides comprehensive metrics in Prometheus format for integration with monitoring systems like Prometheus, Grafana, and others.

### Accessing Metrics

When the daemon is running, metrics are exposed via HTTP endpoints:

- **Prometheus format** (default): `http://localhost:8080/metrics`
- **Health check**: `http://localhost:8080/health`
- **Status**: `http://localhost:8080/status`

### Prometheus Metrics

The following metrics are available:

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `server_monitor_checks_total` | Counter | Total number of health checks performed | `endpoint`, `status` |
| `server_monitor_response_time_seconds` | Histogram | Response time of health checks in seconds | `endpoint` |
| `server_monitor_endpoint_up` | Gauge | Whether the endpoint is up (1) or down (0) | `endpoint` |
| `server_monitor_uptime_seconds` | Gauge | Monitor uptime in seconds | - |
| `server_monitor_endpoint_success_rate` | Gauge | Success rate of endpoint checks (0-1) | `endpoint` |
| `server_monitor_endpoint_avg_response_time_seconds` | Gauge | Average response time for endpoint in seconds | `endpoint` |

### Prometheus Configuration

Add this job to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'server-monitor'
    static_configs:
      - targets: ['localhost:8080']
    scrape_interval: 30s
    metrics_path: /metrics
```

### CLI Metrics

View metrics from the command line in Prometheus format:

```bash
# Display Prometheus metrics
server-monitor metrics
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

## Troubleshooting

### Database Connection Errors

- Ensure the database server is running and accessible.
- Verify the connection details in `config.yaml`.

### Docker Health Check Failures

- Check the logs for errors using:

```bash
docker logs <container_id>
```

- Ensure the health check endpoint is accessible.

### Configuration Issues

- Validate the YAML syntax in `config.yaml`.
- Use the `generate-config` command to create a new configuration file.

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
