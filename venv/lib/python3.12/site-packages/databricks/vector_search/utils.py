import requests
import logging
import os
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from functools import lru_cache
from databricks.vector_search.version import VERSION

class OAuthTokenUtils:

    @staticmethod
    def get_oauth_token(
        workspace_url,
        service_principal_client_id,
        service_principal_client_secret,
        authorization_details=None,
    ):
        authorization_details = authorization_details or []
        url = workspace_url + "/oidc/v1/token"
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data = {
            "grant_type": "client_credentials",
            "scope": "all-apis",
            "authorization_details": authorization_details
        }
        logging.info(f"Issuing request to {url} with data {data} and headers {headers}")
        response = RequestUtils.issue_request(
            url=url,
            auth=(service_principal_client_id, service_principal_client_secret),
            headers=headers,
            method="POST",
            data=data
        )
        return response

@lru_cache(maxsize=64)
def _cached_get_request_session(
        total_retries,
        backoff_factor,
        # To create a new Session object for each process, we use the process id as the cache key.
        # This is to avoid sharing the same Session object across processes, which can lead to issues
        # such as https://stackoverflow.com/q/3724900.
        process_id):
    session = requests.Session()
    retry_strategy = Retry(
        total=total_retries,  # Total number of retries
        backoff_factor=backoff_factor,  # A backoff factor to apply between attempts
        status_forcelist=[429],  # HTTP status codes to retry on
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=50, pool_maxsize=50)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

class RequestUtils:
    session = _cached_get_request_session(
        total_retries=3,
        backoff_factor=1,
        process_id=os.getpid())

    @staticmethod
    def issue_request(url, method, token=None, params=None, json=None, verify=True, auth=None, data=None, headers=None):
        headers = headers or dict()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["X-Databricks-Python-SDK-Version"] = VERSION
        response = RequestUtils.session.request(
            url=url,
            headers=headers,
            method=method,
            params=params,
            json=json,
            verify=verify,
            auth=auth,
            data=data
        )
        try:
            response.raise_for_status()
        except Exception as e:
            logging.warn(f"Error processing request {e}")
            raise Exception(
                f"Response content {response.content}, status_code {response.status_code}"
            )
        return response.json()


class UrlUtils:

    @staticmethod
    def add_https_if_missing(url):
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        return url
