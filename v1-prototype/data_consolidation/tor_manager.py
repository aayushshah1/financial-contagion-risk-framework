"""
Tor Session Manager for Anonymous Web Scraping
Handles Tor lifecycle, IP rotation, and session management.

Author: Auto-generated
Date: February 2026
"""

import os
import sys
import time
import logging
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from stem import Signal
    from stem.control import Controller
    STEM_AVAILABLE = True
except ImportError:
    STEM_AVAILABLE = False
    print("Warning: stem not installed. Tor IP rotation disabled.")

try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
    print("Warning: curl_cffi not installed. Using standard requests library.")

logger = logging.getLogger(__name__)


class TorSessionManager:
    """Manages Tor lifecycle and provides session management with IP rotation."""
    
    # Default Tor configuration
    DEFAULT_SOCKS_PORT = 9050
    DEFAULT_CONTROL_PORT = 9051
    
    def __init__(
        self, 
        project_root: str = None,
        rotation_interval: int = 10,
        delay_range: tuple = (1, 4),
        use_curl_cffi: bool = True,
        tor_enabled: bool = True,
        auto_start_tor: bool = True,
        socks_port: int = None,
        control_port: int = None,
        worker_id: int = 0
    ):
        """
        Initialize Tor Session Manager.
        
        Args:
            project_root: Root directory containing tor_bundle and tor_data
            rotation_interval: Number of requests before rotating IP
            delay_range: (min, max) seconds for random delays
            use_curl_cffi: Use curl_cffi for better Cloudflare bypass
            tor_enabled: Enable Tor routing
            auto_start_tor: Automatically start Tor if not running
            socks_port: Custom SOCKS port (default: 9050 + worker_id)
            control_port: Custom control port (default: 9051 + worker_id)
            worker_id: Worker ID for multi-process setup (used for port allocation)
        """
        self.project_root = Path(project_root) if project_root else Path(__file__).parent
        self.tor_bundle = self.project_root / "tor_bundle"
        self.worker_id = worker_id
        
        # Create separate data directory for each worker
        self.tor_data = self.project_root / f"tor_data_worker_{worker_id}"
        self.torrc = self.project_root / f"torrc_worker_{worker_id}"
        
        # Custom ports for this worker (each worker needs 2 ports: SOCKS + Control)
        # Worker 0: 9050 (SOCKS), 9051 (Control)
        # Worker 1: 9052 (SOCKS), 9053 (Control)
        # Worker 2: 9054 (SOCKS), 9055 (Control)
        # Worker 3: 9056 (SOCKS), 9057 (Control)
        self.TOR_SOCKS_PORT = socks_port if socks_port is not None else (self.DEFAULT_SOCKS_PORT + worker_id * 2)
        self.TOR_CONTROL_PORT = control_port if control_port is not None else (self.DEFAULT_CONTROL_PORT + worker_id * 2)
        
        # Proxies configuration for this worker
        self.TOR_PROXIES = {
            "http": f"socks5h://127.0.0.1:{self.TOR_SOCKS_PORT}",
            "https": f"socks5h://127.0.0.1:{self.TOR_SOCKS_PORT}"
        }
        
        self.rotation_interval = rotation_interval
        self.delay_range = delay_range
        self.use_curl_cffi = use_curl_cffi and CURL_CFFI_AVAILABLE
        self.tor_enabled = tor_enabled
        self.auto_start_tor = auto_start_tor
        
        # State tracking
        self.request_counter = 0
        self.current_ip = None
        self.tor_process = None
        self._lock = threading.Lock()  # Thread-safe counter
        
        # Session
        self.session = None
        
        # Initialize
        if self.tor_enabled:
            self._initialize_tor()
            self._create_session()
            self._verify_ip()
        else:
            self._create_session()
            logger.info("Tor mode disabled. Using direct internet connection.")
    
    def _initialize_tor(self):
        """Check if Tor is running, start if necessary."""
        if not STEM_AVAILABLE:
            logger.error("stem library not available. Cannot manage Tor.")
            self.tor_enabled = False
            return
        
        # Check if Tor is already running on our port
        if self._is_tor_running():
            logger.info(f"✓ Tor worker {self.worker_id} is already running on port {self.TOR_SOCKS_PORT}")
            return
        
        # Start Tor if auto_start is enabled
        if self.auto_start_tor:
            logger.info(f"Tor worker {self.worker_id} not detected. Starting Tor on ports {self.TOR_SOCKS_PORT}/{self.TOR_CONTROL_PORT}...")
            self._start_tor()
        else:
            logger.error(f"Tor is not running on port {self.TOR_SOCKS_PORT} and auto_start is disabled.")
            logger.error("Please start Tor manually or enable auto_start_tor.")
            self.tor_enabled = False
    
    def _is_tor_running(self) -> bool:
        """Check if Tor is running on the SOCKS port."""
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            result = sock.connect_ex(('127.0.0.1', self.TOR_SOCKS_PORT))
            return result == 0
        finally:
            sock.close()
    
    def _start_tor(self):
        """Start Tor from tor_bundle with custom ports for this worker."""
        tor_exe = self.tor_bundle / "tor" / "tor.exe"
        
        if not tor_exe.exists():
            logger.error(f"Tor executable not found at {tor_exe}")
            self.tor_enabled = False
            return
        
        # Ensure worker-specific tor_data directory exists
        self.tor_data.mkdir(exist_ok=True)
        
        # Create worker-specific torrc file
        self._create_torrc()
        
        try:
            # Start Tor process
            cmd = [
                str(tor_exe),
                "-f", str(self.torrc)
            ]
            
            self.tor_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            # Wait for Tor to bootstrap
            logger.info(f"Waiting for Tor worker {self.worker_id} to bootstrap...")
            max_wait = 60  # seconds
            waited = 0
            
            while not self._is_tor_running() and waited < max_wait:
                time.sleep(1)
                waited += 1
            
            if self._is_tor_running():
                logger.info(f"✓ Tor worker {self.worker_id} started successfully in {waited}s")
            else:
                logger.error(f"Tor worker {self.worker_id} failed to start within timeout")
                self.tor_enabled = False
                if self.tor_process:
                    self.tor_process.terminate()
                    self.tor_process = None
        
        except Exception as e:
            logger.error(f"Failed to start Tor worker {self.worker_id}: {e}")
            self.tor_enabled = False
    
    def _create_torrc(self):
        """Create worker-specific torrc configuration file."""
        torrc_content = f"""# Tor configuration for worker {self.worker_id}
SOCKSPort {self.TOR_SOCKS_PORT}
ControlPort {self.TOR_CONTROL_PORT}
DataDirectory {self.tor_data.absolute()}
Log notice stdout
CookieAuthentication 1
"""
        with open(self.torrc, 'w') as f:
            f.write(torrc_content)
        logger.debug(f"Created torrc for worker {self.worker_id}: {self.torrc}")
    
    def _create_session(self):
        """Create HTTP session with or without Tor routing."""
        if self.use_curl_cffi:
            # curl_cffi doesn't have a persistent session in the same way
            # We'll use it per-request
            self.session = None
            logger.debug("Using curl_cffi for requests")
        else:
            session = requests.Session()
            
            # Configure proxies
            if self.tor_enabled:
                session.proxies = self.TOR_PROXIES
            
            # Headers
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            })
            
            # Retry strategy
            retry_strategy = Retry(
                total=3,
                backoff_factor=2,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"],
                raise_on_status=False
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            
            self.session = session
            logger.debug("Created requests.Session")
    
    def rotate_ip(self):
        """Rotate Tor exit node to get a new IP."""
        if not self.tor_enabled or not STEM_AVAILABLE:
            return
        
        try:
            with Controller.from_port(port=self.TOR_CONTROL_PORT) as controller:
                controller.authenticate()
                controller.signal(Signal.NEWNYM)
                time.sleep(2)  # Wait for new circuit
                logger.debug("Requested new Tor IP")
                self._verify_ip()
        except Exception as e:
            logger.error(f"IP rotation failed: {e}")
    
    def _verify_ip(self):
        """Check current IP address using external service."""
        if not self.tor_enabled:
            return
        
        try:
            # Use longer timeout for initial Tor circuit establishment
            response = self._get("https://api.ipify.org?format=json", timeout=30)
            if response and response.status_code == 200:
                ip_info = response.json()
                new_ip = ip_info.get('ip')
                
                if new_ip != self.current_ip:
                    logger.info(f"✓ Tor IP: {new_ip}")
                    self.current_ip = new_ip
                else:
                    logger.debug(f"IP unchanged: {new_ip}")
        except Exception as e:
            logger.debug(f"IP verification failed: {e}")
    
    def _get(self, url: str, timeout: int = 60, **kwargs) -> Optional[Any]:
        """Internal GET request with proper proxy configuration."""
        try:
            if self.use_curl_cffi:
                # Use curl_cffi with proxy
                proxies = self.TOR_PROXIES if self.tor_enabled else None
                response = curl_requests.get(
                    url,
                    proxies=proxies,
                    impersonate="chrome120",
                    timeout=timeout,
                    **kwargs
                )
            else:
                # Use requests.Session
                response = self.session.get(url, timeout=timeout, **kwargs)
            
            return response
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None
    
    def get(self, url: str, timeout: int = 60, retry_on_timeout: bool = True, **kwargs):
        """
        Perform GET request with automatic IP rotation and delay.
        
        Args:
            url: URL to fetch
            timeout: Request timeout in seconds
            retry_on_timeout: Rotate IP and retry once on timeout
            **kwargs: Additional arguments for requests
            
        Returns:
            Response object or None
        """
        # Thread-safe counter increment
        with self._lock:
            self.request_counter += 1
            current_count = self.request_counter
        
        # Rotate IP if threshold reached
        if self.tor_enabled and current_count % self.rotation_interval == 0:
            logger.info(f"Rotation threshold reached ({current_count} requests)")
            self.rotate_ip()
        
        # Random delay
        import random
        delay = random.uniform(self.delay_range[0], self.delay_range[1])
        time.sleep(delay)
        
        # Make request
        try:
            if self.use_curl_cffi:
                proxies = self.TOR_PROXIES if self.tor_enabled else None
                response = curl_requests.get(
                    url,
                    proxies=proxies,
                    impersonate="chrome120",
                    timeout=timeout,
                    **kwargs
                )
            else:
                response = self.session.get(url, timeout=timeout, **kwargs)
            
            logger.debug(f"GET {url} → {response.status_code}")
            return response
            
        except Exception as e:
            error_msg = str(e)
            
            # Check if it's a timeout and retry is enabled
            if retry_on_timeout and ('timeout' in error_msg.lower() or 'timed out' in error_msg.lower()):
                logger.warning(f"Timeout on {url[:60]}... Rotating IP and retrying...")
                
                # Rotate to a new circuit
                if self.tor_enabled:
                    self.rotate_ip()
                    time.sleep(3)  # Wait for circuit to stabilize
                
                # Retry once
                try:
                    if self.use_curl_cffi:
                        proxies = self.TOR_PROXIES if self.tor_enabled else None
                        response = curl_requests.get(
                            url,
                            proxies=proxies,
                            impersonate="chrome120",
                            timeout=timeout,
                            **kwargs
                        )
                    else:
                        response = self.session.get(url, timeout=timeout, **kwargs)
                    
                    logger.info(f"✓ Retry successful: {url[:60]}...")
                    return response
                    
                except Exception as retry_error:
                    logger.error(f"Request to {url} failed after retry: {retry_error}")
                    return None
            else:
                logger.error(f"Request to {url} failed: {e}")
                return None
    
    def get_selenium_options(self):
        """Get Selenium ChromeOptions configured for Tor proxy."""
        try:
            from selenium.webdriver.chrome.options import Options
            
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument(
                'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            )
            
            # Configure Tor proxy for Selenium
            if self.tor_enabled:
                chrome_options.add_argument(f'--proxy-server=socks5://127.0.0.1:{self.TOR_SOCKS_PORT}')
                logger.info("Selenium configured to use Tor proxy")
            
            return chrome_options
            
        except ImportError:
            logger.error("Selenium not available")
            return None
    
    def shutdown(self):
        """Shutdown Tor process if we started it."""
        if self.tor_process:
            logger.info("Shutting down Tor process...")
            self.tor_process.terminate()
            try:
                self.tor_process.wait(timeout=10)
                logger.info("✓ Tor process terminated")
            except subprocess.TimeoutExpired:
                self.tor_process.kill()
                logger.warning("Tor process killed (timeout)")
            self.tor_process = None
    
    def close(self):
        """Alias for shutdown() for compatibility."""
        self.shutdown()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.shutdown()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return {
            'total_requests': self.request_counter,
            'current_ip': self.current_ip,
            'tor_enabled': self.tor_enabled,
            'rotations_performed': self.request_counter // self.rotation_interval
        }
