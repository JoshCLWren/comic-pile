"""Tests for rate limiting functionality."""

import random

import pytest
from httpx import AsyncClient

from app.middleware import limiter


