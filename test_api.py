#!/usr/bin/env python3
"""
Example script to test the FastAPI match reporting endpoint.

Usage:
    python test_api.py

Make sure the FastAPI server is running:
    python tournament_platform/api/server.py
"""

import requests
import json
import time

from tournament_platform.config import settings


def test_health():
    """Test the health check endpoint."""
    print("🏥 Testing health endpoint...")
    try:
        response = requests.get(f"{settings.API_BASE_URL}/health", timeout=10)
        print(f"  Status: {response.status_code}")
        print(f"  Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except requests.exceptions.ConnectionError:
        print(f"  ❌ Error: Cannot connect to {settings.API_BASE_URL}")
        return False
    except requests.exceptions.Timeout:
        print(f"  ❌ Error: Request timed out")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"  ❌ Error: HTTP {e.response.status_code if e.response else 'unknown'}")
        return False
    except json.JSONDecodeError:
        print(f"  ❌ Error: Invalid JSON response")
        return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_report_match(player1, player2, score, winner=None, tournament_id=None):
    """Test the match reporting endpoint."""
    print(f"\n🎾 Testing match report endpoint...")
    print(f"  Players: {player1} vs {player2}")
    print(f"  Score: {score}")

    payload = {
        "player1": player1,
        "player2": player2,
        "score": score,
        "winner": winner or player1,
        "tournament_id": tournament_id
    }

    try:
        response = requests.post(
            f"{settings.API_BASE_URL}/api/report",
            json=payload,
            timeout=10,
        )
        print(f"  Status: {response.status_code}")
        print(f"  Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except requests.exceptions.ConnectionError:
        print(f"  ❌ Error: Cannot connect to {settings.API_BASE_URL}")
        return False
    except requests.exceptions.Timeout:
        print(f"  ❌ Error: Request timed out")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"  ❌ Error: HTTP {e.response.status_code if e.response else 'unknown'}")
        return False
    except json.JSONDecodeError:
        print(f"  ❌ Error: Invalid JSON response")
        return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


def test_invalid_request():
    """Test error handling with invalid request."""
    print(f"\n❌ Testing error handling with invalid request...")

    payload = {
        "player1": "Alice"
        # Missing required fields
    }

    try:
        response = requests.post(
            f"{settings.API_BASE_URL}/api/report",
            json=payload,
            timeout=10,
        )
        print(f"  Status: {response.status_code}")
        print(f"  Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 400
    except requests.exceptions.ConnectionError:
        print(f"  ❌ Error: Cannot connect to {settings.API_BASE_URL}")
        return False
    except requests.exceptions.Timeout:
        print(f"  ❌ Error: Request timed out")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"  ❌ Error: HTTP {e.response.status_code if e.response else 'unknown'}")
        return False
    except json.JSONDecodeError:
        print(f"  ❌ Error: Invalid JSON response")
        return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def run_tests():
    """Run all API tests."""
    print("=" * 60)
    print("🧪 Tournament Platform API Test Suite")
    print("=" * 60)

    results = {
        "health_check": test_health(),
        "match_report_1": test_report_match("Alice", "Bob", "3-0", winner="Alice"),
        "match_report_2": test_report_match("Charlie", "Diana", "2-3", winner="Diana"),
        "error_handling": test_invalid_request(),
    }

    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_flag in results.items():
        status = "✅ PASS" if passed_flag else "❌ FAIL"
        print(f"  {test_name}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")

    return passed == total

if __name__ == "__main__":
    print("\nEnsure the FastAPI server is running:")
    print(f"  API Base URL: {settings.API_BASE_URL}")
    print("  python tournament_platform/api/server.py\n")

    # Wait for user confirmation
    input("Press Enter to start tests...")

    success = run_tests()
    exit(0 if success else 1)

