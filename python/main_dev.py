#!/usr/bin/env python3
"""
Attune Steel — Dev Entry Point
Wraps the production main.py to inject dev middleware before startup.
"""
import os
import sys
import logging

# Set dev mode early so other modules can check it
os.environ['ATTUNE_DEV_MODE'] = '1'

# Enable DEBUG logging for dev builds
logging.getLogger('attune').setLevel(logging.DEBUG)

# Patch the FastAPI app with dev middleware before main() runs
from api.routes import app as fastapi_app
from dev_middleware import install_dev_middleware
install_dev_middleware(fastapi_app)

# Now run the normal main entry point
from main import main
main()
