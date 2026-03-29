"""VP-1000: Vital Pulse Engine
Checks company vital signs using free web signals.
No paid APIs. All checks use standard HTTP requests.
"""

import requests
import re
from datetime import datetime, timezone


def _safe_head(url, timeout=10):
    """HEAD request with fallback to GET."""
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True,
                         headers={"User-Agent": "SUPPLY-1000/1.0"})
        return r
    except Exception:
        try:
            r = requests.get(url, timeout=timeout, allow_redirects=True, stream=True,
                           headers={"User-Agent": "SUPPLY-1000/1.0"})
            return r
        except Exception:
            return None


def check_website_alive(domain):
    """Check if the company website is responding.
    Returns dict: {alive: bool, status_code: int, response_time_ms: float}
    """
    if not domain:
        return {"alive": False, "status_code": 0, "response_time_ms": 0}
    import time
    start = time.time()
    r = _safe_head(f"https://{domain}")
    elapsed = (time.time() - start) * 1000
    if r is None:
        # Try http
        r = _safe_head(f"http://{domain}")
        elapsed = (time.time() - start) * 1000
    if r is None:
        return {"alive": False, "status_code": 0, "response_time_ms": 0}
    return {
        "alive": r.status_code < 400,
        "status_code": r.status_code,
        "response_time_ms": round(elapsed, 1),
    }


def check_careers_page(domain):
    """Check if the company has a careers/jobs page (indicates hiring activity).
    Returns dict: {has_careers: bool, careers_url: str or None}
    """
    if not domain:
        return {"has_careers": False, "careers_url": None}

    career_paths = ["/careers", "/jobs", "/career", "/join-us", "/work-with-us", "/employment"]
    for path in career_paths:
        url = f"https://{domain}{path}"
        try:
            r = requests.head(url, timeout=8, allow_redirects=True,
                            headers={"User-Agent": "SUPPLY-1000/1.0"})
            if r.status_code < 400:
                return {"has_careers": True, "careers_url": url}
        except Exception:
            continue
    return {"has_careers": False, "careers_url": None}


def check_website_freshness(domain):
    """Check how recently the website was updated using Last-Modified header.
    Returns dict: {last_modified: str or None, days_since_update: int or None}
    """
    if not domain:
        return {"last_modified": None, "days_since_update": None}
    r = _safe_head(f"https://{domain}")
    if r is None:
        return {"last_modified": None, "days_since_update": None}

    last_mod = r.headers.get("Last-Modified")
    if last_mod:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(last_mod)
            days = (datetime.now(timezone.utc) - dt).days
            return {"last_modified": last_mod, "days_since_update": days}
        except Exception:
            pass
    return {"last_modified": None, "days_since_update": None}


def check_ssl_freshness(domain):
    """Check SSL certificate issue/expiry dates.
    Returns dict: {issued: str, expires: str, days_until_expiry: int}
    """
    if not domain:
        return {"issued": None, "expires": None, "days_until_expiry": None}
    import ssl
    import socket
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
            s.settimeout(10)
            s.connect((domain, 443))
            cert = s.getpeercert()
        not_after = cert.get("notAfter", "")
        not_before = cert.get("notBefore", "")
        # Parse dates
        exp = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
        iss = datetime.strptime(not_before, "%b %d %H:%M:%S %Y %Z")
        days_left = (exp - datetime.utcnow()).days
        return {
            "issued": not_before,
            "expires": not_after,
            "days_until_expiry": days_left,
        }
    except Exception:
        return {"issued": None, "expires": None, "days_until_expiry": None}


def check_robots_sitemap(domain):
    """Check if robots.txt and sitemap.xml exist (sign of maintained website).
    Returns dict: {has_robots: bool, has_sitemap: bool}
    """
    if not domain:
        return {"has_robots": False, "has_sitemap": False}
    has_robots = False
    has_sitemap = False
    try:
        r = requests.get(f"https://{domain}/robots.txt", timeout=8,
                        headers={"User-Agent": "SUPPLY-1000/1.0"})
        if r.status_code == 200 and len(r.text) > 10:
            has_robots = True
            if "sitemap" in r.text.lower():
                has_sitemap = True
    except Exception:
        pass
    if not has_sitemap:
        try:
            r = requests.head(f"https://{domain}/sitemap.xml", timeout=8,
                            headers={"User-Agent": "SUPPLY-1000/1.0"})
            if r.status_code < 400:
                has_sitemap = True
        except Exception:
            pass
    return {"has_robots": has_robots, "has_sitemap": has_sitemap}


def run_vital_pulse(domain):
    """Run all vital pulse checks on a domain.
    Returns dict with all check results + overall vital_score (0-100).
    """
    alive = check_website_alive(domain)
    careers = check_careers_page(domain)
    freshness = check_website_freshness(domain)
    ssl_info = check_ssl_freshness(domain)
    robots = check_robots_sitemap(domain)

    # Calculate vital score (0-100)
    score = 0
    signals = []

    # Website alive (30 points)
    if alive["alive"]:
        score += 30
        signals.append(("Website Active", "positive"))
    else:
        signals.append(("Website Down", "negative"))

    # Careers page exists (25 points) - strong hiring signal
    if careers["has_careers"]:
        score += 25
        signals.append(("Careers Page Found", "positive"))
    else:
        signals.append(("No Careers Page", "neutral"))

    # Website freshness (15 points)
    days = freshness.get("days_since_update")
    if days is not None:
        if days < 30:
            score += 15
            signals.append(("Recently Updated", "positive"))
        elif days < 180:
            score += 8
            signals.append(("Updated within 6 months", "neutral"))
        else:
            signals.append(("Stale Content", "negative"))
    else:
        score += 5  # no data = neutral
        signals.append(("Update date unknown", "neutral"))

    # SSL valid and not expiring soon (15 points)
    days_left = ssl_info.get("days_until_expiry")
    if days_left is not None:
        if days_left > 60:
            score += 15
            signals.append(("SSL Valid", "positive"))
        elif days_left > 0:
            score += 8
            signals.append(("SSL Expiring Soon", "negative"))
        else:
            signals.append(("SSL Expired", "negative"))
    else:
        signals.append(("No SSL", "negative"))

    # Robots.txt + Sitemap (15 points)
    if robots["has_robots"]:
        score += 8
    if robots["has_sitemap"]:
        score += 7
    if robots["has_robots"] or robots["has_sitemap"]:
        signals.append(("SEO Maintained", "positive"))
    else:
        signals.append(("No SEO Setup", "neutral"))

    return {
        "vital_score": score,  # 0-100
        "signals": signals,
        "alive": alive,
        "careers": careers,
        "freshness": freshness,
        "ssl": ssl_info,
        "robots": robots,
        "domain": domain,
    }
