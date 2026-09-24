#!/usr/bin/env python
"""Configuration diagnostics utility.

Prints safe, sanitized configuration values for the active runtime mode.
Secrets (passwords, tokens, API keys) are never printed.
"""

import sys
from pathlib import Path

# Ensure src is in python path
repo_root = Path(__file__).resolve().parent.parent
src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))
from agent.core.config import get_settings


def main() -> None:
    settings = get_settings()
    data = settings.safe_dict()

    print("=" * 65)
    print("  ServiceNow UAT Agent - Configuration Diagnostics")
    print("=" * 65)
    print(f"Runtime Mode:           {data['runtime_mode'].upper()}")
    print(f"Environment:            {data['environment']}")
    print(f"Active Env File:        {data['active_env_file'] or '(none - using process environment)'}")
    print(f"Repository Root:        {data['repo_root']}")
    print(f"Report Output Dir:      {data['report_output_dir']}")
    print(f"Screenshot Dir:         {data['screenshot_dir']}")
    print("-" * 65)
    print(f"Database URL:           {data['database_url']}")
    print(f"Redis URL:              {data['redis_url']}")
    print(f"Celery Broker URL:      {data['celery_broker_url']}")
    print(f"Celery Backend URL:     {data['celery_result_backend']}")
    print("-" * 65)
    print(f"Browser Headless:       {data['browser']['headless']}")
    print(f"Browser Slow Mo:        {data['browser']['slow_mo']} ms")
    print(f"Browser Show Cursor:    {data['browser']['show_mouse_cursor']}")
    print(f"Browser Keep Open:      {data['browser']['keep_browser_open']}")
    print(f"Browser Timeout:        {data['browser']['interactive_timeout_seconds']} s")
    print("-" * 65)
    print(f"ServiceNow URL:         {data['servicenow']['instance_url']}")
    print(f"ServiceNow User:        {data['servicenow']['username']}")
    print(f"ServiceNow Pwd Set:     {data['servicenow']['password_configured']}")
    print("-" * 65)
    print(f"LLM Provider:           {data['llm']['provider']}")
    print(f"LLM Model:              {data['llm']['model']}")
    print(f"LLM Embedding Model:    {data['llm']['embedding_model']}")
    print(f"LLM API Key Set:        {data['llm']['api_key_configured']}")
    print("-" * 65)
    print(f"JWT Algorithm:          {data['auth']['jwt_algorithm']}")
    print(f"JWT Secret Set:         {data['auth']['jwt_secret_configured']}")
    print("=" * 65)


if __name__ == "__main__":
    main()
