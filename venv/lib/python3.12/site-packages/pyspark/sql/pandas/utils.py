#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from pyspark.loose_version import LooseVersion
from pyspark.errors import PySparkRuntimeError, PySparkImportError


def require_minimum_pandas_version() -> None:
    """Raise ImportError if minimum version of Pandas is not installed"""
    # TODO(HyukjinKwon): Relocate and deduplicate the version specification.
    minimum_pandas_version = "1.0.5"

    try:
        import pandas

        have_pandas = True
    except ImportError as error:
        have_pandas = False
        raised_error = error
    if not have_pandas:
        raise PySparkImportError(
            errorClass="PACKAGE_NOT_INSTALLED",
            messageParameters={
                "package_name": "Pandas",
                "minimum_version": str(minimum_pandas_version),
            },
        ) from raised_error
    if LooseVersion(pandas.__version__) < LooseVersion(minimum_pandas_version):
        raise PySparkImportError(
            errorClass="UNSUPPORTED_PACKAGE_VERSION",
            messageParameters={
                "package_name": "Pandas",
                "minimum_version": str(minimum_pandas_version),
                "current_version": str(pandas.__version__),
            },
        )


def require_minimum_pyarrow_version() -> None:
    """Raise ImportError if minimum version of pyarrow is not installed"""
    # TODO(HyukjinKwon): Relocate and deduplicate the version specification.
    minimum_pyarrow_version = "10.0.0"

    import os

    try:
        import pyarrow

        have_arrow = True
    except ImportError as error:
        have_arrow = False
        raised_error = error
    if not have_arrow:
        raise PySparkImportError(
            errorClass="PACKAGE_NOT_INSTALLED",
            messageParameters={
                "package_name": "PyArrow",
                "minimum_version": str(minimum_pyarrow_version),
            },
        ) from raised_error
    if LooseVersion(pyarrow.__version__) < LooseVersion(minimum_pyarrow_version):
        raise PySparkImportError(
            errorClass="UNSUPPORTED_PACKAGE_VERSION",
            messageParameters={
                "package_name": "PyArrow",
                "minimum_version": str(minimum_pyarrow_version),
                "current_version": str(pyarrow.__version__),
            },
        )
    if os.environ.get("ARROW_PRE_0_15_IPC_FORMAT", "0") == "1":
        raise PySparkRuntimeError(
            errorClass="ARROW_LEGACY_IPC_FORMAT",
            messageParameters={},
        )


# BEGIN-EDGE
def warn_inefficient_columns_for_conversion(spark_schema):
    """
    Warn the inefficient conversion of the DecimalType column in the spark_schema.
    :param spark_schema: the function will only process StructType schema.
    """
    import warnings
    from pyspark.sql.types import DecimalType, StructType

    if not isinstance(spark_schema, StructType):
        return

    decimal_col_names = [
        field.name for field in spark_schema if isinstance(field.dataType, DecimalType)
    ]
    if len(decimal_col_names) > 0:
        warnings.warn(
            "The conversion of DecimalType columns is inefficient and may take a long "
            "time. Column names: [{}] If those columns are not necessary, you may "
            "consider dropping them or converting to primitive types before the "
            "conversion.".format(", ".join(decimal_col_names))
        )


def message_with_direct_cause(excp):
    """
    :param excp: An Exception object
    :return: A string contains str(excp) and optionally "\nDirect cause: " + str(excp.__cause__)
    """
    message = str(excp)
    if excp.__cause__:
        message += "\nDirect cause: " + str(excp.__cause__)
    return message


def _get_pandas_convert_as_arrow_size(pdf):
    """
    Return the rough size of the arrow data size when we the pandas.DataFrame into arrow format
    data, if estimation fails raise exception.

    :param pdf: The pandas.DataFrame to be converted
    """
    import pyarrow as pa
    from distutils.version import LooseVersion

    try:
        if LooseVersion(pa.__version__) >= LooseVersion("0.16"):
            # Try to convert to pyarrow table and get nbytes
            # this approach is accurate, especially for string type column.
            pa_table = pa.Table.from_pandas(pdf, preserve_index=False)
            return pa_table.nbytes
        else:
            raise RuntimeError(
                "The 'pyarrow.Table.nbytes' attribute does not exist in this pyarrow version."
            )
    except Exception:
        # fallback to pandas memory usage estimation
        # `deep=True` is required for non-primitive types such as string type
        return int(pdf.memory_usage(index=False, deep=True).sum())


def estimate_pandas_convert_as_arrow_size(
    pdf, num_sample_blocks=10, min_rows_per_block=10, sample_ratio_per_block=0.0001, seed=1
):
    """
    Estimate the rough size of the arrow data size when we the pandas.DataFrame into arrow format
    data, use block sampling to reduce random memory read.
    Randomly sample a consecutive block of rows in `pdf`, and repeat `num_sample_blocks` times.
    The length of one sample block is `max(min_rows_per_block, pdf_len * sample_ratio_per_block)`.
    """
    import numpy as np

    rng = np.random.RandomState(seed)
    pdf_len = len(pdf)
    rows_per_block = int(max(min_rows_per_block, pdf_len * sample_ratio_per_block))
    if pdf_len <= num_sample_blocks * rows_per_block:
        return _get_pandas_convert_as_arrow_size(pdf)
    else:
        sample_block_size_sum = 0
        for i in range(num_sample_blocks):
            batch_start_pos = rng.randint(0, pdf_len - rows_per_block)
            batch_end_pos = batch_start_pos + rows_per_block
            pdf_sampled = pdf[batch_start_pos:batch_end_pos]
            sample_block_size_sum += _get_pandas_convert_as_arrow_size(pdf_sampled)
        avg_sample_block_size = sample_block_size_sum / num_sample_blocks
        return int(avg_sample_block_size * (pdf_len / rows_per_block))


# END-EDGE
