import logging
import json
import time
import datetime
import math
import deprecation
from databricks.vector_search.utils import OAuthTokenUtils
from databricks.vector_search.utils import RequestUtils
from databricks.vector_search.utils import UrlUtils
from mlflow.utils import databricks_utils


class VectorSearchIndex:
    """
    VectorSearchIndex is a helper class that represents a Vector Search Index.

    Those who wish to use this class should not instantiate it directly, but rather use the VectorSearchClient class.
    """
    def __init__(
        self,
        workspace_url,
        index_url,
        name,
        endpoint_name,
        personal_access_token=None,
        service_principal_client_id=None,
        service_principal_client_secret=None,
        # whether or not credentials were explicitly passed in by user in client or inferred by client
        # via mlflow utilities. If passed in by user, continue to use user credentials. If not, can
        # attempt automatic auth refresh for model serving.
        use_user_passed_credentials=False
    ):
        self.workspace_url = workspace_url
        self.index_url = UrlUtils.add_https_if_missing(index_url) \
            if index_url else None
        self.name = name
        self.endpoint_name = endpoint_name
        self.personal_access_token = personal_access_token
        self.service_principal_client_id = service_principal_client_id
        self.service_principal_client_secret = service_principal_client_secret
        if self.personal_access_token and \
                not (self.service_principal_client_id and 
                     self.service_principal_client_secret):
            # In PAT flow, don't use index_url given for DP ingress
            self.index_url = self.workspace_url + f"/api/2.0/vector-search/endpoints/{self.endpoint_name}/indexes/{self.name}"
        self.index_url = self.index_url or (self.workspace_url + f"/api/2.0/vector-search/endpoints/{self.endpoint_name}/indexes/{self.name}") # Fallback to CP
        self._control_plane_oauth_token = None
        self._control_plane_oauth_token_expiry_ts = None
        self._read_oauth_token = None
        self._read_oauth_token_expiry_ts = None
        self._write_oauth_token = None
        self._write_oauth_token_expiry_ts = None
        self._use_user_passed_credentials = use_user_passed_credentials

    def _get_token_for_request(self, write=False, control_plane=False):
        try:
            # automatically refresh auth if not passed in by user and in model serving environment
            if not self._use_user_passed_credentials and databricks_utils.is_in_databricks_model_serving_environment():
                return databricks_utils.get_databricks_host_creds().token
        except Exception as e:
            logging.warning(f"Reading credentials from model serving environment failed with: {e} "
                    f"Defaulting to cached vector search token")

        if self.personal_access_token:  # PAT flow
            return self.personal_access_token
        if self.workspace_url in self.index_url:
            control_plane = True
        if (
            control_plane and
            self._control_plane_oauth_token and
            self._control_plane_oauth_token_expiry_ts and
            self._control_plane_oauth_token_expiry_ts - 100 > time.time()
        ):
            return self._control_plane_oauth_token
        if (
            write and
            not control_plane and
            self._write_oauth_token
            and self._write_oauth_token_expiry_ts
            and self._write_oauth_token_expiry_ts - 100 > time.time()
        ):
            return self._write_oauth_token
        if (
            not write and
            not control_plane and
            self._read_oauth_token
            and self._read_oauth_token_expiry_ts
            and self._read_oauth_token_expiry_ts - 100 > time.time()
        ):
            return self._read_oauth_token
        if self.service_principal_client_id and \
                self.service_principal_client_secret:
            authorization_details = json.dumps([{
                "type": "unity_catalog_permission",
                "securable_type": "table",
                "securable_object_name": self.name,
                "operation": "WriteVectorIndex" if write else "ReadVectorIndex"
            }]) if not control_plane else []
            oauth_token_data = OAuthTokenUtils.get_oauth_token(
                workspace_url=self.workspace_url,
                service_principal_client_id=self.service_principal_client_id,
                service_principal_client_secret=self.service_principal_client_secret,
                authorization_details=authorization_details
            )
            if control_plane:
                self._control_plane_oauth_token = oauth_token_data["access_token"]
                self._control_plane_oauth_token_expiry_ts = time.time() + oauth_token_data["expires_in"]
                return self._control_plane_oauth_token
            if write:
                self._write_oauth_token = oauth_token_data["access_token"]
                self._write_oauth_token_expiry_ts = time.time() + oauth_token_data["expires_in"]
                return self._write_oauth_token
            self._read_oauth_token = oauth_token_data["access_token"]
            self._read_oauth_token_expiry_ts = time.time() + oauth_token_data["expires_in"]
            return self._read_oauth_token
        raise Exception("You must specify service principal or PAT token")

    def upsert(self, inputs):
        """
        Upsert data into the index.

        :param inputs: List of dictionaries to upsert into the index.
        """
        assert type(inputs) == list, "inputs must be of type: List of dictionaries"
        assert all(
            type(i) == dict for i in inputs
        ), "inputs must be of type: List of dicts"
        upsert_payload = {"inputs_json": json.dumps(inputs)}
        return RequestUtils.issue_request(
            url=f"{self.index_url}/upsert-data",
            token=self._get_token_for_request(write=True),
            method="POST",
            json=upsert_payload
        )

    def delete(self, primary_keys):
        """
        Delete data from the index.

        :param primary_keys: List of primary keys to delete from the index.
        """
        assert type(primary_keys) == list, "inputs must be of type: List"
        delete_payload = {"primary_keys": primary_keys}
        return RequestUtils.issue_request(
            url=f"{self.index_url}/delete-data",
            token=self._get_token_for_request(write=True),
            method="DELETE",
            json=delete_payload
        )

    def describe(self):
        """
        Describe the index. This returns metadata about the index.
        """
        return RequestUtils.issue_request(
            url=f"{self.workspace_url}/api/2.0/vector-search/endpoints/{self.endpoint_name}/indexes/{self.name}",
            token=self._get_token_for_request(control_plane=True),
            method="GET",
        )

    def sync(self):
        """
        Sync the index. This is used to sync the index with the source delta table.
        This only works with managed delta sync index with pipeline type="TRIGGERED".
        """
        return RequestUtils.issue_request(
            url=f"{self.workspace_url}/api/2.0/vector-search/endpoints/{self.endpoint_name}/indexes/{self.name}/sync",
            token=self._get_token_for_request(control_plane=True),
            method="POST",
        )

    def similarity_search(
        self,
        columns,
        query_text=None,
        query_vector=None,
        filters=None,
        num_results=5,
        debug_level=1,
        score_threshold=None,
        query_type=None
    ):
        """
        Perform a similarity search on the index. This returns the top K results that are most similar to the query.

        :param columns: List of column names to return in the results.
        :param query_text: Query text to search for.
        :param query_vector: Query vector to search for.
        :param filters: Filters to apply to the query.
        :param num_results: Number of results to return.
        :param debug_level: Debug level to use for the query.
        :param score_threshold: Score threshold to use for the query.
        :param query_type: Query type of this query. Choices are "ANN" and "HYBRID".

        """
        json_data = {
            "num_results": num_results,
            "columns": columns,
            "filters_json": json.dumps(filters) if filters else None,
            "debug_level": debug_level
        }
        if query_text:
            json_data["query"] = query_text
            json_data["query_text"] = query_text
        if query_vector:
            json_data["query_vector"] = query_vector
        if score_threshold:
            json_data["score_threshold"] = score_threshold
        if query_type:
            json_data["query_type"] = query_type

        response = RequestUtils.issue_request(
            url=f"{self.index_url}/query",
            token=self._get_token_for_request(),
            method="GET",
            json=json_data
        )

        out_put = response
        while response["next_page_token"]:
           response = self.__get_next_page(response["next_page_token"])
           out_put["result"]["row_count"] += response["result"]["row_count"]
           out_put["result"]["data_array"] += response["result"]["data_array"]

        out_put.pop("next_page_token", None)
        return out_put

    def wait_until_ready(self, verbose=False, timeout=datetime.timedelta(hours=24)):
        """
        Wait for the index to be online.

        :param bool verbose: Whether to print status messages.
        :param datetime.timedelta timeout: The time allowed until we timeout with an Exception.
        """
                         
        def get_index_state():
            return self.describe()["status"]["detailed_state"]

        start_time = datetime.datetime.now()
        sleep_time_seconds = 30
        # Provisioning states all contain `PROVISIONING`
        # Online states all contain `ONLINE`.
        # Offline states all contain `OFFLINE`.
        index_state = get_index_state()
        while "ONLINE" not in index_state and datetime.datetime.now() - start_time < timeout:
            if "OFFLINE" in index_state:
                raise Exception(f"Index {self.name} is offline")
            if verbose:
                running_time = int(math.floor((datetime.datetime.now() - start_time).total_seconds()))
                print(f"Index {self.name} is in state {index_state}. Time: {running_time}s.")
            time.sleep(sleep_time_seconds)
            index_state = get_index_state()
        if verbose:
            print(f"Index {self.name} is in state {index_state}.")
        if "ONLINE" not in index_state:
            raise Exception(f"Index {self.name} did not become online within timeout of {timeout.total_seconds()}s.")

    def scan(self, num_results = 10, last_primary_key=None):
        """
        Given all the data in the index sorted by primary key, this returns the next
        `num_results` data after the primary key specified by `last_primary_key`.
        If last_primary_key is None , it returns the first `num_results`.

        Please note if there's ongoing updates to the index, the scan results may not be consistent.

        :param num_results: Number of results to return.
        :param last_primary_key: last primary key from previous pagination, it will be used as the exclusive starting primary key.
        """
        json_data = {
            "num_results": num_results,
            "endpoint_name": self.endpoint_name,
        }
        if last_primary_key:
            json_data["last_primary_key"] = last_primary_key

        # TODO(ShengZhan): make this consistent with the rest.
        url =  f"{self.workspace_url}/api/2.0/vector-search/indexes/{self.name}/scan"

        return RequestUtils.issue_request(
            url=url,
            token=self._get_token_for_request(),
            method="GET",
            json=json_data
       )

    @deprecation.deprecated(deprecated_in="0.36", removed_in="0.37",
                            current_version="0.36",
                            details="Use the scan function instead")
    def scan_index(self, num_results = 10, last_primary_key=None):
        return self.scan(num_results, last_primary_key)

    def __get_next_page(self, page_token):
        """
        Get the next page of results from a page token.
        """
        json_data = {
            "page_token": page_token,
            "endpoint_name": self.endpoint_name,
        }
        # TODO(ShengZhan): make this consistent with the rest.
        url =  f"{self.workspace_url}/api/2.0/vector-search/indexes/{self.name}/query-next-page"

        return RequestUtils.issue_request(
            url=url,
            token=self._get_token_for_request(),
            method="GET",
            json=json_data
        )
